// RetroGleek - thumbnail items, cache and background decoding service
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

// ====================================================================== thumbnails

sealed class Item
{
    public string Path, Name, Ext;
    public long Size, Stamp, Modified;       // Modified = last write time, UTC ticks
    public bool Offline, Sel;
}

sealed class ThumbJob { public string Path; public int Size; public long Stamp; }

// What a thumbnail worker hands back: the thumbnail plus facts learned while decoding (or why it failed).
sealed class ThumbResult
{
    public Bitmap Bmp;
    public int W, H;             // picture size as displayed (after EXIF rotation)
    public string Note;          // retro platform name, if any
    public string Error;         // set when Bmp == null
    public int FileStars;        // star rating stored in the file by Windows / Lightroom ... (0 = none)
}

// LRU cache of thumbnails, bounded by memory. UI thread only.
sealed class ThumbCache
{
    sealed class E { public Bitmap B; public long Stamp; public int Size, W, H; public string Note; public LinkedListNode<string> Node; }

    const long Budget = 160L * 1024 * 1024;
    readonly Dictionary<string, E> map = new Dictionary<string, E>(StringComparer.OrdinalIgnoreCase);
    readonly LinkedList<string> lru = new LinkedList<string>();
    long bytes;

    public bool Has(string path, long stamp, int size)
    {
        E e;
        return map.TryGetValue(path, out e) && e.Stamp == stamp && e.Size == size;
    }

    // The thumbnail for a picture, whatever size it was generated at (size reports that); null if none.
    public Bitmap Get(string path, long stamp, out int size)
    {
        E e;
        size = 0;
        if (!map.TryGetValue(path, out e) || e.Stamp != stamp) return null;
        lru.Remove(e.Node); lru.AddFirst(e.Node);
        size = e.Size;
        return e.B;
    }

    // size and platform of a cached picture (no LRU bookkeeping)
    public bool Info(string path, long stamp, out int w, out int h, out string note)
    {
        E e;
        w = h = 0; note = null;
        if (!map.TryGetValue(path, out e) || e.Stamp != stamp) return false;
        w = e.W; h = e.H; note = e.Note;
        return true;
    }

    public void Put(string path, long stamp, int size, ThumbResult r)
    {
        E e;
        if (map.TryGetValue(path, out e)) Remove(path, e);
        e = new E { B = r.Bmp, Stamp = stamp, Size = size, W = r.W, H = r.H, Note = r.Note };
        e.Node = lru.AddFirst(path);
        map[path] = e;
        bytes += (long)r.Bmp.Width * r.Bmp.Height * 4;
        while (bytes > Budget && lru.Count > 1) { string k = lru.Last.Value; Remove(k, map[k]); }
    }

    void Remove(string k, E e)
    {
        lru.Remove(e.Node); map.Remove(k);
        bytes -= (long)e.B.Width * e.B.Height * 4;
        e.B.Dispose();
    }

    public void Clear()
    {
        foreach (E e in map.Values) e.B.Dispose();
        map.Clear(); lru.Clear(); bytes = 0;
    }
}

// A few background threads that build thumbnails. The newest request list always wins,
// so whatever is on screen is decoded first and stale work is dropped.
sealed class ThumbService
{
    readonly object sync = new object();
    Queue<ThumbJob> queue = new Queue<ThumbJob>();
    readonly HashSet<string> running = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    readonly Action<ThumbJob, ThumbResult> done;

    public ThumbService(int threads, Action<ThumbJob, ThumbResult> done)
    {
        this.done = done;
        for (int i = 0; i < threads; i++)
        {
            var t = new Thread(Run) { IsBackground = true, Priority = ThreadPriority.BelowNormal, Name = "thumbs" };
            t.Start();
        }
    }

    public void Replace(List<ThumbJob> jobs)
    {
        lock (sync)
        {
            queue = new Queue<ThumbJob>();
            foreach (ThumbJob j in jobs) if (!running.Contains(j.Path)) queue.Enqueue(j);
            Monitor.PulseAll(sync);
        }
    }

    void Run()
    {
        while (true)
        {
            ThumbJob j;
            lock (sync)
            {
                while (queue.Count == 0) Monitor.Wait(sync);
                j = queue.Dequeue();
                running.Add(j.Path);
            }
            ThumbResult r;
            try { r = Make(j.Path, j.Size); }
            catch (Exception ex) { r = new ThumbResult { Error = Util.Why(ex) }; }
            lock (sync) running.Remove(j.Path);
            try { done(j, r); } catch (Exception) { if (r.Bmp != null) r.Bmp.Dispose(); }
        }
    }

    static ThumbResult Make(string path, int size)
    {
        if ((File.GetAttributes(path) & Util.CloudMask) != 0)
            return new ThumbResult { Error = "Cloud placeholder: the file is not stored on this PC." };
        if (!Util.IsNative(path) && Retro.Claims(path))
        {
            long bytes; string platform;
            using (Bitmap src = Retro.Load(path, out bytes, out platform))
                return new ThumbResult { Bmp = Scale(src, 0, size), W = src.Width, H = src.Height, Note = platform };
        }
        if (WinCodec.Claims(path))                             // decoded straight to thumbnail size by Windows' codec
        {
            CodecPic c;
            try { c = WinCodec.Load(path, size, true); }
            catch (Exception ex) { return new ThumbResult { Error = WinCodec.Why(path, ex) }; }
            using (c.Bmp)
            {
                bool sw = (c.Rot & 1) == 1;
                return new ThumbResult { Bmp = Scale(c.Bmp, c.Rot, size), W = sw ? c.H : c.W, H = sw ? c.W : c.H, FileStars = c.Stars };
            }
        }
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16))
        using (Image img = Image.FromStream(fs, false, false))      // reads the header only; pixels are decoded when drawn
        {
            int rot = Util.ReadRotation(img);
            bool swap = (rot & 1) == 1;
            int stars = FileRating.MayHold(path) ? FileRating.Read(path, img) : 0;
            Bitmap thumb = null;
            if (JpegRotate.IsJpeg(path) && WinCodec.WorthScaling(img.Width, img.Height, size))
                thumb = WinCodec.ScaledJpeg(path, img.Width, img.Height, size);     // big photo: decode at 1/2, 1/4 or 1/8 size
            if (thumb != null)
            {
                using (thumb)
                    return new ThumbResult { Bmp = Scale(thumb, rot, size), W = swap ? img.Height : img.Width, H = swap ? img.Width : img.Height, FileStars = stars };
            }
            return new ThumbResult { Bmp = Scale(img, rot, size), W = swap ? img.Height : img.Width, H = swap ? img.Width : img.Height,
                                     FileStars = stars };
        }
    }

    // scales any decoded picture to a thumbnail no larger than size x size (rot = quarter turns to apply)
    static Bitmap Scale(Image img, int rot, int size)
    {
        int w = img.Width, h = img.Height;
        double s = Math.Min(1.0, (double)size / Math.Max(w, h));
        int tw = Math.Max(1, (int)Math.Round(w * s)), th = Math.Max(1, (int)Math.Round(h * s));
        bool swap = (rot & 1) == 1;
        var bmp = new Bitmap(swap ? th : tw, swap ? tw : th, PixelFormat.Format32bppPArgb);
        using (Graphics g = Graphics.FromImage(bmp))
        using (var ia = new ImageAttributes())
        {
            ia.SetWrapMode(WrapMode.TileFlipXY);
            g.InterpolationMode = InterpolationMode.HighQualityBilinear;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.CompositingMode = CompositingMode.SourceCopy;
            g.TranslateTransform(bmp.Width / 2f, bmp.Height / 2f);
            g.RotateTransform(rot * 90f);
            g.TranslateTransform(-tw / 2f, -th / 2f);
            g.DrawImage(img, new Rectangle(0, 0, tw, th), 0, 0, w, h, GraphicsUnit.Pixel, ia);
        }
        return bmp;
    }
}
