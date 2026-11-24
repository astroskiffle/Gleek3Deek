"""Gleek3Deek file operations: copying and moving models together with the files they need.

No Qt in here, so it can be tested without a screen. An OBJ needs its .mtl and the textures that file names,
a glTF needs its .bin and images, a Collada file its images. Moving only the model would leave it broken, so a
transfer is planned as *bundles* (a model plus its companions) and carried out one bundle at a time: if the model
cannot be moved, what was already done for it is put back.

Rules that hold everywhere:
  * nothing is ever overwritten (a model whose name is taken gets a number),
  * local drives only,
  * a companion that other models in the same folder also use is copied, never moved away from them,
  * a companion that already exists at the destination is reused when it is identical, and when it is not
    identical the whole bundle is left alone (a different file under the same name would break the model).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.parse
from dataclasses import dataclass, field

COMPANION_EXTS = (".obj", ".gltf", ".dae")        # the formats whose dependencies we can read
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".dds", ".gif", ".webp", ".hdr", ".exr"}
_HEAD = 64 * 1024                                  # where "mtllib" is looked for in an OBJ
_MTL_MAX = 4 * 1024 * 1024
_GLTF_MAX = 64 * 1024 * 1024
_DAE_MAX = 16 * 1024 * 1024
MAX_SIBLINGS = 2000                                # beyond this, every companion counts as shared
_MTL_OPTION_ARGS = {"-blendu": 1, "-blendv": 1, "-cc": 1, "-clamp": 1, "-texres": 1, "-imfchan": 1,
                    "-bm": 1, "-boost": 1, "-mm": 2, "-o": 3, "-s": 3, "-t": 3, "-type": 1}
_MTL_TEXTURE_KEYS = {"bump", "disp", "decal", "refl", "norm"}


class FileOpsError(Exception):
    """The operation cannot be planned at all (bad destination, not a local drive ...)."""


# ----------------------------------------------------------------------------- names and paths
def _nc(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def split_ext(name: str):
    """('model', '.obj'); the double extension .mesh.xml counts as one."""
    if name.lower().endswith(".mesh.xml"):
        return name[:-9], name[-9:]
    return os.path.splitext(name)


def unique_path(folder: str, name: str, style: str = "number", taken=None) -> str:
    """A path in `folder` that does not exist yet (and is not in `taken`, a set of normcased paths).
    style 'number': 'name (2).ext';  style 'copy': 'name - Copy.ext', 'name - Copy (2).ext'."""
    base, ext = split_ext(name)

    def busy(p):
        return os.path.exists(p) or (taken is not None and _nc(p) in taken)
    cand = os.path.join(folder, name)
    k = 1
    while busy(cand):
        k += 1
        if style == "copy":
            tag = " - Copy" if k == 2 else f" - Copy ({k - 1})"
        else:
            tag = f" ({k})"
        cand = os.path.join(folder, f"{base}{tag}{ext}")
    return cand


def _is_unc(path: str) -> bool:
    return path.startswith("\\\\")


def is_local(path: str) -> bool:
    """False for network shares (UNC paths, and mapped network drives on Windows)."""
    p = os.path.abspath(path)
    if sys.platform.startswith("win"):
        if _is_unc(p):
            return False
        try:
            import ctypes
            root = os.path.splitdrive(p)[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(root) != 4          # 4 = DRIVE_REMOTE
        except Exception:
            return True
    return True


def _inside(path: str, folder: str) -> bool:
    p, f = _nc(path), _nc(folder)
    try:
        return p != f and os.path.commonpath([p, f]) == f
    except ValueError:
        return False


def _same_content(a: str, b: str) -> bool:
    """Same size and same first and last 64 KB: enough to tell an identical copy from a different file."""
    try:
        sa = os.path.getsize(a)
        if sa != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            if fa.read(_HEAD) != fb.read(_HEAD):
                return False
            if sa > _HEAD:
                fa.seek(max(0, sa - _HEAD))
                fb.seek(max(0, sa - _HEAD))
                return fa.read(_HEAD) == fb.read(_HEAD)
        return True
    except OSError:
        return False


# ----------------------------------------------------------------------------- reading dependencies
def _read_text(path: str, limit: int) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _mtl_name(rest: str) -> str:
    """A texture line of an MTL file without its options: '-s 1 1 1 -bm 0.5 my map.png' -> 'my map.png'."""
    tokens = rest.split()
    i = 0
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 1 + _MTL_OPTION_ARGS.get(tokens[i].lower(), 0)
    return " ".join(tokens[i:])


def _clean_rel(name: str) -> str:
    return urllib.parse.unquote(name.strip().strip('"')).replace("\\", "/")


def _mtl_textures(mtl: str, model_folder: str) -> list:
    out = []
    folder = os.path.dirname(mtl)
    for line in _read_text(mtl, _MTL_MAX).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(None, 1)
        key = parts[0].lower()
        if len(parts) == 2 and (key.startswith("map_") or key in _MTL_TEXTURE_KEYS):
            name = _mtl_name(parts[1]).replace("\\", "/").strip('"')
            if not name:
                continue
            cand = os.path.normpath(os.path.join(folder, name))
            out.append(cand if os.path.isfile(cand) else os.path.normpath(os.path.join(model_folder, name)))
    return out


def _obj_refs(path: str) -> list:
    folder = os.path.dirname(path)
    refs = []
    for line in _read_text(path, _HEAD).splitlines():
        s = line.strip()
        if s[:6].lower() != "mtllib" or not s[6:7].isspace():
            continue
        rest = s[6:].strip()
        if not rest:
            continue
        whole = os.path.normpath(os.path.join(folder, rest.replace("\\", "/")))
        names = [whole] if os.path.isfile(whole) else [os.path.normpath(os.path.join(folder, n.replace("\\", "/")))
                                                       for n in rest.split()]
        for mtl in names:
            refs.append(mtl)
            if os.path.isfile(mtl):
                refs.extend(_mtl_textures(mtl, folder))
    return refs


def _gltf_refs(path: str) -> list:
    try:
        if os.path.getsize(path) > _GLTF_MAX:
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    folder = os.path.dirname(path)
    refs = []
    for group in ("buffers", "images"):
        for item in data.get(group) or []:
            uri = item.get("uri") if isinstance(item, dict) else None
            if isinstance(uri, str) and uri and not uri.startswith("data:") and "://" not in uri:
                refs.append(os.path.normpath(os.path.join(folder, _clean_rel(uri))))
    return refs


def _dae_refs(path: str) -> list:
    folder = os.path.dirname(path)
    refs = []
    for m in re.finditer(r"<init_from>\s*([^<]+?)\s*</init_from>", _read_text(path, _DAE_MAX)):
        name = m.group(1)
        if name.lower().startswith("file:///"):
            name = name[8:]
        if os.path.splitext(name)[1].lower() in IMAGE_EXTS and "://" not in name:
            refs.append(os.path.normpath(os.path.join(folder, _clean_rel(name))))
    return refs


def companion_files(path: str) -> list:
    """The existing files a model needs, inside its own folder (or below it), without the model itself.
    Anything outside that folder (an absolute path, '..') is ignored: we never reach out of the folder."""
    path = os.path.abspath(path)
    ext = os.path.splitext(path)[1].lower()
    reader = {".obj": _obj_refs, ".gltf": _gltf_refs, ".dae": _dae_refs}.get(ext)
    if reader is None:
        return []
    folder = os.path.dirname(path)
    out, seen = [], {_nc(path)}
    for ref in reader(path):
        k = _nc(ref)
        if k in seen or not _inside(ref, folder) or not os.path.isfile(ref):
            continue
        seen.add(k)
        out.append(os.path.normpath(ref))
    return out


def _outside_refs(folder: str, selected: set) -> set:
    """Companions (normcased) used by the models in `folder` that are *not* part of this transfer."""
    try:
        names = os.listdir(folder)
    except OSError:
        return set()
    sibs = [os.path.join(folder, n) for n in names if os.path.splitext(n)[1].lower() in COMPANION_EXTS]
    sibs = [s for s in sibs if _nc(s) not in selected]
    if len(sibs) > MAX_SIBLINGS:
        return {"*"}
    out = set()
    for s in sibs:
        out.update(_nc(c) for c in companion_files(s))
    return out


# ----------------------------------------------------------------------------- planning
@dataclass
class Step:
    src: str
    dst: str
    role: str            # 'model' or 'companion'
    action: str          # 'move', 'copy' or 'reuse' (already there, identical, or brought by an earlier bundle)
    fallback: str = "copy"   # what a 'reuse' becomes if the file turns out not to be there after all


@dataclass
class Bundle:
    model: Step
    companions: list = field(default_factory=list)


@dataclass
class Plan:
    dest: str
    move: bool
    bundles: list = field(default_factory=list)
    skipped: list = field(default_factory=list)       # (path, reason)
    notes: list = field(default_factory=list)

    def file_count(self) -> int:
        return sum(1 + sum(1 for c in b.companions if c.action != "reuse") for b in self.bundles)


def plan_transfer(paths, dest: str, move: bool, companions: bool = True) -> Plan:
    dest = os.path.abspath(dest)
    if not os.path.isdir(dest):
        raise FileOpsError(f"“{dest}” is not a folder.")
    if not is_local(dest):
        raise FileOpsError("Files can only be copied or moved on local drives, not network locations.")
    plan = Plan(dest, move)
    paths = [os.path.abspath(p) for p in paths]
    selected = {_nc(p) for p in paths}
    taken, claimed, outside = set(), {}, {}
    carried = set()                                    # selected files that travel as another model's companion
    if companions:
        for p in paths:
            if os.path.isfile(p):
                carried.update(_nc(c) for c in companion_files(p))
    for p in paths:
        name = os.path.basename(p)
        if _nc(p) in carried:
            continue
        if not os.path.isfile(p):
            plan.skipped.append((p, "the file is no longer there"))
            continue
        if not is_local(p):
            plan.skipped.append((p, "it is not on a local drive"))
            continue
        src_folder = os.path.dirname(p)
        same = _nc(src_folder) == _nc(dest)
        if move and same:
            plan.skipped.append((p, "it is already in that folder"))
            continue
        dst = unique_path(dest, name, "copy" if same else "number", taken)
        if _nc(dst) != _nc(os.path.join(dest, name)):
            plan.notes.append(f"{name} is saved as {os.path.basename(dst)} because that name was taken")
        steps, added, bad = [], [], ""
        if companions:
            for c in companion_files(p):
                rel = os.path.relpath(c, src_folder)
                target = os.path.join(dest, rel)
                tk = _nc(target)
                if tk == _nc(c):
                    steps.append(Step(c, target, "companion", "reuse"))
                elif claimed.get(tk, (None, ""))[0] == _nc(c):         # an earlier bundle of this plan brings it
                    steps.append(Step(c, target, "companion", "reuse", claimed[tk][1]))
                elif tk in claimed or (os.path.exists(target) and not _same_content(c, target)):
                    bad = f"{rel.replace(os.sep, '/')} already exists there and is a different file"
                    break
                elif os.path.exists(target):
                    steps.append(Step(c, target, "companion", "reuse"))
                else:
                    if move:
                        if _nc(src_folder) not in outside:
                            outside[_nc(src_folder)] = _outside_refs(src_folder, selected)
                        shared = "*" in outside[_nc(src_folder)] or _nc(c) in outside[_nc(src_folder)]
                    else:
                        shared = True
                    steps.append(Step(c, target, "companion", "copy" if shared else "move"))
                    claimed[tk] = (_nc(c), "copy" if shared else "move")
                    added.append(tk)
        if bad:
            for k in added:
                claimed.pop(k, None)
            plan.skipped.append((p, bad))
            continue
        taken.add(_nc(dst))
        for st in steps:
            if st.action == "copy" and move:
                plan.notes.append(f"{os.path.basename(st.src)} is used by other models, so it was copied, not moved")
        plan.bundles.append(Bundle(Step(p, dst, "model", "move" if move else "copy"), steps))
    return plan


# ----------------------------------------------------------------------------- doing it
@dataclass
class Result:
    moves: list = field(default_factory=list)         # (src, dst) of every file moved: what undo needs
    copies: list = field(default_factory=list)        # dst of every file copied
    models: list = field(default_factory=list)        # (src, dst, moved) per model that was transferred
    errors: list = field(default_factory=list)


def _move_file(src: str, dst: str):
    if os.path.exists(dst):
        raise FileExistsError(f"“{os.path.basename(dst)}” already exists")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)
        return
    except OSError:
        pass                                           # another drive, or locked: copy and then remove
    try:
        shutil.copy2(src, dst)
        if os.path.getsize(dst) != os.path.getsize(src):
            raise OSError("the copy is incomplete")
    except OSError:
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        raise
    os.remove(src)


def _copy_file(src: str, dst: str):
    if os.path.exists(dst):
        raise FileExistsError(f"“{os.path.basename(dst)}” already exists")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy2(src, dst)
    except OSError:
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        raise


def execute(plan: Plan, progress=None) -> Result:
    """Carry out a plan. `progress(done, total)` is called after every bundle; it may raise to stop."""
    res = Result()
    total = len(plan.bundles)
    for n, b in enumerate(plan.bundles, 1):
        done = []                                      # (action, step) in the order they were done
        moved_here = []
        try:
            for st in b.companions:
                action = st.action
                if action == "reuse":
                    if os.path.isfile(st.dst):
                        continue
                    if not os.path.isfile(st.src):
                        raise FileNotFoundError(f"“{os.path.basename(st.dst)}” is missing")
                    action = st.fallback                 # the earlier bundle did not bring it: do it now
                if action == "move":
                    _move_file(st.src, st.dst)
                    done.append(("move", st))
                    moved_here.append((st.src, st.dst))
                else:
                    _copy_file(st.src, st.dst)
                    done.append(("copy", st))
            if b.model.action == "move":
                _move_file(b.model.src, b.model.dst)
                moved_here.append((b.model.src, b.model.dst))
            else:
                _copy_file(b.model.src, b.model.dst)
        except OSError as e:
            for kind, st in reversed(done):             # put back what this bundle had already done
                try:
                    if kind == "move":
                        _move_file(st.dst, st.src)
                    elif os.path.exists(st.dst):
                        os.remove(st.dst)
                except OSError:
                    pass
            res.errors.append(f"{os.path.basename(b.model.src)}: {e}")
        else:
            res.moves.extend(moved_here)
            res.copies.extend(st.dst for k, st in done if k == "copy")
            if b.model.action == "copy":
                res.copies.append(b.model.dst)
            res.models.append((b.model.src, b.model.dst, b.model.action == "move"))
        if progress is not None:
            progress(n, total)
    return res


def undo_moves(moves) -> tuple:
    """Put moved files back (newest first). A file is only restored if it is still where it was moved to and its old
    place is free; anything else is left alone and reported. Returns (restored count, [skipped paths])."""
    restored, skipped = 0, []
    for src, dst in reversed(list(moves)):
        same_name = _nc(src) == _nc(dst)               # a rename that only changed the letter case (Windows)
        if not os.path.isfile(dst) or (os.path.exists(src) and not same_name):
            skipped.append(dst)
            continue
        try:
            if same_name:
                os.rename(dst, src)
            else:
                _move_file(dst, src)
            restored += 1
        except OSError:
            skipped.append(dst)
    return restored, skipped


# ----------------------------------------------------------------------------- batch rename
_BAD_CHARS = set('\\/:*?"<>|') | {chr(i) for i in range(32)}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_NAME = 200


@dataclass
class RenameItem:
    src: str
    name: str            # the new file name, with its extension
    dst: str
    problem: str = ""    # why this rename cannot be done ("" = fine)

    @property
    def changed(self) -> bool:
        return os.path.basename(self.src) != self.name


def expand_pattern(pattern: str, base: str, number: int) -> str:
    """'#' runs become the number padded to the run's length ('###' -> 001); '[name]' is the current name
    (without its extension)."""
    out = re.sub(r"#+", lambda m: str(number).zfill(len(m.group(0))), pattern)
    return out.replace("[name]", base)


def name_problem(name: str) -> str:
    """Why `name` cannot be a file name ('' if it can)."""
    if not name.strip():
        return "the name is empty"
    bad = sorted({c for c in name if c in _BAD_CHARS and c >= " "})
    if bad or any(c < " " for c in name):
        return "a name can't contain " + " ".join(bad or ["control characters"])
    if name != name.rstrip(" .") or name.startswith(" "):
        return "a name can't start with a space or end with a space or dot"
    if split_ext(name)[0].lower() in _RESERVED:
        return "that is a reserved Windows name"
    if len(name) > MAX_NAME:
        return "the name is too long"
    return ""


def plan_batch_rename(paths, pattern: str, first: int = 1) -> list:
    """Work out the new name of every file, in the order given (the numbers follow that order). Extensions are kept.
    A problem is reported per file; nothing is renamed unless every problem is gone."""
    items = []
    for i, p in enumerate(paths):
        p = os.path.abspath(p)
        base, ext = split_ext(os.path.basename(p))
        name = expand_pattern(pattern, base, first + i) + ext
        items.append(RenameItem(p, name, os.path.join(os.path.dirname(p), name)))
    leaving = {_nc(it.src) for it in items}                 # these names are free again once the rename is done
    count = {}
    for it in items:
        count[_nc(it.dst)] = count.get(_nc(it.dst), 0) + 1
    for it in items:
        if not os.path.isfile(it.src):
            it.problem = "the file is no longer there"
        elif not it.changed:
            continue
        elif (why := name_problem(it.name)):
            it.problem = why
        elif count[_nc(it.dst)] > 1:
            it.problem = "another file gets the same new name"
        elif os.path.exists(it.dst) and _nc(it.dst) not in leaving:
            it.problem = "a file with that name already exists"
    return items


def rename_many(pairs) -> tuple:
    """Rename (src, dst) pairs so that names can be swapped or shifted (a->b, b->c): everything goes to a temporary
    name first, then to its final one. If anything fails, everything is put back.
    Returns (pairs renamed, error text or '')."""
    pairs = [(os.path.abspath(a), os.path.abspath(b)) for a, b in pairs if _nc(a) != _nc(b) or a != b]
    if not pairs:
        return [], ""
    leaving = {_nc(a) for a, _b in pairs}
    seen = set()
    for a, b in pairs:
        if not os.path.isfile(a):
            return [], f"“{os.path.basename(a)}” is no longer there"
        if _nc(b) in seen or (os.path.exists(b) and _nc(b) not in leaving):
            return [], f"“{os.path.basename(b)}” already exists"
        seen.add(_nc(b))
    tag = f".g3d-{os.getpid()}-"
    temps = []                                              # (src, temp, dst) for what has been moved aside
    try:
        for i, (a, b) in enumerate(pairs):
            tmp = os.path.join(os.path.dirname(a), f"{tag}{i}{split_ext(a)[1]}")
            os.rename(a, tmp)
            temps.append((a, tmp, b))
    except OSError as e:
        for a, tmp, _b in reversed(temps):
            try:
                os.rename(tmp, a)
            except OSError:
                pass
        return [], str(e)
    placed = []
    try:
        for a, tmp, b in temps:
            os.rename(tmp, b)
            placed.append((a, tmp, b))
    except OSError as e:
        for a, tmp, b in reversed(placed):
            try:
                os.rename(b, tmp)
            except OSError:
                pass
        for a, tmp, _b in reversed(temps):
            try:
                os.rename(tmp, a)
            except OSError:
                pass
        return [], str(e)
    return [(a, b) for a, _t, b in temps], ""


# ----- drag and drop ------------------------------------------------------------------------------------------
def volume_of(path: str):
    """What drive or disk `path` is on (works for a folder that does not exist yet: its nearest existing parent counts)."""
    p = os.path.abspath(path)
    drive = os.path.splitdrive(p)[0]
    if drive:
        return drive.lower()
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return os.stat(p).st_dev
    except OSError:
        return None


def same_volume(a: str, b: str) -> bool:
    va, vb = volume_of(a), volume_of(b)
    return va is not None and va == vb


def droppable(paths, dest: str) -> list:
    """The dropped files that can go into `dest`: real files that are not in that folder already."""
    out = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p) and _nc(os.path.dirname(p)) != _nc(os.path.abspath(dest)) and p not in out:
            out.append(p)
    return out


def drop_is_move(paths, dest: str, ctrl: bool = False, shift: bool = False, internal: bool = True) -> bool:
    """Move or copy for a drop. Shift forces a move and Ctrl a copy. Otherwise files dragged inside the app move when
    they stay on the same drive and are copied to another drive; files dragged in from another program are copied
    (that program would otherwise delete its own originals)."""
    if shift:
        return True
    if ctrl or not internal:
        return False
    return bool(paths) and all(same_volume(p, dest) for p in paths)
