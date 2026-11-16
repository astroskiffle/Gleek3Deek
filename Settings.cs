// RetroGleek - remembered settings (settings.ini next to RetroGleek.exe)
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


// ====================================================================== remembered settings

// One small plain-text file, settings.ini, next to RetroGleek.exe (portable: it travels with the program).
// If that folder can't be written (Program Files, a read-only stick, a network location), the file goes to
// %LOCALAPPDATA%\RetroGleek\ instead. It is read once at start-up and written once when RetroGleek closes.
// Delete it (or use Settings > Reset to default settings) to start again with the defaults.
static class Prefs
{
    const string FileName = "settings.ini";
    static readonly Dictionary<string, string> values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    public static bool SkipSave;                           // Reset was chosen: don't write the current values at exit
    public static string LoadedFrom;                       // where the file was found (null = defaults)

    static string ExeDir()
    {
        try { return Path.GetDirectoryName(Application.ExecutablePath); } catch (Exception) { return null; }
    }

    static string ProfileDir()
    {
        try { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RetroGleek"); }
        catch (Exception) { return null; }
    }

    // a folder RetroGleek may keep its file in: local drives only (the program never writes to the network)
    static bool LocalFolder(string dir)
    {
        try
        {
            if (string.IsNullOrEmpty(dir) || dir.StartsWith("\\\\")) return false;
            string root = Path.GetPathRoot(Path.GetFullPath(dir));
            return !string.IsNullOrEmpty(root) && new DriveInfo(root).DriveType != DriveType.Network;
        }
        catch (Exception) { return false; }
    }

    public static string[] Candidates()
    {
        var r = new List<string>();
        string a = ExeDir(), b = ProfileDir();
        if (LocalFolder(a)) r.Add(Path.Combine(a, FileName));
        if (LocalFolder(b)) r.Add(Path.Combine(b, FileName));
        return r.ToArray();
    }

    public static void Load()
    {
        values.Clear();
        foreach (string p in Candidates())
        {
            try
            {
                if (!File.Exists(p)) continue;
                var fi = new FileInfo(p);
                if (fi.Length > 65536 || (fi.Attributes & Util.CloudMask) != 0) continue;
                foreach (string raw in File.ReadAllLines(p, System.Text.Encoding.UTF8))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line[0] == '#' || line[0] == ';') continue;
                    int eq = line.IndexOf('=');
                    if (eq <= 0) continue;
                    values[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
                }
                LoadedFrom = p;
                return;
            }
            catch (Exception) { values.Clear(); }
        }
    }

    // Writes the file (next to the exe if possible, else in the profile). Never throws.
    public static void Save()
    {
        if (SkipSave) return;
        var sb = new System.Text.StringBuilder();
        sb.Append("# RetroGleek settings - written when RetroGleek closes.\r\n");
        sb.Append("# Delete this file to go back to the default settings.\r\n");
        var keys = new List<string>(values.Keys);
        keys.Sort(StringComparer.OrdinalIgnoreCase);
        foreach (string k in keys) sb.Append(k).Append('=').Append(values[k]).Append("\r\n");
        foreach (string p in Candidates())
        {
            string tmp = p + ".tmp";
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(p));
                File.WriteAllText(tmp, sb.ToString(), new System.Text.UTF8Encoding(false));
                if (File.Exists(p)) File.Delete(p);
                File.Move(tmp, p);
                // only one copy: a file left at the other place would be read first next time
                foreach (string other in Candidates())
                    if (!string.Equals(other, p, StringComparison.OrdinalIgnoreCase) && File.Exists(other)) { try { File.Delete(other); } catch (Exception) { } }
                return;
            }
            catch (Exception) { try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { } }
        }
    }

    // Settings > Reset: removes the file; the defaults apply from the next start
    public static void Reset()
    {
        SkipSave = true;
        foreach (string p in Candidates()) { try { if (File.Exists(p)) File.Delete(p); } catch (Exception) { } }
    }

    public static string Get(string key, string def)
    {
        string v;
        return values.TryGetValue(key, out v) ? v : def;
    }

    public static int Int(string key, int def, int min, int max)
    {
        int v;
        if (!int.TryParse(Get(key, ""), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out v)) return def;
        return Math.Max(min, Math.Min(max, v));
    }

    public static bool Bool(string key, bool def)
    {
        string v = Get(key, "");
        if (v == "1" || string.Equals(v, "true", StringComparison.OrdinalIgnoreCase)) return true;
        if (v == "0" || string.Equals(v, "false", StringComparison.OrdinalIgnoreCase)) return false;
        return def;
    }

    public static void Set(string key, string value)
    {
        if (value == null) { values.Remove(key); return; }
        values[key] = value.Replace("\r", " ").Replace("\n", " ");
    }

    public static void Set(string key, int value) { Set(key, value.ToString(System.Globalization.CultureInfo.InvariantCulture)); }
    public static void Set(string key, bool value) { Set(key, value ? "1" : "0"); }
}
