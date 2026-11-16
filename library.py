"""Gleek3Deek library: tags, colour labels and star ratings kept in one small JSON file next to the program.

Nothing is ever written into a model file. The file is plain text (easy to back up or edit), is saved safely
(temporary file, then rename, with one .bak copy) and records, for every tagged file, its path (relative to the
library file where possible) and a cheap fingerprint so a file renamed outside the app can be found again.
No Qt here: this module is pure Python so it can be tested without a window."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time

LIB_NAME = "gleek3deek-library.json"
RATING_MAX = 5
MAX_TAGS = 32
MAX_TAG_LEN = 40
RELINK_LIMIT = 300                                   # most files fingerprinted in one folder view

# (key, label, colour)
COLORS = [("red", "Red", "#e5534b"), ("orange", "Orange", "#e8903a"), ("yellow", "Yellow", "#d9b93a"),
          ("green", "Green", "#4caf6a"), ("blue", "Blue", "#4a8fe0"), ("purple", "Purple", "#9a6ad8"),
          ("gray", "Gray", "#8a929c")]
COLOR_KEYS = [c[0] for c in COLORS]


def _nk(key: str) -> str:
    """Comparison form of a key: case-insensitive where the file system is."""
    return key.lower() if os.name == "nt" else key


def clean_tag(t) -> str:
    t = re.sub(r"\s+", " ", str(t).replace(",", " ")).strip().lstrip("#").strip()
    return t[:MAX_TAG_LEN]


def clean_tags(tags) -> list:
    out, seen = [], set()
    for t in tags or []:
        t = clean_tag(t)
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_TAGS]


def split_tags(text: str) -> list:
    return clean_tags(text.split(","))


def normalise_color(c) -> str:
    c = str(c or "").strip().lower()
    c = "gray" if c == "grey" else c
    return c if c in COLOR_KEYS else ""


def fingerprint(path: str) -> str:
    """Size plus a hash of the first and last 64 KB: cheap, and survives renames and moves."""
    try:
        size = os.path.getsize(path)
        h = hashlib.sha1()
        with open(path, "rb") as f:
            h.update(f.read(65536))
            if size > 131072:
                f.seek(size - 65536)
                h.update(f.read(65536))
        return f"{size}:{h.hexdigest()[:16]}"
    except OSError:
        return ""


def resolve_library_path(base_dir: str, fallback_dir: str, override: str = "") -> str:
    """Where the library lives: the override if one is set, else next to the program when that folder is
    writable (or already holds a library), else the user's application-data folder."""
    if override:
        return override
    here = os.path.join(base_dir, LIB_NAME)
    if os.path.isfile(here) or os.access(base_dir, os.W_OK):
        return here
    return os.path.join(fallback_dir, LIB_NAME)


# ----- searching -----------------------------------------------------------------------------
_TERM = re.compile(r'(-?)(tag|color|colour|rating):("[^"]*"|\S+)|(#)("[^"]*"|\S+)|"([^"]*)"|(\S+)', re.I)
_RATING = re.compile(r"^(>=|<=|>|<|=)?\s*(\d)(\+)?$")


def parse_query(text: str) -> dict:
    """'rock tag:"hard surface" -tag:old color:red rating:>=3' -> a dict of terms. Unknown pieces are words
    (matched against the file name)."""
    q = {"words": [], "tags": [], "not_tags": [], "colors": [], "rating": None}
    for m in _TERM.finditer(text or ""):
        neg, kind, val, hash_, hval, quoted, word = m.groups()
        if kind:
            kind, val = kind.lower(), val.strip('"').strip()
            if kind == "tag":
                (q["not_tags"] if neg else q["tags"]).append(val.lower())
            elif kind in ("color", "colour"):
                c = normalise_color(val)
                if c or val.lower() in ("none", "no"):
                    q["colors"].append(c)
            else:
                r = _RATING.match(val)
                if r:
                    op = r.group(1) or (">=" if r.group(3) else "=")
                    q["rating"] = (op, int(r.group(2)))
        elif hash_:
            q["tags"].append(hval.strip('"').strip().lower())
        elif quoted is not None:
            if quoted.strip():
                q["words"].append(quoted.strip().lower())
        elif word:
            q["words"].append(word.lower())
    return q


def query_is_empty(q: dict) -> bool:
    return not (q["words"] or q["tags"] or q["not_tags"] or q["colors"] or q["rating"])


def query_uses_metadata(q: dict) -> bool:
    return bool(q["tags"] or q["not_tags"] or q["colors"] or q["rating"])


def _cmp(op: str, a: int, b: int) -> bool:
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b, "=": a == b}[op]


def matches(q: dict, name: str, meta: dict | None) -> bool:
    """Does a file called `name` with metadata `meta` (None = none) satisfy the parsed query?"""
    meta = meta or {}
    low = name.lower()
    tags = [t.lower() for t in meta.get("tags", [])]
    for w in q["words"]:
        if w not in low and not any(w in t for t in tags):
            return False
    for t in q["tags"]:
        if t not in tags:
            return False
    for t in q["not_tags"]:
        if t in tags:
            return False
    if q["colors"] and (meta.get("color", "") or "") not in q["colors"]:
        return False
    if q["rating"] is not None and not _cmp(q["rating"][0], int(meta.get("rating", 0) or 0), q["rating"][1]):
        return False
    return True


# ----- the store ------------------------------------------------------------------------------
class Library:
    def __init__(self, path: str):
        self.path = path
        self.root = os.path.dirname(os.path.abspath(path))
        self.files: dict = {}                        # comparison key -> {"p": key, "tags", "color", "rating", "fp"}
        self.smart: dict = {}                        # name -> query text
        self.error = ""                              # last problem, for the status bar ("" = none)
        self.notice = ""                             # one-time message (e.g. a damaged file was set aside)
        self._mtime = None
        self._dirty: set = set()
        self._dirty_smart: set = set()
        self.load()

    # ----- paths
    def key(self, path: str) -> str:
        p = os.path.abspath(path)
        try:
            k = os.path.relpath(p, self.root)
        except ValueError:                           # another drive: keep the full path
            k = p
        return k.replace("\\", "/")

    def abspath(self, key: str) -> str:
        return os.path.normpath(key if os.path.isabs(key) else os.path.join(self.root, key))

    # ----- reading and writing the file
    @staticmethod
    def _read(path: str):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or d.get("gleek3deek_library") != 1:
            raise ValueError("not a Gleek3Deek library")
        files, smart = {}, {}
        for p, e in (d.get("files") or {}).items():
            if not isinstance(e, dict):
                continue
            ent = {"p": str(p), "tags": clean_tags(e.get("tags")), "color": normalise_color(e.get("color")),
                   "rating": max(0, min(RATING_MAX, int(e.get("rating", 0) or 0))), "fp": str(e.get("fp") or "")}
            if ent["tags"] or ent["color"] or ent["rating"]:
                files[_nk(ent["p"])] = ent
        for n, qtext in (d.get("smart_folders") or {}).items():
            if isinstance(qtext, str) and str(n).strip():
                smart[str(n).strip()[:60]] = qtext
        return files, smart

    def load(self):
        self.files, self.smart, self.error = {}, {}, ""
        self._dirty, self._dirty_smart = set(), set()
        if not os.path.isfile(self.path):
            self._mtime = None
            return
        try:
            self.files, self.smart = self._read(self.path)
            self._mtime = os.path.getmtime(self.path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
            bad = f"{self.path}.damaged-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                os.replace(self.path, bad)           # never overwrite a file we could not read
                self.notice = f"The library file could not be read ({e}); it was kept as {os.path.basename(bad)}."
            except OSError:
                self.error = f"The library file could not be read: {e}"
            self._mtime = None

    def _merge_disk(self):
        """Another copy of the app saved since we loaded: take its changes, then lay ours over them."""
        try:
            files, smart = self._read(self.path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        for nk in self._dirty:
            if nk in self.files:
                files[nk] = self.files[nk]
            else:
                files.pop(nk, None)
        for n in self._dirty_smart:
            if n in self.smart:
                smart[n] = self.smart[n]
            else:
                smart.pop(n, None)
        self.files, self.smart = files, smart

    def save(self) -> bool:
        try:
            if os.path.isfile(self.path) and os.path.getmtime(self.path) != self._mtime:
                self._merge_disk()
            d = {"gleek3deek_library": 1,
                 "files": {e["p"]: {k: v for k, v in (("tags", e["tags"]), ("color", e["color"]),
                                                     ("rating", e["rating"]), ("fp", e["fp"])) if v}
                           for e in sorted(self.files.values(), key=lambda e: e["p"].lower())},
                 "smart_folders": dict(sorted(self.smart.items(), key=lambda kv: kv[0].lower()))}
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1, ensure_ascii=False)
            if os.path.isfile(self.path):
                try:
                    shutil.copy2(self.path, self.path + ".bak")
                except OSError:
                    pass
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
            self._dirty, self._dirty_smart = set(), set()
            self.error = ""
            return True
        except OSError as e:
            self.error = f"The library could not be saved: {e}"
            return False

    def move_to(self, new_path: str) -> bool:
        """Use another library file: an existing one is opened, otherwise the current data is copied there."""
        old = (self.path, self.root, self.files, self.smart)
        self.path = new_path
        self.root = os.path.dirname(os.path.abspath(new_path))
        if os.path.isfile(new_path):
            self.load()
            return not self.error
        # relative keys must follow the new root
        absolute = {self.abspath_from(old[1], e["p"]): e for e in old[2].values()}
        self.files, self.smart = {}, dict(old[3])
        for ap, e in absolute.items():
            k = self.key(ap)
            self.files[_nk(k)] = {**e, "p": k}
        self._mtime = None
        return self.save()

    @staticmethod
    def abspath_from(root: str, key: str) -> str:
        return os.path.normpath(key if os.path.isabs(key) else os.path.join(root, key))

    # ----- reading metadata
    def get(self, path: str) -> dict:
        e = self.files.get(_nk(self.key(path)))
        return {"tags": list(e["tags"]), "color": e["color"], "rating": e["rating"]} if e else \
            {"tags": [], "color": "", "rating": 0}

    def has_any(self) -> bool:
        return bool(self.files)

    def all_tags(self) -> list:
        """[(tag, number of files)] most used first."""
        n: dict = {}
        for e in self.files.values():
            for t in e["tags"]:
                n.setdefault(t.lower(), [t, 0])[1] += 1
        return sorted(((v[0], v[1]) for v in n.values()), key=lambda x: (-x[1], x[0].lower()))

    # ----- changing metadata (every change is saved at once)
    def _edit(self, paths, fn) -> bool:
        changed = False
        for path in paths:
            nk = _nk(self.key(path))
            e = self.files.get(nk) or {"p": self.key(path), "tags": [], "color": "", "rating": 0, "fp": ""}
            before = (list(e["tags"]), e["color"], e["rating"])
            fn(e)
            e["tags"] = clean_tags(e["tags"])
            e["color"] = normalise_color(e["color"])
            e["rating"] = max(0, min(RATING_MAX, int(e["rating"])))
            if (e["tags"], e["color"], e["rating"]) == before:
                continue
            changed = True
            self._dirty.add(nk)
            if e["tags"] or e["color"] or e["rating"]:
                e["fp"] = e["fp"] or fingerprint(path)
                self.files[nk] = e
            else:
                self.files.pop(nk, None)
        if changed:
            self.save()
        return changed

    def set_rating(self, paths, rating: int):
        return self._edit(paths, lambda e: e.__setitem__("rating", rating))

    def set_color(self, paths, color: str):
        return self._edit(paths, lambda e: e.__setitem__("color", color))

    def set_tags(self, path: str, tags):
        return self._edit([path], lambda e: e.__setitem__("tags", list(tags)))

    def change_tags(self, paths, removed, added):
        """Remove the tags in `removed` and add those in `added` for every file (others are kept)."""
        rm = {t.lower() for t in removed}
        return self._edit(paths, lambda e: e.__setitem__(
            "tags", [t for t in e["tags"] if t.lower() not in rm] + list(added)))

    def remove(self, path: str):
        nk = _nk(self.key(path))
        if nk in self.files:
            del self.files[nk]
            self._dirty.add(nk)
            self.save()

    def rename(self, old: str, new: str):
        """A file was renamed or moved inside the app: its data follows it."""
        ok = _nk(self.key(old))
        e = self.files.pop(ok, None)
        if e is None:
            return
        e["p"] = self.key(new)
        self.files[_nk(e["p"])] = e
        self._dirty.update((ok, _nk(e["p"])))
        self.save()

    def relink(self, folder: str, files) -> int:
        """Files of `folder` that were renamed outside the app: match them by fingerprint to entries whose file is
        gone. Cheap when nothing is missing (the usual case). Returns how many entries were re-attached."""
        fkey = os.path.normcase(os.path.abspath(folder))
        orphans = {}
        for nk, e in self.files.items():
            ap = self.abspath(e["p"])
            if e["fp"] and os.path.normcase(os.path.dirname(ap)) == fkey and not os.path.exists(ap):
                orphans.setdefault(e["fp"], []).append(nk)
        if not orphans:
            return 0
        done = 0
        for path in list(files)[:RELINK_LIMIT * 4]:
            if _nk(self.key(path)) in self.files:
                continue
            fp = fingerprint(path)
            cand = orphans.get(fp)
            if cand:
                old = cand.pop()
                e = self.files.pop(old)
                e["p"] = self.key(path)
                self.files[_nk(e["p"])] = e
                self._dirty.update((old, _nk(e["p"])))
                done += 1
        if done:
            self.save()
        return done

    # ----- smart folders (saved searches over the whole library)
    def save_smart(self, name: str, query: str):
        name = re.sub(r"\s+", " ", name).strip()[:60]
        if not name:
            return False
        self.smart[name] = query.strip()
        self._dirty_smart.add(name)
        return self.save()

    def delete_smart(self, name: str):
        if name in self.smart:
            del self.smart[name]
            self._dirty_smart.add(name)
            self.save()

    def find(self, query: str, exists=os.path.isfile) -> list:
        """Absolute paths of every library file that matches the query (files that no longer exist are skipped)."""
        q = parse_query(query)
        out = []
        for e in self.files.values():
            ap = self.abspath(e["p"])
            if matches(q, os.path.basename(ap), e) and exists(ap):
                out.append(ap)
        return sorted(out, key=lambda p: (os.path.basename(p).lower(), p.lower()))
