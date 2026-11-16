// RetroGleek - the full-canvas viewer
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

// ====================================================================== full-canvas viewer

sealed class Canvas : Control
{
    static readonly Color Bg = Color.FromArgb(24, 24, 24);
    const long MaxPredecodePixels = 100000000L;

    List<string> files = new List<string>();
    int idx = -1;
    readonly Dictionary<string, Pic> cache = new Dictionary<string, Pic>(StringComparer.OrdinalIgnoreCase);
    readonly HashSet<string> pending = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    string want, notice;
    Pic cur;

    int rot, fitMode;                 // fitMode: 0 = free, 1 = fit (never enlarge), 2 = fit (may enlarge)
    double zoom = 1, px, py;          // px,py = offset of image centre from window centre
    bool fast, showInfo = true, dragging;
    int wheelAcc;
    Point last;

    // pixel tools, slideshow and short on-screen messages
    bool showGrid;                         // G: pixel grid (drawn at 8x and above)
    int pixMode;                           // N: 0 = auto (retro pictures sharp, photos smooth), 1 = crisp, 2 = smooth, 3 = sharp
    bool mouseIn;                          // the pointer is over the picture area
    bool loupe;                            // Z held: a magnifier around the pointer

    // ---- filmstrip (J): a row of small thumbnails of the folder along the bottom; click one to show it.
    // Hidden during a slideshow. The picture area is the window minus the strip.
    bool strip;
    ThumbService stripSvc;
    readonly ThumbCache stripCache = new ThumbCache();
    readonly Dictionary<string, long> stripStamps = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
    Control stripHost;
    public bool Filmstrip { get { return strip; } set { strip = value; if (HasImage) { Refit(); Clamp(); } Invalidate(); } }
    bool StripShown { get { return strip && !slideshow && files.Count > 1; } }
    int StripH { get { return StripShown ? Util.S(84) : 0; } }
    int ViewH { get { return Math.Max(1, ClientSize.Height - StripH); } }      // the height the picture is shown in
    Point mousePt;
    int lhx = -2, lhy = -2;                // last pixel reported under the pointer
    string flash;
    bool slideshow;
    int slideIdx = 2;                      // index into SlideSecs (3 seconds)
    static readonly int[] SlideSecs = { 1, 2, 3, 5, 8, 12, 20, 30 };
    readonly WinTimer slideTimer = new WinTimer();
    readonly WinTimer flashTimer = new WinTimer { Interval = 2200 };
    public bool Slideshow { get { return slideshow; } }

    // ---- True TV aspect (T) and scanlines (K): display only, never in saved or copied pictures
    bool tvAspect;
    int scanMode;                                          // 0 off, 1 light, 2 medium, 3 strong
    static readonly string[] ScanNames = { "off", "light", "medium", "strong" };
    public bool TvAspect { get { return tvAspect; } set { tvAspect = value; fxOff = false; LeaveAuto(); if (HasImage) { Refit(); Clamp(); } Invalidate(); } }
    public int ScanMode { get { return scanMode; } set { scanMode = Math.Max(0, Math.Min(3, value)); fxOff = false; LeaveAuto(); if (HasImage) Refit(); Invalidate(); } }

    // O: every screen effect off at once (TV aspect, scanlines, mask, signal, glow), to compare with the picture as
    // decoded; O again, or changing any effect, brings them back. Not remembered: each start shows the effects.
    bool fxOff;
    public bool EffectsOff { get { return fxOff; } set { fxOff = value; if (HasImage) { Refit(); Clamp(); } Invalidate(); } }

    // ---- automatic effects (A) and presets. Automatic: every retro picture gets the effects of the screen its computer
    // was usually seen on (EffectSet.ForPlatform). Your own settings are kept aside meanwhile: A again brings them back.
    // Changing any single effect while automatic is on keeps what is shown, with your change, as your own settings
    // (except curvature, which automatic never chooses: changing it leaves automatic on).
    bool autoFx;
    EffectSet manualFx;                                    // your own settings while automatic is on
    EffectSet autoChoice;                                  // what automatic chose for the current picture

    public EffectSet CurrentEffects { get { return new EffectSet { Tv = tvAspect, Scan = scanMode, Mask = maskMode, Signal = signalMode, Glow = glowMode, Curve = curveMode }; } }
    public EffectSet ManualEffects { get { return autoFx && manualFx != null ? manualFx.Copy() : CurrentEffects; } }   // what settings.ini keeps
    public EffectSet AutoChoice { get { return autoFx ? autoChoice : null; } }

    public bool AutoEffects
    {
        get { return autoFx; }
        set
        {
            if (value == autoFx) return;
            fxOff = false;
            if (value) { manualFx = CurrentEffects; autoFx = true; ApplyAuto(); }
            else { autoFx = false; autoChoice = null; if (manualFx != null) SetFields(manualFx); manualFx = null; }
            if (HasImage) { Refit(); Clamp(); }
            Invalidate();
        }
    }

    void LeaveAuto() { if (autoFx) { autoFx = false; manualFx = null; autoChoice = null; } }

    void SetFields(EffectSet e)
    {
        tvAspect = e.Tv; scanMode = e.Scan; maskMode = e.Mask; signalMode = e.Signal; glowMode = e.Glow; curveMode = e.Curve;
    }

    // automatic: pick the effects for the current picture's computer (pictures that are not retro keep the last ones)
    void ApplyAuto()
    {
        if (!autoFx || !HasImage) return;
        EffectSet e = EffectSet.ForPlatform(cur.Note, cur.Geom != null ? cur.Geom.OrigW : 0, cur.Geom != null ? cur.Geom.OrigH : 0);
        if (e == null) return;
        e.Curve = manualFx != null ? manualFx.Curve : curveMode;   // curvature is a matter of taste: automatic keeps yours
        autoChoice = e;
        SetFields(e);
    }

    // a preset (or the settings from settings.ini): replaces the effects and ends automatic mode
    public void UseEffects(EffectSet e)
    {
        if (e == null) return;
        LeaveAuto();
        fxOff = false;
        SetFields(e);
        if (HasImage) { Refit(); Clamp(); }
        Invalidate();
    }

    public void ToggleAuto()
    {
        AutoEffects = !autoFx;
        if (!autoFx) { Flash("Automatic screen effects off: your own settings again"); return; }
        Flash(autoChoice != null ? "Automatic screen effects: " + cur.Note + " - " + autoChoice.Name + " (" + autoChoice.Describe() + ")"
                                 : "Automatic screen effects on: each retro picture gets the effects of its computer's usual screen");
    }

    // ---- glow (W): bright areas light up their surroundings, as on a CRT
    int glowMode;                                          // 0 off, 1 soft, 2 strong
    static readonly string[] GlowNames = { "off", "soft", "strong" };
    public int GlowMode { get { return glowMode; } set { glowMode = Math.Max(0, Math.Min(2, value)); fxOff = false; LeaveAuto(); Invalidate(); } }
    bool GlowShown { get { return glowMode > 0 && !fxOff && HasImage && cur.Note != null; } }

    // ---- screen curvature (U): the picture bulges like a CRT's glass, with darker, rounded corners. It bends the
    // picture's pixels, so it switches itself off at 800% and above, where the pixel grid and outline need exact pixels.
    int curveMode;                                         // 0 off, 1 slight, 2 strong
    static readonly string[] CurveNames = { "off", "slight", "strong" };
    // automatic mode stays on when only the curvature changes: it is yours either way (ApplyAuto keeps it)
    public int CurveMode
    {
        get { return curveMode; }
        set
        {
            curveMode = Math.Max(0, Math.Min(2, value));
            fxOff = false;
            if (manualFx != null) manualFx.Curve = curveMode;
            if (autoChoice != null) autoChoice.Curve = curveMode;
            Invalidate();
        }
    }
    bool CurveWanted { get { return curveMode > 0 && !fxOff && HasImage && cur.Note != null; } }
    bool CurveShown { get { return CurveWanted && zoom < 8; } }

    // ---- phosphor mask (M): the fine pattern of red, green and blue phosphors on a CRT, drawn in screen pixels
    int maskMode;                                          // 0 off, 1 aperture grille, 2 slot mask, 3 dot mask
    static readonly string[] MaskNames = { "off", "aperture grille", "slot mask", "dot mask" };
    public int MaskMode { get { return maskMode; } set { maskMode = Math.Max(0, Math.Min(3, value)); fxOff = false; LeaveAuto(); Invalidate(); } }

    // ---- video signal (C): RGB (as decoded), S-Video or composite, as the picture would have reached a TV
    int signalMode;                                        // 0 RGB, 1 S-Video, 2 composite
    static readonly string[] SignalNames = { "RGB (sharp)", "S-Video", "composite" };
    public int SignalMode { get { return signalMode; } set { signalMode = Math.Max(0, Math.Min(2, value)); fxOff = false; LeaveAuto(); Invalidate(); } }
    bool SignalApplies { get { return signalMode > 0 && !fxOff && HasImage && cur.Note != null; } }

    // width of one displayed pixel relative to its height (1 = square, or not known / not wanted)
    double Ax { get { return tvAspect && !fxOff && HasImage && cur.Geom != null ? cur.Geom.PixelAspect : 1.0; } }

    // scanlines apply to retro pictures; one per original screen line. Not shown while the picture is turned on its
    // side (90 / 270 degrees): they would run vertically. They come back when it is upright or upside down again.
    bool ScanWanted { get { return scanMode > 0 && !fxOff && HasImage && cur.Note != null; } }
    bool ScanApplies { get { return ScanWanted && (rot & 1) == 0; } }
    bool MaskWanted { get { return maskMode > 0 && !fxOff && HasImage && cur.Note != null; } }
    bool MaskApplies { get { return MaskWanted && (rot & 1) == 0; } }
    bool ScanShown { get { return ScanApplies && LineHeight * zoom >= 3; } }
    bool MaskShown { get { return MaskApplies && zoom * Math.Min(1.0, Ax) >= 2; } }
    double LineHeight { get { return HasImage && cur.Geom != null && cur.Geom.OrigH > 0 ? (double)cur.H / cur.Geom.OrigH : 1.0; } }

    // ---- side-by-side compare: two viewers follow each other's zoom and position
    public event Action ViewChanged;                       // the user zoomed, panned or chose fit (not raised by SetView)
    bool applyingView;
    void RaiseView() { if (applyingView) return; var h = ViewChanged; if (h != null) h(); }

    public void GetView(out double z, out double x, out double y, out int fm) { z = zoom; x = px; y = py; fm = fitMode; }

    // Takes over another viewer's view. Fit modes are applied as modes (each picture fits its own window);
    // a free zoom takes the same scale and offset, so equal-sized pictures line up pixel for pixel.
    public void SetView(double z, double x, double y, int fm)
    {
        applyingView = true;
        try
        {
            fast = false;
            if (fm != 0) { fitMode = fm; Refit(); }
            else { zoom = z; px = x; py = y; fitMode = 0; Clamp(); }
            Invalidate();
        }
        finally { applyingView = false; }
    }

    // forgets the picture(s) and frees their memory (when a comparison ends)
    public void Release()
    {
        StopSlideshow();
        StopAnim();
        if (cur != null && !cache.ContainsValue(cur)) cur.Dispose();
        foreach (Pic p in cache.Values) p.Dispose();
        cache.Clear();
        DropSharp(); DropFx(); DropComposite(); DropGlow();
        stripCache.Clear(); stripStamps.Clear();
        cur = null; want = null; notice = null;
        files = new List<string>(); idx = -1;
        Invalidate();
    }

    // read by the menu bar (check marks, enabled entries)
    public bool HasPicture { get { return HasImage; } }
    public bool FitLock { get { return fitLock; } set { fitLock = value; } }
    public bool Checker { get { return checker; } set { checker = value; Invalidate(); } }
    public bool GridOn { get { return showGrid; } }
    public bool InfoOn { get { return showInfo; } set { showInfo = value; Invalidate(); } }
    public bool ExifOn { get { return showExif; } set { showExif = value; Invalidate(); } }
    public int SlideIndex { get { return slideIdx; } set { slideIdx = Math.Max(0, Math.Min(SlideSecs.Length - 1, value)); } }
    public bool Animated { get { return AnimActive; } }
    public bool AnimPaused { get { return animPaused; } }
    public int FileCount { get { return files.Count; } }
    // 0 = automatic (retro pictures sharp, photos smooth), 1 = crisp, 2 = smooth, 3 = sharp
    public int PixMode { get { return pixMode; } set { pixMode = Math.Max(0, Math.Min(3, value)); Invalidate(); } }

    // Fit-to-Screen (F): on = every picture is scaled to fit the window, off = every picture opens at 100%.
    // Starts off at every launch and is kept only while the program runs (nothing is saved to disk).
    // Zooming by hand only affects the current picture.
    bool fitLock;                          // remembered in settings.ini (off by default)
    bool showExif;                         // E: EXIF details panel (remembered in settings.ini)

    // own animation clock for animated GIFs, so they can be paused (P) and stepped frame by frame (, and .)
    readonly WinTimer animTimer = new WinTimer();
    int frame, frameCount;
    int[] frameDelays;                     // milliseconds per frame
    bool animPaused;
    bool flipX, flipY;                     // H / V: mirror the current picture (reset for the next one)
    bool checker;                          // B: checkerboard behind transparent pictures (remembered in settings.ini)
    TextureBrush checkerBrush;
    int checkerCell;

    readonly WinTimer settle = new WinTimer { Interval = 150 };
    readonly ImageAttributes ia = new ImageAttributes();
    readonly Font font = new Font("Segoe UI", 9f);
    readonly Font big = new Font("Segoe UI", 12f);

    public event Action<string, int> ImageChanged;
    public string Want { get { return want; } }

    // what "Save as PNG" / "Copy picture" use while viewing: the picture's file plus any rotation and mirroring
    // you added on top of its own
    public bool GetSaveSource(out string path, out int extraTurns, out bool fx, out bool fy)
    {
        path = null; extraTurns = 0; fx = fy = false;
        if (cur == null || cur.Img == null) return false;
        path = cur.FullPath;
        extraTurns = (rot - cur.Rot) & 3;
        fx = flipX; fy = flipY;
        return true;
    }

    // the file currently shown (also when it failed to decode), or null
    public string CurrentPath { get { return cur != null ? cur.FullPath : null; } }
    public string Platform { get { return HasImage ? cur.Note : null; } }        // retro pictures: e.g. "Commodore 64"

    // marks of the picture shown (read once per picture; MarksChanged after marking)
    string markPath;
    Mark curMark;
    Mark CurMark
    {
        get
        {
            if (cur == null) return null;
            if (!string.Equals(markPath, cur.FullPath, StringComparison.Ordinal)) { markPath = cur.FullPath; curMark = Marks.ForFile(markPath); }
            return curMark;
        }
    }
    public void MarksChanged() { markPath = null; Invalidate(); }

    // the current file was changed on disk (a lossless turn): read it again and show it as it is now
    public bool ExtraTurns { get { return cur != null && ((rot - cur.Rot) & 3) != 0; } }
    public void Reload()
    {
        if (cur == null || idx < 0 || idx >= files.Count) return;
        string p = cur.FullPath;
        StopAnim();
        Pic c = cur, old;
        if (cache.TryGetValue(p, out old)) { cache.Remove(p); if (old != c) old.Dispose(); }
        cur = null;
        if (c != null) c.Dispose();
        DropSharp(); DropFx(); DropComposite(); DropGlow();
        markPath = null;
        stripStamps.Remove(p);
        GoTo(idx);
    }
    public void Next() { Step(1); }                       // auto-advance after marking

    // The current file was deleted: drop it from the list and show its neighbour. False if nothing is left.
    public bool RemoveCurrent()
    {
        if (cur == null) return files.Count > 0;
        string gone = cur.FullPath;
        int at = files.FindIndex(x => string.Equals(x, gone, StringComparison.OrdinalIgnoreCase));
        files = new List<string>(files);                   // the list may be the grid's own: never change that one
        if (at >= 0) files.RemoveAt(at);
        Pic p;
        if (cache.TryGetValue(gone, out p)) { cache.Remove(gone); if (p != cur) p.Dispose(); }
        StopAnim();
        Pic old = cur;
        cur = null;
        if (old != null) old.Dispose();
        if (files.Count == 0) { idx = -1; want = null; Invalidate(); return false; }
        idx = -1;
        GoTo(Math.Max(0, Math.Min(at < 0 ? 0 : at, files.Count - 1)));
        return true;
    }

    public Canvas()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
        BackColor = Bg; Dock = DockStyle.Fill; TabStop = true; Visible = false;
        ia.SetWrapMode(WrapMode.TileFlipXY);          // no faded edges when scaling
        settle.Tick += delegate { settle.Stop(); fast = false; Invalidate(); };
        flashTimer.Tick += delegate { flashTimer.Stop(); flash = null; Invalidate(); };
        slideTimer.Tick += delegate { Step(1); };
        animTimer.Tick += delegate { animTimer.Stop(); if (AnimActive) { ShowFrame(frame + 1); ScheduleFrame(); } };
    }

    // ---------------------------------------------------------------- public API

    // Show one image right away; the folder list arrives later through SetList.
    public void ShowSingle(string path)
    {
        files = new List<string> { path };
        idx = -1;
        if (cur == null || !string.Equals(cur.FullPath, path, StringComparison.OrdinalIgnoreCase)) Clear();
        GoTo(0);
    }

    public void Open(List<string> list, int index)
    {
        files = list; idx = -1;
        if (index < 0 || index >= list.Count) return;
        if (cur == null || !string.Equals(cur.FullPath, list[index], StringComparison.OrdinalIgnoreCase)) Clear();
        GoTo(index);
    }

    public void SetList(List<string> list, string current)
    {
        files = list;
        int i = current == null ? -1 : list.FindIndex(x => string.Equals(x, current, StringComparison.OrdinalIgnoreCase));
        idx = i;
        if (i >= 0) { Prefetch(); Trim(); }
        stripStamps.Clear();                               // the folder was read again: dates may have changed
        if (strip) { if (HasImage) { Refit(); Clamp(); } Invalidate(); }
    }

    public bool HandleKey(Keys keyData)
    {
        Keys k = keyData & Keys.KeyCode;
        bool shift = (keyData & Keys.Shift) != 0, ctrl = (keyData & Keys.Control) != 0;
        int digit = k >= Keys.D2 && k <= Keys.D9 ? (int)k - (int)Keys.D0
                  : k >= Keys.NumPad2 && k <= Keys.NumPad9 ? (int)k - (int)Keys.NumPad0 : 0;
        if (digit >= 2) { ZoomCenter(digit); return true; }                  // 2..9 = 200% .. 900%
        switch (k)
        {
            case Keys.Right: case Keys.PageDown: case Keys.Space: Step(1); return true;
            case Keys.Left: case Keys.PageUp: case Keys.Back: Step(-1); return true;
            case Keys.Home: GoTo(0); return true;
            case Keys.End: GoTo(files.Count - 1); return true;
            case Keys.Add: case Keys.Oemplus: ZoomCenter(NextZoom(1)); return true;
            case Keys.Subtract: case Keys.OemMinus: ZoomCenter(NextZoom(-1)); return true;
            case Keys.F: if (ctrl) break; ToggleFitLock(); return true;
            case Keys.D0: case Keys.NumPad0: SetFit(2); return true;
            case Keys.H: if (ctrl) break; Flip(true); return true;
            case Keys.V: if (ctrl) break; Flip(false); return true;
            case Keys.B: if (ctrl) break; ToggleChecker(); return true;
            case Keys.D1: case Keys.NumPad1: ZoomCenter(1); return true;
            case Keys.R: Rotate(shift ? -1 : 1); return true;
            case Keys.L: Rotate(-1); return true;
            case Keys.I: showInfo = !showInfo; Invalidate(); return true;
            case Keys.E:
                if (ctrl) break;
                showExif = !showExif;
                Invalidate();
                return true;
            case Keys.P: if (ctrl) break; ToggleAnimPause(); return true;
            case Keys.T:
                if (ctrl) break;
                TvAspect = !tvAspect;
                if (!tvAspect) Flash("True TV aspect off (pixels as RECOIL hands them over)");
                else if (HasImage && cur.Geom != null && cur.Geom.XPpm > 0)
                    Flash("True TV aspect on: each pixel " + cur.Geom.PixelAspect.ToString("0.00") + " wide : 1 high, as on a real TV");
                else Flash("True TV aspect on (not known for this picture: shown unchanged)");
                return true;
            case Keys.K:
                if (ctrl) break;
                ScanMode = (scanMode + 1) % 4;
                Flash("Scanlines: " + ScanNames[scanMode] + (scanMode > 0 && HasImage && cur.Note == null ? " (retro pictures only)" : scanMode > 0 ? " (shown from about 300%)" : ""));
                return true;
            case Keys.C:
                if (ctrl) break;
                SignalMode = (signalMode + 1) % 3;
                Flash("Video signal: " + SignalNames[signalMode] + (signalMode > 0 && HasImage && cur.Note == null ? " (retro pictures only)"
                      : signalMode == 1 ? " (colours soften a little)" : signalMode == 2 ? " (dithering blends, as on a TV)" : ""));
                return true;
            case Keys.J:
                if (ctrl) break;
                Filmstrip = !strip;
                Flash(strip ? (files.Count > 1 ? "Filmstrip on (click a thumbnail to show it)" : "Filmstrip on (shown when the folder has more than one picture)") : "Filmstrip off");
                return true;
            case Keys.Z:
                if (ctrl) break;
                if (!loupe && HasImage) { loupe = true; Invalidate(); }      // shown while Z is held down
                return true;
            case Keys.U:
                if (ctrl) break;
                CurveMode = (curveMode + 1) % 3;
                Flash("Screen curvature: " + CurveNames[curveMode] + (curveMode > 0 && HasImage && cur.Note == null ? " (retro pictures only)" : curveMode > 0 ? " (off at 800% and above)" : ""));
                return true;
            case Keys.W:
                if (ctrl) break;
                GlowMode = (glowMode + 1) % 3;
                Flash("Glow: " + GlowNames[glowMode] + (glowMode > 0 && HasImage && cur.Note == null ? " (retro pictures only)" : ""));
                return true;
            case Keys.A:
                if (ctrl) break;
                ToggleAuto();
                return true;
            case Keys.O:
                if (ctrl) break;
                EffectsOff = !fxOff;
                Flash(fxOff ? "Screen effects off: the picture as decoded   (O shows them again)" : "Screen effects on");
                return true;
            case Keys.M:
                if (ctrl) break;
                MaskMode = (maskMode + 1) % 4;
                Flash("Phosphor mask: " + MaskNames[maskMode] + (maskMode > 0 && HasImage && cur.Note == null ? " (retro pictures only)" : maskMode > 0 ? " (shown from 200%)" : ""));
                return true;
            case Keys.Oemcomma: StepFrame(-1); return true;
            case Keys.OemPeriod: StepFrame(1); return true;
            case Keys.S: if (ctrl) break; ToggleSlideshow(); return true;
            case Keys.G:
                if (ctrl) break;
                showGrid = !showGrid;
                Flash(showGrid ? "Pixel grid on (shown at 800% and above)" : "Pixel grid off");
                Invalidate();
                return true;
            case Keys.N: if (ctrl) break; CyclePixMode(); return true;
            case Keys.Up: if (!slideshow) break; ChangeSlide(1); return true;
            case Keys.Down: if (!slideshow) break; ChangeSlide(-1); return true;
        }
        return false;
    }

    // ---------------------------------------------------------------- navigation / loading

    void Step(int d)
    {
        int n = files.Count;
        if (n > 1) GoTo((((idx < 0 ? 0 : idx) + d) % n + n) % n);
    }

    void GoTo(int i)
    {
        if (i < 0 || i >= files.Count) return;
        if (slideshow) { slideTimer.Stop(); slideTimer.Start(); }      // a manual step restarts the countdown
        idx = i;
        want = files[i];
        Pic p;
        bool have = cache.TryGetValue(want, out p);
        if (have && p.Stamp != FileStamp(want))            // replaced, changed or re-made since it was read: read it again
        {
            cache.Remove(want);
            if (p == cur) { StopAnim(); cur = null; DropSharp(); DropFx(); DropComposite(); DropGlow(); }
            p.Dispose();
            stripStamps.Remove(want);
            have = false;
        }
        if (have) Display(p); else Request(want);
        Prefetch();
    }

    // the file's size and modified time in one number (0 if it is not there); kept with each decoded picture, so a
    // file that was deleted and made again under the same name (a new conversion, say) is never shown from memory
    static long FileStamp(string path)
    {
        try
        {
            var fi = new FileInfo(path);
            return fi.Exists ? fi.LastWriteTimeUtc.Ticks ^ (fi.Length * 1000003L) : 0;
        }
        catch (Exception) { return 0; }
    }

    void Prefetch()
    {
        int n = files.Count;
        if (n < 2 || idx < 0) return;
        Request(files[(idx + 1) % n]);
        Request(files[(idx + n - 1) % n]);
    }

    bool IsNear(string p)
    {
        int n = files.Count;
        if (idx < 0 || n == 0) return false;
        for (int d = -1; d <= 1; d++)
            if (string.Equals(files[((idx + d) % n + n) % n], p, StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    void Request(string path)
    {
        if (cache.ContainsKey(path) || pending.Contains(path)) return;
        pending.Add(path);
        Control host = FindForm();
        ThreadPool.QueueUserWorkItem(delegate
        {
            Pic p = Decode(path);
            if (!Util.Post(host, delegate { Loaded(p); })) p.Dispose();
        });
    }

    void Loaded(Pic p)
    {
        pending.Remove(p.FullPath);
        if (!IsNear(p.FullPath) || cache.ContainsKey(p.FullPath)) { p.Dispose(); return; }
        if (p.Stamp != FileStamp(p.FullPath))              // the file changed while it was being read: read it again
        {
            string again = p.FullPath;
            p.Dispose();
            Request(again);                                 // stops by itself once the file stays the same
            return;
        }
        cache[p.FullPath] = p;
        if (string.Equals(p.FullPath, want, StringComparison.OrdinalIgnoreCase)) Display(p);
    }

    void StopAnim() { animTimer.Stop(); frameCount = 0; animPaused = false; }

    bool AnimActive { get { return cur != null && cur.Anim && cur.Img != null && frameCount > 1; } }

    void StartAnim(Pic p)
    {
        frame = 0; frameCount = 0; animPaused = false;
        if (p.Frames != null)                              // animated WebP: frames already put together, delays in ms
        {
            frameCount = p.Frames.Count;
            frameDelays = (int[])p.Delays.Clone();
            p.Img = p.Frames[0];
            if (frameCount > 1) ScheduleFrame();
            return;
        }
        try
        {
            frameCount = p.Img.GetFrameCount(FrameDimension.Time);
            frameDelays = new int[Math.Max(1, frameCount)];
            byte[] d = null;
            try { if (Array.IndexOf(p.Img.PropertyIdList, 0x5100) >= 0) d = p.Img.GetPropertyItem(0x5100).Value; } catch (Exception) { }
            for (int i = 0; i < frameDelays.Length; i++)
            {
                int cs = d != null && d.Length >= i * 4 + 4 ? BitConverter.ToInt32(d, i * 4) : 10;   // 1/100 s per frame
                frameDelays[i] = cs < 2 ? 100 : Math.Min(cs * 10, 60000);                         // 0 or 1 means "fast": 100 ms, as browsers do
            }
            p.Img.SelectActiveFrame(FrameDimension.Time, 0);
        }
        catch (Exception) { frameCount = 0; }
        if (frameCount > 1) ScheduleFrame();
    }

    void ScheduleFrame()
    {
        animTimer.Stop();
        if (!AnimActive || animPaused || !Visible) return;
        animTimer.Interval = Math.Max(10, frameDelays[Math.Min(frame, frameDelays.Length - 1)]);
        animTimer.Start();
    }

    void ShowFrame(int f)
    {
        if (!AnimActive) return;
        frame = ((f % frameCount) + frameCount) % frameCount;
        if (cur.Frames != null) { if (frame < cur.Frames.Count) cur.Img = cur.Frames[frame]; }   // animated WebP: show that frame
        else try { cur.Img.SelectActiveFrame(FrameDimension.Time, frame); } catch (Exception) { }
        Invalidate();
    }

    void ToggleAnimPause()
    {
        if (!AnimActive) { Flash("This picture is not animated"); return; }   // animated GIF or WebP
        animPaused = !animPaused;
        if (animPaused) animTimer.Stop(); else ScheduleFrame();
        Flash(animPaused ? "Animation paused   (, and . step one frame)" : "Animation playing");
    }

    void StepFrame(int d)
    {
        if (!AnimActive) return;
        animPaused = true;
        animTimer.Stop();
        ShowFrame(frame + d);
    }

    void Clear() { StopAnim(); cur = null; notice = null; DropSharp(); DropFx(); DropComposite(); DropGlow(); Invalidate(); }

    void Display(Pic p)
    {
        StopAnim();
        cur = p;
        notice = p.Err != null ? "Can't open this file\n" + Path.GetFileName(p.FullPath) + "\n" + p.Err : null;
        rot = p.Rot;
        flipX = flipY = false;
        if (fitLock) fitMode = 2;                          // Fit-to-Screen on: fit the window (small pictures grow)
        else { fitMode = 0; zoom = 1; px = py = 0; }       // off: 100%, centred
        fast = false;
        if (p.Anim && p.Img != null) StartAnim(p);
        ApplyAuto();                                       // automatic effects: chosen for this picture's computer
        Refit();
        Trim();
        Invalidate();
        var h = ImageChanged;
        if (h != null) h(p.FullPath, idx);
    }

    // keep only the current picture and its two neighbours in memory
    void Trim()
    {
        var drop = new List<string>();
        foreach (KeyValuePair<string, Pic> kv in cache)
            if (kv.Value != cur && !IsNear(kv.Key)) drop.Add(kv.Key);
        foreach (string k in drop) { cache[k].Dispose(); cache.Remove(k); }
    }

    // runs on worker threads
    static Pic Decode(string path)
    {
        var p = new Pic { FullPath = path, Stamp = FileStamp(path) };   // taken before reading, so a change during it shows
        Image img = null; MemoryStream ms = null;
        try
        {
            if ((File.GetAttributes(path) & Util.CloudMask) != 0)
                throw new IOException("This file is a cloud placeholder that isn't stored on this PC, so it was not opened. RetroGleek never goes online.");
            if (!Util.IsNative(path) && Retro.Claims(path))
            {
                long size; string platform;
                int frames; RetroGeom geom;
                p.Img = Retro.Load(path, out size, out platform, out frames, out geom);
                p.Bytes = size; p.W = p.Img.Width; p.H = p.Img.Height; p.Note = platform; p.Geom = geom;
                return p;
            }
            if (WinCodec.Claims(path))                         // WebP, AVIF, HEIC, JPEG XL, camera RAW ... (Windows' own decoders)
            {
                if (WebpAnim.IsWebp(path))                     // an animated WebP: every frame, played on the GIF clock
                {
                    List<Bitmap> frames = null;
                    int[] delays;
                    long size;
                    try { if (!WebpAnim.TryLoad(path, out frames, out delays, out size)) frames = null; else { p.Delays = delays; p.Bytes = size; } }
                    catch (Exception) { frames = null; }      // a damaged animation: the still decoder below says why
                    if (frames != null)
                    {
                        p.Frames = frames; p.Img = frames[0]; p.W = frames[0].Width; p.H = frames[0].Height; p.Anim = true;
                        return p;
                    }
                }
                CodecPic c;
                try { c = WinCodec.Load(path, 0, true); }
                catch (Exception cex) { throw new IOException(WinCodec.Why(path, cex)); }
                p.Img = c.Bmp; p.W = c.W; p.H = c.H; p.Rot = c.Rot; p.FileStars = c.Stars;
                p.Bytes = c.Bytes; p.Exif = c.Exif;                // Note stays null: Note marks a retro picture
                return p;
            }
            byte[] bytes = Util.ReadShared(path);             // one fast sequential read, no lock afterwards
            p.Bytes = bytes.Length;
            ms = new MemoryStream(bytes, false);
            img = Image.FromStream(ms, false, false);          // skip colour management + validation = faster
            p.W = img.Width; p.H = img.Height;
            p.Rot = Util.ReadRotation(img);
            p.Exif = ExifInfo.Read(img);                      // read now: the original is dropped after decoding
            if (FileRating.MayHold(path)) p.FileStars = FileRating.Read(path, img);

            bool anim = false;
            try { anim = ImageAnimator.CanAnimate(img); } catch (Exception) { }

            if (!anim && (long)p.W * p.H <= MaxPredecodePixels)
            {
                // Decode now, off the UI thread, into the format GDI+ draws fastest.
                var bmp = new Bitmap(p.W, p.H, PixelFormat.Format32bppPArgb);
                using (Graphics g = Graphics.FromImage(bmp))
                {
                    g.CompositingMode = CompositingMode.SourceCopy;
                    g.InterpolationMode = InterpolationMode.NearestNeighbor;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    g.DrawImage(img, new Rectangle(0, 0, p.W, p.H), 0, 0, p.W, p.H, GraphicsUnit.Pixel);
                }
                img.Dispose(); ms.Dispose();
                p.Img = bmp;
            }
            else { p.Img = img; p.Ms = ms; p.Anim = anim; }    // animated GIF or gigantic image: keep lazy
        }
        catch (Exception ex)
        {
            if (img != null) img.Dispose();
            if (ms != null) ms.Dispose();
            p.Img = null; p.Ms = null;
            p.Err = ex is OutOfMemoryException ? "Unsupported, damaged or too large." : ex.Message;
        }
        return p;
    }

    // ---------------------------------------------------------------- view maths

    bool HasImage { get { return cur != null && cur.Img != null; } }
    // the picture's size on screen at 100% (with True TV aspect, its own width is stretched or squeezed)
    double RW { get { return !HasImage ? 1 : ((rot & 1) == 0 ? cur.W * Ax : cur.H); } }
    double RH { get { return !HasImage ? 1 : ((rot & 1) == 0 ? cur.H : cur.W * Ax); } }

    void Refit()
    {
        if (!HasImage) return;
        if (fitMode == 0) { Clamp(); return; }
        double cw = ClientSize.Width, ch = ViewH;
        if (cw < 1 || ch < 1) return;
        double z = Math.Min(cw / RW, ch / RH);
        if (fitMode == 1 && z > 1) z = 1;
        if (ScanApplies && z >= 2) z = Math.Floor(z);   // scanlines: the largest whole-number size that fits, so every line is equally thick
        zoom = z; px = py = 0;
    }

    void Clamp()
    {
        if (!HasImage) return;
        double mx = Math.Max(0, (RW * zoom - ClientSize.Width) / 2);
        double my = Math.Max(0, (RH * zoom - ViewH) / 2);
        px = Math.Max(-mx, Math.Min(mx, px));
        py = Math.Max(-my, Math.Min(my, py));
    }

    // Low-quality interpolation while the user is interacting, high quality once things settle.
    void Interact()
    {
        fast = true;
        settle.Stop(); settle.Start();
        Invalidate();
    }

    void SetFit(int mode)
    {
        if (!HasImage) return;
        fitMode = mode; fast = false;
        Refit(); Invalidate();
        RaiseView();
    }

    void ZoomTo(double nz, double sx, double sy)
    {
        if (!HasImage) return;
        nz = Math.Max(0.01, Math.Min(64, nz));
        double cx = ClientSize.Width / 2.0, cy = ViewH / 2.0, k = nz / zoom;
        px = (sx - cx) - ((sx - cx) - px) * k;       // keeps the point under the cursor fixed
        py = (sy - cy) - ((sy - cy) - py) * k;
        zoom = nz; fitMode = 0;
        Clamp(); Interact();
        RaiseView();
    }

    void ZoomCenter(double nz) { ZoomTo(nz, ClientSize.Width / 2.0, ViewH / 2.0); }

    void Rotate(int d)
    {
        if (!HasImage) return;
        rot = (rot + d + 4) & 3;
        px = py = 0;
        Refit(); Invalidate();
    }

    // ---------------------------------------------------------------- painting

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(Bg);

        if (StripShown) g.SetClip(new Rectangle(0, 0, ClientSize.Width, ViewH));
        if (HasImage)
        {
            bool sharp = pixMode == 3 || (pixMode == 0 && cur.Note != null);          // retro pictures are pixel art
            bool crisp = pixMode == 1 || sharp;
            bool exact = Math.Abs(zoom - 1) < 1e-6 || (pixMode != 2 && zoom >= 3) || (zoom > 1 && crisp);
            bool scan = ScanShown, mask = MaskShown, glow = GlowShown, curve = CurveShown;
            if (scan || mask || glow || curve)
            {
                // CRT effects: the picture is drawn into a buffer of its on-screen area, then shaded pixel by pixel
                Rectangle r = PicScreenRect();
                Bitmap fx = r.Width > 0 && r.Height > 0 ? EffectFrame(r, sharp, exact, scan, mask, glow, curve) : null;
                if (fx != null)
                {
                    g.CompositingMode = CompositingMode.SourceCopy;
                    g.InterpolationMode = InterpolationMode.NearestNeighbor;
                    g.PixelOffsetMode = PixelOffsetMode.None;
                    g.DrawImage(fx, r, 0, 0, r.Width, r.Height, GraphicsUnit.Pixel);
                    g.CompositingMode = CompositingMode.SourceOver;
                }
                else { if (checker) DrawChecker(g); PicTransform(g); DrawPic(g, sharp, exact); g.ResetTransform(); }
            }
            else { if (checker) DrawChecker(g); PicTransform(g); DrawPic(g, sharp, exact); g.ResetTransform(); }
            g.PixelOffsetMode = PixelOffsetMode.Half;
            PicTransform(g);                                                         // for the pixel grid and outline

            int hx = -1, hy = -1;
            bool hov = mouseIn && !dragging && PixelAt(mousePt, out hx, out hy);
            if (zoom >= 8 && (showGrid || hov)) DrawPixelTools(g, hov, hx, hy);
            g.ResetTransform();
            if (loupe && mouseIn && !dragging) DrawLoupe(g, hov, hx, hy);
            if (showInfo) DrawInfo(g, hov, hx, hy);
        }

        if (notice != null)
        {
            g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
            using (var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                g.DrawString(notice, big, Brushes.Gray, new RectangleF(20, 0, ClientSize.Width - 40, ClientSize.Height), sf);
        }
        if (StripShown) { g.ResetClip(); DrawStrip(g); }
        if (showExif && HasImage) DrawExif(g);
        if (flash != null) DrawFlash(g);
    }

    int StripCell { get { return Util.S(76); } }

    // first file index shown in the strip, so the current picture sits in the middle
    int StripFirst(out int count)
    {
        int cell = StripCell;
        count = Math.Max(1, ClientSize.Width / cell);
        int first = (idx < 0 ? 0 : idx) - count / 2;
        return Math.Max(0, Math.Min(first, Math.Max(0, files.Count - count)));
    }

    long StripStamp(string path)
    {
        long st;
        if (stripStamps.TryGetValue(path, out st)) return st;
        try { var fi = new FileInfo(path); st = fi.Exists ? fi.LastWriteTimeUtc.Ticks ^ fi.Length : 0; } catch (Exception) { st = 0; }
        stripStamps[path] = st;
        return st;
    }

    void DrawStrip(Graphics g)
    {
        int top = ClientSize.Height - StripH, cell = StripCell, thumb = Util.S(64), count;
        using (var bb = new SolidBrush(Color.FromArgb(32, 32, 32))) g.FillRectangle(bb, 0, top, ClientSize.Width, StripH);
        using (var line = new Pen(Color.FromArgb(52, 52, 52))) g.DrawLine(line, 0, top, ClientSize.Width, top);
        int first = StripFirst(out count);
        int x0 = Math.Max(0, (ClientSize.Width - Math.Min(count, files.Count) * cell) / 2);
        var jobs = new List<ThumbJob>();
        InterpolationMode oldI = g.InterpolationMode;
        g.InterpolationMode = InterpolationMode.Bilinear;
        for (int k = 0; k < count && first + k < files.Count; k++)
        {
            int i = first + k;
            string p = files[i];
            var box = new Rectangle(x0 + k * cell + (cell - thumb) / 2, top + (StripH - thumb) / 2, thumb, thumb);
            long st = StripStamp(p);
            int bs;
            Bitmap b = stripCache.Get(p, st, out bs);
            if (b != null)
            {
                double f = Math.Min(1.0, Math.Min((double)thumb / b.Width, (double)thumb / b.Height));
                int dw = Math.Max(1, (int)(b.Width * f)), dh = Math.Max(1, (int)(b.Height * f));
                g.DrawImage(b, box.X + (thumb - dw) / 2, box.Y + (thumb - dh) / 2, dw, dh);
            }
            else
            {
                using (var ph = new SolidBrush(Color.FromArgb(44, 44, 44))) g.FillRectangle(ph, box.X + thumb / 6, box.Y + thumb / 6, thumb * 2 / 3, thumb * 2 / 3);
                if (st != 0) jobs.Add(new ThumbJob { Path = p, Size = thumb, Stamp = st });
            }
            if (i == idx)
                using (var sel = new Pen(Color.FromArgb(60, 130, 230), Math.Max(2f, Util.K * 2f))) g.DrawRectangle(sel, box.X - 3, box.Y - 3, thumb + 5, thumb + 5);
        }
        g.InterpolationMode = oldI;
        if (jobs.Count > 0)
        {
            if (stripSvc == null) stripSvc = new ThumbService(1, StripThumb);
            stripHost = FindForm();
            stripSvc.Replace(jobs);
        }
    }

    void StripThumb(ThumbJob j, ThumbResult r)        // worker thread
    {
        Control h = stripHost;
        if (!Util.Post(h, delegate
        {
            if (r.Bmp == null) return;
            stripCache.Put(j.Path, j.Stamp, j.Size, r);
            if (StripShown) Invalidate(new Rectangle(0, ClientSize.Height - StripH, ClientSize.Width, StripH));
        }) && r.Bmp != null) r.Bmp.Dispose();
    }

    // the file index of the strip thumbnail at a window point, or -1
    int StripHit(Point p)
    {
        if (!StripShown || p.Y < ClientSize.Height - StripH) return -1;
        int count, first = StripFirst(out count), cell = StripCell;
        int x0 = Math.Max(0, (ClientSize.Width - Math.Min(count, files.Count) * cell) / 2);
        if (p.X < x0) return -1;
        int i = first + (p.X - x0) / cell;
        return i < files.Count && (p.X - x0) / cell < count ? i : -1;
    }

    // drawn while the picture's transform is active, so everything is in picture-pixel coordinates
    void DrawPixelTools(Graphics g, bool hov, int hx, int hy)
    {
        float inv = (float)(1.0 / zoom);                                               // one screen pixel, in picture units
        if (showGrid)
        {
            using (Matrix m = g.Transform)
            {
                m.Invert();
                PointF[] c = { new PointF(0, 0), new PointF(ClientSize.Width, 0), new PointF(0, ClientSize.Height), new PointF(ClientSize.Width, ClientSize.Height) };
                m.TransformPoints(c);
                float minX = Math.Min(Math.Min(c[0].X, c[1].X), Math.Min(c[2].X, c[3].X));
                float maxX = Math.Max(Math.Max(c[0].X, c[1].X), Math.Max(c[2].X, c[3].X));
                float minY = Math.Min(Math.Min(c[0].Y, c[1].Y), Math.Min(c[2].Y, c[3].Y));
                float maxY = Math.Max(Math.Max(c[0].Y, c[1].Y), Math.Max(c[2].Y, c[3].Y));
                int x0 = Math.Max(0, (int)Math.Floor(minX)), x1 = Math.Min(cur.W, (int)Math.Ceiling(maxX));
                int y0 = Math.Max(0, (int)Math.Floor(minY)), y1 = Math.Min(cur.H, (int)Math.Ceiling(maxY));
                using (var pen = new Pen(Color.FromArgb(90, 128, 128, 128), inv))
                {
                    for (int x = x0; x <= x1; x++) g.DrawLine(pen, x, y0, x, y1);
                    for (int y = y0; y <= y1; y++) g.DrawLine(pen, x0, y, x1, y);
                }
            }
        }
        if (hov)
            using (var pen = new Pen(Color.FromArgb(230, 255, 220, 0), 2f * inv)) g.DrawRectangle(pen, hx, hy, 1, 1);
    }

    // ---- Sharp enlargement (sharp-bilinear, as used by RetroArch): at a size that is not a whole number, plain
    // nearest-neighbour makes some pixel columns and rows one screen pixel wider than others. Instead the picture is
    // first enlarged by whole numbers with hard edges (the next whole number above the zoom, per direction), and that
    // copy is then shrunk smoothly to the exact size. Every pixel ends up the same size, and only the one screen pixel
    // where two picture pixels meet is blended. At whole-number sizes nothing changes. Display only.
    const long MaxSharpPixels = 24000000L;                 // about 96 MB for the enlarged copy; above that: crisp
    Bitmap sharpBmp;
    Image sharpOf;
    int sharpFx, sharpFy, sharpFrame = -1;

    void DropSharp()
    {
        if (sharpBmp != null) sharpBmp.Dispose();
        sharpBmp = null; sharpOf = null; sharpFrame = -1;
    }

    // sx, sy = the picture's scale across and down; null when plain drawing is already exact (or the copy is too big)
    Bitmap SharpSource(Image src, int sw, int sh, double sx, double sy)
    {
        const double eps = 1e-4;
        if (sx <= 1 + eps && sy <= 1 + eps) return null;                       // not enlarged: nothing uneven to fix
        bool wholeX = Math.Abs(sx - Math.Round(sx)) < eps, wholeY = Math.Abs(sy - Math.Round(sy)) < eps;
        if (wholeX && wholeY) return null;                                     // whole numbers: nearest is exact
        int fx = wholeX ? (int)Math.Round(sx) : (int)Math.Ceiling(sx);
        int fy = wholeY ? (int)Math.Round(sy) : (int)Math.Ceiling(sy);
        fx = Math.Max(1, fx); fy = Math.Max(1, fy);
        if ((long)sw * fx * sh * fy > MaxSharpPixels) return null;
        int f = AnimActive ? frame : 0;
        if (sharpBmp != null && sharpOf == src && sharpFx == fx && sharpFy == fy && sharpFrame == f) return sharpBmp;
        DropSharp();
        try
        {
            var b = new Bitmap(sw * fx, sh * fy, PixelFormat.Format32bppPArgb);
            using (Graphics tg = Graphics.FromImage(b))
            {
                tg.CompositingMode = CompositingMode.SourceCopy;
                tg.InterpolationMode = InterpolationMode.NearestNeighbor;
                tg.PixelOffsetMode = PixelOffsetMode.Half;
                tg.DrawImage(src, new Rectangle(0, 0, b.Width, b.Height), 0, 0, sw, sh, GraphicsUnit.Pixel, ia);
            }
            sharpBmp = b; sharpOf = src; sharpFx = fx; sharpFy = fy; sharpFrame = f;
        }
        catch (Exception) { DropSharp(); }                                     // out of memory: fall back to crisp
        return sharpBmp;
    }

    // ---- Video signal (C): S-Video and composite, worked out once per picture (and frame) and kept.
    // The picture is split into brightness (Y) and colour (U, V), as a PAL / NTSC signal carries them, and each is
    // blurred along the line by the signal's limited bandwidth: colour much more than brightness, and both more for
    // composite than for S-Video. This is what made 1-pixel dithering (checkerboards, stripes) blend into a solid
    // in-between colour on a TV. Blur widths are in pixels of a 320-pixel-wide line, so hires pictures get the same
    // blur on screen. Four samples per pixel across keep the result smooth when enlarged; lines stay separate.
    // Not modelled: cross-colour rainbows and dot crawl, which depend on each machine's exact timing.
    Bitmap compBmp;
    Image compOf;
    int compMode, compFrame = -1;
    const long MaxCompositeSamples = 16000000L;

    void DropComposite()
    {
        if (compBmp != null) compBmp.Dispose();
        compBmp = null; compOf = null; compFrame = -1;
    }

    Bitmap CompositeSource()
    {
        int f = AnimActive ? frame : 0;
        if (compBmp != null && compOf == cur.Img && compMode == signalMode && compFrame == f) return compBmp;
        DropComposite();
        int w = cur.W, h = cur.H;
        int k = (long)w * 4 * h <= MaxCompositeSamples ? 4 : (long)w * 2 * h <= MaxCompositeSamples ? 2 : 1;
        double unit = Math.Max(0.75, w / 320.0) * k;           // samples per pixel of a 320-pixel line
        double sy = (signalMode == 2 ? 0.65 : 0.35) * unit;    // brightness blur (Gaussian sigma, in samples)
        double sc = (signalMode == 2 ? 2.2 : 1.2) * unit;      // colour blur
        try
        {
            int[] src = new int[w * h];
            using (var tmp = new Bitmap(w, h, PixelFormat.Format32bppArgb))
            {
                using (Graphics tg = Graphics.FromImage(tmp))
                {
                    tg.CompositingMode = CompositingMode.SourceCopy;
                    tg.InterpolationMode = InterpolationMode.NearestNeighbor;
                    tg.PixelOffsetMode = PixelOffsetMode.Half;
                    tg.DrawImage(cur.Img, new Rectangle(0, 0, w, h), 0, 0, w, h, GraphicsUnit.Pixel);
                }
                BitmapData bd = tmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try { for (int y = 0; y < h; y++) Marshal.Copy(bd.Scan0 + y * bd.Stride, src, y * w, w); }
                finally { tmp.UnlockBits(bd); }
            }
            int n = w * k;
            int[] dst = new int[n * h];
            float[] Y = new float[n], U = new float[n], V = new float[n], t = new float[n];
            for (int y = 0; y < h; y++)
            {
                for (int x = 0; x < w; x++)
                {
                    int c = src[y * w + x];
                    float r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
                    float yy = 0.299f * r + 0.587f * g + 0.114f * b;
                    float u = 0.492f * (b - yy), v = 0.877f * (r - yy);
                    for (int j = 0; j < k; j++) { Y[x * k + j] = yy; U[x * k + j] = u; V[x * k + j] = v; }
                }
                Blur(Y, t, sy); Blur(U, t, sc); Blur(V, t, sc);
                for (int i = 0; i < n; i++)
                {
                    float yy = Y[i], u = U[i], v = V[i];
                    int r = Clamp255(yy + 1.140f * v), g = Clamp255(yy - 0.395f * u - 0.581f * v), b = Clamp255(yy + 2.032f * u);
                    dst[y * n + i] = (int)(0xFF000000u | (uint)(r << 16) | (uint)(g << 8) | (uint)b);
                }
            }
            var bmp = new Bitmap(n, h, PixelFormat.Format32bppArgb);
            BitmapData od = bmp.LockBits(new Rectangle(0, 0, n, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            try { for (int y = 0; y < h; y++) Marshal.Copy(dst, y * n, od.Scan0 + y * od.Stride, n); }
            finally { bmp.UnlockBits(od); }
            compBmp = bmp; compOf = cur.Img; compMode = signalMode; compFrame = f;
        }
        catch (Exception) { DropComposite(); }                     // out of memory: shown as RGB
        return compBmp;
    }

    static int Clamp255(float v) { return v <= 0 ? 0 : v >= 255 ? 255 : (int)(v + 0.5f); }

    // Gaussian blur of one line, approximated by three box blurs (edges repeat the end samples)
    static void Blur(float[] a, float[] t, double sigma)
    {
        int rad = (int)Math.Round((Math.Sqrt(4 * sigma * sigma + 1) - 1) / 2);    // box of width 2r+1, three passes
        if (rad < 1) return;
        for (int pass = 0; pass < 3; pass++)
        {
            float[] from = (pass & 1) == 0 ? a : t, to = (pass & 1) == 0 ? t : a;
            int n = from.Length;
            float sum = 0, inv = 1f / (2 * rad + 1);
            for (int i = -rad; i <= rad; i++) sum += from[Math.Max(0, Math.Min(n - 1, i))];
            for (int i = 0; i < n; i++)
            {
                to[i] = sum * inv;
                sum += from[Math.Min(n - 1, i + rad + 1)] - from[Math.Max(0, i - rad)];
            }
        }
        Array.Copy(t, a, a.Length);                                 // three passes end in t
    }

    // ---- Glow (W). Worked out once per picture (and frame): the bright parts of the picture (brightness squared, so
    // dark colours hardly glow) are blurred by about one to two original screen lines. When drawing, that halo is
    // enlarged smoothly to the picture's size on screen and added on top of the picture, after scanlines and mask.
    Bitmap glowBmp, glowLayerBmp;
    Image glowOf;
    int glowFrame = -1;
    int[] glowPix;

    void DropGlow()
    {
        if (glowBmp != null) glowBmp.Dispose();
        if (glowLayerBmp != null) glowLayerBmp.Dispose();
        glowBmp = null; glowLayerBmp = null; glowOf = null; glowFrame = -1; glowPix = null;
    }

    Bitmap GlowSource()
    {
        int f = AnimActive ? frame : 0;
        if (glowBmp != null && glowOf == cur.Img && glowFrame == f) return glowBmp;
        if (glowBmp != null) glowBmp.Dispose();
        glowBmp = null;
        int w = cur.W, h = cur.H;
        if ((long)w * h > 16000000L) return null;
        int[] pix = new int[w * h];
        using (var tmp = new Bitmap(w, h, PixelFormat.Format32bppArgb))
        {
            using (Graphics tg = Graphics.FromImage(tmp))
            {
                tg.CompositingMode = CompositingMode.SourceCopy;
                tg.InterpolationMode = InterpolationMode.NearestNeighbor;
                tg.PixelOffsetMode = PixelOffsetMode.Half;
                tg.DrawImage(cur.Img, new Rectangle(0, 0, w, h), 0, 0, w, h, GraphicsUnit.Pixel);
            }
            BitmapData bd = tmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try { for (int y = 0; y < h; y++) Marshal.Copy(bd.Scan0 + y * bd.Stride, pix, y * w, w); }
            finally { tmp.UnlockBits(bd); }
        }
        var ch = new float[3][];
        for (int c = 0; c < 3; c++) ch[c] = new float[w * h];
        for (int i = 0; i < pix.Length; i++)
        {
            int v = pix[i];
            float r = (v >> 16) & 255, g = (v >> 8) & 255, b = v & 255;
            ch[0][i] = r * r / 255f; ch[1][i] = g * g / 255f; ch[2][i] = b * b / 255f;
        }
        double sigma = Math.Max(1.0, 1.5 * LineHeight);          // about one and a half original screen lines
        var rowBuf = new float[w]; var rowTmp = new float[w];
        var colBuf = new float[h]; var colTmp = new float[h];
        for (int c = 0; c < 3; c++)
        {
            float[] a = ch[c];
            for (int y = 0; y < h; y++) { Array.Copy(a, y * w, rowBuf, 0, w); Blur(rowBuf, rowTmp, sigma); Array.Copy(rowBuf, 0, a, y * w, w); }
            for (int x = 0; x < w; x++)
            {
                for (int y = 0; y < h; y++) colBuf[y] = a[y * w + x];
                Blur(colBuf, colTmp, sigma);
                for (int y = 0; y < h; y++) a[y * w + x] = colBuf[y];
            }
        }
        for (int i = 0; i < pix.Length; i++)
            pix[i] = (int)(0xFF000000u | (uint)(Clamp255(ch[0][i]) << 16) | (uint)(Clamp255(ch[1][i]) << 8) | (uint)Clamp255(ch[2][i]));
        var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        BitmapData od = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
        try { for (int y = 0; y < h; y++) Marshal.Copy(pix, y * w, od.Scan0 + y * od.Stride, w); }
        finally { bmp.UnlockBits(od); }
        glowBmp = bmp; glowOf = cur.Img; glowFrame = f;
        return glowBmp;
    }

    // the halo for the window area r, as packed colours (null if it could not be made)
    int[] GlowLayer(Rectangle r)
    {
        Bitmap src = GlowSource();
        if (src == null) return null;
        if (glowLayerBmp == null || glowLayerBmp.Width != r.Width || glowLayerBmp.Height != r.Height)
        {
            if (glowLayerBmp != null) glowLayerBmp.Dispose();
            glowLayerBmp = new Bitmap(r.Width, r.Height, PixelFormat.Format32bppArgb);
        }
        using (Graphics gg = Graphics.FromImage(glowLayerBmp))
        {
            gg.Clear(Color.Black);
            gg.TranslateTransform(-r.X, -r.Y);
            PicTransform(gg);
            gg.InterpolationMode = InterpolationMode.HighQualityBilinear;
            gg.PixelOffsetMode = PixelOffsetMode.Half;
            gg.DrawImage(src, new Rectangle(0, 0, cur.W, cur.H), 0, 0, cur.W, cur.H, GraphicsUnit.Pixel, ia);
        }
        int n = r.Width * r.Height;
        if (glowPix == null || glowPix.Length != n) glowPix = new int[n];
        BitmapData bd = glowLayerBmp.LockBits(new Rectangle(0, 0, r.Width, r.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try { for (int y = 0; y < r.Height; y++) Marshal.Copy(bd.Scan0 + y * bd.Stride, glowPix, y * r.Width, r.Width); }
        finally { glowLayerBmp.UnlockBits(bd); }
        return glowPix;
    }

    // the picture's transform: pan, rotate, zoom, True TV aspect, mirror (picture pixels -> window pixels)
    void PicTransform(Graphics g)
    {
        g.TranslateTransform((float)(ClientSize.Width / 2.0 + px), (float)(ViewH / 2.0 + py));
        g.RotateTransform(rot * 90f);
        g.ScaleTransform((float)zoom, (float)zoom);
        double ax = Ax;
        if (ax != 1.0) g.ScaleTransform((float)ax, 1f);                                // True TV aspect: the picture's own width
        if (flipX || flipY) g.ScaleTransform(flipX ? -1f : 1f, flipY ? -1f : 1f);     // mirror around the picture's centre
        g.TranslateTransform(-cur.W / 2f, -cur.H / 2f);
    }

    // draws the picture under PicTransform, crisp / sharp / smooth as chosen
    void DrawPic(Graphics g, bool sharp, bool exact)
    {
        g.InterpolationMode = exact ? InterpolationMode.NearestNeighbor
                            : fast ? InterpolationMode.Bilinear : InterpolationMode.HighQualityBicubic;
        g.PixelOffsetMode = PixelOffsetMode.Half;
        Image src = cur.Img;
        int sw = cur.W, sh = cur.H;
        Bitmap comp = SignalApplies ? CompositeSource() : null;
        if (comp != null)                                  // several samples per pixel across: always drawn the sharp way
        {
            src = comp; sw = comp.Width; sh = comp.Height; sharp = true;
        }
        Bitmap sb = sharp ? SharpSource(src, sw, sh, zoom * Ax * cur.W / sw, zoom * cur.H / sh) : null;
        if (sb != null)
        {
            g.InterpolationMode = fast ? InterpolationMode.Bilinear : InterpolationMode.HighQualityBilinear;
            g.DrawImage(sb, new Rectangle(0, 0, cur.W, cur.H), 0, 0, sb.Width, sb.Height, GraphicsUnit.Pixel, ia);
        }
        else
        {
            // whole-number enlargement: nearest keeps the lines sharp; 100% or smaller: average the samples across
            if (comp != null) g.InterpolationMode = zoom > 1 + 1e-6 ? InterpolationMode.NearestNeighbor
                                                 : fast ? InterpolationMode.Bilinear : InterpolationMode.HighQualityBilinear;
            g.DrawImage(src, new Rectangle(0, 0, cur.W, cur.H), 0, 0, sw, sh, GraphicsUnit.Pixel, ia);
        }
    }

    // the window pixels the picture covers (only the visible part)
    Rectangle PicScreenRect()
    {
        double w = RW * zoom, h = RH * zoom;
        double x = ClientSize.Width / 2.0 + px - w / 2, y = ViewH / 2.0 + py - h / 2;
        int x0 = (int)Math.Floor(x), y0 = (int)Math.Floor(y), x1 = (int)Math.Ceiling(x + w), y1 = (int)Math.Ceiling(y + h);
        return Rectangle.Intersect(Rectangle.FromLTRB(x0, y0, x1, y1), new Rectangle(0, 0, ClientSize.Width, ViewH));
    }

    // ---- CRT effects (K scanlines, M phosphor mask): display only, retro pictures, upright or upside down.
    // The visible part of the picture is drawn into a buffer, then each window pixel is shaded:
    //   scanlines: each original screen line is a soft beam, brightest in its middle. Bright colours make a wider beam
    //     that fills more of the dark gap, as on a real CRT; the whole picture is brightened to make up for the gaps.
    //   mask: a fixed pattern of red, green and blue stripes or dots in window pixels, so it stays put while panning.
    // The result is kept and reused until anything that changes it does (zoom, position, picture, frame, options).
    Bitmap fxBmp;
    Image fxOf;
    string fxKey;
    int[] fxPix, fxOut;
    int[] scanTab;                                         // 64 positions across a line x 16 brightness levels, x256
    int scanTabMode = -1;

    void DropFx()
    {
        if (fxBmp != null) fxBmp.Dispose();
        fxBmp = null; fxOf = null; fxKey = null; fxPix = null; fxOut = null;
    }

    Bitmap EffectFrame(Rectangle r, bool sharp, bool exact, bool scan, bool mask, bool glow, bool curve)
    {
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        string key = zoom.ToString("R", inv) + "|" + px.ToString("R", inv) + "|" + py.ToString("R", inv) + "|" + ClientSize.Width + "x" + ViewH
                   + "|" + r.X + "," + r.Y + "," + r.Width + "," + r.Height + "|" + rot + (flipX ? "h" : "") + (flipY ? "v" : "") + "|" + Ax.ToString("R", inv)
                   + "|" + (scan ? scanMode : 0) + "|" + (mask ? maskMode : 0) + "|" + (sharp ? "s" : "") + (exact ? "e" : "") + (fast ? "f" : "")
                   + (checker ? "c" : "") + "|" + (SignalApplies ? signalMode : 0) + "|" + (glow ? glowMode : 0) + "|" + (curve ? curveMode : 0) + "|" + (AnimActive ? frame : 0);
        if (fxBmp != null && fxOf == cur.Img && fxKey == key) return fxBmp;
        try
        {
            if (fxBmp == null || fxBmp.Width != r.Width || fxBmp.Height != r.Height)
            {
                DropFx();
                fxBmp = new Bitmap(r.Width, r.Height, PixelFormat.Format32bppArgb);
            }
            using (Graphics bg = Graphics.FromImage(fxBmp))
            {
                bg.Clear(Bg);
                bg.TranslateTransform(-r.X, -r.Y);
                if (checker) DrawChecker(bg);
                PicTransform(bg);
                DrawPic(bg, sharp, exact);
            }
            int[] halo = glow ? GlowLayer(r) : null;
            Shade(r, scan, mask, halo);
            if (curve) Warp(r);
            fxOf = cur.Img; fxKey = key;
            return fxBmp;
        }
        catch (Exception) { DropFx(); return null; }                           // out of memory: draw without effects
    }

    // Screen curvature: every window pixel of the visible picture area r looks up the point of the flat picture it
    // shows on a bulging screen (barrel distortion, as in crt-geom style shaders), smoothly between neighbours.
    // The visible area is the screen: zoomed in, the window is the glass. Corners are rounded and darkened.
    // Runs on fxPix (already shaded), after scanlines, mask and glow.
    void Warp(Rectangle r)
    {
        int w = r.Width, h = r.Height, n = w * h;
        if (w < 8 || h < 8) return;
        if (fxOut == null || fxOut.Length != n) fxOut = new int[n];
        double k = curveMode == 2 ? 0.07 : 0.03;                          // how much the glass bulges
        double vigPow = curveMode == 2 ? 0.28 : 0.16;                     // how dark the corners get
        double rad = Math.Max(4, Math.Min(w, h) * (curveMode == 2 ? 0.05 : 0.03));   // corner radius in pixels
        int bgc = Bg.ToArgb();
        int[] src = fxPix;
        for (int y = 0; y < h; y++)
        {
            double v = (y + 0.5) / h * 2 - 1;
            for (int x = 0; x < w; x++)
            {
                double u = (x + 0.5) / w * 2 - 1;
                double su = u * (1 + k * v * v), sv = v * (1 + k * u * u);     // where this pixel looks on the flat picture
                int o = y * w + x;
                if (su <= -1 || su >= 1 || sv <= -1 || sv >= 1) { fxOut[o] = bgc; continue; }
                double fx = (su + 1) / 2 * w - 0.5, fy = (sv + 1) / 2 * h - 0.5;
                int x0 = (int)Math.Floor(fx), y0 = (int)Math.Floor(fy);
                double ax = fx - x0, ay = fy - y0;
                int xa = Math.Max(0, Math.Min(w - 1, x0)), xb = Math.Max(0, Math.Min(w - 1, x0 + 1));
                int ya = Math.Max(0, Math.Min(h - 1, y0)), yb = Math.Max(0, Math.Min(h - 1, y0 + 1));
                int c00 = src[ya * w + xa], c10 = src[ya * w + xb], c01 = src[yb * w + xa], c11 = src[yb * w + xb];
                double w00 = (1 - ax) * (1 - ay), w10 = ax * (1 - ay), w01 = (1 - ax) * ay, w11 = ax * ay;
                double cr = ((c00 >> 16) & 255) * w00 + ((c10 >> 16) & 255) * w10 + ((c01 >> 16) & 255) * w01 + ((c11 >> 16) & 255) * w11;
                double cg = ((c00 >> 8) & 255) * w00 + ((c10 >> 8) & 255) * w10 + ((c01 >> 8) & 255) * w01 + ((c11 >> 8) & 255) * w11;
                double cb = (c00 & 255) * w00 + (c10 & 255) * w10 + (c01 & 255) * w01 + (c11 & 255) * w11;

                // vignette: darker towards the edges of the glass
                double tx = (su + 1) / 2, ty = (sv + 1) / 2;
                double vig = Math.Pow(Math.Max(0, 16 * tx * ty * (1 - tx) * (1 - ty)), vigPow);
                // rounded corners, with a soft one-pixel edge
                double px0 = tx * w, py0 = ty * h;
                double dx = Math.Max(0, Math.Abs(px0 - w / 2.0) - (w / 2.0 - rad)), dy = Math.Max(0, Math.Abs(py0 - h / 2.0) - (h / 2.0 - rad));
                double edge = Math.Max(0, Math.Min(1, rad - Math.Sqrt(dx * dx + dy * dy) + 0.5));
                double f = vig * edge, bgPart = 1 - edge;
                int rr = Clamp255((float)(cr * f + Bg.R * bgPart)), gg = Clamp255((float)(cg * f + Bg.G * bgPart)), bb = Clamp255((float)(cb * f + Bg.B * bgPart));
                fxOut[o] = (int)(0xFF000000u | (uint)(rr << 16) | (uint)(gg << 8) | (uint)bb);
            }
        }
        BitmapData bd = fxBmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
        try { for (int y = 0; y < h; y++) Marshal.Copy(fxOut, y * w, bd.Scan0 + y * bd.Stride, w); }
        finally { fxBmp.UnlockBits(bd); }
    }

    void BuildScanTable()
    {
        if (scanTabMode == scanMode && scanTab != null) return;
        double s = scanMode == 1 ? 0.35 : scanMode == 2 ? 0.55 : 0.75;         // how dark the gaps get
        var f = new double[64 * 16];
        double mid = 0;
        for (int p = 0; p < 64; p++)
        {
            double d = Math.Abs((p + 0.5) / 64 - 0.5) * 2;                     // 0 = middle of the line, 1 = its edge
            for (int l = 0; l < 16; l++)
            {
                double lum = (l + 0.5) / 16, h = 0.45 + 0.4 * lum;             // brighter = wider beam
                double w = Math.Exp(-2.2 * (d / h) * (d / h));
                f[p * 16 + l] = 1 - s * (1 - w);
                if (l == 8) mid += f[p * 16 + l] / 64;
            }
        }
        double gain = Math.Min(1.5, 1 / mid);                                  // keep mid-tones about as bright as before
        scanTab = new int[64 * 16];
        for (int i = 0; i < f.Length; i++) scanTab[i] = (int)Math.Round(f[i] * gain * 256);
        scanTabMode = scanMode;
    }

    void Shade(Rectangle r, bool scan, bool mask, int[] halo)
    {
        int w = r.Width, h = r.Height, n = w * h;
        if (fxPix == null || fxPix.Length != n) fxPix = new int[n];
        BitmapData bd = fxBmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
        try
        {
            for (int y = 0; y < h; y++) Marshal.Copy(bd.Scan0 + y * bd.Stride, fxPix, y * w, w);
            if (scan) BuildScanTable();
            int[] tab = scanTab;
            double lh = LineHeight, cy = ViewH / 2.0 + py;
            bool upside = rot == 2;
            int unit = Util.K >= 1.75f ? 2 : 1;                                 // phosphors twice as wide on very dense screens
            const int Lit = 333, Dim = 166;                                     // mask: 1.3 and 0.65 (x256)
            int gs = glowMode == 2 ? 170 : 100;                                 // glow strength (x256)
            for (int y = 0; y < h; y++)
            {
                int row = 0;
                if (scan)
                {
                    double v = (r.Y + y + 0.5 - cy) / zoom;                     // picture units from the picture's centre
                    if (upside) v = -v;
                    if (flipY) v = -v;
                    double t = (v + cur.H / 2.0) / lh;
                    int p = (int)((t - Math.Floor(t)) * 64);
                    row = Math.Max(0, Math.Min(63, p)) * 16;
                }
                int sy = (r.Y + y) / unit;
                for (int x = 0, i = y * w; x < w; x++, i++)
                {
                    int c = fxPix[i];
                    int cr = (c >> 16) & 255, cg = (c >> 8) & 255, cb = c & 255;
                    if (scan)
                    {
                        int k = tab[row + (((cr * 77 + cg * 150 + cb * 29) >> 8) >> 4)];
                        cr = cr * k >> 8; cg = cg * k >> 8; cb = cb * k >> 8;
                    }
                    if (mask)
                    {
                        int sx = (r.X + x) / unit, mr, mg, mb;
                        if (maskMode == 3)                                      // dot mask: magenta / green checker
                        {
                            if (((sx + sy) & 1) == 0) { mr = Lit; mg = Dim; mb = Lit; } else { mr = Dim; mg = Lit; mb = Dim; }
                        }
                        else
                        {
                            int ph = sx % 3;                                    // aperture grille: R, G, B stripes
                            mr = ph == 0 ? Lit : Dim; mg = ph == 1 ? Lit : Dim; mb = ph == 2 ? Lit : Dim;
                            if (maskMode == 2 && (sy + ((sx / 3) & 1) * 2) % 4 == 0) { mr = mr * 166 >> 8; mg = mg * 166 >> 8; mb = mb * 166 >> 8; }   // slot mask: staggered breaks
                        }
                        cr = cr * mr >> 8; cg = cg * mg >> 8; cb = cb * mb >> 8;
                    }
                    if (halo != null)                                           // glow: light added on top, like a CRT's glass
                    {
                        int hc = halo[i];
                        cr += ((hc >> 16) & 255) * gs >> 8; cg += ((hc >> 8) & 255) * gs >> 8; cb += (hc & 255) * gs >> 8;
                    }
                    if (cr > 255) cr = 255; if (cg > 255) cg = 255; if (cb > 255) cb = 255;
                    fxPix[i] = (int)(0xFF000000u | (uint)(cr << 16) | (uint)(cg << 8) | (uint)cb);
                }
            }
            for (int y = 0; y < h; y++) Marshal.Copy(fxPix, y * w, bd.Scan0 + y * bd.Stride, w);
        }
        finally { fxBmp.UnlockBits(bd); }
    }

    // stars, label and tag for the info bar, e.g. "    (3 stars)  Red  (tick) tagged" ("" without marks)
    string MarkText()
    {
        Mark m = CurMark;
        if ((m == null || m.Stars == 0) && cur != null && cur.FileStars > 0)          // only the file's own rating
            return "    " + Marks.StarText(cur.FileStars) + " (in the file)" + (m != null && !m.Empty ? "  " + MarkRest(m) : "");
        if (m == null || m.Empty) return "";
        return "    " + (m.Stars > 0 ? Marks.StarText(m.Stars) : "") + (m.Label > 0 ? (m.Stars > 0 ? "  " : "") + Marks.LabelNames[m.Label] : "")
             + (m.Tag ? (m.Stars > 0 || m.Label > 0 ? "  " : "") + "\u2714 tagged" : "");
    }

    // label and tag only (when the stars come from the file)
    static string MarkRest(Mark m)
    {
        return (m.Label > 0 ? Marks.LabelNames[m.Label] : "") + (m.Tag ? (m.Label > 0 ? "  " : "") + "\u2714 tagged" : "");
    }

    void DrawInfo(Graphics g, bool hov, int hx, int hy)
    {
        string s = Path.GetFileName(cur.FullPath) + "    " + cur.W + " x " + cur.H + "    " + Util.FmtSize(cur.Bytes)
                 + MarkText()
                 + (cur.Note != null ? "    " + cur.Note : "") + "    " + (int)Math.Round(zoom * 100) + "%" + (fitLock ? " (Fit)" : "")
                 + (flipX ? "    Flipped H" : "") + (flipY ? "    Flipped V" : "") + "    " + (idx + 1) + " / " + files.Count
                 + (slideshow ? "    Slideshow " + SlideSecs[slideIdx] + " s" : "")
                 + (AnimActive ? "    Frame " + (frame + 1) + " / " + frameCount + (animPaused ? " (paused)" : "") : "")
                 + (cur.Geom != null && cur.Geom.OrigW > 0 && (cur.Geom.OrigW != cur.W || cur.Geom.OrigH != cur.H) ? "    original " + cur.Geom.OrigW + " x " + cur.Geom.OrigH : "")
                 + (Ax != 1.0 ? "    TV aspect" : "")
                 + (ScanApplies ? (LineHeight * zoom >= 3 ? "    Scanlines " + ScanNames[scanMode] : "    Scanlines (from 300%)")
                    : ScanWanted ? "    Scanlines (off while turned sideways)" : "")
                 + (SignalApplies ? "    " + (signalMode == 1 ? "S-Video" : "Composite") : "")
                 + (GlowShown ? "    Glow " + GlowNames[glowMode] : "")
                 + (CurveShown ? "    Curved" : CurveWanted ? "    Curve (off from 800%)" : "")
                 + (fxOff ? "    Screen effects off (O)" : autoFx && autoChoice != null && cur.Note != null ? "    Auto effects" : "")
                 + (MaskApplies ? (MaskShown ? "    Mask " + MaskNames[maskMode] : "    Mask (from 200%)")
                    : MaskWanted ? "    Mask (off while turned sideways)" : "");
        float k = g.DpiY / 96f;
        int h = (int)(font.GetHeight(g) + 10 * k);
        var bar = new Rectangle(0, ViewH - h, ClientSize.Width, h);
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        using (var b = new SolidBrush(Color.FromArgb(170, 0, 0, 0))) g.FillRectangle(b, bar);

        float rightEdge = bar.Width - 10 * k;
        if (hov)                                                                       // pixel under the pointer
        {
            Color c = Color.Black;
            bool got = false;
            try { Bitmap bm = cur.Img as Bitmap; if (bm != null) { c = bm.GetPixel(hx, hy); got = true; } } catch (Exception) { }
            string rt = "x " + hx + "  y " + hy;
            if (got)
                rt += "   #" + c.R.ToString("X2") + c.G.ToString("X2") + c.B.ToString("X2")
                    + "   (" + c.R + ", " + c.G + ", " + c.B + (c.A != 255 ? ", a " + c.A : "") + ")";
            SizeF rs = g.MeasureString(rt, font);
            float tx = rightEdge - rs.Width, sw = 14 * k, sy = bar.Y + (bar.Height - sw) / 2;
            g.DrawString(rt, font, Brushes.Gainsboro, tx, bar.Y + (bar.Height - rs.Height) / 2);
            if (got)
            {
                float sx = tx - sw - 6 * k;
                using (var sb = new SolidBrush(Color.FromArgb(255, c))) g.FillRectangle(sb, sx, sy, sw, sw);
                g.DrawRectangle(Pens.Gray, sx, sy, sw, sw);
                rightEdge = sx - 12 * k;
            }
            else rightEdge = tx - 12 * k;
        }
        using (var sf = new StringFormat { LineAlignment = StringAlignment.Center, Trimming = StringTrimming.EllipsisCharacter, FormatFlags = StringFormatFlags.NoWrap })
            g.DrawString(s, font, Brushes.Gainsboro, new RectangleF(bar.X + 10 * k, bar.Y, Math.Max(0, rightEdge - 10 * k), bar.Height), sf);
    }

    // E: EXIF details in a box at the top right
    void DrawExif(Graphics g)
    {
        var lines = new List<string>();
        if (cur.Exif != null) lines.AddRange(cur.Exif);
        else lines.Add(cur.Note != null ? "Retro picture (" + cur.Note + "): no EXIF details" : "No EXIF details in this file");
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        float k = g.DpiY / 96f, lh = font.GetHeight(g), w = 0;
        foreach (string l in lines) w = Math.Max(w, g.MeasureString(l, font).Width);
        w = Math.Min(w, Math.Max(50, ClientSize.Width - 40 * k));
        var r = new RectangleF(ClientSize.Width - w - 26 * k, 10 * k, w + 16 * k, lines.Count * lh + 12 * k);
        using (var b = new SolidBrush(Color.FromArgb(200, 0, 0, 0))) g.FillRectangle(b, r);
        using (var sf = new StringFormat { Trimming = StringTrimming.EllipsisCharacter, FormatFlags = StringFormatFlags.NoWrap })
            for (int i = 0; i < lines.Count; i++)
                g.DrawString(lines[i], font, Brushes.Gainsboro, new RectangleF(r.X + 8 * k, r.Y + 6 * k + i * lh, w, lh), sf);
    }

    void DrawFlash(Graphics g)
    {
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        float k = g.DpiY / 96f;
        SizeF sz = g.MeasureString(flash, font);
        var r = new RectangleF(10 * k, 10 * k, sz.Width + 16 * k, sz.Height + 10 * k);
        using (var b = new SolidBrush(Color.FromArgb(200, 0, 0, 0))) g.FillRectangle(b, r);
        g.DrawString(flash, font, Brushes.White, r.X + 8 * k, r.Y + 5 * k);
    }

    // ---------------------------------------------------------------- input

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if (Visible) { Refit(); Invalidate(); ScheduleFrame(); } else { StopSlideshow(); animTimer.Stop(); }
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        Refit();
        Interact();
    }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        if ((ModifierKeys & Keys.Control) != 0)
        {
            ZoomTo(zoom * Math.Pow(1.2, e.Delta / 120.0), e.X, e.Y);
            return;
        }
        wheelAcc += e.Delta;                               // accumulate so touchpads don't skip images
        while (Math.Abs(wheelAcc) >= 120)
        {
            Step(wheelAcc > 0 ? -1 : 1);
            wheelAcc -= wheelAcc > 0 ? 120 : -120;
        }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (StripShown && e.Y >= ClientSize.Height - StripH)       // the filmstrip: show the clicked picture
        {
            int hit = StripHit(e.Location);
            if (e.Button == MouseButtons.Left && hit >= 0 && hit != idx) GoTo(hit);
            return;
        }
        if (e.Button == MouseButtons.Left && HasImage) { dragging = true; last = e.Location; Cursor = Cursors.SizeAll; }
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (!dragging) { UpdateHover(e.Location); if (loupe) Invalidate(); return; }
        px += e.X - last.X; py += e.Y - last.Y;
        last = e.Location;
        Clamp(); Interact();
        RaiseView();
    }

    // ---------------------------------------------------------------- pixel tools, slideshow, messages

    // The picture pixel under a window point (inverse of the paint transform: pan, then rotate, then zoom).
    bool PixelAt(Point s, out int ix, out int iy)
    {
        ix = iy = 0;
        double a, b;
        if (!PicPoint(s, out a, out b)) return false;
        ix = (int)Math.Floor(a);
        iy = (int)Math.Floor(b);
        return ix >= 0 && iy >= 0 && ix < cur.W && iy < cur.H;
    }

    // the exact point of the picture (in its own pixels, 0..W, 0..H) under a window point
    bool PicPoint(Point s, out double pa, out double pb)
    {
        pa = pb = 0;
        if (!HasImage || zoom <= 0) return false;
        double u = (s.X - (ClientSize.Width / 2.0 + px)) / zoom, v = (s.Y - (ViewH / 2.0 + py)) / zoom, a, b;
        switch (rot & 3)
        {
            case 0: a = u; b = v; break;
            case 1: a = v; b = -u; break;
            case 2: a = -u; b = -v; break;
            default: a = -v; b = u; break;
        }
        if (flipX) a = -a;
        if (flipY) b = -b;
        a /= Ax;                                          // undo the True TV aspect stretch
        pa = a + cur.W / 2.0;
        pb = b + cur.H / 2.0;
        return true;
    }

    // ---- loupe (hold Z): a round magnifier around the pointer, 4 times the current size (at least 400%,
    // at most 6400%), showing the picture's own pixels sharp (no screen effects) with the pixel under the pointer
    // outlined. Gone as soon as Z is let go.
    void DrawLoupe(Graphics g, bool hov, int hx, int hy)
    {
        double a, b;
        if (!PicPoint(mousePt, out a, out b)) return;
        int size = Util.S(240);
        float mag = (float)Math.Min(64, Math.Max(4, zoom * 4));
        var area = new Rectangle(mousePt.X - size / 2, mousePt.Y - size / 2, size, size);
        double ax = Ax;
        double reach = size / (2.0 * mag * Math.Min(1.0, ax)) + 2;                 // picture pixels the loupe can show
        int x0 = Math.Max(0, (int)Math.Floor(a - reach)), y0 = Math.Max(0, (int)Math.Floor(b - reach));
        int x1 = Math.Min(cur.W, (int)Math.Ceiling(a + reach)), y1 = Math.Min(cur.H, (int)Math.Ceiling(b + reach));
        GraphicsState st = g.Save();
        using (var path = new GraphicsPath())
        {
            path.AddEllipse(area);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var bg = new SolidBrush(Bg)) g.FillPath(bg, path);
            g.SetClip(path);
            g.SmoothingMode = SmoothingMode.None;
            g.InterpolationMode = InterpolationMode.NearestNeighbor;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.TranslateTransform(mousePt.X, mousePt.Y);
            g.RotateTransform(rot * 90f);
            g.ScaleTransform(mag, mag);
            if (ax != 1.0) g.ScaleTransform((float)ax, 1f);
            if (flipX || flipY) g.ScaleTransform(flipX ? -1f : 1f, flipY ? -1f : 1f);
            g.TranslateTransform((float)-a, (float)-b);
            if (x1 > x0 && y1 > y0)
                g.DrawImage(cur.Img, new Rectangle(x0, y0, x1 - x0, y1 - y0), x0, y0, x1 - x0, y1 - y0, GraphicsUnit.Pixel, ia);
            if (hov)
                using (var pen = new Pen(Color.FromArgb(230, 255, 220, 0), 2f / mag)) g.DrawRectangle(pen, hx, hy, 1, 1);
        }
        g.Restore(st);
        SmoothingMode old = g.SmoothingMode;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using (var ring = new Pen(Color.FromArgb(60, 130, 230), Math.Max(2f, Util.K * 2f))) g.DrawEllipse(ring, area);
        g.SmoothingMode = old;
        string label = (int)Math.Round(mag * 100) + "%";                          // the loupe's own size: picture pixels x mag
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        SizeF ls = g.MeasureString(label, font);
        var lr = new RectangleF(area.X + (area.Width - ls.Width) / 2 - 4, area.Bottom - ls.Height - Util.S(10), ls.Width + 8, ls.Height);
        using (var lb = new SolidBrush(Color.FromArgb(170, 0, 0, 0))) g.FillRectangle(lb, lr);
        g.DrawString(label, font, Brushes.Gainsboro, lr.X + 4, lr.Y);
    }

    protected override void OnKeyUp(KeyEventArgs e)
    {
        base.OnKeyUp(e);
        if (e.KeyCode == Keys.Z && loupe) { loupe = false; Invalidate(); }
    }

    protected override void OnLostFocus(EventArgs e)
    {
        base.OnLostFocus(e);
        if (loupe) { loupe = false; Invalidate(); }          // the key-up would go elsewhere
    }

    void UpdateHover(Point p)
    {
        if (StripShown && p.Y >= ClientSize.Height - StripH)       // over the filmstrip: no pixel readout or loupe
        {
            if (mouseIn) { mouseIn = false; lhx = lhy = -2; InvalidateReadout(); if (loupe) Invalidate(); }
            return;
        }
        mouseIn = true; mousePt = p;
        int ix, iy;
        if (!PixelAt(p, out ix, out iy)) { ix = -1; iy = -1; }
        if (ix == lhx && iy == lhy) return;
        lhx = ix; lhy = iy;
        InvalidateReadout();
    }

    // Repaint only the info bar for a moving pointer; the whole picture only when the pixel outline is shown.
    void InvalidateReadout()
    {
        if (zoom >= 8) { Invalidate(); return; }
        int h = font.Height + Util.S(14);
        Invalidate(new Rectangle(0, Math.Max(0, ViewH - h), ClientSize.Width, h));
    }

    // + / - : whole-number steps above 100%, so enlarged pixels stay square; 1.25x steps below
    double NextZoom(int dir)
    {
        const double eps = 1e-6;
        if (dir > 0)
        {
            if (zoom >= 1 - eps) return Math.Floor(zoom + eps) + 1;
            return Math.Min(1.0, zoom * 1.25);
        }
        if (zoom > 1 + eps) return Math.Max(1.0, Math.Ceiling(zoom - eps) - 1);
        return zoom / 1.25;
    }

    public void ToggleFitLock()
    {
        fitLock = !fitLock;
        if (!HasImage) { Flash(fitLock ? "Fit to screen: on" : "Fit to screen: off (100%)"); return; }
        if (fitLock) SetFit(2);
        else { fitMode = 0; zoom = 1; px = py = 0; fast = false; Clamp(); Invalidate(); }
        Flash(fitLock ? "Fit to screen: on (every picture fits the window)" : "Fit to screen: off (every picture opens at 100%)");
    }

    // H always flips left-right and V top-bottom as you see the picture, whatever its rotation
    void Flip(bool horizontal)
    {
        if (!HasImage) return;
        bool local = horizontal != ((rot & 1) == 1);       // turned on its side: the picture's own axes are swapped
        if (local) flipX = !flipX; else flipY = !flipY;
        Flash(horizontal ? "Flipped left-right" : "Flipped top-bottom");
        Invalidate();
    }

    public void ToggleChecker()
    {
        checker = !checker;
        Flash(checker ? "Checkerboard background on (shows transparency)" : "Checkerboard background off");
        Invalidate();
    }

    // checkerboard in window pixels behind the picture's on-screen rectangle
    void DrawChecker(Graphics g)
    {
        int cell = Math.Max(4, Util.S(8));
        if (checkerBrush == null || checkerCell != cell)
        {
            if (checkerBrush != null) checkerBrush.Dispose();
            using (var tileBmp = new Bitmap(cell * 2, cell * 2, PixelFormat.Format32bppArgb))
            {
                using (Graphics tg = Graphics.FromImage(tileBmp))
                using (var light = new SolidBrush(Color.FromArgb(102, 102, 102)))
                using (var dark = new SolidBrush(Color.FromArgb(68, 68, 68)))
                {
                    tg.FillRectangle(dark, 0, 0, cell * 2, cell * 2);
                    tg.FillRectangle(light, 0, 0, cell, cell);
                    tg.FillRectangle(light, cell, cell, cell, cell);
                }
                checkerBrush = new TextureBrush(tileBmp, WrapMode.Tile);   // the brush keeps its own copy
            }
            checkerCell = cell;
        }
        double w = RW * zoom, h = RH * zoom;
        double x = ClientSize.Width / 2.0 + px - w / 2, y = ViewH / 2.0 + py - h / 2;
        g.FillRectangle(checkerBrush, (float)x, (float)y, (float)w, (float)h);
    }

    void CyclePixMode()
    {
        // order: crisp -> sharp -> smooth -> crisp; "auto" starts from what it does for this picture
        int now = pixMode != 0 ? pixMode : cur != null && cur.Note != null ? 3 : 2;
        pixMode = now == 1 ? 3 : now == 3 ? 2 : 1;
        Flash(pixMode == 1 ? "Enlarged pixels: crisp" : pixMode == 3 ? "Enlarged pixels: sharp (even pixels at any size)"
                                                                 : "Enlarged pixels: smooth");
        Invalidate();
    }

    public void ShowMessage(string text) { Flash(text); }

    void Flash(string text)
    {
        flash = text;
        flashTimer.Stop(); flashTimer.Start();
        Invalidate();
    }

    void ToggleSlideshow()
    {
        if (slideshow) { StopSlideshow(); Flash("Slideshow stopped"); return; }
        if (files.Count < 2) { Flash("A slideshow needs at least two pictures"); return; }
        slideshow = true;
        if (strip && HasImage) { Refit(); Clamp(); }        // the filmstrip hides during a slideshow
        slideTimer.Interval = SlideSecs[slideIdx] * 1000;
        slideTimer.Start();
        Flash("Slideshow: " + SlideSecs[slideIdx] + " s per picture   (Up / Down = interval, S or Esc = stop)");
    }

    public void StopSlideshow()
    {
        if (!slideshow) return;
        slideshow = false;
        slideTimer.Stop();
        if (strip && HasImage) { Refit(); Clamp(); }
        Invalidate();
    }

    void ChangeSlide(int dir)                                                          // dir = +1: longer per picture
    {
        slideIdx = Math.Max(0, Math.Min(SlideSecs.Length - 1, slideIdx + dir));
        slideTimer.Interval = SlideSecs[slideIdx] * 1000;
        slideTimer.Stop(); slideTimer.Start();
        Flash("Slideshow: " + SlideSecs[slideIdx] + " s per picture");
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        base.OnMouseLeave(e);
        mouseIn = false; lhx = lhy = -2;
        InvalidateReadout();
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e);
        dragging = false; Cursor = Cursors.Default;
    }

    protected override void OnMouseDoubleClick(MouseEventArgs e)
    {
        base.OnMouseDoubleClick(e);
        if (!HasImage || (StripShown && e.Y >= ClientSize.Height - StripH)) return;
        if (Math.Abs(zoom - 1) < 1e-6) SetFit(2); else ZoomTo(1, e.X, e.Y);
    }
}
