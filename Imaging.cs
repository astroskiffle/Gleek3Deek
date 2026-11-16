// RetroGleek - picture decoding: lossless PNG export, the RECOIL wrapper, the viewer's picture holder
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

// ====================================================================== lossless export (PNG)

// Saves pictures as PNG. PNG is lossless: every saved pixel equals the pixel RetroGleek decoded. The file is written
// under a temporary name, read back and compared pixel by pixel, and only then moved into place; on any mismatch
// nothing is kept. The smallest lossless pixel format is chosen: indexed (<= 256 colours, typical for retro
// pictures), 24-bit (opaque), or 32-bit (transparency).
static class Exporter
{
    const long MaxPixels = 100000000L;

    // Decodes any supported picture to a straight-alpha 32-bit bitmap, applying its EXIF rotation plus
    // extraTurns clockwise quarter turns (rotation the user added in the viewer).
    public static Bitmap Decode(string path, int extraTurns) { return Decode(path, extraTurns, false, false); }

    // flipX / flipY mirror the decoded picture (in its own, unrotated orientation) before it is rotated,
    // exactly as the viewer draws it. RotateFlip only moves pixels, so this stays lossless.
    public static Bitmap Decode(string path, int extraTurns, bool flipX, bool flipY)
    {
        if ((File.GetAttributes(path) & Util.CloudMask) != 0)
            throw new IOException("This file is a cloud placeholder that isn't stored on this PC.");
        Bitmap bmp;
        int turns = extraTurns;
        if (!Util.IsNative(path) && Retro.Claims(path))
        {
            long bytes; string platform;
            using (Bitmap src = Retro.Load(path, out bytes, out platform)) bmp = ToArgb(src);
        }
        else if (WinCodec.Claims(path))
        {
            CodecPic c;
            try { c = WinCodec.Load(path, 0, false); }                       // exact (straight-alpha) pixels
            catch (Exception cex) { throw new IOException(WinCodec.Why(path, cex)); }
            bmp = c.Bmp;
            turns += c.Rot;
        }
        else
        {
            byte[] data = Util.ReadShared(path);
            using (var ms = new MemoryStream(data, false))
            using (Image img = Image.FromStream(ms, false, false))
            {
                turns += Util.ReadRotation(img);
                bmp = ToArgb(img);
            }
        }
        if (flipX || flipY)
            bmp.RotateFlip(flipX && flipY ? RotateFlipType.RotateNoneFlipXY : flipX ? RotateFlipType.RotateNoneFlipX : RotateFlipType.RotateNoneFlipY);
        turns &= 3;
        if (turns != 0)
            bmp.RotateFlip(turns == 1 ? RotateFlipType.Rotate90FlipNone : turns == 2 ? RotateFlipType.Rotate180FlipNone : RotateFlipType.Rotate270FlipNone);
        return bmp;
    }

    // Exact 1:1 copy into a straight-alpha 32-bit bitmap. Reads the raw pixel data (no drawing, so no
    // blending or colour rounding can creep in, even for semi-transparent pixels).
    static Bitmap ToArgb(Image img)
    {
        Bitmap src = img as Bitmap;
        if (src == null) throw new InvalidDataException("This picture type can't be exported.");
        int w = src.Width, h = src.Height;
        if ((long)w * h > MaxPixels) throw new IOException("This picture is too large to export.");
        int[] px = Pixels(src);
        var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        BitmapData bd = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
        try
        {
            for (int y = 0; y < h; y++)
                Marshal.Copy(px, y * w, new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), w);
        }
        finally { bmp.UnlockBits(bd); }
        return bmp;
    }

    static int[] Pixels(Bitmap b)
    {
        int w = b.Width, h = b.Height;
        int[] px = new int[w * h];
        BitmapData bd = b.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            for (int y = 0; y < h; y++)
                Marshal.Copy(new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), px, y * w, w);
        }
        finally { b.UnlockBits(bd); }
        return px;
    }

    // Every frame of an animated GIF or WebP / every page of a multi-page TIFF, each as its own verified lossless PNG
    // in destDir (stem_frame001.png ...; existing files are never overwritten). Frames are saved as they are shown:
    // GDI+ hands over each GIF frame already combined with the frames before it, and WebpAnim puts WebP frames
    // together the same way. Rotation and mirroring are applied as in Decode. Runs on a worker thread. Returns the
    // number of frames saved, or 0 if the picture has only one.
    public static int ExportFrames(string path, int extraTurns, bool flipX, bool flipY, string destDir,
                                   Action<int, int> progress, out string firstFile)
    {
        firstFile = null;
        if ((File.GetAttributes(path) & Util.CloudMask) != 0)
            throw new IOException("This file is a cloud placeholder that isn't stored on this PC.");
        if (WebpAnim.IsWebp(path))
        {
            List<Bitmap> frames;
            int[] delays;
            long size;
            if (!WebpAnim.TryLoad(path, out frames, out delays, out size)) return 0;   // a still WebP (or too big to animate)
            try
            {
                int webpTurns = extraTurns & 3;
                string webpStem = Path.GetFileNameWithoutExtension(path) + "_frame";
                int webpDigits = Math.Max(3, frames.Count.ToString().Length);
                for (int i = 0; i < frames.Count; i++)
                {
                    if (progress != null) progress(i + 1, frames.Count);
                    Bitmap fb = frames[i];
                    if (flipX || flipY)
                        fb.RotateFlip(flipX && flipY ? RotateFlipType.RotateNoneFlipXY : flipX ? RotateFlipType.RotateNoneFlipX : RotateFlipType.RotateNoneFlipY);
                    if (webpTurns != 0)
                        fb.RotateFlip(webpTurns == 1 ? RotateFlipType.Rotate90FlipNone : webpTurns == 2 ? RotateFlipType.Rotate180FlipNone : RotateFlipType.Rotate270FlipNone);
                    string fdest = Util.UniquePath(destDir, webpStem + (i + 1).ToString().PadLeft(webpDigits, '0'), ".png");
                    SavePng(fb, fdest, false);
                    if (firstFile == null) firstFile = fdest;
                }
                return frames.Count;
            }
            finally { foreach (Bitmap fb in frames) fb.Dispose(); }
        }
        if (!Util.IsNative(path)) return 0;                // retro pictures: flicker frames are blended into one picture
        byte[] data = Util.ReadShared(path);
        using (var ms = new MemoryStream(data, false))
        using (Image img = Image.FromStream(ms, false, false))
        {
            FrameDimension dim = null;
            foreach (Guid g in img.FrameDimensionsList)
            {
                if (g == FrameDimension.Time.Guid) { dim = FrameDimension.Time; break; }
                if (g == FrameDimension.Page.Guid) dim = FrameDimension.Page;
            }
            int count = dim == null ? 1 : img.GetFrameCount(dim);
            if (count < 2) return 0;
            int turns = (extraTurns + Util.ReadRotation(img)) & 3;
            string stem = Path.GetFileNameWithoutExtension(path) + (dim.Guid == FrameDimension.Page.Guid ? "_page" : "_frame");
            int digits = Math.Max(3, count.ToString().Length);
            for (int i = 0; i < count; i++)
            {
                if (progress != null) progress(i + 1, count);
                img.SelectActiveFrame(dim, i);
                using (Bitmap bmp = ToArgb(img))
                {
                    if (flipX || flipY)
                        bmp.RotateFlip(flipX && flipY ? RotateFlipType.RotateNoneFlipXY : flipX ? RotateFlipType.RotateNoneFlipX : RotateFlipType.RotateNoneFlipY);
                    if (turns != 0)
                        bmp.RotateFlip(turns == 1 ? RotateFlipType.Rotate90FlipNone : turns == 2 ? RotateFlipType.Rotate180FlipNone : RotateFlipType.Rotate270FlipNone);
                    string dest = Util.UniquePath(destDir, stem + (i + 1).ToString().PadLeft(digits, '0'), ".png");
                    SavePng(bmp, dest, false);
                    if (firstFile == null) firstFile = dest;
                }
            }
            return count;
        }
    }

    // Writes bmp (32-bit ARGB, as returned by Decode) to destPath as a verified, lossless PNG.
    public static void SavePng(Bitmap bmp, string destPath, bool overwrite)
    {
        int w = bmp.Width, h = bmp.Height;
        int[] px = Pixels(bmp);
        string tmp = destPath + "." + Guid.NewGuid().ToString("N").Substring(0, 8) + ".tmp";
        try
        {
            using (Bitmap enc = Encodable(px, w, h, bmp)) enc.Save(tmp, ImageFormat.Png);
            VerifyPng(tmp, px, w, h);
            if (File.Exists(destPath))
            {
                if (!overwrite) throw new IOException("A file with that name already exists.");
                File.Delete(destPath);
            }
            File.Move(tmp, destPath);
        }
        catch (Exception)
        {
            try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { }
            throw;
        }
    }

    static Bitmap Encodable(int[] px, int w, int h, Bitmap argb)
    {
        var map = new Dictionary<int, byte>();
        bool opaque = true, fits = true;
        for (int i = 0; i < px.Length; i++)
        {
            int c = px[i];
            if ((int)((uint)c >> 24) != 255) opaque = false;
            if (fits && !map.ContainsKey(c))
            {
                if (map.Count == 256) fits = false; else map[c] = (byte)map.Count;
            }
            if (!fits && !opaque) break;
        }
        if (opaque && fits) return Indexed(px, w, h, map);
        if (opaque)
        {
            var rgb = new Bitmap(w, h, PixelFormat.Format24bppRgb);
            BitmapData bd = rgb.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format24bppRgb);
            try
            {
                byte[] row = new byte[Math.Abs(bd.Stride)];
                for (int y = 0; y < h; y++)
                {
                    for (int x = 0; x < w; x++)
                    {
                        int c = px[y * w + x];
                        row[x * 3] = (byte)c; row[x * 3 + 1] = (byte)(c >> 8); row[x * 3 + 2] = (byte)(c >> 16);   // B, G, R
                    }
                    Marshal.Copy(row, 0, new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), row.Length);
                }
            }
            finally { rgb.UnlockBits(bd); }
            return rgb;
        }
        return (Bitmap)argb.Clone();                      // real transparency: keep the full 32 bits
    }

    static Bitmap Indexed(int[] px, int w, int h, Dictionary<int, byte> map)
    {
        var bmp = new Bitmap(w, h, PixelFormat.Format8bppIndexed);
        ColorPalette pal = bmp.Palette;
        for (int i = 0; i < pal.Entries.Length; i++) pal.Entries[i] = Color.Black;
        foreach (KeyValuePair<int, byte> kv in map) pal.Entries[kv.Value] = Color.FromArgb(kv.Key);
        bmp.Palette = pal;
        BitmapData bd = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format8bppIndexed);
        try
        {
            byte[] row = new byte[Math.Abs(bd.Stride)];
            for (int y = 0; y < h; y++)
            {
                for (int x = 0; x < w; x++) row[x] = map[px[y * w + x]];
                Marshal.Copy(row, 0, new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), row.Length);
            }
        }
        finally { bmp.UnlockBits(bd); }
        return bmp;
    }

    // Reads the PNG back and compares every pixel with the original. (The hidden colour of a fully
    // transparent pixel is not visible, so it is not compared.)
    static void VerifyPng(string path, int[] expected, int w, int h)
    {
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (Image img = Image.FromStream(fs, false, true))
        using (Bitmap back = ToArgb(img))
        {
            if (back.Width != w || back.Height != h) throw new InvalidDataException("The saved PNG has the wrong size. Nothing was kept.");
            int[] got = Pixels(back);
            for (int i = 0; i < got.Length; i++)
            {
                if (got[i] == expected[i]) continue;
                if ((got[i] >> 24) == 0 && (expected[i] >> 24) == 0) continue;
                throw new InvalidDataException("The saved PNG does not match the original pixels. Nothing was kept.");
            }
        }
    }
}

// ====================================================================== retro-computer pictures (RECOIL)

// Thin, defensive wrapper around RECOIL (managed C#, bounds-checked, no native code, no network).
// Whatever a malformed file does inside the decoder, the worst outcome here is a clean error message.
static class Retro
{
    public static volatile bool Enabled = true;          // shown in folder listings by default (F8 or --no-retro turns it off)
    const long MaxFileBytes = 32L * 1024 * 1024;         // RECOIL also caps pictures at 16 million pixels

    // Extensions that are also used by unrelated files (fonts, man pages) are never listed automatically.
    static readonly HashSet<string> Deny = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".fnt", ".3" };
    // RECOIL marks many extensions "too generic" (.cs .obj .map .raw .img ...); .scr (ZX Spectrum) is the exception.
    static readonly HashSet<string> KeepListed = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".scr" };

    // RECOIL decodes this extension (explicitly opened files, thumbnails): every <ext> in its formats.xml
    public static bool Claims(string path) { return RetroFormats.Extensions.Contains(Path.GetExtension(path)); }

    // Appears in folder listings (only when retro formats are switched on): real, specific extensions only.
    public static bool Listable(string ext) { return Enabled && Specific(ext); }

    // a real, specific retro extension (whether or not retro formats are switched on): not too generic, not made up
    public static bool Specific(string ext)
    {
        return RetroFormats.Extensions.Contains(ext)
            && !Deny.Contains(ext) && !RetroFormats.Arbitrary.Contains(ext)
            && (!RetroFormats.Generic.Contains(ext) || KeepListed.Contains(ext));
    }

    // Some formats keep their palette or colour map in a companion file. Those may only come from the
    // picture's own folder, never from anywhere else, and never from a cloud placeholder.
    sealed class Reader : Recoil.RECOIL
    {
        readonly string dir;
        public Reader(string imagePath) { dir = Path.GetDirectoryName(Path.GetFullPath(imagePath)); }

        protected override int ReadFile(string filename, byte[] content, int contentLength)
        {
            try
            {
                string full = Path.GetFullPath(filename);
                if (!Util.SameDir(Path.GetDirectoryName(full), dir) || !File.Exists(full)) return -1;
                if ((File.GetAttributes(full) & Util.CloudMask) != 0) return -1;
                using (var fs = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                {
                    int total = 0;
                    while (total < contentLength)
                    {
                        int n = fs.Read(content, total, contentLength - total);
                        if (n <= 0) break;
                        total += n;
                    }
                    return total;
                }
            }
            catch (Exception) { return -1; }
        }
    }

    // Decodes a retro picture into a 32-bit bitmap. Throws an exception with a readable message on any problem.
    public static Bitmap Load(string path, out long fileBytes, out string platform)
    {
        int frames;
        return Load(path, out fileBytes, out platform, out frames);
    }

    public static Bitmap Load(string path, out long fileBytes, out string platform, out int frameCount)
    {
        RetroGeom geom;
        return Load(path, out fileBytes, out platform, out frameCount, out geom);
    }

    // frameCount: how many sub-pictures the original hardware flickered between (they are blended into one).
    // geom: RECOIL's original resolution (before its whole-number pixel doubling) and the density of the pixels it
    // returns (from the machine's PAL / NTSC video timing; 0 = unknown), for True TV aspect and scanlines.
    public static Bitmap Load(string path, out long fileBytes, out string platform, out int frameCount, out RetroGeom geom)
    {
        geom = new RetroGeom();
        frameCount = 1;
        byte[] bytes;
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16))
        {
            if (fs.Length > MaxFileBytes) throw new IOException("This file is too large for the retro-format decoder (limit 32 MB).");
            bytes = new byte[(int)fs.Length];
            int off = 0;
            while (off < bytes.Length)
            {
                int n = fs.Read(bytes, off, bytes.Length - off);
                if (n <= 0) break;
                off += n;
            }
        }
        fileBytes = bytes.Length;

        var r = new Reader(path);
        bool ok;
        try { ok = r.Decode(path, bytes, bytes.Length); }
        catch (Exception) { ok = false; }                // malformed input must never take the viewer down
        if (!ok) throw new InvalidDataException("RECOIL couldn't decode this picture (damaged, truncated or an unsupported variant).");

        int w = r.GetWidth(), h = r.GetHeight(), frames = Math.Max(1, r.GetFrames());
        int[] px = r.GetPixels();
        long n2 = (long)w * h;
        if (w <= 0 || h <= 0 || px == null || n2 * frames > px.Length) throw new InvalidDataException("RECOIL returned an invalid picture.");
        platform = r.GetPlatform();
        frameCount = frames;
        try
        {
            geom.OrigW = r.GetOriginalWidth(); geom.OrigH = r.GetOriginalHeight();
            geom.XPpm = r.GetXPixelsPerMeter(); geom.YPpm = r.GetYPixelsPerMeter();
        }
        catch (Exception) { }

        // Some pictures flicker between 2-3 sub-pictures on the original hardware; the eye blends them, so do we.
        int count = (int)n2;
        int[] argb = new int[count];
        int opaque = unchecked((int)0xFF000000);
        if (frames == 1)
        {
            for (int i = 0; i < count; i++) argb[i] = px[i] | opaque;
        }
        else
        {
            for (int i = 0; i < count; i++)
            {
                int rr = 0, gg = 0, bb = 0;
                for (int f = 0; f < frames; f++)
                {
                    int c = px[f * count + i];
                    rr += (c >> 16) & 255; gg += (c >> 8) & 255; bb += c & 255;
                }
                argb[i] = opaque | (rr / frames) << 16 | (gg / frames) << 8 | (bb / frames);
            }
        }

        var bmp = new Bitmap(w, h, PixelFormat.Format32bppPArgb);
        BitmapData bd = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppPArgb);
        try
        {
            for (int y = 0; y < h; y++)
                Marshal.Copy(argb, y * w, new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), w);
        }
        finally { bmp.UnlockBits(bd); }
        return bmp;
    }
}

// ====================================================================== viewer data

sealed class Pic : IDisposable
{
    public string FullPath;
    public Image Img;
    public MemoryStream Ms;      // only kept for lazily-decoded (huge / animated) images
    public int W, H, Rot;        // Rot = quarter turns needed to honour EXIF orientation
    public long Bytes;
    public bool Anim;
    public List<Bitmap> Frames;  // animated WebP: every frame, put together (Img is the one shown); null otherwise
    public int[] Delays;         // animated WebP: each frame's time on screen, in milliseconds
    public string Err;
    public string Note;          // e.g. the retro platform name
    public RetroGeom Geom;       // retro pictures only: original resolution and pixel density
    public List<string> Exif;    // readable EXIF lines (camera, exposure ...), or null
    public int FileStars;        // star rating stored in the file (Windows, Lightroom ...), 0 = none
    public long Stamp;           // the file's size and modified time when it was read (Canvas.FileStamp): a kept copy is
                                 // shown again only while the file is unchanged

    public void Dispose()
    {
        if (Frames != null) { foreach (Bitmap b in Frames) b.Dispose(); Frames = null; }   // Img is one of them
        else if (Img != null) Img.Dispose();
        if (Ms != null) Ms.Dispose();
        Img = null; Ms = null;
    }
}

// ====================================================================== EXIF details (viewer panel, E)

// Turns a photo's EXIF tags into short readable lines. Reads only what GDI+ already parsed from the file; never
// throws (a damaged tag is skipped). GPS coordinates are shown only here, on screen; nothing is written or sent.
static class ExifInfo
{
    public static List<string> Read(Image img)
    {
        var r = new List<string>();
        try
        {
            int[] ids = img.PropertyIdList;
            if (ids == null || ids.Length == 0) return null;
            var have = new HashSet<int>(ids);

            string make = Text(img, have, 0x010F), model = Text(img, have, 0x0110);
            string cam = model;
            if (make != null && (model == null || !model.StartsWith(make, StringComparison.OrdinalIgnoreCase)))
                cam = model == null ? make : make + " " + model;
            Add(r, "Camera", cam);
            Add(r, "Lens", Text(img, have, 0xA434));
            string date = Text(img, have, 0x9003);
            if (date == null) date = Text(img, have, 0x0132);
            if (date != null && date.Length >= 10 && date[4] == ':' && date[7] == ':')
                date = date.Substring(0, 4) + "-" + date.Substring(5, 2) + "-" + date.Substring(8);
            Add(r, "Taken", date);

            double v;
            if (URational(img, have, 0x829A, 0, out v) && v > 0)
                Add(r, "Exposure", v < 1 ? "1/" + Math.Round(1 / v) + " s" : v.ToString("0.#") + " s");
            if (URational(img, have, 0x829D, 0, out v) && v > 0) Add(r, "Aperture", "f/" + v.ToString("0.0"));
            int n;
            if (UShort(img, have, 0x8827, out n) && n > 0) Add(r, "ISO", n.ToString());
            if (URational(img, have, 0x920A, 0, out v) && v > 0)
            {
                string fl = v.ToString("0.#") + " mm";
                if (UShort(img, have, 0xA405, out n) && n > 0) fl += "  (" + n + " mm in 35 mm terms)";
                Add(r, "Focal length", fl);
            }
            if (SRational(img, have, 0x9204, out v) && Math.Abs(v) > 1e-9) Add(r, "Exposure bias", (v > 0 ? "+" : "") + v.ToString("0.##") + " EV");
            if (UShort(img, have, 0x9209, out n)) Add(r, "Flash", (n & 1) != 0 ? "fired" : "did not fire");
            if (UShort(img, have, 0x0112, out n) && n >= 2 && n <= 8)
            {
                string[] o = { "", "", "mirrored", "rotated 180 degrees", "rotated 180 degrees, mirrored", "rotated 90 degrees, mirrored",
                               "rotated 90 degrees", "rotated 270 degrees, mirrored", "rotated 270 degrees" };
                Add(r, "Orientation", o[n]);
            }
            Add(r, "Software", Text(img, have, 0x0131));
            Add(r, "Artist", Text(img, have, 0x013B));
            Add(r, "Copyright", Text(img, have, 0x8298));
            Add(r, "Description", Text(img, have, 0x010E));

            double lat, lon;
            if (Gps(img, have, 0x0002, 0x0001, out lat) && Gps(img, have, 0x0004, 0x0003, out lon))
                Add(r, "GPS", Math.Abs(lat).ToString("0.00000") + (lat < 0 ? " S" : " N") + ", " + Math.Abs(lon).ToString("0.00000") + (lon < 0 ? " W" : " E"));
        }
        catch (Exception) { }
        return r.Count > 0 ? r : null;
    }

    static void Add(List<string> r, string label, string value)
    {
        if (string.IsNullOrEmpty(value)) return;
        if (value.Length > 80) value = value.Substring(0, 77) + "...";
        r.Add(label + ":  " + value);
    }

    static byte[] Raw(Image img, HashSet<int> have, int id)
    {
        if (!have.Contains(id)) return null;
        try { PropertyItem p = img.GetPropertyItem(id); return p == null ? null : p.Value; }
        catch (Exception) { return null; }
    }

    static string Text(Image img, HashSet<int> have, int id)
    {
        byte[] b = Raw(img, have, id);
        if (b == null || b.Length == 0) return null;
        string s;
        try { s = System.Text.Encoding.UTF8.GetString(b); } catch (Exception) { return null; }
        var sb = new System.Text.StringBuilder(s.Length);
        foreach (char c in s) if (c >= ' ' && c != '\uFFFD') sb.Append(c);      // no control characters
        s = sb.ToString().Trim();
        return s.Length > 0 ? s : null;
    }

    static bool UShort(Image img, HashSet<int> have, int id, out int v)
    {
        v = 0;
        byte[] b = Raw(img, have, id);
        if (b == null || b.Length < 2) return false;
        v = BitConverter.ToUInt16(b, 0);
        return true;
    }

    // unsigned rational number 'index' of a tag (GDI+ hands the values over in the PC's own byte order)
    static bool URational(Image img, HashSet<int> have, int id, int index, out double v)
    {
        v = 0;
        byte[] b = Raw(img, have, id);
        int at = index * 8;
        if (b == null || b.Length < at + 8) return false;
        uint num = BitConverter.ToUInt32(b, at), den = BitConverter.ToUInt32(b, at + 4);
        if (den == 0) return false;
        v = (double)num / den;
        return true;
    }

    static bool SRational(Image img, HashSet<int> have, int id, out double v)
    {
        v = 0;
        byte[] b = Raw(img, have, id);
        if (b == null || b.Length < 8) return false;
        int num = BitConverter.ToInt32(b, 0), den = BitConverter.ToInt32(b, 4);
        if (den == 0) return false;
        v = (double)num / den;
        return true;
    }

    // degrees / minutes / seconds -> signed decimal degrees (south and west are negative)
    static bool Gps(Image img, HashSet<int> have, int valueId, int refId, out double deg)
    {
        deg = 0;
        double d, m, s;
        if (!URational(img, have, valueId, 0, out d) || !URational(img, have, valueId, 1, out m) || !URational(img, have, valueId, 2, out s)) return false;
        deg = d + m / 60 + s / 3600;
        if (deg == 0 || deg > 180) return false;
        string rf = Text(img, have, refId);
        if (rf != null && (rf.StartsWith("S") || rf.StartsWith("W"))) deg = -deg;
        return true;
    }
}

// What RECOIL says about a retro picture's screen: its original resolution (RECOIL doubles pixels by whole numbers so
// that pictures look roughly right) and the density of the pixels it returns, horizontally and vertically, per metre
// of the original TV screen. YPpm / XPpm is the width of one pixel relative to its height.
sealed class RetroGeom
{
    public int OrigW, OrigH, XPpm, YPpm;
    public double PixelAspect { get { return XPpm > 0 && YPpm > 0 ? (double)YPpm / XPpm : 1.0; } }
}
