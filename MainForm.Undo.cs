// RetroGleek - the main window, continued: undo (Ctrl+Z) for renames, batch renames and moves
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
using VBCancel = Microsoft.VisualBasic.FileIO.UICancelOption;

// ====================================================================== undo

partial class MainForm
{
    // One undoable action: what each item was called / where it was (Key) and what it is now (Value).
    sealed class UndoStep
    {
        public string Text;                    // for the menu: "rename of x.png", "move of 3 items to Pictures"
        public bool Move;                      // false: renames inside the same folders
        public List<KeyValuePair<string, string>> Pairs = new List<KeyValuePair<string, string>>();
    }

    const int MaxUndo = 20;
    readonly List<UndoStep> undoSteps = new List<UndoStep>();   // kept only while RetroGleek runs

    void PushUndo(string text, bool move, List<KeyValuePair<string, string>> pairs)
    {
        if (pairs == null || pairs.Count == 0) return;
        Marks.Moved(pairs);                                // ratings, labels and tags follow renamed / moved pictures
        undoSteps.Add(new UndoStep { Text = text, Move = move, Pairs = pairs });
        if (undoSteps.Count > MaxUndo) undoSteps.RemoveAt(0);
    }

    string UndoMenuText()
    {
        return undoSteps.Count == 0 ? "&Undo" : "&Undo " + undoSteps[undoSteps.Count - 1].Text;
    }

    static bool PathExists(string p) { return File.Exists(p) || Directory.Exists(p); }

    static void MovePath(string from, string to)
    {
        if (Directory.Exists(from)) Directory.Move(from, to); else File.Move(from, to);
    }

    // Ctrl+Z: puts the last renamed / moved items back. Nothing is overwritten: an item whose old name is taken
    // by something else now, or that is no longer there, is skipped and reported.
    void DoUndo()
    {
        if (viewing || undoSteps.Count == 0) return;
        UndoStep st = undoSteps[undoSteps.Count - 1];
        undoSteps.RemoveAt(undoSteps.Count - 1);
        var errs = new List<string>();
        var touched = new List<string>();
        string gd = grid.Dir, follow = null, firstBack = null;
        int back = 0;
        var backPairs = new List<KeyValuePair<string, string>>();   // what really went back: its marks go with it
        Cursor = Cursors.WaitCursor;
        try
        {
            // which items can go back: still there, old place free (or freed by another item of the same step)
            var nowSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (KeyValuePair<string, string> pr in st.Pairs) nowSet.Add(pr.Value);
            var todo = new List<KeyValuePair<string, string>>();
            foreach (KeyValuePair<string, string> pr in st.Pairs)
            {
                string name = Path.GetFileName(pr.Value);
                if (!PathExists(pr.Value)) { errs.Add(name + ": it is no longer there."); continue; }
                if (!Directory.Exists(Path.GetDirectoryName(pr.Key))) { errs.Add(name + ": its old folder no longer exists."); continue; }
                bool sameItem = string.Equals(pr.Key, pr.Value, StringComparison.OrdinalIgnoreCase);    // only the letter case changed
                if (!sameItem && PathExists(pr.Key) && (st.Move || !nowSet.Contains(pr.Key)))
                { errs.Add(Path.GetFileName(pr.Key) + ": that name is taken now, so " + name + " was left as it is."); continue; }
                todo.Add(pr);
            }

            if (!st.Move)
            {
                // renames: two steps through temporary names, so swapped or shifted names come back correctly
                var temps = new List<KeyValuePair<KeyValuePair<string, string>, string>>();
                foreach (KeyValuePair<string, string> pr in todo)
                {
                    try
                    {
                        string tmp = Path.Combine(Path.GetDirectoryName(pr.Value), "~rg" + Guid.NewGuid().ToString("N").Substring(0, 12) + ".tmp");
                        MovePath(pr.Value, tmp);
                        temps.Add(new KeyValuePair<KeyValuePair<string, string>, string>(pr, tmp));
                    }
                    catch (Exception ex) { errs.Add(Path.GetFileName(pr.Value) + ": " + ex.Message); }
                }
                foreach (KeyValuePair<KeyValuePair<string, string>, string> t in temps)
                {
                    try
                    {
                        MovePath(t.Value, t.Key.Key);
                        back++;
                        backPairs.Add(new KeyValuePair<string, string>(t.Key.Value, t.Key.Key));
                        if (firstBack == null) firstBack = t.Key.Key;
                        touched.Add(Path.GetDirectoryName(t.Key.Key));
                        if (gd != null && Directory.Exists(t.Key.Key) && InsideOrSame(gd, t.Key.Value))
                            follow = t.Key.Key + gd.Substring(t.Key.Value.TrimEnd('\\').Length);
                    }
                    catch (Exception ex)
                    {
                        try { MovePath(t.Value, t.Key.Value); } catch (Exception) { }   // keep the newer name rather than a temporary one
                        errs.Add(Path.GetFileName(t.Key.Value) + ": " + ex.Message);
                    }
                }
            }
            else
            {
                // moves: back to where they came from, newest first, with Windows' own file operation
                for (int i = todo.Count - 1; i >= 0; i--)
                {
                    KeyValuePair<string, string> pr = todo[i];
                    bool isDir = Directory.Exists(pr.Value);
                    try
                    {
                        if (isDir) VBFS.MoveDirectory(pr.Value, pr.Key, VBUI.AllDialogs, VBCancel.ThrowException);
                        else VBFS.MoveFile(pr.Value, pr.Key, VBUI.AllDialogs, VBCancel.ThrowException);
                        back++;
                        backPairs.Add(new KeyValuePair<string, string>(pr.Value, pr.Key));
                        firstBack = pr.Key;
                        touched.Add(Path.GetDirectoryName(pr.Key));
                        touched.Add(Path.GetDirectoryName(pr.Value));
                        if (isDir && gd != null && InsideOrSame(gd, pr.Value)) follow = pr.Key + gd.Substring(pr.Value.TrimEnd('\\').Length);
                    }
                    catch (OperationCanceledException) { errs.Add("Cancelled: the remaining items were left where they are."); break; }
                    catch (Exception ex) { errs.Add(Path.GetFileName(pr.Value) + ": " + ex.Message); }
                }
            }
        }
        finally { Cursor = Cursors.Default; }
        Marks.Moved(backPairs);

        foreach (string d in touched)
            foreach (TreeNode n in FindLoadedNodes(d)) RefreshFolderNode(n);
        if (follow != null) { ShowFolder(follow, null, -1, true); RevealInTree(follow); }
        else if (gd != null && touched.Exists(x => grid.Covers(x)))
        {
            if (firstBack != null && File.Exists(firstBack) && grid.Covers(Path.GetDirectoryName(firstBack))) ShowFolder(gd, firstBack, -1, true);
            else grid.Rescan();
        }
        status.Text = "  Undid the " + st.Text + (back != st.Pairs.Count ? " (" + back + " of " + st.Pairs.Count + " items)" : "");
        if (errs.Count > 0)
        {
            if (errs.Count > 8) { errs = errs.GetRange(0, 8); errs.Add("..."); }
            Warn("Not everything could be undone:\n\n" + string.Join("\n", errs));
        }
    }
}
