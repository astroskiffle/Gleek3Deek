"""Gleek3Deek gallery: background loading tasks, file icons, thumbnails (rendered offscreen), orientation memory and the thumbnail grid."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
import numpy as np
from PySide6.QtCore import (
    QObject, QRunnable, QSettings, QSize, QStandardPaths, Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QApplication, QFrame, QListWidget, QListWidgetItem, QListView, QAbstractItemView
from vtkmodules.util import numpy_support
from vtkmodules.vtkRenderingCore import (
    vtkPolyDataMapper, vtkRenderer, vtkRenderWindow, vtkWindowToImageFilter)
from formats import ALL_EXTS, ASSIMP, CAD, EXT_COLORS, LoadError, NATIVE, asset_ext, human_size, load_scene


# ---------------------------------------------------------------------------
# Async plumbing
# ---------------------------------------------------------------------------
class _Signals(QObject):
    done = Signal(int, object, str)
    failed = Signal(int, str)


class LoadTask(QRunnable):
    def __init__(self, token: int, path: str):
        super().__init__()
        self.token, self.path = token, path
        self.signals = _Signals()

    def run(self):
        try:
            actors = load_scene(self.path)
            self.signals.done.emit(self.token, actors, self.path)
        except LoadError as e:
            self.signals.failed.emit(self.token, str(e))
        except MemoryError:
            self.signals.failed.emit(self.token, "Out of memory while loading this asset.")
        except Exception as e:  # never let a worker kill the app
            tb = traceback.format_exc(limit=3)
            self.signals.failed.emit(self.token, f"Failed to parse file:\n{e}\n\n{tb}")


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------
_icon_cache: dict[str, QIcon] = {}


def asset_icon(ext: str) -> QIcon:
    if ext in _icon_cache:
        return _icon_cache[ext]
    S = 96
    pm = QPixmap(S, S)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    base = QColor(EXT_COLORS.get(ext, "#90A4AE"))

    def poly(pts, color):
        p.setBrush(QBrush(color))
        p.setPen(QPen(color.darker(160), 1.5))
        p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))

    if ext == "folder":
        poly([(10, 28), (38, 28), (46, 36), (86, 36), (86, 76), (10, 76)], base)
    else:
        poly([(48, 10), (84, 28), (48, 46), (12, 28)], base.lighter(130))   # top
        poly([(12, 28), (48, 46), (48, 86), (12, 66)], base)                # left
        poly([(84, 28), (48, 46), (48, 86), (84, 66)], base.darker(130))    # right
        p.setPen(QColor("#10141a"))
        p.setFont(QFont("Sans", 9, QFont.Bold))
        p.drawText(pm.rect().adjusted(0, 0, 0, -2), Qt.AlignHCenter | Qt.AlignBottom,
                   ext.lstrip(".").split(".")[0].upper())
    p.end()
    ic = QIcon(pm)
    _icon_cache[ext] = ic
    return ic


def scan_assets(folder: str) -> list[str]:
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(folder, n)
        if asset_ext(n) in ALL_EXTS and os.path.isfile(p):
            out.append(p)
    return out


class OrientStore:
    """Remembers whether a file is Y-up (default) or Z-up, keyed by path."""

    def __init__(self):
        self._s = None

    def _settings(self):
        if self._s is None:
            self._s = QSettings("Gleek3Deek", "Gleek3Deek")
        return self._s

    @staticmethod
    def _key(path: str) -> str:
        return "up/" + hashlib.sha1(os.path.normcase(path).encode("utf-8", "replace")).hexdigest()[:20]

    def get(self, path: str) -> str:
        return "Z" if str(self._settings().value(self._key(path), "Y")) == "Z" else "Y"

    def set(self, path: str, up: str):
        if up == "Z":
            self._settings().setValue(self._key(path), "Z")
        else:
            self._settings().remove(self._key(path))


ORIENT = OrientStore()


def iso_camera(ren, up: str = "Y"):
    """Three-quarter view from front-right-above, for a Y-up or Z-up model."""
    ren.ResetCamera()
    cam = ren.GetActiveCamera()
    fp = np.array(cam.GetFocalPoint())
    dist = cam.GetDistance()
    if up == "Z":
        d, vup = np.array((0.8, -1.0, 0.6)), (0, 0, 1)
    else:
        d, vup = np.array((0.8, 0.6, 1.0)), (0, 1, 0)
    d = d / np.linalg.norm(d)
    cam.SetPosition(*(fp + d * dist))
    cam.SetViewUp(*vup)
    ren.ResetCamera()


# ---------------------------------------------------------------------------
# Thumbnails: parse on worker threads, render on ONE shared offscreen window
# (main thread, one model per tick), cache PNGs on disk keyed by path+mtime+size.
# ---------------------------------------------------------------------------
THUMB_PX = 192


THUMB_EXTS = NATIVE | CAD | ASSIMP            # no Blender spawns for thumbnails


MAX_THUMB_BYTES = int(os.environ.get("GLEEK_THUMB_MAX_MB", "200")) * 1024 * 1024


class _ThumbSignals(QObject):
    done = Signal(int, str, object)
    failed = Signal(int, str)


class ThumbTask(QRunnable):
    def __init__(self, gen: int, path: str):
        super().__init__()
        self.gen, self.path = gen, path
        self.signals = _ThumbSignals()

    def run(self):
        try:
            self.signals.done.emit(self.gen, self.path, load_scene(self.path))
        except BaseException:
            self.signals.failed.emit(self.gen, self.path)


class ThumbnailManager(QObject):
    ready = Signal(str, QPixmap)

    def __init__(self):
        super().__init__()
        base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation) \
            or tempfile.gettempdir()
        self.cache_dir = Path(base) / "thumbs"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.cache_dir = Path(tempfile.gettempdir()) / "gleek3deek_thumbs"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)       # keep the global pool free for the viewer
        self.gen = 0
        self.pending: deque = deque()        # (path, cache_file)
        self.render_q: deque = deque()       # (path, polydata)
        self.inflight = 0
        self._tasks: dict = {}
        self._disabled = False
        self._rw = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_one)

    # ---- public
    def request_batch(self, paths: list[str]):
        self.gen += 1                         # invalidates everything in flight
        self.pending.clear()
        self.render_q.clear()
        if self._disabled:
            return
        for p in paths:
            cf = self._cache_file(p)
            if cf is not None:
                self.pending.append((p, cf))
        self._pump()

    def refresh(self, path: str, force: bool = False):
        """Re-render one thumbnail now. force=True discards the cached picture first."""
        cf = self._cache_file(path)
        if cf is None or self._disabled:
            return
        if force:
            self._unlink(cf)
        self.pending.appendleft((path, cf))
        self._pump()

    @staticmethod
    def _unlink(cf):
        try:
            cf.unlink()
        except OSError:
            pass

    def forget(self, path: str):
        """Drop the cached picture for a file so the next request re-renders it."""
        cf = self._cache_file(path)
        if cf is not None:
            self._unlink(cf)

    def adopt(self, old_cache, new_path: str):
        """After a rename or copy, reuse the old thumbnail for the new file name."""
        new_cache = self._cache_file(new_path)
        if old_cache is None or new_cache is None or not old_cache.exists() or new_cache.exists():
            return
        try:
            shutil.copy2(old_cache, new_cache)
        except OSError:
            pass

    def shutdown(self):
        self.gen += 1
        self.pending.clear()
        self.render_q.clear()
        self._rw = None

    # ---- internals
    def _cache_file(self, path: str) -> Path | None:
        if asset_ext(path) not in THUMB_EXTS:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        if st.st_size > MAX_THUMB_BYTES:
            return None
        key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}|{ORIENT.get(path)}|v2".encode()).hexdigest()[:24]
        return self.cache_dir / f"{key}.png"

    def _pump(self):
        n = 0
        while self.pending and n < 24:
            path, cf = self.pending[0]
            if cf.exists():                   # cache hit: cheap
                self.pending.popleft()
                n += 1
                pm = QPixmap(str(cf))
                if not pm.isNull():
                    self.ready.emit(path, pm)
                continue
            if self.inflight >= 2 or len(self.render_q) >= 2:
                return                        # resumed by done / render callbacks
            self.pending.popleft()
            n += 1
            task = ThumbTask(self.gen, path)
            task.signals.done.connect(self._on_done)
            task.signals.failed.connect(self._on_failed)
            self._tasks[(self.gen, path)] = task
            self.inflight += 1
            self.pool.start(task)
        if self.pending:
            QTimer.singleShot(0, self._pump)

    def _on_done(self, gen: int, path: str, pd):
        self._tasks.pop((gen, path), None)
        self.inflight -= 1
        if gen == self.gen:
            self.render_q.append((path, pd))
            self._timer.start(0)
        self._pump()

    def _on_failed(self, gen: int, path: str):
        self._tasks.pop((gen, path), None)
        self.inflight -= 1
        self._pump()                          # keep the generic icon

    def _render_one(self):
        if not self.render_q:
            return
        path, pd = self.render_q.popleft()
        try:
            img = self._render(pd, ORIENT.get(path))
            cf = self._cache_file(path)
            if cf is not None:
                img.save(str(cf), "PNG")
            self.ready.emit(path, QPixmap.fromImage(img))
        except Exception:
            if self._rw is None:              # couldn't even create offscreen GL
                self._disabled = True
                self.pending.clear()
                self.render_q.clear()
        if self.render_q:
            self._timer.start(0)
        self._pump()

    def _ensure_window(self):
        if self._rw is not None:
            return
        rw = vtkRenderWindow()
        rw.SetOffScreenRendering(1)
        rw.SetSize(THUMB_PX, THUMB_PX)
        rw.SetMultiSamples(4)
        ren = vtkRenderer()
        ren.GradientBackgroundOn()
        ren.SetBackground(0.10, 0.11, 0.14)
        ren.SetBackground2(0.20, 0.22, 0.27)
        rw.AddRenderer(ren)
        self._ren, self._mapper = ren, vtkPolyDataMapper()
        self._rw = rw

    def _render(self, actors, up: str = "Y") -> QImage:
        self._ensure_window()
        ren, rw = self._ren, self._rw
        for a in actors:
            ren.AddActor(a)
        try:
            iso_camera(ren, up)
            ren.GetActiveCamera().Zoom(1.1)
            rw.Render()
            w2i = vtkWindowToImageFilter()
            w2i.SetInput(rw)
            w2i.SetInputBufferTypeToRGB()
            w2i.ReadFrontBufferOff()
            w2i.Update()
            vimg = w2i.GetOutput()
            w, h, _ = vimg.GetDimensions()
            arr = numpy_support.vtk_to_numpy(vimg.GetPointData().GetScalars())
            arr = np.ascontiguousarray(arr.reshape(h, w, 3)[::-1])   # VTK origin is bottom-left
            return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        finally:
            for a in actors:
                ren.RemoveActor(a)


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------
SORTS = [
    ("Name A–Z", lambda e: e["name"].lower(), False),
    ("Name Z–A", lambda e: e["name"].lower(), True),
    ("Newest first", lambda e: e["mtime"], True),
    ("Oldest first", lambda e: e["mtime"], False),
    ("Largest first", lambda e: e["size"], True),
    ("Smallest first", lambda e: e["size"], False),
    ("Type", lambda e: (e["ext"], e["name"].lower()), False),
]


def _setting_int(settings, key: str, default: int) -> int:
    try:
        return int(settings.value(key, default))
    except (TypeError, ValueError):
        return default


class Gallery(QListWidget):
    open_asset = Signal(str)
    open_folder = Signal(str)
    counts = Signal(int, int)          # models shown, models total
    rename_requested = Signal(str)
    copy_requested = Signal(str)
    paste_requested = Signal()
    delete_requested = Signal(str)
    refresh_thumb_requested = Signal(str)
    refresh_all_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.set_card_size(88)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFrameShape(QFrame.NoFrame)
        self.itemDoubleClicked.connect(self._activated)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        for key, fn in (("F2", lambda: self._emit_file(self.rename_requested)),
                        ("Delete", lambda: self._emit_file(self.delete_requested)),
                        ("Ctrl+C", lambda: self._emit_file(self.copy_requested)),
                        ("Ctrl+V", lambda: self.paste_requested.emit()),
                        ("F5", self._refresh_key)):
            QShortcut(QKeySequence(key), self, activated=fn, context=Qt.WidgetShortcut)
        self.folder = ""
        self._entries: list[dict] = []
        self._filter = ""
        self._sort = 0
        self._thumbs: dict[str, QPixmap] = {}
        self._items: dict[str, QListWidgetItem] = {}
        self._order: list[str] = []

    # ----- view options
    def set_card_size(self, px: int):
        self.setIconSize(QSize(px, px))
        self.setGridSize(QSize(px + 44, px + 50))

    def set_filter(self, text: str):
        self._filter = text
        self._rebuild()

    def set_sort(self, idx: int):
        self._sort = max(0, min(idx, len(SORTS) - 1))
        self._rebuild()

    def asset_paths(self) -> list[str]:
        """Models currently shown, in display order."""
        return list(self._order)

    def select_path(self, path: str):
        it = self._items.get(path)
        if it is not None:
            self.setCurrentItem(it)
            self.scrollToItem(it)

    def set_thumb(self, path: str, pm: QPixmap):
        self._thumbs[path] = pm
        it = self._items.get(path)
        if it is not None:
            it.setIcon(QIcon(pm))

    # ----- content
    def populate(self, folder: str) -> list[str]:
        self.folder = folder
        self._filter = ""
        self._thumbs = {}
        entries = []
        try:
            with os.scandir(folder) as scan:
                for e in scan:
                    if e.name.startswith("."):
                        continue
                    try:
                        if e.is_dir():
                            entries.append({"path": e.path, "name": e.name, "ext": "",
                                            "dir": True, "size": 0, "mtime": 0.0})
                        else:
                            ext = asset_ext(e.name)
                            if ext in ALL_EXTS:
                                st = e.stat()
                                entries.append({"path": e.path, "name": e.name, "ext": ext,
                                                "dir": False, "size": st.st_size,
                                                "mtime": st.st_mtime})
                    except OSError:
                        continue
        except OSError:
            entries = []
        self._entries = entries
        self._rebuild()
        return [e["path"] for e in entries if not e["dir"]]

    def _rebuild(self):
        f = self._filter.strip().lower()
        shown = [e for e in self._entries if not f or f in e["name"].lower()]
        _label, key, rev = SORTS[self._sort]
        dirs = sorted((e for e in shown if e["dir"]), key=lambda e: e["name"].lower())
        files = sorted((e for e in shown if not e["dir"]), key=key, reverse=rev)
        self.setUpdatesEnabled(False)
        self.clear()
        self._items = {}
        self._order = []
        for e in dirs + files:
            if e["dir"]:
                it = QListWidgetItem(asset_icon("folder"), e["name"])
                it.setData(Qt.UserRole, (e["path"], True))
            else:
                pm = self._thumbs.get(e["path"])
                it = QListWidgetItem(QIcon(pm) if pm is not None else asset_icon(e["ext"]), e["name"])
                it.setData(Qt.UserRole, (e["path"], False))
                when = datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M")
                it.setToolTip(f'{e["path"]}\n{human_size(e["size"])}  ·  {when}')
                self._items[e["path"]] = it
                self._order.append(e["path"])
            self.addItem(it)
        self.setUpdatesEnabled(True)
        total = sum(1 for e in self._entries if not e["dir"])
        self.counts.emit(len(files), total)

    def _refresh_key(self):
        path = self._current_file()
        if path:
            self.refresh_thumb_requested.emit(path)
        else:
            self.refresh_all_requested.emit()

    def clear_thumb(self, path: str):
        """Back to the generic cube icon while a fresh thumbnail is rendered."""
        self._thumbs.pop(path, None)
        it = self._items.get(path)
        if it is not None:
            it.setIcon(asset_icon(asset_ext(path)))

    def file_paths(self) -> list[str]:
        return [e["path"] for e in self._entries if not e["dir"]]

    def _current_file(self) -> str:
        item = self.currentItem()
        if item is None:
            return ""
        path, is_dir = item.data(Qt.UserRole)
        return "" if is_dir else path

    def _emit_file(self, signal):
        path = self._current_file()
        if path:
            signal.emit(path)

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        path, is_dir = item.data(Qt.UserRole) if item is not None else ("", False)
        if item is not None:
            self.setCurrentItem(item)
        menu = QMenu(self)
        if item is not None:
            menu.addAction("Open", lambda _=False: (self.open_folder if is_dir else self.open_asset).emit(path))
            if not is_dir:
                menu.addSeparator()
                menu.addAction("Rename…\tF2", lambda _=False: self.rename_requested.emit(path))
                menu.addAction("Copy\tCtrl+C", lambda _=False: self.copy_requested.emit(path))
                menu.addAction("Refresh thumbnail\tF5", lambda _=False: self.refresh_thumb_requested.emit(path))
        mime = QApplication.clipboard().mimeData()
        paste = menu.addAction("Paste\tCtrl+V", lambda _=False: self.paste_requested.emit())
        paste.setEnabled(bool(mime is not None and mime.hasUrls()))
        if item is None:
            menu.addSeparator()
            menu.addAction("Refresh all thumbnails\tF5", lambda _=False: self.refresh_all_requested.emit())
        if item is not None and not is_dir:
            menu.addSeparator()
            menu.addAction("Delete\tDel", lambda _=False: self.delete_requested.emit(path))
        menu.exec(self.viewport().mapToGlobal(pos))

    def _activated(self, item: QListWidgetItem):
        path, is_dir = item.data(Qt.UserRole)
        (self.open_folder if is_dir else self.open_asset).emit(path)
