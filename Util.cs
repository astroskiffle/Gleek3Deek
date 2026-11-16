// RetroGleek - shared helpers (DPI scaling, natural sort, UI-thread posting, file names, EXIF rotation)
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

// ====================================================================== helpers

static class Util
{
    public static readonly HashSet<string> Exts = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        { ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".bmp", ".dib", ".gif", ".tif", ".tiff" };

    // native (GDI+) and Windows-codec formats are always listed; retro formats only when the user opted in
    public static bool Listed(string ext) { return Exts.Contains(ext) || WinCodec.ClaimsExt(ext) || Retro.Listable(ext); }
    public static bool IsNative(string path) { return Exts.Contains(Path.GetExtension(path)); }

    // OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS: file content lives in the cloud, not on this PC.
    public const FileAttributes CloudMask = (FileAttributes)0x441000;

    public static float K = 1f;   // DPI scale factor

    [DllImport("shlwapi.dll", CharSet = CharSet.Unicode)] static extern int StrCmpLogicalW(string a, string b);
    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)] static extern int SetWindowTheme(IntPtr hwnd, string app, string ids);

    public static int NatCmp(string a, string b) { return StrCmpLogicalW(a, b); }   // Explorer-style order
    public static int S(int v) { return (int)Math.Round(v * K); }

    public static void Dark(Control c)
    {
        EventHandler apply = delegate { try { SetWindowTheme(c.Handle, "DarkMode_Explorer", null); } catch (Exception) { } };
        c.HandleCreated += apply;
        if (c.IsHandleCreated) apply(c, EventArgs.Empty);
    }

    // Run something on the UI thread from a worker; false if the window is gone.
    public static bool Post(Control host, MethodInvoker m)
    {
        try
        {
            if (host != null && host.IsHandleCreated && !host.IsDisposed) { host.BeginInvoke(m); return true; }
        }
        catch (Exception) { }
        return false;
    }

    // a short, readable reason for a failed decode (GDI+ reports unreadable files as 'out of memory')
    public static string Why(Exception ex)
    {
        return ex is OutOfMemoryException ? "Unsupported, damaged or too large." : ex.Message;
    }

    public static string FmtSize(long b)
    {
        if (b < 1024) return b + " B";
        if (b < 1048576) return (b / 1024.0).ToString("0.#") + " KB";
        if (b < 1073741824) return (b / 1048576.0).ToString("0.##") + " MB";
        return (b / 1073741824.0).ToString("0.##") + " GB";
    }

    public static bool SameDir(string a, string b)
    {
        return a != null && b != null &&
               string.Equals(a.TrimEnd('\\', '/'), b.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase);
    }

    public static byte[] ReadShared(string path)
    {
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16))
        {
            byte[] b = new byte[(int)fs.Length];
            int off = 0;
            while (off < b.Length)
            {
                int n = fs.Read(b, off, b.Length - off);
                if (n <= 0) break;
                off += n;
            }
            return b;
        }
    }

    // EXIF orientation -> quarter turns clockwise
    public static int ReadRotation(Image img)
    {
        try
        {
            if (Array.IndexOf(img.PropertyIdList, 0x0112) < 0) return 0;
            byte[] v = img.GetPropertyItem(0x0112).Value;
            int o = (v.Length > 1 && v[0] == 0) ? v[1] : v[0];     // value is 1..8, so read it whichever byte order the file / GDI+ uses
            switch (o) { case 3: return 2; case 6: return 1; case 8: return 3; }
        }
        catch (Exception) { }
        return 0;
    }

    public static string UniqueName(string dir, string name, bool isDir)
    {
        string stem = isDir ? name : Path.GetFileNameWithoutExtension(name);
        string ext = isDir ? "" : Path.GetExtension(name);
        string p = Path.Combine(dir, name);
        for (int i = 1; File.Exists(p) || Directory.Exists(p); i++)
            p = Path.Combine(dir, stem + " - Copy" + (i > 1 ? " (" + i + ")" : "") + ext);
        return p;
    }

    // dir\stem.ext, or dir\stem (2).ext, (3) ... - the first name that doesn't exist yet
    public static string UniquePath(string dir, string stem, string ext)
    {
        string p = Path.Combine(dir, stem + ext);
        for (int i = 2; File.Exists(p) || Directory.Exists(p); i++) p = Path.Combine(dir, stem + " (" + i + ")" + ext);
        return p;
    }

    // Copies a folder with everything in it. Cloud placeholders (files, and folders whose contents are not stored on
    // this PC) are never opened or copied, so a copy can't start a download: they are left out, and once everything
    // else is copied an IOException says how many were left out. The caller lists that message with the folder's
    // name, as it does for any other copy problem. Links and junctions are never followed.
    public static void CopyDir(string src, string dst)
    {
        if ((File.GetAttributes(src) & CloudMask) != 0)
            throw new IOException("cloud-only folder that isn't stored on this PC, so it was left alone.");
        int files = 0, folders = 0;
        CopyDir(src, dst, ref files, ref folders);
        if (files == 0 && folders == 0) return;
        throw new IOException("copied, except " + CloudText(files, folders) + " that " + (files + folders == 1 ? "isn't" : "aren't")
                              + " stored on this PC, so " + (files + folders == 1 ? "it was" : "they were") + " left out.");
    }

    // "3 cloud-only files and 1 cloud-only folder"
    public static string CloudText(int files, int folders)
    {
        return (files > 0 ? files + (files == 1 ? " cloud-only file" : " cloud-only files") : "")
             + (files > 0 && folders > 0 ? " and " : "")
             + (folders > 0 ? folders + (folders == 1 ? " cloud-only folder" : " cloud-only folders") : "");
    }

    // Counts the cloud placeholders inside a folder (and the folder itself, if it is one) from their attributes only:
    // nothing is opened, and a cloud-only folder is counted without being listed, so counting downloads nothing.
    // Stops after looking at 100,000 items (more = true), which also ends any loop of links.
    public static void CloudInside(string dir, out int files, out int folders, out bool more)
    {
        files = 0; folders = 0; more = false;
        if ((File.GetAttributes(dir) & CloudMask) != 0) { folders = 1; return; }
        int budget = 100000;
        var stack = new Stack<string>();
        stack.Push(dir);
        while (stack.Count > 0)
        {
            string d = stack.Pop();
            foreach (string f in Directory.GetFiles(d))
            {
                if (--budget < 0) { more = true; return; }
                if ((File.GetAttributes(f) & CloudMask) != 0) files++;
            }
            foreach (string sub in Directory.GetDirectories(d))
            {
                if (--budget < 0) { more = true; return; }
                if ((File.GetAttributes(sub) & CloudMask) != 0) { folders++; continue; }
                stack.Push(sub);              // folders synced by OneDrive can look like links, so they are looked into too
            }
        }
    }

    static void CopyDir(string src, string dst, ref int skippedFiles, ref int skippedFolders)
    {
        Directory.CreateDirectory(dst);
        foreach (string f in Directory.GetFiles(src))
        {
            if ((File.GetAttributes(f) & CloudMask) != 0) { skippedFiles++; continue; }   // reading the attributes downloads nothing
            File.Copy(f, Path.Combine(dst, Path.GetFileName(f)));
        }
        foreach (string d in Directory.GetDirectories(src))
        {
            FileAttributes a = File.GetAttributes(d);
            if ((a & CloudMask) != 0) { skippedFolders++; continue; }                     // listing it could fetch it from the cloud
            if ((a & FileAttributes.ReparsePoint) != 0) continue;                       // never follow links/junctions
            CopyDir(d, Path.Combine(dst, Path.GetFileName(d)), ref skippedFiles, ref skippedFolders);
        }
    }
}
