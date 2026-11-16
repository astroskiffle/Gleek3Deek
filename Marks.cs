// RetroGleek - marks: star ratings, colour labels and the tag (marks.tsv next to settings.ini)
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE). Part of RetroGleek; see Program.cs for the overview.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

// What you marked a picture with. Kept outside the picture files (so it works for every format, retro ones
// included, and never changes a picture), in one small text file. A mark belongs to a file of a given size and
// date: if the file is changed, replaced or copied over, its old mark no longer applies and is ignored.
sealed class Mark
{
    public int Stars;            // 0 = no rating, 1..5
    public int Label;            // 0 = no colour label, 1..5 (see Marks.LabelNames)
    public bool Tag;
    public long Size, Modified;  // the file the mark belongs to (Modified = last write time, UTC ticks)

    public bool Empty { get { return Stars == 0 && Label == 0 && !Tag; } }
}

static class Marks
{
    const string FileName = "marks.tsv";
    public static readonly string[] LabelNames = { "No label", "Red", "Yellow", "Green", "Blue", "Purple" };
    public static readonly System.Drawing.Color[] LabelColours =
    {
        System.Drawing.Color.Empty,
        System.Drawing.Color.FromArgb(225, 70, 70),
        System.Drawing.Color.FromArgb(235, 200, 60),
        System.Drawing.Color.FromArgb(85, 185, 95),
        System.Drawing.Color.FromArgb(70, 135, 235),
        System.Drawing.Color.FromArgb(165, 105, 215)
    };

    static readonly Dictionary<string, Mark> map = new Dictionary<string, Mark>(StringComparer.OrdinalIgnoreCase);
    static readonly object sync = new object();            // the audit reads marks on a worker thread
    static bool loaded;
    // name + size + date -> marked paths, to find a mark again after Explorer moved or renamed the file's folder
    static readonly Dictionary<string, List<string>> byFacts = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
    // folder + size + date -> marked paths, to find a mark again after Explorer renamed the file itself
    static readonly Dictionary<string, List<string>> byPlace = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
    // pictures already found to be too uncertain to take a renamed file's mark (asked again only after marks change)
    static readonly HashSet<string> unsure = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    static bool factsDirty = true;
    public static bool ReadOnly;                            // the command-line audit: marks.tsv is read, never written

    // e.g. "\u2605\u2605\u2605" for 3 stars (empty for none)
    public static string StarText(int n) { return n <= 0 ? "" : new string('\u2605', Math.Min(5, n)); }

    // marks.tsv sits next to settings.ini (next to RetroGleek.exe, or in %LOCALAPPDATA%\RetroGleek\)
    static string[] Candidates()
    {
        var r = new List<string>();
        foreach (string p in Prefs.Candidates()) r.Add(Path.Combine(Path.GetDirectoryName(p), FileName));
        return r.ToArray();
    }

    public static void Load() { lock (sync) LoadLocked(); }

    static void LoadLocked()
    {
        loaded = true;
        factsDirty = true;
        map.Clear();
        foreach (string p in Candidates())
        {
            try
            {
                if (!File.Exists(p)) continue;
                var fi = new FileInfo(p);
                if (fi.Length > 32 * 1024 * 1024 || (fi.Attributes & Util.CloudMask) != 0) continue;
                foreach (string line in File.ReadAllLines(p, Encoding.UTF8))
                {
                    if (line.Length == 0 || line[0] == '#') continue;
                    string[] f = line.Split('\t');                       // path, size, modified, stars, label, tag
                    if (f.Length < 6 || f[0].Length == 0) continue;
                    var m = new Mark();
                    int st, lb;
                    if (!long.TryParse(f[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out m.Size)) continue;
                    if (!long.TryParse(f[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out m.Modified)) continue;
                    if (!int.TryParse(f[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out st)) continue;
                    if (!int.TryParse(f[4], NumberStyles.Integer, CultureInfo.InvariantCulture, out lb)) continue;
                    m.Stars = Math.Max(0, Math.Min(5, st));
                    m.Label = Math.Max(0, Math.Min(5, lb));
                    m.Tag = f[5] == "1";
                    if (!m.Empty) map[f[0]] = m;
                }
                return;
            }
            catch (Exception) { map.Clear(); }
        }
    }

    // Written straight after every change (marking is an explicit action), through a temporary file so a crash
    // can never leave half a file. Same place rules as settings.ini; never on the network. Never throws.
    static void Save()
    {
        factsDirty = true;
        if (ReadOnly) return;
        var sb = new StringBuilder();
        sb.Append("# RetroGleek marks (ratings, colour labels, tags) - path, size, modified, stars, label, tag\r\n");
        var keys = new List<string>(map.Keys);
        keys.Sort(StringComparer.OrdinalIgnoreCase);
        foreach (string k in keys)
        {
            Mark m = map[k];
            if (m.Empty) continue;
            sb.Append(k).Append('\t').Append(m.Size.ToString(CultureInfo.InvariantCulture)).Append('\t')
              .Append(m.Modified.ToString(CultureInfo.InvariantCulture)).Append('\t').Append(m.Stars).Append('\t')
              .Append(m.Label).Append('\t').Append(m.Tag ? "1" : "0").Append("\r\n");
        }
        foreach (string p in Candidates())
        {
            string tmp = p + ".tmp";
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(p));
                File.WriteAllText(tmp, sb.ToString(), new UTF8Encoding(false));
                if (File.Exists(p)) File.Delete(p);
                File.Move(tmp, p);
                foreach (string other in Candidates())
                    if (!string.Equals(other, p, StringComparison.OrdinalIgnoreCase) && File.Exists(other)) { try { File.Delete(other); } catch (Exception) { } }
                return;
            }
            catch (Exception) { try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { } }
        }
    }

    // the mark of a picture, or null; size / modified are the file's current ones (from the grid's Item)
    public static Mark Get(string path, long size, long modified)
    {
        if (!loaded || path == null) return null;
        lock (sync)
        {
            Mark m;
            if (!map.TryGetValue(path, out m) && (m = Adopt(path, size, modified)) == null) return null;
            if (m.Size != size || m.Modified != modified) return null;
            return new Mark { Stars = m.Stars, Label = m.Label, Tag = m.Tag, Size = m.Size, Modified = m.Modified };   // a copy
        }
    }

    // A picture with no mark of its own: was it moved or renamed outside RetroGleek (in Explorer, say)? Under the lock.
    //  1. Moved, or its folder moved or renamed: a mark belongs to a file of the same name, size and date that is no
    //     longer where it was - on a drive that is still there, so an unplugged USB stick never loses its marks.
    //  2. Renamed on its own: a mark belongs to a file in this same folder, with the same size and date, that is no
    //     longer there. Taken only when it is certain: exactly one such marked file has gone, and this picture is the
    //     only file in the folder with that size and date (so a copy or a duplicate never takes it).
    // A copy never takes a mark: the original is still there.
    static Mark Adopt(string path, long size, long modified)
    {
        if (map.Count == 0) return null;
        if (factsDirty) Index();
        List<string> cands;
        if (byFacts.TryGetValue(Facts(path, size, modified), out cands))
        {
            foreach (string old in cands)
            {
                try
                {
                    string root = Path.GetPathRoot(old);
                    if (string.IsNullOrEmpty(root) || !Directory.Exists(root) || File.Exists(old)) continue;
                    if (!File.Exists(path)) return null;
                    return Take(old, path);
                }
                catch (Exception) { }
            }
        }
        string place = Place(path, size, modified);
        if (!byPlace.TryGetValue(place, out cands) || unsure.Contains(path)) return null;
        try
        {
            string gone = null;
            int goneCount = 0;
            foreach (string old in cands)
                if (!File.Exists(old)) { gone = old; goneCount++; }
            if (goneCount == 1 && File.Exists(path) && OnlyOneLike(path, size, modified)) return Take(gone, path);
        }
        catch (Exception) { }
        unsure.Add(path);                                   // not certain: leave it, and don't look in the folder again
        return null;
    }

    static Mark Take(string old, string path)
    {
        Mark m = map[old];
        map.Remove(old);
        map[path] = m;
        Save();
        return m;
    }

    static void Index()
    {
        byFacts.Clear();
        byPlace.Clear();
        unsure.Clear();
        foreach (KeyValuePair<string, Mark> kv in map)
        {
            AddTo(byFacts, Facts(kv.Key, kv.Value.Size, kv.Value.Modified), kv.Key);
            AddTo(byPlace, Place(kv.Key, kv.Value.Size, kv.Value.Modified), kv.Key);
        }
        factsDirty = false;
    }

    static void AddTo(Dictionary<string, List<string>> d, string key, string path)
    {
        List<string> l;
        if (!d.TryGetValue(key, out l)) d[key] = l = new List<string>();
        l.Add(path);
    }

    // is this picture the only file in its folder with this size and date? (one listing of the folder; nothing is
    // opened, so cloud placeholders are not downloaded)
    static bool OnlyOneLike(string path, long size, long modified)
    {
        string dir = Path.GetDirectoryName(path);
        if (string.IsNullOrEmpty(dir)) return false;
        int n = 0;
        foreach (FileInfo fi in new DirectoryInfo(dir).GetFiles())
            if (fi.Length == size && fi.LastWriteTimeUtc.Ticks == modified && ++n > 1) return false;
        return n == 1;
    }

    static string Facts(string path, long size, long modified)
    {
        return Path.GetFileName(path) + "|" + size.ToString(CultureInfo.InvariantCulture) + "|" + modified.ToString(CultureInfo.InvariantCulture);
    }

    static string Place(string path, long size, long modified)
    {
        return (Path.GetDirectoryName(path) ?? "") + "|" + size.ToString(CultureInfo.InvariantCulture) + "|" + modified.ToString(CultureInfo.InvariantCulture);
    }

    // the mark of a file on disk (reads its size and date), or null
    public static Mark ForFile(string path)
    {
        long size, mod;
        return FileFacts(path, out size, out mod) ? Get(path, size, mod) : null;
    }

    static bool FileFacts(string path, out long size, out long modified)
    {
        size = modified = 0;
        try
        {
            var fi = new FileInfo(path);
            if (!fi.Exists) return false;
            size = fi.Length; modified = fi.LastWriteTimeUtc.Ticks;
            return true;
        }
        catch (Exception) { return false; }
    }

    // stars / label: -1 = leave as it is. tag: null = leave as it is.
    public static void Set(IList<string> paths, int stars, int label, bool? tag)
    {
        if (!loaded) Load();
        lock (sync) SetLocked(paths, stars, label, tag);
    }

    static void SetLocked(IList<string> paths, int stars, int label, bool? tag)
    {
        bool any = false;
        foreach (string p in paths)
        {
            long size, mod;
            if (!FileFacts(p, out size, out mod)) continue;
            Mark m;
            if (!map.TryGetValue(p, out m) || m.Size != size || m.Modified != mod) m = new Mark { Size = size, Modified = mod };
            if (stars >= 0) m.Stars = Math.Min(5, stars);
            if (label >= 0) m.Label = Math.Min(5, label);
            if (tag.HasValue) m.Tag = tag.Value;
            if (m.Empty) map.Remove(p); else map[p] = m;
            any = true;
        }
        if (any) Save();
    }

    // the file was changed by RetroGleek itself (a lossless JPEG turn): its mark stays with the new size and date
    public static void Rebind(string path, long oldSize, long oldModified)
    {
        if (!loaded || path == null) return;
        lock (sync)
        {
            Mark m;
            if (!map.TryGetValue(path, out m) || m.Size != oldSize || m.Modified != oldModified) return;
            long size, mod;
            if (!FileFacts(path, out size, out mod)) return;
            m.Size = size; m.Modified = mod;
            Save();
        }
    }

    // a file or folder was renamed or moved: its marks (and those of everything inside a folder) go with it
    public static void Moved(IList<KeyValuePair<string, string>> pairs)
    {
        if (!loaded || pairs == null) return;
        lock (sync) MovedLocked(pairs);
    }

    static void MovedLocked(IList<KeyValuePair<string, string>> pairs)
    {
        if (map.Count == 0) return;
        bool any = false;
        foreach (KeyValuePair<string, string> pr in pairs)
        {
            string from = pr.Key.TrimEnd('\\', '/'), to = pr.Value.TrimEnd('\\', '/');
            if (string.Equals(from, to, StringComparison.Ordinal)) continue;
            var hits = new List<string>();
            foreach (string k in map.Keys)
                if (string.Equals(k, from, StringComparison.OrdinalIgnoreCase) || k.StartsWith(from + "\\", StringComparison.OrdinalIgnoreCase)) hits.Add(k);
            foreach (string k in hits)
            {
                Mark m = map[k];
                map.Remove(k);
                map[to + k.Substring(from.Length)] = m;
                any = true;
            }
        }
        if (any) Save();
    }

    // how a set of marks reads in a message: "3 stars, red label, tagged"
    public static string Describe(Mark m)
    {
        if (m == null || m.Empty) return "no marks";
        var parts = new List<string>();
        if (m.Stars > 0) parts.Add(m.Stars + (m.Stars == 1 ? " star" : " stars"));
        if (m.Label > 0) parts.Add(LabelNames[m.Label].ToLowerInvariant() + " label");
        if (m.Tag) parts.Add("tagged");
        return string.Join(", ", parts.ToArray());
    }
}

// The star rating that Windows Explorer, Lightroom and other programs store inside JPEG / TIFF (and some PNG) files:
// the EXIF Rating tag (0x4746), or else xmp:Rating in the file's XMP block. RetroGleek writes it only into JPEG and PNG files, when asked (RatingWriter).
// Shown in silver wherever RetroGleek shows ratings; a RetroGleek rating of the same picture takes its place.
static class FileRating
{
    // img = the decoded picture if there is one (for the EXIF tag); 0 = no rating stored
    public static int Read(string path, System.Drawing.Image img) { return Read(path, img, false); }

    // anyName: read the XMP whatever the file is called (JpegRating checks its temporary file this way)
    public static int Read(string path, System.Drawing.Image img, bool anyName)
    {
        int r = 0;
        if (img != null)
        {
            try
            {
                if (Array.IndexOf(img.PropertyIdList, 0x4746) >= 0)
                {
                    byte[] v = img.GetPropertyItem(0x4746).Value;
                    if (v != null && v.Length > 0) r = v[0] != 0 ? v[0] : v.Length > 1 ? v[1] : 0;   // 0..5 in either byte order
                }
            }
            catch (Exception) { }
        }
        if (r <= 0 || r > 5) r = Xmp(path, anyName);
        return r > 0 && r <= 5 ? r : 0;
    }

    public static bool MayHold(string path)
    {
        string e = (Path.GetExtension(path) ?? "").ToLowerInvariant();
        return e == ".jpg" || e == ".jpeg" || e == ".jpe" || e == ".jfif" || e == ".tif" || e == ".tiff" || e == ".png";
    }

    // xmp:Rating="3" or <xmp:Rating>3</xmp:Rating>, looked for in the first 256 KB (where JPEG keeps its XMP)
    static int Xmp(string path, bool anyName)
    {
        if (!anyName && !MayHold(path)) return 0;
        try
        {
            byte[] buf;
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16))
            {
                int n = (int)Math.Min(fs.Length, 262144);
                buf = new byte[n];
                int got = 0;
                while (got < n) { int k = fs.Read(buf, got, n - got); if (k <= 0) break; got += k; }
            }
            string s = Encoding.ASCII.GetString(buf);
            int at = s.IndexOf("xmp:Rating", StringComparison.Ordinal);
            while (at >= 0)
            {
                int i = at + 10;
                while (i < s.Length && (s[i] == ' ' || s[i] == '=' || s[i] == '"' || s[i] == '\'' || s[i] == '>')) i++;
                if (i < s.Length && s[i] >= '0' && s[i] <= '5') return s[i] - '0';
                at = s.IndexOf("xmp:Rating", at + 10, StringComparison.Ordinal);
            }
        }
        catch (Exception) { }
        return 0;
    }
}
