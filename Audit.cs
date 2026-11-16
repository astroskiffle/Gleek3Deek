// RetroGleek - folder audit: an offline HTML report of every picture file in one folder
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


// ====================================================================== folder audit (HTML report)

sealed class AuditEntry
{
    public string Name, Ext, Kind, Status, Platform, Format, Error, Hash, DupOf, Thumb;
    public long Size, Modified;            // Modified: milliseconds since 1970 (UTC), for the page's own date display
    public int W, H, Frames = 1, Colours = -1;
    public int Stars, Label;               // your marks (marks.tsv): 0..5 stars, colour label 0..5
    public bool Tag;
    public int FileStars;                  // the rating stored in the file itself (Windows, Lightroom ...), 0 = none
}

// Examines every picture file in one folder (not subfolders) and writes a self-contained HTML page about them.
// Only reads files; the report is written only to the place the user chose. The page needs nothing from the
// internet: no links, no fonts, no scripts from elsewhere, and a content policy that blocks any network access.
static class FolderAudit
{
    const int ThumbSize = 96;
    const long MaxColourPixels = 4L * 1024 * 1024;         // colours are counted for pictures up to 4 million pixels
    static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

    // Worker thread. skipped = files with a too-generic extension (.raw .img ...) that turned out not to be pictures.
    // thumbs = false: the pictures are still decoded (so damaged files are caught) but no thumbnails are stored
    public static List<AuditEntry> Scan(string dir, bool thumbs, Action<int, int, string> progress, out int skipped)
    {
        skipped = 0;
        var files = new List<FileInfo>();
        foreach (FileInfo fi in new DirectoryInfo(dir).EnumerateFiles())
        {
            if ((fi.Attributes & FileAttributes.Hidden) != 0) continue;
            if (Util.IsNative(fi.FullName) || WinCodec.Claims(fi.FullName) || Retro.Claims(fi.FullName)) files.Add(fi);
        }
        files.Sort(delegate (FileInfo a, FileInfo b) { return Util.NatCmp(a.Name, b.Name); });
        var list = new List<AuditEntry>();
        var byHash = new Dictionary<string, string>();
        for (int i = 0; i < files.Count; i++)
        {
            if (progress != null) progress(i + 1, files.Count, files[i].Name);
            AuditEntry e = Examine(files[i], thumbs);
            if (e == null) { skipped++; continue; }
            if (e.Hash != null)
            {
                string first;
                if (byHash.TryGetValue(e.Hash, out first)) e.DupOf = first; else byHash[e.Hash] = e.Name;
            }
            list.Add(e);
        }
        return list;
    }

    // Analyse folder (Details view): everything the audit finds out about one file, without a thumbnail.
    // null = a generic-extension file that is not a picture. Worker thread.
    public static AuditEntry Analyse(string path) { return Examine(new FileInfo(path), false); }

    static AuditEntry Examine(FileInfo fi, bool thumbs)
    {
        string path = fi.FullName;
        bool native = Util.IsNative(path);
        bool codec = !native && WinCodec.Claims(path);                       // WebP, HEIC, camera RAW ... (Windows' decoders)
        bool generic = !native && !codec && !Retro.Specific(fi.Extension);
        var e = new AuditEntry
        {
            Name = fi.Name, Ext = fi.Extension.TrimStart('.').ToUpperInvariant(), Size = fi.Length,
            Modified = (long)(fi.LastWriteTimeUtc - Epoch).TotalMilliseconds,
            Kind = native || codec ? "Standard" : generic ? "Retro (generic extension)" : "Retro"
        };
        Mark mk = Marks.Get(path, fi.Length, fi.LastWriteTimeUtc.Ticks);          // ratings, labels and tags
        if (mk != null) { e.Stars = mk.Stars; e.Label = mk.Label; e.Tag = mk.Tag; }
        if ((fi.Attributes & Util.CloudMask) != 0)
        {
            if (generic) return null;
            e.Status = "Cloud-only";
            e.Error = "Not stored on this PC, so it was not opened (RetroGleek never downloads files).";
            return e;
        }
        try { e.Hash = Sha256(path); } catch (Exception) { }
        Bitmap thumbSrc = null;
        try
        {
            if (native)
            {
                byte[] data = Util.ReadShared(path);
                using (var ms = new MemoryStream(data, false))
                using (Image img = Image.FromStream(ms, false, true))    // validate the data: catch damaged files
                {
                    e.W = img.Width; e.H = img.Height;
                    e.Format = FormatName(img.RawFormat);
                    e.Platform = "PC (standard image)";
                    foreach (Guid g in img.FrameDimensionsList)
                    {
                        if (g == FrameDimension.Time.Guid) { e.Frames = img.GetFrameCount(FrameDimension.Time); break; }
                        if (g == FrameDimension.Page.Guid) e.Frames = img.GetFrameCount(FrameDimension.Page);
                    }
                    e.Thumb = Thumb(img, thumbs);                         // drawing it decodes the first frame for real
                    if (FileRating.MayHold(path)) e.FileStars = FileRating.Read(path, img);
                    var b = img as Bitmap;
                    if (b != null && (long)e.W * e.H <= MaxColourPixels) e.Colours = CountColours(b);
                }
            }
            else if (codec)
            {
                CodecPic c;
                try { c = WinCodec.Load(path, 0, false); }                     // the whole picture, so damage is caught
                catch (Exception cex) { throw new IOException(WinCodec.Why(path, cex)); }
                thumbSrc = c.Bmp;
                e.W = c.W; e.H = c.H;                                         // as stored (like the other formats)
                if (c.Rot != 0) thumbSrc.RotateFlip(c.Rot == 1 ? RotateFlipType.Rotate90FlipNone : c.Rot == 2 ? RotateFlipType.Rotate180FlipNone : RotateFlipType.Rotate270FlipNone);
                e.Platform = "PC (standard image)";
                e.Frames = c.Frames;
                e.Format = c.Format;
                e.FileStars = c.Stars;
                e.Thumb = Thumb(thumbSrc, thumbs);
                if ((long)e.W * e.H <= MaxColourPixels) e.Colours = CountColours(thumbSrc);
            }
            else
            {
                long bytes; string platform; int frames;
                thumbSrc = Retro.Load(path, out bytes, out platform, out frames);
                e.W = thumbSrc.Width; e.H = thumbSrc.Height;
                e.Platform = string.IsNullOrEmpty(platform) ? "Unknown" : platform;
                e.Frames = frames;
                e.Format = "RECOIL " + Recoil.RECOIL.Version;
                e.Thumb = Thumb(thumbSrc, thumbs);
                if ((long)e.W * e.H <= MaxColourPixels) e.Colours = CountColours(thumbSrc);
            }
            e.Status = "OK";
        }
        catch (Exception ex)
        {
            if (generic) return null;                             // a .raw / .img that isn't a picture: not listed
            e.Status = "Failed";
            e.Error = ex is OutOfMemoryException ? "Unsupported, damaged or too large."
                    : ex is ArgumentException ? "Damaged, or not really a " + e.Ext + " file."
                    : ex.Message;
        }
        finally { if (thumbSrc != null) thumbSrc.Dispose(); }
        return e;
    }

    static string Sha256(string path)
    {
        using (var sha = System.Security.Cryptography.SHA256.Create())
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16))
        {
            byte[] h = sha.ComputeHash(fs);
            var sb = new System.Text.StringBuilder(64);
            foreach (byte x in h) sb.Append(x.ToString("x2"));
            return sb.ToString();
        }
    }

    static string FormatName(ImageFormat f)
    {
        Guid g = f.Guid;
        if (g == ImageFormat.Jpeg.Guid) return "JPEG";
        if (g == ImageFormat.Png.Guid) return "PNG";
        if (g == ImageFormat.Gif.Guid) return "GIF";
        if (g == ImageFormat.Bmp.Guid || g == ImageFormat.MemoryBmp.Guid) return "BMP";
        if (g == ImageFormat.Tiff.Guid) return "TIFF";
        return "Other";
    }

    // a small PNG thumbnail as base64 (pixel art stays sharp: nearest neighbour when it is shrunk by whole steps).
    // keep = false: only draws it (which makes GDI+ really decode the picture) and returns null
    static string Thumb(Image img, bool keep)
    {
        int w = img.Width, h = img.Height;
        double s = Math.Min(1.0, (double)ThumbSize / Math.Max(w, h));
        int tw = Math.Max(1, (int)Math.Round(w * s)), th = Math.Max(1, (int)Math.Round(h * s));
        using (var bmp = new Bitmap(tw, th, PixelFormat.Format32bppArgb))
        {
            using (Graphics g = Graphics.FromImage(bmp))
            using (var ia = new ImageAttributes())
            {
                ia.SetWrapMode(WrapMode.TileFlipXY);
                g.InterpolationMode = s >= 1.0 ? InterpolationMode.NearestNeighbor : InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                g.DrawImage(img, new Rectangle(0, 0, tw, th), 0, 0, w, h, GraphicsUnit.Pixel, ia);
            }
            if (!keep) return null;
            using (var ms = new MemoryStream())
            {
                bmp.Save(ms, ImageFormat.Png);
                return Convert.ToBase64String(ms.ToArray());
            }
        }
    }

    // distinct colours of the (first frame of the) picture; stops at 65,536
    static int CountColours(Bitmap b)
    {
        int w = b.Width, h = b.Height;
        var seen = new HashSet<int>();
        BitmapData bd = b.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            int[] row = new int[w];
            for (int y = 0; y < h; y++)
            {
                Marshal.Copy(new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), row, 0, w);
                for (int x = 0; x < w; x++)
                {
                    seen.Add(row[x]);
                    if (seen.Count >= 65536) return 65536;
                }
            }
        }
        finally { b.UnlockBits(bd); }
        return seen.Count;
    }

    // ------------------------------------------------------------------ files

    // the suggested report name: "RetroGleek audit - <folder> - <date>[ (no thumbnails)].html|.csv"
    public static string DefaultFileName(string dir, bool thumbs, bool csv)
    {
        string folderName = Path.GetFileName(dir.TrimEnd('\\'));
        if (folderName.Length == 0) folderName = dir.Substring(0, 1) + " drive";
        foreach (char c in Path.GetInvalidFileNameChars()) folderName = folderName.Replace(c, '_');
        return "RetroGleek audit - " + folderName + " - " + DateTime.Now.ToString("yyyy-MM-dd") +
               (thumbs || csv ? "" : " (no thumbnails)") + (csv ? ".csv" : ".html");
    }

    // writes the report under a temporary name first, then puts it in place (replacing an old one only if allowed)
    public static void WriteReport(string dest, string text, bool bom, bool overwrite)
    {
        if (!overwrite && File.Exists(dest)) throw new IOException("The report file already exists: " + dest);
        string tmp = dest + "." + Guid.NewGuid().ToString("N").Substring(0, 8) + ".tmp";
        try
        {
            File.WriteAllText(tmp, text, new System.Text.UTF8Encoding(bom));
            if (File.Exists(dest)) File.Delete(dest);
            File.Move(tmp, dest);
        }
        finally { try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { } }
    }

    // the same columns as the page's "Download CSV" (UTF-8 with a byte-order mark, so Excel reads names correctly)
    public static string Csv(List<AuditEntry> list)
    {
        var sb = new System.Text.StringBuilder();
        sb.Append("Name,Type,Kind,Platform,Status,Size (bytes),Width,Height,Frames,Colours,Modified,SHA-256,Notes,Rating,Label,Tagged,Rating source\r\n");
        foreach (AuditEntry e in list)
        {
            string note = (e.DupOf != null ? "Duplicate of " + e.DupOf + (e.Error != null ? ". " : "") : "") + (e.Error ?? "");
            string when = Epoch.AddMilliseconds(e.Modified).ToLocalTime().ToString("yyyy-MM-dd HH:mm");
            string[] f =
            {
                e.Name, e.Ext, e.Kind, e.Platform ?? "", e.Status, N(e.Size), e.W > 0 ? N(e.W) : "", e.H > 0 ? N(e.H) : "",
                e.W > 0 ? N(e.Frames) : "", e.Colours < 0 ? "" : N(e.Colours), when, e.Hash ?? "", note,
                e.Stars > 0 ? N(e.Stars) : e.FileStars > 0 ? N(e.FileStars) : "", e.Label > 0 ? Marks.LabelNames[e.Label] : "", e.Tag ? "yes" : "",
                e.Stars > 0 ? "RetroGleek" : e.FileStars > 0 ? "file" : ""
            };
            for (int i = 0; i < f.Length; i++)
            {
                if (i > 0) sb.Append(',');
                string v = f[i] ?? "";
                if (v.IndexOfAny(new[] { '"', ',', '\r', '\n' }) >= 0) v = "\"" + v.Replace("\"", "\"\"") + "\"";
                sb.Append(v);
            }
            sb.Append("\r\n");
        }
        return sb.ToString();
    }

    // ------------------------------------------------------------------ the HTML page

    static string Html(string s)
    {
        if (s == null) return "";
        return s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;").Replace("'", "&#39;");
    }

    // a JSON string; everything outside plain ASCII (and < > &) is escaped, so the page source stays ASCII
    static string J(string s)
    {
        if (s == null) return "null";
        var sb = new System.Text.StringBuilder(s.Length + 2);
        sb.Append('"');
        foreach (char c in s)
        {
            if (c == '"' || c == '\\') sb.Append('\\').Append(c);
            else if (c < 0x20 || c > 0x7E || c == '<' || c == '>' || c == '&') sb.Append("\\u").Append(((int)c).ToString("x4"));
            else sb.Append(c);
        }
        return sb.Append('"').ToString();
    }

    static string N(long v) { return v.ToString(System.Globalization.CultureInfo.InvariantCulture); }

    public static string Page(string dir, List<AuditEntry> list, int skipped, DateTime when, bool thumbs)
    {
        var data = new System.Text.StringBuilder();
        data.Append("[");
        for (int i = 0; i < list.Count; i++)
        {
            AuditEntry e = list[i];
            if (i > 0) data.Append(",\n");
            data.Append("{\"n\":").Append(J(e.Name)).Append(",\"e\":").Append(J(e.Ext)).Append(",\"k\":").Append(J(e.Kind))
                .Append(",\"st\":").Append(J(e.Status)).Append(",\"p\":").Append(J(e.Platform)).Append(",\"fmt\":").Append(J(e.Format))
                .Append(",\"s\":").Append(N(e.Size)).Append(",\"m\":").Append(N(e.Modified))
                .Append(",\"w\":").Append(N(e.W)).Append(",\"h\":").Append(N(e.H)).Append(",\"f\":").Append(N(e.Frames))
                .Append(",\"c\":").Append(N(e.Colours)).Append(",\"hash\":").Append(J(e.Hash)).Append(",\"dup\":").Append(J(e.DupOf))
                .Append(",\"err\":").Append(J(e.Error)).Append(",\"t\":").Append(J(e.Thumb))
                .Append(",\"r\":").Append(N(e.Stars)).Append(",\"l\":").Append(J(e.Label > 0 ? Marks.LabelNames[e.Label] : ""))
                .Append(",\"tg\":").Append(e.Tag ? "1" : "0").Append(",\"rf\":").Append(N(e.FileStars)).Append("}");
        }
        data.Append("]");

        string title = "RetroGleek folder audit - " + dir;
        var sb = new System.Text.StringBuilder();
        sb.Append("<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'>\n");
        sb.Append("<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'\">\n");
        sb.Append("<meta name='viewport' content='width=device-width, initial-scale=1'>\n");
        sb.Append("<title>").Append(Html(title)).Append("</title>\n<style>").Append(Css).Append("</style></head><body>\n");
        sb.Append("<header><h1>RetroGleek folder audit</h1><div class='meta'><b>").Append(Html(dir)).Append("</b><br>Made ")
          .Append(Html(when.ToString("yyyy-MM-dd HH:mm"))).Append(" by RetroGleek. Retro pictures decoded by RECOIL ").Append(Html(Recoil.RECOIL.Version))
          .Append(". This page works offline and loads nothing from the internet.")
          .Append(thumbs ? "" : " Thumbnails were left out to keep this file small.").Append("</div></header>\n");
        sb.Append("<section id='cards'></section>\n");
        sb.Append("<details id='sums' open><summary>Summary by platform and file type</summary><section class='two'>")
          .Append("<div><h2>By platform</h2><div class='box'><table class='sum' id='byp'></table></div></div>")
          .Append("<div><h2>By file type</h2><div class='box'><table class='sum' id='byt'></table></div></div></section></details>\n");
        sb.Append("<section id='bar'><input id='q' type='search' placeholder='Search name, type, platform, error ...' autofocus>")
          .Append("<select id='pf'><option value=''>All platforms</option></select>")
          .Append("<select id='tf'><option value=''>All file types</option></select>")
          .Append("<select id='kf'><option value=''>Standard and retro</option><option>Standard</option><option>Retro</option><option>Retro (generic extension)</option></select>")
          .Append("<select id='sf'><option value=''>Any status</option><option>OK</option><option value='Failed'>Could not be opened</option><option>Cloud-only</option><option value='Duplicate'>Duplicates</option></select>")
          .Append("<select id='mf'><option value=''>Any marks</option><option value='tag'>Tagged</option><option value='rated'>Rated</option>")
          .Append("<option value='r1'>&#9733; or more</option><option value='r2'>&#9733;&#9733; or more</option><option value='r3'>&#9733;&#9733;&#9733; or more</option>")
          .Append("<option value='r4'>&#9733;&#9733;&#9733;&#9733; or more</option><option value='r5'>&#9733;&#9733;&#9733;&#9733;&#9733;</option>")
          .Append("<option value='l:Red'>Red label</option><option value='l:Yellow'>Yellow label</option><option value='l:Green'>Green label</option>")
          .Append("<option value='l:Blue'>Blue label</option><option value='l:Purple'>Purple label</option><option value='none'>No marks</option></select>")
          .Append("<button id='reset' type='button'>Clear</button><button id='csv' type='button'>Download CSV</button><span id='count'></span></section>\n");
        sb.Append(thumbs ? "<table id='list'><thead>" : "<table id='list' class='nothumbs'><thead>");
        sb.Append("<tr><th></th><th data-k='n'>Name</th><th data-k='r'>Rating</th><th data-k='l'>Label</th><th data-k='tg'>Tag</th><th data-k='e'>Type</th><th data-k='p'>Platform</th>")
          .Append("<th data-k='st'>Status</th><th data-k='s'>Size</th><th data-k='px'>Dimensions</th><th data-k='f'>Frames</th>")
          .Append("<th data-k='c'>Colours</th><th data-k='m'>Modified</th><th data-k='hash'>SHA-256</th><th data-k='note'>Notes</th></tr></thead><tbody id='tb'></tbody></table>\n");
        sb.Append("<script>\nvar D=").Append(data.ToString()).Append(";\nvar SKIPPED=").Append(N(skipped)).Append(";\n").Append(Script).Append("</script>\n</body></html>\n");
        return sb.ToString();
    }

    const string Css = @"
:root{color-scheme:dark}
body{margin:0;background:#181818;color:#ddd;font:14px/1.4 'Segoe UI',system-ui,sans-serif}
header{padding:18px 24px 6px}
h1{margin:0 0 6px;font-size:22px;color:#fff}
h2{font-size:15px;margin:0 0 6px;color:#bbb}
.meta{color:#999;font-size:13px}.meta b{color:#ddd}
#cards{display:flex;flex-wrap:wrap;gap:10px;padding:10px 24px}
.card{background:#262626;border-radius:8px;padding:10px 16px;min-width:120px;cursor:pointer;border:1px solid #333}
.card:hover{border-color:#3c82e6}
.card .v{font-size:22px;color:#fff}.card .l{font-size:12px;color:#999}
.card.bad .v{color:#ff8c5a}
#sums{padding:0 24px 10px}
#sums>summary{cursor:pointer;color:#bbb;padding:4px 0;user-select:none}
#sums>summary:hover{color:#fff}
.two{display:flex;flex-wrap:wrap;gap:24px;padding:6px 0 0}
.two .box{max-height:210px;overflow-y:auto;background:#202020;border:1px solid #333;border-radius:6px;padding:4px 10px;min-width:260px}
table.sum{border-collapse:collapse;font-size:13px}
table.sum td{padding:3px 12px 3px 0;cursor:pointer}
table.sum tr:hover td{color:#fff}
table.sum td.n{text-align:right;color:#aaa}
#bar{position:sticky;top:0;z-index:2;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:10px 24px;background:#262626;border-top:1px solid #333;border-bottom:1px solid #333}
input,select,button{background:#343434;color:#eee;border:1px solid #444;border-radius:4px;padding:6px 8px;font:inherit}
#q{flex:1;min-width:220px}
button{cursor:pointer}button:hover{border-color:#3c82e6}
#count{color:#999;margin-left:auto}
#list{border-collapse:collapse;width:100%;font-size:13px}
#list th{position:sticky;top:51px;background:#202020;text-align:left;padding:8px 10px;cursor:pointer;white-space:nowrap;color:#bbb;border-bottom:1px solid #333;user-select:none}
#list th.asc:after{content:' \25B2'}#list th.desc:after{content:' \25BC'}
#list td{padding:6px 10px;border-bottom:1px solid #2a2a2a;vertical-align:middle}
#list tr:hover td{background:#222}
#list.nothumbs td.th,#list.nothumbs th:first-child{display:none}
td.th{width:100px;text-align:center}td.th img{max-width:96px;max-height:96px;image-rendering:pixelated;display:block;margin:auto}
td.num{text-align:right;white-space:nowrap}td.mono{font-family:Consolas,monospace;color:#999}
td.name{color:#fff;word-break:break-all}td.note{color:#aaa;max-width:340px}
tr.st-Failed td.status,tr.st-Failed td.note{color:#ff8c5a}
tr.st-Cloudonly td.status{color:#8cb4ff}
tr.st-OK td.status{color:#7fd17f}
td.stars{color:#ffcd46;white-space:nowrap}td.stars.file{color:#c8c8c8}td.tag{color:#3c82e6;text-align:center}
td.lab-Red{color:#e14646}td.lab-Yellow{color:#ebc83c}td.lab-Green{color:#55b95f}td.lab-Blue{color:#4687eb}td.lab-Purple{color:#a569d7}
";

    const string Script = @"
function $(id){return document.getElementById(id);}
function fmtSize(b){if(b<1024)return b+' B';if(b<1048576)return (b/1024).toFixed(1)+' KB';if(b<1073741824)return (b/1048576).toFixed(2)+' MB';return (b/1073741824).toFixed(2)+' GB';}
function two(x){return (x<10?'0':'')+x;}
function fmtDate(ms){var d=new Date(ms);return d.getFullYear()+'-'+two(d.getMonth()+1)+'-'+two(d.getDate())+' '+two(d.getHours())+':'+two(d.getMinutes());}
D.forEach(function(r){r.px=r.w*r.h;r.p=r.p||'';r.note=(r.dup?'Duplicate of '+r.dup+(r.err?'. ':''):'')+(r.err||'');r.r=r.r||0;r.l=r.l||'';r.tg=r.tg||0;r.src=r.r?'RetroGleek':'';if(!r.r&&r.rf){r.r=r.rf;r.src='file';}});
function stars(n){var s='';for(var i=0;i<n;i++)s+='\u2605';return s;}
var sortKey='n',sortDir=1;
function fill(id,key){var seen={},vals=[];D.forEach(function(r){var v=r[key];if(v&&!seen[v]){seen[v]=1;vals.push(v);}});
 vals.sort(function(a,b){return a.localeCompare(b,undefined,{sensitivity:'base'});});
 var s=$(id);vals.forEach(function(v){var o=document.createElement('option');o.value=v;o.textContent=v;s.appendChild(o);});}
fill('pf','p');fill('tf','e');
function marked(r,mf){if(!mf)return true;if(mf==='tag')return r.tg===1;if(mf==='rated')return r.r>0;if(mf==='none')return !r.r&&!r.l&&!r.tg;
 if(mf.charAt(0)==='r')return r.r>=parseInt(mf.substring(1),10);if(mf.indexOf('l:')===0)return r.l===mf.substring(2);return true;}
function matches(r){var q=$('q').value.toLowerCase().trim(),pf=$('pf').value,tf=$('tf').value,sf=$('sf').value,kf=$('kf').value;
 if(!marked(r,$('mf').value))return false;
 if(pf&&r.p!==pf)return false;if(tf&&r.e!==tf)return false;if(kf&&r.k!==kf)return false;
 if(sf==='Duplicate'){if(!r.dup)return false;}else if(sf&&r.st!==sf)return false;
 if(q){var hay=(r.n+' '+r.e+' '+r.p+' '+r.st+' '+(r.fmt||'')+' '+r.note+' '+r.l+(r.tg?' tagged':'')).toLowerCase(),parts=q.split(/\s+/);
  for(var i=0;i<parts.length;i++)if(hay.indexOf(parts[i])<0)return false;}
 return true;}
function cmp(a,b){var x=a[sortKey],y=b[sortKey];if(x===null||x===undefined)x='';if(y===null||y===undefined)y='';
 var c=(typeof x==='number'&&typeof y==='number')?x-y:String(x).localeCompare(String(y),undefined,{numeric:true,sensitivity:'base'});
 if(c===0&&sortKey!=='n')c=a.n.localeCompare(b.n,undefined,{numeric:true,sensitivity:'base'});
 return c*sortDir;}
function cell(tr,text,cls,title){var td=document.createElement('td');td.textContent=text;if(cls)td.className=cls;if(title)td.title=title;tr.appendChild(td);return td;}
function shown(){var rows=D.filter(matches);rows.sort(cmp);return rows;}
function render(){var rows=shown(),tb=$('tb'),frag=document.createDocumentFragment();tb.textContent='';
 rows.forEach(function(r){var tr=document.createElement('tr');tr.className='st-'+r.st.replace(/[^a-z]/gi,'');
  var td=document.createElement('td');td.className='th';
  if(r.t){var im=document.createElement('img');im.src='data:image/png;base64,'+r.t;im.alt='';td.appendChild(im);}
  tr.appendChild(td);
  cell(tr,r.n,'name');cell(tr,stars(r.r),r.src==='file'?'stars file':'stars',r.r?r.r+' of 5'+(r.src==='file'?' (stored in the file)':''):'');cell(tr,r.l,r.l?'lab-'+r.l:'');cell(tr,r.tg?'\u2714':'','tag');cell(tr,r.e);cell(tr,r.p);cell(tr,r.st==='Failed'?'Could not be opened':r.st,'status');
  cell(tr,fmtSize(r.s),'num',r.s+' bytes');cell(tr,r.w?r.w+' x '+r.h:'','num');cell(tr,r.w?String(r.f):'','num');
  cell(tr,r.c<0?'':(r.c>=65536?'65,536+':String(r.c)),'num');cell(tr,fmtDate(r.m),'num');
  cell(tr,r.hash?r.hash.substring(0,12):'','mono',r.hash||'');cell(tr,r.note,'note');
  frag.appendChild(tr);});
 tb.appendChild(frag);$('count').textContent='Showing '+rows.length+' of '+D.length;
 Array.prototype.forEach.call(document.querySelectorAll('th[data-k]'),function(th){
  th.className=th.getAttribute('data-k')===sortKey?(sortDir>0?'asc':'desc'):'';});}
Array.prototype.forEach.call(document.querySelectorAll('th[data-k]'),function(th){th.onclick=function(){
 var k=th.getAttribute('data-k');if(k===sortKey)sortDir=-sortDir;else{sortKey=k;sortDir=1;}render();};});
['q','pf','tf','kf','sf','mf'].forEach(function(id){$(id).oninput=render;$(id).onchange=render;});
function set(pf,tf,sf,mf){$('q').value='';$('pf').value=pf||'';$('tf').value=tf||'';$('sf').value=sf||'';$('kf').value='';$('mf').value=mf||'';render();}
$('reset').onclick=function(){set();};
function card(v,l,bad,f){var d=document.createElement('div');d.className='card'+(bad&&v>0?' bad':'');
 d.innerHTML='<div class=v></div><div class=l></div>';d.firstChild.textContent=v;d.lastChild.textContent=l;d.onclick=f;$('cards').appendChild(d);}
function count(f){var n=0;D.forEach(function(r){if(f(r))n++;});return n;}
card(D.length,'picture files',false,function(){set();});
card(count(function(r){return r.st==='OK';}),'opened',false,function(){set('','','OK');});
card(count(function(r){return r.st==='Failed';}),'could not be opened',true,function(){set('','','Failed');});
card(count(function(r){return r.st==='Cloud-only';}),'cloud-only (not opened)',false,function(){set('','','Cloud-only');});
card(count(function(r){return !!r.dup;}),'duplicates',false,function(){set('','','Duplicate');});
card(count(function(r){return r.k!=='Standard';}),'retro files',false,function(){set();$('kf').value='Retro';render();});
var nTag=count(function(r){return r.tg===1;}),nRated=count(function(r){return r.r>0;});
if(nTag>0)card(nTag,'tagged',false,function(){set('','','','tag');});
if(nRated>0)card(nRated,'rated',false,function(){set('','','','rated');});
if(SKIPPED>0)card(SKIPPED,'generic-extension files that are not pictures (not listed)',false,function(){});
var NOPLAT='(unknown: could not be opened)';
function summary(id,key,label){var groups={},order=[];D.forEach(function(r){var v=r[key]||(key==='p'?NOPLAT:'(none)');
  if(!groups[v]){groups[v]={all:0,bad:0};order.push(v);}groups[v].all++;if(r.st==='Failed')groups[v].bad++;});
 order.sort(function(a,b){return groups[b].all-groups[a].all||a.localeCompare(b);});
 var t=$(id);order.forEach(function(v){var tr=document.createElement('tr');
  cell(tr,v);cell(tr,String(groups[v].all),'n');cell(tr,groups[v].bad?groups[v].bad+' could not be opened':'','n');
  tr.onclick=function(){if(key==='p'){if(v===NOPLAT)set('','','Failed');else set(v);}else set('',v);};t.appendChild(tr);});}
summary('byp','p');summary('byt','e');
function csvq(v){v=String(v===null||v===undefined?'':v);return /[\x22,\r\n]/.test(v)?'\x22'+v.replace(/\x22/g,'\x22\x22')+'\x22':v;}
$('csv').onclick=function(){var lines=['Name,Type,Kind,Platform,Status,Size (bytes),Width,Height,Frames,Colours,Modified,SHA-256,Notes,Rating,Label,Tagged,Rating source'];
 shown().forEach(function(r){lines.push([r.n,r.e,r.k,r.p,r.st,r.s,r.w||'',r.h||'',r.w?r.f:'',r.c<0?'':r.c,fmtDate(r.m),r.hash||'',r.note,r.r||'',r.l,r.tg?'yes':'',r.src].map(csvq).join(','));});
 var blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv'}),a=document.createElement('a');
 a.href=URL.createObjectURL(blob);a.download='retrogleek-audit.csv';document.body.appendChild(a);a.click();a.remove();};
render();
";
}
