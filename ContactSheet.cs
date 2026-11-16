// RetroGleek - contact sheet: lossless PNG index sheets of the selected pictures (Tools > Contact sheet)
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE). Part of RetroGleek; see Program.cs for the overview.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Windows.Forms;

// Pages of at most 100 thumbnails, each with the picture's name and its size / platform underneath (and its marks,
// if wanted). Built one page at a time on a worker thread, decoding one picture at a time, so memory stays bounded
// however many pictures there are: one page (about 20 MB medium, 33 MB large) plus the copy used to verify the PNG. At most 2,000 pictures (20 pages) per export. Every page is saved as
// a verified lossless PNG (written under a temporary name, read back and compared, then put in place).
sealed class SheetOptions
{
    public int Size = 1;                   // 0 small, 1 medium, 2 large
    public bool Light;                     // light background (for printing)
    public bool Marks = true;              // stars, colour label and tag on each thumbnail
}

static class ContactSheet
{
    public const int MaxPictures = 2000;
    static readonly int[] Thumbs = { 128, 192, 256 };      // thumbnail box in pixels (the PNG's own pixels, not scaled for DPI)
    static readonly int[] Cols = { 12, 10, 8 };
    static readonly int[] Rows = { 8, 10, 12 };            // 96, 100, 96 pictures per page
    const int Pad = 8, CaptionH = 40, HeaderH = 44;

    public static int PerPage(int size) { return Cols[size] * Rows[size]; }
    public static int Pages(int count, int size) { return Math.Max(1, (count + PerPage(size) - 1) / PerPage(size)); }

    static int CellW(int size) { return Thumbs[size] + 2 * Pad; }
    static int CellH(int size) { return Thumbs[size] + 2 * Pad + CaptionH; }

    // width and height of a page holding n pictures
    static Size PageSize(int n, int size)
    {
        int cols = Cols[size], rows = Math.Max(1, (n + cols - 1) / cols);
        return new Size(cols * CellW(size) + 2 * Pad, HeaderH + rows * CellH(size) + Pad);
    }

    // a rough range for the total file size: retro pictures compress very well, photos much less
    public static void Estimate(int count, int size, out long low, out long high, out long pixels)
    {
        pixels = 0;
        int per = PerPage(size);
        for (int done = 0; done < count; done += per)
        {
            Size s = PageSize(Math.Min(per, count - done), size);
            pixels += (long)s.Width * s.Height;
        }
        low = pixels / 4;                                  // mostly flat colours
        high = pixels * 3 / 2;                             // mostly photos
    }

    public static string Mb(long bytes) { return bytes < 1048576 ? Math.Max(1, bytes / 1024) + " KB" : (bytes / 1048576.0).ToString("0.#") + " MB"; }

    // the file name of page p (0-based) of pages
    public static string PagePath(string chosen, int p, int pages)
    {
        if (pages == 1) return chosen;
        string dir = Path.GetDirectoryName(chosen), stem = Path.GetFileNameWithoutExtension(chosen);
        return Path.Combine(dir, stem + "_" + (p + 1).ToString("000") + ".png");
    }

    // Worker thread. Makes and saves every page; progress(picture, total, page, pages). Returns the files written.
    // errs gets one line per picture that could not be opened (it still gets a place on the sheet, marked).
    public static List<string> Make(List<string> paths, string title, SheetOptions o, string chosen, bool overwriteFirst,
                                    Action<int, int, int, int> progress, List<string> errs)
    {
        var written = new List<string>();
        int per = PerPage(o.Size), pages = Pages(paths.Count, o.Size);
        for (int p = 0; p < pages; p++)
        {
            int start = p * per, n = Math.Min(per, paths.Count - start);
            Size ps = PageSize(n, o.Size);
            using (var page = new Bitmap(ps.Width, ps.Height, PixelFormat.Format32bppArgb))
            {
                using (Graphics g = Graphics.FromImage(page))
                {
                    Color bg = o.Light ? Color.White : Color.FromArgb(24, 24, 24);
                    g.Clear(bg);
                    g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                    using (var hf = new Font("Segoe UI", 15f, FontStyle.Bold, GraphicsUnit.Pixel))
                    using (var sf = new Font("Segoe UI", 12f, GraphicsUnit.Pixel))
                    using (var hb = new SolidBrush(o.Light ? Color.Black : Color.White))
                    using (var mb = new SolidBrush(o.Light ? Color.FromArgb(90, 90, 90) : Color.FromArgb(150, 150, 150)))
                    {
                        string head = title + (pages > 1 ? "    page " + (p + 1) + " of " + pages : "");
                        g.DrawString(head, hf, hb, new RectangleF(Pad, 8, ps.Width - 2 * Pad - 300, 22), new StringFormat { Trimming = StringTrimming.EllipsisCharacter, FormatFlags = StringFormatFlags.NoWrap });
                        string right = paths.Count + (paths.Count == 1 ? " picture" : " pictures") + "    " + DateTime.Now.ToString("yyyy-MM-dd HH:mm") + "    RetroGleek";
                        SizeF rs = g.MeasureString(right, sf);
                        g.DrawString(right, sf, mb, ps.Width - Pad - rs.Width, 12);
                        for (int k = 0; k < n; k++)
                        {
                            int i = start + k;
                            if (progress != null) progress(i + 1, paths.Count, p + 1, pages);
                            int cx = Pad + (k % Cols[o.Size]) * CellW(o.Size), cy = HeaderH + (k / Cols[o.Size]) * CellH(o.Size);
                            Cell(g, paths[i], new Rectangle(cx, cy, CellW(o.Size), CellH(o.Size)), o, sf, errs);
                        }
                    }
                }
                string dest = PagePath(chosen, p, pages);
                if (p > 0 || !overwriteFirst)
                    if (File.Exists(dest)) dest = Util.UniquePath(Path.GetDirectoryName(dest), Path.GetFileNameWithoutExtension(dest), ".png");
                Exporter.SavePng(page, dest, p == 0 && overwriteFirst);
                written.Add(dest);
            }
        }
        return written;
    }

    // one picture: its thumbnail (pixel art enlarged by whole steps with hard edges), name, size / platform, marks
    static void Cell(Graphics g, string path, Rectangle rc, SheetOptions o, Font f, List<string> errs)
    {
        int t = Thumbs[o.Size];
        var box = new Rectangle(rc.X + Pad, rc.Y + Pad, t, t);
        Color text = o.Light ? Color.Black : Color.Gainsboro, dim = o.Light ? Color.FromArgb(90, 90, 90) : Color.FromArgb(150, 150, 150);
        string line2 = null;
        int fileStars = 0;
        Bitmap pic = null, decoded = null;                                  // decoded: Windows codec or scaled big JPEG
        Image img = null;
        Stream fs = null;
        try
        {
            if ((File.GetAttributes(path) & Util.CloudMask) != 0) throw new IOException("cloud-only, not stored on this PC");
            int turns = 0;
            Image src;
            if (!Util.IsNative(path) && Retro.Claims(path))
            {
                long bytes; string platform; int frames; RetroGeom geom;
                pic = Retro.Load(path, out bytes, out platform, out frames, out geom);
                src = pic;
                int ow = geom != null && geom.OrigW > 0 ? geom.OrigW : pic.Width, oh = geom != null && geom.OrigH > 0 ? geom.OrigH : pic.Height;
                line2 = ow + " x " + oh + "  " + (string.IsNullOrEmpty(platform) ? "retro" : platform);
            }
            else if (WinCodec.Claims(path))
            {
                CodecPic c;
                try { c = WinCodec.Load(path, t, true); }                     // decoded straight to about thumbnail size
                catch (Exception cex) { throw new IOException(WinCodec.Why(path, cex)); }
                decoded = c.Bmp; src = decoded; turns = c.Rot;
                if (o.Marks) fileStars = c.Stars;
                bool sw = (turns & 1) == 1;
                line2 = (sw ? c.H : c.W) + " x " + (sw ? c.W : c.H) + "  " + WinCodec.Name(path);
            }
            else
            {
                fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16);
                img = Image.FromStream(fs, false, false);
                turns = Util.ReadRotation(img);
                if (o.Marks && FileRating.MayHold(path)) fileStars = FileRating.Read(path, img);
                src = img;
                bool sw = (turns & 1) == 1;
                line2 = (sw ? img.Height : img.Width) + " x " + (sw ? img.Width : img.Height) + "  " + Path.GetExtension(path).TrimStart('.').ToUpperInvariant();
                if (JpegRotate.IsJpeg(path) && WinCodec.WorthScaling(img.Width, img.Height, t))
                {
                    decoded = WinCodec.ScaledJpeg(path, img.Width, img.Height, t);   // big photo: much quicker
                    if (decoded != null) src = decoded;
                }
            }
            int w = src.Width, h = src.Height;
            bool swap = (turns & 1) == 1;
            int vw = swap ? h : w, vh = swap ? w : h;                          // as it is shown, after rotation
            double s = Math.Min((double)t / vw, (double)t / vh);
            bool art = pic != null;
            if (art && s > 1) s = Math.Floor(s);                            // retro: whole-number enlargement only
            if (!art && s > 1) s = 1;                                       // photos are never enlarged
            int dw = Math.Max(1, (int)Math.Round(vw * s)), dh = Math.Max(1, (int)Math.Round(vh * s));
            GraphicsState st = g.Save();
            g.InterpolationMode = s >= 1 ? InterpolationMode.NearestNeighbor : InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.TranslateTransform(box.X + t / 2f, box.Y + t / 2f);
            g.RotateTransform(turns * 90f);
            float rw = swap ? dh : dw, rh = swap ? dw : dh;                  // the drawn size in the picture's own orientation
            using (var ia = new ImageAttributes())
            {
                ia.SetWrapMode(WrapMode.TileFlipXY);
                g.DrawImage(src, new Rectangle((int)(-rw / 2), (int)(-rh / 2), (int)rw, (int)rh), 0, 0, w, h, GraphicsUnit.Pixel, ia);
            }
            g.Restore(st);
        }
        catch (Exception ex)
        {
            using (var pb = new SolidBrush(o.Light ? Color.FromArgb(230, 230, 230) : Color.FromArgb(44, 44, 44))) g.FillRectangle(pb, box.X + t / 6, box.Y + t / 6, t * 2 / 3, t * 2 / 3);
            using (var eb = new SolidBrush(Color.FromArgb(230, 110, 60)))
                g.DrawString("could not be opened", f, eb, new RectangleF(box.X, box.Y + t / 2 - 8, t, 20), new StringFormat { Alignment = StringAlignment.Center });
            line2 = "could not be opened";
            if (errs != null) errs.Add(Path.GetFileName(path) + ": " + Util.Why(ex));
        }
        finally
        {
            if (pic != null) pic.Dispose();
            if (decoded != null) decoded.Dispose();
            if (img != null) img.Dispose();
            if (fs != null) fs.Dispose();
        }

        // marks
        Mark m = null;
        if (o.Marks)
        {
            try { var fi = new FileInfo(path); m = Marks.Get(path, fi.Length, fi.LastWriteTimeUtc.Ticks); } catch (Exception) { }
        }
        if (m != null && m.Label > 0)
            using (var lb = new SolidBrush(Marks.LabelColours[m.Label])) g.FillRectangle(lb, box.X, rc.Y + Pad - 6, t, 4);
        var sfmt = new StringFormat { Alignment = StringAlignment.Center, Trimming = StringTrimming.EllipsisCharacter, FormatFlags = StringFormatFlags.NoWrap };
        using (var tb = new SolidBrush(text))
            g.DrawString((m != null && m.Tag ? "\u2714 " : "") + Path.GetFileName(path), f, tb, new RectangleF(rc.X + 2, box.Bottom + 4, rc.Width - 4, 17), sfmt);
        int stars = m != null && m.Stars > 0 ? m.Stars : fileStars;           // yours, or else the file's own rating
        string l2 = (stars > 0 ? Marks.StarText(stars) + "  " : "") + (line2 ?? "");
        using (var db = new SolidBrush(dim))
            g.DrawString(l2, f, db, new RectangleF(rc.X + 2, box.Bottom + 21, rc.Width - 4, 17), sfmt);
    }

    // ---- the options dialog: size, background, marks, with the page count and size estimate. null = cancelled.
    public static SheetOptions Ask(IWin32Window owner, int count, string folder, Action<Form> darkTitle, out string chosen, out bool overwrite)
    {
        chosen = null; overwrite = false;
        var o = new SheetOptions();
        Color panelBg = Color.FromArgb(38, 38, 38), text = Color.Gainsboro;
        using (var f = new Form())
        {
            f.AutoScaleMode = AutoScaleMode.None;
            f.Font = new Font("Segoe UI", 9.5f);
            f.Text = "Contact sheet - " + count + (count == 1 ? " picture" : " pictures");
            f.StartPosition = FormStartPosition.CenterParent;
            f.FormBorderStyle = FormBorderStyle.FixedDialog;
            f.ShowInTaskbar = false; f.MinimizeBox = false; f.MaximizeBox = false;
            f.BackColor = panelBg; f.ForeColor = text;
            f.ClientSize = new Size(Util.S(470), Util.S(268));
            if (darkTitle != null) f.HandleCreated += delegate { darkTitle(f); };
            int pad = Util.S(14), y = pad;
            var head = new Label { Left = pad, Top = y, Width = Util.S(440), Height = Util.S(20), ForeColor = Color.Silver,
                                   Text = "Lossless PNG index sheets of the selected pictures, in grid order." };
            f.Controls.Add(head);
            y += Util.S(30);
            var radios = new RadioButton[3];
            string[] names = { "Small  (128 px, 12 per row)", "Medium  (192 px, 10 per row)", "Large  (256 px, 8 per row)" };
            for (int i = 0; i < 3; i++)
            {
                radios[i] = new RadioButton { Left = pad, Top = y, Width = Util.S(300), Height = Util.S(24), Text = names[i], Checked = i == o.Size, ForeColor = text };
                f.Controls.Add(radios[i]);
                y += Util.S(26);
            }
            y += Util.S(6);
            var light = new CheckBox { Left = pad, Top = y, Width = Util.S(400), Height = Util.S(24), Text = "Light background (better for printing)", ForeColor = text };
            f.Controls.Add(light);
            y += Util.S(26);
            var marks = new CheckBox { Left = pad, Top = y, Width = Util.S(400), Height = Util.S(24), Text = "Show ratings, colour labels and tags", Checked = true, ForeColor = text };
            f.Controls.Add(marks);
            y += Util.S(32);
            var est = new Label { Left = pad, Top = y, Width = Util.S(440), Height = Util.S(38), ForeColor = Color.FromArgb(255, 205, 70) };
            f.Controls.Add(est);
            Action update = delegate
            {
                int size = radios[0].Checked ? 0 : radios[2].Checked ? 2 : 1;
                long low, high, px;
                Estimate(count, size, out low, out high, out px);
                int pages = Pages(count, size);
                est.Text = pages + (pages == 1 ? " page" : " pages") + " (up to " + PerPage(size) + " pictures each), about " + Mb(low) + " to " + Mb(high) +
                           " in all.\nBuilt one page at a time, so memory use stays small.";
            };
            foreach (RadioButton r in radios) r.CheckedChanged += delegate { update(); };
            update();
            var ok = new Button { Text = "Save...", Width = Util.S(96), Height = Util.S(30), Left = Util.S(470) - pad - Util.S(200), Top = Util.S(268) - pad - Util.S(30),
                                  FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(60, 130, 230), ForeColor = Color.White, DialogResult = DialogResult.OK };
            var cancel = new Button { Text = "Cancel", Width = Util.S(96), Height = Util.S(30), Left = Util.S(470) - pad - Util.S(96), Top = ok.Top,
                                      FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(52, 52, 52), ForeColor = text, DialogResult = DialogResult.Cancel };
            ok.FlatAppearance.BorderSize = 0; cancel.FlatAppearance.BorderSize = 0;
            f.Controls.Add(ok); f.Controls.Add(cancel);
            f.AcceptButton = ok; f.CancelButton = cancel;
            if (f.ShowDialog(owner) != DialogResult.OK) return null;
            o.Size = radios[0].Checked ? 0 : radios[2].Checked ? 2 : 1;
            o.Light = light.Checked;
            o.Marks = marks.Checked;
        }
        using (var d = new SaveFileDialog())
        {
            int pages = Pages(count, o.Size);
            d.Title = pages == 1 ? "Save the contact sheet" : "Save the contact sheet (" + pages + " pages: name_001.png, name_002.png ...)";
            d.Filter = "PNG image (lossless)|*.png";
            d.DefaultExt = "png"; d.AddExtension = true; d.OverwritePrompt = pages == 1;
            if (folder != null) d.InitialDirectory = folder;
            string fn = Path.GetFileName((folder ?? "").TrimEnd('\\'));
            d.FileName = "Contact sheet - " + (fn.Length > 0 ? fn : "pictures") + ".png";
            foreach (char c in Path.GetInvalidFileNameChars()) d.FileName = d.FileName.Replace(c, '_');
            if (d.ShowDialog(owner) != DialogResult.OK) return null;
            chosen = d.FileName;
            overwrite = pages == 1;                            // a single sheet: the dialog already asked before replacing
        }
        return o;
    }
}
