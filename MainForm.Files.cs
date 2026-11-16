// RetroGleek - the main window, continued: menus, file operations, PNG export, address bar / filter / sort, key routing
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

// ====================================================================== main window (continued)

partial class MainForm
{
    // ================================================================ menus & file operations

    static ToolStripMenuItem AddEntry(ContextMenuStrip m, string text, string keys, EventHandler h)
    {
        var mi = new ToolStripMenuItem(text) { ShortcutKeyDisplayString = keys };
        mi.Click += h;
        m.Items.Add(mi);
        return mi;
    }

    void BuildMenus()
    {
        gridMenu = new ContextMenuStrip();
        gOpen = AddEntry(gridMenu, "Open", "Enter", delegate { OpenIndex(grid.FocusIndex); });
        gridMenu.Items.Add(new ToolStripSeparator());
        gInvert = AddEntry(gridMenu, "Invert selection", "Ctrl+I", delegate { grid.InvertSelection(); });
        gridMenu.Items.Add(new ToolStripSeparator());
        gRename = AddEntry(gridMenu, "Rename", "F2", delegate { DoRename(false); });
        gBatch = AddEntry(gridMenu, "Batch rename...", "Ctrl+F2", delegate { DoBatchRename(); });
        gCompare = AddEntry(gridMenu, "Compare side by side", "Ctrl+Shift+C", delegate { StartCompare(); });
        gCut = AddEntry(gridMenu, "Cut", "Ctrl+X", delegate { DoCut(false); });
        gCopy = AddEntry(gridMenu, "Copy", "Ctrl+C", delegate { DoCopy(false); });
        gPaste = AddEntry(gridMenu, "Paste", "Ctrl+V", delegate { DoPaste(false); });
        gridMenu.Items.Add(new ToolStripSeparator());
        gSave = AddEntry(gridMenu, "Save as PNG (lossless)...", "Ctrl+S", delegate { DoSavePng(); });
        gFrames = AddEntry(gridMenu, "Export all frames as PNG...", "Ctrl+Shift+S", delegate { DoExportFrames(); });
        gridMenu.Items.Add(new ToolStripSeparator());
        gDelete = AddEntry(gridMenu, "Delete (to Recycle Bin)", "Del", delegate { DoDelete(false); });
        gridMenu.Items.Add(new ToolStripSeparator());
        AddEntry(gridMenu, "Refresh", "F5", delegate { ReloadAll(); });
        gridMenu.Items.Add(new ToolStripSeparator());
        var sortMenu = new ToolStripMenuItem("Sort by");
        string[] sortNames = { "Name", "Date modified", "Size", "Type" };
        for (int i = 0; i < sortNames.Length; i++)
        {
            int key = i;
            gSort[i] = new ToolStripMenuItem(sortNames[i]);
            gSort[i].Click += delegate { ChooseSort(key); };
            sortMenu.DropDownItems.Add(gSort[i]);
        }
        sortMenu.DropDownItems.Add(new ToolStripSeparator());
        gSortDesc = new ToolStripMenuItem("Reverse order");
        gSortDesc.Click += delegate { grid.SetSort(grid.SortKey, !grid.SortDesc); };
        sortMenu.DropDownItems.Add(gSortDesc);
        gridMenu.Items.Add(sortMenu);
        gDetails = AddEntry(gridMenu, "Show details on tiles", "", delegate { grid.ShowDetails = !grid.ShowDetails; });
        gridMenu.Items.Add(new ToolStripSeparator());
        gRetro = AddEntry(gridMenu, "Show retro-computer formats (RECOIL)", "F8", delegate { ToggleRetro(); });

        treeMenu = new ContextMenuStrip();
        tNew = AddEntry(treeMenu, "New Folder", "", delegate { DoNewFolder(); });
        treeMenu.Items.Add(new ToolStripSeparator());
        tRename = AddEntry(treeMenu, "Rename", "F2", delegate { DoRename(true); });
        tCut = AddEntry(treeMenu, "Cut", "Ctrl+X", delegate { DoCut(true); });
        tCopy = AddEntry(treeMenu, "Copy", "Ctrl+C", delegate { DoCopy(true); });
        tPaste = AddEntry(treeMenu, "Paste", "Ctrl+V", delegate { DoPaste(true); });
        treeMenu.Items.Add(new ToolStripSeparator());
        tDelete = AddEntry(treeMenu, "Delete (to Recycle Bin)", "Del", delegate { DoDelete(true); });
        treeMenu.Items.Add(new ToolStripSeparator());
        AddEntry(treeMenu, "Refresh", "F5", delegate { ReloadAll(); });
        treeMenu.Items.Add(new ToolStripSeparator());
        tRetro = AddEntry(treeMenu, "Show retro-computer formats (RECOIL)", "F8", delegate { ToggleRetro(); });
        treeMenu.Items.Insert(1, tFav = new ToolStripMenuItem("Add to favourites"));
        tFav.Click += delegate { ToggleFavourite(NodePath(tree.SelectedNode)); };
    }

    // ---------------------------------------------------------------- favourite and recent folders

    // Favourites (Ctrl+D, Go > Favourites, right-click a folder in the tree): shortcuts listed in the tree after
    // Desktop, Documents, Downloads and Pictures, with a star. Recent folders: the last 10 folders opened.
    // Both are remembered in settings.ini. A favourite is only a shortcut: removing it never touches the folder.
    const int MaxFavourites = 20, MaxRecentFolders = 10;
    readonly List<string> favourites = new List<string>();
    readonly List<string> recentFolders = new List<string>();
    ToolStripMenuItem tFav;

    void LoadFavourites()
    {
        favourites.Clear(); recentFolders.Clear();
        for (int i = 1; i <= MaxFavourites; i++)
        {
            string p = Prefs.Get("favourite" + i, null);
            if (!string.IsNullOrEmpty(p) && !p.StartsWith("\\\\") && !favourites.Exists(x => Util.SameDir(x, p))) favourites.Add(p);
        }
        for (int i = 1; i <= MaxRecentFolders; i++)
        {
            string p = Prefs.Get("recentFolder" + i, null);
            if (!string.IsNullOrEmpty(p) && !p.StartsWith("\\\\") && !recentFolders.Exists(x => Util.SameDir(x, p))) recentFolders.Add(p);
        }
        RefreshFavNodes();
    }

    void StoreFavourites()
    {
        for (int i = 1; i <= MaxFavourites; i++) Prefs.Set("favourite" + i, i <= favourites.Count ? favourites[i - 1] : null);
        for (int i = 1; i <= MaxRecentFolders; i++) Prefs.Set("recentFolder" + i, i <= recentFolders.Count ? recentFolders[i - 1] : null);
    }

    bool IsFavourite(string dir) { return dir != null && favourites.Exists(x => Util.SameDir(x, dir)); }

    void ToggleFavourite(string dir)
    {
        if (string.IsNullOrEmpty(dir)) return;
        string name = FavText(dir);
        if (IsFavourite(dir))
        {
            favourites.RemoveAll(x => Util.SameDir(x, dir));
            status.Text = "  Removed " + name + " from the favourites (the folder itself is untouched)";
        }
        else
        {
            if (favourites.Count >= MaxFavourites) { Warn("You already have " + MaxFavourites + " favourites. Remove one first (right-click it in the folder tree)."); return; }
            favourites.Add(dir);
            status.Text = "  Added " + name + " to the favourites (in the folder tree and Go > Favourites)";
        }
        StoreFavourites();
        RefreshFavNodes();
        if (viewing) canvas.ShowMessage(IsFavourite(dir) ? "Added " + name + " to the favourites" : "Removed " + name + " from the favourites");
    }

    static string FavText(string dir)
    {
        string n = Path.GetFileName(dir.TrimEnd('\\', '/'));
        return n.Length > 0 ? n : dir;
    }

    // the favourites' nodes in the tree: right after the quick-access entries
    void RefreshFavNodes()
    {
        if (pcNode == null) return;
        tree.ShowNodeToolTips = true;
        suppress = true;                                   // no folder change while the nodes are swapped
        tree.BeginUpdate();
        try
        {
            TreeNode sel = tree.SelectedNode;
            bool selWasFav = sel != null && sel.Name == "fav";
            for (int i = pcNode.Nodes.Count - 1; i >= 0; i--) if (pcNode.Nodes[i].Name == "fav") { waiting.Remove(pcNode.Nodes[i]); pcNode.Nodes.RemoveAt(i); }
            int at = 0;
            for (int i = 0; i < pcNode.Nodes.Count; i++) if (pcNode.Nodes[i].Name == "quick") at = i + 1;
            foreach (string f in favourites)
            {
                TreeNode n = MakeNode(f, FavText(f), "fav", 3);
                n.ToolTipText = f;
                pcNode.Nodes.Insert(at++, n);
            }
            if (selWasFav) tree.SelectedNode = pcNode;
        }
        finally { tree.EndUpdate(); suppress = false; }
    }

    void RememberRecentFolder(string dir)
    {
        recentFolders.RemoveAll(x => Util.SameDir(x, dir));
        recentFolders.Insert(0, dir);
        while (recentFolders.Count > MaxRecentFolders) recentFolders.RemoveAt(recentFolders.Count - 1);
    }

    // from Go > Favourites / Recent folders
    void OpenFolderShortcut(string dir)
    {
        if (!Directory.Exists(dir)) { Warn("That folder isn't available right now (moved, deleted, or on a drive that isn't connected):\n\n" + dir); return; }
        OpenImage(dir);
    }

    static bool ClipHasFiles()
    {
        try { return Clipboard.ContainsFileDropList(); } catch (Exception) { return false; }
    }

    void ShowGridMenu(Point p, int hit)
    {
        lastPane = grid;
        bool on = hit >= 0;
        gOpen.Enabled = on;
        gRename.Enabled = on && grid.SelectedIndices().Count == 1;
        gBatch.Enabled = on;
        gCompare.Enabled = CanCompare();
        gCopy.Enabled = on;
        gCut.Enabled = on;
        gDelete.Enabled = on;
        gPaste.Enabled = grid.Dir != null && ClipHasFiles();
        gSave.Enabled = on;
        gFrames.Enabled = on;
        gInvert.Enabled = grid.Items.Count > 0;
        for (int i = 0; i < gSort.Length; i++) gSort[i].Checked = grid.SortKey == i;
        gSortDesc.Checked = grid.SortDesc;
        gDetails.Checked = grid.ShowDetails;
        gRetro.Checked = Retro.Enabled;
        gridMenu.Show(grid, p);
    }

    void OnTreeClick(object s, TreeNodeMouseClickEventArgs e)
    {
        if (e.Button != MouseButtons.Right) return;
        tree.SelectedNode = e.Node;
        lastPane = tree;
        string p = NodePath(e.Node);
        bool real = p != null, plain = real && !IsRootPath(p) && e.Node.Name != "fav";   // a favourite is a shortcut
        tNew.Enabled = real;
        tFav.Enabled = real;
        tFav.Text = real && IsFavourite(p) ? "Remove from favourites" : "Add to favourites";
        tRename.Enabled = plain;
        tCopy.Enabled = plain;
        tCut.Enabled = plain;
        tDelete.Enabled = plain;
        tPaste.Enabled = real && ClipHasFiles();
        tRetro.Checked = Retro.Enabled;
        treeMenu.Show(tree, e.Location);
    }

    void ReloadAll()
    {
        TreeNode n = tree.SelectedNode;
        if (NodePath(n) != null) ReloadNode(n);
        if (grid.Dir != null) ShowFolder(grid.Dir, null, -1, true);
    }

    string ValidateName(string name)
    {
        if (string.IsNullOrEmpty(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || name.EndsWith(".") || name.EndsWith(" "))
            return "That name isn't valid. It can't be empty, end with a dot or space, or contain any of  \\ / : * ? \" < > |";
        return null;
    }

    void Warn(string msg) { MessageBox.Show(this, msg, "RetroGleek", MessageBoxButtons.OK, MessageBoxIcon.Warning); }

    void DoRename(bool inTree)
    {
        if (inTree)
        {
            TreeNode n = tree.SelectedNode;
            string p = NodePath(n);
            if (p == null || IsRootPath(p)) return;
            string nn = Prompt.Ask(this, "Rename folder", "New name:", n.Text, false);
            if (nn == null || nn == n.Text) return;
            string bad = ValidateName(nn);
            if (bad != null) { Warn(bad); return; }
            string dest = Path.Combine(Path.GetDirectoryName(p), nn);
            if (!string.Equals(dest, p, StringComparison.OrdinalIgnoreCase) && (Directory.Exists(dest) || File.Exists(dest))) { Warn("An item with that name already exists."); return; }
            try { Directory.Move(p, dest); }
            catch (Exception ex) { Warn(ex.Message); return; }
            PushUndo("rename of " + Path.GetFileName(p.TrimEnd('\\')), false,
                     new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>(p, dest) });
            string gd = grid.Dir;
            n.Text = nn; n.Tag = dest;
            ReloadNode(n);
            if (gd != null && (Util.SameDir(gd, p) || gd.StartsWith(p.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase)))
                ShowFolder(dest + gd.Substring(p.TrimEnd('\\').Length), null, -1, true);
            return;
        }
        List<int> sel = grid.SelectedIndices();
        if (sel.Count != 1) return;
        Item it = grid.Items[sel[0]];
        string name = Prompt.Ask(this, "Rename", "New name:", it.Name, true);
        if (name == null || name == it.Name) return;
        string err = ValidateName(name);
        if (err != null) { Warn(err); return; }
        string target = Path.Combine(Path.GetDirectoryName(it.Path), name);
        if (!string.Equals(target, it.Path, StringComparison.OrdinalIgnoreCase) && (File.Exists(target) || Directory.Exists(target))) { Warn("A file with that name already exists."); return; }
        try { File.Move(it.Path, target); }
        catch (Exception ex) { Warn(ex.Message); return; }
        PushUndo("rename of " + it.Name, false, new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>(it.Path, target) });
        ShowFolder(grid.Dir, target, -1, true);
    }

    void DoCopy(bool inTree) { PutOnClipboard(inTree, false); }

    // Ctrl+X: like Copy, but marked "move" the way Explorer does it, so Paste here or in Explorer moves the files
    void DoCut(bool inTree) { PutOnClipboard(inTree, true); }

    void PutOnClipboard(bool inTree, bool cut)
    {
        var list = new StringCollection();
        if (inTree)
        {
            string p = NodePath(tree.SelectedNode);
            if (p == null || IsRootPath(p)) return;
            list.Add(p);
        }
        else foreach (int i in grid.SelectedIndices()) list.Add(grid.Items[i].Path);
        if (list.Count == 0) return;
        try
        {
            var d = new DataObject();
            d.SetFileDropList(list);                                // real Explorer-compatible clipboard format
            d.SetData("Preferred DropEffect", new MemoryStream(BitConverter.GetBytes((int)(cut ? DragDropEffects.Move : DragDropEffects.Copy))));
            Clipboard.SetDataObject(d, true, 5, 50);
            var marked = new List<string>();
            if (cut) foreach (string p in list) marked.Add(p);
            SetCut(marked);                                         // copying instead of cutting un-fades earlier cut items
            status.Text = "  " + (cut ? "Cut " : "Copied ") + list.Count + (list.Count == 1 ? " item" : " items") + " to the clipboard"
                        + (cut ? " (Paste moves " + (list.Count == 1 ? "it" : "them") + ")" : "");
        }
        catch (Exception ex) { Warn(ex.Message); }
    }

    void DoPaste(bool inTree)
    {
        string dest = inTree ? NodePath(tree.SelectedNode) : grid.Dir;
        if (dest == null || !ClipHasFiles()) return;
        var srcs = new List<string>();
        foreach (string s in Clipboard.GetFileDropList()) srcs.Add(s);
        if (srcs.Count == 0) return;
        if (ClipIsCut())
        {
            if (MoveItems(srcs, dest)) { try { Clipboard.Clear(); } catch (Exception) { } SetCut(null); }   // cut files are pasted once, as in Explorer
        }
        else CopyItems(srcs, dest);
    }

    // ---------------------------------------------------------------- faded "cut" items

    readonly HashSet<string> cutPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    // marks the items cut with Ctrl+X (null or empty: none). Pictures fade in the grid, folders turn grey in the tree.
    void SetCut(List<string> paths)
    {
        foreach (string p in cutPaths)
            foreach (TreeNode n in FindLoadedNodes(p)) n.ForeColor = Color.Empty;
        cutPaths.Clear();
        if (paths != null) foreach (string p in paths) cutPaths.Add(p.TrimEnd('\\', '/'));
        foreach (string p in cutPaths)
            foreach (TreeNode n in FindLoadedNodes(p)) if (n.Parent != null && n.Parent != pcNode) n.ForeColor = Color.Gray;
        grid.CutPaths = cutPaths;
        grid.Invalidate();
    }

    // When RetroGleek comes back to the front: if the clipboard no longer holds exactly what was cut here (something
    // else was copied, here or in another program, or Explorer pasted it), the items stop looking cut.
    protected override void OnActivated(EventArgs e)
    {
        base.OnActivated(e);
        if (cutPaths.Count == 0) return;
        bool still = false;
        try
        {
            if (ClipIsCut() && Clipboard.ContainsFileDropList())
            {
                var now = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (string p in Clipboard.GetFileDropList()) now.Add(p.TrimEnd('\\', '/'));
                still = now.SetEquals(cutPaths);
            }
        }
        catch (Exception) { still = true; }                 // clipboard busy: leave things as they are
        if (!still) SetCut(null);
    }

    // true when the files on the clipboard were cut (here or in Explorer) rather than copied
    static bool ClipIsCut()
    {
        try
        {
            IDataObject d = Clipboard.GetDataObject();
            var ms = d == null ? null : d.GetData("Preferred DropEffect") as MemoryStream;
            if (ms == null || ms.Length < 4) return false;
            byte[] b = new byte[4];
            ms.Position = 0;
            if (ms.Read(b, 0, 4) != 4) return false;
            return (BitConverter.ToInt32(b, 0) & (int)DragDropEffects.Move) != 0;
        }
        catch (Exception) { return false; }
    }

    // Copying and moving take files from local drives only, and never cloud placeholders (that would download them).
    // Returns null if the item may be used, otherwise the reason.
    static string RefuseSource(string s)
    {
        try
        {
            if (s.StartsWith("\\\\")) return "network locations are not used (RetroGleek works with local drives only).";
            string root = Path.GetPathRoot(Path.GetFullPath(s));
            if (string.IsNullOrEmpty(root) || new DriveInfo(root).DriveType == DriveType.Network) return "network drives are not used (local drives only).";
            if (File.Exists(s) && (File.GetAttributes(s) & Util.CloudMask) != 0) return "cloud-only file that isn't stored on this PC, so it was left alone.";
        }
        catch (Exception ex) { return ex.Message; }
        return null;
    }

    static bool InsideOrSame(string dest, string folder)
    {
        string f = folder.TrimEnd('\\', '/');
        return Util.SameDir(dest, f) || dest.StartsWith(f + "\\", StringComparison.OrdinalIgnoreCase);
    }

    void CopyItems(List<string> srcs, string dest)
    {
        status.Text = "  Copying " + srcs.Count + (srcs.Count == 1 ? " item" : " items") + "...";
        ThreadPool.QueueUserWorkItem(delegate            // copying never blocks the UI
        {
            var errs = new List<string>();
            foreach (string s in srcs)
            {
                try
                {
                    bool isDir = Directory.Exists(s);
                    if (!isDir && !File.Exists(s)) continue;
                    string why = RefuseSource(s);
                    if (why != null) { errs.Add(Path.GetFileName(s.TrimEnd('\\', '/')) + ": " + why); continue; }
                    string name = Path.GetFileName(s.TrimEnd('\\', '/'));
                    if (name.Length == 0) continue;
                    if (isDir && (Util.SameDir(dest, s) || dest.StartsWith(s.TrimEnd('\\', '/') + "\\", StringComparison.OrdinalIgnoreCase)))
                    { errs.Add(name + ": a folder can't be copied into itself."); continue; }
                    string target = Util.UniqueName(dest, name, isDir);   // never overwrites anything
                    if (isDir) Util.CopyDir(s, target); else File.Copy(s, target);
                }
                catch (Exception ex) { errs.Add(Path.GetFileName(s) + ": " + ex.Message); }
            }
            Util.Post(this, delegate { PasteDone(dest, errs); });
        });
    }

    // Folders that would go to another drive and hold cloud placeholders (OneDrive and the like): their path, and
    // what they hold. Windows moves a folder to another drive by copying it, which downloads every cloud-only file
    // in it first; a move on the same drive only renames, so nothing is downloaded and nothing is listed here.
    // Counting reads attributes only, so it downloads nothing itself.
    static Dictionary<string, string> CloudFoldersCrossingDrives(List<string> srcs, string dest)
    {
        var found = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        string droot = Path.GetPathRoot(Path.GetFullPath(dest));
        foreach (string raw in srcs)
        {
            string s = raw.TrimEnd('\\', '/');
            try
            {
                if (!Directory.Exists(s) || IsRootPath(s)) continue;
                if (string.Equals(Path.GetPathRoot(Path.GetFullPath(s)), droot, StringComparison.OrdinalIgnoreCase)) continue;
                int files, folders;
                bool more;
                Util.CloudInside(s, out files, out folders, out more);
                if (files + folders > 0 && !found.ContainsKey(s)) found.Add(s, Util.CloudText(files, folders) + (more ? " (or more)" : ""));
            }
            catch (Exception) { }                          // unreadable: the move itself will report the problem
        }
        return found;
    }

    // Moves files and folders into dest with Windows' own file operation (progress window for big moves, works
    // across drives). Never overwrites: a name that is taken becomes "name (2)". Runs on the UI thread, like delete.
    // A folder that would go to another drive with cloud-only files inside is moved only after you say so.
    // Returns true if at least one item was moved.
    bool MoveItems(List<string> srcs, string dest)
    {
        var errs = new List<string>();
        var touched = new List<string>();                  // folders whose contents changed
        string follow = null;                              // the shown folder moved: where it is now
        string gd = grid.Dir;
        int moved = 0;
        var undoPairs = new List<KeyValuePair<string, string>>();
        HashSet<string> leaveOut = null;                   // folders with cloud-only files that you chose to leave where they are
        Cursor = Cursors.WaitCursor;
        Dictionary<string, string> cloudy;
        try { cloudy = CloudFoldersCrossingDrives(srcs, dest); }
        finally { Cursor = Cursors.Default; }
        if (cloudy.Count > 0)
        {
            var lines = new List<string>();
            foreach (KeyValuePair<string, string> kv in cloudy)
            {
                if (lines.Count == 8) { lines.Add("  ..."); break; }
                lines.Add("  " + Path.GetFileName(kv.Key) + ":  " + kv.Value);
            }
            bool one = cloudy.Count == 1;
            string ask = "Moving to another drive means Windows copies " + (one ? "this folder" : "these folders") +
                         ", and it would first download what " + (one ? "it holds" : "they hold") +
                         " that is stored only in the cloud (OneDrive or similar):\n\n" + string.Join("\n", lines) + "\n\n" +
                         "Yes:  move anyway (Windows downloads those files; RetroGleek itself never goes online).\n" +
                         "No:  leave " + (one ? "this folder" : "these folders") + " where " + (one ? "it is" : "they are") + " and move the rest.\n" +
                         "Cancel:  move nothing.";
            DialogResult answer = MessageBox.Show(this, ask, "Cloud-only files", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Warning,
                                                  MessageBoxDefaultButton.Button2);
            if (answer == DialogResult.Cancel) return false;
            if (answer == DialogResult.No) leaveOut = new HashSet<string>(cloudy.Keys, StringComparer.OrdinalIgnoreCase);
        }
        Cursor = Cursors.WaitCursor;
        try
        {
            foreach (string raw in srcs)
            {
                string s = raw.TrimEnd('\\', '/');
                bool isDir = Directory.Exists(s);
                if (!isDir && !File.Exists(s)) continue;
                string name = Path.GetFileName(s);
                if (name.Length == 0 || IsRootPath(s)) { errs.Add(s + ": a whole drive can't be moved."); continue; }
                if (leaveOut != null && leaveOut.Contains(s)) { errs.Add(name + ": left where it is (it holds cloud-only files)."); continue; }
                string why = RefuseSource(s);
                if (why != null) { errs.Add(name + ": " + why); continue; }
                string from = Path.GetDirectoryName(s);
                if (Util.SameDir(from, dest)) continue;                            // already there
                if (isDir && InsideOrSame(dest, s)) { errs.Add(name + ": a folder can't be moved into itself."); continue; }
                if (isDir && ProtectedFolder(s) != null) { errs.Add(name + ": Windows' own folders (such as " + ProtectedFolder(s) + ") are not moved."); continue; }
                string target = isDir ? Util.UniquePath(dest, name, "")
                                      : Util.UniquePath(dest, Path.GetFileNameWithoutExtension(name), Path.GetExtension(name));
                try
                {
                    if (isDir) VBFS.MoveDirectory(s, target, VBUI.AllDialogs, VBCancel.ThrowException);
                    else VBFS.MoveFile(s, target, VBUI.AllDialogs, VBCancel.ThrowException);
                    moved++;
                    undoPairs.Add(new KeyValuePair<string, string>(s, target));
                    touched.Add(from);
                    if (isDir && gd != null && InsideOrSame(gd, s)) follow = target + gd.Substring(s.Length);
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex) { errs.Add(name + ": " + ex.Message); }
            }
        }
        finally { Cursor = Cursors.Default; }

        touched.Add(dest);
        foreach (string d in touched)
        {
            foreach (TreeNode n in FindLoadedNodes(d)) RefreshFolderNode(n);
        }
        if (follow != null) { ShowFolder(follow, null, -1, true); RevealInTree(follow); }
        else if (gd != null && (grid.Covers(dest) || touched.Exists(x => grid.Covers(x)))) grid.Rescan();
        PushUndo("move of " + (moved == 1 ? Path.GetFileName(undoPairs[0].Key) : moved + " items") + " to " + (Path.GetFileName(dest.TrimEnd('\\')).Length > 0 ? Path.GetFileName(dest.TrimEnd('\\')) : dest), true, undoPairs);
        status.Text = "  Moved " + moved + (moved == 1 ? " item" : " items") + " to " + dest + (moved > 0 ? "   (Ctrl+Z undoes it)" : "");
        if (errs.Count > 0)
        {
            if (errs.Count > 8) { errs = errs.GetRange(0, 8); errs.Add("..."); }
            Warn("Some items could not be moved:\n\n" + string.Join("\n", errs));
        }
        return moved > 0;
    }

    // ---------------------------------------------------------------- dropping onto a folder in the tree

    TreeNode dropNode;
    bool treeDragging;                                     // a folder from our own tree is being dragged

    // Dragging a folder in the tree: drop it on another folder (or in Explorer) to move / copy it.
    // Drives, the quick-access entries and Windows' own folders can't be dragged.
    void OnTreeItemDrag(object s, ItemDragEventArgs e)
    {
        var n = e.Item as TreeNode;
        string p = NodePath(n);
        if (n == null || p == null || n.Name == "quick" || n.Name == "fav" || IsRootPath(p)) return;   // shortcuts: never dragged
        if (ProtectedFolder(p) != null) { status.Text = "  " + Path.GetFileName(p) + " is a Windows folder and can't be moved"; return; }
        var list = new StringCollection();
        list.Add(p);
        var data = new DataObject();
        data.SetFileDropList(list);
        treeDragging = true;
        try { tree.DoDragDrop(data, DragDropEffects.Copy | DragDropEffects.Move); }
        catch (Exception) { }
        finally { treeDragging = false; SetDropNode(null); }
    }

    // Windows' own folders (and any folder that contains one) are never moved: returns its name, or null
    static string ProtectedFolder(string folder)
    {
        var special = new List<string>();
        Environment.SpecialFolder[] kinds =
        {
            Environment.SpecialFolder.Desktop, Environment.SpecialFolder.DesktopDirectory, Environment.SpecialFolder.MyDocuments,
            Environment.SpecialFolder.MyPictures, Environment.SpecialFolder.MyMusic, Environment.SpecialFolder.MyVideos,
            Environment.SpecialFolder.UserProfile, Environment.SpecialFolder.ApplicationData, Environment.SpecialFolder.LocalApplicationData,
            Environment.SpecialFolder.CommonApplicationData, Environment.SpecialFolder.Windows, Environment.SpecialFolder.System,
            Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86
        };
        foreach (Environment.SpecialFolder k in kinds)
        {
            try { string p = Environment.GetFolderPath(k); if (!string.IsNullOrEmpty(p)) special.Add(p); } catch (Exception) { }
        }
        try
        {
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            if (!string.IsNullOrEmpty(home)) special.Add(Path.Combine(home, "Downloads"));
        }
        catch (Exception) { }
        foreach (string p in special)
            if (InsideOrSame(p, folder)) return Path.GetFileName(p.TrimEnd('\\'));
        return null;
    }

    void SetDropNode(TreeNode n)
    {
        if (n == dropNode) return;
        if (dropNode != null) { dropNode.BackColor = Color.Empty; dropNode.ForeColor = Color.Empty; }
        dropNode = n;
        if (n != null) { n.BackColor = Color.FromArgb(60, 130, 230); n.ForeColor = Color.White; }
    }

    // Explorer's rules: same drive = move, another drive = copy; Ctrl forces copy, Shift forces move
    static DragDropEffects ChooseEffect(DragEventArgs e, string[] srcs, string dest)
    {
        bool allThere = true;
        foreach (string raw in srcs)
        {
            string s = raw.TrimEnd('\\', '/');
            if (Directory.Exists(s) && InsideOrSame(dest, s)) return DragDropEffects.None;   // into itself
            if (!Util.SameDir(Path.GetDirectoryName(s), dest)) allThere = false;
        }
        if (allThere) return DragDropEffects.None;
        bool ctrl = (e.KeyState & 8) != 0, shift = (e.KeyState & 4) != 0;
        DragDropEffects want;
        if (ctrl && !shift) want = DragDropEffects.Copy;
        else if (shift && !ctrl) want = DragDropEffects.Move;
        else want = string.Equals(Path.GetPathRoot(srcs[0]), Path.GetPathRoot(dest), StringComparison.OrdinalIgnoreCase)
                    ? DragDropEffects.Move : DragDropEffects.Copy;
        if ((e.AllowedEffect & want) == 0)
            want = (e.AllowedEffect & DragDropEffects.Copy) != 0 ? DragDropEffects.Copy
                 : (e.AllowedEffect & DragDropEffects.Move) != 0 ? DragDropEffects.Move : DragDropEffects.None;
        return want;
    }

    void OnTreeDragOver(object s, DragEventArgs e)
    {
        try
        {
            string[] srcs = e.Data.GetDataPresent(DataFormats.FileDrop) ? e.Data.GetData(DataFormats.FileDrop) as string[] : null;
            Point pt = tree.PointToClient(new Point(e.X, e.Y));
            TreeNode n = tree.GetNodeAt(pt);
            string dest = NodePath(n);
            DragDropEffects eff = srcs == null || srcs.Length == 0 || dest == null ? DragDropEffects.None : ChooseEffect(e, srcs, dest);
            e.Effect = eff;
            SetDropNode(eff != DragDropEffects.None ? n : null);

            // scroll the tree while the pointer is near its top or bottom edge
            int edge = Util.S(18);
            TreeNode top = tree.TopNode;
            if (top != null && pt.Y < edge && top.PrevVisibleNode != null) tree.TopNode = top.PrevVisibleNode;
            else if (top != null && pt.Y > tree.ClientSize.Height - edge && top.NextVisibleNode != null)
            {
                TreeNode bottom = tree.GetNodeAt(2, tree.ClientSize.Height - 2);
                if (bottom != null && bottom.NextVisibleNode != null) tree.TopNode = top.NextVisibleNode;
            }
        }
        catch (Exception) { e.Effect = DragDropEffects.None; }
    }

    void OnTreeDrop(object s, DragEventArgs e)
    {
        string[] arr = null; string dest = null;
        DragDropEffects eff = DragDropEffects.None;
        try
        {
            arr = e.Data.GetData(DataFormats.FileDrop) as string[];
            TreeNode n = tree.GetNodeAt(tree.PointToClient(new Point(e.X, e.Y)));
            dest = NodePath(n);
            if (arr != null && arr.Length > 0 && dest != null) eff = ChooseEffect(e, arr, dest);
        }
        catch (Exception) { }
        SetDropNode(null);
        if (eff == DragDropEffects.None) return;
        e.Effect = eff;
        var srcs = new List<string>(arr);
        string to = dest;
        bool move = eff == DragDropEffects.Move;
        // run after the drop has finished, so the program the files came from (maybe Explorer) isn't kept waiting
        BeginInvoke(new MethodInvoker(delegate { if (move) MoveItems(srcs, to); else CopyItems(srcs, to); }));
    }

    // ---------------------------------------------------------------- copy to / move to a folder

    // Ctrl+Shift+Y / Ctrl+Shift+M (or Edit > Copy to / Move to): the selected pictures (or the folder chosen in the
    // tree, or the picture in the viewer) go to a folder you pick, or to one of the last 8 used. The same copy and
    // move as everywhere else: nothing is overwritten, local drives only, and a move can be undone with Ctrl+Z.
    const int MaxRecentDest = 8;
    readonly List<string> recentDest = new List<string>();

    void LoadRecentDest()
    {
        recentDest.Clear();
        for (int i = 1; i <= MaxRecentDest; i++)
        {
            string p = Prefs.Get("recentDest" + i, null);
            if (!string.IsNullOrEmpty(p) && !recentDest.Exists(x => Util.SameDir(x, p))) recentDest.Add(p);
        }
    }

    void StoreRecentDest()
    {
        for (int i = 1; i <= MaxRecentDest; i++) Prefs.Set("recentDest" + i, i <= recentDest.Count ? recentDest[i - 1] : null);
    }

    void RememberDest(string dir)
    {
        recentDest.RemoveAll(x => Util.SameDir(x, dir));
        recentDest.Insert(0, dir);
        while (recentDest.Count > MaxRecentDest) recentDest.RemoveAt(recentDest.Count - 1);
        StoreRecentDest();
    }

    List<string> TransferSources()
    {
        var list = new List<string>();
        if (viewing) { string p = canvas.CurrentPath; if (p != null && File.Exists(p)) list.Add(p); return list; }
        if (lastPane == tree) { string p = NodePath(tree.SelectedNode); if (p != null && !IsRootPath(p)) list.Add(p); return list; }
        foreach (int i in grid.SelectedIndices()) list.Add(grid.Items[i].Path);
        return list;
    }

    // dest null: ask with a folder dialog
    void TransferTo(bool move, string dest)
    {
        List<string> srcs = TransferSources();
        if (srcs.Count == 0) return;
        if (comparing) return;
        string what = srcs.Count == 1 ? "\"" + Path.GetFileName(srcs[0].TrimEnd('\\')) + "\"" : srcs.Count + " items";
        if (dest == null)
        {
            using (var d = new FolderBrowserDialog())
            {
                d.Description = (move ? "Move " : "Copy ") + what + " to this folder. Nothing is ever overwritten: a name that is already taken gets a number added.";
                d.ShowNewFolderButton = true;
                string start = recentDest.Count > 0 && Directory.Exists(recentDest[0]) ? recentDest[0] : grid.Dir;
                if (start != null) d.SelectedPath = start;
                if (d.ShowDialog(this) != DialogResult.OK) return;
                dest = d.SelectedPath;
            }
        }
        if (!Directory.Exists(dest)) { Warn("That folder isn't there any more:\n" + dest); recentDest.RemoveAll(x => Util.SameDir(x, dest)); return; }
        string why = RefuseSource(dest);                      // the same local-drives-only rule as for the source
        if (why != null) { Warn("RetroGleek can't " + (move ? "move" : "copy") + " there: " + why); return; }
        RememberDest(dest);
        string place = Path.GetFileName(dest.TrimEnd('\\'));
        if (place.Length == 0) place = dest;
        if (!move)
        {
            CopyItems(srcs, dest);
            if (viewing) canvas.ShowMessage("Copying " + what + " to " + place);
            return;
        }
        string shown = viewing ? srcs[0] : null;
        bool moved = MoveItems(srcs, dest);
        if (viewing && moved && shown != null && !File.Exists(shown))
        {
            bool left = canvas.RemoveCurrent();               // the viewer moves on to the next picture
            if (!left) SetViewing(false);
            else canvas.ShowMessage("Moved " + what + " to " + place + "   (Ctrl+Z in the browser undoes it)");
        }
    }

    void PasteDone(string dest, List<string> errs)
    {
        if (grid.Covers(dest)) grid.Rescan(); else UpdateStatus();
        foreach (TreeNode n in FindLoadedNodes(dest)) RefreshFolderNode(n);
        if (errs.Count > 0)
        {
            if (errs.Count > 8) { errs = errs.GetRange(0, 8); errs.Add("..."); }
            Warn("Some items could not be copied:\n\n" + string.Join("\n", errs));
        }
    }

    void DoDelete(bool inTree)
    {
        var paths = new List<string>();
        int hint = -1;
        if (inTree)
        {
            string p = NodePath(tree.SelectedNode);
            if (p == null || IsRootPath(p)) return;
            paths.Add(p);
        }
        else
        {
            List<int> sel = grid.SelectedIndices();
            if (sel.Count > 0) hint = sel[0];
            foreach (int i in sel) paths.Add(grid.Items[i].Path);
        }
        if (paths.Count == 0) return;
        string msg = paths.Count == 1 ? "Move \"" + Path.GetFileName(paths[0]) + "\" to the Recycle Bin?"
                                      : "Move these " + paths.Count + " items to the Recycle Bin?";
        if (MessageBox.Show(this, msg, "Delete", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;

        Cursor = Cursors.WaitCursor;
        try
        {
            foreach (string p in paths)
            {
                if (Directory.Exists(p)) VBFS.DeleteDirectory(p, VBUI.OnlyErrorDialogs, VBRecycle.SendToRecycleBin);
                else VBFS.DeleteFile(p, VBUI.OnlyErrorDialogs, VBRecycle.SendToRecycleBin);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex) { Warn(ex.Message); }
        finally { Cursor = Cursors.Default; }

        if (inTree)
        {
            TreeNode parent = tree.SelectedNode.Parent;
            string pp = NodePath(parent);
            if (parent != null && pp != null)
            {
                SelectQuiet(parent);
                ReloadNode(parent);
                ShowFolder(pp, null, -1, true);
                return;
            }
        }
        if (grid.Dir != null) ShowFolder(grid.Dir, null, hint, true);
    }

    // Ctrl+F2 / Tools > Batch rename: the selected pictures, in grid order
    void DoBatchRename()
    {
        if (viewing) return;
        var paths = new List<string>();
        foreach (int i in grid.SelectedIndices()) paths.Add(grid.Items[i].Path);
        if (paths.Count == 0) return;
        List<KeyValuePair<string, string>> done = BatchRename.Show(this, paths, DarkTitle);
        if (done == null || done.Count == 0) return;
        PushUndo("batch rename of " + done.Count + (done.Count == 1 ? " picture" : " pictures"), false, done);
        ShowFolder(grid.Dir, done[0].Value, -1, true);
        status.Text = "  Renamed " + done.Count + (done.Count == 1 ? " picture" : " pictures") + "   (Ctrl+Z undoes it)";
    }

    // dark title bar for RetroGleek's own dialogs
    void DarkTitle(Form f)
    {
        try { int on = 1; DwmSetWindowAttribute(f.Handle, 20, ref on, 4); } catch (Exception) { }
    }

    void DoNewFolder()
    {
        TreeNode n = tree.SelectedNode;
        string p = NodePath(n);
        if (p == null) return;
        try
        {
            string target = Path.Combine(p, "New folder");
            for (int i = 2; Directory.Exists(target) || File.Exists(target); i++) target = Path.Combine(p, "New folder (" + i + ")");
            Directory.CreateDirectory(target);
            ReloadNode(n);
            n.Expand();
        }
        catch (Exception ex) { Warn(ex.Message); }
    }

    // ================================================================ open dialog, drag & drop, keys, fullscreen

    // ================================================================ save as PNG (lossless)

    sealed class ExportJob
    {
        public string Src;
        public string DestFile;      // exact target (single picture, overwrite already confirmed)
        public string DestDir;       // target folder (several pictures; names are made unique)
        public int Turns;            // extra clockwise quarter turns added in the viewer
        public bool FlipX, FlipY;    // mirroring added in the viewer
    }

    void DoSavePng()
    {
        List<int> sel = grid.SelectedIndices();
        if (sel.Count == 0) return;
        var jobs = new List<ExportJob>();
        foreach (int i in sel) jobs.Add(new ExportJob { Src = grid.Items[i].Path });
        SavePngJobs(jobs);
    }

    void SaveCurrentPng()
    {
        string path; int turns; bool fx, fy;
        if (!canvas.GetSaveSource(out path, out turns, out fx, out fy)) { Warn("There is no picture to save."); return; }
        SavePngJobs(new List<ExportJob> { new ExportJob { Src = path, Turns = turns, FlipX = fx, FlipY = fy } });
    }

    // Ctrl+C in the viewer: puts the picture, as you see it (rotation and mirroring included), on the clipboard.
    // Nothing is written to disk.
    void CopyCurrentPicture()
    {
        string path; int turns; bool fx, fy;
        if (!canvas.GetSaveSource(out path, out turns, out fx, out fy)) return;
        ThreadPool.QueueUserWorkItem(delegate
        {
            Bitmap bmp = null; string err = null;
            try { bmp = Exporter.Decode(path, turns, fx, fy); }
            catch (Exception ex) { err = ex.Message; }
            Bitmap b = bmp; string e2 = err;
            if (!Util.Post(this, delegate { CopyDone(b, e2); }) && b != null) b.Dispose();
        });
    }

    void CopyDone(Bitmap bmp, string err)
    {
        if (bmp == null) { Warn("The picture could not be copied:\n\n" + err); return; }
        try
        {
            var d = new DataObject();
            d.SetImage(bmp);
            Clipboard.SetDataObject(d, true, 5, 50);       // copy = true: the clipboard keeps its own copy
            canvas.ShowMessage("Picture copied to the clipboard");
        }
        catch (Exception ex) { Warn(ex.Message); }
        finally { bmp.Dispose(); }
    }

    // Del in the viewer: moves the current file to the Recycle Bin and shows the next picture
    void DeleteCurrentPicture()
    {
        string path = canvas.CurrentPath;
        if (path == null || !File.Exists(path)) return;
        bool wasSlideshow = canvas.Slideshow;
        if (wasSlideshow) canvas.StopSlideshow();
        if (MessageBox.Show(this, "Move \"" + Path.GetFileName(path) + "\" to the Recycle Bin?", "Delete",
                            MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        try { VBFS.DeleteFile(path, VBUI.OnlyErrorDialogs, VBRecycle.SendToRecycleBin); }
        catch (OperationCanceledException) { return; }
        catch (Exception ex) { Warn(ex.Message); return; }
        if (File.Exists(path)) return;                     // cancelled in the system dialog
        string dir = Path.GetDirectoryName(path);
        bool left = canvas.RemoveCurrent();
        if (!left) SetViewing(false);
        if (grid.Covers(dir)) ShowFolder(grid.Dir, left ? canvas.Want : null, -1, true);
    }

    // Ctrl+Shift+S: every frame of animated GIFs / every page of multi-page TIFFs, as separate lossless PNGs
    void DoExportFrames()
    {
        var jobs = new List<ExportJob>();
        if (viewing)
        {
            string path; int turns; bool fx, fy;
            if (!canvas.GetSaveSource(out path, out turns, out fx, out fy)) { Warn("There is no picture to export."); return; }
            jobs.Add(new ExportJob { Src = path, Turns = turns, FlipX = fx, FlipY = fy });
        }
        else foreach (int i in grid.SelectedIndices()) jobs.Add(new ExportJob { Src = grid.Items[i].Path });
        if (jobs.Count == 0) return;
        string destDir;
        using (var d = new FolderBrowserDialog())
        {
            d.Description = "Save every frame of " + (jobs.Count == 1 ? Path.GetFileName(jobs[0].Src) : "the " + jobs.Count + " selected pictures") +
                            " as lossless PNG into this folder. Existing files are never overwritten.";
            d.SelectedPath = Path.GetDirectoryName(jobs[0].Src); d.ShowNewFolderButton = true;
            if (d.ShowDialog(this) != DialogResult.OK) return;
            destDir = d.SelectedPath;
        }
        status.Text = "  Exporting frames...";
        ThreadPool.QueueUserWorkItem(delegate
        {
            int frames = 0, pictures = 0;
            string first = null;
            var single = new List<string>();
            var errs = new List<string>();
            foreach (ExportJob j in jobs)
            {
                string name = Path.GetFileName(j.Src);
                try
                {
                    string f1;
                    int n = Exporter.ExportFrames(j.Src, j.Turns, j.FlipX, j.FlipY, destDir,
                        delegate (int k, int total) { Util.Post(this, delegate { status.Text = "  Exporting " + name + ": frame " + k + " of " + total + "..."; }); },
                        out f1);
                    if (n == 0) single.Add(name);
                    else { frames += n; pictures++; if (first == null) first = f1; }
                }
                catch (Exception ex) { errs.Add(name + ": " + ex.Message); }
            }
            Util.Post(this, delegate { ExportFramesDone(frames, pictures, first, destDir, single, errs); });
        });
    }

    void ExportFramesDone(int frames, int pictures, string first, string destDir, List<string> single, List<string> errs)
    {
        status.Text = "  Saved " + frames + (frames == 1 ? " frame" : " frames") + " from " + pictures + (pictures == 1 ? " picture" : " pictures") +
                      " as PNG   |   " + destDir;
        if (first != null && !viewing && grid.Covers(destDir)) grid.Rescan();
        var msg = new List<string>();
        if (single.Count > 0)
        {
            List<string> s = single.Count > 8 ? single.GetRange(0, 8) : single;
            msg.Add((pictures == 0 ? "Nothing was exported: " : "Skipped, ") + (single.Count == 1 ? "this picture has" : "these pictures have") +
                    " only one frame (use Save as PNG, Ctrl+S, for those):\n" + string.Join("\n", s) + (single.Count > 8 ? "\n..." : ""));
        }
        if (errs.Count > 0)
        {
            List<string> e = errs.Count > 8 ? errs.GetRange(0, 8) : errs;
            msg.Add("Some pictures could not be exported:\n" + string.Join("\n", e) + (errs.Count > 8 ? "\n..." : ""));
        }
        if (msg.Count > 0) Warn(string.Join("\n\n", msg));
    }

    // Ctrl+Shift+A / Tools > Folder audit: every picture file in the open folder (not subfolders) checked and listed
    // in one self-contained HTML page, saved where the user chooses
    bool auditBusy;

    void DoAudit(bool thumbs)
    {
        string dir = grid.Dir;
        if (dir == null || auditBusy) return;
        string dest;
        using (var d = new SaveFileDialog())
        {
            d.Title = "Save the folder audit report";
            d.Filter = "Web page (offline)|*.html";
            d.DefaultExt = "html"; d.AddExtension = true; d.OverwritePrompt = true;
            d.InitialDirectory = dir;
            d.FileName = FolderAudit.DefaultFileName(dir, thumbs, false);
            if (d.ShowDialog(this) != DialogResult.OK) return;
            dest = d.FileName;
        }
        auditBusy = true;
        status.Text = "  Auditing " + dir + "...";
        DateTime when = DateTime.Now;
        ThreadPool.QueueUserWorkItem(delegate
        {
            string err = null;
            int pictures = 0, failed = 0, skipped = 0;
            try
            {
                List<AuditEntry> list = FolderAudit.Scan(dir, thumbs,
                    delegate (int i, int n, string name) { Util.Post(this, delegate { status.Text = "  Auditing " + i + " of " + n + ": " + name; }); },
                    out skipped);
                pictures = list.Count;
                foreach (AuditEntry e in list) if (e.Status == "Failed") failed++;
                string html = FolderAudit.Page(dir, list, skipped, when, thumbs);
                FolderAudit.WriteReport(dest, html, false, true);          // the user agreed to replace an old one
            }
            catch (Exception ex) { err = ex.Message; }
            Util.Post(this, delegate { AuditDone(dest, pictures, failed, err); });
        });
    }

    // Tools > Contact sheet: lossless PNG index sheets of the selected pictures (at most 2,000; 100 per page)
    bool sheetBusy;

    void DoContactSheet()
    {
        if (viewing || sheetBusy) return;
        var paths = new List<string>();
        foreach (int i in grid.SelectedIndices()) if (!grid.Items[i].Offline) paths.Add(grid.Items[i].Path);
        if (paths.Count == 0) { Warn("Select the pictures for the contact sheet first (Ctrl+A selects them all)."); return; }
        if (paths.Count > ContactSheet.MaxPictures)
        {
            Warn(paths.Count + " pictures are selected. A contact sheet takes at most " + ContactSheet.MaxPictures + " (20 pages of 100), " +
                 "so it stays quick to make and to open. Select fewer, or use the folder audit report (Ctrl+Shift+A) for a whole collection.");
            return;
        }
        string chosen; bool overwrite;
        SheetOptions o = ContactSheet.Ask(this, paths.Count, grid.Dir, DarkTitle, out chosen, out overwrite);
        if (o == null) return;
        string destDir = Path.GetDirectoryName(chosen);
        string why = RefuseSource(destDir);
        if (why != null) { Warn("The contact sheet can't be saved there: " + why); return; }
        long low, high, px;
        ContactSheet.Estimate(paths.Count, o.Size, out low, out high, out px);
        try
        {
            var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(chosen)));
            if (drive.IsReady && drive.AvailableFreeSpace < high + 64L * 1024 * 1024)
            {
                Warn("There may not be enough free space on " + drive.Name + " (" + ContactSheet.Mb(drive.AvailableFreeSpace) + " free; the sheets need up to " +
                     ContactSheet.Mb(high) + "). Nothing was written.");
                return;
            }
        }
        catch (Exception) { }
        sheetBusy = true;
        string title = grid.Dir ?? "";
        status.Text = "  Making the contact sheet...";
        ThreadPool.QueueUserWorkItem(delegate
        {
            List<string> written = null;
            string err = null;
            var errs = new List<string>();
            int lastTick = 0;
            try
            {
                written = ContactSheet.Make(paths, title, o, chosen, overwrite, delegate (int k, int n, int pg, int pages)
                {
                    if (Environment.TickCount - lastTick < 150 && k < n) return;           // no flood of status updates
                    lastTick = Environment.TickCount;
                    Util.Post(this, delegate { status.Text = "  Contact sheet: picture " + k + " of " + n + (pages > 1 ? " (page " + pg + " of " + pages + ")" : "") + "..."; });
                }, errs);
            }
            catch (Exception ex) { err = ex.Message; }
            Util.Post(this, delegate { SheetDone(written, err, errs); });
        });
    }

    void SheetDone(List<string> written, string err, List<string> errs)
    {
        sheetBusy = false;
        int n = written == null ? 0 : written.Count;
        if (n > 0)
        {
            status.Text = "  Saved the contact sheet: " + n + (n == 1 ? " page" : " pages") + "   |   " + written[0] + (n > 1 ? "  ..." : "");
            if (!viewing && grid.Covers(Path.GetDirectoryName(written[0]))) grid.Rescan();
        }
        else UpdateStatus();
        var msg = new List<string>();
        if (err != null) msg.Add("The contact sheet could not be finished" + (n > 0 ? " (" + n + " pages were saved)" : "") + ":\n" + err);
        if (errs.Count > 0)
        {
            List<string> e = errs.Count > 8 ? errs.GetRange(0, 8) : errs;
            msg.Add("These pictures could not be opened (they are marked on the sheet):\n" + string.Join("\n", e) + (errs.Count > 8 ? "\n..." : ""));
        }
        if (msg.Count > 0) Warn(string.Join("\n\n", msg));
    }

    // ---------------------------------------------------------------- lossless JPEG turn (changes files, always asks)

    bool rotateBusy;

    // turns = clockwise quarter turns: the selected JPEG photos (browser) or the photo shown (viewer)
    void RotateFiles(int turns)
    {
        turns &= 3;
        if (turns == 0 || comparing || rotateBusy) return;
        var paths = new List<string>();
        if (viewing) { string p = canvas.CurrentPath; if (p != null) paths.Add(p); }
        else foreach (int i in grid.SelectedIndices()) if (!grid.Items[i].Offline) paths.Add(grid.Items[i].Path);
        if (paths.Count == 0) return;
        List<string> jpegs = paths.FindAll(JpegRotate.IsJpeg);
        if (jpegs.Count == 0)
        {
            Warn("Only JPEG photos can be turned on disk without loss." + (viewing ? "\n\nR and L turn the view; Save as PNG (Ctrl+S) keeps that turn in a lossless PNG copy." : ""));
            return;
        }
        string how = turns == 1 ? "90 degrees clockwise" : turns == 3 ? "90 degrees counter-clockwise" : "180 degrees";
        string what = jpegs.Count == 1 ? "\"" + Path.GetFileName(jpegs[0]) + "\"" : jpegs.Count + " JPEG photos";
        string msg = "Turn " + what + " " + how + "?\n\n" +
                     "This changes " + (jpegs.Count == 1 ? "the file" : "the files") + " on disk, without re-compressing, so no quality is lost: " +
                     "photos with an orientation tag just get a new tag value, others are turned block by block (only when their size allows it; " +
                     "otherwise they are left alone). Each new file is checked before it replaces the old one." +
                     (paths.Count > jpegs.Count ? "\n\n" + (paths.Count - jpegs.Count) + " other selected pictures are not JPEGs and are left alone." : "");
        if (MessageBox.Show(this, msg, "Turn the file", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        rotateBusy = true;
        status.Text = "  Turning " + what + "...";
        if (viewing) canvas.ShowMessage("Turning " + what + "...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            int done = 0;
            var errs = new List<string>();
            foreach (string p in jpegs)
            {
                try
                {
                    var fi = new FileInfo(p);
                    long oldSize = fi.Length, oldMod = fi.LastWriteTimeUtc.Ticks;
                    JpegRotate.Rotate(p, turns);
                    Marks.Rebind(p, oldSize, oldMod);              // ratings, labels and tags stay with the photo
                    done++;
                }
                catch (Exception ex) { errs.Add(Path.GetFileName(p) + ": " + Util.Why(ex)); }
            }
            int d2 = done;
            Util.Post(this, delegate { RotateDone(d2, errs); });
        });
    }

    void RotateDone(int done, List<string> errs)
    {
        rotateBusy = false;
        if (viewing) { canvas.Reload(); if (done > 0) canvas.ShowMessage("Turned and saved (lossless)"); }
        else if (grid.Dir != null) grid.Rescan();
        status.Text = "  Turned " + done + (done == 1 ? " photo" : " photos") + " (lossless)" + (errs.Count > 0 ? ", " + errs.Count + " left as they were" : "");
        if (errs.Count > 0)
        {
            List<string> e = errs.Count > 8 ? errs.GetRange(0, 8) : errs;
            Warn((done > 0 ? "Some photos were left as they were:" : "Nothing was turned:") + "\n\n" + string.Join("\n", e) + (errs.Count > 8 ? "\n..." : ""));
        }
    }

    // ---------------------------------------------------------------- converting to a retro format (new files only)

    bool convertBusy;

    // Ctrl+Shift+E / Tools > Convert to a retro format: the selected pictures (browser) or the picture shown (viewer)
    // become new files in a retro format (RetroConvert). The originals are never changed; nothing is overwritten.
    void DoConvert()
    {
        if (comparing || convertBusy) return;
        var paths = new List<string>();
        if (viewing) { string p = canvas.CurrentPath; if (p != null && File.Exists(p)) paths.Add(p); }
        else foreach (int i in grid.SelectedIndices()) if (!grid.Items[i].Offline) paths.Add(grid.Items[i].Path);
        if (paths.Count == 0) { Warn("Select the pictures to convert first (Ctrl+A selects them all)."); return; }
        ConvertOptions o = RetroConvert.Ask(this, paths, Path.GetDirectoryName(paths[0]), DarkTitle);
        if (o == null) return;
        string why = RefuseSource(o.DestDir);                // local drives only, as for every other file operation
        if (why != null) { Warn("RetroGleek can't save there: " + why); return; }
        convertBusy = true;
        status.Text = "  Converting " + paths.Count + (paths.Count == 1 ? " picture" : " pictures") + "...";
        if (viewing) canvas.ShowMessage("Converting...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            int done = 0, k = 0;
            string last = null;
            var errs = new List<string>();
            foreach (string p in paths)
            {
                k++;
                int kk = k;
                Util.Post(this, delegate { status.Text = "  Converting " + kk + " of " + paths.Count + "..."; });
                try { last = RetroConvert.ConvertFile(p, o); done++; }
                catch (Exception ex) { errs.Add(Path.GetFileName(p) + ": " + Util.Why(ex)); }
            }
            int d2 = done;
            string l2 = last;
            Util.Post(this, delegate { ConvertDone(d2, paths.Count, l2, o.DestDir, errs); });
        });
    }

    void ConvertDone(int done, int total, string last, string destDir, List<string> errs)
    {
        convertBusy = false;
        status.Text = "  Converted " + done + " of " + total + (total == 1 ? " picture" : " pictures") + "   |   " + destDir;
        if (viewing) canvas.ShowMessage(done > 0 ? "Converted: " + Path.GetFileName(last) : "Nothing was converted");
        else if (done > 0 && grid.Covers(destDir)) grid.Rescan();
        if (errs.Count > 0)
        {
            List<string> e = errs.Count > 8 ? errs.GetRange(0, 8) : errs;
            Warn((done > 0 ? "Some pictures could not be converted:" : "Nothing was converted:") + "\n\n" + string.Join("\n", e) + (errs.Count > 8 ? "\n..." : ""));
        }
    }

    // ---------------------------------------------------------------- star ratings into the files (changes files, always asks)

    bool ratingBusy;

    // Edit > Rating > Write my ratings into the files: your RetroGleek star rating is copied into the selected JPEG
    // and PNG files (browser) or the picture shown (viewer), so other programs see it. Pictures without a RetroGleek
    // rating, and other formats, are left alone. Marks stay with the files (their size and date change).
    void WriteRatingsToFiles()
    {
        if (comparing || ratingBusy) return;
        var paths = new List<string>();
        if (viewing) { string p = canvas.CurrentPath; if (p != null) paths.Add(p); }
        else foreach (int i in grid.SelectedIndices()) if (!grid.Items[i].Offline) paths.Add(grid.Items[i].Path);
        if (paths.Count == 0) return;
        var jobs = new List<KeyValuePair<string, int>>();
        int unrated = 0, otherFormat = 0;
        foreach (string p in paths)
        {
            if (!RatingWriter.CanWrite(p)) { otherFormat++; continue; }
            Mark m = Marks.ForFile(p);
            if (m == null || m.Stars == 0) { unrated++; continue; }
            jobs.Add(new KeyValuePair<string, int>(p, m.Stars));
        }
        string left = (unrated > 0 ? "\n\n" + unrated + (unrated == 1 ? " picture has" : " pictures have") + " no RetroGleek rating and " + (unrated == 1 ? "is" : "are") + " left alone." : "") +
                      (otherFormat > 0 ? "\n\n" + otherFormat + (otherFormat == 1 ? " picture is" : " pictures are") + " not JPEG or PNG and " + (otherFormat == 1 ? "is" : "are") + " left alone." : "");
        if (jobs.Count == 0)
        {
            Warn("There is nothing to write: ratings are written into JPEG and PNG files that you have rated in RetroGleek (Alt+1 .. Alt+5)." + left);
            return;
        }
        string what = jobs.Count == 1 ? "\"" + Path.GetFileName(jobs[0].Key) + "\" (" + Marks.Describe(new Mark { Stars = jobs[0].Value }) + ")" : jobs.Count + " pictures";
        string msg = "Write your star rating into " + what + "?\n\n" +
                     "This changes " + (jobs.Count == 1 ? "the file" : "the files") + " on disk, so Windows Explorer, Lightroom and other programs can see the rating. " +
                     "Only the information block changes (XMP, and the Windows rating tags if there are any); the picture data is copied byte for byte, " +
                     "so no quality is lost. Each new file is checked before it replaces the old one. Colour labels and tags stay in RetroGleek only." + left;
        if (MessageBox.Show(this, msg, "Write ratings into the files", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        ratingBusy = true;
        status.Text = "  Writing ratings into " + what + "...";
        if (viewing) canvas.ShowMessage("Writing the rating into the file...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            int done = 0;
            var errs = new List<string>();
            foreach (KeyValuePair<string, int> j in jobs)
            {
                try
                {
                    var fi = new FileInfo(j.Key);
                    long oldSize = fi.Length, oldMod = fi.LastWriteTimeUtc.Ticks;
                    RatingWriter.Write(j.Key, j.Value);
                    Marks.Rebind(j.Key, oldSize, oldMod);           // ratings, labels and tags stay with the file
                    done++;
                }
                catch (Exception ex) { errs.Add(Path.GetFileName(j.Key) + ": " + Util.Why(ex)); }
            }
            int d2 = done;
            Util.Post(this, delegate { RatingsDone(d2, errs); });
        });
    }

    void RatingsDone(int done, List<string> errs)
    {
        ratingBusy = false;
        if (viewing) { canvas.Reload(); if (done > 0) canvas.ShowMessage("Rating written into the file"); }
        else if (grid.Dir != null) grid.Rescan();
        UpdatePreview();
        status.Text = "  Wrote the rating into " + done + (done == 1 ? " file" : " files") + (errs.Count > 0 ? ", " + errs.Count + " left as they were" : "");
        if (errs.Count > 0)
        {
            List<string> e = errs.Count > 8 ? errs.GetRange(0, 8) : errs;
            Warn((done > 0 ? "Some files were left as they were:" : "Nothing was written:") + "\n\n" + string.Join("\n", e) + (errs.Count > 8 ? "\n..." : ""));
        }
    }

    void AuditDone(string dest, int pictures, int failed, string err)
    {
        auditBusy = false;
        if (err != null) { UpdateStatus(); Warn("The audit could not be saved:\n\n" + err); return; }
        status.Text = "  Audit saved: " + pictures + (pictures == 1 ? " picture file" : " picture files") +
                      (failed > 0 ? ", " + failed + " could not be opened" : "") + "   |   " + dest;
        MessageBox.Show(this, "The folder audit was saved as\n\n" + dest + "\n\n" + pictures + (pictures == 1 ? " picture file" : " picture files") +
                        " checked" + (failed > 0 ? ", " + failed + " could not be opened" : "") + ".\n\n" +
                        "Double-click the file to open it in your web browser. It works offline and loads nothing from the internet.",
                        "Folder audit", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    void SavePngJobs(List<ExportJob> jobs)
    {
        string firstDir = Path.GetDirectoryName(jobs[0].Src);
        if (jobs.Count == 1)
        {
            using (var d = new SaveFileDialog())
            {
                d.Title = "Save as PNG (lossless)";
                d.Filter = "PNG image (lossless)|*.png";
                d.DefaultExt = "png"; d.AddExtension = true; d.OverwritePrompt = true;
                d.InitialDirectory = firstDir;
                d.FileName = Path.GetFileNameWithoutExtension(jobs[0].Src) + ".png";
                if (d.ShowDialog(this) != DialogResult.OK) return;
                jobs[0].DestFile = d.FileName;
            }
        }
        else
        {
            using (var d = new FolderBrowserDialog())
            {
                d.Description = "Save " + jobs.Count + " pictures as lossless PNG into this folder. Existing files are never overwritten.";
                d.SelectedPath = firstDir; d.ShowNewFolderButton = true;
                if (d.ShowDialog(this) != DialogResult.OK) return;
                foreach (ExportJob j in jobs) j.DestDir = d.SelectedPath;
            }
        }
        StartExport(jobs);
    }

    // decoding, encoding and verifying run on a background thread, so the window stays responsive
    void StartExport(List<ExportJob> jobs)
    {
        status.Text = "  Saving PNG...";
        ThreadPool.QueueUserWorkItem(delegate
        {
            int ok = 0;
            string last = null;
            var errs = new List<string>();
            for (int i = 0; i < jobs.Count; i++)
            {
                ExportJob j = jobs[i];
                int n = i + 1;
                Util.Post(this, delegate { status.Text = "  Saving PNG " + n + " of " + jobs.Count + "..."; });
                try
                {
                    using (Bitmap bmp = Exporter.Decode(j.Src, j.Turns, j.FlipX, j.FlipY))
                    {
                        string dest = j.DestFile != null ? j.DestFile
                                    : Util.UniquePath(j.DestDir, Path.GetFileNameWithoutExtension(j.Src), ".png");
                        Exporter.SavePng(bmp, dest, j.DestFile != null);
                        last = dest; ok++;
                    }
                }
                catch (Exception ex) { errs.Add(Path.GetFileName(j.Src) + ": " + ex.Message); }
            }
            Util.Post(this, delegate { ExportDone(ok, jobs.Count, last, errs); });
        });
    }

    void ExportDone(int ok, int total, string last, List<string> errs)
    {
        status.Text = "  Saved " + ok + " of " + total + (total == 1 ? " picture" : " pictures") + " as PNG" +
                      (last != null ? "   |   " + Path.GetDirectoryName(last) : "");
        if (last != null && !viewing && grid.Covers(Path.GetDirectoryName(last)))
            ShowFolder(grid.Dir, ok == 1 ? last : null, -1, true);               // show the new file(s)
        if (errs.Count > 0)
        {
            if (errs.Count > 8) { errs = errs.GetRange(0, 8); errs.Add("..."); }
            Warn("Some pictures could not be saved:\n\n" + string.Join("\n", errs));
        }
    }

    // ================================================================ address bar, history, filter, sort

    // dir: 0 = left, 1 = right, 2 = up. The arrow is drawn here, so it never depends on a font having arrow characters,
    // and a disabled button is visibly dimmed.
    Button NavButton(int dir, string tooltip, EventHandler click)
    {
        var b = new Button
        {
            Dock = DockStyle.Left, Width = Util.S(34), TabStop = false, FlatStyle = FlatStyle.Flat,
            BackColor = Color.FromArgb(52, 52, 52), ForeColor = Color.Gainsboro
        };
        b.FlatAppearance.BorderSize = 0;
        b.FlatAppearance.MouseOverBackColor = Color.FromArgb(72, 72, 72);
        b.Click += click;
        b.EnabledChanged += delegate { b.Invalidate(); };
        b.Paint += delegate (object sender, PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float cx = b.ClientSize.Width / 2f, cy = b.ClientSize.Height / 2f, r = Math.Min(b.ClientSize.Width, b.ClientSize.Height) * 0.27f;
            float dx = dir == 0 ? -1f : dir == 1 ? 1f : 0f, dy = dir == 2 ? -1f : 0f;          // direction the arrow points
            PointF tip = new PointF(cx + dx * r, cy + dy * r), tail = new PointF(cx - dx * r, cy - dy * r);
            PointF h1 = new PointF(tip.X - dx * r * 0.85f - dy * r * 0.85f, tip.Y - dy * r * 0.85f + dx * r * 0.85f);
            PointF h2 = new PointF(tip.X - dx * r * 0.85f + dy * r * 0.85f, tip.Y - dy * r * 0.85f - dx * r * 0.85f);
            using (var pen = new Pen(b.Enabled ? Color.Gainsboro : Color.FromArgb(100, 100, 100), Math.Max(1.6f, Util.K * 2f)))
            {
                pen.StartCap = LineCap.Round; pen.EndCap = LineCap.Round; pen.LineJoin = LineJoin.Round;
                g.DrawLine(pen, tail, tip);
                g.DrawLines(pen, new[] { h1, tip, h2 });
            }
        };
        navTip.SetToolTip(b, tooltip);
        return b;
    }

    static Label Spacer(int w) { return new Label { Dock = DockStyle.Left, Width = Util.S(w) }; }

    static string ParentDir(string d)
    {
        if (string.IsNullOrEmpty(d)) return null;
        string t = d.TrimEnd('\\', '/');
        return t.Length == 0 ? null : Path.GetDirectoryName(t);       // null for a drive root
    }

    void UpdateNavButtons()
    {
        btnBack.Enabled = hpos > 0;
        btnFwd.Enabled = hpos >= 0 && hpos < hist.Count - 1;
        btnUp.Enabled = ParentDir(grid.Dir) != null;
    }

    // every folder that finishes loading is remembered, except when we got there by going back / forward
    void RecordHistory(string dir)
    {
        if (pendingNav != null && Util.SameDir(pendingNav, dir)) { pendingNav = null; return; }
        if (hpos >= 0 && Util.SameDir(hist[hpos], dir)) return;
        if (hpos < hist.Count - 1) hist.RemoveRange(hpos + 1, hist.Count - hpos - 1);
        hist.Add(dir);
        if (hist.Count > 100) hist.RemoveAt(0);
        hpos = hist.Count - 1;
    }

    void GoHistory(int delta)
    {
        int n = hpos + delta;
        if (n < 0 || n >= hist.Count) return;
        hpos = n;
        pendingNav = hist[n];
        ShowFolder(hist[n], null, -1, false);
        RevealInTree(hist[n]);
        UpdateNavButtons();
    }

    void GoUp()
    {
        string p = ParentDir(grid.Dir);
        if (p == null) return;
        ShowFolder(p, null, -1, false);
        RevealInTree(p);
    }

    void FocusAddress() { addrBox.Focus(); addrBox.SelectAll(); }

    void RestoreAddress() { addrBox.Text = grid.Dir ?? ""; }

    // Local folders and files only: network paths are never opened from here.
    void CommitAddress()
    {
        string t = Environment.ExpandEnvironmentVariables(addrBox.Text.Trim().Trim('"'));
        if (t.Length == 0) { RestoreAddress(); return; }
        try
        {
            if (t.StartsWith("\\\\") || t.StartsWith("//")) { Warn("Only local drives are supported; network paths are not opened."); RestoreAddress(); return; }
            string full = Path.GetFullPath(t);
            DriveType dt = new DriveInfo(Path.GetPathRoot(full)).DriveType;
            if (dt != DriveType.Fixed && dt != DriveType.Removable && dt != DriveType.CDRom) { Warn("Only local drives are supported."); RestoreAddress(); return; }
            if (Directory.Exists(full)) { ShowFolder(full, null, -1, false); RevealInTree(full); grid.Focus(); }
            else if (File.Exists(full)) { OpenImage(full); }
            else { Warn("That folder doesn't exist:\n" + full); RestoreAddress(); }
        }
        catch (Exception ex) { Warn(ex.Message); RestoreAddress(); }
    }

    void AddrKeyDown(object s, KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; CommitAddress(); }
        else if (e.Control && e.KeyCode == Keys.A) { e.SuppressKeyPress = true; addrBox.SelectAll(); }
    }

    void FilterKeyDown(object s, KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Enter || e.KeyCode == Keys.Down) { e.SuppressKeyPress = true; grid.Focus(); }
        else if (e.Control && e.KeyCode == Keys.A) { e.SuppressKeyPress = true; filterBox.SelectAll(); }
    }

    // the filter box is always visible: Ctrl+F jumps to it, Esc clears it
    void ShowFilter()
    {
        filterBox.Focus();
        filterBox.SelectAll();
    }

    void CloseFilter()
    {
        filterBox.Text = "";                  // clears the filter through TextChanged
        grid.Focus();
    }

    // keep the sort pull-down and direction arrow in step with changes made elsewhere (right-click menu, reverse button)
    void SyncSortControls()
    {
        suppressSort = true;
        try { if (sortCombo.SelectedIndex != grid.SortKey) sortCombo.SelectedIndex = grid.SortKey; }
        finally { suppressSort = false; }
        sortDirBtn.Invalidate();
    }

    // choosing the current sort again reverses it; date and size start with newest / largest first
    void ChooseSort(int key)
    {
        bool desc = key == grid.SortKey ? !grid.SortDesc : (key == 1 || key == 2 || key == 5 || key == 9);
        grid.SetSort(key, desc);
    }

    void ToggleRetro()
    {
        Retro.Enabled = !Retro.Enabled;
        ReloadAll();
    }

    // F1: every shortcut on one page, followed by the About / credits text
    void ShowHelp()
    {
        string nl = "\r\n";
        string text = string.Join(nl, new[] {
            "RETROGLEEK - KEYS AND MOUSE",
            "",
            "EVERYWHERE",
            "  F1                      this help",
            "  Alt                     the menu bar (File, Edit, View, Effects, Go, Tools, Settings, Help)",
            "  F11                     fullscreen",
            "  Ctrl+O                  open a picture or folder",
            "  Drag & drop             open a dropped file or folder",
            "",
            "BROWSER (folder tree and thumbnails)",
            "  Double-click / Enter    open the picture in the viewer",
            "  Arrows, Home / End,     move; Shift or Ctrl for multi-select",
            "    PgUp / PgDn",
            "  Drag with the mouse     rubber-band select (Ctrl adds to the selection)",
            "  Ctrl+A / Ctrl+I         select all / invert the selection",
            "  Mouse wheel             scroll;  Ctrl + wheel or the Size slider: thumbnail size",
            "  Ctrl+F                  filter box (* and ? wildcards, spaces mean AND); Esc clears",
            "  Alt+P                   preview pane: a large preview and facts about the focused picture, right of the list",
            "  Ctrl+Shift+D            details list (name, type, platform, dimensions, frames, colours, size, date, status);",
            "  Tools > Analyse folder  fills in frames, colours and duplicates in the details list",
            "                          click a column title to sort by it, again to reverse",
            "  Ctrl+Shift+F            Subfolders switch: also list pictures in all folders below this one",
            "                          (turns off again when you open another folder or drive)",
            "  Ctrl+L                  address bar: type or paste a local path, Enter",
            "  Alt+Left / Alt+Right    back / forward",
            "  Ctrl+D                  add the open folder to the favourites (or remove it); Go > Favourites, Recent folders",
            "  Alt+Up or Backspace     up one folder",
            "  Ctrl+Z                  undo the last rename, batch rename or move (up to 20 steps)",
            "  Alt+0 .. Alt+5          rating: 1 to 5 stars (Alt+0 removes it); also in the viewer and slideshow",
            "  Shift+0 .. Shift+5      colour label: red, yellow, green, blue, purple (Shift+0 removes it)",
            "  X                       tag / untag;  the Show pull-down lists only tagged, rated or labelled pictures",
            "                          (marks are kept in marks.tsv next to settings.ini, never in the pictures)",
            "                          ratings stored in photos by Windows / Lightroom show in silver (read only)",
            "  Edit > Rating > Write my ratings into the files   copies your stars into JPEG / PNG files (asks first)",
            "  F2                      rename",
            "  Ctrl+F2                 batch rename the selection (pattern such as holiday_###, with a preview)",
            "  Ctrl+Shift+C            compare the 2 selected pictures side by side (zoom and panning linked;",
            "                          rotate / flip / grid / info apply to both; Esc goes back)",
            "  Tools > Contact sheet   lossless PNG index sheets of the selection (100 per page, at most 2,000)",
            "  Ctrl+Shift+E            convert the selection (or the picture in the viewer) to a retro format:",
            "                          ZX Spectrum .scr, C64 Koala .koa / Doodle .dd, Amstrad CPC .scr (mode 0 / 1),",
            "                          Atari ST Degas .pi1, Amiga IFF .iff, MSX .sc2 / .sc8;",
            "                          new files only, each checked with RECOIL (also in the viewer)",
            "  Ctrl+Shift+A            folder audit: an offline HTML report of every picture file in this folder",
            "                          (platform, type, size, colours, duplicates, files that could not be opened)",
            "  Ctrl+C / Ctrl+X / Ctrl+V   copy / cut / paste files (cut + paste moves them; works with Explorer too)",
            "  Ctrl+Shift+Y / Ctrl+Shift+M   copy / move the selection to a folder (Edit > Copy to / Move to: the last 8)",
            "  Drag selected pictures  onto a folder in the tree (or into Explorer): same drive moves, another",
            "                          drive copies; hold Ctrl to copy, Shift to move",
            "  Drag a folder in the tree   onto another folder: moves / copies it the same way",
            "  Del                     delete (to the Recycle Bin)",
            "  F5                      refresh (the folder tree and the open folder also refresh by themselves)",
            "  Ctrl+S                  save the selection as lossless PNG",
            "  Ctrl+Shift+S            save every frame of animated GIFs and WebPs / pages of TIFFs as separate PNGs",
            "  Ctrl+Shift+R / L        turn the selected JPEG photos on disk, without loss (asks first; also in the viewer)",
            "  F8                      show / hide retro-computer formats",
            "  Right-click             menu: sort, details on tiles, invert selection ...",
            "",
            "VIEWER",
            "  Left / Right, PgUp / PgDn, Space / Backspace, wheel   previous / next picture",
            "  Home / End              first / last picture",
            "  Ctrl + wheel, + / -     zoom (whole-number steps above 100%)",
            "  2 .. 9                  200% .. 900%",
            "  1  /  0                 actual size / fit this picture;  double-click toggles",
            "  F                       Fit-to-Screen on / off for every picture (remembered)",
            "  Click and drag          pan",
            "  R / L                   rotate clockwise / counter-clockwise",
            "  H / V                   flip left-right / top-bottom",
            "  B                       checkerboard behind transparent pictures",
            "  O                       screen effects off / on (compare with the picture as decoded)",
            "  A                       automatic effects: the usual screen of each picture's computer (A again: your own)",
            "  Ctrl+1 .. Ctrl+9        use a saved screen effects preset (Effects > Save these effects as a preset)",
            "  T                       True TV aspect: pixels shaped as on the original PAL / NTSC screen (retro)",
            "  K                       scanlines: off / light / medium / strong (retro, shown from about 300%)",
            "  C                       video signal: RGB / S-Video / composite (retro; composite blends dithering)",
            "  M                       phosphor mask: off / aperture grille / slot mask / dot mask (retro, from 200%)",
            "  W                       glow: off / soft / strong (bright areas light up their surroundings; retro)",
            "  U                       screen curvature: off / slight / strong, darker rounded corners (retro, below 800%)",
            "  G                       pixel grid (at 800% and above)",
            "  J                       filmstrip: thumbnails of the folder along the bottom; click one to show it",
            "  Z (hold)                loupe: a magnifier around the pointer, 4 times the current size",
            "  N                       crisp / sharp / smooth enlargement",
            "  I                       info bar (x, y and colour under the pointer)",
            "  E                       EXIF details (camera, exposure, date ...)",
            "  P                       pause / play an animated GIF or WebP",
            "  ,  /  .                 previous / next frame of an animated GIF or WebP",
            "  S                       slideshow;  Up / Down change the interval",
            "  Alt+0..5 / Shift+0..5 / X   rate / colour-label / tag the picture (Settings: move on to the next one)",
            "  Ctrl+C                  copy the picture to the clipboard",
            "  Ctrl+S                  save the picture as lossless PNG (first frame of an animation)",
            "  Ctrl+Shift+S            save every frame / page of the picture as separate PNGs",
            "  Del                     delete the picture (to the Recycle Bin)",
            "  Enter                   fullscreen",
            "  Esc                     stop the slideshow / leave fullscreen / back to the browser",
            "",
            "",
            "ABOUT",
            "RetroGleek - offline image browser and viewer",
            "Copyright (c) 2026 Mark Billson. Released under the MIT License.",
            "No network access and no telemetry. Files are only written when you save, copy, move, rename or delete,",
            "plus settings.ini next to RetroGleek.exe when it closes (delete it, or Settings > Reset, for the defaults).",
            "",
            "Retro-computer pictures are decoded by RECOIL " + Recoil.RECOIL.Version,
            Recoil.RECOIL.Credits.Trim().Replace("\r\n", "\n").Replace("\n", nl),
            Recoil.RECOIL.License.Replace("\r\n", "\n").Replace("\n", nl)
        });
        using (var f = new Form())
        {
            f.AutoScaleMode = AutoScaleMode.None;
            f.Text = "RetroGleek - help";
            f.StartPosition = FormStartPosition.CenterParent;
            f.ShowInTaskbar = false; f.MinimizeBox = false;
            f.BackColor = Color.FromArgb(38, 38, 38);
            f.ClientSize = new Size(Math.Min(Util.S(820), Screen.FromControl(this).WorkingArea.Width * 9 / 10),
                                    Math.Min(Util.S(640), Screen.FromControl(this).WorkingArea.Height * 9 / 10));
            f.KeyPreview = true;
            f.KeyDown += delegate (object s, KeyEventArgs e) { if (e.KeyCode == Keys.Escape || e.KeyCode == Keys.F1) f.Close(); };
            var box = new TextBox
            {
                Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, WordWrap = false,
                Dock = DockStyle.Fill, BorderStyle = BorderStyle.None,
                BackColor = Color.FromArgb(32, 32, 32), ForeColor = Color.Gainsboro,
                Font = new Font("Consolas", 10f), Text = text
            };
            var close = new Button
            {
                Text = "Close", Dock = DockStyle.Bottom, Height = Util.S(32), FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(52, 52, 52), ForeColor = Color.Gainsboro
            };
            close.Click += delegate { f.Close(); };
            f.Controls.Add(box);                               // fill first, edge-docked after
            f.Controls.Add(close);
            f.CancelButton = close;
            Util.Dark(box);
            f.Shown += delegate { box.SelectionStart = 0; box.SelectionLength = 0; close.Focus(); };
            f.HandleCreated += delegate { try { int on = 1; DwmSetWindowAttribute(f.Handle, 20, ref on, 4); } catch (Exception) { } };
            f.ShowDialog(this);
        }
    }

    void ResetPrefs()
    {
        if (MessageBox.Show(this, "Delete the settings file and start with the default settings next time?\n\n" +
                            "(The current window and options stay as they are until you close RetroGleek.)",
                            "Reset settings", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        Prefs.Reset();
        status.Text = "  Settings reset: RetroGleek will start with the default settings next time";
    }

    void ShowAbout()
    {
        MessageBox.Show(this,
            "RetroGleek - offline image browser and viewer\n" +
            "Copyright (c) 2026 Mark Billson. Released under the MIT License.\n" +
            "No network access and no telemetry. Files are only written when you save, copy, move, rename or delete,\n" +
            "plus settings.ini next to RetroGleek.exe when it closes.\n\n" +
            "Retro-computer pictures are decoded by RECOIL " + Recoil.RECOIL.Version + "\n" +
            Recoil.RECOIL.Credits.Trim() + "\n" + Recoil.RECOIL.License + "\n\n" +
            "Press F1 for every key and mouse action.",
            "About RetroGleek", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    // ================================================================ marks: ratings, colour labels, tag

    // Alt+0..5 = rating (kind 1), Shift+0..5 = colour label (kind 2), top row or keypad; kind 0 = not a mark key
    static int MarkKey(Keys keyData, out int kind)
    {
        kind = 0;
        bool ctrl = (keyData & Keys.Control) != 0, alt = (keyData & Keys.Alt) != 0, shift = (keyData & Keys.Shift) != 0;
        if (ctrl || alt == shift) return -1;
        Keys k = keyData & Keys.KeyCode;
        int d = k >= Keys.D0 && k <= Keys.D5 ? (int)k - (int)Keys.D0 : k >= Keys.NumPad0 && k <= Keys.NumPad5 ? (int)k - (int)Keys.NumPad0 : -1;
        if (d < 0) return -1;
        kind = alt ? 1 : 2;
        return d;
    }

    // what a mark applies to in the browser: the selected pictures, or the focused one
    List<string> MarkTargets()
    {
        var paths = new List<string>();
        foreach (int i in grid.SelectedIndices()) if (!grid.Items[i].Offline) paths.Add(grid.Items[i].Path);
        int f = grid.FocusIndex;
        if (paths.Count == 0 && f >= 0 && f < grid.Items.Count && !grid.Items[f].Offline) paths.Add(grid.Items[f].Path);
        return paths;
    }

    // stars / label: -1 = leave as it is. toggleTag: tag them all, or untag them all if they all were tagged.
    void DoMark(int stars, int label, bool toggleTag)
    {
        var paths = new List<string>();
        if (viewing) { string p = canvas.CurrentPath; if (p != null && File.Exists(p)) paths.Add(p); }
        else paths = MarkTargets();
        if (paths.Count == 0) return;
        bool? tag = null;
        if (toggleTag)
        {
            bool allTagged = true;
            foreach (string p in paths) { Mark m = Marks.ForFile(p); if (m == null || !m.Tag) { allTagged = false; break; } }
            tag = !allTagged;
        }
        string focusBefore = !viewing && grid.FocusIndex >= 0 && grid.FocusIndex < grid.Items.Count ? grid.Items[grid.FocusIndex].Path : null;
        Marks.Set(paths, stars, label, tag);
        string what = toggleTag ? (tag.Value ? "Tagged" : "Tag removed")
                    : stars >= 0 ? (stars == 0 ? "Rating removed" : "Rating: " + Marks.StarText(stars))
                    : label == 0 ? "Colour label removed" : "Colour label: " + Marks.LabelNames[label];
        canvas.MarksChanged();
        grid.MarksChanged();
        UpdatePreview();
        if (viewing)
        {
            canvas.ShowMessage(what);
            if (autoAdvance) canvas.Next();
        }
        else
        {
            // auto-advance; if the Show filter just took the picture out of the list, the next one is already in its place
            bool stillThere = focusBefore != null && grid.FocusIndex >= 0 && grid.FocusIndex < grid.Items.Count
                              && string.Equals(grid.Items[grid.FocusIndex].Path, focusBefore, StringComparison.OrdinalIgnoreCase);
            if (autoAdvance && paths.Count == 1 && stillThere) grid.SelectNext();
            UpdateStatus();
            status.Text = "  " + what + (paths.Count > 1 ? " (" + paths.Count + " pictures)" : "") + "   |   " + status.Text.Trim();
        }
    }

    void SetShow(int mode)
    {
        if (showCombo.SelectedIndex != mode) showCombo.SelectedIndex = mode;     // its handler sets grid.ShowMode
        else grid.ShowMode = mode;
        UpdateStatus();
    }

    void ClearTags()
    {
        var paths = new List<string>();
        foreach (Item it in grid.Items) { Mark m = grid.MarkOf(it); if (m != null && m.Tag) paths.Add(it.Path); }
        if (paths.Count == 0) return;
        if (MessageBox.Show(this, "Remove the tag from the " + paths.Count + (paths.Count == 1 ? " tagged picture" : " tagged pictures") + " shown here?\n\n(Ratings and colour labels stay.)",
                            "Clear tags", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        Marks.Set(paths, -1, -1, false);
        grid.MarksChanged();
        canvas.MarksChanged();
        UpdatePreview();
        UpdateStatus();
    }

    // ================================================================ screen effect presets (Effects menu, Ctrl+1 .. Ctrl+9)

    const int MaxPresets = 9;
    readonly EffectSet[] presets = new EffectSet[MaxPresets];

    void LoadPresets()
    {
        for (int i = 0; i < MaxPresets; i++) presets[i] = EffectSet.Parse(Prefs.Get("preset" + (i + 1), null));
    }

    void StorePresets()
    {
        for (int i = 0; i < MaxPresets; i++) Prefs.Set("preset" + (i + 1), presets[i] == null ? null : presets[i].Serialize());
    }

    int PresetCount()
    {
        int n = 0;
        foreach (EffectSet p in presets) if (p != null) n++;
        return n;
    }

    // the viewer(s) showing pictures right now: both halves while comparing
    IEnumerable<Canvas> EffectTargets() { return comparing ? new[] { cmpA, cmpB } : new[] { canvas }; }

    void ApplyPreset(int i)
    {
        if (i < 0 || i >= MaxPresets) return;
        EffectSet p = presets[i];
        if (p == null)
        {
            if (viewing || comparing) foreach (Canvas c in EffectTargets()) c.ShowMessage("No preset " + (i + 1) + " yet (Effects > Save these effects as a preset)");
            return;
        }
        canvas.UseEffects(p);
        if (comparing) { cmpA.UseEffects(p); cmpB.UseEffects(p); }
        foreach (Canvas c in EffectTargets()) c.ShowMessage("Preset " + (i + 1) + ": " + p.Name + "  (" + p.Describe() + ")");
        if (!viewing && !comparing) status.Text = "  Screen effects preset " + (i + 1) + ": " + p.Name + "  (" + p.Describe() + ")";
    }

    void SavePreset()
    {
        Canvas src = comparing ? cmpA : canvas;
        EffectSet e = src.CurrentEffects;
        EffectSet a = src.AutoChoice;
        int free = Array.IndexOf(presets, null);
        string suggest = a != null && src.Platform != null ? src.Platform : "Preset " + ((free >= 0 ? free : 0) + 1);   // automatic: the computer's name
        string name = Prompt.Ask(this, "Save screen effects preset", "Name for " + e.Describe() + ":", suggest, false);
        if (name == null) return;
        name = name.Replace("|", "/").Trim();
        if (name.Length == 0) return;
        int slot = -1;
        for (int i = 0; i < MaxPresets; i++)
            if (presets[i] != null && string.Equals(presets[i].Name, name, StringComparison.OrdinalIgnoreCase)) slot = i;
        if (slot >= 0)
        {
            if (MessageBox.Show(this, "Replace the preset \"" + presets[slot].Name + "\" (" + presets[slot].Describe() + ")?", "Save preset",
                                MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        }
        else if (free < 0) { Warn("All " + MaxPresets + " presets are in use. Delete one first (Effects > Delete a preset)."); return; }
        else slot = free;
        e.Name = name;
        presets[slot] = e;
        StorePresets();
        Prefs.Save();                                      // kept straight away, not only when RetroGleek closes
        string msg = "Saved preset " + (slot + 1) + ": " + name + "  (Ctrl+" + (slot + 1) + " uses it)";
        foreach (Canvas c in EffectTargets()) c.ShowMessage(msg);
        if (!viewing && !comparing) status.Text = "  " + msg;
    }

    void DeletePreset(int i)
    {
        if (i < 0 || i >= MaxPresets || presets[i] == null) return;
        if (MessageBox.Show(this, "Delete the preset \"" + presets[i].Name + "\"?", "Delete preset", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        presets[i] = null;
        StorePresets();
        Prefs.Save();
    }

    // Ctrl+1 .. Ctrl+9 (top row or keypad): the preset number, or 0
    static int PresetKey(Keys keyData)
    {
        if ((keyData & Keys.Control) == 0 || (keyData & (Keys.Shift | Keys.Alt)) != 0) return 0;
        Keys k = keyData & Keys.KeyCode;
        if (k >= Keys.D1 && k <= Keys.D9) return (int)k - (int)Keys.D0;
        if (k >= Keys.NumPad1 && k <= Keys.NumPad9) return (int)k - (int)Keys.NumPad0;
        return 0;
    }

    // ================================================================ menu bar

    // Each entry remembers when it is available and whether it is ticked; both are worked out each time a
    // menu opens. New features: add an entry to the menu it belongs to, and give it a shortcut in RunShortcut.
    sealed class MenuState
    {
        public ToolStripMenuItem Item;
        public Func<bool> On, Checked;
        public Func<string> Text;
        public Func<bool> Show;                            // shown only while this is true (e.g. a preset slot in use)
        public bool InCompare;                             // stays available while two pictures are being compared
    }

    MenuStrip menuBar;
    readonly List<MenuState> menuStates = new List<MenuState>();
    static readonly Color MenuText = Color.Gainsboro;

    ToolStripMenuItem MenuTop(string text)
    {
        var m = new ToolStripMenuItem(text) { ForeColor = MenuText };
        m.DropDownOpening += delegate { UpdateMenus(); };
        m.DropDown.BackColor = Color.FromArgb(38, 38, 38);
        menuBar.Items.Add(m);
        return m;
    }

    ToolStripMenuItem MenuSub(ToolStripMenuItem parent, string text, Func<bool> on)
    {
        var m = new ToolStripMenuItem(text) { ForeColor = MenuText };
        m.DropDown.BackColor = Color.FromArgb(38, 38, 38);
        parent.DropDownItems.Add(m);
        menuStates.Add(new MenuState { Item = m, On = on });
        return m;
    }

    ToolStripMenuItem MenuEntry(ToolStripMenuItem parent, string text, string keys, Action run, Func<bool> on, Func<bool> chk)
    {
        var m = new ToolStripMenuItem(text) { ForeColor = MenuText, ShortcutKeyDisplayString = keys };
        m.Click += delegate { try { run(); } catch (Exception ex) { Warn(ex.Message); } };
        parent.DropDownItems.Add(m);
        menuStates.Add(new MenuState { Item = m, On = on, Checked = chk });
        return m;
    }

    // an entry that does exactly what its shortcut does
    ToolStripMenuItem MenuKey(ToolStripMenuItem parent, string text, string keys, Keys shortcut, Func<bool> on, Func<bool> chk)
    {
        return MenuEntry(parent, text, keys, delegate { RunShortcut(shortcut, true); }, on, chk);
    }

    MenuState LastEntry { get { return menuStates[menuStates.Count - 1]; } }

    static void MenuSep(ToolStripMenuItem parent) { parent.DropDownItems.Add(new ToolStripSeparator()); }

    void UpdateMenus()
    {
        foreach (MenuState s in menuStates)
        {
            try
            {
                if (s.Show != null) s.Item.Visible = s.Show();
                if (s.Text != null) s.Item.Text = s.Text();
                s.Item.Enabled = (!comparing || s.InCompare) && (s.On == null || s.On());
                if (s.Checked != null) s.Item.Checked = s.Checked();
            }
            catch (Exception) { }                             // a menu must never raise an error dialog
        }
    }

    void BuildMenuBar()
    {
        menuBar = new MenuStrip
        {
            Dock = DockStyle.Top, Renderer = new DarkMenuRenderer(), BackColor = Color.FromArgb(38, 38, 38),
            ForeColor = MenuText, Font = new Font("Segoe UI", 9f), GripStyle = ToolStripGripStyle.Hidden,
            Padding = new Padding(Util.S(4), Util.S(2), 0, Util.S(2))
        };
        Func<bool> browsing = delegate { return !viewing; };
        Func<bool> inViewer = delegate { return viewing && canvas.HasPicture; };
        Func<bool> hasSel = delegate { return !viewing && (lastPane == tree ? IsPlainFolder(tree.SelectedNode) : grid.SelectedIndices().Count > 0); };
        Func<bool> hasItems = delegate { return !viewing && grid.Items.Count > 0; };

        // ---- File
        ToolStripMenuItem file = MenuTop("&File");
        MenuKey(file, "&Open...", "Ctrl+O", Keys.Control | Keys.O, null, null);
        MenuEntry(file, "&New folder", "", delegate { DoNewFolder(); }, delegate { return !viewing && NodePath(tree.SelectedNode) != null; }, null);
        MenuSep(file);
        MenuKey(file, "&Save as PNG (lossless)...", "Ctrl+S", Keys.Control | Keys.S,
            delegate { return viewing ? canvas.HasPicture : grid.SelectedIndices().Count > 0; }, null);
        MenuKey(file, "Export all &frames as PNG...", "Ctrl+Shift+S", Keys.Control | Keys.Shift | Keys.S,
            delegate { return viewing ? canvas.HasPicture : grid.SelectedIndices().Count > 0; }, null);
        MenuEntry(file, "Save the &turn into the JPEG (lossless)...", "", delegate
            {
                string sp; int st; bool sfx, sfy;
                if (canvas.GetSaveSource(out sp, out st, out sfx, out sfy)) RotateFiles(st);
            },
            delegate { return viewing && canvas.ExtraTurns && canvas.CurrentPath != null && JpegRotate.IsJpeg(canvas.CurrentPath) && !rotateBusy; }, null);
        MenuSep(file);
        MenuEntry(file, "E&xit", "Alt+F4", delegate { Close(); }, null, null);
        LastEntry.InCompare = true;

        // ---- Edit
        ToolStripMenuItem edit = MenuTop("&Edit");
        MenuEntry(edit, "&Undo", "Ctrl+Z", delegate { DoUndo(); }, delegate { return !viewing && undoSteps.Count > 0; }, null);
        LastEntry.Text = UndoMenuText;
        MenuSep(edit);
        MenuKey(edit, "&Copy", "Ctrl+C", Keys.Control | Keys.C, delegate { return viewing ? canvas.HasPicture : hasSel(); }, null);
        LastEntry.Text = delegate { return viewing ? "&Copy picture" : "&Copy"; };
        MenuKey(edit, "Cu&t", "Ctrl+X", Keys.Control | Keys.X, hasSel, null);
        MenuKey(edit, "&Paste", "Ctrl+V", Keys.Control | Keys.V, delegate { return !viewing && ClipHasFiles(); }, null);
        Func<bool> canSend = delegate { return viewing ? canvas.CurrentPath != null : hasSel(); };
        for (int tm = 0; tm < 2; tm++)
        {
            bool mv = tm == 1;
            ToolStripMenuItem sendMenu = MenuSub(edit, mv ? "&Move to" : "C&opy to", canSend);
            MenuKey(sendMenu, "&Choose a folder...", mv ? "Ctrl+Shift+M" : "Ctrl+Shift+Y", Keys.Control | Keys.Shift | (mv ? Keys.M : Keys.Y), null, null);
            for (int ri = 0; ri < MaxRecentDest; ri++)
            {
                int slot = ri;
                MenuEntry(sendMenu, "Recent " + (slot + 1), "", delegate { if (slot < recentDest.Count) TransferTo(mv, recentDest[slot]); }, null, null);
                LastEntry.Show = delegate { return slot < recentDest.Count; };
                LastEntry.Text = delegate { return slot < recentDest.Count ? "&" + (slot + 1) + "  " + recentDest[slot].Replace("&", "&&") : ""; };
            }
        }
        MenuKey(edit, "&Rename...", "F2", Keys.F2, delegate { return !viewing && (lastPane == tree ? IsPlainFolder(tree.SelectedNode) : grid.SelectedIndices().Count == 1); }, null);
        MenuKey(edit, "&Delete (to Recycle Bin)", "Del", Keys.Delete, delegate { return viewing ? canvas.CurrentPath != null : hasSel(); }, null);
        ToolStripMenuItem turnMenu = MenuSub(edit, "Turn the file (lossless &JPEG)", delegate { return !rotateBusy && (viewing ? canvas.CurrentPath != null : grid.SelectedIndices().Count > 0); });
        MenuKey(turnMenu, "&Clockwise", "Ctrl+Shift+R", Keys.Control | Keys.Shift | Keys.R, null, null);
        MenuKey(turnMenu, "C&ounter-clockwise", "Ctrl+Shift+L", Keys.Control | Keys.Shift | Keys.L, null, null);
        MenuEntry(turnMenu, "&180 degrees", "", delegate { RotateFiles(2); }, null, null);
        MenuSep(edit);
        // marks: the picture in the viewer, or the selected pictures (kept in marks.tsv, never in the pictures)
        Func<bool> canMark = delegate { return viewing ? canvas.CurrentPath != null : MarkTargets().Count > 0; };
        ToolStripMenuItem rate = MenuSub(edit, "Rati&ng", canMark);
        for (int ri = 0; ri <= 5; ri++)
            MenuKey(rate, ri == 0 ? "&No rating" : "&" + ri + "  " + Marks.StarText(ri), "Alt+" + ri, Keys.Alt | (Keys)((int)Keys.D0 + ri), null, null);
        MenuSep(rate);
        MenuEntry(rate, "&Write my ratings into the files (JPEG, PNG)...", "", delegate { WriteRatingsToFiles(); }, delegate { return !ratingBusy; }, null);
        ToolStripMenuItem lab = MenuSub(edit, "Colour &label", canMark);
        for (int li = 0; li <= 5; li++)
            MenuKey(lab, "&" + li + "  " + Marks.LabelNames[li], "Shift+" + li, Keys.Shift | (Keys)((int)Keys.D0 + li), null, null);
        MenuKey(edit, "Ta&g / untag", "X", Keys.X, canMark, null);
        MenuEntry(edit, "Sel&ect tagged", "", delegate { grid.SelectTagged(); }, delegate { return !viewing && grid.CountTagged() > 0; }, null);
        MenuEntry(edit, "Clear tags in this &view...", "", delegate { ClearTags(); }, delegate { return !viewing && grid.CountTagged() > 0; }, null);
        MenuSep(edit);
        MenuEntry(edit, "Select &all", "Ctrl+A", delegate { grid.SelectAllItems(); }, hasItems, null);
        MenuEntry(edit, "&Invert selection", "Ctrl+I", delegate { grid.InvertSelection(); }, hasItems, null);
        MenuSep(edit);
        MenuKey(edit, "&Filter...", "Ctrl+F", Keys.Control | Keys.F, browsing, null);
        MenuKey(edit, "Include &subfolders", "Ctrl+Shift+F", Keys.Control | Keys.Shift | Keys.F, browsing, delegate { return grid.Recursive; });

        // ---- View
        ToolStripMenuItem view = MenuTop("&View");
        MenuEntry(view, "Open in &viewer", "Enter / Esc", delegate { if (viewing) SetViewing(false); else OpenIndex(grid.FocusIndex); },
              delegate { return viewing || (grid.FocusIndex >= 0 && grid.FocusIndex < grid.Items.Count); }, null);
        LastEntry.Text = delegate { return viewing ? "Back to the &browser" : "Open in &viewer"; };
        MenuEntry(view, "F&ullscreen", "F11", delegate { ToggleFull(); }, null, delegate { return full; });
        LastEntry.InCompare = true;
        MenuEntry(view, "&Compare side by side", "Ctrl+Shift+C", delegate { if (comparing) EndCompare(); else StartCompare(); },
                  delegate { return comparing || CanCompare(); }, null);
        LastEntry.Text = delegate { return comparing ? "&Close the comparison" : "&Compare side by side (2 pictures selected)"; };
        LastEntry.InCompare = true;
        MenuKey(view, "&Refresh", "F5", Keys.F5, browsing, null);
        MenuSep(view);
        ToolStripMenuItem sortBy = MenuSub(view, "&Sort by", browsing);
        string[] sortNames = { "&Name", "&Date modified", "&Size", "&Type", "&Platform", "D&imensions", "&Frames", "&Colours", "S&tatus", "R&ating", "&Label" };
        for (int i = 0; i < sortNames.Length; i++)
        {
            int key = i;
            MenuEntry(sortBy, sortNames[i], "", delegate { ChooseSort(key); }, null, delegate { return grid.SortKey == key; });
        }
        MenuSep(sortBy);
        MenuEntry(sortBy, "&Reverse order", "", delegate { grid.SetSort(grid.SortKey, !grid.SortDesc); }, null, delegate { return grid.SortDesc; });
        ToolStripMenuItem showMenu = MenuSub(view, "S&how (marks)", browsing);
        for (int shi = 0; shi < ThumbGrid.ShowNames.Length; shi++)
        {
            int mode = shi;
            if (shi == 3 || shi == 9) MenuSep(showMenu);
            MenuEntry(showMenu, ThumbGrid.ShowNames[shi], "", delegate { SetShow(mode); }, null, delegate { return grid.ShowMode == mode; });
        }
        MenuKey(view, "&Details list", "Ctrl+Shift+D", Keys.Control | Keys.Shift | Keys.D, browsing, delegate { return grid.DetailsMode; });
        MenuEntry(view, "Show &details on tiles", "", delegate { grid.ShowDetails = !grid.ShowDetails; }, delegate { return !viewing && !grid.DetailsMode; }, delegate { return grid.ShowDetails; });
        MenuSep(view);
        ToolStripMenuItem zoom = MenuSub(view, "&Zoom", inViewer);
        MenuKey(zoom, "&Fit this picture", "0", Keys.D0, null, null);
        MenuKey(zoom, "&Actual size (100%)", "1", Keys.D1, null, null);
        MenuKey(zoom, "Zoom &in", "+", Keys.Add, null, null);
        MenuKey(zoom, "Zoom &out", "-", Keys.Subtract, null, null);
        MenuKey(view, "Rotate &clockwise", "R", Keys.R, inViewer, null);
        MenuKey(view, "Rotate co&unter-clockwise", "L", Keys.L, inViewer, null);
        MenuKey(view, "Flip &left-right", "H", Keys.H, inViewer, null);
        MenuKey(view, "Flip &top-bottom", "V", Keys.V, inViewer, null);
        MenuSep(view);
        MenuKey(view, "&Info bar", "I", Keys.I, inViewer, delegate { return canvas.InfoOn; });
        MenuKey(view, "&EXIF details", "E", Keys.E, inViewer, delegate { return canvas.ExifOn; });
        MenuKey(view, "Pixel &grid (800% and above)", "G", Keys.G, inViewer, delegate { return canvas.GridOn; });
        MenuEntry(view, "Loupe: hold Z over the picture (4 times the current size)", "Z", delegate { }, delegate { return false; }, null);
        MenuKey(view, "Fil&mstrip", "J", Keys.J, inViewer, delegate { return canvas.Filmstrip; });
        MenuKey(view, "&Preview pane", "Alt+P", Keys.Alt | Keys.P, browsing, delegate { return preview.Visible; });

        // ---- Effects: screen effects for retro pictures (display only; remembered in settings.ini)
        ToolStripMenuItem effects = MenuTop("Effe&cts");
        MenuEntry(effects, "&Show screen effects", "O", delegate { canvas.EffectsOff = !canvas.EffectsOff; }, null, delegate { return !canvas.EffectsOff; });
        MenuEntry(effects, "&Automatic: the usual screen of each picture's computer", "A", delegate { canvas.ToggleAuto(); }, null, delegate { return canvas.AutoEffects; });
        LastEntry.Text = delegate
        {
            EffectSet ac = canvas.AutoChoice;
            return ac != null && viewing ? "&Automatic: " + ac.Name.Replace("&", "&&") : "&Automatic: the usual screen of each picture's computer";
        };
        MenuSep(effects);
        MenuEntry(effects, "True &TV aspect", "T", delegate { canvas.TvAspect = !canvas.TvAspect; }, null, delegate { return canvas.TvAspect; });
        ToolStripMenuItem scan = MenuSub(effects, "Scan&lines", null);
        string[] scanNames = { "&Off", "&Light", "&Medium", "&Strong" };
        for (int si = 0; si < scanNames.Length; si++)
        {
            int mode = si;
            MenuEntry(scan, scanNames[si], si == 0 ? "K cycles" : "", delegate { canvas.ScanMode = mode; }, null, delegate { return canvas.ScanMode == mode; });
        }
        ToolStripMenuItem maskMenu = MenuSub(effects, "Phosphor &mask", null);
        string[] maskNames = { "&Off", "&Aperture grille (Trinitron)", "&Slot mask (most TVs, Commodore 1084S)", "&Dot mask (fine)" };
        for (int mi = 0; mi < maskNames.Length; mi++)
        {
            int mode = mi;
            MenuEntry(maskMenu, maskNames[mi], mi == 0 ? "M cycles" : "", delegate { canvas.MaskMode = mode; }, null, delegate { return canvas.MaskMode == mode; });
        }
        ToolStripMenuItem sigMenu = MenuSub(effects, "Video si&gnal", null);
        string[] sigNames = { "&RGB (sharp, as decoded)", "&S-Video (colours soften a little)", "&Composite (dithering blends, as on a TV)" };
        for (int gi = 0; gi < sigNames.Length; gi++)
        {
            int mode = gi;
            MenuEntry(sigMenu, sigNames[gi], gi == 0 ? "C cycles" : "", delegate { canvas.SignalMode = mode; }, null, delegate { return canvas.SignalMode == mode; });
        }
        ToolStripMenuItem glowMenu = MenuSub(effects, "Gl&ow", null);
        string[] glowNames = { "&Off", "&Soft", "St&rong" };
        for (int wi = 0; wi < glowNames.Length; wi++)
        {
            int mode = wi;
            MenuEntry(glowMenu, glowNames[wi], wi == 0 ? "W cycles" : "", delegate { canvas.GlowMode = mode; }, null, delegate { return canvas.GlowMode == mode; });
        }
        ToolStripMenuItem curveMenu = MenuSub(effects, "Screen c&urvature", null);
        string[] curveNames = { "&Off (flat)", "&Slight", "St&rong" };
        for (int ui = 0; ui < curveNames.Length; ui++)
        {
            int mode = ui;
            MenuEntry(curveMenu, curveNames[ui], ui == 0 ? "U cycles" : "", delegate { canvas.CurveMode = mode; }, null, delegate { return canvas.CurveMode == mode; });
        }
        MenuSep(effects);
        for (int pi = 0; pi < MaxPresets; pi++)
        {
            int slot = pi;
            MenuEntry(effects, "Preset " + (slot + 1), "Ctrl+" + (slot + 1), delegate { ApplyPreset(slot); }, null, null);
            LastEntry.Show = delegate { return presets[slot] != null; };
            LastEntry.Text = delegate { return presets[slot] == null ? "" : "&" + (slot + 1) + "  " + presets[slot].Name.Replace("&", "&&"); };
            LastEntry.InCompare = true;
        }
        MenuEntry(effects, "(no presets saved yet)", "", delegate { }, delegate { return false; }, null);
        LastEntry.Show = delegate { return PresetCount() == 0; };
        MenuEntry(effects, "Sa&ve these effects as a preset...", "", delegate { SavePreset(); }, null, null);
        ToolStripMenuItem del = MenuSub(effects, "&Delete a preset", delegate { return PresetCount() > 0; });
        for (int di = 0; di < MaxPresets; di++)
        {
            int slot = di;
            MenuEntry(del, "Preset " + (slot + 1), "", delegate { DeletePreset(slot); }, null, null);
            LastEntry.Show = delegate { return presets[slot] != null; };
            LastEntry.Text = delegate { return presets[slot] == null ? "" : "&" + (slot + 1) + "  " + presets[slot].Name.Replace("&", "&&"); };
        }
        MenuSep(effects);
        MenuEntry(effects, "Retro pictures only. Display only: saved and copied pictures never change", "", delegate { }, delegate { return false; }, null);

        // ---- Go
        ToolStripMenuItem go = MenuTop("&Go");
        MenuKey(go, "&Back", "Alt+Left", Keys.Alt | Keys.Left, delegate { return !viewing && hpos > 0; }, null);
        MenuKey(go, "&Forward", "Alt+Right", Keys.Alt | Keys.Right, delegate { return !viewing && hpos < hist.Count - 1; }, null);
        MenuKey(go, "&Up one folder", "Alt+Up", Keys.Alt | Keys.Up, browsing, null);
        MenuKey(go, "&Address bar", "Ctrl+L", Keys.Control | Keys.L, browsing, null);
        MenuSep(go);
        ToolStripMenuItem favMenu = MenuSub(go, "Fa&vourites", null);
        MenuKey(favMenu, "&Add this folder", "Ctrl+D", Keys.Control | Keys.D, delegate { return grid.Dir != null; }, null);
        LastEntry.Text = delegate { return IsFavourite(grid.Dir) ? "&Remove this folder from the favourites" : "&Add this folder"; };
        MenuSep(favMenu);
        for (int fi = 0; fi < MaxFavourites; fi++)
        {
            int slot = fi;
            MenuEntry(favMenu, "Favourite " + (slot + 1), "", delegate { if (slot < favourites.Count) OpenFolderShortcut(favourites[slot]); }, null, null);
            LastEntry.Show = delegate { return slot < favourites.Count; };
            LastEntry.Text = delegate { return slot < favourites.Count ? (slot < 9 ? "&" + (slot + 1) + "  " : "    ") + FavText(favourites[slot]).Replace("&", "&&") + "    " + favourites[slot].Replace("&", "&&") : ""; };
        }
        MenuEntry(favMenu, "(no favourites yet: Ctrl+D adds the open folder)", "", delegate { }, delegate { return false; }, null);
        LastEntry.Show = delegate { return favourites.Count == 0; };
        ToolStripMenuItem recMenu = MenuSub(go, "Recen&t folders", delegate { return recentFolders.Count > 0; });
        for (int ri = 0; ri < MaxRecentFolders; ri++)
        {
            int slot = ri;
            MenuEntry(recMenu, "Recent " + (slot + 1), "", delegate { if (slot < recentFolders.Count) OpenFolderShortcut(recentFolders[slot]); }, null, null);
            LastEntry.Show = delegate { return slot < recentFolders.Count; };
            LastEntry.Text = delegate { return slot < recentFolders.Count ? "&" + ((slot + 1) % 10) + "  " + recentFolders[slot].Replace("&", "&&") : ""; };
        }
        MenuSep(go);
        Func<bool> canStep = delegate { return viewing && canvas.FileCount > 1; };
        MenuKey(go, "&Previous picture", "Left", Keys.Left, canStep, null);
        MenuKey(go, "&Next picture", "Right", Keys.Right, canStep, null);
        MenuKey(go, "F&irst picture", "Home", Keys.Home, canStep, null);
        MenuKey(go, "&Last picture", "End", Keys.End, canStep, null);

        // ---- Tools
        ToolStripMenuItem tools = MenuTop("&Tools");
        MenuEntry(tools, "Analyse &folder (colours, frames, duplicates)", "",
            delegate { if (grid.Analysing) grid.StopAnalysis(); else { SetDetailsView(true); grid.StartAnalysis(); } },
            delegate { return !viewing && grid.Dir != null; }, null);
        LastEntry.Text = delegate { return grid.Analysing ? "Stop &analysing" : "Analyse &folder (colours, frames, duplicates)"; };
        MenuSep(tools);
        MenuKey(tools, "Folder &audit report (HTML)...", "Ctrl+Shift+A", Keys.Control | Keys.Shift | Keys.A,
            delegate { return grid.Dir != null && !auditBusy; }, null);
        MenuEntry(tools, "Folder audit report, &no thumbnails (smaller)...", "", delegate { DoAudit(false); },
            delegate { return grid.Dir != null && !auditBusy; }, null);
        MenuEntry(tools, "&Contact sheet (lossless PNG)...", "", delegate { DoContactSheet(); },
            delegate { return !viewing && !sheetBusy && grid.SelectedIndices().Count > 0; }, null);
        MenuKey(tools, "Con&vert to a retro format...", "Ctrl+Shift+E", Keys.Control | Keys.Shift | Keys.E,
            delegate { return !convertBusy && (viewing ? canvas.CurrentPath != null : grid.SelectedIndices().Count > 0); }, null);
        MenuKey(tools, "Batch &rename...", "Ctrl+F2", Keys.Control | Keys.F2, delegate { return !viewing && grid.SelectedIndices().Count > 0; }, null);
        MenuSep(tools);
        MenuKey(tools, "&Slideshow", "S", Keys.S, delegate { return viewing && canvas.FileCount > 1; }, delegate { return canvas.Slideshow; });
        ToolStripMenuItem anim = MenuSub(tools, "&Animated GIF / WebP", delegate { return viewing && canvas.Animated; });
        MenuKey(anim, "&Pause", "P", Keys.P, null, delegate { return canvas.AnimPaused; });
        MenuKey(anim, "Pre&vious frame", ",", Keys.Oemcomma, null, null);
        MenuKey(anim, "&Next frame", ".", Keys.OemPeriod, null, null);
        MenuSep(anim);
        MenuKey(anim, "&Export all frames as PNG...", "Ctrl+Shift+S", Keys.Control | Keys.Shift | Keys.S, null, null);

        // ---- Settings (remembered in settings.ini next to RetroGleek.exe, written when RetroGleek closes)
        ToolStripMenuItem settings = MenuTop("&Settings");
        MenuEntry(settings, "Show &retro-computer formats (RECOIL)", "F8", delegate { ToggleRetro(); }, null, delegate { return Retro.Enabled; });
        MenuSep(settings);
        MenuEntry(settings, "&Fit to screen", "F", delegate { canvas.ToggleFitLock(); }, null, delegate { return canvas.FitLock; });
        MenuEntry(settings, "Move to the &next picture after marking", "", delegate { autoAdvance = !autoAdvance; }, null, delegate { return autoAdvance; });
        MenuEntry(settings, "&Checkerboard behind transparency", "B", delegate { canvas.ToggleChecker(); }, null, delegate { return canvas.Checker; });
        ToolStripMenuItem pix = MenuSub(settings, "&Enlarged pixels", null);
        MenuEntry(pix, "&Automatic (retro sharp, photos smooth)", "N cycles", delegate { canvas.PixMode = 0; }, null, delegate { return canvas.PixMode == 0; });
        MenuEntry(pix, "&Crisp", "", delegate { canvas.PixMode = 1; }, null, delegate { return canvas.PixMode == 1; });
        MenuEntry(pix, "S&harp (even pixels at any size)", "", delegate { canvas.PixMode = 3; }, null, delegate { return canvas.PixMode == 3; });
        MenuEntry(pix, "&Smooth", "", delegate { canvas.PixMode = 2; }, null, delegate { return canvas.PixMode == 2; });
        MenuSep(settings);
        MenuEntry(settings, "&Reset to default settings...", "", delegate { ResetPrefs(); }, null, null);
        MenuEntry(settings, "Settings are remembered in settings.ini next to RetroGleek.exe", "", delegate { }, delegate { return false; }, null);

        // ---- Help
        ToolStripMenuItem help = MenuTop("&Help");
        MenuEntry(help, "&Keys and mouse", "F1", delegate { ShowHelp(); }, null, null);
        LastEntry.InCompare = true;
        MenuEntry(help, "&About RetroGleek", "", delegate { ShowAbout(); }, null, null);
        LastEntry.InCompare = true;
    }

    bool IsPlainFolder(TreeNode n)
    {
        string p = NodePath(n);
        return p != null && !IsRootPath(p);
    }

    void OpenDialog()
    {
        using (var d = new OpenFileDialog())
        {
            d.Filter = "Images|*.jpg;*.jpeg;*.jpe;*.jfif;*.png;*.bmp;*.dib;*.gif;*.tif;*.tiff|All files|*.*";
            if (grid.Dir != null) d.InitialDirectory = grid.Dir;
            if (d.ShowDialog(this) == DialogResult.OK) OpenImage(d.FileName);
        }
    }

    void OnDragEnterFiles(object s, DragEventArgs e)
    {
        e.Effect = !grid.DraggingOut && !treeDragging && e.Data.GetDataPresent(DataFormats.FileDrop) ? DragDropEffects.Copy : DragDropEffects.None;
    }

    void OnDropFiles(object s, DragEventArgs e)
    {
        if (grid.DraggingOut || treeDragging) return;
        string[] f = e.Data.GetData(DataFormats.FileDrop) as string[];
        if (f != null && f.Length > 0) OpenImage(f[0]);
    }

    void ToggleFull()
    {
        if (!full)
        {
            Screen sc = Screen.FromControl(this);
            oldStyle = FormBorderStyle; oldState = WindowState;
            oldBounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            full = true;
            WindowState = FormWindowState.Normal;
            FormBorderStyle = FormBorderStyle.None;
            menuBar.Visible = false;
            Bounds = sc.Bounds;
        }
        else
        {
            full = false;
            menuBar.Visible = true;
            FormBorderStyle = oldStyle;
            WindowState = FormWindowState.Normal;
            Bounds = oldBounds;
            WindowState = oldState;
        }
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (RunShortcut(keyData, false)) return true;
        return base.ProcessCmdKey(ref msg, keyData);
    }

    // Every shortcut, in one place. The menu bar calls this too (fromMenu = true), so a menu entry always does
    // exactly what its key does. From a menu, the text-box guards are skipped: a menu click is never typing.
    bool RunShortcut(Keys keyData, bool fromMenu)
    {
        Keys k = keyData & Keys.KeyCode;
        bool ctrl = (keyData & Keys.Control) != 0, alt = (keyData & Keys.Alt) != 0, shift = (keyData & Keys.Shift) != 0;
        bool typing = !fromMenu && (filterBox.Focused || addrBox.Focused);   // a text box has the keyboard: don't steal editing keys
        if (k == Keys.F11) { ToggleFull(); return true; }
        if (k == Keys.F1) { ShowHelp(); return true; }
        int preset = PresetKey(keyData);
        if (preset > 0) { ApplyPreset(preset - 1); return true; }
        int markKind, markValue = MarkKey(keyData, out markKind);
        if (comparing) return markKind != 0 || CompareKey(keyData);       // marks are given in the browser or the viewer
        if (ctrl && shift && k == Keys.C && !viewing) { StartCompare(); return true; }
        if (ctrl && shift && k == Keys.S) { DoExportFrames(); return true; }
        if (ctrl && shift && k == Keys.A) { DoAudit(true); return true; }
        if (ctrl && shift && k == Keys.D && !viewing) { SetDetailsView(!grid.DetailsMode); return true; }
        if (ctrl && !shift && !alt && k == Keys.D) { ToggleFavourite(grid.Dir); return true; }
        if (ctrl && shift && !alt && (k == Keys.R || k == Keys.L)) { RotateFiles(k == Keys.R ? 1 : 3); return true; }   // the file, not the view
        if (ctrl && shift && k == Keys.Y && !alt) { TransferTo(false, null); return true; }
        if (ctrl && shift && k == Keys.M && !alt) { TransferTo(true, null); return true; }
        if (ctrl && shift && k == Keys.E && !alt) { DoConvert(); return true; }
        if (ctrl && k == Keys.S) { if (viewing) SaveCurrentPng(); else DoSavePng(); return true; }
        if (ctrl && k == Keys.O) { OpenDialog(); return true; }

        if (viewing)
        {
            if (k == Keys.Enter && !ctrl) { ToggleFull(); return true; }
            if (k == Keys.Escape)
            {
                if (canvas.Slideshow) canvas.StopSlideshow();      // Esc stops a running slideshow first
                else if (full) ToggleFull();
                else SetViewing(false);
                return true;
            }
            if (ctrl && k == Keys.C) { CopyCurrentPicture(); return true; }
            if (k == Keys.Delete && !ctrl) { DeleteCurrentPicture(); return true; }
            if (markKind != 0) { DoMark(markKind == 1 ? markValue : -1, markKind == 2 ? markValue : -1, false); return true; }
            if (k == Keys.X && !ctrl && !alt && !shift) { DoMark(-1, -1, true); return true; }
            if (canvas.HandleKey(keyData)) return true;
        }
        else
        {
            if (ctrl && shift && k == Keys.F) { ToggleSubfolders(); return true; }
            if (ctrl && k == Keys.F) { ShowFilter(); return true; }
            if (ctrl && k == Keys.L) { FocusAddress(); return true; }
            if (alt && k == Keys.Left) { GoHistory(-1); return true; }
            if (alt && k == Keys.Right) { GoHistory(1); return true; }
            if (alt && k == Keys.Up) { GoUp(); return true; }
            bool onBar = !fromMenu && (sortCombo.Focused || sizeSlider.Focused);   // the sort box / size slider have the keyboard
            if (typing || onBar)
            {
                if (k == Keys.Escape)
                {
                    if (filterBox.Focused) CloseFilter();
                    else if (addrBox.Focused) { RestoreAddress(); grid.Focus(); }
                    else grid.Focus();
                    return true;
                }
            }
            else
            {
                bool tr = lastPane == tree;
                if (markKind != 0 && (!tr || fromMenu)) { DoMark(markKind == 1 ? markValue : -1, markKind == 2 ? markValue : -1, false); return true; }
                if (alt && !ctrl && !shift && k == Keys.P) { SetPreview(!preview.Visible); return true; }
                if (k == Keys.X && !ctrl && !alt && !shift && (!tr || fromMenu)) { DoMark(-1, -1, true); return true; }
                switch (k)
                {
                    case Keys.F2:
                        if (ctrl) { if (!tr) DoBatchRename(); return true; }
                        DoRename(tr); return true;
                    case Keys.Delete: DoDelete(tr); return true;
                    case Keys.F5: ReloadAll(); return true;
                    case Keys.F8: ToggleRetro(); return true;
                    case Keys.Back: GoUp(); return true;
                    case Keys.C: if (ctrl) { DoCopy(tr); return true; } break;
                    case Keys.X: if (ctrl) { DoCut(tr); return true; } break;
                    case Keys.Z: if (ctrl) { DoUndo(); return true; } break;
                    case Keys.V: if (ctrl) { DoPaste(tr); return true; } break;
                    case Keys.I: if (ctrl && !tr) { grid.InvertSelection(); return true; } break;
                    case Keys.Escape: if (full) { ToggleFull(); return true; } break;
                }
            }
        }
        return false;
    }
}
