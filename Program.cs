// RetroGleek - a tiny, 100% offline image browser + viewer for Windows 11.
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE).
//
// Uses ONLY the .NET Framework that ships with Windows (System, System.Drawing, System.Windows.Forms,
// Microsoft.VisualBasic for Recycle Bin deletes, System.Xml, and WPF's imaging classes for the picture decoders
// installed in Windows: WebP, AVIF, HEIC, JPEG XL, JPEG XR, camera RAW), plus RECOIL.cs, a bundled
// managed C# library for retro pictures. There is no networking code in this file or in RECOIL.cs:
// no sockets, no HTTP, no telemetry, no licensing, no cloud APIs.
// Cloud "placeholder" files (OneDrive etc. that are not stored on this PC) are never opened,
// so browsing can't trigger a download. Copying a folder leaves the cloud-only files inside it out (and says how
// many); moving a folder that holds some to another drive asks first, because Windows would download them.
//
// BROWSE MODE (folder tree | thumbnails)
//   Click folder in the tree          show its images (lazy-loaded, scanned on background threads)
//   Double-click / Enter              open the image in the viewer
//   Arrows, Home/End, PgUp/PgDn       move;  Shift / Ctrl + click or arrows: multi-select;  Ctrl+A all;  Ctrl+I invert selection
//   Mouse wheel / Ctrl + wheel        scroll / change thumbnail size
//   Right-click, or F2, Ctrl+C, Ctrl+V, Del, F5   Rename, Copy, Paste, Delete (Recycle Bin), Refresh
//   Drag with the mouse               rubber-band select (Ctrl adds); a drag that starts on a SELECTED picture
//                                     moves / copies the selection onto a tree folder or into Explorer
//   Ctrl+X then Ctrl+V                cut and paste = move (Explorer-compatible)
//   Ctrl+Shift+Y / Ctrl+Shift+M       copy / move the selection to a folder (Edit > Copy to / Move to: the last 8)
//   Ctrl+Shift+F / Subfolders switch  also list the pictures of every folder below this one
//   Ctrl+Shift+D / Details button     details list with sortable columns (instead of thumbnails)
//   Ctrl+Shift+C                      compare the 2 selected pictures side by side (zoom / pan linked)
//   Ctrl+F2                           batch rename the selection (pattern, preview)
//   Ctrl+Z                            undo the last rename, batch rename or move (20 steps, while running)
//   Ctrl+Shift+S                      every frame of an animated GIF or WebP / page of a TIFF as separate lossless PNGs
//   Ctrl+Shift+A                      folder audit report (HTML): platforms, types, failures, duplicates
//   Ctrl+Shift+R / Ctrl+Shift+L       turn the selected JPEG photos on disk, without loss (asks first)
//   Ctrl+Shift+E                      convert the selection to a retro format (Spectrum .scr, C64 .koa/.dd, CPC .scr, ST .pi1, Amiga .iff, MSX .sc2/.sc8);
//                                     new files, each checked by RECOIL
//   Alt+0..5 / Shift+0..5 / X         rating / colour label / tag (browser and viewer); Show pull-down filters by them
//   Edit > Rating > Write my ratings into the files   copies your stars into JPEG / PNG files (XMP; asks first)
//   The open folder refreshes by itself when its files change (FileSystemWatcher, local drives only);
//   the folder tree updates itself when folders change, and when a USB stick / card is plugged in or out
//
// COMMAND LINE AUDIT (no window):  RetroGleek.exe --audit <folder> [--out <file>] [--no-thumbs] [--csv] [--overwrite]
//   or the console companion, with progress and a summary:  RetroGleekCli.exe <folder> [same options] [--quiet]
//   exit code 0 = all opened, 1 = some could not be opened, 2 = error
//
// VIEW MODE (full canvas)
//   Left / Right, PgUp / PgDn, Space / Backspace, Mouse wheel   previous / next image (wraps)
//   Home / End                        first / last image in the folder
//   Ctrl + Mouse wheel, + / -         zoom (around the cursor / window centre)
//   Click and drag                    pan            Double-click   toggle fit <-> 100%
//   F = Fit-to-Screen on/off (off at launch; kept for the next pictures while running: on = fit the window, off = 100%)
//   0 = fit this picture,  1 = actual size    R / L (Shift+R)  rotate clockwise / counter-clockwise
//   I                                 show / hide the info bar
//   Esc                               back to the browser (or leave fullscreen)
//
// Anywhere: the menu bar (Alt) has every command; F1 = help (every key, plus credits), F11 = fullscreen, Ctrl+O = open file, or drag & drop a file / folder onto the window.
//
// RETRO-COMPUTER PICTURES (Amiga, Atari, C64, ZX Spectrum, MSX ... 567 file extensions)
//   Decoded by RECOIL (MIT licence, bundled as the managed C# file RECOIL.cs; see THIRD-PARTY-NOTICES.txt).
//   Shown in folder listings by default. F8 / the right-click menu / the --no-retro switch turn it off;
//   opening a retro picture directly turns it back on.
//   Settings (window, sort, thumbnail size, viewer options, last folder) are remembered in settings.ini next to
//   RetroGleek.exe, written when RetroGleek closes; delete it or use Settings > Reset to go back to the defaults.
//
// SAVE AS PNG (lossless)  Ctrl+S, or right-click > "Save as PNG (lossless)..."
//   Browse mode: saves the selected picture(s); one picture asks for a file name, several ask for a folder
//   (existing files are never overwritten). Viewer: saves the current picture as you see it (incl. rotation).
//   Works for retro and normal formats. Every PNG is read back and compared pixel by pixel before it is kept.
//
// BROWSING AIDS
//   Filter box (always visible; Ctrl+F jumps to it, Esc clears it): part of a name, or * ? wildcards; spaces mean AND
//   To its right: a Sort pull-down (name, date modified, size, type) with a reverse arrow, and a thumbnail Size slider
//   Alt+P    preview pane (large preview + facts of the focused picture, right of the thumbnails)
//   Ctrl+D   add / remove the open folder as a favourite (tree, Go > Favourites); Go > Recent folders
//   Ctrl+L   address bar: type or paste a local path, Enter.   Alt+Left / Alt+Right / Alt+Up (or Backspace) = back / forward / up
//   Right-click > Sort by also works; Ctrl + mouse wheel also changes the thumbnail size
//   Right-click > Show details on tiles: size and platform under each name; rest the pointer on a tile for more
// VIEWER EXTRAS
//   S slideshow (Up / Down = interval; S or Esc stops)    2..9 = 200%..900% zoom    + / - = whole-number steps above 100%
//   J filmstrip    Z (hold) loupe    G pixel grid (at 800% and above)    N crisp / sharp / smooth enlargement    the info bar shows x, y and colour under the pointer
//   H / V flip left-right / top-bottom    B checkerboard behind transparency    Ctrl+C copy the picture    Del Recycle Bin
//   E EXIF details (JPEG, TIFF, and HEIC / AVIF / RAW ... through Windows' decoders)    P pause / play an animated GIF or WebP    , / . previous / next frame
//   T True TV aspect (pixel shape of the original screen)    K scanlines    M phosphor mask    C RGB / S-Video / composite signal    W glow    U curvature
//   O all screen effects off / on    A automatic effects for each computer    Ctrl+1..9 presets (Effects menu; display only)
//
// Written in C# 5 so it builds with the compiler included in Windows (see build.bat).
//
// SOURCE FILES (all next to build.bat, which lists each of them; add any new file there too)
//   Program.cs         this overview, version info, Main
//   Util.cs            shared helpers (incl. copying a folder without its cloud-only files)
//   Imaging.cs         Exporter (lossless PNG), Retro (RECOIL wrapper), Pic
//   Thumbnails.cs      Item, ThumbJob, ThumbResult, ThumbCache, ThumbService
//   Controls.cs        Prompt, WheelRouter, Gfx, DarkColors, DarkMenuRenderer, DarkCombo, DarkSlider
//   Canvas.cs          the full-canvas viewer
//   ThumbGrid.cs       the thumbnail grid
//   MainForm.cs        the main window: layout, tree, browsing <-> viewing
//   MainForm.Files.cs  the main window, continued: menus, file operations, export, address bar, keys
//   MainForm.Undo.cs   the main window, continued: undo (Ctrl+Z) for renames, batch renames and moves
//   BatchRename.cs     batch rename: pattern, preview, safe two-step renaming
//   Settings.cs        remembered settings (settings.ini)
//   Audit.cs           folder audit: offline HTML report of every picture file in one folder
//   ScreenEffects.cs   screen effect sets: presets (Ctrl+1..9) and the automatic choice for each computer (A)
//   JpegRotate.cs      lossless changes to photo files, checked first: the JPEG turn on disk (orientation tag, or
//                      GDI+'s lossless transform), and writing your star rating into JPEG and PNG files (XMP)
//   WinCodecs.cs       pictures decoded by Windows' own codecs (WebP, AVIF, HEIC, JPEG XL, RAW ...) and their EXIF
//                      details; animated WebP frames (WebpAnim); fast big-JPEG thumbnails
//   ContactSheet.cs    contact sheet: lossless PNG index sheets of the selection (Tools menu)
//   Marks.cs           ratings, colour labels and tags (marks.tsv next to settings.ini; never inside the pictures);
//                      found again after a file or its folder is moved or renamed in Explorer
//   RetroConvert.cs    converting pictures into retro formats (Spectrum .scr, C64 Koala .koa and Doodle .dd,
//                      Amstrad CPC .scr mode 0 and 1, Atari ST Degas .pi1, Amiga IFF .iff, MSX Screen 2 .sc2 and
//                      Screen 8 .sc8), every file checked by RECOIL
//   RECOIL.cs          generated RECOIL library (never edit by hand; see tools/downgrade_recoil.py)

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

[assembly: AssemblyTitle("RetroGleek")]
[assembly: AssemblyDescription("Offline image browser and viewer")]
[assembly: AssemblyProduct("RetroGleek")]
[assembly: AssemblyCompany("Mark Billson")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Mark Billson. MIT License.")]
[assembly: AssemblyVersion("1.2.0.0")]
[assembly: AssemblyFileVersion("1.2.0.0")]

static class Program
{
    static bool reporting;
    public static bool RetroFromArgs = false;       // --retro / --no-retro: just for this run, not saved (set by the window's Main)

    // Shows any unexpected error in a message box (Ctrl+C in the box copies the text).
    // Nothing is written to disk and nothing is sent anywhere.
    static void Report(Exception ex)
    {
        if (reporting) return;                       // don't stack dialogs if a repaint keeps failing
        reporting = true;
        try
        {
            MessageBox.Show("RetroGleek hit an unexpected error:\n\n" + (ex == null ? "(unknown)" : ex.ToString()),
                            "RetroGleek", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        catch (Exception) { }
        reporting = false;
    }

#if CLI
    // RetroGleekCli.exe: the console companion (built by build.bat with /define:CLI from the same source files).
    //   RetroGleekCli.exe <folder> [--out <file>] [--no-thumbs] [--csv] [--overwrite] [--quiet]
    // Prints progress and a summary; same exit codes as RetroGleek.exe --audit.
    [STAThread]
    static int Main(string[] args)
    {
        foreach (string a in args)
            if (a == "--help" || a == "-h" || a == "/?") { Usage(Console.Out); return 0; }
        if (args.Length == 0) { Usage(Console.Error); return 2; }
        var list = new List<string>(args);
        bool hasAudit = list.Exists(x => string.Equals(x, "--audit", StringComparison.OrdinalIgnoreCase));
        if (!hasAudit && !args[0].StartsWith("-")) list.Insert(0, "--audit");     // "RetroGleekCli.exe <folder>" is enough
        return RunAudit(list.ToArray(), Console.Out, Console.Error);
    }

    static void Usage(TextWriter w)
    {
        w.WriteLine("RetroGleekCli - folder audit from the command line (part of RetroGleek, MIT License, (c) 2026 Mark Billson)");
        w.WriteLine();
        w.WriteLine("  RetroGleekCli.exe <folder> [--out <file>] [--no-thumbs] [--csv] [--overwrite] [--quiet]");
        w.WriteLine();
        w.WriteLine("  <folder>       the folder to audit (its pictures only, not subfolders)");
        w.WriteLine("  --out <file>   where to write the report (default: in the folder, \"RetroGleek audit - <folder> - <date>.html\")");
        w.WriteLine("  --no-thumbs    leave the thumbnails out of the HTML page (a much smaller file)");
        w.WriteLine("  --csv          write a CSV file instead of the HTML page");
        w.WriteLine("  --overwrite    replace the report if it already exists");
        w.WriteLine("  --quiet        no progress, no summary (errors are still shown)");
        w.WriteLine();
        w.WriteLine("Exit code: 0 = every picture file opened, 1 = some could not be opened, 2 = error.");
    }
#else
    [STAThread]
    static int Main(string[] args)
    {
        foreach (string a in args)
            if (string.Equals(a, "--audit", StringComparison.OrdinalIgnoreCase)) return RunAudit(args, null, null);   // no window at all
        try
        {
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += delegate (object s, ThreadExceptionEventArgs e) { Report(e.Exception); };
            AppDomain.CurrentDomain.UnhandledException += delegate (object s, UnhandledExceptionEventArgs e) { Report(e.ExceptionObject as Exception); };

            // High-DPI awareness (real pixels, no blurry scaling) is declared in RetroGleek.manifest.
            using (Graphics g = Graphics.FromHwnd(IntPtr.Zero)) Util.K = g.DpiX / 96f;
            Application.EnableVisualStyles();
            Prefs.Load();                                // settings.ini next to the exe (defaults if there is none)
            Retro.Enabled = Prefs.Bool("retro", true);
            string first = null;
            foreach (string a in args)
            {
                if (string.Equals(a, "--retro", StringComparison.OrdinalIgnoreCase)) { Retro.Enabled = true; RetroFromArgs = true; }
                else if (string.Equals(a, "--no-retro", StringComparison.OrdinalIgnoreCase)) { Retro.Enabled = false; RetroFromArgs = true; }
                else if (first == null) first = a;
            }
            Application.Run(new MainForm(first));
        }
        catch (Exception ex) { Report(ex); }
        return 0;
    }

#endif

    // The command-line audit, shared by RetroGleek.exe --audit (no output at all: outw / errw are null) and by
    // RetroGleekCli.exe (progress on errw, summary on outw).
    //   --audit <folder> [--out <file>] [--no-thumbs] [--csv] [--overwrite] [--quiet]
    // Exit code: 0 = every picture file opened, 1 = some could not be opened, 2 = error (bad arguments, folder missing
    // or not local, report already exists without --overwrite, report could not be written). No dialog boxes;
    // settings.ini is neither read nor written; marks.tsv is read (never written) so the report includes your marks.
    static int RunAudit(string[] args, TextWriter outw, TextWriter errw)
    {
        try
        {
            string dir = null, outFile = null;
            bool thumbs = true, csv = false, overwrite = false, quiet = false;
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (string.Equals(a, "--audit", StringComparison.OrdinalIgnoreCase))
                { if (++i >= args.Length) return Fail(errw, "--audit needs a folder."); dir = args[i]; }
                else if (string.Equals(a, "--out", StringComparison.OrdinalIgnoreCase))
                { if (++i >= args.Length) return Fail(errw, "--out needs a file name."); outFile = args[i]; }
                else if (string.Equals(a, "--no-thumbs", StringComparison.OrdinalIgnoreCase)) thumbs = false;
                else if (string.Equals(a, "--csv", StringComparison.OrdinalIgnoreCase)) csv = true;
                else if (string.Equals(a, "--overwrite", StringComparison.OrdinalIgnoreCase)) overwrite = true;
                else if (string.Equals(a, "--quiet", StringComparison.OrdinalIgnoreCase)) quiet = true;
                else return Fail(errw, "Unknown option: " + a + "   (--help lists the options)");   // never guess
            }
            if (string.IsNullOrEmpty(dir)) return Fail(errw, "No folder given.");
            if (!LocalPath(dir)) return Fail(errw, "Only folders on local drives can be audited: " + dir);
            dir = Path.GetFullPath(dir);
            if (!Directory.Exists(dir)) return Fail(errw, "Folder not found: " + dir);
            string dest = string.IsNullOrEmpty(outFile) ? Path.Combine(dir, FolderAudit.DefaultFileName(dir, thumbs, csv)) : Path.GetFullPath(outFile);
            if (!LocalPath(dest)) return Fail(errw, "The report can only be written to a local drive: " + dest);
            if (!Directory.Exists(Path.GetDirectoryName(dest))) return Fail(errw, "The folder for the report does not exist: " + Path.GetDirectoryName(dest));
            if (File.Exists(dest) && !overwrite) return Fail(errw, "The report already exists (add --overwrite to replace it): " + dest);

            Marks.ReadOnly = true;                           // read only: the report shows your ratings, labels and tags
            Marks.Load();
            bool live = errw != null && !quiet && !ErrRedirected();
            Action<int, int, string> progress = null;
            if (live)
                progress = delegate (int k, int total, string name)
                {
                    string line = "  " + k + " of " + total + "  " + name;
                    if (line.Length > 78) line = line.Substring(0, 75) + "...";
                    errw.Write("\r" + line.PadRight(79));
                };
            int skipped;
            List<AuditEntry> list = FolderAudit.Scan(dir, thumbs && !csv, progress, out skipped);
            if (live) errw.Write("\r" + new string(' ', 79) + "\r");
            string text = csv ? FolderAudit.Csv(list) : FolderAudit.Page(dir, list, skipped, DateTime.Now, thumbs);
            FolderAudit.WriteReport(dest, text, csv, overwrite);

            int failed = 0;
            foreach (AuditEntry e in list) if (e.Status == "Failed") failed++;
            if (outw != null && !quiet) Summary(outw, dir, dest, list, skipped);
            return failed > 0 ? 1 : 0;
        }
        catch (Exception ex) { return Fail(errw, ex.Message); }
    }

    static int Fail(TextWriter errw, string message)
    {
        if (errw != null) { try { errw.WriteLine("Error: " + message); } catch (Exception) { } }
        return 2;
    }

    static bool ErrRedirected()
    {
        try { return Console.IsErrorRedirected; } catch (Exception) { return true; }
    }

    static void Summary(TextWriter w, string dir, string dest, List<AuditEntry> list, int skipped)
    {
        int ok = 0, failed = 0, cloud = 0, dups = 0, retro = 0;
        var byPlatform = new Dictionary<string, int>();
        foreach (AuditEntry e in list)
        {
            if (e.Status == "OK") ok++; else if (e.Status == "Failed") failed++; else if (e.Status == "Cloud-only") cloud++;
            if (e.DupOf != null) dups++;
            if (e.Kind != "Standard") retro++;
            if (e.Status == "OK")
            {
                string p = string.IsNullOrEmpty(e.Platform) ? "Unknown" : e.Platform;
                int c; byPlatform.TryGetValue(p, out c); byPlatform[p] = c + 1;
            }
        }
        w.WriteLine("RetroGleek folder audit");
        w.WriteLine("  Folder:  " + dir);
        w.WriteLine("  Report:  " + dest);
        w.WriteLine();
        w.WriteLine("  Picture files: " + list.Count + "   opened: " + ok + "   could not be opened: " + failed +
                    "   cloud-only: " + cloud + "   duplicates: " + dups + "   retro: " + retro);
        if (skipped > 0) w.WriteLine("  Generic-extension files that are not pictures (not listed): " + skipped);
        if (byPlatform.Count > 0)
        {
            w.WriteLine();
            w.WriteLine("  Opened, by platform:");
            var keys = new List<string>(byPlatform.Keys);
            keys.Sort(delegate (string x, string y) { int cc = byPlatform[y].CompareTo(byPlatform[x]); return cc != 0 ? cc : string.Compare(x, y, StringComparison.OrdinalIgnoreCase); });
            foreach (string k in keys) w.WriteLine("    " + k.PadRight(36) + byPlatform[k].ToString().PadLeft(7));
        }
        if (failed > 0)
        {
            w.WriteLine();
            w.WriteLine("  Could not be opened:");
            foreach (AuditEntry e in list)
                if (e.Status == "Failed") w.WriteLine("    " + e.Name + "  -  " + (e.Error ?? ""));
        }
    }

    // local drives only (the program never reads from or writes to the network)
    static bool LocalPath(string p)
    {
        try
        {
            if (p.StartsWith("\\\\") || p.StartsWith("//")) return false;
            string root = Path.GetPathRoot(Path.GetFullPath(p));
            return !string.IsNullOrEmpty(root) && new DriveInfo(root).DriveType != DriveType.Network;
        }
        catch (Exception) { return false; }
    }
}
