// RetroGleek - lossless changes to photo files: turning a JPEG (Ctrl+Shift+R / Ctrl+Shift+L) and writing star ratings
// into JPEG and PNG files (Edit > Rating > Write my ratings into the files)
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE). Part of RetroGleek; see Program.cs for the overview.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Text;
using System.Xml;

// Turns JPEG photos on disk without re-compressing them, so no quality is lost. Two ways, tried in this order:
//   1. The photo has an EXIF orientation tag: only that tag's value changes (2 bytes in the file); every viewer that
//      honours EXIF (Windows, browsers, RetroGleek) shows it turned. The picture data is not touched at all.
//   2. No orientation tag: GDI+'s lossless JPEG transform turns the compressed blocks themselves. That is only
//      lossless when the width and height are whole multiples of the JPEG block size (8 or 16 pixels); otherwise the
//      photo is left alone. The result is decoded and compared with the original turned in memory before it is kept.
// Either way the new file is written next to the original under a temporary name, checked, and only then put in
// its place (File.Replace). Anything that is not a JPEG, or can't be turned without loss, is skipped with a reason.
static class JpegRotate
{
    public static bool IsJpeg(string path)
    {
        string e = (Path.GetExtension(path) ?? "").ToLowerInvariant();
        return e == ".jpg" || e == ".jpeg" || e == ".jpe" || e == ".jfif";
    }

    // turns = clockwise quarter turns (1, 2 or 3). Throws with a readable reason when the file can't be turned losslessly.
    public static void Rotate(string path, int turns)
    {
        turns &= 3;
        if (turns == 0) return;
        if (!IsJpeg(path)) throw new IOException("only JPEG photos can be turned without loss.");
        if ((File.GetAttributes(path) & Util.CloudMask) != 0) throw new IOException("cloud-only, not stored on this PC.");
        if ((File.GetAttributes(path) & FileAttributes.ReadOnly) != 0) throw new IOException("the file is read-only.");
        byte[] data = File.ReadAllBytes(path);
        string tmp = Path.Combine(Path.GetDirectoryName(path), "~rg" + Guid.NewGuid().ToString("N").Substring(0, 12) + ".tmp");
        try
        {
            int at, littleEndian;
            int orient = FindOrientation(data, out at, out littleEndian);
            if (orient >= 1 && orient <= 8)
            {
                int now = Compose(orient, turns);
                byte[] copy = (byte[])data.Clone();
                if (littleEndian == 1) { copy[at] = (byte)now; copy[at + 1] = 0; } else { copy[at] = 0; copy[at + 1] = (byte)now; }
                File.WriteAllBytes(tmp, copy);
                CheckOrientation(tmp, now);
            }
            else
            {
                int w, h, mw, mh;
                if (!Frame(data, out w, out h, out mw, out mh)) throw new IOException("its JPEG structure could not be read.");
                if (w % mw != 0 || h % mh != 0)
                    throw new IOException(w + " x " + h + " is not a whole number of " + mw + " x " + mh + " JPEG blocks and it has no orientation tag, so it can't be turned without loss.");
                Transform(data, tmp, turns);
                CheckPixels(data, tmp, turns);
            }
            File.Replace(tmp, path, null, true);           // keeps the original's creation date and attributes
        }
        finally { try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { } }
    }

    // EXIF orientation after turning the shown picture by more clockwise quarter turns
    // (1, 6, 3, 8 = 0, 90, 180, 270 degrees; 2, 7, 4, 5 = mirrored, then 0, 90, 180, 270 degrees)
    static int Compose(int orient, int turns)
    {
        int[] plain = { 1, 6, 3, 8 }, mirrored = { 2, 7, 4, 5 };
        int r = Array.IndexOf(plain, orient);
        if (r >= 0) return plain[(r + turns) & 3];
        r = Array.IndexOf(mirrored, orient);
        return mirrored[((r < 0 ? 0 : r) + turns) & 3];
    }

    // the value of the EXIF orientation tag (0 = none) and where its 2 bytes are
    static int FindOrientation(byte[] d, out int at, out int little)
    {
        at = -1; little = 1;
        if (d.Length < 4 || d[0] != 0xFF || d[1] != 0xD8) return 0;
        int p = 2;
        while (p + 4 <= d.Length && d[p] == 0xFF)
        {
            int marker = d[p + 1];
            if (marker == 0xD9 || marker == 0xDA) break;                     // end of image / start of the picture data
            int len = (d[p + 2] << 8) | d[p + 3];
            if (len < 2 || p + 2 + len > d.Length) break;
            if (marker == 0xE1 && len >= 16 && d[p + 4] == 'E' && d[p + 5] == 'x' && d[p + 6] == 'i' && d[p + 7] == 'f' && d[p + 8] == 0 && d[p + 9] == 0)
            {
                int t = p + 10;                                             // TIFF header
                int end = p + 2 + len;
                bool le = d[t] == 'I' && d[t + 1] == 'I';
                if (!le && !(d[t] == 'M' && d[t + 1] == 'M')) return 0;
                little = le ? 1 : 0;
                int ifd = t + (int)U32(d, t + 4, le);
                if (ifd < t || ifd + 2 > end) return 0;
                int n = U16(d, ifd, le);
                for (int i = 0; i < n; i++)
                {
                    int e = ifd + 2 + i * 12;
                    if (e + 12 > end) return 0;
                    if (U16(d, e, le) == 0x0112 && U16(d, e + 2, le) == 3)  // orientation, SHORT
                    {
                        at = e + 8;
                        return U16(d, at, le);
                    }
                }
                return 0;
            }
            p += 2 + len;
        }
        return 0;
    }

    static int U16(byte[] d, int i, bool le) { return le ? d[i] | (d[i + 1] << 8) : (d[i] << 8) | d[i + 1]; }
    static uint U32(byte[] d, int i, bool le)
    {
        return le ? (uint)(d[i] | (d[i + 1] << 8) | (d[i + 2] << 16) | (d[i + 3] << 24)) : (uint)((d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]);
    }

    // width, height and the JPEG block (MCU) size from the frame header
    static bool Frame(byte[] d, out int w, out int h, out int mw, out int mh)
    {
        w = h = 0; mw = mh = 8;
        int p = 2;
        while (p + 4 <= d.Length && d[p] == 0xFF)
        {
            int marker = d[p + 1];
            if (marker == 0xD9 || marker == 0xDA) break;
            int len = (d[p + 2] << 8) | d[p + 3];
            if (len < 2 || p + 2 + len > d.Length) break;
            bool sof = marker >= 0xC0 && marker <= 0xCF && marker != 0xC4 && marker != 0xC8 && marker != 0xCC;
            if (sof && len >= 8)
            {
                h = (d[p + 5] << 8) | d[p + 6];
                w = (d[p + 7] << 8) | d[p + 8];
                int comps = d[p + 9], maxH = 1, maxV = 1;
                for (int c = 0; c < comps && p + 10 + c * 3 + 1 < d.Length; c++)
                {
                    int s = d[p + 10 + c * 3 + 1];
                    maxH = Math.Max(maxH, s >> 4); maxV = Math.Max(maxV, s & 15);
                }
                mw = 8 * maxH; mh = 8 * maxV;
                return w > 0 && h > 0;
            }
            p += 2 + len;
        }
        return false;
    }

    static void Transform(byte[] data, string dest, int turns)
    {
        ImageCodecInfo jpeg = null;
        foreach (ImageCodecInfo c in ImageCodecInfo.GetImageEncoders()) if (c.FormatID == ImageFormat.Jpeg.Guid) jpeg = c;
        if (jpeg == null) throw new IOException("Windows' JPEG encoder is not available.");
        EncoderValue v = turns == 1 ? EncoderValue.TransformRotate90 : turns == 2 ? EncoderValue.TransformRotate180 : EncoderValue.TransformRotate270;
        using (var ms = new MemoryStream(data, false))
        using (Image img = Image.FromStream(ms, false, false))
        using (var ps = new EncoderParameters(1))
        {
            ps.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Transformation, (long)v);
            img.Save(dest, jpeg, ps);
        }
    }

    static void CheckOrientation(string path, int expected)
    {
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (Image img = Image.FromStream(fs, false, true))                // validates the data
        {
            byte[] v = img.GetPropertyItem(0x0112).Value;
            int o = (v.Length > 1 && v[0] == 0) ? v[1] : v[0];
            if (o != expected) throw new IOException("the new orientation could not be confirmed, so nothing was changed.");
        }
    }

    // The transformed photo must be the original turned: decoded side by side, they may differ only by the tiny
    // rounding of the JPEG decoder, never by re-compression
    static void CheckPixels(byte[] original, string path, int turns)
    {
        using (var ms = new MemoryStream(original, false))
        using (Image a = Image.FromStream(ms, false, true))
        using (var ba = new Bitmap(a))
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (Image b = Image.FromStream(fs, false, true))
        using (var bb = new Bitmap(b))
        {
            ba.RotateFlip(turns == 1 ? RotateFlipType.Rotate90FlipNone : turns == 2 ? RotateFlipType.Rotate180FlipNone : RotateFlipType.Rotate270FlipNone);
            if (ba.Width != bb.Width || ba.Height != bb.Height) throw new IOException("the turned photo has the wrong size, so nothing was changed.");
            int[] pa = Pixels(ba), pb = Pixels(bb);
            long sum = 0; int worst = 0;
            for (int i = 0; i < pa.Length; i++)
                for (int sh = 0; sh <= 16; sh += 8)
                {
                    int diff = Math.Abs(((pa[i] >> sh) & 255) - ((pb[i] >> sh) & 255));
                    sum += diff; if (diff > worst) worst = diff;
                }
            double mean = (double)sum / Math.Max(1, pa.Length * 3);
            if (mean > 0.5 || worst > 24) throw new IOException("the turned photo did not match the original closely enough (it would have lost quality), so nothing was changed.");
        }
    }

    static int[] Pixels(Bitmap b)
    {
        int[] px = new int[b.Width * b.Height];
        BitmapData bd = b.LockBits(new Rectangle(0, 0, b.Width, b.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            for (int y = 0; y < b.Height; y++)
                System.Runtime.InteropServices.Marshal.Copy(new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), px, y * b.Width, b.Width);
        }
        finally { b.UnlockBits(bd); }
        return px;
    }
}

// Which files RetroGleek can write a star rating into, and the one entry point for doing it (Edit > Rating >
// Write my ratings into the files): JPEG (JpegRating) and PNG (PngRating). Every other format is never changed.
static class RatingWriter
{
    public static bool CanWrite(string path) { return JpegRotate.IsJpeg(path) || PngRating.IsPng(path); }

    // stars 0..5. Throws with a readable reason when the file is left as it was.
    public static void Write(string path, int stars)
    {
        if (JpegRotate.IsJpeg(path)) JpegRating.Write(path, stars);
        else if (PngRating.IsPng(path)) PngRating.Write(path, stars);
        else throw new IOException("only JPEG and PNG files can hold a rating written by RetroGleek.");
    }
}

// Writes a star rating into a JPEG photo, so Windows Explorer, Lightroom and other programs see it too. Only the
// metadata changes; the compressed picture data is copied byte for byte, so nothing is re-compressed:
//   - XMP: xmp:Rating is set in the photo's XMP block (made if there is none); a MicrosoftPhoto:Rating already there
//     is updated too. Every other XMP property is kept.
//   - EXIF: if the photo already has the Windows Rating / RatingPercent tags, their values are changed in place.
// The new file is written under a temporary name and checked (same picture data, the rating reads back, the photo
// still decodes) before it replaces the original. A photo whose XMP block can't be read safely is left alone.
static class JpegRating
{
    const string XmpHeader = "http://ns.adobe.com/xap/1.0/\0";
    const string XmpExtHeader = "http://ns.adobe.com/xmp/extension/\0";
    const string NsXmp = "http://ns.adobe.com/xap/1.0/";
    const string NsMsPhoto = "http://ns.microsoft.com/photo/1.0/";
    const string NsRdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";
    static readonly int[] Percent = { 0, 1, 25, 50, 75, 99 };              // Windows' RatingPercent for 0..5 stars

    // stars 0..5 (0 removes the rating). Throws with a readable reason when the photo is left as it was.
    public static void Write(string path, int stars)
    {
        stars = Math.Max(0, Math.Min(5, stars));
        if (!JpegRotate.IsJpeg(path)) throw new IOException("only JPEG photos can hold a rating written by RetroGleek.");
        if ((File.GetAttributes(path) & Util.CloudMask) != 0) throw new IOException("cloud-only, not stored on this PC.");
        if ((File.GetAttributes(path) & FileAttributes.ReadOnly) != 0) throw new IOException("the file is read-only.");
        byte[] data = File.ReadAllBytes(path);
        if (data.Length < 4 || data[0] != 0xFF || data[1] != 0xD8) throw new IOException("its JPEG structure could not be read.");

        // the segments before the picture data
        int p = 2, sos = -1, xmpAt = -1, xmpLen = 0, exifAt = -1, exifLen = 0, app0End = -1;
        while (p + 4 <= data.Length && data[p] == 0xFF)
        {
            int marker = data[p + 1];
            if (marker == 0xDA) { sos = p; break; }
            if (marker == 0xD9) break;
            int len = (data[p + 2] << 8) | data[p + 3];
            if (len < 2 || p + 2 + len > data.Length) break;
            if (marker == 0xE1 && Starts(data, p + 4, len - 2, XmpExtHeader))
                throw new IOException("its XMP block is too large for RetroGleek to change safely (extended XMP).");
            if (marker == 0xE1 && Starts(data, p + 4, len - 2, XmpHeader)) { if (xmpAt >= 0) throw new IOException("it has more than one XMP block."); xmpAt = p; xmpLen = 2 + len; }
            else if (marker == 0xE1 && Starts(data, p + 4, len - 2, "Exif\0\0") && exifAt < 0) { exifAt = p; exifLen = 2 + len; }
            else if (marker == 0xE0 && p == 2) app0End = p + 2 + len;
            p += 2 + len;
        }
        if (sos < 0) throw new IOException("its JPEG structure could not be read.");

        byte[] head = (byte[])data.Clone();
        if (exifAt >= 0) PatchTiff(head, exifAt + 10, exifAt + exifLen, stars);

        string oldXmp = xmpAt >= 0 ? Encoding.UTF8.GetString(data, xmpAt + 4 + XmpHeader.Length, xmpLen - 4 - XmpHeader.Length) : null;
        byte[] packet = Encoding.UTF8.GetBytes(NewXmp(oldXmp, stars));
        byte[] hdr = Encoding.ASCII.GetBytes(XmpHeader);
        int segLen = 2 + hdr.Length + packet.Length;
        if (segLen > 65535) throw new IOException("its XMP block would be too large for one JPEG segment.");
        var seg = new byte[2 + segLen];
        seg[0] = 0xFF; seg[1] = 0xE1; seg[2] = (byte)(segLen >> 8); seg[3] = (byte)segLen;
        Buffer.BlockCopy(hdr, 0, seg, 4, hdr.Length);
        Buffer.BlockCopy(packet, 0, seg, 4 + hdr.Length, packet.Length);

        // the new file: everything before, the XMP segment in its old place (or after EXIF / JFIF), everything after
        int cutAt, cutLen;
        if (xmpAt >= 0) { cutAt = xmpAt; cutLen = xmpLen; }
        else { cutAt = exifAt >= 0 ? exifAt + exifLen : app0End > 0 ? app0End : 2; cutLen = 0; }
        var outp = new MemoryStream(data.Length + seg.Length);
        outp.Write(head, 0, cutAt);
        outp.Write(seg, 0, seg.Length);
        outp.Write(head, cutAt + cutLen, head.Length - cutAt - cutLen);
        byte[] result = outp.ToArray();

        string tmp = Path.Combine(Path.GetDirectoryName(path), "~rg" + Guid.NewGuid().ToString("N").Substring(0, 12) + ".tmp");
        try
        {
            File.WriteAllBytes(tmp, result);
            Check(data, sos, tmp, result.Length - (data.Length - sos), stars);
            File.Replace(tmp, path, null, true);           // keeps the original's creation date and attributes
        }
        finally { try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { } }
    }

    static bool Starts(byte[] d, int at, int room, string s)
    {
        if (room < s.Length || at + s.Length > d.Length) return false;
        for (int i = 0; i < s.Length; i++) if (d[at + i] != (byte)s[i]) return false;
        return true;
    }

    // The Windows Rating (0x4746) and RatingPercent (0x4749) tags in IFD0 of an EXIF (TIFF) block that starts at t and
    // ends before end: if they are there, new values in place. Used for JPEG's EXIF segment and PNG's eXIf chunk.
    internal static void PatchTiff(byte[] d, int t, int end, int stars)
    {
        if (t + 8 > end) return;
        bool le = d[t] == 'I' && d[t + 1] == 'I';
        if (!le && !(d[t] == 'M' && d[t + 1] == 'M')) return;
        long ifd = t + U32(d, t + 4, le);
        if (ifd < t || ifd + 2 > end) return;
        int n = U16(d, (int)ifd, le);
        for (int i = 0; i < n; i++)
        {
            int e = (int)ifd + 2 + i * 12;
            if (e + 12 > end) return;
            int tag = U16(d, e, le), type = U16(d, e + 2, le);
            if ((tag != 0x4746 && tag != 0x4749) || type != 3 || U32(d, e + 4, le) != 1) continue;   // SHORT, one value
            int v = tag == 0x4746 ? stars : Percent[stars];
            if (le) { d[e + 8] = (byte)v; d[e + 9] = (byte)(v >> 8); } else { d[e + 8] = (byte)(v >> 8); d[e + 9] = (byte)v; }
        }
    }

    static int U16(byte[] d, int i, bool le) { return le ? d[i] | (d[i + 1] << 8) : (d[i] << 8) | d[i + 1]; }
    static uint U32(byte[] d, int i, bool le)
    {
        return le ? (uint)(d[i] | (d[i + 1] << 8) | (d[i + 2] << 16) | (d[i + 3] << 24)) : (uint)((d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]);
    }

    // the XMP packet with the new rating (old = the file's packet, or null to make one). Also used for PNG.
    internal static string NewXmp(string old, int stars)
    {
        if (old == null)
        {
            return "<?xpacket begin=\"\uFEFF\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>" +
                   "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"" + NsRdf + "\">" +
                   "<rdf:Description rdf:about=\"\" xmlns:xmp=\"" + NsXmp + "\"" + (stars > 0 ? " xmp:Rating=\"" + stars + "\"" : "") + "/>" +
                   "</rdf:RDF></x:xmpmeta>" + new string(' ', 2048) + "<?xpacket end=\"w\"?>";   // room for other programs to edit in place
        }
        var doc = new XmlDocument { PreserveWhitespace = true, XmlResolver = null };
        var rs = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
        try
        {
            using (var sr = new StringReader(old.TrimEnd('\0')))
            using (XmlReader xr = XmlReader.Create(sr, rs))
                doc.Load(xr);
        }
        catch (XmlException) { throw new IOException("its XMP block could not be read, so it was left as it was."); }
        var nm = new XmlNamespaceManager(doc.NameTable);
        nm.AddNamespace("rdf", NsRdf);
        XmlNode rdf = doc.SelectSingleNode("//rdf:RDF", nm);
        if (rdf == null) throw new IOException("its XMP block has an unexpected layout, so it was left as it was.");
        XmlNodeList descs = rdf.SelectNodes("rdf:Description", nm);
        bool hadMs = false;
        foreach (XmlElement d in descs)
        {
            foreach (string ns in new[] { NsXmp, NsMsPhoto })
            {
                if (d.HasAttribute("Rating", ns)) { if (ns == NsMsPhoto) hadMs = true; d.RemoveAttribute("Rating", ns); }
                foreach (XmlNode c in new List<XmlNode>(Children(d)))
                    if (c.NodeType == XmlNodeType.Element && c.LocalName == "Rating" && c.NamespaceURI == ns)
                    { if (ns == NsMsPhoto) hadMs = true; d.RemoveChild(c); }
            }
        }
        XmlElement target = descs.Count > 0 ? (XmlElement)descs[0] : null;
        if (target == null)
        {
            target = doc.CreateElement("rdf", "Description", NsRdf);
            target.SetAttribute("about", NsRdf, "");
            rdf.AppendChild(target);
        }
        if (stars > 0)
        {
            XmlAttribute a = doc.CreateAttribute("xmp", "Rating", NsXmp);
            a.Value = stars.ToString(System.Globalization.CultureInfo.InvariantCulture);
            target.Attributes.Append(a);
            if (hadMs)
            {
                XmlAttribute m = doc.CreateAttribute("MicrosoftPhoto", "Rating", NsMsPhoto);
                m.Value = Percent[stars].ToString(System.Globalization.CultureInfo.InvariantCulture);
                target.Attributes.Append(m);
            }
        }
        var ws = new XmlWriterSettings { OmitXmlDeclaration = true, Encoding = new UTF8Encoding(false), Indent = false };
        var sb = new StringBuilder();
        using (XmlWriter xw = XmlWriter.Create(sb, ws)) doc.Save(xw);
        return sb.ToString();
    }

    static List<XmlNode> Children(XmlNode n)
    {
        var r = new List<XmlNode>();
        foreach (XmlNode c in n.ChildNodes) r.Add(c);
        return r;
    }

    // the picture data (from the start-of-scan marker to the end) must be byte for byte the same, the photo must
    // still decode, and the rating must read back
    static void Check(byte[] original, int sos, string path, int newSos, int stars)
    {
        byte[] d = File.ReadAllBytes(path);
        int tail = original.Length - sos;
        if (newSos < 0 || d.Length - newSos != tail) throw new IOException("the new file did not check out, so nothing was changed.");
        for (int i = 0; i < tail; i++)
            if (d[newSos + i] != original[sos + i]) throw new IOException("the new file did not check out, so nothing was changed.");
        using (var ms = new MemoryStream(d, false))
        using (Image img = Image.FromStream(ms, false, true))               // validates the data
        {
            if (FileRating.Read(path, img, true) != stars) throw new IOException("the rating could not be confirmed, so nothing was changed.");
        }
    }
}

// Writes a star rating into a PNG file, as XMP (xmp:Rating) in PNG's standard place for it: an uncompressed iTXt
// chunk with the keyword "XML:com.adobe.xmp", put just before the picture data (the first IDAT chunk). Programs that
// read XMP, such as Lightroom, see the rating. Nothing else changes:
//   - every other chunk (header, palette, transparency, colour profile, text, the picture data ...) is copied byte
//     for byte, in the same order;
//   - an XMP chunk already there is replaced (every other XMP property is kept);
//   - an eXIf chunk with the Windows Rating / RatingPercent tags gets their new values in place (new checksum).
// The new file is written under a temporary name and checked (every other chunk identical, every checksum right, the
// picture still decodes, the rating reads back) before it replaces the original. A file whose chunks don't add up, or
// whose XMP is compressed or can't be read, is left alone with the reason.
static class PngRating
{
    static readonly byte[] Signature = { 137, 80, 78, 71, 13, 10, 26, 10 };
    const string XmpKeyword = "XML:com.adobe.xmp";

    public static bool IsPng(string path) { return string.Equals(Path.GetExtension(path), ".png", StringComparison.OrdinalIgnoreCase); }

    sealed class Chunk
    {
        public int At;           // where the chunk starts (its length field)
        public int Len;          // the length of its data
        public string Type;
        public int Total { get { return 12 + Len; } }
    }

    // stars 0..5 (0 removes the rating). Throws with a readable reason when the file is left as it was.
    public static void Write(string path, int stars)
    {
        stars = Math.Max(0, Math.Min(5, stars));
        if (!IsPng(path)) throw new IOException("only PNG files are handled here.");
        if ((File.GetAttributes(path) & Util.CloudMask) != 0) throw new IOException("cloud-only, not stored on this PC.");
        if ((File.GetAttributes(path) & FileAttributes.ReadOnly) != 0) throw new IOException("the file is read-only.");
        byte[] data = File.ReadAllBytes(path);
        int end;
        List<Chunk> chunks = Parse(data, out end);

        int xmp = -1, exif = -1, firstIdat = -1;
        for (int i = 0; i < chunks.Count; i++)
        {
            Chunk c = chunks[i];
            if (c.Type == "iTXt" && IsXmp(data, c)) { if (xmp >= 0) throw new IOException("it has more than one XMP block."); xmp = i; }
            else if (c.Type == "eXIf" && exif < 0) exif = i;
            else if (c.Type == "IDAT" && firstIdat < 0) firstIdat = i;
        }
        if (firstIdat < 0) throw new IOException("its PNG structure could not be read (no picture data).");

        string oldXmp = xmp >= 0 ? XmpText(data, chunks[xmp]) : null;
        byte[] packet = Encoding.UTF8.GetBytes(JpegRating.NewXmp(oldXmp, stars));
        byte[] key = Encoding.ASCII.GetBytes(XmpKeyword);
        var body = new byte[key.Length + 5 + packet.Length];               // keyword, 0, not compressed, method 0, no language, no translated keyword
        Buffer.BlockCopy(key, 0, body, 0, key.Length);
        Buffer.BlockCopy(packet, 0, body, key.Length + 5, packet.Length);
        byte[] xmpChunk = MakeChunk("iTXt", body);

        // the new file: the chunks in their order, the XMP chunk (new) just before the first IDAT
        var outp = new MemoryStream(data.Length + xmpChunk.Length);
        outp.Write(data, 0, Signature.Length);
        for (int i = 0; i < chunks.Count; i++)
        {
            Chunk c = chunks[i];
            if (i == xmp) continue;                                        // the old XMP chunk: replaced
            if (i == firstIdat) outp.Write(xmpChunk, 0, xmpChunk.Length);
            if (i == exif)
            {
                var ex = new byte[c.Len];
                Buffer.BlockCopy(data, c.At + 8, ex, 0, c.Len);
                JpegRating.PatchTiff(ex, 0, ex.Length, stars);
                byte[] exChunk = MakeChunk("eXIf", ex);
                outp.Write(exChunk, 0, exChunk.Length);
                continue;
            }
            outp.Write(data, c.At, c.Total);
        }
        outp.Write(data, end, data.Length - end);                          // anything after IEND stays too
        byte[] result = outp.ToArray();

        string tmp = Path.Combine(Path.GetDirectoryName(path), "~rg" + Guid.NewGuid().ToString("N").Substring(0, 12) + ".tmp");
        try
        {
            File.WriteAllBytes(tmp, result);
            Check(data, chunks, tmp, stars);
            File.Replace(tmp, path, null, true);           // keeps the original's creation date and attributes
        }
        finally { try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { } }
    }

    // every chunk up to and including IEND, with its checksum checked; end = just after IEND
    static List<Chunk> Parse(byte[] d, out int end)
    {
        end = 0;
        if (d.Length < Signature.Length + 12) throw new IOException("its PNG structure could not be read.");
        for (int i = 0; i < Signature.Length; i++)
            if (d[i] != Signature[i]) throw new IOException("it is not really a PNG file.");
        var r = new List<Chunk>();
        int p = Signature.Length;
        while (p + 12 <= d.Length)
        {
            long len = BE32(d, p);
            if (len > d.Length - p - 12) throw new IOException("its PNG structure could not be read (a chunk runs past the end).");
            var c = new Chunk { At = p, Len = (int)len, Type = Encoding.ASCII.GetString(d, p + 4, 4) };
            if (Crc(d, p + 4, 4 + c.Len) != (uint)BE32(d, p + 8 + c.Len))
                throw new IOException("its " + c.Type + " chunk is damaged (wrong checksum), so it was left as it was.");
            r.Add(c);
            p += c.Total;
            if (c.Type == "IEND") { end = p; return r; }
        }
        throw new IOException("its PNG structure could not be read (no end chunk).");
    }

    static bool IsXmp(byte[] d, Chunk c)
    {
        int at = c.At + 8;
        if (c.Len < XmpKeyword.Length + 1) return false;
        for (int i = 0; i < XmpKeyword.Length; i++) if (d[at + i] != (byte)XmpKeyword[i]) return false;
        return d[at + XmpKeyword.Length] == 0;
    }

    // the XMP text of an iTXt chunk (only uncompressed XMP is changed)
    static string XmpText(byte[] d, Chunk c)
    {
        int p = c.At + 8 + XmpKeyword.Length + 1, stop = c.At + 8 + c.Len;
        if (p + 2 > stop) throw new IOException("its XMP block could not be read, so it was left as it was.");
        if (d[p] != 0) throw new IOException("its XMP block is compressed, so it was left as it was.");
        p += 2;                                                            // compression flag and method
        for (int k = 0; k < 2; k++)                                        // language tag, translated keyword
        {
            while (p < stop && d[p] != 0) p++;
            if (p >= stop) throw new IOException("its XMP block could not be read, so it was left as it was.");
            p++;
        }
        return Encoding.UTF8.GetString(d, p, stop - p);
    }

    static byte[] MakeChunk(string type, byte[] body)
    {
        var c = new byte[12 + body.Length];
        int n = body.Length;
        c[0] = (byte)(n >> 24); c[1] = (byte)(n >> 16); c[2] = (byte)(n >> 8); c[3] = (byte)n;
        for (int i = 0; i < 4; i++) c[4 + i] = (byte)type[i];
        Buffer.BlockCopy(body, 0, c, 8, n);
        uint crc = Crc(c, 4, 4 + n);
        c[8 + n] = (byte)(crc >> 24); c[9 + n] = (byte)(crc >> 16); c[10 + n] = (byte)(crc >> 8); c[11 + n] = (byte)crc;
        return c;
    }

    static long BE32(byte[] d, int i) { return ((long)d[i] << 24) | ((long)d[i + 1] << 16) | ((long)d[i + 2] << 8) | d[i + 3]; }

    static uint[] crcTable;

    // the CRC-32 that PNG uses for each chunk (over its type and data)
    static uint Crc(byte[] d, int at, int count)
    {
        uint[] t = crcTable;
        if (t == null)
        {
            t = new uint[256];
            for (uint n = 0; n < 256; n++)
            {
                uint c = n;
                for (int k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                t[n] = c;
            }
            crcTable = t;
        }
        uint crc = 0xFFFFFFFFu;
        for (int i = at; i < at + count; i++) crc = t[(crc ^ d[i]) & 0xFF] ^ (crc >> 8);
        return crc ^ 0xFFFFFFFFu;
    }

    // Every chunk except the XMP and eXIf ones must be byte for byte the same and in the same order, the new file
    // must parse with every checksum right and exactly one XMP chunk, the picture must still decode, and the rating
    // must read back
    static void Check(byte[] original, List<Chunk> oldChunks, string path, int stars)
    {
        const string bad = "the new file did not check out, so nothing was changed.";
        byte[] d = File.ReadAllBytes(path);
        int end;
        List<Chunk> now = Parse(d, out end);
        var a = new List<Chunk>();
        var b = new List<Chunk>();
        foreach (Chunk c in oldChunks) if (!(c.Type == "iTXt" && IsXmp(original, c)) && c.Type != "eXIf") a.Add(c);
        int xmps = 0;
        foreach (Chunk c in now)
        {
            if (c.Type == "iTXt" && IsXmp(d, c)) { xmps++; continue; }
            if (c.Type != "eXIf") b.Add(c);
        }
        if (xmps != 1 || a.Count != b.Count) throw new IOException(bad);
        for (int i = 0; i < a.Count; i++)
        {
            if (a[i].Total != b[i].Total) throw new IOException(bad);
            for (int k = 0; k < a[i].Total; k++)
                if (original[a[i].At + k] != d[b[i].At + k]) throw new IOException(bad);
        }
        using (var ms = new MemoryStream(d, false))
        using (Image img = Image.FromStream(ms, false, true))               // validates the data
        {
            if (FileRating.Read(path, img, true) != stars) throw new IOException("the rating could not be confirmed, so nothing was changed.");
        }
    }
}
