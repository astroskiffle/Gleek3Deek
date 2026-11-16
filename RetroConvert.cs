// RetroGleek - converting pictures into retro-computer formats (Tools > Convert to a retro format, Ctrl+Shift+E)
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE). Part of RetroGleek; see Program.cs for the overview.
//
// RECOIL only reads retro formats, so the writers are RetroGleek's own. A conversion always makes NEW files next to
// (or away from) the originals, which are never changed. It is lossy by nature: each picture is fitted to the
// machine's screen and reduced to its colours and colour rules, with optional dithering.
//
// Every converted file is checked before it is kept: RECOIL decodes the new bytes and every pixel must be exactly what
// the converter meant. The machine's palette is also taken from RECOIL (by decoding a small test screen), so the
// preview, the check and the viewer all show the same colours.
//
// Formats:
//   ZX Spectrum screen (.scr, 6912 bytes): 256 x 192 pixels; each 8 x 8 block has one ink and one paper colour from
//   the same brightness (8 colours, normal or bright; black is the same in both). Per block, the pair of colours that
//   best covers the block's pixels (including what dithering between them can show) is chosen; then each pixel is set
//   to ink or paper: nearest colour, an 8 x 8 ordered (Bayer) pattern, or error diffusion (Floyd-Steinberg, serpentine).
//   C64 Koala Painter (.koa, 10003 bytes): 160 x 200 multicolour, pixels twice as wide as tall; 16 fixed colours; each
//   4 x 8 cell shows the screen's background colour plus 3 of its own. The background is the colour nearest to the
//   most pixels; per cell the 3 colours that best cover it (again including the mixes dithering can show) are chosen.
//   C64 Doodle (.dd, 9218 bytes): 320 x 200 hires; 2 of the 16 colours per 8 x 8 cell, chosen like the Spectrum's.
//   Amstrad CPC screen (.scr, AMSDOS header + 16384 bytes): mode 0 is 160 x 200 wide pixels with 16 of the CPC's 27
//   colours, mode 1 is 320 x 200 with 4 of them; the mode and colours sit in the screen's unused bytes (offset 6096).
//   Atari ST Degas (.pi1, 32034 bytes): 320 x 200, 16 colours chosen for the picture from the ST's 512.
//   Amiga IFF ILBM (.iff, uncompressed): 320 x 256 (PAL), 32 colours chosen for the picture from the Amiga's 4096.
//   MSX Screen 2 (.sc2, BSAVE of video memory): 256 x 192, the TMS9918's 15 colours; each 8 x 1 strip has one
//   foreground and one background colour (chosen per strip like the Spectrum's ink and paper).
//   MSX2 Screen 8 (.sc8, BSAVE): 256 x 212, 256 fixed colours (3 bits green, 3 red, 2 blue), one byte per pixel.
//   For the ST, Amiga and CPC the picture's own palette is found by median cut and refined by k-means, then each colour is
//   snapped to the machine's levels. The ordered pattern leaves pixels that already match a palette colour alone.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

sealed class ConvertOptions
{
    public int Format;           // index into RetroConvert.FormatNames (0 = ZX Spectrum .scr)
    public bool Fill;            // false: the whole picture with black borders; true: cropped to fill the screen
    public int Dither;           // 0 none, 1 ordered pattern, 2 error diffusion
    public string DestDir;       // where the new files go
}

static class RetroConvert
{
    public static readonly string[] FormatNames =
    {
        "ZX Spectrum .scr  -  256 x 192, 2 colours per 8 x 8",
        "C64 Koala .koa  -  160 x 200, 4 colours per 4 x 8",
        "C64 Doodle .dd  -  320 x 200, 2 colours per 8 x 8",
        "Amstrad CPC Mode 0 .scr  -  160 x 200, 16 of 27 colours",
        "Amstrad CPC Mode 1 .scr  -  320 x 200, 4 of 27 colours",
        "Atari ST Degas .pi1  -  320 x 200, 16 of 512 colours",
        "Amiga IFF .iff  -  320 x 256, 32 of 4096 colours",
        "MSX Screen 2 .sc2  -  256 x 192, 2 colours per 8 x 1",
        "MSX2 Screen 8 .sc8  -  256 x 212, 256 fixed colours"
    };
    static readonly string[] FormatExts = { ".scr", ".koa", ".dd", ".scr", ".scr", ".pi1", ".iff", ".sc2", ".sc8" };
    public static readonly string[] DitherNames = { "None (flat colours)", "Ordered pattern (typical of the time)", "Error diffusion (finest detail)" };

    // what was chosen last time while RetroGleek runs (not saved)
    static int lastDither = 1, lastFormat;
    static bool lastFill;

    // ---------------------------------------------------------------- RECOIL: palette and checking

    sealed class MemRecoil : Recoil.RECOIL
    {
        protected override int ReadFile(string filename, byte[] content, int contentLength) { return -1; }   // no companion files
    }

    // RECOIL's picture of a file held in memory (first frame), as RGB without alpha. Throws if RECOIL can't read it.
    static int[] RecoilPixels(string name, byte[] data, out int w, out int h)
    {
        var r = new MemRecoil();
        bool ok;
        try { ok = r.Decode(name, data, data.Length); }
        catch (Exception) { ok = false; }
        if (!ok) throw new InvalidDataException("RECOIL could not read the converted picture back, so nothing was kept.");
        w = r.GetWidth(); h = r.GetHeight();
        int[] px = r.GetPixels();
        if (w <= 0 || h <= 0 || px == null || px.Length < w * h) throw new InvalidDataException("RECOIL returned an invalid picture, so nothing was kept.");
        return px;
    }

    static int[] zxPal;                                    // [bright * 8 + colour] -> 0xFFRRGGBB, as RECOIL shows them
    static readonly object palSync = new object();

    // the ZX Spectrum colours, read from RECOIL: a test screen with the 16 ink colours side by side, decoded
    static int[] ZxPalette()
    {
        lock (palSync)
        {
            if (zxPal != null) return zxPal;
            var d = new byte[6912];
            for (int c = 0; c < 16; c++)
            {
                for (int line = 0; line < 8; line++) d[ScrAddr(c * 8, line)] = 0xFF;         // every pixel of block c is ink
                d[6144 + c] = (byte)(((c >> 3) << 6) | (c & 7));                            // bright, paper 0, ink c
            }
            int w, h;
            int[] px = RecoilPixels("palette.scr", d, out w, out h);
            int sx = w / 256, sy = h / 192;
            if (sx < 1 || sy < 1 || w % 256 != 0 || h % 192 != 0) throw new InvalidDataException("RECOIL shows ZX Spectrum screens in an unexpected size.");
            var pal = new int[16];
            for (int c = 0; c < 16; c++) pal[c] = px[(4 * sy) * w + (c * 8 + 4) * sx] | unchecked((int)0xFF000000);
            zxPal = pal;
            return pal;
        }
    }

    // where the byte for pixel (x, y) is in a Spectrum screen (the screen is stored in thirds, then by character line)
    static int ScrAddr(int x, int y) { return ((y & 0xC0) << 5) | ((y & 0x07) << 8) | ((y & 0x38) << 2) | (x >> 3); }

    // RECOIL must show exactly what the converter meant (shown = w x h pixels, 0xFFRRGGBB)
    static void Check(string ext, byte[] data, int[] shown, int w, int h)
    {
        int rw, rh;
        int[] px = RecoilPixels("check" + ext, data, out rw, out rh);
        if (rw % w != 0 || rh % h != 0) throw new InvalidDataException("RECOIL shows the converted picture in an unexpected size, so nothing was kept.");
        int sx = rw / w, sy = rh / h;
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
                if ((px[(y * sy) * rw + x * sx] | unchecked((int)0xFF000000)) != shown[y * w + x])
                    throw new InvalidDataException("RECOIL does not show the converted picture as intended, so nothing was kept.");
    }

    // ---------------------------------------------------------------- the picture, fitted to the screen

    // The source fitted into w x h pixels that are pxw times as wide as they are tall: the whole picture with black
    // borders, or cropped to fill. Transparency becomes black. Returns RGB as floats (3 per pixel).
    static float[] Fit(Bitmap src, int w, int h, bool fill, int pxw)
    {
        int[] px = new int[w * h];
        using (var b = new Bitmap(w, h, PixelFormat.Format32bppArgb))
        {
            using (Graphics g = Graphics.FromImage(b))
            using (var ia = new ImageAttributes())
            {
                g.Clear(Color.Black);
                double dw = (double)w * pxw;                                          // the screen's width as shown (wide pixels)
                double s = fill ? Math.Max(dw / src.Width, (double)h / src.Height) : Math.Min(dw / src.Width, (double)h / src.Height);
                int nw = Math.Max(1, (int)Math.Round(src.Width * s / pxw)), nh = Math.Max(1, (int)Math.Round(src.Height * s));
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                ia.SetWrapMode(WrapMode.TileFlipXY);                                // no dark fringe at the edges
                g.DrawImage(src, new Rectangle((w - nw) / 2, (h - nh) / 2, nw, nh), 0, 0, src.Width, src.Height, GraphicsUnit.Pixel, ia);
            }
            BitmapData bd = b.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try { for (int y = 0; y < h; y++) Marshal.Copy(new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), px, y * w, w); }
            finally { b.UnlockBits(bd); }
        }
        var f = new float[w * h * 3];
        for (int i = 0; i < px.Length; i++)
        {
            f[i * 3] = (px[i] >> 16) & 255; f[i * 3 + 1] = (px[i] >> 8) & 255; f[i * 3 + 2] = px[i] & 255;
        }
        return f;
    }

    // weights for colour distance (squared), close to how bright each primary looks
    const float WR = 0.897f, WG = 1.761f, WB = 0.342f;

    // ---------------------------------------------------------------- ZX Spectrum

    static readonly int[] Bayer8 =
    {
         0, 32,  8, 40,  2, 34, 10, 42,   48, 16, 56, 24, 50, 18, 58, 26,   12, 44,  4, 36, 14, 46,  6, 38,   60, 28, 52, 20, 62, 30, 54, 22,
         3, 35, 11, 43,  1, 33,  9, 41,   51, 19, 59, 27, 49, 17, 57, 25,   15, 47,  7, 39, 13, 45,  5, 37,   63, 31, 55, 23, 61, 29, 53, 21
    };

    // The .scr bytes for a picture, and the picture as that file shows it (256 x 192, 0xFFRRGGBB).
    public static byte[] ToZx(Bitmap src, bool fill, int dither, out int[] shown)
    {
        const int W = 256, H = 192;
        int[] pal = ZxPalette();
        var pr = new float[16]; var pg = new float[16]; var pb = new float[16];
        for (int c = 0; c < 16; c++) { pr[c] = (pal[c] >> 16) & 255; pg[c] = (pal[c] >> 8) & 255; pb[c] = pal[c] & 255; }
        float[] img = Fit(src, W, H, fill, 1);

        // each block's colours: the brightness and pair (paper, ink) that best cover its 64 pixels
        var paper = new int[768]; var ink = new int[768];
        for (int cell = 0; cell < 768; cell++)
        {
            int cx = (cell & 31) * 8, cy = (cell >> 5) * 8;
            double best = double.MaxValue;
            for (int br = 0; br < 2; br++)
                for (int i = 0; i < 8; i++)
                    for (int j = i; j < 8; j++)
                    {
                        int a = br * 8 + i, b = br * 8 + j;
                        double e = 0;
                        float dr = pr[b] - pr[a], dg = pg[b] - pg[a], db = pb[b] - pb[a];
                        float dd = dr * dr * WR + dg * dg * WG + db * db * WB;
                        for (int y = cy; y < cy + 8 && e < best; y++)
                            for (int x = cx; x < cx + 8; x++)
                            {
                                int k = (y * W + x) * 3;
                                float vr = img[k] - pr[a], vg = img[k + 1] - pg[a], vb = img[k + 2] - pb[a];
                                float t = dd <= 0 ? 0 : (vr * dr * WR + vg * dg * WG + vb * db * WB) / dd;
                                if (t < 0) t = 0; else if (t > 1) t = 1;
                                float qr = vr - t * dr, qg = vg - t * dg, qb = vb - t * db;  // distance to the nearest mix of the two
                                e += qr * qr * WR + qg * qg * WG + qb * qb * WB;
                            }
                        if (e < best - 1e-6) { best = e; paper[cell] = a; ink[cell] = b; }
                    }
        }

        // each pixel: ink or paper
        var isInk = new bool[W * H];
        float[] work = dither == 2 ? (float[])img.Clone() : img;
        for (int y = 0; y < H; y++)
        {
            bool rev = dither == 2 && (y & 1) == 1;                               // serpentine: every other line right to left
            for (int n = 0; n < W; n++)
            {
                int x = rev ? W - 1 - n : n;
                int cell = (y >> 3) * 32 + (x >> 3), a = paper[cell], b = ink[cell], k = (y * W + x) * 3;
                float vr = work[k], vg = work[k + 1], vb = work[k + 2];
                bool on;
                if (dither == 1)
                {
                    float dr = pr[b] - pr[a], dg = pg[b] - pg[a], db = pb[b] - pb[a];
                    float dd = dr * dr * WR + dg * dg * WG + db * db * WB;
                    float t = dd <= 0 ? 0 : ((vr - pr[a]) * dr * WR + (vg - pg[a]) * dg * WG + (vb - pb[a]) * db * WB) / dd;
                    on = t > (Bayer8[(y & 7) * 8 + (x & 7)] + 0.5f) / 64f;
                }
                else
                {
                    float ar = vr - pr[a], ag = vg - pg[a], ab = vb - pb[a], br2 = vr - pr[b], bg2 = vg - pg[b], bb2 = vb - pb[b];
                    on = br2 * br2 * WR + bg2 * bg2 * WG + bb2 * bb2 * WB < ar * ar * WR + ag * ag * WG + ab * ab * WB;
                    if (dither == 2)
                    {
                        int c = on ? b : a, dx = rev ? -1 : 1;
                        float er = vr - pr[c], eg = vg - pg[c], eb = vb - pb[c];
                        Spread(work, W, H, x + dx, y, er, eg, eb, 7f / 16);
                        Spread(work, W, H, x - dx, y + 1, er, eg, eb, 3f / 16);
                        Spread(work, W, H, x, y + 1, er, eg, eb, 5f / 16);
                        Spread(work, W, H, x + dx, y + 1, er, eg, eb, 1f / 16);
                    }
                }
                isInk[y * W + x] = on;
            }
        }

        // the file, and what it shows
        var d = new byte[6912];
        shown = new int[W * H];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++)
            {
                int cell = (y >> 3) * 32 + (x >> 3);
                bool on = isInk[y * W + x] && ink[cell] != paper[cell];
                if (on) d[ScrAddr(x, y)] |= (byte)(0x80 >> (x & 7));
                shown[y * W + x] = pal[on ? ink[cell] : paper[cell]];
            }
        for (int cell = 0; cell < 768; cell++)
            d[6144 + cell] = (byte)(((ink[cell] >> 3) << 6) | ((paper[cell] & 7) << 3) | (ink[cell] & 7));   // no flash
        return d;
    }

    static void Spread(float[] work, int w, int h, int x, int y, float er, float eg, float eb, float f)
    {
        if (x < 0 || x >= w || y >= h) return;
        int k = (y * w + x) * 3;
        work[k] = Clamp(work[k] + er * f); work[k + 1] = Clamp(work[k + 1] + eg * f); work[k + 2] = Clamp(work[k + 2] + eb * f);
    }

    static float Clamp(float v) { return v < -64 ? -64 : v > 320 ? 320 : v; }

    // ---------------------------------------------------------------- shared colour helpers

    // squared distance from colour v to the nearest mix of colours a and b (t = how far towards b, 0..1)
    static float SegDist(float vr, float vg, float vb, float ar, float ag, float ab, float br, float bg, float bb, out float t)
    {
        float dr = br - ar, dg = bg - ag, db = bb - ab;
        float dd = dr * dr * WR + dg * dg * WG + db * db * WB;
        float xr = vr - ar, xg = vg - ag, xb = vb - ab;
        t = dd <= 0 ? 0 : (xr * dr * WR + xg * dg * WG + xb * db * WB) / dd;
        if (t < 0) t = 0; else if (t > 1) t = 1;
        float qr = xr - t * dr, qg = xg - t * dg, qb = xb - t * db;
        return qr * qr * WR + qg * qg * WG + qb * qb * WB;
    }

    static float Dist(float vr, float vg, float vb, float r, float g, float b)
    {
        float dr = vr - r, dg = vg - g, db = vb - b;
        return dr * dr * WR + dg * dg * WG + db * db * WB;
    }

    static int Nearest(float vr, float vg, float vb, float[] pr, float[] pg, float[] pb, int n)
    {
        int best = 0;
        float bd = float.MaxValue;
        for (int c = 0; c < n; c++) { float d = Dist(vr, vg, vb, pr[c], pg[c], pb[c]); if (d < bd) { bd = d; best = c; } }
        return best;
    }

    // spreads a pixel's error to its unvisited neighbours (Floyd-Steinberg; dx = the direction of travel)
    static void Diffuse(float[] work, int w, int h, int x, int y, int dx, float er, float eg, float eb)
    {
        Spread(work, w, h, x + dx, y, er, eg, eb, 7f / 16);
        Spread(work, w, h, x - dx, y + 1, er, eg, eb, 3f / 16);
        Spread(work, w, h, x, y + 1, er, eg, eb, 5f / 16);
        Spread(work, w, h, x + dx, y + 1, er, eg, eb, 1f / 16);
    }

    static int Argb(float r, float g, float b) { return unchecked((int)0xFF000000) | ((int)r << 16) | ((int)g << 8) | (int)b; }

    // ---------------------------------------------------------------- Commodore 64 (Koala Painter)

    static int[] c64Pal;

    // the 16 C64 colours, read from RECOIL: a Koala picture whose first 16 cells each show one colour
    static int[] C64Palette()
    {
        lock (palSync)
        {
            if (c64Pal != null) return c64Pal;
            var d = new byte[10003];
            d[0] = 0x00; d[1] = 0x60;                                          // load address $6000
            for (int c = 0; c < 16; c++)
            {
                for (int r = 0; r < 8; r++) d[2 + c * 8 + r] = 0xFF;           // every pixel %11: the colour-RAM colour
                d[9002 + c] = (byte)c;
            }
            int w, h;
            int[] px = RecoilPixels("palette.koa", d, out w, out h);
            if (w % 160 != 0 || h % 200 != 0) throw new InvalidDataException("RECOIL shows Koala pictures in an unexpected size.");
            int sx = w / 160, sy = h / 200;
            var pal = new int[16];
            for (int c = 0; c < 16; c++) pal[c] = px[(4 * sy) * w + (c * 4 + 2) * sx] | unchecked((int)0xFF000000);
            c64Pal = pal;
            return pal;
        }
    }

    // The .koa bytes for a picture, and the picture as that file shows it (160 x 200, 0xFFRRGGBB).
    public static byte[] ToKoala(Bitmap src, bool fill, int dither, out int[] shown)
    {
        const int W = 160, H = 200;
        int[] pal = C64Palette();
        var pr = new float[16]; var pg = new float[16]; var pb = new float[16];
        for (int c = 0; c < 16; c++) { pr[c] = (pal[c] >> 16) & 255; pg[c] = (pal[c] >> 8) & 255; pb[c] = pal[c] & 255; }
        float[] img = Fit(src, W, H, fill, 2);

        // the background: the colour nearest to the most pixels
        var count = new int[16];
        for (int i = 0; i < W * H; i++) count[Nearest(img[i * 3], img[i * 3 + 1], img[i * 3 + 2], pr, pg, pb, 16)]++;
        int bgc = 0;
        for (int c = 1; c < 16; c++) if (count[c] > count[bgc]) bgc = c;
        var others = new int[15];
        for (int c = 0, n = 0; c < 16; c++) if (c != bgc) others[n++] = c;

        // the 120 pairs of colours, and for each cell every pixel's distance to the mixes of each pair
        var pa = new int[120]; var pbx = new int[120];
        var pairOf = new int[256];
        for (int a = 0, n = 0; a < 16; a++)
            for (int b = a + 1; b < 16; b++) { pa[n] = a; pbx[n] = b; pairOf[a * 16 + b] = n; pairOf[b * 16 + a] = n; n++; }
        var seg = new float[32 * 120];
        var cols = new int[1000 * 4];
        float tt;
        for (int cell = 0; cell < 1000; cell++)
        {
            int cx = (cell % 40) * 4, cy = (cell / 40) * 8;
            for (int p = 0; p < 32; p++)
            {
                int k = ((cy + (p >> 2)) * W + cx + (p & 3)) * 3;
                for (int q = 0; q < 120; q++)
                    seg[p * 120 + q] = SegDist(img[k], img[k + 1], img[k + 2], pr[pa[q]], pg[pa[q]], pb[pa[q]], pr[pbx[q]], pg[pbx[q]], pb[pbx[q]], out tt);
            }
            double best = double.MaxValue;
            int ba = others[0], bb = others[1], bc = others[2];
            for (int ia = 0; ia < 15; ia++)
                for (int ib = ia + 1; ib < 15; ib++)
                    for (int ic = ib + 1; ic < 15; ic++)
                    {
                        int a = others[ia], b = others[ib], c = others[ic];
                        int q1 = pairOf[bgc * 16 + a], q2 = pairOf[bgc * 16 + b], q3 = pairOf[bgc * 16 + c];
                        int q4 = pairOf[a * 16 + b], q5 = pairOf[a * 16 + c], q6 = pairOf[b * 16 + c];
                        double e = 0;
                        for (int p = 0; p < 32 && e < best; p++)
                        {
                            int o = p * 120;
                            float m = seg[o + q1];
                            if (seg[o + q2] < m) m = seg[o + q2];
                            if (seg[o + q3] < m) m = seg[o + q3];
                            if (seg[o + q4] < m) m = seg[o + q4];
                            if (seg[o + q5] < m) m = seg[o + q5];
                            if (seg[o + q6] < m) m = seg[o + q6];
                            e += m;
                        }
                        if (e < best - 1e-6) { best = e; ba = a; bb = b; bc = c; }
                    }
            cols[cell * 4] = bgc; cols[cell * 4 + 1] = ba; cols[cell * 4 + 2] = bb; cols[cell * 4 + 3] = bc;
        }

        // each pixel: one of its cell's 4 colours (0 background, 1 and 2 screen memory, 3 colour memory)
        var idx = new byte[W * H];
        float[] work = dither == 2 ? (float[])img.Clone() : img;
        for (int y = 0; y < H; y++)
        {
            bool rev = dither == 2 && (y & 1) == 1;
            for (int n = 0; n < W; n++)
            {
                int x = rev ? W - 1 - n : n;
                int cell = (y >> 3) * 40 + (x >> 2), k = (y * W + x) * 3;
                float vr = work[k], vg = work[k + 1], vb = work[k + 2];
                int pick = 0;
                if (dither == 1)
                {
                    float bestD = float.MaxValue, bestT = 0;
                    int bi = 0, bj = 0;
                    for (int i = 0; i < 4; i++)
                        for (int j = i + 1; j < 4; j++)
                        {
                            int ci = cols[cell * 4 + i], cj = cols[cell * 4 + j];
                            float t;
                            float d = SegDist(vr, vg, vb, pr[ci], pg[ci], pb[ci], pr[cj], pg[cj], pb[cj], out t);
                            if (d < bestD - 1e-6f) { bestD = d; bestT = t; bi = i; bj = j; }
                        }
                    pick = bestT > (Bayer8[(y & 7) * 8 + (x & 7)] + 0.5f) / 64f ? bj : bi;
                }
                else
                {
                    float bd = float.MaxValue;
                    for (int i = 0; i < 4; i++)
                    {
                        int ci = cols[cell * 4 + i];
                        float d = Dist(vr, vg, vb, pr[ci], pg[ci], pb[ci]);
                        if (d < bd) { bd = d; pick = i; }
                    }
                    if (dither == 2)
                    {
                        int c = cols[cell * 4 + pick];
                        Diffuse(work, W, H, x, y, rev ? -1 : 1, vr - pr[c], vg - pg[c], vb - pb[c]);
                    }
                }
                idx[y * W + x] = (byte)pick;
            }
        }

        // the file: load address, bitmap (8 bytes per cell, 4 pixels per byte), screen memory, colour memory, background
        var d2 = new byte[10003];
        d2[0] = 0x00; d2[1] = 0x60;
        shown = new int[W * H];
        for (int cell = 0; cell < 1000; cell++)
        {
            int cx = (cell % 40) * 4, cy = (cell / 40) * 8;
            for (int r = 0; r < 8; r++)
            {
                int v = 0;
                for (int p = 0; p < 4; p++)
                {
                    int i = (cy + r) * W + cx + p;
                    v |= idx[i] << (6 - 2 * p);
                    shown[i] = pal[cols[cell * 4 + idx[i]]];
                }
                d2[2 + cell * 8 + r] = (byte)v;
            }
            d2[8002 + cell] = (byte)((cols[cell * 4 + 1] << 4) | cols[cell * 4 + 2]);
            d2[9002 + cell] = (byte)cols[cell * 4 + 3];
        }
        d2[10002] = (byte)bgc;
        return d2;
    }

    // ---------------------------------------------------------------- pictures with their own palette (Atari ST, Amiga)

    static int[][] stLevels, amigaLevels;                 // [channel][hardware level] -> the 8-bit value RECOIL shows

    // the ST's 8 levels per channel, read from RECOIL: a Degas picture with 8 grey palette entries side by side
    static int[][] StLevels()
    {
        lock (palSync)
        {
            if (stLevels != null) return stLevels;
            var d = new byte[32034];
            for (int v = 0; v < 8; v++) { d[2 + v * 2] = (byte)v; d[3 + v * 2] = (byte)((v << 4) | v); }
            for (int y = 0; y < 200; y++)
                for (int g = 0; g < 8; g++)                                     // 16-pixel group g in colour g
                    for (int pl = 0; pl < 4; pl++)
                        if (((g >> pl) & 1) != 0) { d[34 + y * 160 + g * 8 + pl * 2] = 0xFF; d[35 + y * 160 + g * 8 + pl * 2] = 0xFF; }
            stLevels = LevelsFrom("palette.pi1", d, 320, 200, 8, 16);
            return stLevels;
        }
    }

    // the Amiga's 16 levels per channel, read from RECOIL: an IFF picture with 16 grey palette entries side by side
    static int[][] AmigaLevels()
    {
        lock (palSync)
        {
            if (amigaLevels != null) return amigaLevels;
            var lv = new int[16];
            for (int v = 0; v < 16; v++) lv[v] = v;
            var idx = new byte[320 * 16];
            for (int i = 0; i < idx.Length; i++) idx[i] = (byte)((i % 320) / 20);
            amigaLevels = LevelsFrom("palette.iff", IffBytes(320, 16, 4, idx, new[] { lv, lv, lv }), 320, 16, 16, 20);
            return amigaLevels;
        }
    }

    // colour v of a test picture fills columns v * step .. v * step + step - 1
    static int[][] LevelsFrom(string name, byte[] data, int w, int h, int n, int step)
    {
        int rw, rh;
        int[] px = RecoilPixels(name, data, out rw, out rh);
        if (rw % w != 0 || rh % h != 0) throw new InvalidDataException("RECOIL shows " + Path.GetExtension(name) + " pictures in an unexpected size.");
        int sx = rw / w, sy = rh / h;
        var lv = new[] { new int[n], new int[n], new int[n] };
        for (int v = 0; v < n; v++)
        {
            int c = px[(h / 2 * sy) * rw + (v * step + step / 2) * sx];
            lv[0][v] = (c >> 16) & 255; lv[1][v] = (c >> 8) & 255; lv[2][v] = c & 255;
        }
        return lv;
    }

    // A palette of at most n colours for the picture: median cut (split the box with the widest spread at its
    // median), then 6 rounds of k-means, then each colour snapped to the machine's levels; duplicates are merged.
    // Returns the level index of each colour's red, green and blue: [colour][channel].
    static List<int[]> FreePalette(float[] img, int n, int[][] levels)
    {
        int count = img.Length / 3;
        float[] sw = { (float)Math.Sqrt(WR), (float)Math.Sqrt(WG), (float)Math.Sqrt(WB) };
        var all = new int[count];
        for (int i = 0; i < count; i++) all[i] = i;
        var boxes = new List<int[]> { all };
        while (boxes.Count < n)
        {
            int pick = -1, pickCh = 0;
            float widest = 0;
            for (int bi = 0; bi < boxes.Count; bi++)
            {
                int[] b = boxes[bi];
                if (b.Length < 2) continue;
                for (int ch = 0; ch < 3; ch++)
                {
                    float lo = float.MaxValue, hi = float.MinValue;
                    foreach (int i in b) { float v = img[i * 3 + ch]; if (v < lo) lo = v; if (v > hi) hi = v; }
                    if ((hi - lo) * sw[ch] > widest) { widest = (hi - lo) * sw[ch]; pick = bi; pickCh = ch; }
                }
            }
            if (pick < 0) break;                                               // every box is one colour already
            int[] box = boxes[pick];
            var keys = new float[box.Length];
            for (int i = 0; i < box.Length; i++) keys[i] = img[box[i] * 3 + pickCh];
            Array.Sort(keys, box);
            int half = box.Length / 2;
            var lowHalf = new int[half];
            var highHalf = new int[box.Length - half];
            Array.Copy(box, 0, lowHalf, 0, half);
            Array.Copy(box, half, highHalf, 0, box.Length - half);
            boxes[pick] = lowHalf;
            boxes.Insert(pick + 1, highHalf);
        }
        int k = boxes.Count;
        var cr = new float[k]; var cg = new float[k]; var cb = new float[k];
        for (int c = 0; c < k; c++)
        {
            double sr = 0, sg = 0, sb = 0;
            foreach (int i in boxes[c]) { sr += img[i * 3]; sg += img[i * 3 + 1]; sb += img[i * 3 + 2]; }
            cr[c] = (float)(sr / boxes[c].Length); cg[c] = (float)(sg / boxes[c].Length); cb[c] = (float)(sb / boxes[c].Length);
        }
        var sumR = new double[k]; var sumG = new double[k]; var sumB = new double[k]; var num = new int[k];
        for (int round = 0; round < 6; round++)
        {
            Array.Clear(sumR, 0, k); Array.Clear(sumG, 0, k); Array.Clear(sumB, 0, k); Array.Clear(num, 0, k);
            for (int i = 0; i < count; i++)
            {
                int c = Nearest(img[i * 3], img[i * 3 + 1], img[i * 3 + 2], cr, cg, cb, k);
                sumR[c] += img[i * 3]; sumG[c] += img[i * 3 + 1]; sumB[c] += img[i * 3 + 2]; num[c]++;
            }
            for (int c = 0; c < k; c++)
                if (num[c] > 0) { cr[c] = (float)(sumR[c] / num[c]); cg[c] = (float)(sumG[c] / num[c]); cb[c] = (float)(sumB[c] / num[c]); }
        }
        var result = new List<int[]>();
        var seen = new HashSet<int>();
        for (int c = 0; c < k; c++)
        {
            var q = new[] { Snap(cr[c], levels[0]), Snap(cg[c], levels[1]), Snap(cb[c], levels[2]) };
            if (seen.Add((q[0] << 16) | (q[1] << 8) | q[2])) result.Add(q);
        }
        return result;
    }

    static int Snap(float v, int[] levels)
    {
        int best = 0;
        for (int i = 1; i < levels.Length; i++) if (Math.Abs(levels[i] - v) < Math.Abs(levels[best] - v)) best = i;
        return best;
    }

    // each pixel's palette index: nearest colour, the ordered pattern (an offset per position, amp = its strength, about
    // the gap between the machine's levels; pixels that already match a palette colour closely are left alone, so flat
    // areas and borders stay clean) or error diffusion
    static byte[] FreeDither(float[] img, int w, int h, float[] pr, float[] pg, float[] pb, int n, int dither, float amp = 40f)
    {
        var idx = new byte[w * h];
        float[] work = dither == 2 ? (float[])img.Clone() : img;
        for (int y = 0; y < h; y++)
        {
            bool rev = dither == 2 && (y & 1) == 1;
            for (int m = 0; m < w; m++)
            {
                int x = rev ? w - 1 - m : m, k = (y * w + x) * 3;
                float vr = work[k], vg = work[k + 1], vb = work[k + 2];
                if (dither == 1)
                {
                    int c0 = Nearest(vr, vg, vb, pr, pg, pb, n);
                    if (Dist(vr, vg, vb, pr[c0], pg[c0], pb[c0]) > 12)
                    {
                        float off = ((Bayer8[(y & 7) * 8 + (x & 7)] + 0.5f) / 64f - 0.5f) * amp;
                        vr += off; vg += off; vb += off;
                    }
                }
                int c = Nearest(vr, vg, vb, pr, pg, pb, n);
                if (dither == 2) Diffuse(work, w, h, x, y, rev ? -1 : 1, vr - pr[c], vg - pg[c], vb - pb[c]);
                idx[y * w + x] = (byte)c;
            }
        }
        return idx;
    }

    // the palette's colours as RECOIL shows them, and the picture's pixels as indexes into it
    static byte[] PalettePicture(Bitmap src, bool fill, int dither, int w, int h, int n, int[][] levels, out List<int[]> lv, out int[] shownPal)
    {
        float[] img = Fit(src, w, h, fill, 1);
        lv = FreePalette(img, n, levels);
        int k = lv.Count;
        var pr = new float[k]; var pg = new float[k]; var pb = new float[k];
        shownPal = new int[k];
        for (int c = 0; c < k; c++)
        {
            pr[c] = levels[0][lv[c][0]]; pg[c] = levels[1][lv[c][1]]; pb[c] = levels[2][lv[c][2]];
            shownPal[c] = Argb(pr[c], pg[c], pb[c]);
        }
        return FreeDither(img, w, h, pr, pg, pb, k, dither);
    }

    // ---------------------------------------------------------------- Commodore 64 (Doodle hires)

    // The .dd bytes for a picture, and the picture as that file shows it (320 x 200, 0xFFRRGGBB): two of the 16
    // colours for each 8 x 8 cell, held in screen memory (low half: pixels off, high half: pixels on).
    public static byte[] ToDoodle(Bitmap src, bool fill, int dither, out int[] shown)
    {
        const int W = 320, H = 200;
        int[] pal = C64Palette();
        var pr = new float[16]; var pg = new float[16]; var pb = new float[16];
        for (int c = 0; c < 16; c++) { pr[c] = (pal[c] >> 16) & 255; pg[c] = (pal[c] >> 8) & 255; pb[c] = pal[c] & 255; }
        float[] img = Fit(src, W, H, fill, 1);
        var off = new int[1000]; var on = new int[1000];
        bool[] set = TwoColourCells(img, W, H, pr, pg, pb, 16, dither, off, on);
        var d = new byte[9218];
        d[0] = 0x00; d[1] = 0x5C;                                              // load address $5C00
        for (int cell = 0; cell < 1000; cell++) d[2 + cell] = (byte)((on[cell] << 4) | off[cell]);
        shown = new int[W * H];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++)
            {
                int cell = (y >> 3) * 40 + (x >> 3);
                bool o = set[y * W + x] && on[cell] != off[cell];
                if (o) d[1026 + (y >> 3) * 320 + (x & ~7) + (y & 7)] |= (byte)(0x80 >> (x & 7));
                shown[y * W + x] = pal[o ? on[cell] : off[cell]];
            }
        return d;
    }

    // For pictures with two colours per 8 x 8 cell (W and H multiples of 8): each cell's pair of palette colours
    // (off, on: the pair whose mixes best cover its pixels) and whether each pixel shows the second one.
    static bool[] TwoColourCells(float[] img, int W, int H, float[] pr, float[] pg, float[] pb, int n, int dither, int[] off, int[] on)
    {
        int cols = W / 8, cells = cols * (H / 8);
        float tt;
        for (int cell = 0; cell < cells; cell++)
        {
            int cx = (cell % cols) * 8, cy = (cell / cols) * 8;
            double best = double.MaxValue;
            for (int a = 0; a < n; a++)
                for (int b = a; b < n; b++)
                {
                    double e = 0;
                    for (int y = cy; y < cy + 8 && e < best; y++)
                        for (int x = cx; x < cx + 8; x++)
                        {
                            int k = (y * W + x) * 3;
                            e += SegDist(img[k], img[k + 1], img[k + 2], pr[a], pg[a], pb[a], pr[b], pg[b], pb[b], out tt);
                        }
                    if (e < best - 1e-6) { best = e; off[cell] = a; on[cell] = b; }
                }
        }
        var set = new bool[W * H];
        float[] work = dither == 2 ? (float[])img.Clone() : img;
        for (int y = 0; y < H; y++)
        {
            bool rev = dither == 2 && (y & 1) == 1;
            for (int m = 0; m < W; m++)
            {
                int x = rev ? W - 1 - m : m, cell = (y >> 3) * cols + (x >> 3), a = off[cell], b = on[cell], k = (y * W + x) * 3;
                float vr = work[k], vg = work[k + 1], vb = work[k + 2];
                bool o;
                if (dither == 1)
                {
                    float t;
                    SegDist(vr, vg, vb, pr[a], pg[a], pb[a], pr[b], pg[b], pb[b], out t);
                    o = t > (Bayer8[(y & 7) * 8 + (x & 7)] + 0.5f) / 64f;
                }
                else
                {
                    o = Dist(vr, vg, vb, pr[b], pg[b], pb[b]) < Dist(vr, vg, vb, pr[a], pg[a], pb[a]);
                    if (dither == 2) { int c = o ? b : a; Diffuse(work, W, H, x, y, rev ? -1 : 1, vr - pr[c], vg - pg[c], vb - pb[c]); }
                }
                set[y * W + x] = o;
            }
        }
        return set;
    }

    // ---------------------------------------------------------------- Amstrad CPC (.scr, 16 KB screen)

    static int[][] cpcLevels;                                // [channel][0..2] -> the 8-bit value RECOIL shows

    // A 16 KB CPC screen with an AMSDOS header (a binary file loading at &C000), the way RECOIL reads it: the mode
    // and the firmware colour numbers sit in the unused bytes after the third character line (offset 6096).
    // idx = palette index per pixel, w = 160 (mode 0) or 320 (mode 1), fw = firmware colours 0..26.
    static byte[] CpcScreen(int mode, int[] fw, byte[] idx, int w)
    {
        var d = new byte[128 + 16384];
        for (int y = 0; y < 200; y++)
        {
            int line = 128 + ((y & 7) << 11) + (y >> 3) * 80;
            for (int x = 0; x < w; x++)
            {
                int i = idx[y * w + x];
                if (mode == 1)
                {
                    int p = x & 3;
                    d[line + (x >> 2)] |= (byte)((((i >> 1) & 1) << (3 - p)) | ((i & 1) << (7 - p)));
                }
                else
                {
                    int v = ((i & 1) << 6) | (((i >> 2) & 1) << 4) | (((i >> 1) & 1) << 2) | ((i >> 3) & 1);
                    d[line + (x >> 1)] |= (byte)(v << (1 - (x & 1)));
                }
            }
        }
        int n = mode == 0 ? 16 : 4;
        d[128 + 6096] = (byte)mode;
        for (int c = 0; c < n; c++) d[128 + 6097 + c] = (byte)(c < fw.Length ? fw[c] : fw[0]);
        CpcHeader(d, "PICTURE");
        return d;
    }

    // the AMSDOS header: user 0, the name in 8.3 form, a binary file of 16384 bytes loading at &C000, its checksum
    static void CpcHeader(byte[] d, string stem)
    {
        var name = new System.Text.StringBuilder();
        foreach (char ch in stem.ToUpperInvariant())
            if (name.Length < 8 && ((ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9'))) name.Append(ch);
        if (name.Length == 0) name.Append("PICTURE");
        string n83 = name.ToString().PadRight(8) + "SCR";
        Array.Clear(d, 0, 128);
        for (int i = 0; i < 11; i++) d[1 + i] = (byte)n83[i];
        d[18] = 2;                                                             // binary
        d[21] = 0x00; d[22] = 0xC0;                                            // load address &C000
        d[24] = 0x00; d[25] = 0x40;                                            // length 16384
        d[64] = 0x00; d[65] = 0x40; d[66] = 0;
        int sum = 0;
        for (int i = 0; i < 67; i++) sum += d[i];
        d[67] = (byte)sum; d[68] = (byte)(sum >> 8);
    }

    // the CPC's three levels per channel, read from RECOIL: a mode 0 screen whose columns show firmware colours
    // 0, 1, 2 (blue), 3, 6 (red), 9 and 18 (green)
    static int[][] CpcLevels()
    {
        lock (palSync)
        {
            if (cpcLevels != null) return cpcLevels;
            int[] fw = { 0, 1, 2, 3, 6, 9, 18 };
            var idx = new byte[160 * 200];
            for (int y = 0; y < 200; y++)
                for (int x = 0; x < 140; x++) idx[y * 160 + x] = (byte)(x / 20);
            int w, h;
            int[] px = RecoilPixels("palette.scr", CpcScreen(0, fw, idx, 160), out w, out h);
            if (w % 160 != 0 || h % 200 != 0) throw new InvalidDataException("RECOIL shows Amstrad CPC screens in an unexpected size.");
            int sx = w / 160, sy = h / 200;
            Func<int, int> col = delegate (int c) { return px[(100 * sy) * w + (c * 20 + 10) * sx]; };
            var lv = new[] { new int[3], new int[3], new int[3] };
            lv[2][0] = col(0) & 255; lv[2][1] = col(1) & 255; lv[2][2] = col(2) & 255;
            lv[0][0] = (col(0) >> 16) & 255; lv[0][1] = (col(3) >> 16) & 255; lv[0][2] = (col(4) >> 16) & 255;
            lv[1][0] = (col(0) >> 8) & 255; lv[1][1] = (col(5) >> 8) & 255; lv[1][2] = (col(6) >> 8) & 255;
            cpcLevels = lv;
            return lv;
        }
    }

    // The CPC .scr bytes for a picture (mode 0: 160 x 200 wide pixels, 16 colours; mode 1: 320 x 200, 4 colours;
    // each chosen from the 27), and the picture as that file shows it (0xFFRRGGBB).
    public static byte[] ToCpc(Bitmap src, bool fill, int dither, int mode, out int[] shown)
    {
        int W = mode == 0 ? 160 : 320, H = 200, n = mode == 0 ? 16 : 4;
        int[][] levels = CpcLevels();
        float[] img = Fit(src, W, H, fill, mode == 0 ? 2 : 1);
        var fw = new List<int>();
        foreach (int[] q in FreePalette(img, n, levels)) fw.Add(q[1] * 9 + q[0] * 3 + q[2]);   // firmware colour number
        // with so few colours to pick from, try swapping each one for another of the 27 while that fits better
        var sample = new float[Math.Min(W * H, 4000) * 3];
        int count = sample.Length / 3;
        for (int i = 0; i < count; i++)
        {
            int k = (int)((long)i * (W * H) / count) * 3;
            sample[i * 3] = img[k]; sample[i * 3 + 1] = img[k + 1]; sample[i * 3 + 2] = img[k + 2];
        }
        var all = new float[3][];
        for (int ch = 0; ch < 3; ch++) all[ch] = new float[27];
        for (int c = 0; c < 27; c++) { all[0][c] = levels[0][c / 3 % 3]; all[1][c] = levels[1][c / 9]; all[2][c] = levels[2][c % 3]; }
        double err = CpcError(sample, fw, all);
        for (bool better = true; better; )
        {
            better = false;
            for (int s = 0; s < fw.Count; s++)
                for (int c = 0; c < 27; c++)
                {
                    if (fw.Contains(c)) continue;
                    int old = fw[s];
                    fw[s] = c;
                    double e = CpcError(sample, fw, all);
                    if (e < err - 1e-6) { err = e; better = true; }
                    else fw[s] = old;
                }
        }
        int k2 = fw.Count;
        var pr = new float[k2]; var pg = new float[k2]; var pb = new float[k2];
        var shownPal = new int[k2];
        for (int c = 0; c < k2; c++)
        {
            pr[c] = all[0][fw[c]]; pg[c] = all[1][fw[c]]; pb[c] = all[2][fw[c]];
            shownPal[c] = Argb(pr[c], pg[c], pb[c]);
        }
        float amp = Math.Max(40f, (levels[1][2] - levels[1][0]) / 2f);       // the pattern spans one level step
        byte[] idx = FreeDither(img, W, H, pr, pg, pb, k2, dither, amp);
        shown = new int[W * H];
        for (int i = 0; i < shown.Length; i++) shown[i] = shownPal[idx[i]];
        return CpcScreen(mode, fw.ToArray(), idx, W);
    }

    // how far the sample pixels are, in all, from their nearest colour of fw
    static double CpcError(float[] sample, List<int> fw, float[][] all)
    {
        double e = 0;
        for (int i = 0; i < sample.Length; i += 3)
        {
            float best = float.MaxValue;
            foreach (int c in fw)
            {
                float d = Dist(sample[i], sample[i + 1], sample[i + 2], all[0][c], all[1][c], all[2][c]);
                if (d < best) best = d;
            }
            e += best;
        }
        return e;
    }

    // ---------------------------------------------------------------- Atari ST (Degas .pi1)

    // The .pi1 bytes for a picture, and the picture as that file shows it (320 x 200, 0xFFRRGGBB).
    public static byte[] ToDegas(Bitmap src, bool fill, int dither, out int[] shown)
    {
        List<int[]> lv;
        int[] shownPal;
        byte[] idx = PalettePicture(src, fill, dither, 320, 200, 16, StLevels(), out lv, out shownPal);
        var d = new byte[32034];                                               // resolution word 0: low resolution
        for (int c = 0; c < lv.Count; c++)
        {
            d[2 + c * 2] = (byte)lv[c][0];                                     // 0x0RGB, 3 bits per channel
            d[3 + c * 2] = (byte)((lv[c][1] << 4) | lv[c][2]);
        }
        shown = new int[320 * 200];
        for (int y = 0; y < 200; y++)
            for (int x = 0; x < 320; x++)
            {
                int c = idx[y * 320 + x];
                shown[y * 320 + x] = shownPal[c];
                int at = 34 + y * 160 + (x >> 4) * 8, bit = 0x8000 >> (x & 15);   // 16 pixels: 4 words, one per bit plane
                for (int pl = 0; pl < 4; pl++)
                    if (((c >> pl) & 1) != 0) { d[at + pl * 2] |= (byte)(bit >> 8); d[at + pl * 2 + 1] |= (byte)bit; }
            }
        return d;
    }

    // ---------------------------------------------------------------- Amiga (IFF ILBM)

    // The .iff bytes for a picture, and the picture as that file shows it (320 x 256, 0xFFRRGGBB).
    public static byte[] ToIff(Bitmap src, bool fill, int dither, out int[] shown)
    {
        List<int[]> lv;
        int[] shownPal;
        byte[] idx = PalettePicture(src, fill, dither, 320, 256, 32, AmigaLevels(), out lv, out shownPal);
        var lr = new int[32]; var lg = new int[32]; var lb = new int[32];
        for (int c = 0; c < lv.Count; c++) { lr[c] = lv[c][0]; lg[c] = lv[c][1]; lb[c] = lv[c][2]; }
        shown = new int[320 * 256];
        for (int i = 0; i < shown.Length; i++) shown[i] = shownPal[idx[i]];
        return IffBytes(320, 256, 5, idx, new[] { lr, lg, lb });
    }

    // An uncompressed IFF ILBM picture: w x h, the given number of bit planes, palette levels (0..15 per channel,
    // written as 8-bit values v * 17), and pixels as palette indexes
    static byte[] IffBytes(int w, int h, int planes, byte[] idx, int[][] lv)
    {
        int rowBytes = (w + 15) / 16 * 2, colours = 1 << planes;
        var body = new byte[rowBytes * planes * h];
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                int c = idx[y * w + x];
                for (int pl = 0; pl < planes; pl++)
                    if (((c >> pl) & 1) != 0) body[(y * planes + pl) * rowBytes + (x >> 3)] |= (byte)(0x80 >> (x & 7));
            }
        var bmhd = new byte[20];
        PutBE(bmhd, 0, w, 2); PutBE(bmhd, 2, h, 2);                             // size; position 0, 0
        bmhd[8] = (byte)planes;                                                // no mask, no compression
        bmhd[14] = 10; bmhd[15] = 11;                                          // pixel aspect of a PAL low-resolution screen
        PutBE(bmhd, 16, w, 2); PutBE(bmhd, 18, h, 2);                          // page size
        var cmap = new byte[colours * 3];
        for (int c = 0; c < colours && c < lv[0].Length; c++)
        {
            cmap[c * 3] = (byte)(lv[0][c] * 17); cmap[c * 3 + 1] = (byte)(lv[1][c] * 17); cmap[c * 3 + 2] = (byte)(lv[2][c] * 17);
        }
        var ms = new MemoryStream();
        ms.Write(new byte[] { (byte)'F', (byte)'O', (byte)'R', (byte)'M', 0, 0, 0, 0, (byte)'I', (byte)'L', (byte)'B', (byte)'M' }, 0, 12);
        Chunk(ms, "BMHD", bmhd); Chunk(ms, "CMAP", cmap); Chunk(ms, "BODY", body);
        byte[] r = ms.ToArray();
        PutBE(r, 4, r.Length - 8, 4);                                          // the FORM's size
        return r;
    }

    static void Chunk(MemoryStream ms, string id, byte[] data)
    {
        var head = new byte[8];
        for (int i = 0; i < 4; i++) head[i] = (byte)id[i];
        PutBE(head, 4, data.Length, 4);
        ms.Write(head, 0, 8);
        ms.Write(data, 0, data.Length);
        if ((data.Length & 1) != 0) ms.WriteByte(0);                           // chunks are padded to an even length
    }

    static void PutBE(byte[] d, int at, int v, int n) { for (int i = 0; i < n; i++) d[at + i] = (byte)(v >> (8 * (n - 1 - i))); }

    // ---------------------------------------------------------------- MSX (Screen 2 and Screen 8)

    // An MSX BASIC "BSAVE" file of video memory: 0xFE, start, end, start address (little-endian), then the bytes
    static byte[] Bsave(byte[] vram)
    {
        var d = new byte[7 + vram.Length];
        d[0] = 0xFE;
        int end = vram.Length - 1;
        d[3] = (byte)end; d[4] = (byte)(end >> 8);                              // start 0, end, run address 0
        Buffer.BlockCopy(vram, 0, d, 7, vram.Length);
        return d;
    }

    static int[] msxPal, sc8Pal;

    // video memory for Screen 2 with the usual tables: patterns 0x0000, names 0x1800 (0..255 in each third),
    // sprites switched off at 0x1B00, colours 0x2000
    static byte[] Sc2Vram()
    {
        var v = new byte[0x3800];
        for (int i = 0; i < 768; i++) v[0x1800 + i] = (byte)i;
        v[0x1B00] = 0xD0;                                                      // no sprites
        return v;
    }

    // the TMS9918's colours 1..15, read from RECOIL: a Screen 2 picture whose first 15 characters each show one colour
    static int[] MsxPalette()
    {
        lock (palSync)
        {
            if (msxPal != null) return msxPal;
            byte[] v = Sc2Vram();
            for (int c = 1; c < 16; c++)
                for (int r = 0; r < 8; r++) { v[c * 8 + r] = 0xFF; v[0x2000 + c * 8 + r] = (byte)(c << 4); }
            int w, h;
            int[] px = RecoilPixels("palette.sc2", Bsave(v), out w, out h);
            if (w % 256 != 0 || h % 192 != 0) throw new InvalidDataException("RECOIL shows MSX Screen 2 pictures in an unexpected size.");
            int sx = w / 256, sy = h / 192;
            var pal = new int[16];
            for (int c = 1; c < 16; c++) pal[c] = px[(4 * sy) * w + (c * 8 + 4) * sx] | unchecked((int)0xFF000000);
            pal[0] = pal[1];                                                    // 0 is transparent; never used
            msxPal = pal;
            return pal;
        }
    }

    // The .sc2 bytes for a picture, and the picture as that file shows it (256 x 192, 0xFFRRGGBB).
    public static byte[] ToSc2(Bitmap src, bool fill, int dither, out int[] shown)
    {
        const int W = 256, H = 192;
        int[] pal = MsxPalette();
        var pr = new float[16]; var pg = new float[16]; var pb = new float[16];
        for (int c = 0; c < 16; c++) { pr[c] = (pal[c] >> 16) & 255; pg[c] = (pal[c] >> 8) & 255; pb[c] = pal[c] & 255; }
        float[] img = Fit(src, W, H, fill, 1);
        var back = new int[H * 32]; var fore = new int[H * 32];               // per 8 x 1 strip
        float tt;
        for (int y = 0; y < H; y++)
            for (int sx = 0; sx < 32; sx++)
            {
                double best = double.MaxValue;
                for (int a = 1; a < 16; a++)
                    for (int b = a; b < 16; b++)
                    {
                        double e = 0;
                        for (int p = 0; p < 8 && e < best; p++)
                        {
                            int k = (y * W + sx * 8 + p) * 3;
                            e += SegDist(img[k], img[k + 1], img[k + 2], pr[a], pg[a], pb[a], pr[b], pg[b], pb[b], out tt);
                        }
                        if (e < best - 1e-6) { best = e; back[y * 32 + sx] = a; fore[y * 32 + sx] = b; }
                    }
            }
        var on = new bool[W * H];
        float[] work = dither == 2 ? (float[])img.Clone() : img;
        for (int y = 0; y < H; y++)
        {
            bool rev = dither == 2 && (y & 1) == 1;
            for (int n = 0; n < W; n++)
            {
                int x = rev ? W - 1 - n : n, k = (y * W + x) * 3, a = back[y * 32 + (x >> 3)], b = fore[y * 32 + (x >> 3)];
                float vr = work[k], vg = work[k + 1], vb = work[k + 2];
                bool o;
                if (dither == 1)
                {
                    float t;
                    SegDist(vr, vg, vb, pr[a], pg[a], pb[a], pr[b], pg[b], pb[b], out t);
                    o = t > (Bayer8[(y & 7) * 8 + (x & 7)] + 0.5f) / 64f;
                }
                else
                {
                    o = Dist(vr, vg, vb, pr[b], pg[b], pb[b]) < Dist(vr, vg, vb, pr[a], pg[a], pb[a]);
                    if (dither == 2) { int c = o ? b : a; Diffuse(work, W, H, x, y, rev ? -1 : 1, vr - pr[c], vg - pg[c], vb - pb[c]); }
                }
                on[y * W + x] = o;
            }
        }
        byte[] v = Sc2Vram();
        shown = new int[W * H];
        for (int y = 0; y < H; y++)
            for (int sx = 0; sx < 32; sx++)
            {
                int ch = (y >> 6) * 256 + ((y >> 3) & 7) * 32 + sx, a = back[y * 32 + sx], b = fore[y * 32 + sx], bits = 0;
                for (int p = 0; p < 8; p++)
                {
                    bool o = on[y * W + sx * 8 + p] && a != b;
                    if (o) bits |= 0x80 >> p;
                    shown[y * W + sx * 8 + p] = pal[o ? b : a];
                }
                v[ch * 8 + (y & 7)] = (byte)bits;
                v[0x2000 + ch * 8 + (y & 7)] = (byte)((b << 4) | a);
            }
        return Bsave(v);
    }

    // the 256 Screen 8 colours, read from RECOIL: a picture whose columns show the 256 byte values
    static int[] Sc8Palette()
    {
        lock (palSync)
        {
            if (sc8Pal != null) return sc8Pal;
            var v = new byte[256 * 212];
            for (int i = 0; i < v.Length; i++) v[i] = (byte)(i & 255);
            int w, h;
            int[] px = RecoilPixels("palette.sc8", Bsave(v), out w, out h);
            if (w % 256 != 0 || h % 212 != 0) throw new InvalidDataException("RECOIL shows MSX Screen 8 pictures in an unexpected size.");
            int sx = w / 256, sy = h / 212;
            var pal = new int[256];
            for (int c = 0; c < 256; c++) pal[c] = px[(100 * sy) * w + c * sx] | unchecked((int)0xFF000000);
            sc8Pal = pal;
            return pal;
        }
    }

    // The .sc8 bytes for a picture, and the picture as that file shows it (256 x 212, 0xFFRRGGBB).
    public static byte[] ToSc8(Bitmap src, bool fill, int dither, out int[] shown)
    {
        int[] pal = Sc8Palette();
        var pr = new float[256]; var pg = new float[256]; var pb = new float[256];
        for (int c = 0; c < 256; c++) { pr[c] = (pal[c] >> 16) & 255; pg[c] = (pal[c] >> 8) & 255; pb[c] = pal[c] & 255; }
        float[] img = Fit(src, 256, 212, fill, 1);
        byte[] idx = FreeDither(img, 256, 212, pr, pg, pb, 256, dither);     // the byte is the colour
        shown = new int[256 * 212];
        for (int i = 0; i < idx.Length; i++) shown[i] = pal[idx[i]];
        return Bsave(idx);
    }

    // ---------------------------------------------------------------- converting files

    // The converted file's bytes, the picture it shows and its size. Throws with a reason.
    // pxw = how many times as wide as tall the format's pixels are shown (2 for C64 multicolour and CPC mode 0)
    static byte[] Render(Bitmap src, ConvertOptions o, out int[] shown, out int w, out int h, out int pxw)
    {
        pxw = 1;
        switch (o.Format)
        {
            case 1: w = 160; h = 200; pxw = 2; return ToKoala(src, o.Fill, o.Dither, out shown);
            case 2: w = 320; h = 200; return ToDoodle(src, o.Fill, o.Dither, out shown);
            case 3: w = 160; h = 200; pxw = 2; return ToCpc(src, o.Fill, o.Dither, 0, out shown);
            case 4: w = 320; h = 200; return ToCpc(src, o.Fill, o.Dither, 1, out shown);
            case 5: w = 320; h = 200; return ToDegas(src, o.Fill, o.Dither, out shown);
            case 6: w = 320; h = 256; return ToIff(src, o.Fill, o.Dither, out shown);
            case 7: w = 256; h = 192; return ToSc2(src, o.Fill, o.Dither, out shown);
            case 8: w = 256; h = 212; return ToSc8(src, o.Fill, o.Dither, out shown);
            default: w = 256; h = 192; return ToZx(src, o.Fill, o.Dither, out shown);
        }
    }

    // Converts one picture into a new file in o.DestDir (never overwrites: a name that is taken gets a number) and
    // returns its path. The file is checked by RECOIL first, then written under a temporary name, read back and only
    // then given its name. Throws with a readable reason. Any thread.
    public static string ConvertFile(string path, ConvertOptions o)
    {
        if ((File.GetAttributes(path) & Util.CloudMask) != 0) throw new IOException("cloud-only, not stored on this PC.");
        byte[] data;
        int[] shown;
        int w, h, pxw;
        using (Bitmap src = Exporter.Decode(path, 0)) data = Render(src, o, out shown, out w, out h, out pxw);
        string ext = FormatExts[o.Format], stem = Path.GetFileNameWithoutExtension(path);
        bool cpc = o.Format == 3 || o.Format == 4;
        // a CPC screen with a .pal file of the same name beside it would be shown in that file's colours, so such a
        // name is skipped too
        string dest = Path.Combine(o.DestDir, stem + ext);
        for (int i = 2; File.Exists(dest) || Directory.Exists(dest) || (cpc && File.Exists(Path.ChangeExtension(dest, ".pal"))); i++)
            dest = Path.Combine(o.DestDir, stem + " (" + i + ")" + ext);
        if (cpc) CpcHeader(data, Path.GetFileNameWithoutExtension(dest));
        Check(ext, data, shown, w, h);
        string tmp = dest + "." + Guid.NewGuid().ToString("N").Substring(0, 8) + ".tmp";
        try
        {
            File.WriteAllBytes(tmp, data);
            byte[] back = File.ReadAllBytes(tmp);
            if (back.Length != data.Length) throw new IOException("the new file did not read back correctly, so nothing was kept.");
            for (int i = 0; i < back.Length; i++)
                if (back[i] != data[i]) throw new IOException("the new file did not read back correctly, so nothing was kept.");
            File.Move(tmp, dest);                                               // fails rather than overwrite
        }
        catch (Exception)
        {
            try { if (File.Exists(tmp)) File.Delete(tmp); } catch (Exception) { }
            throw;
        }
        return dest;
    }

    // ---------------------------------------------------------------- the dialog

    // Options for converting paths (the first one is previewed); folder = the suggested destination.
    // null = cancelled.
    public static ConvertOptions Ask(IWin32Window owner, List<string> paths, string folder, Action<Form> darkTitle)
    {
        Color panelBg = Color.FromArgb(38, 38, 38), text = Color.Gainsboro, boxBg = Color.FromArgb(52, 52, 52);
        var o = new ConvertOptions { Format = lastFormat, Fill = lastFill, Dither = lastDither, DestDir = folder };
        Bitmap source = null, preview = null;
        string sourceErr = null;
        try { source = Exporter.Decode(paths[0], 0); }
        catch (Exception ex) { sourceErr = Util.Why(ex); }
        try
        {
            using (var f = new Form())
            {
                f.AutoScaleMode = AutoScaleMode.None;
                f.Font = new Font("Segoe UI", 9.5f);
                f.Text = "Convert to a retro format - " + paths.Count + (paths.Count == 1 ? " picture" : " pictures");
                f.StartPosition = FormStartPosition.CenterParent;
                f.FormBorderStyle = FormBorderStyle.FixedDialog;
                f.ShowInTaskbar = false; f.MinimizeBox = false; f.MaximizeBox = false;
                f.BackColor = panelBg; f.ForeColor = text;
                int pad = Util.S(14), colW = Util.S(360), pw = 640, ph = 512;              // room for 2 x 320 x 256
                f.ClientSize = new Size(pad * 3 + colW + pw, pad * 2 + ph + Util.S(78));
                if (darkTitle != null) f.HandleCreated += delegate { darkTitle(f); };

                int y = pad;
                var head = new Label
                {
                    Left = pad, Top = y, Width = colW, Height = Util.S(70), ForeColor = Color.Silver,
                    Text = "Makes a new file for each picture; the originals are never changed. Converting is lossy: each picture " +
                           "is fitted to the machine's screen and reduced to its colours."
                };
                f.Controls.Add(head);
                y += Util.S(76);

                var radios = new List<RadioButton>();
                Func<string, Label> heading = delegate (string s)
                {
                    var l = new Label { Left = pad, Top = y, Width = colW, Height = Util.S(20), Text = s, ForeColor = Color.Silver };
                    f.Controls.Add(l);
                    y += Util.S(22);
                    return l;
                };
                Func<string, bool, RadioButton> radio = delegate (string s, bool on)
                {
                    var r = new RadioButton { Left = pad + Util.S(6), Top = y, Width = colW - Util.S(6), Height = Util.S(22), Text = s, Checked = on,
                                              FlatStyle = FlatStyle.Flat, ForeColor = text, BackColor = panelBg };
                    f.Controls.Add(r);
                    radios.Add(r);
                    y += Util.S(24);
                    return r;
                };

                heading("Format");
                var fmtPanel = new List<RadioButton>();
                foreach (string n in FormatNames) fmtPanel.Add(radio(n, fmtPanel.Count == o.Format));
                y += Util.S(6);
                var fitLabel = heading("Picture");
                RadioButton rFit = null, rFill = null;
                // radio buttons only group within one parent: each group gets its own panel
                var fitGroup = new Panel { Left = 0, Top = y, Width = colW + pad, Height = Util.S(50), BackColor = panelBg };
                f.Controls.Add(fitGroup);
                rFit = new RadioButton { Left = pad + Util.S(6), Top = 0, Width = colW - Util.S(6), Height = Util.S(22), Text = "Whole picture (black borders)", Checked = !o.Fill, FlatStyle = FlatStyle.Flat, ForeColor = text };
                rFill = new RadioButton { Left = pad + Util.S(6), Top = Util.S(24), Width = colW - Util.S(6), Height = Util.S(22), Text = "Fill the screen (edges cropped)", Checked = o.Fill, FlatStyle = FlatStyle.Flat, ForeColor = text };
                fitGroup.Controls.Add(rFit); fitGroup.Controls.Add(rFill);
                y += Util.S(56);
                heading("Dithering (how in-between colours are shown)");
                var ditherGroup = new Panel { Left = 0, Top = y, Width = colW + pad, Height = Util.S(74), BackColor = panelBg };
                f.Controls.Add(ditherGroup);
                var rDither = new RadioButton[DitherNames.Length];
                for (int i = 0; i < DitherNames.Length; i++)
                {
                    rDither[i] = new RadioButton { Left = pad + Util.S(6), Top = i * Util.S(24), Width = colW - Util.S(6), Height = Util.S(22), Text = DitherNames[i],
                                                   Checked = i == o.Dither, FlatStyle = FlatStyle.Flat, ForeColor = text };
                    ditherGroup.Controls.Add(rDither[i]);
                }
                y += Util.S(80);

                heading("Save the new files in");
                var dirBox = new TextBox { Left = pad, Top = y, Width = colW - Util.S(86), Text = folder ?? "", BorderStyle = BorderStyle.FixedSingle, BackColor = boxBg, ForeColor = Color.White };
                var browse = new Button { Left = pad + colW - Util.S(80), Top = y - 1, Width = Util.S(80), Height = dirBox.Height + 2, Text = "Browse...",
                                          FlatStyle = FlatStyle.Flat, BackColor = boxBg, ForeColor = text };
                browse.FlatAppearance.BorderSize = 0;
                browse.Click += delegate
                {
                    using (var d = new FolderBrowserDialog())
                    {
                        d.Description = "Save the converted files in this folder. Existing files are never overwritten.";
                        d.ShowNewFolderButton = true;
                        if (Directory.Exists(dirBox.Text)) d.SelectedPath = dirBox.Text;
                        if (d.ShowDialog(f) == DialogResult.OK) dirBox.Text = d.SelectedPath;
                    }
                };
                f.Controls.Add(dirBox); f.Controls.Add(browse);
                if (dirBox.Bottom + pad > f.ClientSize.Height)                     // the list of formats is long
                    f.ClientSize = new Size(f.ClientSize.Width, dirBox.Bottom + pad);

                // the preview: the first picture as the converted file will show it, twice the size, hard pixel edges
                int px0 = pad * 2 + colW;
                var box = new PictureBox { Left = px0, Top = pad, Width = pw, Height = ph, BackColor = Color.Black, SizeMode = PictureBoxSizeMode.CenterImage };
                var note = new Label { Left = px0, Top = pad + ph + Util.S(6), Width = pw, Height = Util.S(38), ForeColor = Color.Silver };
                f.Controls.Add(box); f.Controls.Add(note);

                Action refresh = delegate
                {
                    o.Fill = rFill.Checked;
                    for (int i = 0; i < rDither.Length; i++) if (rDither[i].Checked) o.Dither = i;
                    if (source == null) { note.Text = "No preview: " + Path.GetFileName(paths[0]) + " could not be opened (" + sourceErr + ")."; return; }
                    try
                    {
                        int[] shown; int w, h, pxw;
                        Render(source, o, out shown, out w, out h, out pxw);
                        int k = Math.Max(1, Math.Min(pw / (w * pxw), ph / h));          // the largest whole size that fits
                        Bitmap pv = Enlarge(shown, w, h, k * pxw, k);
                        box.Image = pv;
                        if (preview != null) preview.Dispose();
                        preview = pv;
                        note.Text = "Preview of " + Path.GetFileName(paths[0]) + " (" + k + " x). Every new file is checked by decoding it with RECOIL before it is kept.";
                    }
                    catch (Exception ex) { note.Text = "No preview: " + Util.Why(ex); }
                };
                EventHandler changed = delegate (object s, EventArgs e) { var r = s as RadioButton; if (r == null || r.Checked) refresh(); };
                rFit.CheckedChanged += changed; rFill.CheckedChanged += changed;
                for (int i = 0; i < fmtPanel.Count; i++)
                {
                    int fi = i;
                    fmtPanel[i].CheckedChanged += delegate { if (fmtPanel[fi].Checked) { o.Format = fi; refresh(); } };
                }
                foreach (RadioButton r in rDither) r.CheckedChanged += changed;

                var ok = new Button { Text = "Convert", DialogResult = DialogResult.OK, Width = Util.S(96), Height = Util.S(30), FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(60, 130, 230), ForeColor = Color.White };
                var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Width = Util.S(96), Height = Util.S(30), FlatStyle = FlatStyle.Flat, BackColor = boxBg, ForeColor = text };
                ok.FlatAppearance.BorderSize = 0; cancel.FlatAppearance.BorderSize = 0;
                cancel.Left = f.ClientSize.Width - pad - cancel.Width; ok.Left = cancel.Left - Util.S(8) - ok.Width;
                ok.Top = cancel.Top = f.ClientSize.Height - pad - ok.Height;
                f.Controls.Add(ok); f.Controls.Add(cancel);
                f.AcceptButton = ok; f.CancelButton = cancel;
                f.FormClosing += delegate (object s, FormClosingEventArgs e)
                {
                    if (f.DialogResult != DialogResult.OK) return;
                    string dir = dirBox.Text.Trim().Trim('"');
                    if (dir.Length == 0 || !Directory.Exists(dir))
                    {
                        MessageBox.Show(f, "Choose a folder that exists for the new files.", "Convert", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        e.Cancel = true;
                        return;
                    }
                    o.DestDir = dir;
                };
                f.Shown += delegate { refresh(); ok.Focus(); };
                if (f.ShowDialog(owner) != DialogResult.OK) return null;
                o.Fill = rFill.Checked;
                for (int i = 0; i < rDither.Length; i++) if (rDither[i].Checked) o.Dither = i;
                for (int i = 0; i < fmtPanel.Count; i++) if (fmtPanel[i].Checked) o.Format = i;
                lastFill = o.Fill; lastDither = o.Dither; lastFormat = o.Format;
                return o;
            }
        }
        finally
        {
            if (source != null) source.Dispose();
            if (preview != null) preview.Dispose();
        }
    }

    // a picture enlarged by whole numbers with hard edges (for the preview)
    static Bitmap Enlarge(int[] px, int w, int h, int fx, int fy)
    {
        fx = Math.Max(1, fx); fy = Math.Max(1, fy);
        int bw = w * fx, bh = h * fy;
        var row = new int[bw];
        var b = new Bitmap(bw, bh, PixelFormat.Format32bppArgb);
        BitmapData bd = b.LockBits(new Rectangle(0, 0, bw, bh), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
        try
        {
            for (int y = 0; y < bh; y++)
            {
                int sy = y / fy;
                for (int x = 0; x < bw; x++) row[x] = px[sy * w + x / fx];
                Marshal.Copy(row, 0, new IntPtr(bd.Scan0.ToInt64() + (long)y * bd.Stride), bw);
            }
        }
        finally { b.UnlockBits(bd); }
        return b;
    }
}
