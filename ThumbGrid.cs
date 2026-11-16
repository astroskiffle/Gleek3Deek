// RetroGleek - the virtualised thumbnail grid
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE). Part of RetroGleek; see Program.cs for the overview.

using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using VBFS = Microsoft.VisualBasic.FileIO.FileSystem;
using VBUI = Microsoft.VisualBasic.FileIO.UIOption;
using VBRecycle = Microsoft.VisualBasic.FileIO.RecycleOption;
using WinTimer = System.Windows.Forms.Timer;

// ====================================================================== thumbnail grid

// Owner-drawn, virtualized grid: only the visible cells are painted, so 100,000 files cost no more than 100.
sealed class ThumbGrid : Control
{
    // thumbnail size: 17 steps of 16 px from 64 to 320 (the size slider and Ctrl + wheel both move along these)
    public const int TileStepMax = 16;
    static int TileLogical(int step) { return 64 + 16 * step; }
    static readonly Color Bg = Color.FromArgb(24, 24, 24);

    public event Action<int> OpenRequested;
    public event Action<Point, int> ContextRequested;      // client point, hit index (-1 = empty space)
    public event Action SelectionChanged;
    public event Action<string, string> Loaded;            // folder, error message (null = ok)
    public event Action ListChanged;                       // the visible list changed (sort or filter)
    public event Action FilterCleared;                     // the filter was reset because another folder was opened
    public event Action TileStepChanged;                   // the thumbnail size changed (slider or Ctrl + wheel)

    public string Dir, Error;
    public bool Scanning;
    public List<Item> Items = new List<Item>();            // what is shown: sorted, then filtered
    public List<string> Paths = new List<string>();
    public int SortKey;                                    // 0 name, 1 date modified, 2 size, 3 type
    public bool SortDesc;
    public int FocusIndex { get { return fidx; } }
    public int TotalCount { get { return all.Count; } }
    public string Filter { get { return filter; } }
    public bool FilterActive { get { return filter.Length > 0 || showMode != 0; } }

    public string SortLabel
    {
        get
        {
            switch (SortKey)
            {
                case 1: return "date modified, " + (SortDesc ? "newest first" : "oldest first");
                case 2: return "size, " + (SortDesc ? "largest first" : "smallest first");
                case 3: return "type" + (SortDesc ? ", reversed" : "");
                case 4: return "platform" + (SortDesc ? ", reversed" : "");
                case 5: return "dimensions, " + (SortDesc ? "largest first" : "smallest first");
                case 6: return "frames, " + (SortDesc ? "most first" : "fewest first");
                case 7: return "colours, " + (SortDesc ? "most first" : "fewest first");
                case 8: return "status" + (SortDesc ? ", reversed" : "");
                case 9: return "rating, " + (SortDesc ? "most stars first" : "fewest stars first");
                case 10: return "colour label" + (SortDesc ? ", reversed" : "");
                default: return "name" + (SortDesc ? ", reversed" : "");
            }
        }
    }

    // Thumbnail size step, 0..TileStepMax. Existing thumbnails are redrawn scaled at once; sharp ones are
    // generated when the size has rested for a moment, so dragging the slider stays smooth.
    // The size slider's step for the view that is showing: thumbnails and the Details list each keep their own.
    public int TileStep
    {
        get { return detailsMode ? rowStep : tileStep; }
        set
        {
            int n = Math.Max(0, Math.Min(TileStepMax, value));
            if (n == TileStep) return;
            int first = (scrollY / Math.Max(1, cellH)) * cols;           // keep the same pictures in view
            if (detailsMode) rowStep = n; else tileStep = n;
            Relayout();
            SetScroll((first / cols) * cellH);
            HideTip();
            Invalidate();
            tileTimer.Stop(); tileTimer.Start();
            var h = TileStepChanged;
            if (h != null) h();
        }
    }

    // dimensions / platform under each tile's name
    public bool ShowDetails
    {
        get { return showDetails; }
        set
        {
            if (value == showDetails) return;
            showDetails = value;
            int first = (scrollY / Math.Max(1, cellH)) * cols;
            Relayout();
            SetScroll((first / cols) * cellH);
            Schedule(); Invalidate();
        }
    }

    readonly VScrollBar vs = new VScrollBar();
    readonly ThumbCache cache = new ThumbCache();
    readonly ThumbService svc;
    readonly Dictionary<string, long> failed = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, string> failMsg = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    readonly WinTimer repaintTimer = new WinTimer { Interval = 40 };
    readonly WinTimer hoverTimer = new WinTimer { Interval = 500 };
    readonly WinTimer tileTimer = new WinTimer { Interval = 250 };
    readonly ToolTip tip = new ToolTip();
    readonly Font font = new Font("Segoe UI", 9f);
    readonly Font small = new Font("Segoe UI", 8f);
    readonly Font big = new Font("Segoe UI", 12f);
    readonly SolidBrush selBrush = new SolidBrush(Color.FromArgb(90, 60, 130, 230));
    readonly Pen selPen = new Pen(Color.FromArgb(60, 130, 230));
    readonly SolidBrush placeBrush = new SolidBrush(Color.FromArgb(40, 40, 40));

    List<Item> all = new List<Item>();                     // everything in the folder (sorted)
    string filter = "";
    Predicate<string> matcher;                             // null = show everything
    int tileStep = 6, rowStep = 4, tile, pad, cellW, cellH, cols = 1, total, scrollY, anc = -1, fidx = -1;
    int hoverIdx = -1;
    Point hoverPt;
    volatile int scanGen;
    bool setting, repaintPending, showDetails = true;
    Control host;
    string lastDir;

    // Rescan (auto-refresh): what to restore once the new list arrives
    int restoreGen = -1, restoreScroll;
    HashSet<string> restoreSel;
    string restoreFocus, restoreAnchor;

    // rubber-band selection: drag with the left button to select every tile the rectangle touches
    bool bandArmed, banding;
    Point bandStart;                                       // in content coordinates (y includes the scroll offset)
    Point bandNow;                                         // in client coordinates
    HashSet<Item> bandBase;                                // already selected before the drag (Ctrl adds to it)
    readonly WinTimer bandTimer = new WinTimer { Interval = 30 };
    readonly SolidBrush bandBrush = new SolidBrush(Color.FromArgb(50, 60, 130, 230));

    // drag-and-drop: a drag that starts on an already selected tile carries the selected files (to the folder
    // tree, or to Explorer). A plain click on a selected tile selects just that tile when the button is released.
    bool dragArmed;
    Point dragStart;
    int pressIdx = -1;
    public bool DraggingOut;                               // true while our own drag is in progress

    // ---- Analyse folder: colours, frames and SHA-256 (duplicates) for every picture, read in the background
    sealed class Analysed { public long Stamp; public AuditEntry E; }      // E == null: not a picture after all
    readonly Dictionary<string, Analysed> analysed = new Dictionary<string, Analysed>(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, string> dupOf = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    volatile int analyseGen;
    bool analyseRunning;
    int analyseDone, analyseTotal;
    public bool Analysing { get { return analyseRunning; } }
    public event Action<int, int> AnalyseProgress;           // done, total
    public event Action<int, int, int> AnalyseFinished;      // pictures analysed, could not be opened, duplicates

    AuditEntry AnalysisOf(Item it)
    {
        Analysed a;
        return analysed.TryGetValue(it.Path, out a) && a.Stamp == it.Stamp ? a.E : null;
    }

    bool HasAnalysis(Item it)
    {
        Analysed a;
        return analysed.TryGetValue(it.Path, out a) && a.Stamp == it.Stamp;
    }

    public void StartAnalysis()
    {
        if (analyseRunning || Dir == null) return;
        var work = new List<KeyValuePair<string, long>>();
        foreach (Item it in all) if (!it.Offline && !HasAnalysis(it)) work.Add(new KeyValuePair<string, long>(it.Path, it.Stamp));
        int gen = ++analyseGen;
        analyseRunning = true; analyseDone = 0; analyseTotal = work.Count;
        Control h = FindForm();
        ThreadPool.QueueUserWorkItem(delegate
        {
            var batch = new List<KeyValuePair<KeyValuePair<string, long>, AuditEntry>>();
            int last = Environment.TickCount;
            for (int k = 0; k < work.Count; k++)
            {
                if (gen != analyseGen) return;                  // stopped, or another folder was opened
                AuditEntry e = null;
                try { e = FolderAudit.Analyse(work[k].Key); } catch (Exception) { }
                batch.Add(new KeyValuePair<KeyValuePair<string, long>, AuditEntry>(work[k], e));
                if (Environment.TickCount - last > 250 || k == work.Count - 1)
                {
                    last = Environment.TickCount;
                    var send = batch; batch = new List<KeyValuePair<KeyValuePair<string, long>, AuditEntry>>();
                    int done = k + 1;
                    Util.Post(h, delegate { AnalysisBatch(gen, send, done); });
                }
            }
            Util.Post(h, delegate { AnalysisFinished(gen); });
        });
        var p = AnalyseProgress; if (p != null) p(0, analyseTotal);
    }

    public void StopAnalysis()
    {
        if (!analyseRunning) return;
        analyseGen++;
        analyseRunning = false;
        RecomputeDuplicates();
        Invalidate();
        var f = AnalyseFinished; if (f != null) f(-1, 0, 0);    // -1: stopped before the end
    }

    void AnalysisBatch(int gen, List<KeyValuePair<KeyValuePair<string, long>, AuditEntry>> batch, int done)
    {
        if (gen != analyseGen) return;
        foreach (KeyValuePair<KeyValuePair<string, long>, AuditEntry> r in batch)
        {
            analysed[r.Key.Key] = new Analysed { Stamp = r.Key.Value, E = r.Value };
            AuditEntry e = r.Value;
            if (e != null && e.Status == "OK")                  // also tells platform and dimensions
                known[r.Key.Key] = new Known { Stamp = r.Key.Value, W = e.W, H = e.H, Note = e.Kind == "Standard" ? null : e.Platform, FileStars = e.FileStars };
        }
        analyseDone = done;
        RecomputeDuplicates();
        Invalidate();
        var p = AnalyseProgress; if (p != null) p(done, analyseTotal);
    }

    void AnalysisFinished(int gen)
    {
        if (gen != analyseGen) return;
        analyseRunning = false;
        RecomputeDuplicates();
        int n = 0, bad = 0;
        foreach (Item it in all)
        {
            AuditEntry e = AnalysisOf(it);
            if (e == null) continue;
            n++;
            if (e.Status == "Failed") bad++;
        }
        if (SortKey >= 6) SetSort(SortKey, SortDesc);           // sorted by frames / colours / status: sort again, complete
        Invalidate();
        var f = AnalyseFinished; if (f != null) f(n, bad, dupOf.Count);
    }

    // exact copies (same SHA-256) among the listed pictures: every copy after the first (in name order) names it
    void RecomputeDuplicates()
    {
        dupOf.Clear();
        var first = new Dictionary<string, string>();
        var byName = new List<Item>(all);
        byName.Sort(delegate (Item a, Item b) { return Util.NatCmp(a.Name, b.Name); });
        foreach (Item it in byName)
        {
            AuditEntry e = AnalysisOf(it);
            if (e == null || e.Hash == null) continue;
            string f;
            if (first.TryGetValue(e.Hash, out f)) dupOf[it.Path] = f; else first[e.Hash] = it.Name;
        }
    }

    // the Status column: a problem, a duplicate, or nothing
    string StatusText(Item it, int i, out Color colour)
    {
        colour = Color.Gray;
        if (it.Offline) { colour = Color.FromArgb(140, 180, 255); return "Cloud-only (not on this PC)"; }
        AuditEntry e = AnalysisOf(it);
        if (IsFailed(it) || (e != null && e.Status == "Failed"))
        {
            colour = Color.FromArgb(255, 140, 90);
            string why = e != null && e.Error != null ? e.Error : FailureOf(i);
            return "Could not be opened: " + (why ?? "");
        }
        string d;
        if (dupOf.TryGetValue(it.Path, out d)) { colour = Color.FromArgb(230, 200, 110); return "Duplicate of " + d; }
        return "";
    }

    // pictures cut with Ctrl+X (set by the main window); drawn faded until they are pasted or the cut is dropped
    public HashSet<string> CutPaths;
    static readonly ImageAttributes dimAttr = MakeDim();
    static ImageAttributes MakeDim()
    {
        var cm = new ColorMatrix();
        cm.Matrix33 = 0.4f;                                // 40% opacity
        var a = new ImageAttributes();
        a.SetColorMatrix(cm);
        return a;
    }

    bool IsCut(Item it) { return CutPaths != null && CutPaths.Count > 0 && CutPaths.Contains(it.Path); }

    static void Blit(Graphics g, Bitmap b, int x, int y, int w, int h, bool dim)
    {
        if (!dim) g.DrawImage(b, x, y, w, h);
        else g.DrawImage(b, new Rectangle(x, y, w, h), 0, 0, b.Width, b.Height, GraphicsUnit.Pixel, dimAttr);
    }

    // ---- Details view: one row per picture with columns (Name, Type, Platform, Dimensions, Size, Modified, Status)
    bool detailsMode;
    public event Action ColumnsChanged;                    // the header above the grid must be redrawn
    // what the thumbnail workers found out about each picture (kept even when its thumbnail leaves the cache)
    sealed class Known { public long Stamp; public int W, H; public string Note; public int FileStars; }
    bool refilterWhenKnown;                                // Show filter by rating: list again as files' ratings are read
    readonly Dictionary<string, Known> known = new Dictionary<string, Known>(StringComparer.OrdinalIgnoreCase);
    bool resortWhenKnown;                                  // sorted by platform / dimensions: sort again once all are known
    readonly WinTimer resortTimer = new WinTimer { Interval = 800 };

    // the two sizes, for settings.ini
    public int GridStep { get { return tileStep; } set { if (detailsMode) tileStep = Math.Max(0, Math.Min(TileStepMax, value)); else TileStep = value; } }
    public int RowStep { get { return rowStep; } set { if (detailsMode) TileStep = value; else rowStep = Math.Max(0, Math.Min(TileStepMax, value)); } }

    public bool DetailsMode
    {
        get { return detailsMode; }
        set
        {
            if (value == detailsMode) return;
            int first = (scrollY / Math.Max(1, cellH)) * cols;           // keep the same pictures in view
            detailsMode = value;
            HideTip();
            Relayout();
            SetScroll((first / cols) * cellH);
            Schedule(); Invalidate();
            var ts = TileStepChanged;                          // the slider shows this view's own size
            if (ts != null) ts();
        }
    }

    bool KnownInfo(Item it, out int w, out int h, out string note)
    {
        Known k;
        if (known.TryGetValue(it.Path, out k) && k.Stamp == it.Stamp) { w = k.W; h = k.H; note = k.Note; return true; }
        return cache.Info(it.Path, it.Stamp, out w, out h, out note);
    }

    bool IsFailed(Item it)
    {
        long fs;
        return failed.TryGetValue(it.Path, out fs) && fs == it.Stamp;
    }

    // Columns of the Details view: left edge, width, title, sort key (-1 = not sortable), right-aligned
    public sealed class Column { public int X, W, Key; public string Title; public bool Right; }

    public List<Column> Columns()
    {
        int lm = pad / 2, width = Math.Max(1, ClientSize.Width - vs.Width - lm);
        var c = new List<Column>();
        int thumbW = tile + Util.S(10);
        string[] titles = { "Name", "Rating", "Label", "Type", "Platform", "Dimensions", "Frames", "Colours", "Size", "Modified", "Status" };
        int[] keys = { 0, 9, 10, 3, 4, 5, 6, 7, 2, 1, 8 };
        int[] fixedW = { 0, Util.S(70), Util.S(70), Util.S(60), Util.S(146), Util.S(100), Util.S(62), Util.S(76), Util.S(80), Util.S(124), Util.S(200) };
        bool[] right = { false, false, false, false, false, true, true, true, true, true, false };
        int sum = thumbW;
        for (int i = 1; i < fixedW.Length; i++) sum += fixedW[i];
        int nameW = Math.Max(Util.S(160), width - sum);
        int x = lm + thumbW;
        for (int i = 0; i < titles.Length; i++)
        {
            int w = i == 0 ? nameW : fixedW[i];
            c.Add(new Column { X = x, W = w, Key = keys[i], Title = titles[i], Right = right[i] });
            x += w;
        }
        return c;
    }

    // Subfolders switch: also list the pictures in every folder below Dir (hidden / system folders and links skipped)
    public bool Recursive;
    public bool Truncated;                                 // the last subfolder search stopped at MaxRecursive
    public const int MaxRecursive = 20000;
    volatile int scanFound;                                // pictures found so far by a running subfolder search

    // the grid lists pictures from this folder (with the Subfolders switch: also from folders below it)
    public bool Covers(string folder)
    {
        if (Dir == null || folder == null) return false;
        if (Util.SameDir(folder, Dir)) return true;
        return Recursive && folder.StartsWith(Dir.TrimEnd('\\', '/') + "\\", StringComparison.OrdinalIgnoreCase);
    }

    public ThumbGrid()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
        BackColor = Bg; TabStop = true; Dock = DockStyle.Fill;
        vs.Dock = DockStyle.Right;
        vs.ValueChanged += delegate { if (setting) return; scrollY = vs.Value; HideTip(); Schedule(); Invalidate(); };
        Controls.Add(vs);
        Util.Dark(vs);
        svc = new ThumbService(Math.Max(2, Math.Min(4, Environment.ProcessorCount / 2)), OnThumb);
        repaintTimer.Tick += delegate { repaintTimer.Stop(); repaintPending = false; Invalidate(); };
        hoverTimer.Tick += delegate
        {
            hoverTimer.Stop();
            if (Visible && hoverIdx >= 0 && hoverIdx < Items.Count && MouseButtons == MouseButtons.None
                && ClientRectangle.Contains(PointToClient(Control.MousePosition)))
            {
                try { tip.Show(Describe(hoverIdx), this, hoverPt.X + 16, hoverPt.Y + 22, 15000); }
                catch (Exception) { }                                   // a tooltip must never raise an error dialog
            }
        };
        tileTimer.Tick += delegate { tileTimer.Stop(); Schedule(); Invalidate(); };      // size settled: make sharp thumbnails
        bandTimer.Tick += delegate { BandAutoScroll(); };
        resortTimer.Tick += delegate
        {
            resortTimer.Stop();
            bool sortPending = resortWhenKnown && (SortKey == 4 || SortKey == 5 || SortKey == 9);
            bool showPending = refilterWhenKnown && showMode >= 3 && showMode <= 8;
            if (!sortPending && !showPending) return;
            bool needDims = sortPending && SortKey != 9, needRating = (sortPending && SortKey == 9) || showPending, done = true;
            foreach (Item it in all)
            {
                if (it.Offline || IsFailed(it)) continue;
                int w, h; string n;
                if (needDims && !KnownInfo(it, out w, out h, out n)) { done = false; break; }   // still reading
                if (needRating && !RatingKnown(it)) { done = false; break; }
            }
            if (showPending)                                  // rated pictures appear as their ratings are read
            {
                Item fi = FocusItem(), an = AnchorItem();
                Rebuild(fi, an);
                if (done) refilterWhenKnown = false;
            }
            if (sortPending && done)
            {
                resortWhenKnown = false;                      // everything is known: one final, complete sort
                SetSort(SortKey, SortDesc);
                resortWhenKnown = false;
            }
        };
        Relayout();
    }

    // ---------------------------------------------------------------- sorting and filtering

    // natural name order is the tie-breaker for every sort, so the order is always fully determined
    // keys 0..3 can be used on a worker thread; 4 (platform) and 5 (dimensions) need what the thumbnails found
    Comparison<Item> SortComparer(int key, bool desc)
    {
        if (key < 4) return MakeComparer(key, desc);
        if (key == 9 || key == 10)
            return delegate (Item a, Item b)
            {
                Mark ma = MarkOf(a), mb = MarkOf(b);
                int va = key == 9 ? StarsOf(a) : ma == null ? 0 : ma.Label, vb = key == 9 ? StarsOf(b) : mb == null ? 0 : mb.Label;
                int c;
                if ((va == 0) != (vb == 0)) c = va == 0 ? 1 : -1;                                 // unmarked: at the end, either way
                else { c = va.CompareTo(vb); if (desc) c = -c; }
                if (c == 0) c = Util.NatCmp(a.Name, b.Name);
                return c;
            };
        if (key >= 6)
            return delegate (Item a, Item b)
            {
                int c;
                if (key == 8)
                {
                    Color ca, cb;
                    string sa = StatusText(a, -1, out ca), sb = StatusText(b, -1, out cb);
                    if ((sa.Length == 0) != (sb.Length == 0)) c = sa.Length == 0 ? 1 : -1;    // problems / duplicates first
                    else c = string.Compare(sa, sb, StringComparison.OrdinalIgnoreCase);
                    if (desc) c = -c;
                }
                else
                {
                    AuditEntry ea = AnalysisOf(a), eb = AnalysisOf(b);
                    bool ka = ea != null && ea.W > 0, kb = eb != null && eb.W > 0;
                    if (ka != kb) c = ka ? -1 : 1;                                             // not analysed: at the end
                    else if (!ka) c = 0;
                    else
                    {
                        c = key == 6 ? ea.Frames.CompareTo(eb.Frames) : ea.Colours.CompareTo(eb.Colours);
                        if (desc) c = -c;
                    }
                }
                if (c == 0) c = Util.NatCmp(a.Name, b.Name);
                return c;
            };
        return delegate (Item a, Item b)
        {
            int aw, ah, bw, bh; string an, bn;
            bool ka = KnownInfo(a, out aw, out ah, out an), kb = KnownInfo(b, out bw, out bh, out bn);
            int c;
            if (ka != kb) c = ka ? -1 : 1;                                   // not read yet: at the end, either way
            else
            {
                if (key == 4)
                {
                    string pa = ka ? (an ?? "PC (standard image)") : "", pb = kb ? (bn ?? "PC (standard image)") : "";
                    c = string.Compare(pa, pb, StringComparison.OrdinalIgnoreCase);
                }
                else c = ((long)aw * ah).CompareTo((long)bw * bh);
                if (desc && ka && kb) c = -c;
            }
            if (c == 0) c = Util.NatCmp(a.Name, b.Name);
            return c;
        };
    }

    static Comparison<Item> MakeComparer(int key, bool desc)
    {
        return delegate (Item a, Item b)
        {
            int c = 0;
            switch (key)
            {
                case 1: c = a.Modified.CompareTo(b.Modified); break;
                case 2: c = a.Size.CompareTo(b.Size); break;
                case 3: c = string.CompareOrdinal(a.Ext, b.Ext); break;
            }
            if (key != 0 && desc) c = -c;
            if (c == 0)
            {
                c = Util.NatCmp(a.Name, b.Name);
                if (key == 0 && desc) c = -c;
            }
            return c;
        };
    }

    // "koa 2"  = names containing both "koa" and "2";   "*.scr", "img?"  = wildcards (* any text, ? one character)
    static Predicate<string> BuildMatcher(string text)
    {
        if (text.Length == 0) return null;
        var terms = new List<Predicate<string>>();
        foreach (string t in text.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (t.IndexOfAny(new[] { '*', '?' }) >= 0)
            {
                var re = new Regex("^" + Regex.Escape(t).Replace("\\*", ".*").Replace("\\?", ".") + "$",
                                   RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
                terms.Add(delegate (string n) { return re.IsMatch(n); });
            }
            else
            {
                string needle = t;
                terms.Add(delegate (string n) { return n.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0; });
            }
        }
        return delegate (string n)
        {
            foreach (Predicate<string> p in terms) if (!p(n)) return false;
            return true;
        };
    }

    List<Item> Filtered()
    {
        if (matcher == null && showMode == 0) return all;
        Predicate<string> m = matcher;
        int sm = showMode;
        return all.FindAll(delegate (Item i) { return (m == null || m(i.Name)) && ShowMatches(i, sm); });
    }

    // ---------------------------------------------------------------- marks (ratings, colour labels, tag)

    // The Show pull-down: 0 all, 1 tagged, 2 not tagged, 3..7 = 1..5 stars or more, 8 no rating,
    // 9..13 = colour label 1..5, 14 no label
    public static readonly string[] ShowNames =
    {
        "All", "Tagged", "Not tagged",
        "\u2605 or more", "\u2605\u2605 or more", "\u2605\u2605\u2605 or more", "\u2605\u2605\u2605\u2605 or more", "\u2605\u2605\u2605\u2605\u2605",
        "No rating", "Red", "Yellow", "Green", "Blue", "Purple", "No label"
    };
    int showMode;

    public int ShowMode
    {
        get { return showMode; }
        set
        {
            int v = Math.Max(0, Math.Min(ShowNames.Length - 1, value));
            if (v == showMode) return;
            Item fi = FocusItem(), an = AnchorItem();
            showMode = v;
            refilterWhenKnown = v >= 3 && v <= 8;              // by rating: photos' own ratings are read in the background
            Rebuild(fi, an);
        }
    }

    public Mark MarkOf(Item it) { return it == null || it.Offline ? null : Marks.Get(it.Path, it.Size, it.Modified); }

    // the star rating stored in the file itself (Windows, Lightroom ...), as read with its thumbnail; 0 = none / not yet read
    public int FileStarsOf(Item it)
    {
        Known k;
        return it != null && known.TryGetValue(it.Path, out k) && k.Stamp == it.Stamp ? k.FileStars : 0;
    }

    // the rating that counts: yours, or else the file's own
    public int StarsOf(Item it)
    {
        Mark m = MarkOf(it);
        return m != null && m.Stars > 0 ? m.Stars : FileStarsOf(it);
    }

    // true when the file's own rating is known (or it can't have one)
    bool RatingKnown(Item it)
    {
        if (it.Offline || (!FileRating.MayHold(it.Path) && !WinCodec.Claims(it.Path)) || IsFailed(it)) return true;
        Known k;
        return known.TryGetValue(it.Path, out k) && k.Stamp == it.Stamp;
    }

    bool ShowMatches(Item it, int sm)
    {
        if (sm == 0) return true;
        Mark m = MarkOf(it);
        int stars = StarsOf(it), label = m == null ? 0 : m.Label;
        bool tag = m != null && m.Tag;
        if (sm == 1) return tag;
        if (sm == 2) return !tag;
        if (sm >= 3 && sm <= 7) return stars >= sm - 2;
        if (sm == 8) return stars == 0;
        if (sm >= 9 && sm <= 13) return label == sm - 8;
        return label == 0;
    }

    // after marking: redraw, and with a Show filter re-check which pictures belong in the list
    // (a picture that no longer matches leaves it; the focus stays at the same place in the list)
    public void MarksChanged()
    {
        if (showMode == 0) { Invalidate(); return; }
        int at = fidx;
        Item fi = FocusItem(), an = AnchorItem();
        Rebuild(fi, an);
        if (fidx < 0 && Items.Count > 0 && at >= 0) SelectOnly(Math.Min(at, Items.Count - 1));
    }

    public int CountTagged()
    {
        int n = 0;
        foreach (Item it in all) { Mark m = MarkOf(it); if (m != null && m.Tag) n++; }
        return n;
    }

    // Edit > Select tagged: exactly the tagged pictures in the current view
    public void SelectTagged()
    {
        int first = -1;
        for (int i = 0; i < Items.Count; i++)
        {
            Mark m = MarkOf(Items[i]);
            Items[i].Sel = m != null && m.Tag;
            if (Items[i].Sel && first < 0) first = i;
        }
        anc = fidx = first;
        if (first >= 0) EnsureVisible(first);
        Changed();
    }

    // after marking one picture: the next one becomes the only selection (auto-advance)
    public void SelectNext()
    {
        if (fidx >= 0 && fidx + 1 < Items.Count) SelectOnly(fidx + 1);
    }

    Item FocusItem() { return fidx >= 0 && fidx < Items.Count ? Items[fidx] : null; }
    Item AnchorItem() { return anc >= 0 && anc < Items.Count ? Items[anc] : null; }

    // re-derive the visible list from `all`, keeping focus and anchor on the same pictures
    void Rebuild(Item fi, Item an)
    {
        Items = Filtered();
        if (matcher != null || showMode != 0)
        {
            var visible = new HashSet<Item>(Items);                       // a hidden picture is never left selected
            foreach (Item it in all) if (!visible.Contains(it)) it.Sel = false;
        }
        Paths = new List<string>(Items.Count);
        foreach (Item it in Items) Paths.Add(it.Path);
        fidx = fi == null ? -1 : Items.IndexOf(fi);
        anc = an == null ? -1 : Items.IndexOf(an);
        Relayout();
        if (fidx >= 0) EnsureVisible(fidx);
        Schedule(); Invalidate();
        var h = ListChanged;
        if (h != null) h();
        Changed();
    }

    public void SetSort(int key, bool desc)
    {
        Item fi = FocusItem(), an = AnchorItem();
        SortKey = key; SortDesc = desc;
        all.Sort(SortComparer(key, desc));
        resortWhenKnown = key == 4 || key == 5 || key == 9;
        if (key >= 6 && key <= 7 && !analyseRunning) { bool any = false; foreach (Item it in all) if (!it.Offline && !HasAnalysis(it)) { any = true; break; } if (any) StartAnalysis(); }
        Rebuild(fi, an);
        var cc = ColumnsChanged; if (cc != null) cc();
    }

    public void SetFilter(string text)
    {
        text = (text ?? "").Trim();
        if (text == filter) return;
        Item fi = FocusItem(), an = AnchorItem();
        filter = text;
        matcher = BuildMatcher(text);
        Rebuild(fi, an);
    }

    // ---------------------------------------------------------------- folder scan (background thread)

    public void Load(string dir, string selectPath, int hint)
    {
        int gen = ++scanGen;
        Scanning = true;
        host = FindForm();
        Control h = host;
        int sortKey = SortKey; bool sortDesc = SortDesc;
        bool rec = Recursive;
        scanFound = 0;
        ThreadPool.QueueUserWorkItem(delegate
        {
            var list = new List<Item>();
            string err = null;
            bool trunc = false;
            try
            {
                if (!rec) { if (!AddFiles(dir, list, gen, int.MaxValue)) return; }
                else
                {
                    // depth-first through the folders below dir; one unreadable folder is skipped, not fatal
                    var stack = new Stack<string>();
                    stack.Push(dir);
                    int lastPing = Environment.TickCount;
                    while (stack.Count > 0)
                    {
                        if (gen != scanGen) return;
                        string d = stack.Pop();
                        try { if (!AddFiles(d, list, gen, MaxRecursive)) return; }
                        catch (Exception) { if (Util.SameDir(d, dir)) throw; }
                        if (list.Count >= MaxRecursive) { trunc = true; break; }
                        try
                        {
                            var subs = new List<string>();
                            foreach (DirectoryInfo sd in new DirectoryInfo(d).EnumerateDirectories())
                            {
                                if ((sd.Attributes & (FileAttributes.Hidden | FileAttributes.System | FileAttributes.ReparsePoint)) != 0) continue;
                                subs.Add(sd.FullName);
                            }
                            subs.Sort(delegate (string a, string b) { return Util.NatCmp(Path.GetFileName(b), Path.GetFileName(a)); });
                            foreach (string sd in subs) stack.Push(sd);              // reversed, so they come off in name order
                        }
                        catch (Exception) { }                                         // access denied, removed meanwhile ...
                        scanFound = list.Count;
                        if (Environment.TickCount - lastPing > 300)
                        {
                            lastPing = Environment.TickCount;
                            Control hh = h;
                            Util.Post(hh, delegate { if (gen == scanGen) Invalidate(); });   // shows the running count
                        }
                    }
                }
                list.Sort(MakeComparer(sortKey >= 4 ? 0 : sortKey, sortDesc));   // platform / dimensions: sorted on the UI thread
            }
            catch (Exception ex) { err = ex.Message; list.Clear(); }
            if (gen != scanGen) return;
            Util.Post(h, delegate { if (gen == scanGen) Truncated = trunc; Apply(gen, dir, list, err, selectPath, hint); });
        });
    }

    // adds the listed pictures of one folder; false if a newer scan took over (worker thread)
    bool AddFiles(string dir, List<Item> list, int gen, int max)
    {
        foreach (FileInfo fi in new DirectoryInfo(dir).EnumerateFiles())
        {
            if (gen != scanGen) return false;                 // superseded by a newer request
            FileAttributes a = fi.Attributes;
            if ((a & FileAttributes.Hidden) != 0 || !Util.Listed(fi.Extension)) continue;
            list.Add(new Item
            {
                Path = fi.FullName, Name = fi.Name, Ext = fi.Extension.ToLowerInvariant(), Size = fi.Length,
                Modified = fi.LastWriteTimeUtc.Ticks,
                Stamp = fi.LastWriteTimeUtc.Ticks ^ fi.Length,
                Offline = (a & Util.CloudMask) != 0
            });
            if (list.Count >= max) break;
        }
        return true;
    }

    // Reads the same folder again but keeps the selection, focus and scroll position (used by auto-refresh)
    public void Rescan()
    {
        if (Dir == null) return;
        var sel = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (Item it in Items) if (it.Sel) sel.Add(it.Path);
        Item f = FocusItem(), a = AnchorItem();
        string dir = Dir;
        Load(dir, null, -1);
        restoreGen = scanGen;
        restoreSel = sel; restoreScroll = scrollY;
        restoreFocus = f != null ? f.Path : null; restoreAnchor = a != null ? a.Path : null;
    }

    void Apply(int gen, string dir, List<Item> list, string err, string selectPath, int hint)
    {
        if (gen != scanGen) return;
        Scanning = false;
        bool newDir = !Util.SameDir(dir, lastDir);
        Dir = dir; all = list; Error = err;
        if (SortKey >= 4) { all.Sort(SortComparer(SortKey, SortDesc)); resortWhenKnown = SortKey <= 5 || SortKey == 9; }
        refilterWhenKnown = showMode >= 3 && showMode <= 8;
        bool cleared = false;
        if (newDir) StopAnalysis();                                                          // results stay, for when you come back
        if (newDir && filter.Length > 0) { filter = ""; matcher = null; cleared = true; }   // a filter belongs to one folder
        if (!newDir) { failed.Clear(); failMsg.Clear(); }                                    // refresh = try failed pictures again
        Items = Filtered();
        Paths = new List<string>(Items.Count);
        foreach (Item it in Items) Paths.Add(it.Path);
        anc = fidx = -1;
        int sel = selectPath == null ? -1 : IndexOfPath(selectPath, -1);
        if (sel < 0 && hint >= 0 && Items.Count > 0) sel = Math.Min(hint, Items.Count - 1);
        if (newDir) scrollY = 0;
        lastDir = dir;
        bool restore = gen == restoreGen && !newDir && restoreSel != null;
        if (restore)
        {
            foreach (Item it in Items) it.Sel = restoreSel.Contains(it.Path);
            fidx = restoreFocus == null ? -1 : IndexOfPath(restoreFocus, -1);
            anc = restoreAnchor == null ? -1 : IndexOfPath(restoreAnchor, -1);
            scrollY = restoreScroll;
        }
        restoreGen = -1; restoreSel = null;
        EndBand();
        Relayout();
        if (restore) Changed();
        else if (sel >= 0) SelectOnly(sel); else Changed();
        Schedule();
        Invalidate();
        var h = Loaded;
        if (h != null) h(dir, err);
        if (cleared) { var fc = FilterCleared; if (fc != null) fc(); }
    }

    public int IndexOfPath(string path, int hint)
    {
        if (hint >= 0 && hint < Items.Count && string.Equals(Items[hint].Path, path, StringComparison.OrdinalIgnoreCase)) return hint;
        return Items.FindIndex(x => string.Equals(x.Path, path, StringComparison.OrdinalIgnoreCase));
    }

    // ---------------------------------------------------------------- thumbnails

    void Schedule()
    {
        host = FindForm();
        int n = Items.Count;
        var jobs = new List<ThumbJob>();
        if (n > 0 && cellH > 0)
        {
            int v0 = (scrollY / cellH) * cols;
            int v1 = Math.Min(n - 1, ((scrollY + ClientSize.Height) / cellH + 1) * cols - 1);
            int p0 = Math.Max(0, v0 - 2 * cols), p1 = Math.Min(n - 1, v1 + 3 * cols);
            for (int i = v0; i <= v1; i++) Want(i, jobs);             // what's on screen first
            for (int i = v1 + 1; i <= p1; i++) Want(i, jobs);         // then a little ahead
            for (int i = v0 - 1; i >= p0; i--) Want(i, jobs);         // then a little behind
            if (SortKey == 4 || SortKey == 5)                          // sorted by platform / dimensions: read the rest too
                for (int i = 0; i < n; i++)
                {
                    if (i >= p0 && i <= p1) continue;
                    Item it = Items[i];
                    int w, h; string nt;
                    if (it.Offline || IsFailed(it) || KnownInfo(it, out w, out h, out nt)) continue;
                    jobs.Add(new ThumbJob { Path = it.Path, Size = tile, Stamp = it.Stamp });
                }
            if (SortKey == 9 || (showMode >= 3 && showMode <= 8))      // by rating: read the photos' own ratings too
            {
                var queued = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (ThumbJob qj in jobs) queued.Add(qj.Path);
                foreach (Item it in all)                               // (all, not just the list: a filter may hide them)
                {
                    if (RatingKnown(it) || queued.Contains(it.Path)) continue;
                    if (jobs.Count > 4000) break;
                    jobs.Add(new ThumbJob { Path = it.Path, Size = tile, Stamp = it.Stamp });
                }
            }
        }
        svc.Replace(jobs);
    }

    void Want(int i, List<ThumbJob> jobs)
    {
        Item it = Items[i];
        if (it.Offline || cache.Has(it.Path, it.Stamp, tile)) return;
        long fs;
        if (failed.TryGetValue(it.Path, out fs) && fs == it.Stamp) return;
        jobs.Add(new ThumbJob { Path = it.Path, Size = tile, Stamp = it.Stamp });
    }

    void OnThumb(ThumbJob j, ThumbResult r)    // worker thread
    {
        if (!Util.Post(host, delegate { Thumbed(j, r); }) && r.Bmp != null) r.Bmp.Dispose();
    }

    void Thumbed(ThumbJob j, ThumbResult r)
    {
        if (r.Bmp != null) known[j.Path] = new Known { Stamp = j.Stamp, W = r.W, H = r.H, Note = r.Note, FileStars = r.FileStars };
        if (resortWhenKnown || refilterWhenKnown) { resortTimer.Stop(); resortTimer.Start(); }
        if (r.Bmp == null) { failed[j.Path] = j.Stamp; failMsg[j.Path] = r.Error ?? "unknown error"; }
        else if (j.Size != tile) r.Bmp.Dispose();
        else cache.Put(j.Path, j.Stamp, j.Size, r);
        if (!repaintPending) { repaintPending = true; repaintTimer.Start(); }   // coalesce repaints
    }

    // why a picture has no thumbnail (null = it has one, or hasn't been tried yet)
    public string FailureOf(int i)
    {
        if (i < 0 || i >= Items.Count) return null;
        Item it = Items[i];
        if (it.Offline) return "Cloud placeholder: the file is not stored on this PC.";
        long fs; string msg;
        if (failed.TryGetValue(it.Path, out fs) && fs == it.Stamp && failMsg.TryGetValue(it.Path, out msg)) return msg;
        return null;
    }

    string Describe(int i)
    {
        Item it = Items[i];
        var sb = new System.Text.StringBuilder();
        sb.Append(it.Name);
        if (Recursive && Dir != null)
        {
            string folder = System.IO.Path.GetDirectoryName(it.Path);
            string rel = Util.SameDir(folder, Dir) ? "(this folder)" : folder.Substring(Math.Min(folder.Length, Dir.TrimEnd('\\').Length + 1));
            sb.Append("\nIn: ").Append(rel);
        }
        sb.Append("\nSize: ").Append(Util.FmtSize(it.Size));
        sb.Append("\nModified: ").Append(new DateTime(it.Modified, DateTimeKind.Utc).ToLocalTime().ToString("yyyy-MM-dd HH:mm"));
        int w, h; string note;
        if (cache.Info(it.Path, it.Stamp, out w, out h, out note))
        {
            sb.Append("\nDimensions: ").Append(w).Append(" x ").Append(h);
            if (note != null) sb.Append("\nPlatform: ").Append(note);
        }
        string why = FailureOf(i);
        if (why != null) sb.Append("\nNo thumbnail: ").Append(why);
        return sb.ToString();
    }

    void HideTip()
    {
        hoverTimer.Stop();
        try { tip.Hide(this); } catch (Exception) { }
    }

    // ---------------------------------------------------------------- layout / scrolling

    void Relayout()
    {
        int W = Math.Max(1, ClientSize.Width - vs.Width), H = Math.Max(1, ClientSize.Height);
        pad = Util.S(8);
        if (detailsMode)
        {
            // one picture per row; the Size slider sets the row's thumbnail from 24 to 88 pixels
            tile = Util.S(24 + 4 * rowStep);
            cellH = Math.Max(tile, font.Height) + Util.S(6);
            cellW = Math.Max(1, W - pad);
            cols = 1;
        }
        else
        {
            tile = Util.S(TileLogical(tileStep));
            cellW = tile + 2 * pad; cellH = pad + tile + pad / 2 + font.Height + (showDetails ? small.Height : 0) + pad;
            cols = Math.Max(1, (W - pad) / cellW);
        }
        int rows = (Items.Count + cols - 1) / cols;
        total = rows * cellH + pad;
        scrollY = Math.Max(0, Math.Min(scrollY, Math.Max(0, total - H)));
        setting = true;
        try
        {
            vs.Minimum = 0;
            vs.SmallChange = Math.Max(1, cellH / 3);
            vs.LargeChange = H;
            vs.Maximum = Math.Max(total, 1) - 1;
            vs.Enabled = total > H;
            vs.Value = Math.Min(scrollY, vs.Maximum);
        }
        finally { setting = false; }
        var cc = ColumnsChanged;
        if (cc != null) cc();
    }

    void SetScroll(int v)
    {
        v = Math.Max(0, Math.Min(Math.Max(0, total - ClientSize.Height), v));
        if (v == scrollY) return;
        scrollY = v;
        HideTip();
        setting = true;
        try { vs.Value = Math.Min(v, vs.Maximum); } finally { setting = false; }
        Schedule(); Invalidate();
    }

    void EnsureVisible(int i)
    {
        if (i < 0 || i >= Items.Count) return;
        int top = (i / cols) * cellH + pad / 2, bottom = top + cellH;
        if (top < scrollY) SetScroll(top - pad / 2);
        else if (bottom > scrollY + ClientSize.Height) SetScroll(bottom - ClientSize.Height + pad / 2);
    }

    void ChangeTile(int dir) { TileStep = TileStep + dir; }

    // ---------------------------------------------------------------- selection

    public List<int> SelectedIndices()
    {
        var r = new List<int>();
        for (int i = 0; i < Items.Count; i++) if (Items[i].Sel) r.Add(i);
        return r;
    }

    void Changed()
    {
        Invalidate();
        var h = SelectionChanged;
        if (h != null) h();
    }

    void ClearAll() { foreach (Item it in Items) it.Sel = false; }

    public void SelectAllItems()
    {
        if (Items.Count == 0) return;
        foreach (Item it in Items) it.Sel = true;
        if (fidx < 0) fidx = anc = 0;
        Changed();
    }

    // Ctrl+I: selects exactly the pictures that were not selected (in the current, filtered view)
    public void InvertSelection()
    {
        if (Items.Count == 0) return;
        int first = -1;
        for (int i = 0; i < Items.Count; i++)
        {
            Items[i].Sel = !Items[i].Sel;
            if (Items[i].Sel && first < 0) first = i;
        }
        anc = fidx = first;
        if (first >= 0) EnsureVisible(first);
        Changed();
    }

    public void SelectOnly(int i)
    {
        if (i < 0 || i >= Items.Count) return;
        ClearAll();
        Items[i].Sel = true;
        anc = fidx = i;
        EnsureVisible(i);
        Changed();
    }

    void SelectRange(int a, int b)
    {
        ClearAll();
        for (int i = Math.Min(a, b); i <= Math.Max(a, b); i++) Items[i].Sel = true;
        fidx = b;
        EnsureVisible(b);
        Changed();
    }

    int HitTest(Point p)
    {
        int lm = pad / 2;
        if (p.X < lm || p.Y < 0) return -1;
        int c = (p.X - lm) / cellW;
        if (c >= cols) return -1;
        int i = ((p.Y + scrollY) / cellH) * cols + c;
        return i >= 0 && i < Items.Count ? i : -1;
    }

    // ---------------------------------------------------------------- painting

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(Bg);
        if (Items.Count == 0)
        {
            string m = Scanning ? (Recursive ? "Searching subfolders...\n" + scanFound + " pictures found so far" : "Loading...") : Error != null ? "Can't open this folder\n" + Error
                     : Dir == null ? "Select a folder on the left"
                     : FilterActive && all.Count > 0 ? "No pictures match the filter" : "No images in this folder";
            g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
            using (var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                g.DrawString(m, big, Brushes.Gray, new RectangleF(0, 0, ClientSize.Width - vs.Width, ClientSize.Height), sf);
            return;
        }
        int lm = pad / 2;
        int r0 = scrollY / cellH, r1 = (scrollY + ClientSize.Height) / cellH;
        g.InterpolationMode = InterpolationMode.NearestNeighbor;
        for (int r = r0; r <= r1; r++)
            for (int c = 0; c < cols; c++)
            {
                int i = r * cols + c;
                if (i >= Items.Count) break;
                var rc = new Rectangle(lm + c * cellW, r * cellH - scrollY + pad / 2, cellW, cellH);
                if (rc.IntersectsWith(e.ClipRectangle)) DrawCell(g, i, rc);
            }
        if (banding)
        {
            Rectangle br = BandRect();
            br.Offset(0, -scrollY);
            g.FillRectangle(bandBrush, br);
            g.DrawRectangle(selPen, br.X, br.Y, Math.Max(0, br.Width - 1), Math.Max(0, br.Height - 1));
        }
    }

    // ---------------------------------------------------------------- rubber-band selection

    Rectangle BandRect()                                   // content coordinates
    {
        int x2 = bandNow.X, y2 = bandNow.Y + scrollY;
        return Rectangle.FromLTRB(Math.Min(bandStart.X, x2), Math.Min(bandStart.Y, y2), Math.Max(bandStart.X, x2), Math.Max(bandStart.Y, y2));
    }

    void UpdateBand()
    {
        Rectangle br = BandRect();
        int lm = pad / 2, first = -1;
        for (int i = 0; i < Items.Count; i++)
        {
            int r = i / cols, c = i % cols;
            var cell = new Rectangle(lm + c * cellW + pad, r * cellH + pad / 2 + pad, cellW - 2 * pad, cellH - 2 * pad);
            bool hit = cell.IntersectsWith(br);
            Items[i].Sel = hit || bandBase.Contains(Items[i]);
            if (hit && first < 0) first = i;
        }
        if (first >= 0) { fidx = first; anc = first; }
        Changed();
    }

    // while the pointer is above or below the grid during a drag, keep scrolling
    void BandAutoScroll()
    {
        if (!banding) { bandTimer.Stop(); return; }
        Point p = PointToClient(Control.MousePosition);
        int dy = p.Y < 0 ? p.Y : p.Y > ClientSize.Height ? p.Y - ClientSize.Height : 0;
        if (dy == 0) return;
        int step = Math.Max(-cellH / 2, Math.Min(cellH / 2, dy / 2 + (dy > 0 ? 4 : -4)));
        SetScroll(scrollY + step);
        bandNow = p;
        UpdateBand();
    }

    void EndBand()
    {
        bandArmed = false;
        bandTimer.Stop();
        if (banding) { banding = false; Invalidate(); }
    }

    void DrawCell(Graphics g, int i, Rectangle rc)
    {
        if (detailsMode) { DrawRow(g, i, rc); return; }
        Item it = Items[i];
        bool dim = IsCut(it);
        if (it.Sel)
        {
            var sel = new Rectangle(rc.X + 1, rc.Y + 1, rc.Width - 3, rc.Height - 3);
            g.FillRectangle(selBrush, sel);
            g.DrawRectangle(selPen, sel);
        }
        if (i == fidx && Focused) ControlPaint.DrawFocusRectangle(g, new Rectangle(rc.X + 3, rc.Y + 3, rc.Width - 7, rc.Height - 7));

        var box = new Rectangle(rc.X + pad, rc.Y + pad, tile, tile);
        int bs = 0;
        Bitmap b = it.Offline ? null : cache.Get(it.Path, it.Stamp, out bs);
        if (b != null)
        {
            if (bs == tile || bs <= 0)
                Blit(g, b, box.X + (tile - b.Width) / 2, box.Y + (tile - b.Height) / 2, b.Width, b.Height, dim);
            else
            {
                // made for another tile size (the slider was just moved): show it scaled until a sharp one arrives
                double f = (double)tile / bs;
                int dw = Math.Max(1, (int)Math.Round(b.Width * f)), dh = Math.Max(1, (int)Math.Round(b.Height * f));
                InterpolationMode old = g.InterpolationMode;
                g.InterpolationMode = InterpolationMode.Bilinear;
                Blit(g, b, box.X + (tile - dw) / 2, box.Y + (tile - dh) / 2, dw, dh, dim);
                g.InterpolationMode = old;
            }
        }
        else
        {
            int s = tile * 3 / 4;
            var ph = new Rectangle(box.X + (tile - s) / 2, box.Y + (tile - s) / 2, s, s);
            g.FillRectangle(placeBrush, ph);
            string t = it.Offline ? "cloud-only\n(not on this PC)" : failed.ContainsKey(it.Path) ? "?" : "";
            if (t.Length > 0)
                TextRenderer.DrawText(g, t, font, ph, Color.Gray, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
        }
        DrawMarks(g, it, box);
        var tr = new Rectangle(rc.X + 2, box.Bottom + pad / 2, rc.Width - 4, font.Height + 2);
        TextRenderer.DrawText(g, it.Name, font, tr, dim ? Color.Gray : it.Sel ? Color.White : Color.Gainsboro,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);

        if (showDetails)
        {
            int w, h; string note, dims = null, full = null;
            if (it.Offline) dims = full = "cloud-only";
            else if (cache.Info(it.Path, it.Stamp, out w, out h, out note)) { dims = w + " x " + h; full = dims + (note != null ? "  " + note : ""); }
            else if (failed.ContainsKey(it.Path)) dims = full = "can't read";
            if (full != null)
            {
                const TextFormatFlags fl = TextFormatFlags.HorizontalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;
                var area = new Rectangle(rc.X + 2, tr.Bottom, rc.Width - 4, small.Height + 2);
                string d = full;
                if (TextRenderer.MeasureText(g, d, small, Size.Empty, fl).Width > area.Width) d = dims;       // too narrow: size only
                if (TextRenderer.MeasureText(g, d, small, Size.Empty, fl).Width > area.Width) d = null;       // still too narrow: nothing
                if (d != null) TextRenderer.DrawText(g, d, small, area, Color.FromArgb(150, 150, 150), fl);   // (no clipped fragments)
            }
        }
    }

    readonly SolidBrush stripeBrush = new SolidBrush(Color.FromArgb(29, 29, 29));

    // marks on a thumbnail tile, drawn only when the picture has some: a colour strip along the top, a tick for
    // the tag at the top right, stars at the bottom left
    void DrawMarks(Graphics g, Item it, Rectangle box)
    {
        Mark m = MarkOf(it);
        int fileStars = m != null && m.Stars > 0 ? 0 : FileStarsOf(it);
        if ((m == null || m.Empty) && fileStars == 0) return;
        if (m == null) m = new Mark();
        if (m.Label > 0)
            using (var lb = new SolidBrush(Marks.LabelColours[m.Label])) g.FillRectangle(lb, box.X, box.Y, box.Width, Math.Max(3, Util.S(4)));
        if (m.Tag)
        {
            int s = Math.Max(12, Util.S(16));
            var r = new Rectangle(box.Right - s - Util.S(3), box.Y + Util.S(7), s, s);
            using (var bb = new SolidBrush(Color.FromArgb(60, 130, 230))) g.FillRectangle(bb, r);
            SmoothingMode old = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(Color.White, Math.Max(1.5f, Util.K * 2f)))
                g.DrawLines(pen, new[] { new PointF(r.X + s * 0.22f, r.Y + s * 0.52f), new PointF(r.X + s * 0.42f, r.Y + s * 0.72f), new PointF(r.X + s * 0.78f, r.Y + s * 0.28f) });
            g.SmoothingMode = old;
        }
        if (m.Stars > 0 || fileStars > 0)
        {
            string st = Marks.StarText(m.Stars > 0 ? m.Stars : fileStars);
            Size sz = TextRenderer.MeasureText(g, st, font, Size.Empty, TextFormatFlags.NoPadding);
            var r = new Rectangle(box.X + Util.S(3), box.Bottom - sz.Height - Util.S(4), sz.Width + Util.S(6), sz.Height + Util.S(2));
            using (var bb = new SolidBrush(Color.FromArgb(170, 0, 0, 0))) g.FillRectangle(bb, r);
            Color sc = m.Stars > 0 ? Color.FromArgb(255, 205, 70) : Color.FromArgb(200, 200, 200);   // silver: the file's own rating
            TextRenderer.DrawText(g, st, font, r, sc, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
        }
    }

    void DrawRow(Graphics g, int i, Rectangle rc)
    {
        Item it = Items[i];
        var row = new Rectangle(rc.X, rc.Y, rc.Width, rc.Height);
        bool dim = IsCut(it);
        if (it.Sel) { g.FillRectangle(selBrush, row); g.DrawRectangle(selPen, row.X, row.Y, row.Width - 1, row.Height - 1); }
        else if ((i & 1) == 1) g.FillRectangle(stripeBrush, row);
        if (i == fidx && Focused) ControlPaint.DrawFocusRectangle(g, new Rectangle(row.X + 2, row.Y + 1, row.Width - 4, row.Height - 2));

        // thumbnail
        var box = new Rectangle(rc.X + Util.S(5), rc.Y + (rc.Height - tile) / 2, tile, tile);
        int bs = 0;
        Bitmap b = it.Offline ? null : cache.Get(it.Path, it.Stamp, out bs);
        if (b != null)
        {
            double f = (bs == tile || bs <= 0) ? 1.0 : (double)tile / bs;
            int dw = Math.Max(1, (int)Math.Round(b.Width * f)), dh = Math.Max(1, (int)Math.Round(b.Height * f));
            if (dw > tile || dh > tile) { double s2 = Math.Min((double)tile / dw, (double)tile / dh); dw = Math.Max(1, (int)(dw * s2)); dh = Math.Max(1, (int)(dh * s2)); }
            InterpolationMode old = g.InterpolationMode;
            if (dw != b.Width) g.InterpolationMode = InterpolationMode.Bilinear;
            Blit(g, b, box.X + (tile - dw) / 2, box.Y + (tile - dh) / 2, dw, dh, dim);
            g.InterpolationMode = old;
        }
        else g.FillRectangle(placeBrush, box.X + tile / 6, box.Y + tile / 6, tile * 2 / 3, tile * 2 / 3);

        // columns
        int w = 0, h = 0; string note = null;
        bool have = false;
        if (!it.Offline) have = KnownInfo(it, out w, out h, out note);
        if (!have) { w = h = 0; note = null; }
        Color statusColour;
        string status = StatusText(it, i, out statusColour);
        AuditEntry an = AnalysisOf(it);
        bool deep = an != null && an.W > 0;
        Mark mk = MarkOf(it);
        string[] text =
        {
            it.Name + (mk != null && mk.Tag ? "  \u2714" : ""),
            Marks.StarText(StarsOf(it)),
            mk != null && mk.Label > 0 ? Marks.LabelNames[mk.Label] : "",
            (it.Ext ?? "").TrimStart('.').ToUpperInvariant(),
            have ? (note ?? "PC (standard image)") : "",
            have ? w + " x " + h : "",
            deep ? an.Frames.ToString() : "",
            deep && an.Colours >= 0 ? (an.Colours >= 65536 ? "65,536+" : an.Colours.ToString()) : "",
            Util.FmtSize(it.Size),
            new DateTime(it.Modified, DateTimeKind.Utc).ToLocalTime().ToString("yyyy-MM-dd HH:mm"),
            status
        };
        int statusCol = text.Length - 1;
        List<Column> cols2 = Columns();
        Color fore = dim ? Color.Gray : it.Sel ? Color.White : Color.Gainsboro;
        for (int c = 0; c < cols2.Count && c < text.Length; c++)
        {
            Column col = cols2[c];
            if (text[c].Length == 0) continue;
            var cell = new Rectangle(col.X + Util.S(6), rc.Y, Math.Max(0, col.W - Util.S(12)), rc.Height);
            TextFormatFlags fl = TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine
                               | (col.Right ? TextFormatFlags.Right : TextFormatFlags.Left);
            Color fc = c == statusCol ? statusColour : c == 0 ? fore : dim ? Color.Gray
                     : c == 1 ? (mk != null && mk.Stars > 0 ? Color.FromArgb(255, 205, 70) : Color.FromArgb(200, 200, 200))   // gold: yours, silver: the file's
                     : c == 2 && mk != null && mk.Label > 0 ? Marks.LabelColours[mk.Label]       // the label in its colour
                     : (it.Sel ? Color.White : Color.FromArgb(175, 175, 175));
            TextRenderer.DrawText(g, text[c], c == 0 ? font : small, cell, fc, fl);
        }
    }

    // ---------------------------------------------------------------- input

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if (!Visible) { hoverIdx = -1; HideTip(); return; }
        Relayout();
        if (fidx >= 0) EnsureVisible(fidx);
        Schedule(); Invalidate();
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        Relayout(); Schedule(); Invalidate();
    }

    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        Wheel(e.Delta, (ModifierKeys & Keys.Control) != 0);
    }

    // wheel = scroll, Ctrl + wheel = change thumbnail size
    public void Wheel(int delta, bool ctrl)
    {
        if (ctrl) { ChangeTile(delta > 0 ? 1 : -1); return; }
        SetScroll(scrollY - (int)(delta * cellH * 0.6 / 120.0));
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (dragArmed && (e.Button & MouseButtons.Left) != 0)
        {
            if (Math.Abs(e.X - dragStart.X) > SystemInformation.DragSize.Width || Math.Abs(e.Y - dragStart.Y) > SystemInformation.DragSize.Height)
            {
                dragArmed = false; pressIdx = -1;
                StartDrag();
            }
            return;
        }
        if (bandArmed && (e.Button & MouseButtons.Left) != 0)
        {
            int tx = Math.Abs(e.X - bandStart.X), ty = Math.Abs(e.Y + scrollY - bandStart.Y);
            if (!banding && (tx > SystemInformation.DragSize.Width || ty > SystemInformation.DragSize.Height))
            {
                banding = true;
                hoverIdx = -1; HideTip();
                bandTimer.Start();
            }
            if (banding) { bandNow = e.Location; UpdateBand(); return; }
        }
        hoverPt = e.Location;
        int i = HitTest(e.Location);
        if (i == hoverIdx) return;
        hoverIdx = i;
        HideTip();
        if (i >= 0) hoverTimer.Start();                      // details appear when the pointer rests on a tile
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        base.OnMouseLeave(e);
        hoverIdx = -1;
        HideTip();
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        HideTip();
        Focus();
        int i = HitTest(e.Location);
        bool ctrl = (ModifierKeys & Keys.Control) != 0, shift = (ModifierKeys & Keys.Shift) != 0;
        if (e.Button == MouseButtons.Right) { if (i >= 0 && !Items[i].Sel) SelectOnly(i); return; }
        if (e.Button != MouseButtons.Left) return;
        pressIdx = -1; dragArmed = false;
        if (i >= 0 && Items[i].Sel && !ctrl && !shift)
        {
            dragArmed = true; dragStart = e.Location; pressIdx = i;
            anc = fidx = i;
            Changed();
            return;
        }
        if (i < 0) { if (!ctrl && !shift) { ClearAll(); Changed(); } }
        else if (shift && anc >= 0) SelectRange(anc, i);
        else if (ctrl) { Items[i].Sel = !Items[i].Sel; anc = fidx = i; Changed(); }
        else SelectOnly(i);
        if (!shift && Items.Count > 0)                     // a drag from here becomes a rubber band
        {
            bandArmed = true;
            bandStart = new Point(e.X, e.Y + scrollY);
            bandBase = new HashSet<Item>();
            if (ctrl) foreach (Item it in Items) if (it.Sel) bandBase.Add(it);
        }
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e);
        if (e.Button == MouseButtons.Left)
        {
            EndBand();
            dragArmed = false;
            if (pressIdx >= 0 && pressIdx < Items.Count) { int k = pressIdx; pressIdx = -1; SelectOnly(k); }
            pressIdx = -1;
        }
        if (e.Button != MouseButtons.Right) return;
        var h = ContextRequested;
        if (h != null) h(e.Location, HitTest(e.Location));
    }

    protected override void OnMouseCaptureChanged(EventArgs e)
    {
        base.OnMouseCaptureChanged(e);
        if (!Capture) { EndBand(); dragArmed = false; }
    }

    void StartDrag()
    {
        var list = new StringCollection();
        foreach (Item it in Items) if (it.Sel) list.Add(it.Path);
        if (list.Count == 0) return;
        HideTip(); hoverIdx = -1;
        var data = new DataObject();
        data.SetFileDropList(list);                        // the format Explorer understands
        DraggingOut = true;
        try { DoDragDrop(data, DragDropEffects.Copy | DragDropEffects.Move); }
        catch (Exception) { }
        finally { DraggingOut = false; }
    }

    protected override void OnMouseDoubleClick(MouseEventArgs e)
    {
        base.OnMouseDoubleClick(e);
        int i = HitTest(e.Location);
        var h = OpenRequested;
        if (e.Button == MouseButtons.Left && i >= 0 && h != null) h(i);
    }

    protected override bool IsInputKey(Keys keyData)
    {
        switch (keyData & Keys.KeyCode)
        {
            case Keys.Left: case Keys.Right: case Keys.Up: case Keys.Down:
            case Keys.Home: case Keys.End: case Keys.PageUp: case Keys.PageDown: case Keys.Return:
                return true;
        }
        return base.IsInputKey(keyData);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        HideTip();
        int n = Items.Count;
        if (n == 0) return;
        int f = fidx < 0 ? 0 : fidx, t = f;
        int page = Math.Max(1, ClientSize.Height / cellH) * cols;
        switch (e.KeyCode)
        {
            case Keys.Left: t = f - 1; break;
            case Keys.Right: t = f + 1; break;
            case Keys.Up: t = f - cols; break;
            case Keys.Down: t = f + cols; break;
            case Keys.Home: t = 0; break;
            case Keys.End: t = n - 1; break;
            case Keys.PageUp: t = f - page; break;
            case Keys.PageDown: t = f + page; break;
            case Keys.Return:
                if (fidx >= 0 && OpenRequested != null) OpenRequested(fidx);
                e.Handled = true; return;
            case Keys.A:
                if (e.Control) { foreach (Item it in Items) it.Sel = true; Changed(); e.Handled = true; }
                return;
            default: return;
        }
        t = Math.Max(0, Math.Min(n - 1, t));
        if (e.Shift) SelectRange(anc < 0 ? f : anc, t); else SelectOnly(t);
        e.Handled = true;
    }
}

// The header of the Details view: column titles; click one to sort by it (again to reverse).
sealed class DetailHeader : Control
{
    readonly ThumbGrid grid;
    readonly Font font = new Font("Segoe UI", 9f);
    int hot = -1;

    public DetailHeader(ThumbGrid grid)
    {
        this.grid = grid;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        Dock = DockStyle.Top; Height = Util.S(26); BackColor = Color.FromArgb(32, 32, 32);
        grid.ColumnsChanged += delegate { Invalidate(); };
        grid.ListChanged += delegate { Invalidate(); };
    }

    int Hit(int x)
    {
        List<ThumbGrid.Column> cols = grid.Columns();
        for (int i = 0; i < cols.Count; i++) if (x >= cols[i].X && x < cols[i].X + cols[i].W) return i;
        return -1;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(BackColor);
        List<ThumbGrid.Column> cols = grid.Columns();
        for (int i = 0; i < cols.Count; i++)
        {
            ThumbGrid.Column c = cols[i];
            var r = new Rectangle(c.X, 0, c.W, Height);
            if (i == hot && c.Key >= 0) using (var b = new SolidBrush(Color.FromArgb(48, 48, 48))) g.FillRectangle(b, r);
            bool sorted = c.Key >= 0 && c.Key == grid.SortKey;
            string t = c.Title;
            var tr = new Rectangle(r.X + Util.S(6), 0, Math.Max(0, r.Width - Util.S(20)), Height);
            TextRenderer.DrawText(g, t, font, tr, sorted ? Color.White : Color.Silver,
                TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine |
                (c.Right ? TextFormatFlags.Right : TextFormatFlags.Left));
            if (sorted)
            {
                // a small arrow: up = ascending, down = descending (drawn, so it never depends on a font)
                g.SmoothingMode = SmoothingMode.AntiAlias;
                float ax = c.Right ? r.X + Util.S(8) : r.Right - Util.S(12), ay = Height / 2f, s = Util.S(4);
                PointF[] tri = grid.SortDesc
                    ? new[] { new PointF(ax - s, ay - s / 2), new PointF(ax + s, ay - s / 2), new PointF(ax, ay + s / 2 + 1) }
                    : new[] { new PointF(ax - s, ay + s / 2), new PointF(ax + s, ay + s / 2), new PointF(ax, ay - s / 2 - 1) };
                using (var b = new SolidBrush(Color.FromArgb(60, 130, 230))) g.FillPolygon(b, tri);
                g.SmoothingMode = SmoothingMode.None;
            }
            using (var p = new Pen(Color.FromArgb(52, 52, 52))) g.DrawLine(p, r.Right - 1, Util.S(5), r.Right - 1, Height - Util.S(5));
        }
        using (var p = new Pen(Color.FromArgb(60, 60, 60))) g.DrawLine(p, 0, Height - 1, Width, Height - 1);
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        int h = Hit(e.X);
        if (h != hot) { hot = h; Invalidate(); }
        List<ThumbGrid.Column> cols = grid.Columns();
        Cursor = h >= 0 && cols[h].Key >= 0 ? Cursors.Hand : Cursors.Default;
    }

    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hot = -1; Invalidate(); }

    protected override void OnMouseClick(MouseEventArgs e)
    {
        base.OnMouseClick(e);
        if (e.Button != MouseButtons.Left) return;
        int h = Hit(e.X);
        if (h < 0) return;
        int key = grid.Columns()[h].Key;
        if (key < 0) return;
        if (key == grid.SortKey) grid.SetSort(key, !grid.SortDesc);
        else grid.SetSort(key, key == 1 || key == 2 || key == 5 || key == 6 || key == 7 || key == 9);   // date, size, dimensions, frames, colours, rating: largest first
        grid.Focus();
    }
}

// The preview pane (Alt+P): to the right of the thumbnails, a large preview of the focused picture and a few
// facts about it. Off by default. The preview is made on its own background thread, at the pane's size.
sealed class PreviewPane : Control
{
    readonly Font font = new Font("Segoe UI", 9f), bold = new Font("Segoe UI", 10f, FontStyle.Bold);
    ThumbService svc;
    Control host;
    Item item;                             // what is shown (null = nothing)
    Mark mark;
    string where, selNote;
    Bitmap bmp;
    int bmpW, bmpH, reqSize;
    string note, error;
    int gen, fileStars;

    public PreviewPane()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        BackColor = Color.FromArgb(30, 30, 30);
    }

    int WantSize { get { return Math.Max(64, Math.Min(1600, Math.Max(ClientSize.Width, ClientSize.Height - Util.S(150)))); } }

    // it = the focused picture; m = its marks; folder = shown when the list spans subfolders; others = how many more are selected
    public void ShowItem(Item it, Mark m, string folder, int others)
    {
        mark = m; where = folder;
        selNote = others > 0 ? "+ " + others + " more selected" : null;
        if (it == null || item == null || !string.Equals(it.Path, item.Path, StringComparison.OrdinalIgnoreCase) || it.Stamp != item.Stamp)
        {
            item = it;
            if (bmp != null) { bmp.Dispose(); bmp = null; }
            note = error = null; bmpW = bmpH = 0; reqSize = 0; fileStars = 0;
            gen++;
            Request();
        }
        Invalidate();
    }

    void Request()
    {
        if (item == null || !Visible) return;
        if (item.Offline) { error = "Cloud-only: not stored on this PC, so it is not opened."; return; }
        int size = WantSize;
        if (reqSize >= size) return;
        reqSize = size;
        if (svc == null) svc = new ThumbService(1, Done);
        host = FindForm();
        int g = gen;
        svc.Replace(new List<ThumbJob> { new ThumbJob { Path = item.Path, Size = size, Stamp = g } });   // Stamp carries the request number
    }

    void Done(ThumbJob j, ThumbResult r)               // worker thread
    {
        Control h = host;
        if (!Util.Post(h, delegate
        {
            if (j.Stamp != gen || item == null || !string.Equals(j.Path, item.Path, StringComparison.OrdinalIgnoreCase)) { if (r.Bmp != null) r.Bmp.Dispose(); return; }
            if (bmp != null) bmp.Dispose();
            bmp = r.Bmp; bmpW = r.W; bmpH = r.H; note = r.Note; fileStars = r.FileStars; error = r.Bmp == null ? (r.Error ?? "Could not be opened.") : null;
            Invalidate();
        }) && r.Bmp != null) r.Bmp.Dispose();
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); Request(); Invalidate(); }
    protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); if (Visible) Request(); }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(BackColor);
        int pad = Util.S(10);
        if (item == null)
        {
            TextRenderer.DrawText(g, "Select a picture to preview it here", font, ClientRectangle, Color.Gray,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak);
            return;
        }
        // the facts first, so the picture gets whatever height is left
        var lines = new List<string>();
        if (bmpW > 0) lines.Add(bmpW + " x " + bmpH + "    " + (note ?? "PC (standard image)"));
        lines.Add(Util.FmtSize(item.Size) + "    " + new DateTime(item.Modified, DateTimeKind.Utc).ToLocalTime().ToString("yyyy-MM-dd HH:mm"));
        if (mark != null && !mark.Empty) lines.Add(Marks.Describe(mark));
        if ((mark == null || mark.Stars == 0) && fileStars > 0) lines.Add(Marks.StarText(fileStars) + "  rating stored in the file");
        if (where != null) lines.Add("In: " + where);
        if (selNote != null) lines.Add(selNote);
        int lh = font.Height + Util.S(2);
        int infoH = bold.Height + Util.S(6) + lines.Count * lh + (error != null ? lh * 2 : 0) + pad;
        var pic = new Rectangle(pad, pad, Math.Max(1, ClientSize.Width - 2 * pad), Math.Max(1, ClientSize.Height - infoH - 2 * pad));
        if (bmp != null)
        {
            double s = Math.Min((double)pic.Width / bmp.Width, (double)pic.Height / bmp.Height);
            bool pixelArt = note != null;                            // retro pictures: enlarged with hard edges
            if (s > 1 && pixelArt) s = Math.Max(1, Math.Floor(s));
            int dw = Math.Max(1, (int)(bmp.Width * s)), dh = Math.Max(1, (int)(bmp.Height * s));
            g.InterpolationMode = s > 1 && pixelArt ? InterpolationMode.NearestNeighbor : InterpolationMode.HighQualityBilinear;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.DrawImage(bmp, pic.X + (pic.Width - dw) / 2, pic.Y + (pic.Height - dh) / 2, dw, dh);
        }
        else if (error == null)
            TextRenderer.DrawText(g, "Loading...", font, pic, Color.Gray, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        int y = pic.Bottom + pad;
        const TextFormatFlags fl = TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;
        TextRenderer.DrawText(g, item.Name, bold, new Rectangle(pad, y, ClientSize.Width - 2 * pad, bold.Height + 2), Color.White, fl);
        y += bold.Height + Util.S(6);
        if (error != null)
        {
            TextRenderer.DrawText(g, error, font, new Rectangle(pad, y, ClientSize.Width - 2 * pad, lh * 2), Color.FromArgb(255, 140, 90),
                TextFormatFlags.WordBreak | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            y += lh * 2;
        }
        foreach (string l in lines)
        {
            Color c = mark != null && !mark.Empty && l == Marks.Describe(mark) ? Color.FromArgb(255, 205, 70)
                    : l.EndsWith("rating stored in the file", StringComparison.Ordinal) ? Color.FromArgb(215, 215, 215) : Color.Silver;
            TextRenderer.DrawText(g, l, font, new Rectangle(pad, y, ClientSize.Width - 2 * pad, lh), c, fl);
            y += lh;
        }
    }
}
