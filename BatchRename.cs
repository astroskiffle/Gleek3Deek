// RetroGleek - batch rename (pattern, preview, safe two-step renaming)
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

// ====================================================================== batch rename

// one file in a batch rename
sealed class RenamePlan
{
    public string From, To;      // full paths
    public string NewName;       // just the new file name (shown even when it is invalid)
    public string Note;          // shown in the preview ("" = fine)
    public bool Change;          // the name really changes
    public bool Bad;             // this row blocks the rename
}

// Pattern: "#" is the number (a run of #s sets the digits: ### gives 001), "[name]" is the current name without its
// extension; anything else is kept as typed. The extension is always kept. Each file stays in its own folder.
// Nothing is ever overwritten: a name that is taken by a file outside the selection, or used twice, blocks the rename.
static class BatchRename
{
    static readonly HashSet<string> Reserved = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    };

    public static string Expand(string pattern, string stem, int n)
    {
        var sb = new System.Text.StringBuilder();
        int i = 0;
        while (i < pattern.Length)
        {
            if (string.Compare(pattern, i, "[name]", 0, 6, StringComparison.OrdinalIgnoreCase) == 0) { sb.Append(stem); i += 6; continue; }
            if (pattern[i] == '#')
            {
                int run = 0;
                while (i < pattern.Length && pattern[i] == '#') { run++; i++; }
                sb.Append(n.ToString().PadLeft(run, '0'));
                continue;
            }
            sb.Append(pattern[i]);
            i++;
        }
        return sb.ToString();
    }

    // works out every new name and checks it; never touches the disk except to look for existing files
    public static List<RenamePlan> Plan(List<string> paths, string pattern, int start)
    {
        var plans = new List<RenamePlan>();
        var selected = new HashSet<string>(paths, StringComparer.OrdinalIgnoreCase);
        var used = new Dictionary<string, RenamePlan>(StringComparer.OrdinalIgnoreCase);
        char[] bad = Path.GetInvalidFileNameChars();
        int n = start;
        foreach (string p in paths)
        {
            var r = new RenamePlan { From = p, Note = "" };
            plans.Add(r);
            string dir = Path.GetDirectoryName(p), ext = Path.GetExtension(p);
            string stem = Expand(pattern, Path.GetFileNameWithoutExtension(p), n++);
            string name = stem + ext;
            r.NewName = name;
            r.To = dir.TrimEnd('\\') + "\\" + name;          // built by hand: Path.Combine would throw on a bad character
            string baseName = stem.Split('.')[0].Trim();
            if (stem.Trim().Length == 0) { r.Bad = true; r.Note = "the new name is empty"; continue; }
            if (name.IndexOfAny(bad) >= 0) { r.Bad = true; r.Note = "contains a character that names can't have  \\ / : * ? \" < > |"; continue; }
            if (stem.EndsWith(" ") || stem.EndsWith(".")) { r.Bad = true; r.Note = "a name can't end with a space or a dot"; continue; }
            if (Reserved.Contains(baseName)) { r.Bad = true; r.Note = "\"" + baseName + "\" is reserved by Windows"; continue; }
            if (r.To.Length >= 260) { r.Bad = true; r.Note = "the full path would be too long"; continue; }
            r.Change = !string.Equals(r.To, p, StringComparison.Ordinal);
            if (!r.Change) { r.Note = "unchanged"; continue; }
            RenamePlan other;
            if (used.TryGetValue(r.To, out other))
            {
                r.Bad = true; r.Note = "same new name as " + Path.GetFileName(other.From);
                if (!other.Bad) { other.Bad = true; other.Note = "same new name as " + Path.GetFileName(p); }
                continue;
            }
            used[r.To] = r;
            // taken by something that isn't part of this rename (a selected file is moved out of the way first)
            if (!selected.Contains(r.To) && (File.Exists(r.To) || Directory.Exists(r.To))) { r.Bad = true; r.Note = "a file with this name already exists"; }
        }
        return plans;
    }

    // Renames in two steps (every file to a temporary name, then to its new name), so names can be swapped or
    // shifted inside the selection. On any error, what was done is undone. Returns null, or the error.
    public static string Apply(List<RenamePlan> plans)
    {
        var todo = plans.FindAll(x => x.Change && !x.Bad);
        var temps = new List<KeyValuePair<RenamePlan, string>>();
        try
        {
            foreach (RenamePlan r in todo)
            {
                string tmp = Path.Combine(Path.GetDirectoryName(r.From), "~rg" + Guid.NewGuid().ToString("N").Substring(0, 12) + ".tmp");
                File.Move(r.From, tmp);
                temps.Add(new KeyValuePair<RenamePlan, string>(r, tmp));
            }
        }
        catch (Exception ex)
        {
            foreach (KeyValuePair<RenamePlan, string> t in temps) { try { File.Move(t.Value, t.Key.From); } catch (Exception) { } }
            return "Nothing was renamed: " + ex.Message;
        }
        var done = new List<KeyValuePair<RenamePlan, string>>();
        foreach (KeyValuePair<RenamePlan, string> t in temps)
        {
            try { File.Move(t.Value, t.Key.To); done.Add(t); }
            catch (Exception ex)
            {
                // put everything back the way it was
                foreach (KeyValuePair<RenamePlan, string> d in done) { try { File.Move(d.Key.To, d.Value); } catch (Exception) { } }
                foreach (KeyValuePair<RenamePlan, string> u in temps) { try { File.Move(u.Value, u.Key.From); } catch (Exception) { } }
                return Path.GetFileName(t.Key.From) + ": " + ex.Message + "\n\nThe other files were given back their old names.";
            }
        }
        return null;
    }

    // a suggestion for the pattern: the first file's name without trailing digits, then a counter
    static string Suggest(List<string> paths)
    {
        string s = Path.GetFileNameWithoutExtension(paths[0]).TrimEnd('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ' ', '_', '-', '.');
        if (s.Length == 0) s = "picture";
        int digits = Math.Max(2, paths.Count.ToString().Length);
        return s + "_" + new string('#', digits);
    }

    // The dialog. Returns every rename that was made (old path -> new path, for undo), or null if nothing was renamed.
    public static List<KeyValuePair<string, string>> Show(IWin32Window owner, List<string> paths, Action<Form> darkTitle)
    {
        if (paths == null || paths.Count == 0) return null;
        Color panelBg = Color.FromArgb(38, 38, 38), boxBg = Color.FromArgb(52, 52, 52), text = Color.Gainsboro;
        using (var f = new Form())
        using (var timer = new WinTimer { Interval = 200 })
        {
            f.AutoScaleMode = AutoScaleMode.None;
            f.Font = new Font("Segoe UI", 9.5f);
            f.Text = "Batch rename - " + paths.Count + (paths.Count == 1 ? " picture" : " pictures");
            f.StartPosition = FormStartPosition.CenterParent;
            f.ShowInTaskbar = false; f.MinimizeBox = false;
            f.BackColor = panelBg; f.ForeColor = text;
            f.ClientSize = new Size(Util.S(760), Util.S(520));
            f.MinimumSize = new Size(Util.S(520), Util.S(360));
            if (darkTitle != null) f.HandleCreated += delegate { darkTitle(f); };

            int pad = Util.S(12);
            var top = new Panel { Dock = DockStyle.Top, Height = Util.S(108), Padding = new Padding(pad, pad, pad, 0) };
            var lp = new Label { Text = "New name:", Left = pad, Top = pad + Util.S(4), Width = Util.S(80), ForeColor = Color.Silver };
            var pattern = new TextBox
            {
                Left = pad + Util.S(84), Top = pad, Width = Util.S(400), BorderStyle = BorderStyle.FixedSingle,
                BackColor = boxBg, ForeColor = Color.White, Font = new Font("Segoe UI", 10f), Text = Suggest(paths)
            };
            var ls = new Label { Text = "Start at:", Left = pad + Util.S(500), Top = pad + Util.S(4), Width = Util.S(64), ForeColor = Color.Silver };
            var start = new NumericUpDown
            {
                Left = pad + Util.S(566), Top = pad, Width = Util.S(90), Minimum = 0, Maximum = 99999999, Value = 1,
                BackColor = boxBg, ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle
            };
            var hint = new Label
            {
                Left = pad, Top = pad + Util.S(38), Width = Util.S(720), Height = Util.S(44), ForeColor = Color.Gray,
                Text = "#  = the number (### gives 001, 002 ...)     [name]  = the current name     The extension is kept.\n" +
                       "Pictures are numbered in the order shown in the grid. Nothing is overwritten."
            };
            top.Controls.Add(lp); top.Controls.Add(pattern); top.Controls.Add(ls); top.Controls.Add(start); top.Controls.Add(hint);

            var list = new ListView
            {
                Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, HeaderStyle = ColumnHeaderStyle.Nonclickable,
                BackColor = Color.FromArgb(32, 32, 32), ForeColor = text, BorderStyle = BorderStyle.None, MultiSelect = false
            };
            list.Columns.Add("Current name", Util.S(260));
            list.Columns.Add("New name", Util.S(260));
            list.Columns.Add("", Util.S(210));
            Util.Dark(list);

            var bottom = new Panel { Dock = DockStyle.Bottom, Height = Util.S(52), Padding = new Padding(pad, Util.S(10), pad, Util.S(10)) };
            var summary = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.Silver };
            var ok = new Button
            {
                Dock = DockStyle.Right, Width = Util.S(140), FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(60, 130, 230),
                ForeColor = Color.White, Text = "Rename"
            };
            var cancel = new Button
            {
                Dock = DockStyle.Right, Width = Util.S(100), FlatStyle = FlatStyle.Flat, BackColor = boxBg, ForeColor = text,
                Text = "Cancel", DialogResult = DialogResult.Cancel
            };
            ok.FlatAppearance.BorderSize = 0; cancel.FlatAppearance.BorderSize = 0;
            bottom.Controls.Add(summary);                          // fill first, edge-docked after
            bottom.Controls.Add(ok);
            bottom.Controls.Add(new Label { Dock = DockStyle.Right, Width = Util.S(8) });
            bottom.Controls.Add(cancel);

            f.Controls.Add(list);                                  // fill first, edge-docked after
            f.Controls.Add(bottom);
            f.Controls.Add(top);
            f.CancelButton = cancel;

            List<RenamePlan> plans = null;
            MethodInvoker refresh = delegate
            {
                plans = Plan(paths, pattern.Text, (int)start.Value);
                int changes = 0, problems = 0;
                list.BeginUpdate();
                try
                {
                    list.Items.Clear();
                    foreach (RenamePlan r in plans)
                    {
                        var it = new ListViewItem(new[] { Path.GetFileName(r.From), r.NewName ?? "", r.Note });
                        if (r.Bad) { it.ForeColor = Color.FromArgb(255, 140, 90); problems++; }
                        else if (!r.Change) it.ForeColor = Color.Gray;
                        else changes++;
                        list.Items.Add(it);
                    }
                }
                finally { list.EndUpdate(); }
                ok.Enabled = problems == 0 && changes > 0;
                ok.BackColor = ok.Enabled ? Color.FromArgb(60, 130, 230) : boxBg;
                ok.Text = changes > 0 ? "Rename " + changes : "Rename";
                summary.Text = problems > 0 ? problems + (problems == 1 ? " name needs" : " names need") + " fixing (shown in orange) before anything can be renamed."
                             : changes == 0 ? "No name would change."
                             : changes + (changes == 1 ? " picture" : " pictures") + " will be renamed.";
            };
            timer.Tick += delegate { timer.Stop(); refresh(); };
            pattern.TextChanged += delegate { timer.Stop(); timer.Start(); };
            start.ValueChanged += delegate { timer.Stop(); timer.Start(); };

            List<KeyValuePair<string, string>> result = null;
            ok.Click += delegate
            {
                timer.Stop();
                refresh();                                         // what you see is exactly what is renamed
                if (!ok.Enabled) return;
                string err = Apply(plans);
                if (err != null) { MessageBox.Show(f, err, "Batch rename", MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
                result = new List<KeyValuePair<string, string>>();
                foreach (RenamePlan r in plans) if (r.Change && !r.Bad) result.Add(new KeyValuePair<string, string>(r.From, r.To));
                f.DialogResult = DialogResult.OK;
            };
            f.Shown += delegate { refresh(); pattern.Focus(); pattern.SelectAll(); };
            f.ShowDialog(owner);
            return result;
        }
    }
}
