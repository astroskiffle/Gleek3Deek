// RetroGleek - the main window: layout, folder tree, browsing and viewing (menus, file operations and keys are in MainForm.Files.cs)
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

// ====================================================================== main window

sealed partial class MainForm : Form
{
    const string Dummy = "\u0001dummy";

    Panel browse;
    Splitter splitter;
    Panel right, addrPanel, filterPanel;
    TextBox addrBox, filterBox;
    Button btnBack, btnFwd, btnUp, sortDirBtn;
    DarkCombo sortCombo, showCombo;
    bool autoAdvance;                                      // after marking a picture, move to the next one
    DarkSlider sizeSlider;
    ToolStripMenuItem gDetails, gSortDesc;
    readonly ToolStripMenuItem[] gSort = new ToolStripMenuItem[4];
    readonly ToolTip navTip = new ToolTip();
    readonly List<string> hist = new List<string>();
    int hpos = -1;
    string pendingNav;
    bool suppressFilter, suppressSort, suppressSize;
    TreeView tree;
    ThumbGrid grid;
    Canvas canvas;
    Label status;
    ImageList icons;
    TreeNode pcNode;
    ContextMenuStrip gridMenu, treeMenu;
    ToolStripMenuItem gInvert, gCut, tCut;
    Button subBtn, viewBtn;
    DetailHeader detailHeader;
    PreviewPane preview;                                   // Alt+P: large preview of the focused picture (off by default)
    Splitter previewSplit;
    ToolStripMenuItem gBatch, gFrames, gCompare;
    ToolStripMenuItem gOpen, gRename, gCopy, gPaste, gSave, gDelete, tRename, tCopy, tPaste, tDelete, tNew, gRetro, tRetro;

    readonly Dictionary<TreeNode, List<Action>> waiting = new Dictionary<TreeNode, List<Action>>();
    readonly Dictionary<TreeNode, string> driveDefault = new Dictionary<TreeNode, string>();
    readonly WinTimer navTimer = new WinTimer { Interval = 180 };

    // auto-refresh: watches the folder shown in the grid (files only, not subfolders) and rescans it shortly
    // after something changes there. Uses Windows' own change notifications for local drives; nothing goes online.
    FileSystemWatcher watcher;
    string watchedDir;
    bool watchedRecursive;
    readonly WinTimer refreshTimer = new WinTimer { Interval = 700 };
    string navPath, startArg;
    int revealToken;
    bool viewing, suppress, full;
    Control lastPane;
    FormBorderStyle oldStyle; FormWindowState oldState; Rectangle oldBounds;

    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int val, int size);

    public MainForm(string arg)
    {
        startArg = arg;
        AutoScaleMode = AutoScaleMode.None;
        Text = "RetroGleek";
        BackColor = Color.FromArgb(24, 24, 24);
        MinimumSize = new Size(Util.S(560), Util.S(360));
        Rectangle wa = Screen.PrimaryScreen.WorkingArea;
        ClientSize = new Size(wa.Width * 8 / 10, wa.Height * 8 / 10);
        StartPosition = FormStartPosition.CenterScreen;

        icons = new ImageList { ColorDepth = ColorDepth.Depth32Bit, ImageSize = new Size(Util.S(16), Util.S(16)) };
        for (int k = 0; k < 4; k++) icons.Images.Add(DrawIcon(k, Util.S(16)));

        tree = new TreeView
        {
            Dock = DockStyle.Left, Width = Util.S(280), BorderStyle = BorderStyle.None,
            BackColor = Color.FromArgb(32, 32, 32), ForeColor = Color.Gainsboro,
            HideSelection = false, ShowLines = false, FullRowSelect = true, HotTracking = true,
            ItemHeight = Util.S(22), Indent = Util.S(16), ImageList = icons, Font = new Font("Segoe UI", 9.5f)
        };
        Util.Dark(tree);
        tree.BeforeExpand += delegate (object s, TreeViewCancelEventArgs e) { EnsureLoaded(e.Node, null); };
        tree.AfterSelect += OnTreeSelect;
        tree.NodeMouseClick += OnTreeClick;
        tree.GotFocus += delegate { lastPane = tree; };

        grid = new ThumbGrid();
        grid.GotFocus += delegate { lastPane = grid; };
        grid.OpenRequested += OpenIndex;
        grid.ContextRequested += ShowGridMenu;
        grid.SelectionChanged += UpdateStatus;
        grid.SelectionChanged += UpdatePreview;
        grid.AnalyseProgress += delegate (int done, int total) { status.Text = "  Analysing " + done + " of " + total + " pictures (colours, frames, duplicates)..."; };
        grid.AnalyseFinished += delegate (int n, int bad, int dups)
        {
            if (n < 0) { UpdateStatus(); return; }
            status.Text = "  Analysed " + n + (n == 1 ? " picture" : " pictures") + ": " + bad + " could not be opened, " +
                          dups + (dups == 1 ? " duplicate" : " duplicates") + "   (Details view: Frames, Colours and Status columns)";
        };
        grid.Loaded += OnFolderLoaded;
        grid.ListChanged += delegate { UpdateStatus(); SyncCanvas(); SyncSortControls(); UpdatePreview(); };
        grid.TileStepChanged += delegate
        {
            suppressSize = true;
            try { sizeSlider.Value = grid.TileStep; } finally { suppressSize = false; }
        };
        grid.FilterCleared += delegate { suppressFilter = true; filterBox.Text = ""; suppressFilter = false; };
        lastPane = grid;

        canvas = new Canvas();
        canvas.ImageChanged += OnImageChanged;

        // browse pane: [tree | splitter | grid]; the fill control is added first, edge-docked ones after
        browse = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(24, 24, 24) };
        splitter = new Splitter
        {
            Dock = DockStyle.Left, Width = Util.S(5), MinSize = Util.S(140), MinExtra = Util.S(200),
            BackColor = Color.FromArgb(52, 52, 52)
        };
        // address bar (back / forward / up + path) across the top of the browser; filter bar above the thumbnails
        Color panelBg = Color.FromArgb(38, 38, 38), boxBg = Color.FromArgb(52, 52, 52);
        addrBox = new TextBox { Dock = DockStyle.Fill, BorderStyle = BorderStyle.FixedSingle, BackColor = boxBg, ForeColor = Color.White, Font = new Font("Segoe UI", 10f) };
        addrBox.KeyDown += AddrKeyDown;
        btnBack = NavButton(0, "Back (Alt+Left)", delegate { GoHistory(-1); grid.Focus(); });
        btnFwd = NavButton(1, "Forward (Alt+Right)", delegate { GoHistory(1); grid.Focus(); });
        btnUp = NavButton(2, "Up one folder (Alt+Up or Backspace)", delegate { GoUp(); grid.Focus(); });
        addrPanel = new Panel { Dock = DockStyle.Top, Height = Util.S(38), BackColor = panelBg, Padding = new Padding(Util.S(6), Util.S(6), Util.S(8), Util.S(6)) };
        addrPanel.Controls.Add(addrBox);
        addrPanel.Controls.Add(Spacer(6)); addrPanel.Controls.Add(btnUp);
        addrPanel.Controls.Add(Spacer(4)); addrPanel.Controls.Add(btnFwd);
        addrPanel.Controls.Add(Spacer(4)); addrPanel.Controls.Add(btnBack);

        filterBox = new TextBox { Dock = DockStyle.Fill, BorderStyle = BorderStyle.FixedSingle, BackColor = boxBg, ForeColor = Color.White, Font = new Font("Segoe UI", 10f) };
        filterBox.TextChanged += delegate { if (!suppressFilter) grid.SetFilter(filterBox.Text); };
        filterBox.KeyDown += FilterKeyDown;
        navTip.SetToolTip(filterBox, "Filter by name: part of a name, or * and ? wildcards; spaces mean \"and\".  Ctrl+F jumps here, Esc clears.");
        var fLab = new Label { Text = "Filter:", Dock = DockStyle.Left, Width = Util.S(50), TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.Silver, Font = new Font("Segoe UI", 9.5f) };

        // sort pull-down, direction button and thumbnail-size slider, to the right of the filter box
        int barH = Util.S(28);
        Font barFont = new Font("Segoe UI", 9.5f);
        var sortLab = new Label { Text = "Sort:", Left = 0, Top = 0, Width = Util.S(40), Height = barH, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.Silver, Font = barFont };
        sortCombo = new DarkCombo { Left = Util.S(40), Top = Math.Max(0, (barH - Util.S(26)) / 2), Width = Util.S(136), Height = Util.S(26), BackColor = boxBg, ForeColor = Color.White, Font = barFont };
        sortCombo.SetItems("Name", "Date modified", "Size", "Type", "Platform", "Dimensions", "Frames", "Colours", "Status", "Rating", "Label");
        sortCombo.SelectedIndex = 0;
        sortCombo.SelectedIndexChanged += delegate
        {
            int key = sortCombo.SelectedIndex;
            if (!suppressSort && key >= 0 && key != grid.SortKey) grid.SetSort(key, key == 1 || key == 2 || key == 5 || key == 6 || key == 7 || key == 9);   // newest / largest / most stars first
        };
        sortCombo.DropDownClosed += delegate { grid.Focus(); };
        navTip.SetToolTip(sortCombo, "Sort the pictures by name, date, size, type, platform, dimensions, frames, colours, status, rating or label");
        sortDirBtn = new Button { Left = Util.S(180), Top = Math.Max(0, (barH - Util.S(26)) / 2), Width = Util.S(30), Height = Util.S(26), TabStop = false, FlatStyle = FlatStyle.Flat, BackColor = boxBg };
        sortDirBtn.FlatAppearance.BorderSize = 0;
        sortDirBtn.FlatAppearance.MouseOverBackColor = Color.FromArgb(72, 72, 72);
        sortDirBtn.Click += delegate { grid.SetSort(grid.SortKey, !grid.SortDesc); grid.Focus(); };
        sortDirBtn.Paint += delegate (object sender, PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float cx = sortDirBtn.ClientSize.Width / 2f, cy = sortDirBtn.ClientSize.Height / 2f;
            float r = Math.Min(sortDirBtn.ClientSize.Width, sortDirBtn.ClientSize.Height) * 0.22f;
            PointF[] tri = grid.SortDesc
                ? new[] { new PointF(cx - r, cy - r * 0.6f), new PointF(cx + r, cy - r * 0.6f), new PointF(cx, cy + r * 0.8f) }     // pointing down
                : new[] { new PointF(cx - r, cy + r * 0.6f), new PointF(cx + r, cy + r * 0.6f), new PointF(cx, cy - r * 0.8f) };   // pointing up
            using (var br = new SolidBrush(Color.Gainsboro)) g.FillPolygon(br, tri);
        };
        navTip.SetToolTip(sortDirBtn, "Sort direction (click to reverse)");
        var sizeLab = new Label { Text = "Size:", Left = Util.S(222), Top = 0, Width = Util.S(38), Height = barH, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.Silver, Font = barFont };
        sizeSlider = new DarkSlider
        {
            Left = Util.S(262), Top = 0, Width = Util.S(150), Height = barH,
            Minimum = 0, Maximum = ThumbGrid.TileStepMax, Value = grid.TileStep, BackColor = panelBg
        };
        sizeSlider.ValueChanged += delegate { if (!suppressSize) grid.TileStep = sizeSlider.Value; };
        sizeSlider.MouseUp += delegate { grid.Focus(); };
        navTip.SetToolTip(sizeSlider, "Thumbnail size (Ctrl + mouse wheel also works)");
        var tools = new Panel { Dock = DockStyle.Right, Width = Util.S(416), BackColor = panelBg };
        tools.Controls.Add(sortLab); tools.Controls.Add(sortCombo); tools.Controls.Add(sortDirBtn);
        tools.Controls.Add(sizeLab); tools.Controls.Add(sizeSlider);

        filterPanel = new Panel { Dock = DockStyle.Top, Height = Util.S(38), BackColor = panelBg, Padding = new Padding(Util.S(8), Util.S(5), Util.S(8), Util.S(5)) };
        subBtn = new Button
        {
            Text = "Subfolders", Dock = DockStyle.Right, Width = Util.S(92), TabStop = false, FlatStyle = FlatStyle.Flat,
            BackColor = boxBg, ForeColor = Color.Gainsboro, Font = barFont
        };
        subBtn.FlatAppearance.BorderSize = 0;
        subBtn.FlatAppearance.MouseOverBackColor = Color.FromArgb(72, 72, 72);
        subBtn.Click += delegate { ToggleSubfolders(); grid.Focus(); };
        navTip.SetToolTip(subBtn, "Also list the pictures in all folders below this one (Ctrl+Shift+F)");
        viewBtn = new Button
        {
            Text = "Details", Dock = DockStyle.Right, Width = Util.S(72), TabStop = false, FlatStyle = FlatStyle.Flat,
            BackColor = boxBg, ForeColor = Color.Gainsboro, Font = barFont
        };
        viewBtn.FlatAppearance.BorderSize = 0;
        viewBtn.FlatAppearance.MouseOverBackColor = Color.FromArgb(72, 72, 72);
        viewBtn.Click += delegate { SetDetailsView(!grid.DetailsMode); grid.Focus(); };
        navTip.SetToolTip(viewBtn, "Switch between thumbnails and a details list (Ctrl+Shift+D)");

        filterPanel.Controls.Add(filterBox);      // fill first, edge-docked after
        filterPanel.Controls.Add(subBtn);
        filterPanel.Controls.Add(new Label { Dock = DockStyle.Right, Width = Util.S(6) });
        filterPanel.Controls.Add(viewBtn);
        filterPanel.Controls.Add(new Label { Dock = DockStyle.Right, Width = Util.S(8) });
        filterPanel.Controls.Add(tools);

        // Show pull-down (marks): all pictures, or only tagged / rated / colour-labelled ones
        var showLab = new Label { Text = "Show:", Left = Util.S(6), Top = 0, Width = Util.S(44), Height = barH, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.Silver, Font = barFont };
        showCombo = new DarkCombo { Left = Util.S(50), Top = Math.Max(0, (barH - Util.S(26)) / 2), Width = Util.S(140), Height = Util.S(26), BackColor = boxBg, ForeColor = Color.White, Font = barFont };
        showCombo.SetItems(ThumbGrid.ShowNames);
        showCombo.SelectedIndex = 0;
        showCombo.SelectedIndexChanged += delegate { if (showCombo.SelectedIndex >= 0) grid.ShowMode = showCombo.SelectedIndex; };
        showCombo.DropDownClosed += delegate { grid.Focus(); };
        navTip.SetToolTip(showCombo, "Show all pictures, or only tagged, rated or colour-labelled ones (Alt+0..5 rates, Shift+0..5 labels, X tags)");
        var showPanel = new Panel { Dock = DockStyle.Right, Width = Util.S(196), BackColor = panelBg };
        showPanel.Controls.Add(showLab); showPanel.Controls.Add(showCombo);
        filterPanel.Controls.Add(showPanel);
        filterPanel.Controls.Add(fLab);

        right = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(24, 24, 24) };
        detailHeader = new DetailHeader(grid) { Visible = false };
        right.Controls.Add(grid);                 // fill first, edge-docked after
        right.Controls.Add(detailHeader);         // column titles of the Details view, just above the grid
        preview = new PreviewPane { Dock = DockStyle.Right, Width = Util.S(320), Visible = false };
        previewSplit = new Splitter
        {
            Dock = DockStyle.Right, Width = Util.S(5), MinSize = Util.S(180), MinExtra = Util.S(240),
            BackColor = Color.FromArgb(52, 52, 52), Visible = false
        };
        right.Controls.Add(previewSplit);         // docks after the pane, so it sits on the pane's left edge
        right.Controls.Add(preview);              // beside the grid and its header, below the filter bar
        right.Controls.Add(filterPanel);
        browse.Controls.Add(right);
        browse.Controls.Add(splitter);
        browse.Controls.Add(tree);
        browse.Controls.Add(addrPanel);           // added last: docks first, so it spans the full width

        status = new Label
        {
            Dock = DockStyle.Bottom, Height = Util.S(24), TextAlign = ContentAlignment.MiddleLeft,
            BackColor = Color.FromArgb(38, 38, 38), ForeColor = Color.Gainsboro, Font = new Font("Segoe UI", 9f)
        };

        // fill-docked controls first, edge-docked ones after
        Controls.Add(browse);
        Controls.Add(canvas);
        BuildCompare();
        Controls.Add(comparePanel);
        Controls.Add(status);
        BuildMenuBar();
        Controls.Add(menuBar);                    // added last: docks first, so it spans the whole window
        MainMenuStrip = menuBar;

        BuildMenus();
        BuildRoots();

        navTimer.Tick += delegate { navTimer.Stop(); if (navPath != null) ShowFolder(navPath, null, -1, false); };
        refreshTimer.Tick += delegate { refreshTimer.Stop(); AutoRefresh(); };
        treeTimer.Tick += delegate { treeTimer.Stop(); ApplyTreeChanges(); };
        driveTimer.Tick += delegate { driveTimer.Stop(); RefreshDrives(); };

        AllowDrop = true;
        foreach (Control c in new Control[] { this, grid, canvas })   // dropping a file here opens it
        {
            c.AllowDrop = true;
            c.DragEnter += OnDragEnterFiles;
            c.DragDrop += OnDropFiles;
        }
        tree.AllowDrop = true;                                        // dropping onto a folder copies / moves into it
        tree.DragEnter += OnTreeDragOver;
        tree.DragOver += OnTreeDragOver;
        tree.DragLeave += delegate { SetDropNode(null); };
        tree.DragDrop += OnTreeDrop;
        tree.ItemDrag += OnTreeItemDrag;                              // folders can be dragged too
        ApplyPrefs();
    }

    // ================================================================ remembered settings (settings.ini)

    void ApplyPrefs()
    {
        try
        {
            string[] wb = Prefs.Get("window", "").Split(',');
            int x, y, w, h;
            var inv = System.Globalization.CultureInfo.InvariantCulture;
            var ns = System.Globalization.NumberStyles.Integer;
            if (wb.Length == 4 && int.TryParse(wb[0], ns, inv, out x) && int.TryParse(wb[1], ns, inv, out y) &&
                int.TryParse(wb[2], ns, inv, out w) && int.TryParse(wb[3], ns, inv, out h) &&
                w >= MinimumSize.Width && h >= MinimumSize.Height)
            {
                var r = new Rectangle(x, y, w, h);
                bool onScreen = false;                                // the screen it was on may be gone
                foreach (Screen s in Screen.AllScreens)
                {
                    Rectangle i = Rectangle.Intersect(s.WorkingArea, r);
                    if (i.Width >= Util.S(120) && i.Height >= Util.S(60)) onScreen = true;
                }
                if (onScreen) { StartPosition = FormStartPosition.Manual; Bounds = r; }
            }
            if (Prefs.Bool("maximized", false)) WindowState = FormWindowState.Maximized;
            tree.Width = Util.S(Prefs.Int("treeWidth", 280, 140, 2000));
            Marks.Load();                                          // ratings, colour labels and tags (marks.tsv)
            int sk = Prefs.Int("sort", 0, 0, 10);
            bool needsAnalysis = sk >= 6 && sk <= 8;
            grid.SetSort(needsAnalysis ? 0 : sk, needsAnalysis ? false : Prefs.Bool("sortDesc", false));   // analysis sorts need an analysis first
            grid.GridStep = Prefs.Int("thumbSize", grid.GridStep, 0, ThumbGrid.TileStepMax);
            grid.RowStep = Prefs.Int("rowSize", grid.RowStep, 0, ThumbGrid.TileStepMax);
            grid.ShowDetails = Prefs.Bool("details", grid.ShowDetails);
            SetDetailsView(Prefs.Bool("detailsView", false));
            canvas.FitLock = Prefs.Bool("fitToScreen", false);
            canvas.Checker = Prefs.Bool("checkerboard", false);
            canvas.PixMode = Prefs.Int("enlargedPixels", 0, 0, 3);
            canvas.InfoOn = Prefs.Bool("infoBar", true);
            canvas.ExifOn = Prefs.Bool("exifPanel", false);
            canvas.SlideIndex = Prefs.Int("slideshowStep", 2, 0, 99);
            canvas.TvAspect = Prefs.Bool("tvAspect", false);
            canvas.ScanMode = Prefs.Int("scanlines", 0, 0, 3);
            canvas.MaskMode = Prefs.Int("mask", 0, 0, 3);
            canvas.SignalMode = Prefs.Int("signal", 0, 0, 2);
            canvas.GlowMode = Prefs.Int("glow", 0, 0, 2);
            canvas.CurveMode = Prefs.Int("curvature", 0, 0, 2);
            canvas.AutoEffects = Prefs.Bool("autoEffects", false);
            autoAdvance = Prefs.Bool("autoAdvance", false);
            canvas.Filmstrip = Prefs.Bool("filmstrip", false);
            preview.Width = Util.S(Prefs.Int("previewWidth", 320, 180, 2000));
            SetPreview(Prefs.Bool("previewPane", false));
            LoadPresets();
            LoadRecentDest();
            LoadFavourites();
        }
        catch (Exception) { }                                     // a damaged file just means defaults
    }

    // the last folder, if it is still there (local drives only)
    static string LastFolder()
    {
        string p = Prefs.Get("lastFolder", null);
        try
        {
            if (string.IsNullOrEmpty(p) || p.StartsWith("\\\\")) return null;
            string root = Path.GetPathRoot(p);
            if (string.IsNullOrEmpty(root) || new DriveInfo(root).DriveType == DriveType.Network) return null;
            return Directory.Exists(p) ? p : null;
        }
        catch (Exception) { return null; }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        if (e.Cancel) return;
        try { SavePrefs(); } catch (Exception) { }
    }

    void SavePrefs()
    {
        Rectangle b; bool max;
        if (full) { b = oldBounds; max = oldState == FormWindowState.Maximized; }
        else { b = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds; max = WindowState == FormWindowState.Maximized; }
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        Prefs.Set("window", b.X.ToString(inv) + "," + b.Y.ToString(inv) + "," + b.Width.ToString(inv) + "," + b.Height.ToString(inv));
        Prefs.Set("maximized", max);
        Prefs.Set("treeWidth", (int)Math.Round(tree.Width / Util.K));
        Prefs.Set("sort", grid.SortKey);
        Prefs.Set("sortDesc", grid.SortDesc);
        Prefs.Set("thumbSize", grid.GridStep);
        Prefs.Set("rowSize", grid.RowStep);
        Prefs.Set("details", grid.ShowDetails);
        Prefs.Set("detailsView", grid.DetailsMode);
        if (!Program.RetroFromArgs) Prefs.Set("retro", Retro.Enabled);
        Prefs.Set("fitToScreen", canvas.FitLock);
        Prefs.Set("checkerboard", canvas.Checker);
        Prefs.Set("enlargedPixels", canvas.PixMode);
        Prefs.Set("infoBar", canvas.InfoOn);
        Prefs.Set("exifPanel", canvas.ExifOn);
        Prefs.Set("slideshowStep", canvas.SlideIndex);
        EffectSet own = canvas.ManualEffects;              // your own settings, also while automatic effects are on
        Prefs.Set("tvAspect", own.Tv);
        Prefs.Set("scanlines", own.Scan);
        Prefs.Set("mask", own.Mask);
        Prefs.Set("signal", own.Signal);
        Prefs.Set("glow", own.Glow);
        Prefs.Set("curvature", own.Curve);
        Prefs.Set("autoEffects", canvas.AutoEffects);
        Prefs.Set("autoAdvance", autoAdvance);
        Prefs.Set("filmstrip", canvas.Filmstrip);
        Prefs.Set("previewPane", preview.Visible);
        Prefs.Set("previewWidth", (int)Math.Round(preview.Width / Util.K));
        StorePresets();
        StoreRecentDest();
        StoreFavourites();
        Prefs.Set("lastFolder", grid.Dir);
        Prefs.Save();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try { int on = 1; DwmSetWindowAttribute(Handle, 20, ref on, 4); } catch (Exception) { }   // dark title bar
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        Application.AddMessageFilter(new WheelRouter(this, tree, grid));
        pcNode.Expand();
        LabelDrives();
        StartTreeWatch();
        string last = string.IsNullOrEmpty(startArg) ? LastFolder() : null;
        if (!string.IsNullOrEmpty(startArg)) OpenImage(startArg);
        else if (last != null) { OpenImage(last); grid.Focus(); }        // where you were last time
        else
        {
            TreeNode q = null;
            foreach (TreeNode n in pcNode.Nodes) if (n.Name == "quick" && n.Text == "Pictures") q = n;
            if (q == null && pcNode.Nodes.Count > 0) q = pcNode.Nodes[pcNode.Nodes.Count - 1];
            if (q != null) tree.SelectedNode = q;
            grid.Focus();
        }
    }

    // ================================================================ folder tree (lazy, async)

    static Bitmap DrawIcon(int kind, int s)
    {
        var b = new Bitmap(s, s, PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(b))
        {
            float u = s / 16f;
            if (kind == 0)        // folder
                using (var back = new SolidBrush(Color.FromArgb(214, 160, 40)))
                using (var front = new SolidBrush(Color.FromArgb(246, 202, 84)))
                {
                    g.FillRectangle(back, 1 * u, 3 * u, 6 * u, 3 * u);
                    g.FillRectangle(back, 1 * u, 4 * u, 14 * u, 9 * u);
                    g.FillRectangle(front, 1 * u, 6 * u, 14 * u, 7 * u);
                }
            else if (kind == 1)   // drive
                using (var body = new SolidBrush(Color.FromArgb(170, 176, 186)))
                using (var led = new SolidBrush(Color.FromArgb(80, 200, 100)))
                {
                    g.FillRectangle(body, 1 * u, 5 * u, 14 * u, 7 * u);
                    g.FillRectangle(led, 11 * u, 9 * u, 2 * u, 1.5f * u);
                }
            else if (kind == 3)   // favourite: a yellow star
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                var pts = new PointF[10];
                for (int i = 0; i < 10; i++)
                {
                    double ang = -Math.PI / 2 + i * Math.PI / 5, r = (i & 1) == 0 ? 7.2 : 3.0;
                    pts[i] = new PointF((float)(8 + r * Math.Cos(ang)) * u, (float)(8.4 + r * Math.Sin(ang)) * u);
                }
                using (var star = new SolidBrush(Color.FromArgb(245, 200, 70))) g.FillPolygon(star, pts);
            }
            else                  // this PC
                using (var screen = new SolidBrush(Color.FromArgb(70, 140, 230)))
                using (var stand = new SolidBrush(Color.FromArgb(170, 176, 186)))
                {
                    g.FillRectangle(screen, 2 * u, 2 * u, 12 * u, 8 * u);
                    g.FillRectangle(stand, 6 * u, 11 * u, 4 * u, 2 * u);
                    g.FillRectangle(stand, 4 * u, 13 * u, 8 * u, 1.5f * u);
                }
        }
        return b;
    }

    static TreeNode DummyNode() { return new TreeNode("") { Name = Dummy }; }

    TreeNode MakeNode(string path, string text, string name, int icon)
    {
        var n = new TreeNode(text) { Tag = path, Name = name, ImageIndex = icon, SelectedImageIndex = icon };
        n.Nodes.Add(DummyNode());
        return n;
    }

    void BuildRoots()
    {
        pcNode = new TreeNode("This PC") { Name = "pc", ImageIndex = 2, SelectedImageIndex = 2 };
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string[][] quick =
        {
            new[] { "Desktop", Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory) },
            new[] { "Documents", Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments) },
            new[] { "Downloads", Path.Combine(home, "Downloads") },
            new[] { "Pictures", Environment.GetFolderPath(Environment.SpecialFolder.MyPictures) }
        };
        foreach (string[] q in quick)
            if (!string.IsNullOrEmpty(q[1]) && Directory.Exists(q[1])) pcNode.Nodes.Add(MakeNode(q[1], q[0], "quick", 0));

        foreach (DriveInfo d in DriveInfo.GetDrives())
        {
            string kind = DriveKind(d.DriveType);
            if (kind == null) continue;                          // no network or virtual drives
            pcNode.Nodes.Add(MakeDriveNode(d.Name, kind));
        }
        tree.Nodes.Add(pcNode);
    }

    static string DriveKind(DriveType t)
    {
        if (t == DriveType.Fixed) return "Local Disk";
        if (t == DriveType.Removable) return "Removable Disk";
        if (t == DriveType.CDRom) return "CD/DVD Drive";
        return null;
    }

    TreeNode MakeDriveNode(string root, string kind)
    {
        TreeNode n = MakeNode(root, kind + " (" + root.TrimEnd('\\') + ")", "drive", 1);
        driveDefault[n] = kind;
        return n;
    }

    // ================================================================ folder tree auto-refresh

    // One watcher per local drive, reporting folder changes only (files are the grid's business). Changes are
    // collected on the watcher threads, then applied on the UI thread half a second later, and only to folders
    // the tree has already loaded. Existing branches are updated in place, so expanded folders stay open.
    readonly List<FileSystemWatcher> treeWatchers = new List<FileSystemWatcher>();
    readonly object treeSync = new object();
    readonly HashSet<string> treeDirty = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    bool treeDirtyAll;
    readonly WinTimer treeTimer = new WinTimer { Interval = 500 };
    readonly WinTimer driveTimer = new WinTimer { Interval = 1500 };

    void StartTreeWatch()
    {
        foreach (FileSystemWatcher w in treeWatchers) { try { w.EnableRaisingEvents = false; w.Dispose(); } catch (Exception) { } }
        treeWatchers.Clear();
        var roots = new List<string>();
        foreach (TreeNode n in pcNode.Nodes) if (n.Name == "drive") roots.Add((string)n.Tag);
        ThreadPool.QueueUserWorkItem(delegate                 // asking a card reader whether it is ready can be slow
        {
            var ready = new List<string>();
            foreach (string r in roots)
            {
                try
                {
                    var d = new DriveInfo(r);
                    if (d.IsReady && (d.DriveType == DriveType.Fixed || d.DriveType == DriveType.Removable)) ready.Add(r);
                }
                catch (Exception) { }
            }
            Util.Post(this, delegate
            {
                foreach (string rr in ready)
                {
                    try
                    {
                        var fw = new FileSystemWatcher(rr) { IncludeSubdirectories = true, NotifyFilter = NotifyFilters.DirectoryName, InternalBufferSize = 65536 };
                        fw.Created += delegate (object s, FileSystemEventArgs e) { TreeDirty(Path.GetDirectoryName(e.FullPath)); };
                        fw.Deleted += delegate (object s, FileSystemEventArgs e) { TreeDirty(Path.GetDirectoryName(e.FullPath)); };
                        fw.Renamed += delegate (object s, RenamedEventArgs e)
                        {
                            TreeDirty(Path.GetDirectoryName(e.OldFullPath));
                            TreeDirty(Path.GetDirectoryName(e.FullPath));
                        };
                        fw.Error += delegate { TreeDirty(null); };   // too many changes at once: check every loaded folder
                        fw.EnableRaisingEvents = true;
                        treeWatchers.Add(fw);
                    }
                    catch (Exception) { }                     // a drive without change notifications: F5 still works
                }
            });
        });
    }

    // watcher threads: remember which folder's subfolders changed (null = don't know, check all)
    void TreeDirty(string dir)
    {
        bool first;
        lock (treeSync)
        {
            first = treeDirty.Count == 0 && !treeDirtyAll;
            if (dir == null || treeDirty.Count > 2000) treeDirtyAll = true;
            else treeDirty.Add(dir);
        }
        if (first) Util.Post(this, delegate { treeTimer.Stop(); treeTimer.Start(); });
    }

    void ApplyTreeChanges()
    {
        List<string> dirs; bool all;
        lock (treeSync)
        {
            dirs = new List<string>(treeDirty);
            all = treeDirtyAll;
            treeDirty.Clear(); treeDirtyAll = false;
        }
        if (all)
        {
            var loaded = new List<TreeNode>();
            CollectLoaded(pcNode, loaded);
            foreach (TreeNode n in loaded) RefreshFolderNode(n);
            return;
        }
        foreach (string d in dirs)
            foreach (TreeNode n in FindLoadedNodes(d)) RefreshFolderNode(n);
    }

    void CollectLoaded(TreeNode n, List<TreeNode> into)
    {
        foreach (TreeNode c in n.Nodes)
        {
            if (!(c.Tag is string) || IsUnloaded(c)) continue;
            into.Add(c);
            CollectLoaded(c, into);
        }
    }

    // every loaded node showing this folder: under its drive, and under a quick-access entry (Pictures ...)
    List<TreeNode> FindLoadedNodes(string path)
    {
        var r = new List<TreeNode>();
        if (string.IsNullOrEmpty(path)) return r;
        foreach (TreeNode top in pcNode.Nodes)
        {
            string tp = top.Tag as string;
            if (tp == null) continue;
            TreeNode n = Descend(top, tp, path);
            if (n != null) r.Add(n);
        }
        return r;
    }

    TreeNode Descend(TreeNode top, string topPath, string path)
    {
        if (Util.SameDir(topPath, path)) return top;
        string tp = topPath.TrimEnd('\\');
        if (!path.StartsWith(tp + "\\", StringComparison.OrdinalIgnoreCase)) return null;
        TreeNode cur = top;
        string at = tp;
        foreach (string part in path.Substring(tp.Length + 1).Split(new[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (IsUnloaded(cur)) return null;
            at = at + "\\" + part;
            TreeNode next = null;
            foreach (TreeNode c in cur.Nodes)
                if (Util.SameDir(c.Tag as string, at)) { next = c; break; }
            if (next == null) return null;
            cur = next;
        }
        return cur;
    }

    // Lists the folder again (worker thread) and merges the result into its loaded branch
    void RefreshFolderNode(TreeNode n)
    {
        string path = n == null ? null : n.Tag as string;
        if (path == null || IsUnloaded(n) || waiting.ContainsKey(n)) return;
        ThreadPool.QueueUserWorkItem(delegate
        {
            List<string> dirs = ListDirs(path);
            bool exists = Directory.Exists(path);
            Util.Post(this, delegate { MergeChildren(n, path, dirs, exists); });
        });
    }

    static bool IsUnder(TreeNode n, TreeNode ancestor)
    {
        for (TreeNode p = n; p != null; p = p.Parent) if (p == ancestor) return true;
        return false;
    }

    // Adds new subfolders and removes vanished ones, keeping every other node (and what is expanded under it)
    void MergeChildren(TreeNode n, string path, List<string> dirs, bool exists)
    {
        if (n.TreeView == null || !Util.SameDir(n.Tag as string, path) || IsUnloaded(n) || waiting.ContainsKey(n)) return;
        if (!exists) return;                                  // the folder itself went: its parent's update removes it
        var want = new HashSet<string>(dirs, StringComparer.OrdinalIgnoreCase);
        var have = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var gone = new List<TreeNode>();
        foreach (TreeNode c in n.Nodes)
        {
            string cp = c.Tag as string;
            if (cp != null && want.Contains(cp)) have.Add(cp); else gone.Add(c);
        }
        bool added = dirs.Exists(x => !have.Contains(x));
        if (gone.Count == 0 && !added) return;

        TreeNode sel = tree.SelectedNode;
        bool selGone = false;
        foreach (TreeNode g in gone) if (sel != null && IsUnder(sel, g)) selGone = true;
        string gd = grid.Dir;
        bool shownGone = false;
        foreach (TreeNode g in gone)
        {
            string gp = g.Tag as string;
            if (gp != null && gd != null && (Util.SameDir(gd, gp) || gd.StartsWith(gp.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase))) shownGone = true;
        }
        tree.BeginUpdate();
        try
        {
            if (selGone) SelectQuiet(n);
            foreach (TreeNode g in gone) { waiting.Remove(g); n.Nodes.Remove(g); }
            for (int i = 0; i < dirs.Count; i++)
            {
                if (have.Contains(dirs[i])) continue;
                n.Nodes.Insert(Math.Min(i, n.Nodes.Count), MakeNode(dirs[i], Path.GetFileName(dirs[i]), "dir", 0));
            }
        }
        finally { tree.EndUpdate(); }
        if (shownGone && (gd == null || !Directory.Exists(gd))) ShowFolder(path, null, -1, true);   // the shown folder went: show its parent
    }

    // a USB stick or card was plugged in or removed (Windows tells every window; no extra system calls needed)
    protected override void WndProc(ref Message m)
    {
        base.WndProc(ref m);
        if (m.Msg == 0x0219)                                  // WM_DEVICECHANGE
        {
            long w = m.WParam.ToInt64();
            if (w == 0x8000 || w == 0x8004) { driveTimer.Stop(); driveTimer.Start(); }   // device arrived / removed
        }
    }

    void RefreshDrives()
    {
        ThreadPool.QueueUserWorkItem(delegate
        {
            var now = new List<KeyValuePair<string, string>>();
            try
            {
                foreach (DriveInfo d in DriveInfo.GetDrives())
                {
                    string kind = DriveKind(d.DriveType);
                    if (kind != null) now.Add(new KeyValuePair<string, string>(d.Name, kind));
                }
            }
            catch (Exception) { return; }
            Util.Post(this, delegate { ApplyDrives(now); });
        });
    }

    void ApplyDrives(List<KeyValuePair<string, string>> now)
    {
        var present = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (KeyValuePair<string, string> d in now) present.Add(d.Key);
        var existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var gone = new List<TreeNode>();
        foreach (TreeNode n in pcNode.Nodes)
        {
            if (n.Name != "drive") continue;
            string r = (string)n.Tag;
            if (present.Contains(r)) existing.Add(r); else gone.Add(n);
        }
        bool added = now.Exists(x => !existing.Contains(x.Key));
        if (gone.Count == 0 && !added) return;
        tree.BeginUpdate();
        try
        {
            foreach (TreeNode g in gone)
            {
                if (tree.SelectedNode != null && IsUnder(tree.SelectedNode, g)) SelectQuiet(pcNode);
                waiting.Remove(g); driveDefault.Remove(g);
                pcNode.Nodes.Remove(g);
            }
            foreach (KeyValuePair<string, string> d in now)
            {
                if (existing.Contains(d.Key)) continue;
                int at = pcNode.Nodes.Count;                  // keep drives in letter order, after the quick-access entries
                for (int i = 0; i < pcNode.Nodes.Count; i++)
                {
                    TreeNode c = pcNode.Nodes[i];
                    if (c.Name == "drive" && string.Compare((string)c.Tag, d.Key, StringComparison.OrdinalIgnoreCase) > 0) { at = i; break; }
                }
                pcNode.Nodes.Insert(at, MakeDriveNode(d.Key, d.Value));
            }
        }
        finally { tree.EndUpdate(); }
        LabelDrives();
        StartTreeWatch();
    }

    // volume labels can be slow to query (card readers, optical drives), so fetch them off-thread
    void LabelDrives()
    {
        var nodes = new List<TreeNode>();
        foreach (TreeNode n in pcNode.Nodes) if (n.Name == "drive") nodes.Add(n);
        ThreadPool.QueueUserWorkItem(delegate
        {
            foreach (TreeNode n in nodes)
            {
                string root = (string)n.Tag, label = "";
                try { var d = new DriveInfo(root); if (d.IsReady) label = d.VolumeLabel; } catch (Exception) { }
                if (label.Length == 0) continue;
                string text = label + " (" + root.TrimEnd('\\') + ")";
                TreeNode nn = n;
                Util.Post(this, delegate { nn.Text = text; });
            }
        });
    }

    static List<string> ListDirs(string path)
    {
        var r = new List<string>();
        try
        {
            foreach (DirectoryInfo d in new DirectoryInfo(path).EnumerateDirectories())
            {
                if ((d.Attributes & (FileAttributes.Hidden | FileAttributes.System)) != 0) continue;
                r.Add(d.FullName);
            }
            r.Sort(delegate (string a, string b) { return Util.NatCmp(Path.GetFileName(a), Path.GetFileName(b)); });
        }
        catch (Exception) { }                                    // access denied, disc removed, ...
        return r;
    }

    static bool IsUnloaded(TreeNode n) { return n.Nodes.Count == 1 && n.Nodes[0].Name == Dummy; }

    // Fill a node's children on a worker thread; callbacks run on the UI thread afterwards.
    void EnsureLoaded(TreeNode n, Action done)
    {
        if (!IsUnloaded(n)) { if (done != null) done(); return; }
        List<Action> w;
        if (waiting.TryGetValue(n, out w)) { if (done != null) w.Add(done); return; }
        w = new List<Action>();
        if (done != null) w.Add(done);
        waiting[n] = w;
        n.Nodes[0].Text = "Loading...";
        string path = (string)n.Tag;
        ThreadPool.QueueUserWorkItem(delegate
        {
            List<string> dirs = ListDirs(path);
            Util.Post(this, delegate { Populate(n, dirs); });
        });
    }

    void Populate(TreeNode n, List<string> dirs)
    {
        if (!waiting.ContainsKey(n)) return;                     // node was reloaded meanwhile
        tree.BeginUpdate();
        n.Nodes.Clear();
        foreach (string d in dirs) n.Nodes.Add(MakeNode(d, Path.GetFileName(d), "dir", 0));
        tree.EndUpdate();
        List<Action> w = waiting[n];
        waiting.Remove(n);
        foreach (Action a in w) a();
    }

    void ReloadNode(TreeNode n)
    {
        bool exp = n.IsExpanded;
        waiting.Remove(n);
        n.Nodes.Clear();
        n.Nodes.Add(DummyNode());
        if (exp) n.Expand();
    }

    TreeNode FindDrive(string root)
    {
        foreach (TreeNode n in pcNode.Nodes)
            if (n.Name == "drive" && Util.SameDir((string)n.Tag, root)) return n;
        return null;
    }

    TreeNode FindLoadedNode(string path)
    {
        string root = Path.GetPathRoot(path);
        TreeNode cur = root == null ? null : FindDrive(root);
        if (cur == null) return null;
        if (Util.SameDir(root, path)) return cur;
        foreach (string part in path.Substring(root.Length).Split(new[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (IsUnloaded(cur)) return null;
            TreeNode next = null;
            foreach (TreeNode c in cur.Nodes)
                if (string.Equals(c.Text, part, StringComparison.OrdinalIgnoreCase)) { next = c; break; }
            if (next == null) return null;
            cur = next;
        }
        return cur;
    }

    // Expand and highlight a folder in the tree (asynchronously, one level at a time).
    void RevealInTree(string dir)
    {
        int token = ++revealToken;
        try
        {
            dir = Path.GetFullPath(dir);
            string root = Path.GetPathRoot(dir);
            TreeNode n = FindDrive(root);
            if (n == null) return;
            string[] parts = dir.Substring(root.Length).Split(new[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries);
            RevealStep(n, parts, 0, token);
        }
        catch (Exception) { }
    }

    void RevealStep(TreeNode n, string[] parts, int i, int token)
    {
        if (token != revealToken) return;
        if (i == parts.Length) { SelectQuiet(n); return; }
        EnsureLoaded(n, delegate
        {
            if (token != revealToken) return;
            n.Expand();
            TreeNode next = null;
            foreach (TreeNode c in n.Nodes)
                if (string.Equals(c.Text, parts[i], StringComparison.OrdinalIgnoreCase)) { next = c; break; }
            if (next == null) { SelectQuiet(n); return; }
            RevealStep(next, parts, i + 1, token);
        });
    }

    void SelectQuiet(TreeNode n)
    {
        suppress = true;
        try { tree.SelectedNode = n; n.EnsureVisible(); }
        finally { suppress = false; }
    }

    void OnTreeSelect(object s, TreeViewEventArgs e)
    {
        if (suppress) return;
        string p = NodePath(e.Node);
        if (p == null) return;
        if (e.Action == TreeViewAction.ByKeyboard) { navPath = p; navTimer.Stop(); navTimer.Start(); }   // debounce arrow-key scrubbing
        else ShowFolder(p, null, -1, false);
    }

    static string NodePath(TreeNode n) { return n == null ? null : n.Tag as string; }

    static bool IsRootPath(string p) { return Util.SameDir(Path.GetPathRoot(p), p); }

    // ================================================================ browsing <-> viewing

    void ShowFolder(string dir, string select, int hint, bool force)
    {
        if (dir == null) return;
        if (!force && select != null && !grid.Scanning && Util.SameDir(dir, grid.Dir))
        {
            int i = grid.IndexOfPath(select, -1);
            if (i >= 0) { grid.SelectOnly(i); SyncCanvas(); return; }
        }
        if (grid.Recursive && !Util.SameDir(dir, grid.Dir)) SetSubfolders(false, false);   // another folder or drive: switch off
        grid.Load(dir, select, hint);
        UpdateStatus();
    }

    void OnFolderLoaded(string dir, string err)
    {
        UpdateStatus();
        if (!viewing) Text = dir + " - RetroGleek";
        RecordHistory(dir);
        if (err == null) RememberRecentFolder(dir);
        if (!addrBox.Focused) addrBox.Text = dir;
        UpdateNavButtons();
        SyncCanvas();
        Watch(err == null ? dir : null);
    }

    void Watch(string dir)
    {
        if (dir != null && Util.SameDir(dir, watchedDir) && watcher != null && watchedRecursive == grid.Recursive) return;
        if (watcher != null)
        {
            try { watcher.EnableRaisingEvents = false; watcher.Dispose(); } catch (Exception) { }
            watcher = null;
        }
        watchedDir = null;
        refreshTimer.Stop();
        if (dir == null) return;
        try
        {
            var w = new FileSystemWatcher(dir)
            {
                IncludeSubdirectories = grid.Recursive,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size | NotifyFilters.Attributes
            };
            FileSystemEventHandler changed = delegate { Util.Post(this, FolderChanged); };
            w.Created += changed; w.Deleted += changed; w.Changed += changed;
            w.Renamed += delegate { Util.Post(this, FolderChanged); };
            w.Error += delegate { Util.Post(this, FolderChanged); };       // too many changes at once: just rescan
            w.EnableRaisingEvents = true;
            watcher = w; watchedDir = dir; watchedRecursive = grid.Recursive;
        }
        catch (Exception) { }                                 // e.g. a CD, or a drive that gives no notifications: F5 still works
    }

    void FolderChanged()                                      // UI thread; waits until the changes settle
    {
        refreshTimer.Interval = grid.Recursive ? 2000 : 700;  // a whole tree of folders: wait a little longer
        refreshTimer.Stop(); refreshTimer.Start();
    }

    // the Subfolders switch: applies to the folder that is open, and turns itself off when another folder or drive
    // is opened (ShowFolder). A refresh of the same folder keeps it on.
    void ToggleSubfolders() { SetSubfolders(!grid.Recursive, true); }

    void SetSubfolders(bool on, bool rescan)
    {
        grid.Recursive = on;
        subBtn.BackColor = on ? Color.FromArgb(60, 130, 230) : Color.FromArgb(52, 52, 52);
        subBtn.ForeColor = on ? Color.White : Color.Gainsboro;
        if (rescan && grid.Dir != null) { grid.Rescan(); UpdateStatus(); }
    }

    // Alt+P: the preview pane to the right of the thumbnails (remembered in settings.ini)
    void SetPreview(bool on)
    {
        SuspendLayout();
        preview.Visible = on;
        previewSplit.Visible = on;
        ResumeLayout(true);
        UpdatePreview();
    }

    void UpdatePreview()
    {
        if (preview == null || !preview.Visible) return;
        int f = grid.FocusIndex;
        List<int> sel = grid.SelectedIndices();
        Item it = f >= 0 && f < grid.Items.Count ? grid.Items[f] : sel.Count > 0 ? grid.Items[sel[0]] : null;
        string folder = null;
        if (it != null && grid.Recursive && grid.Dir != null)
        {
            string d = Path.GetDirectoryName(it.Path);
            folder = Util.SameDir(d, grid.Dir) ? "(this folder)" : d.Substring(Math.Min(d.Length, grid.Dir.TrimEnd('\\').Length + 1));
        }
        int others = it != null && sel.Count > 1 ? sel.Count - (it.Sel ? 1 : 0) : 0;
        preview.ShowItem(it, grid.MarkOf(it), folder, others);
    }

    // thumbnails <-> details list (remembered in settings.ini)
    void SetDetailsView(bool on)
    {
        grid.DetailsMode = on;
        detailHeader.Visible = on;
        viewBtn.BackColor = on ? Color.FromArgb(60, 130, 230) : Color.FromArgb(52, 52, 52);
        viewBtn.ForeColor = on ? Color.White : Color.Gainsboro;
        viewBtn.Text = on ? "Thumbnails" : "Details";
        viewBtn.Width = Util.S(on ? 92 : 72);
    }

    void AutoRefresh()
    {
        if (watchedDir == null || !Util.SameDir(watchedDir, grid.Dir)) return;
        if (grid.Scanning) { refreshTimer.Start(); return; }   // a scan is running: try again a little later
        if (!Directory.Exists(watchedDir)) { Watch(null); grid.Rescan(); return; }
        grid.Rescan();
    }

    // hand the viewer the (sorted) list of the folder once the grid has scanned it
    void SyncCanvas()
    {
        string w = canvas.Want;
        if (w == null || grid.Dir == null) return;
        if (grid.Covers(Path.GetDirectoryName(w)) && grid.IndexOfPath(w, -1) >= 0) canvas.SetList(grid.Paths, w);
    }

    void OpenImage(string path)
    {
        try
        {
            path = Path.GetFullPath(path);
            if (grid.FilterActive) { filterBox.Text = ""; SetShow(0); }   // opening something explicitly shouldn't be hidden by a filter
            if (Directory.Exists(path))
            {
                SetViewing(false);
                ShowFolder(path, null, -1, false);
                RevealInTree(path);
                return;
            }
            if (!File.Exists(path)) return;
            string dir = Path.GetDirectoryName(path);
            if (!Util.IsNative(path) && Retro.Claims(path)) Retro.Enabled = true;   // you opened a retro picture: show its neighbours too
            canvas.ShowSingle(path);                       // show it immediately, before the folder scan finishes
            SetViewing(true);
            ShowFolder(dir, path, -1, false);              // grid + tree follow in the background
            RevealInTree(dir);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "RetroGleek"); }
    }

    void OpenIndex(int i)
    {
        if (i < 0 || i >= grid.Paths.Count) return;
        canvas.Open(grid.Paths, i);
        SetViewing(true);
    }

    void OnImageChanged(string path, int index)
    {
        if (viewing) Text = Path.GetFileName(path) + " - RetroGleek";
        if (grid.Dir != null && grid.Covers(Path.GetDirectoryName(path)))
        {
            int i = grid.IndexOfPath(path, index);
            if (i >= 0) grid.SelectOnly(i);                // keep the browser's selection in step with the viewer
        }
    }

    // ================================================================ side-by-side compare

    TableLayoutPanel comparePanel;
    Canvas cmpA, cmpB;
    bool comparing;

    void BuildCompare()
    {
        comparePanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Visible = false, Padding = new Padding(0), Margin = new Padding(0),
            BackColor = Color.FromArgb(52, 52, 52)
        };
        comparePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
        comparePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
        comparePanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
        cmpA = new Canvas { Margin = new Padding(0, 0, Util.S(1), 0) };
        cmpB = new Canvas { Margin = new Padding(Util.S(1), 0, 0, 0) };
        comparePanel.Controls.Add(cmpA, 0, 0);
        comparePanel.Controls.Add(cmpB, 1, 0);
        // each follows the other's zoom and position
        cmpA.ViewChanged += delegate { double z, x, y; int fm; cmpA.GetView(out z, out x, out y, out fm); cmpB.SetView(z, x, y, fm); };
        cmpB.ViewChanged += delegate { double z, x, y; int fm; cmpB.GetView(out z, out x, out y, out fm); cmpA.SetView(z, x, y, fm); };
        foreach (Control c in new Control[] { cmpA, cmpB })
        {
            c.AllowDrop = true;
            c.DragEnter += OnDragEnterFiles;
            c.DragDrop += delegate { };                    // dropping files while comparing does nothing
        }
    }

    bool CanCompare() { return !viewing && !comparing && grid.SelectedIndices().Count == 2; }

    void StartCompare()
    {
        if (!CanCompare()) return;
        List<int> sel = grid.SelectedIndices();
        string a = grid.Items[sel[0]].Path, b = grid.Items[sel[1]].Path;
        comparing = true;
        SuspendLayout();
        browse.Visible = false; status.Visible = false; canvas.Visible = false;
        cmpA.Visible = true; cmpB.Visible = true;
        comparePanel.Visible = true;
        ResumeLayout(true);
        foreach (Canvas c in new[] { cmpA, cmpB })
        {
            c.UseEffects(canvas.ManualEffects);
            c.AutoEffects = canvas.AutoEffects;            // automatic: each picture gets its own computer's effects
            c.EffectsOff = canvas.EffectsOff;
        }
        cmpA.ShowSingle(a);
        cmpB.ShowSingle(b);
        Text = "Compare: " + Path.GetFileName(a) + "  |  " + Path.GetFileName(b) + " - RetroGleek";
        cmpA.Focus();
    }

    void EndCompare()
    {
        if (!comparing) return;
        comparing = false;
        comparePanel.Visible = false;
        cmpA.Release(); cmpB.Release();
        SetViewing(false);
    }

    // keys while comparing: zoom keys go to the left picture (the right one follows), the rest to both
    bool CompareKey(Keys keyData)
    {
        Keys k = keyData & Keys.KeyCode;
        bool ctrl = (keyData & Keys.Control) != 0, shift = (keyData & Keys.Shift) != 0;
        if (k == Keys.Escape) { if (full) ToggleFull(); else EndCompare(); return true; }
        if (ctrl && shift && k == Keys.C) { EndCompare(); return true; }
        if (k == Keys.Enter && !ctrl) { ToggleFull(); return true; }
        bool zoomKey = k == Keys.Add || k == Keys.Subtract || k == Keys.Oemplus || k == Keys.OemMinus ||
                       (k >= Keys.D0 && k <= Keys.D9) || (k >= Keys.NumPad0 && k <= Keys.NumPad9);
        bool navKey = k == Keys.Left || k == Keys.Right || k == Keys.PageUp || k == Keys.PageDown || k == Keys.Space ||
                      k == Keys.Back || k == Keys.Home || k == Keys.End || k == Keys.S || k == Keys.Up || k == Keys.Down;
        if (navKey || ctrl) return true;                   // nothing to step through; Ctrl+C / Ctrl+S etc. do nothing here
        if (k == Keys.Z) return true;                      // no loupe while comparing (only one side would see Z let go)
        if (zoomKey) return cmpA.HandleKey(keyData);
        bool used = cmpA.HandleKey(keyData);
        used |= cmpB.HandleKey(keyData);
        return used;
    }

    void SetViewing(bool v)
    {
        viewing = v;
        SuspendLayout();
        if (v) { canvas.Visible = true; browse.Visible = false; status.Visible = false; }
        else { browse.Visible = true; status.Visible = true; canvas.Visible = false; }
        ResumeLayout(true);
        if (v) canvas.Focus();
        else { grid.Focus(); lastPane = grid; Text = (grid.Dir ?? "RetroGleek") + " - RetroGleek"; UpdateStatus(); }
    }

    void UpdateStatus()
    {
        if (grid.Scanning) { status.Text = grid.Recursive ? "  Searching subfolders..." : "  Loading folder..."; return; }
        if (grid.Error != null) { status.Text = "  " + grid.Error; return; }
        List<int> sel = grid.SelectedIndices();
        long bytes = 0;
        foreach (int i in sel) bytes += grid.Items[i].Size;
        int shown = grid.Items.Count, total = grid.TotalCount;
        string s = "  " + (grid.FilterActive ? shown + " of " + total : total.ToString()) + (total == 1 ? " image" : " images");
        if (grid.Recursive) s += grid.Truncated ? " (including subfolders; stopped at " + ThumbGrid.MaxRecursive + ")" : " (including subfolders)";
        if (grid.FilterActive) s += grid.ShowMode != 0 ? " (showing: " + ThumbGrid.ShowNames[grid.ShowMode] + ")" : " (filtered)";
        int tagged = grid.CountTagged();
        if (tagged > 0) s += "   |   " + tagged + " tagged";
        if (sel.Count > 0) s += "   |   " + sel.Count + " selected (" + Util.FmtSize(bytes) + ")";
        if (grid.SortKey != 0 || grid.SortDesc) s += "   |   sorted by " + grid.SortLabel;
        if (sel.Count == 1)
        {
            string why = grid.FailureOf(sel[0]);
            if (why != null) s += "   |   no thumbnail: " + why;
        }
        status.Text = s + "   |   " + grid.Dir;
    }
}
