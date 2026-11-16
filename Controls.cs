// RetroGleek - small dialogs and custom-drawn dark controls (rename prompt, wheel routing, menus, pull-down, slider)
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

// ====================================================================== small dialog / wheel routing

static class Prompt
{
    public static string Ask(IWin32Window owner, string title, string label, string text, bool selectStem)
    {
        using (var f = new Form())
        {
            f.AutoScaleMode = AutoScaleMode.None;
            f.Font = SystemFonts.MessageBoxFont;
            f.Text = title;
            f.FormBorderStyle = FormBorderStyle.FixedDialog;
            f.StartPosition = FormStartPosition.CenterParent;
            f.MaximizeBox = false; f.MinimizeBox = false; f.ShowInTaskbar = false;
            f.ClientSize = new Size(Util.S(400), Util.S(112));
            var l = new Label { Text = label, Left = Util.S(12), Top = Util.S(12), AutoSize = true };
            var t = new TextBox { Left = Util.S(12), Top = Util.S(36), Width = Util.S(376), Text = text };
            var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Left = Util.S(222), Top = Util.S(72), Width = Util.S(80), Height = Util.S(28) };
            var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Left = Util.S(308), Top = Util.S(72), Width = Util.S(80), Height = Util.S(28) };
            f.AcceptButton = ok; f.CancelButton = cancel;
            f.Controls.Add(l); f.Controls.Add(t); f.Controls.Add(ok); f.Controls.Add(cancel);
            f.Shown += delegate
            {
                t.Focus();
                int dot = text.LastIndexOf('.');
                t.Select(0, selectStem && dot > 0 ? dot : text.Length);
            };
            return f.ShowDialog(owner) == DialogResult.OK ? t.Text.Trim() : null;
        }
    }
}

// Scrolls the pane under the mouse cursor even when the other pane has keyboard focus,
// so hovering over the tree or the thumbnails and turning the wheel just works.
// Pure managed code: it only ever talks to this window's own two panes.
sealed class WheelRouter : IMessageFilter
{
    readonly Form owner;
    readonly TreeView tree;
    readonly ThumbGrid grid;

    public WheelRouter(Form owner, TreeView tree, ThumbGrid grid)
    {
        this.owner = owner; this.tree = tree; this.grid = grid;
    }

    public bool PreFilterMessage(ref Message m)
    {
        if (m.Msg != 0x020A || Form.ActiveForm != owner) return false;      // 0x020A = WM_MOUSEWHEEL
        Point p = Control.MousePosition;
        int delta = unchecked((short)(m.WParam.ToInt64() >> 16));
        if (grid.Visible && !grid.Focused && grid.RectangleToScreen(grid.ClientRectangle).Contains(p))
        {
            grid.Wheel(delta, (Control.ModifierKeys & Keys.Control) != 0);
            return true;
        }
        if (tree.Visible && !tree.Focused && tree.RectangleToScreen(tree.ClientRectangle).Contains(p))
        {
            ScrollTree(delta);
            return true;
        }
        return false;
    }

    void ScrollTree(int delta)
    {
        TreeNode n = tree.TopNode;
        if (n == null) return;
        if (delta < 0)
        {
            TreeNode bottom = tree.GetNodeAt(2, tree.ClientSize.Height - 2);
            if (bottom == null || bottom.NextVisibleNode == null) return;    // already at the end
        }
        int steps = Math.Max(1, Math.Abs(delta) * Math.Max(1, SystemInformation.MouseWheelScrollLines) / 120);
        for (int i = 0; i < steps; i++)
        {
            TreeNode q = delta > 0 ? n.PrevVisibleNode : n.NextVisibleNode;
            if (q == null) break;
            n = q;
        }
        tree.TopNode = n;
    }
}

// ====================================================================== dark toolbar controls

// The system combo box and track bar are drawn by Windows in light colours and can't be restyled, so the
// sort pull-down and the thumbnail-size slider are drawn here instead.

static class Gfx
{
    public static readonly Color Accent = Color.FromArgb(60, 130, 230);          // same blue as the thumbnail selection

    public static GraphicsPath Round(RectangleF r, float rad)
    {
        float d = Math.Min(rad * 2f, Math.Min(r.Width, r.Height));
        var p = new GraphicsPath();
        p.AddArc(r.X, r.Y, d, d, 180, 90);
        p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }
}

// dark colours for the pull-down's drop-down list
sealed class DarkColors : ProfessionalColorTable
{
    static readonly Color Back = Color.FromArgb(38, 38, 38), Line = Color.FromArgb(84, 84, 84), Hot = Color.FromArgb(72, 72, 72);
    public override Color ToolStripDropDownBackground { get { return Back; } }
    public override Color ImageMarginGradientBegin { get { return Back; } }
    public override Color ImageMarginGradientMiddle { get { return Back; } }
    public override Color ImageMarginGradientEnd { get { return Back; } }
    public override Color MenuBorder { get { return Line; } }
    public override Color MenuItemBorder { get { return Hot; } }
    public override Color MenuItemSelected { get { return Hot; } }
    public override Color MenuItemSelectedGradientBegin { get { return Hot; } }
    public override Color MenuItemSelectedGradientEnd { get { return Hot; } }
    public override Color SeparatorDark { get { return Line; } }
    public override Color SeparatorLight { get { return Back; } }
    // the main menu bar
    public override Color MenuStripGradientBegin { get { return Back; } }
    public override Color MenuStripGradientEnd { get { return Back; } }
    public override Color MenuItemPressedGradientBegin { get { return Hot; } }
    public override Color MenuItemPressedGradientMiddle { get { return Hot; } }
    public override Color MenuItemPressedGradientEnd { get { return Hot; } }
}

sealed class DarkMenuRenderer : ToolStripProfessionalRenderer
{
    public DarkMenuRenderer() : base(new DarkColors()) { RoundedEdges = false; }

    // sub-menu arrows: light, so they show on the dark background
    protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e)
    {
        e.ArrowColor = e.Item != null && !e.Item.Enabled ? Color.Gray : Color.Gainsboro;
        base.OnRenderArrow(e);
    }

    // disabled entries: a mid grey that stays readable on the dark background
    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
    {
        if (e.Item != null && !e.Item.Enabled) e.TextColor = Color.FromArgb(120, 120, 120);
        base.OnRenderItemText(e);
    }

    // the system draws a black check mark, which would vanish on a dark menu
    protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
    {
        Rectangle r = e.ImageRectangle;
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using (var br = new SolidBrush(Color.FromArgb(70, 100, 160))) g.FillRectangle(br, r);
        using (var pen = new Pen(Color.White, Math.Max(1.6f, Util.K * 1.8f)))
        {
            pen.StartCap = LineCap.Round; pen.EndCap = LineCap.Round; pen.LineJoin = LineJoin.Round;
            g.DrawLines(pen, new[]
            {
                new PointF(r.X + r.Width * 0.25f, r.Y + r.Height * 0.55f),
                new PointF(r.X + r.Width * 0.43f, r.Y + r.Height * 0.72f),
                new PointF(r.X + r.Width * 0.76f, r.Y + r.Height * 0.30f)
            });
        }
    }
}

// A dark drop-down list: shows the chosen item and opens a dark popup list on click.
// Keyboard: Up / Down change the choice; Space, Enter, F4 or Alt+Down open the list.
sealed class DarkCombo : Control
{
    public event EventHandler SelectedIndexChanged;
    public event EventHandler DropDownClosed;

    string[] items = new string[0];
    int sel = -1, closedAt;
    bool hot, open;
    ContextMenuStrip menu;

    public DarkCombo()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
        TabStop = false;
        BackColor = Color.FromArgb(52, 52, 52); ForeColor = Color.White; Font = new Font("Segoe UI", 9.5f);
    }

    public void SetItems(params string[] list)
    {
        items = list;
        if (sel >= items.Length) sel = -1;
        Invalidate();
    }

    public int SelectedIndex
    {
        get { return sel; }
        set
        {
            if (value < -1 || value >= items.Length || value == sel) return;
            sel = value;
            Invalidate();
            var h = SelectedIndexChanged;
            if (h != null) h(this, EventArgs.Empty);
        }
    }

    void ShowList()
    {
        if (items.Length == 0) return;
        if (menu == null)
        {
            menu = new ContextMenuStrip { Renderer = new DarkMenuRenderer(), BackColor = Color.FromArgb(38, 38, 38), ForeColor = Color.Gainsboro };
            menu.Closed += delegate
            {
                open = false; closedAt = Environment.TickCount; Invalidate();
                var h = DropDownClosed;
                if (h != null) h(this, EventArgs.Empty);
            };
        }
        menu.Font = Font;
        menu.Items.Clear();
        for (int i = 0; i < items.Length; i++)
        {
            int idx = i;
            var mi = new ToolStripMenuItem(items[i]) { Checked = i == sel, ForeColor = Color.Gainsboro };
            mi.Click += delegate { SelectedIndex = idx; };
            menu.Items.Add(mi);
        }
        menu.MinimumSize = new Size(Width, 0);
        open = true;
        Invalidate();
        menu.Show(this, new Point(0, Height));
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hot = true; Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hot = false; Invalidate(); }
    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        Focus();
        // the click that dismisses the open list must not immediately reopen it
        if (unchecked(Environment.TickCount - closedAt) < 250) return;
        ShowList();
    }

    protected override bool IsInputKey(Keys keyData)
    {
        switch (keyData & Keys.KeyCode)
        {
            case Keys.Up: case Keys.Down: case Keys.Home: case Keys.End: case Keys.Return: case Keys.Space: case Keys.F4:
                return true;
        }
        return base.IsInputKey(keyData);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        switch (e.KeyCode)
        {
            case Keys.Up: SelectedIndex = Math.Max(0, sel - 1); e.Handled = true; break;
            case Keys.Down:
                if (e.Alt) ShowList(); else SelectedIndex = Math.Min(items.Length - 1, sel + 1);
                e.Handled = true; break;
            case Keys.Home: SelectedIndex = 0; e.Handled = true; break;
            case Keys.End: SelectedIndex = items.Length - 1; e.Handled = true; break;
            case Keys.Return: case Keys.Space: case Keys.F4: ShowList(); e.Handled = true; break;
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(Parent != null ? Parent.BackColor : BackColor);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        Color border = open || Focused ? Gfx.Accent : hot ? Color.FromArgb(125, 125, 125) : Color.FromArgb(84, 84, 84);
        using (GraphicsPath p = Gfx.Round(new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f), Util.S(4)))
        {
            using (var br = new SolidBrush(hot || open ? Color.FromArgb(62, 62, 62) : BackColor)) g.FillPath(br, p);
            using (var pen = new Pen(border)) g.DrawPath(pen, p);
        }
        TextRenderer.DrawText(g, sel >= 0 ? items[sel] : "", Font, new Rectangle(Util.S(9), 0, Width - Util.S(30), Height), ForeColor,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
        float cx = Width - Util.S(15), cy = Height / 2f, a = Util.S(4);                  // drop-down arrow
        using (var br = new SolidBrush(Color.Gainsboro))
            g.FillPolygon(br, new[] { new PointF(cx - a, cy - a * 0.55f), new PointF(cx + a, cy - a * 0.55f), new PointF(cx, cy + a * 0.75f) });
    }
}

// A slim dark slider: groove, blue filled part and a round thumb. Mouse (click or drag), wheel and keyboard.
sealed class DarkSlider : Control
{
    public event EventHandler ValueChanged;

    int min, max = 100, val;
    bool dragging, hot;

    public DarkSlider()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
        TabStop = false;
    }

    public int Minimum { get { return min; } set { min = value; if (val < min) val = min; Invalidate(); } }
    public int Maximum { get { return max; } set { max = value; if (val > max) val = max; Invalidate(); } }

    public int Value
    {
        get { return val; }
        set
        {
            int n = Math.Max(min, Math.Min(max, value));
            if (n == val) return;
            val = n;
            Invalidate();
            var h = ValueChanged;
            if (h != null) h(this, EventArgs.Empty);
        }
    }

    float ThumbR { get { return Util.S(7); } }
    float TrackLeft { get { return ThumbR + 1f; } }
    float TrackWidth { get { return Math.Max(1f, Width - 2f * TrackLeft); } }

    float ThumbX
    {
        get { return TrackLeft + (max == min ? 0f : (float)(val - min) / (max - min) * TrackWidth); }
    }

    void SetFromX(int x)
    {
        double f = (x - TrackLeft) / TrackWidth;
        Value = min + (int)Math.Round(Math.Max(0.0, Math.Min(1.0, f)) * (max - min));
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hot = true; Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hot = false; Invalidate(); }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        Focus();
        dragging = true;
        Capture = true;
        SetFromX(e.X);
        Invalidate();
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (dragging) SetFromX(e.X);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        dragging = false;
        Capture = false;
        Invalidate();
        base.OnMouseUp(e);
    }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        Value = val + (e.Delta > 0 ? 1 : -1);
    }

    protected override bool IsInputKey(Keys keyData)
    {
        switch (keyData & Keys.KeyCode)
        {
            case Keys.Left: case Keys.Right: case Keys.Up: case Keys.Down: case Keys.Home: case Keys.End: case Keys.PageUp: case Keys.PageDown:
                return true;
        }
        return base.IsInputKey(keyData);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        switch (e.KeyCode)
        {
            case Keys.Left: case Keys.Down: Value = val - 1; e.Handled = true; break;
            case Keys.Right: case Keys.Up: Value = val + 1; e.Handled = true; break;
            case Keys.PageDown: Value = val - 2; e.Handled = true; break;
            case Keys.PageUp: Value = val + 2; e.Handled = true; break;
            case Keys.Home: Value = min; e.Handled = true; break;
            case Keys.End: Value = max; e.Handled = true; break;
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(BackColor);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        float cy = Height / 2f, th = Math.Max(3f, Util.S(4)), tx = ThumbX, r = ThumbR;
        using (GraphicsPath groove = Gfx.Round(new RectangleF(TrackLeft, cy - th / 2f, TrackWidth, th), th / 2f))
        using (var br = new SolidBrush(Color.FromArgb(78, 78, 78)))
            g.FillPath(br, groove);
        if (tx > TrackLeft + 0.5f)
            using (GraphicsPath fill = Gfx.Round(new RectangleF(TrackLeft, cy - th / 2f, tx - TrackLeft, th), th / 2f))
            using (var br = new SolidBrush(Gfx.Accent))
                g.FillPath(br, fill);
        Color thumb = dragging ? Color.FromArgb(180, 210, 255) : hot || Focused ? Color.White : Color.Gainsboro;
        using (var br = new SolidBrush(thumb)) g.FillEllipse(br, tx - r, cy - r, r * 2f, r * 2f);
        using (var pen = new Pen(Color.FromArgb(24, 24, 24))) g.DrawEllipse(pen, tx - r, cy - r, r * 2f, r * 2f);
    }
}
