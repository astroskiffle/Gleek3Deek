"""The 3D viewer widget: scene, camera, lighting and shading modes, measurements, analyses, export.

Split out of main.py so the window code (folder tree, gallery, menus) and the viewer code can be read and changed
separately. This module must not import main.py. The application name and the About-box wording live here
(ABOUT) because the viewer's context menu uses them too.
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from pathlib import Path
import numpy as np
from PySide6.QtCore import (
    QEvent, QObject, QRunnable, QSettings, QStandardPaths, Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtCore import QLineF, QPointF, QRectF
from PySide6.QtGui import QPainterPath
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout, QMenu, QMessageBox,
    QPushButton)
from PySide6.QtGui import QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QSplitter, QToolButton, QVBoxLayout, QWidget)
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401  (registers GL backend)
import vtkmodules.vtkInteractionStyle  # noqa: F401  (registers styles)
import vtkmodules.vtkRenderingFreeType  # noqa: F401  (text for the axes gizmo)
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.util import numpy_support
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPlane, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkCutter
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkCellPicker, vtkPolyDataMapper, vtkRenderer, vtkLight, vtkSkybox, vtkTexture,
    vtkWindowToImageFilter)
try:                                          # 2D overlay props for the split-compare divider
    from vtkmodules.vtkRenderingCore import vtkActor2D, vtkPolyDataMapper2D
except Exception:  # pragma: no cover
    vtkActor2D = vtkPolyDataMapper2D = None
from vtkmodules.vtkFiltersSources import vtkLineSource, vtkOutlineSource, vtkPlaneSource, vtkSphereSource
try:                                          # 3D text for measurement labels
    from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D
except Exception:  # pragma: no cover
    vtkBillboardTextActor3D = None
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from formats import _face_count, _log_size, _mapper_data, _shader_error_since, human_size
from analysis import (
    EXPORT_FORMATS, LOD_LEVELS, SHEET_BACKGROUNDS, SHEET_CELLS, SHEET_ENV, SHEET_LAYOUTS, UNITS,
    UV_COLOR_OK, UV_HEAT_DEFAULTS, UV_ISLAND_TESTS, UV_TESTS, _HEAT_STOPS, _STRETCH_STOPS, angle_at,
    build_export_polydata, collect_model_info, export_default_name, fmt_num, lod_decimate,
    measure_model, Cancelled, cavity_part, mesh_part_analysis, mesh_totals, run_parts, sheet_framing,
    sheet_views, snapshot_export_parts, texture_channel_rgb, texture_to_array, unit_scale,
    uv_collect_part, uv_heat_density, uv_heat_stretch, uv_poly_colors, weighted_median, world_parts,
    write_mesh)
from panels import ExportDialog, InfoPanel, MaterialsPanel, ScenePanel, VIEW_CHANNELS, _rgb_to_qimage
from environment import (
    ENV_BUILTIN_PRESETS, ENV_DEFAULTS, EnvironmentPanel, SKY_TEX_W, blob_texture_array, clean_env,
    dir_to_azel, env_shader_code, frame_to_world, numpy_to_vtk_image, pano_frame_matrix,
    prepare_panorama, read_panorama, reproject_panorama, sun_dir_frame)
from gallery import ORIENT, _setting_int
from matcap import MATCAPS, MatCapEditor, custom_matcap_parts, default_spec, preset_to_spec, spec_to_preset

APP_NAME = "Gleek3Deek"


# ---------------------------------------------------------------------------
# About dialog text. EDIT FREELY: everything the About dialog shows comes from this block.
# ---------------------------------------------------------------------------
ABOUT = {
    "app_name": APP_NAME,
    "tagline": "A fast, minimal 3D asset viewer and manager.",
    "version": "",                      # leave empty to hide; set e.g. "0.4.0" when you are ready
    # --- who made it
    "author_heading": "Created by",
    "author_name": "Mark Billson",
    "author_alias": "Astroskiffle",
    "author_note": "",                  # optional extra line, e.g. a website or contact address
    # --- legal
    "legal_heading": "Legal",
    "copyright": "Copyright (c) 2026 Mark Billson (Astroskiffle)",
    "legal_notice": "Provided as is, without warranty.",
    # --- licence and attributions
    "licence_heading": "Licence",
    "licence_intro": f"{APP_NAME} is open-source software released under the MIT Licence.",
    "licence_text": (
        "{copyright}\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy of this "
        "software and associated documentation files (the \"Software\"), to deal in the Software "
        "without restriction, including without limitation the rights to use, copy, modify, merge, "
        "publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons "
        "to whom the Software is furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all copies or "
        "substantial portions of the Software.\n\n"
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, "
        "INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR "
        "PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE "
        "FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR "
        "OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER "
        "DEALINGS IN THE SOFTWARE."),
    "third_party_heading": "Open-source attributions",
    "third_party_intro": f"{APP_NAME} is built with the following open-source projects:",
    # (name, licence, website). Check each against the version you ship.
    "third_party": [
        ("PySide6 / Qt for Python", "LGPL-3.0", "https://doc.qt.io/qtforpython-6/"),
        ("VTK (Visualization Toolkit)", "BSD-3-Clause", "https://vtk.org/"),
        ("NumPy", "BSD-3-Clause", "https://numpy.org/"),
        ("Assimp, via assimp-py (optional)", "BSD-3-Clause", "https://github.com/assimp/assimp"),
        ("Draco, via DracoPy (optional)", "Apache-2.0", "https://github.com/google/draco"),
        ("meshoptimizer, via the meshoptimizer package (optional)", "MIT", "https://github.com/zeux/meshoptimizer"),
        ("CadQuery (optional)", "Apache-2.0", "https://github.com/CadQuery/cadquery"),
    ],
    "third_party_note": "Each project remains under its own licence; see its website for the full terms.",
    "close_label": "Close",
}


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------
class Overlay(QLabel):
    """Native-window label so it stays above the VTK GL surface."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.hide()

    def show_text(self, text: str, error: bool):
        color = "#ff8a80" if error else "#e0e6ed"
        border = "#c62828" if error else "#3a4656"
        self.setStyleSheet(f"background:#1b2028;color:{color};border:1px solid {border};"
                           "border-radius:8px;padding:16px;font-size:13px;")
        self.setText(text)
        self.setFixedWidth(min(560, max(260, self.parent().width() - 80)))
        self.adjustSize()
        self.setFixedWidth(min(560, max(260, self.parent().width() - 80)))
        self.reposition()
        self.show()
        self.raise_()

    def reposition(self):
        p = self.parent()
        self.move((p.width() - self.width()) // 2, (p.height() - self.height()) // 2)


class _AnalysisSignals(QObject):
    progress = Signal(str)
    done = Signal(int, object)
    failed = Signal(int, str)


class AnalysisTask(QRunnable):
    """Runs one per-part analysis (UV tests or integrity tests) on a worker thread. It only ever sees read-only
    copies of the geometry. Cancelling is checked between parts and between the stages of a part, so it takes
    effect within a moment, not instantly."""

    def __init__(self, token: int, func, inputs: list, label: str):
        super().__init__()
        self.token, self.func, self.inputs, self.label = token, func, inputs, label
        self.cancelled = False
        self.signals = _AnalysisSignals()
        self._last = 0.0

    def _progress(self, text: str):
        now = time.monotonic()
        if now - self._last >= 0.15:                 # a model with thousands of parts must not flood the window
            self._last = now
            self.signals.progress.emit(text)

    def run(self):
        try:
            res = run_parts(self.func, self.inputs, self.label, lambda: self.cancelled, self._progress)
            self.signals.done.emit(self.token, res)
        except Cancelled:
            self.signals.failed.emit(self.token, "cancelled")
        except Exception as e:
            self.signals.failed.emit(self.token, str(e) or type(e).__name__)


class _LodSignals(QObject):
    progress = Signal(str)
    done = Signal(int, object)
    failed = Signal(int, str)


class LodTask(QRunnable):
    """Builds the LOD levels for every part in the background."""

    def __init__(self, token: int, inputs: list):
        super().__init__()
        self.token, self.inputs = token, inputs
        self.cancelled = False
        self.signals = _LodSignals()

    def run(self):
        try:
            res = {}
            n = len(self.inputs)
            for lvl, red in LOD_LEVELS:
                outs = []
                for i, pd in enumerate(self.inputs):
                    if self.cancelled:
                        self.signals.failed.emit(self.token, "cancelled")
                        return
                    self.signals.progress.emit(f"Simplifying to {lvl}%: part {i + 1} of {n} …")
                    try:
                        outs.append(lod_decimate(pd, red))
                    except Exception:
                        outs.append(None)
                res[lvl] = outs
            self.signals.done.emit(self.token, res)
        except Exception as e:
            self.signals.failed.emit(self.token, str(e) or type(e).__name__)


class _ExportSignals(QObject):
    done = Signal(str)
    failed = Signal(str)


class ExportTask(QRunnable):
    def __init__(self, parts, path, kind, binary, keep):
        super().__init__()
        self.parts, self.path, self.kind, self.binary, self.keep = parts, path, kind, binary, keep
        self.signals = _ExportSignals()

    def run(self):
        try:
            mesh, n_in, n_out = build_export_polydata(self.parts, self.keep, normals=(self.kind == "obj"))
            write_mesh(mesh, self.path, self.kind, self.binary)
            size = human_size(os.path.getsize(self.path))
            change = f" (from {n_in:,})" if n_out != n_in else ""
            self.signals.done.emit(f"Exported {n_out:,} triangles{change} to {self.path}  [{size}]")
        except Exception as e:
            self.signals.failed.emit(str(e) or type(e).__name__)


# ---------------------------------------------------------------------------
# Scene helpers: ground grid, camera, display and screenshot options
# ---------------------------------------------------------------------------
def nice_step(x: float) -> float:
    """Round a length up to 1, 2, 5 or 10 times a power of ten."""
    x = max(float(x), 1e-12)
    p = 10.0 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * p >= x * 0.999:
            return m * p
    return 10 * p


def ground_grid_geometry(lo, hi, up: str):
    """Grid plane under the model. Returns (origin, point1, point2, cells_per_side, cell_size).
    Lines are aligned to whole multiples of the cell size, so they line up with the world axes.
    point1 / point2 are ordered so the plane's normal points up."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    h0, h1, vax = (0, 1, 2) if up == "Z" else (0, 2, 1)
    ext = np.maximum(hi - lo, 1e-9)
    foot = 2.2 * max(ext[h0], ext[h1])
    cell = nice_step(foot / 12.0)
    half_cells = min(max(int(math.ceil(foot / 2.0 / cell)), 2), 40)
    half = half_cells * cell
    c0 = round(((lo[h0] + hi[h0]) / 2.0) / cell) * cell
    c1 = round(((lo[h1] + hi[h1]) / 2.0) / cell) * cell
    level = lo[vax] - 0.004 * float(ext.max())          # a hair below the shadow blob
    o0, o1, s = c0 - half, c1 - half, 2.0 * half
    if up == "Z":
        o, p1, p2 = (o0, o1, level), (o0 + s, o1, level), (o0, o1 + s, level)
    else:
        o, p1, p2 = (o0, level, o1), (o0, level, o1 + s), (o0 + s, level, o1)
    return o, p1, p2, 2 * half_cells, cell


def fov_distance(dist: float, old_deg: float, new_deg: float) -> float:
    """Camera distance that keeps the subject the same size when the field of view changes."""
    return dist * math.tan(math.radians(old_deg / 2.0)) / math.tan(math.radians(new_deg / 2.0))


def turntable_rel(rel, up, view_up, theta: float, d_el: float, limit_deg: float = 88.0):
    """Turntable orbit: new camera offset (camera position minus focal point).
    Turn by `theta` about the world up axis, then tilt by `d_el`, never past +/- limit_deg from the
    horizon. The horizon never rolls and the camera can't flip over the poles."""
    rel, up = np.asarray(rel, float), np.asarray(up, float)
    r = float(np.linalg.norm(rel))
    if r < 1e-12:
        return rel
    c, s = math.cos(theta), math.sin(theta)
    rel = rel * c + np.cross(up, rel) * s + up * float(np.dot(up, rel)) * (1.0 - c)   # azimuth about up
    height = float(np.dot(rel, up))
    horiz = rel - height * up
    hn = float(np.linalg.norm(horiz))
    if hn < 1e-9 * r:                                   # looking straight along the up axis
        vu = np.asarray(view_up, float)
        horiz = vu - float(np.dot(vu, up)) * up
        hn = float(np.linalg.norm(horiz))
        if hn < 1e-9:
            horiz = np.cross(up, [1.0, 0.0, 0.0] if abs(up[0]) < 0.9 else [0.0, 1.0, 0.0])
            hn = float(np.linalg.norm(horiz))
    el = math.atan2(height, hn) + d_el
    lim = math.radians(limit_deg)
    el = max(-lim, min(lim, el))
    return r * (math.cos(el) * (horiz / hn) + math.sin(el) * up)


def matte_rgba(on_black: np.ndarray, on_white: np.ndarray) -> np.ndarray:
    """Recover colour + transparency from the same render on a black and on a white backdrop.
    A pixel is alpha*colour + (1-alpha)*backdrop, so the two renders differ by (1-alpha)*255."""
    a, b = on_black.astype(np.float32), on_white.astype(np.float32)
    alpha = np.clip(1.0 - (b - a).mean(axis=2) / 255.0, 0.0, 1.0)
    color = np.where(alpha[..., None] > 1e-3, a / np.maximum(alpha[..., None], 1e-3), 0.0)
    return np.dstack([np.clip(color, 0, 255), alpha * 255.0]).astype(np.uint8)


# ---------------------------------------------------------------------------
# Material viewing: channel views (albedo / normals), texture list, parts list
# ---------------------------------------------------------------------------
# Fragment-shader bodies for the 'Light::Impl' slot. Literals only, no uniforms.
VIEW_SHADERS = {
    "albedo": """
  fragOutput0 = vec4(clamp(diffuseColor, 0.0, 1.0), opacity);
""",
    "normals": """
  vec3 nvCol = normalize(normalVCVSOutput) * 0.5 + 0.5;
  if (!gl_FrontFacing) nvCol = mix(nvCol, vec3(0.95, 0.10, 0.10), 0.65);
  fragOutput0 = vec4(nvCol, opacity);
""",
}


# (name, bottom colour, top colour); equal colours = flat background
BACKGROUNDS = [
    ("Dark gradient", (0.07, 0.08, 0.10), (0.17, 0.19, 0.23)),
    ("Mid grey", (0.30, 0.31, 0.33), (0.45, 0.46, 0.49)),
    ("Light grey", (0.74, 0.76, 0.80), (0.92, 0.93, 0.95)),
    ("White", (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),
    ("Black", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
]


CUSTOM_BG = len(BACKGROUNDS)


ORBIT_SPEEDS = [("Slow", 12.0), ("Medium", 30.0), ("Fast", 60.0)]   # degrees per second


VIEW_LABELS = [("front", "Front\t1"), ("back", "Back\t2"), ("right", "Right\t3"),
               ("left", "Left\t4"), ("top", "Top\t5"), ("bottom", "Bottom\t6"),
               ("iso", "Isometric\t7")]


class ReferenceSheetDialog(QDialog):
    """Options for the AI reference sheet."""

    def __init__(self, parent, settings: QSettings):
        super().__init__(parent)
        self.setWindowTitle("Reference sheet for AI 3D tools")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel("Renders the model from several angles on one image, for Meshy, Tripo, Rodin, Luma and "
                       "similar tools. While capturing, the viewer temporarily switches to orthographic "
                       "projection, flat even lighting and a plain background with no grid, sky or edges, "
                       "then puts everything back.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.layout_box = QComboBox()
        for key, label in SHEET_LAYOUTS:
            self.layout_box.addItem(label, key)
        self.bg_box = QComboBox()
        for key, label, _c in SHEET_BACKGROUNDS:
            self.bg_box.addItem(label, key)
        self.cell_box = QComboBox()
        for c in SHEET_CELLS:
            self.cell_box.addItem(f"{c} × {c} px per view", c)
        self.labels_cb = QCheckBox("Write the view names under each view (off is best for AI tools)")
        self.single_cb = QCheckBox("Also save each view as its own PNG")
        form.addRow("Layout", self.layout_box)
        form.addRow("Background", self.bg_box)
        form.addRow("Size", self.cell_box)
        form.addRow("", self.labels_cb)
        form.addRow("", self.single_cb)
        lay.addLayout(form)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#8a96a6;")
        lay.addWidget(self.note)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        ok = QPushButton("Render and save…")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        try:                                          # last choices
            self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(str(settings.value("sheet_layout", "ortho4")))))
            self.bg_box.setCurrentIndex(max(0, self.bg_box.findData(str(settings.value("sheet_bg", "white")))))
            self.cell_box.setCurrentIndex(max(0, self.cell_box.findData(int(settings.value("sheet_cell", 1024)))))
            self.labels_cb.setChecked(str(settings.value("sheet_labels", "false")).lower() in ("1", "true"))
            self.single_cb.setChecked(str(settings.value("sheet_single", "false")).lower() in ("1", "true"))
        except Exception:
            pass
        self.cell_box.currentIndexChanged.connect(self._note)
        self._note()

    def _note(self):
        c = int(self.cell_box.currentData())
        self.note.setText(f"The sheet will be {4 * c} × {c} px. Views are rendered from the live viewport, so a "
                          f"larger window gives a sharper result at big sizes.")

    def values(self) -> dict:
        return {"layout": self.layout_box.currentData(), "bg": self.bg_box.currentData(),
                "cell": int(self.cell_box.currentData()), "labels": self.labels_cb.isChecked(),
                "single": self.single_cb.isChecked()}


class UVLayoutView(QWidget):
    """The UV layout beside the 3D view: island edges over an optional texture, failing triangles filled.
    Wheel = zoom, drag = pan, double-click = fit. The drawing is cached and only redrawn after the view stops
    moving, so big meshes stay responsive."""
    MAX_EDGES = 300000
    MAX_FILL = 120000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 160)
        self.setMouseTracking(True)
        self.parts: list = []                 # dicts: uv, tris, flags (dict of bool arrays)
        self.active: list = []                # test keys currently on
        self.backdrop = None                  # QImage or None
        self.title = ""
        self.summary = ""
        self.legend = None                    # {"title", "stops": [(pos, rgb)], "labels": [(pos, text)]}
        self.scale = 300.0                    # pixels per UV unit
        self.off = [30.0, 330.0]              # screen position of UV (0, 0)
        self._drag = None
        self._pm = None
        self._base = (self.scale, (self.off[0], self.off[1]))
        self._fit_pending = True
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._redraw)

    # ----- data
    def set_data(self, parts: list, active: list, backdrop, title: str, summary: str, legend=None):
        self.parts, self.active, self.backdrop, self.title, self.summary = parts, list(active), backdrop, title, summary
        self.legend = legend
        self.fit()

    def _bounds(self):
        lo, hi = np.array([0.0, 0.0]), np.array([1.0, 1.0])
        for part in self.parts:
            uv = part["uv"]
            if len(uv):
                lo = np.minimum(lo, np.clip(uv.min(0), -8, 8))
                hi = np.maximum(hi, np.clip(uv.max(0), -8, 8))
        return lo, hi

    def fit(self):
        lo, hi = self._bounds()
        w, h = max(self.width(), 50), max(self.height(), 50)
        pad = 26.0
        sc = min((w - 2 * pad) / max(hi[0] - lo[0], 1e-6), (h - 2 * pad - 18) / max(hi[1] - lo[1], 1e-6))
        self.scale = max(sc, 1.0)
        self.off = [pad + (w - 2 * pad - (hi[0] - lo[0]) * self.scale) / 2 - lo[0] * self.scale,
                    h - pad - 18 - (h - 2 * pad - 18 - (hi[1] - lo[1]) * self.scale) / 2 + lo[1] * self.scale]
        self._fit_pending = False
        self._redraw()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit_pending or self._pm is None:
            self.fit()
        else:
            self._timer.start(80)

    # ----- interaction
    def wheelEvent(self, e):
        k = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        p = e.position()
        self.off[0] = p.x() - (p.x() - self.off[0]) * k
        self.off[1] = p.y() - (p.y() - self.off[1]) * k
        self.scale *= k
        self.update()
        self._timer.start(90)

    def mousePressEvent(self, e):
        if e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag = (e.position().x(), e.position().y(), self.off[0], self.off[1])

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            x0, y0, ox, oy = self._drag
            self.off = [ox + e.position().x() - x0, oy + e.position().y() - y0]
            self.update()
            self._timer.start(90)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.fit()

    # ----- drawing
    def _redraw(self):
        if self.width() < 4 or self.height() < 4:
            return
        pm = QPixmap(self.size())
        pm.fill(QColor(18, 21, 27))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        sc, ox, oy = self.scale, self.off[0], self.off[1]
        lo, hi = self._bounds()
        # texture tile and tile grid
        x0, y0, x1, y1 = ox, oy - sc, ox + sc, oy
        if self.backdrop is not None:
            p.setOpacity(0.55)
            p.drawImage(QRectF(x0, y0, sc, sc), self.backdrop)
            p.setOpacity(1.0)
        else:
            p.fillRect(QRectF(x0, y0, sc, sc), QColor(30, 35, 43))
        p.setPen(QPen(QColor(60, 70, 84), 1))
        for gx in range(int(math.floor(lo[0])), int(math.ceil(hi[0])) + 1):
            p.drawLine(QPointF(ox + gx * sc, oy - hi[1] * sc - sc), QPointF(ox + gx * sc, oy - lo[1] * sc + sc))
        for gy in range(int(math.floor(lo[1])), int(math.ceil(hi[1])) + 1):
            p.drawLine(QPointF(ox + lo[0] * sc - sc, oy - gy * sc), QPointF(ox + hi[0] * sc + sc, oy - gy * sc))
        p.setPen(QPen(QColor(120, 140, 165), 1.5))
        p.drawRect(QRectF(x0, y0, sc, sc))
        colors = {k: QColor(*c) for k, _l, _t, c in UV_TESTS}
        # density / stretch heat: every triangle filled with its colour (grouped into a few shades)
        for part in self.parts:
            heat = part.get("heat")
            if heat is None:
                continue
            n = len(heat)
            idx = np.arange(n)
            if n > self.MAX_FILL:
                idx = idx[np.linspace(0, n - 1, self.MAX_FILL).astype(int)]
            q = (heat[idx].astype(np.int32) // 24)
            code = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
            for c in np.unique(code):
                sel = idx[code == c]
                path = QPainterPath()
                pts = part["uv"][part["tris"][sel]]
                sx, sy = (ox + pts[..., 0] * sc).tolist(), (oy - pts[..., 1] * sc).tolist()
                for a_x, a_y in zip(sx, sy):
                    path.moveTo(a_x[0], a_y[0])
                    path.lineTo(a_x[1], a_y[1])
                    path.lineTo(a_x[2], a_y[2])
                    path.closeSubpath()
                rgb = heat[sel].mean(0)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), 190))
                p.drawPath(path)
        # failing triangles, filled
        for part in self.parts:
            uv, tris = part["uv"], part["tris"]
            for key in self.active:
                flag = part["flags"].get(key)
                if flag is None:
                    continue
                idx = np.nonzero(flag)[0]
                if len(idx) > self.MAX_FILL:
                    idx = idx[np.linspace(0, len(idx) - 1, self.MAX_FILL).astype(int)]
                if not len(idx):
                    continue
                path = QPainterPath()
                pts = uv[tris[idx]]                                 # (n, 3, 2)
                sx = ox + pts[..., 0] * sc
                sy = oy - pts[..., 1] * sc
                for a_x, a_y in zip(sx.tolist(), sy.tolist()):
                    path.moveTo(a_x[0], a_y[0])
                    path.lineTo(a_x[1], a_y[1])
                    path.lineTo(a_x[2], a_y[2])
                    path.closeSubpath()
                col = QColor(colors[key])
                col.setAlpha(150)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPath(path)
        # all edges
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(120, 165, 215, 170), 1))
        for part in self.parts:
            e = part.get("edges")
            if e is None:
                t = part["tris"]
                e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
                e.sort(1)
                e = np.unique(e, axis=0)
                part["edges"] = e
            if len(e) > self.MAX_EDGES:
                e = e[np.linspace(0, len(e) - 1, self.MAX_EDGES).astype(int)]
            a, b = part["uv"][e[:, 0]], part["uv"][e[:, 1]]
            arr = np.stack([ox + a[:, 0] * sc, oy - a[:, 1] * sc, ox + b[:, 0] * sc, oy - b[:, 1] * sc], 1)
            p.drawLines([QLineF(x0_, y0_, x1_, y1_) for x0_, y0_, x1_, y1_ in arr.tolist()])
        if self.legend and self.parts:
            lg = self.legend
            bw, bx, by = 150, self.width() - 166, 24
            grad = QLinearGradient(bx, 0, bx + bw, 0)
            for pos, rgb in lg["stops"]:
                grad.setColorAt(pos, QColor(*rgb))
            p.setPen(QPen(QColor(10, 12, 16), 1))
            p.setBrush(grad)
            p.drawRect(QRectF(bx, by, bw, 10))
            p.setPen(QColor(190, 198, 210))
            p.drawText(QPointF(bx, by - 5), lg["title"])
            for pos, text in lg["labels"]:
                tw = p.fontMetrics().horizontalAdvance(text)
                p.drawText(QPointF(min(max(bx + pos * bw - tw / 2, 4), self.width() - tw - 4), by + 24), text)
        p.setPen(QColor(150, 160, 175))
        if not self.parts:
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.summary or "No UV data")
        else:
            p.drawText(QPointF(10, 16), self.title)
            p.drawText(QPointF(10, self.height() - 8), self.summary)
        p.end()
        self._pm = pm
        self._base = (self.scale, (self.off[0], self.off[1]))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        if self._pm is None:
            p.fillRect(self.rect(), QColor(18, 21, 27))
            return
        s0, (o0x, o0y) = self._base
        k = self.scale / s0
        if abs(k - 1.0) < 1e-6 and abs(self.off[0] - o0x) < 0.5 and abs(self.off[1] - o0y) < 0.5:
            p.drawPixmap(0, 0, self._pm)
        else:                                  # moving: reuse the last drawing until the timer redraws
            p.fillRect(self.rect(), QColor(18, 21, 27))
            p.translate(self.off[0], self.off[1])
            p.scale(k, k)
            p.translate(-o0x, -o0y)
            p.drawPixmap(0, 0, self._pm)


class Viewer(QWidget):
    closed = Signal()
    step = Signal(int)                    # -1 previous model, +1 next model
    message = Signal(str)                 # short status text for the main window
    orientation_changed = Signal(str)     # path whose up-axis changed
    about_requested = Signal()            # open the About dialog
    panel_requested = Signal(str)         # show/raise a docked panel: environment, matcap, scene, materials
    uv_changed = Signal()                 # UV analysis or UV view settings changed
    mesh_changed = Signal()               # mesh analysis or mesh test selection changed
    analysis_progress = Signal(str, str)  # ("uv" | "mesh", text) while an analysis runs in the background
    measure_changed = Signal()            # measurement results, units, points or section changed
    lod_changed = Signal()                # LOD generation progress, results or shown level changed

    def __init__(self):
        super().__init__()
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.mode = "surface"
        self.actors: list = []
        self.matcap_idx = 0
        self._editor = None
        self.info_on = str(self.settings.value("info_on", "true")).lower() in ("1", "true")
        self._export_task = None
        try:                                      # environment settings from the last session
            self.env = clean_env(json.loads(str(self.settings.value("environment", ""))))
        except Exception:
            self.env = copy.deepcopy(ENV_DEFAULTS)
        self._env_panel = None
        self._env_code = ""
        self._env_view_locked = False
        self._env_lights = None
        self._env_lights_added = False
        self._pano, self._pano_path, self._sky_key = None, "", None
        self._sky_tex = self._skybox = None
        self._sky_added = False
        self._blob = self._blob_src = None
        self._blob_added = False
        self._bg_from_env = False
        self._light_drag = None
        self._preset_idx = -1
        self.fov = float(_setting_int(self.settings, "fov", 30))
        self.grid_on = str(self.settings.value("grid_on", "false")).lower() in ("1", "true")
        self.edges_on = str(self.settings.value("edges_on", "false")).lower() in ("1", "true")
        self.shot_scale = _setting_int(self.settings, "shot_scale", 2)
        self.shot_transparent = str(self.settings.value("shot_transparent", "false")).lower() in ("1", "true")
        self._grid = self._grid_src = None
        self._grid_added = False
        self._bookmarks = {}
        self._scene_panel = None
        self.turntable = str(self.settings.value("turntable", "true")).lower() in ("1", "true")
        self._tt_drag = None
        self.split_on = False                      # MatCap | normal shading comparison
        self.split_style = "vertical"
        self.split_pos = 0.5
        self.split_swap = False
        self._split_drag = False
        self._split_props = None
        self._split_cursor = False
        self._split_timer = QTimer(self)
        self._split_timer.setSingleShot(True)
        self._split_timer.timeout.connect(self._split_rebake)
        self._split_resize_timer = QTimer(self)
        self._split_resize_timer.setSingleShot(True)
        self._split_resize_timer.timeout.connect(self._split_after_resize)
        self._materials_panel = None
        keys = [k for k, _l, _f in UNITS]
        u = str(self.settings.value("measure_src", "m"))
        self.unit_src = u if u in keys else "m"
        u = str(self.settings.value("measure_disp", self.unit_src))
        self.unit_disp = u if u in keys else self.unit_src
        self._measure_result = None                # last "Calculate" result, in model units
        self._lod_sets = None                      # {level %: [polydata or None per part]} once generated
        self._lod_orig_counts = (0, 0)
        self._lod_info: dict = {}
        self._lod_level = 0                        # 0 = original geometry
        self._lod_task = None
        self._lod_token = 0
        self.lod_status = ""
        self.measure_on = False                    # click-to-measure mode
        self._meas_pts: list = []                  # picked world points (A, B, C)
        self._meas_props: list = []
        self._meas_press = None
        self.section_on = False
        self.section_axis = 2
        self.section_pos = 0.5
        self.section_flip = False
        self._sec_plane = None
        self._sec_items: list = []                 # (actor, transform, cut actor)
        self.uv_on = False                         # UV layout shown beside the 3D view
        self.uv_tests: set = set()                 # active UV diagnostics (keys of UV_TESTS)
        self.mesh_tests: set = set()               # active mesh diagnostics (keys of MESH_TESTS)
        self._mesh_data = None                     # per-part mesh analysis; None until asked for
        self._mesh_task, self._mesh_token, self.mesh_status = None, 0, ""     # background integrity analysis
        self._uv_task, self._uv_token, self.uv_status = None, 0, ""           # background UV analysis
        self._ao_cav, self._ao_task, self._ao_token, self._ao_on = None, None, 0, False   # Fake AO
        self.uv_part = -1                          # -1 = all parts
        self.uv_backdrop_on = True
        self.uv_heat = "off"                       # off | density | stretch
        self.uv_th = dict(UV_HEAT_DEFAULTS)
        self._uv_ref = 0.0                         # reference texel density (area-weighted median)
        self._uv_data: list = []
        self._uv_ready = False                     # UV analysis runs only on request
        self._uv_saved: dict = {}
        self._uv_tex_cache: dict = {}
        self._outline = self._outline_src = None
        self._outline_added = False
        try:                                      # last custom MatCap from the previous session
            self.custom = preset_to_spec(json.loads(str(self.settings.value("custom_matcap", ""))))
            self._custom_parts = custom_matcap_parts(self.custom)
        except Exception:
            self.custom, self._custom_parts = None, ("", "", None)
        self.path = ""
        self.up_axis = "Y"
        self.bg_idx = _setting_int(self.settings, "bg_idx", 0)
        self.axes_on = str(self.settings.value("axes_on", "true")).lower() in ("1", "true")
        self.transparent = str(self.settings.value("transparency_on", "false")).lower() in ("1", "true")
        self.orbit_speed_idx = min(_setting_int(self.settings, "orbit_speed", 1), len(ORBIT_SPEEDS) - 1)
        self._dragging = False
        self._axes_widget = None
        self._axes_actor = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # The 3D view lives in a stage (with its HUD and messages) inside a splitter, so the UV layout
        # can sit beside it.
        self.view_split = QSplitter(Qt.Horizontal)
        self.view_split.setChildrenCollapsible(False)
        self.view_split.setHandleWidth(5)
        lay.addWidget(self.view_split)
        self.stage = QWidget()
        sl = QVBoxLayout(self.stage)
        sl.setContentsMargins(0, 0, 0, 0)
        self.stage.installEventFilter(self)
        self.vtk_widget = QVTKRenderWindowInteractor(self.stage)
        self.vtk_widget.installEventFilter(self)       # Shift + right-drag rotates the lighting
        sl.addWidget(self.vtk_widget)
        self.view_split.addWidget(self.stage)
        self.uv_view = UVLayoutView()
        self.uv_view.hide()
        self.view_split.addWidget(self.uv_view)
        self.view_split.setStretchFactor(0, 3)
        self.view_split.setStretchFactor(1, 2)

        self.renderer = vtkRenderer()
        self.rw = self.vtk_widget.GetRenderWindow()
        self.rw.AddRenderer(self.renderer)
        self.rw.SetMultiSamples(4)
        self.iren = self.rw.GetInteractor()
        # Trackball: LMB orbit, RMB zoom, MMB pan
        self.style = vtkInteractorStyleTrackballCamera()
        self.style.AddObserver("StartInteractionEvent", lambda *a: setattr(self, "_dragging", True))
        self.style.AddObserver("EndInteractionEvent", lambda *a: setattr(self, "_dragging", False))
        self.iren.SetInteractorStyle(self.style)
        self.iren.Initialize()
        self.renderer.GetActiveCamera().SetViewAngle(self.fov)

        self._orbit_timer = QTimer(self)
        self._orbit_timer.timeout.connect(self._orbit_tick)

        # ----- floating HUD (native child so it sits above the GL surface)
        self.hud = QFrame(self.stage)
        self.hud.setAttribute(Qt.WA_NativeWindow, True)
        self.hud.setObjectName("hud")
        h = QHBoxLayout(self.hud)
        h.setContentsMargins(8, 4, 6, 4)
        h.setSpacing(4)
        h.addWidget(self._btn("‹", "Previous model (←)", lambda: self.step.emit(-1)))
        h.addWidget(self._btn("›", "Next model (→)", lambda: self.step.emit(1)))
        for text, tip, fn in (("Wire", "Wireframe (W)", lambda: self.set_mode("wire")),
                              ("Points", "Point cloud (P)", lambda: self.set_mode("points")),
                              ("Shaded", "Shaded surface (S)", lambda: self.set_mode("surface")),
                              ("MatCap", "Cycle MatCaps (M)", lambda: self.cycle_matcap())):
            b = self._btn(text, tip, fn)
            if text == "MatCap":
                self.matcap_btn = b
            h.addWidget(b)
        self.orbit_btn = self._btn("Orbit", "Auto-orbit (O)", None, checkable=True)
        self.orbit_btn.toggled.connect(self.set_orbit)
        h.addWidget(self.orbit_btn)
        h.addWidget(self._btn("Reset", "Reset camera (R)", self.reset_camera))
        h.addWidget(self._build_view_button())
        x = self._btn("✕", "Close (Esc)", self.closed.emit)
        x.setObjectName("hudClose")
        h.addWidget(x)

        self.info_panel = InfoPanel(self.stage)
        self.info_panel.hide()
        self.overlay = Overlay(self.stage)
        self.set_background(self.bg_idx, announce=False)

    # ----- HUD construction -------------------------------------------------
    def _btn(self, text, tip, fn, checkable=False) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if fn is not None:
            b.clicked.connect(fn)
        return b

    def _build_view_button(self) -> QToolButton:
        menu = QMenu(self)
        bg = menu.addMenu("Background\tB")
        for i, (name, _c1, _c2) in enumerate(BACKGROUNDS):
            bg.addAction(name, lambda _=False, i=i: self.set_background(i))
        bg.addSeparator()
        bg.addAction("Custom colour…", lambda _=False: self.pick_background())

        self.act_axes = QAction("Axes gizmo\tA", menu, checkable=True)
        self.act_axes.setChecked(self.axes_on)
        self.act_axes.toggled.connect(self.set_axes)
        menu.addAction(self.act_axes)
        self.act_ortho = QAction("Orthographic\tC", menu, checkable=True)
        self.act_ortho.toggled.connect(self.set_ortho)
        menu.addAction(self.act_ortho)
        self.act_upz = QAction("Z-up model\tU", menu, checkable=True)
        self.act_upz.toggled.connect(lambda _=False: self.toggle_up_axis())
        menu.addAction(self.act_upz)
        self.act_transp = QAction("Respect transparency\tT", menu, checkable=True)
        self.act_transp.setChecked(self.transparent)
        self.act_transp.toggled.connect(self.set_transparency)
        menu.addAction(self.act_transp)

        views = menu.addMenu("Standard views")
        for key, label in VIEW_LABELS:
            views.addAction(label, lambda _=False, k=key: self.set_view(k))

        speed = menu.addMenu("Orbit speed")
        group = QActionGroup(speed)
        for i, (name, _dps) in enumerate(ORBIT_SPEEDS):
            a = QAction(name, speed, checkable=True)
            a.setChecked(i == self.orbit_speed_idx)
            a.triggered.connect(lambda _=False, i=i: self.set_orbit_speed(i))
            group.addAction(a)
            speed.addAction(a)

        self.act_env = QAction("Environment (sky, light, shadow)\tL", menu, checkable=True)
        self.act_env.setChecked(bool(self.env["enabled"]))
        self.act_env.toggled.connect(self.set_environment_enabled)
        menu.addAction(self.act_env)
        presets = menu.addMenu("Lighting preset\tCtrl+L")
        for preset_name in ENV_BUILTIN_PRESETS:
            presets.addAction(preset_name, lambda _=False, n=preset_name: self.apply_builtin_preset(n))
        self.act_grid = QAction("Ground grid\tG", menu, checkable=True)
        self.act_grid.setChecked(self.grid_on)
        self.act_grid.toggled.connect(self.set_grid)
        menu.addAction(self.act_grid)
        self.act_edges = QAction("Edges over shaded\tShift+W", menu, checkable=True)
        self.act_edges.setChecked(self.edges_on)
        self.act_edges.toggled.connect(self.set_edges)
        menu.addAction(self.act_edges)
        self.act_turntable = QAction("Lock horizon (turntable)\tH", menu, checkable=True)
        self.act_turntable.setChecked(self.turntable)
        self.act_turntable.toggled.connect(self.set_turntable)
        menu.addAction(self.act_turntable)
        self.act_uv = QAction("UV layout beside the model\tShift+U", menu, checkable=True)
        self.act_uv.toggled.connect(self.set_uv_view)
        menu.addAction(self.act_uv)
        self.act_split = QAction("Split compare: MatCap | normal\tD", menu, checkable=True)
        self.act_split.toggled.connect(self.set_split)
        menu.addAction(self.act_split)
        sm = menu.addMenu("Split style\tShift+D")
        self._split_style_acts = {}
        grp = QActionGroup(sm)
        for key, label in (("vertical", "Vertical (left | right)"), ("horizontal", "Horizontal (top / bottom)"),
                           ("diagonal", "Diagonal")):
            act = QAction(label, sm, checkable=True)
            act.setChecked(key == self.split_style)
            act.triggered.connect(lambda _=False, k=key: self.set_split_style(k))
            grp.addAction(act)
            sm.addAction(act)
            self._split_style_acts[key] = act
        sm.addSeparator()
        sm.addAction("Swap sides", lambda _=False: self.swap_split_sides())
        sm.addAction("Reset divider to centre", lambda _=False: self.reset_split())
        chan = menu.addMenu("Material view\tV")
        for key, label in VIEW_CHANNELS:
            chan.addAction(label, lambda _=False, k=key: self.set_view_channel(k))
        self.act_info = QAction("Model info\tI", menu, checkable=True)
        self.act_info.setChecked(self.info_on)
        self.act_info.toggled.connect(self.set_info_visible)
        menu.addAction(self.act_info)
        menu.addAction("Export / convert…\tCtrl+E", lambda _=False: self.open_export_dialog())
        menu.addAction("About " + ABOUT["app_name"] + "\tF1", lambda _=False: self.about_requested.emit())
        menu.addSeparator()
        menu.addAction("Reference sheet for AI 3D tools…\tShift+F12", lambda _=False: self.open_reference_sheet_dialog())
        menu.addAction("Save screenshot…\tF12", lambda _=False: self.save_screenshot())
        menu.addAction("Copy screenshot\tCtrl+C", lambda _=False: self.copy_screenshot())

        b = QToolButton()
        b.setText("Main ▾")
        b.setToolTip("Main menu")
        b.setMenu(menu)
        b.setPopupMode(QToolButton.InstantPopup)
        return b

    # ----- layout -----------------------------------------------------------
    def _place_hud(self):
        self.hud.adjustSize()
        self.hud.move(max(8, self.stage.width() - self.hud.width() - 12), 12)
        self.hud.raise_()
        self._place_info()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_hud()
        if self.overlay.isVisible():
            self.overlay.reposition()
        if self._split_visible():
            self._split_resize_timer.start(150)

    # ----- scene state ------------------------------------------------------
    def clear_scene(self):
        self._lod_reset()
        self._measure_clear(render=False)
        self._section_clear()
        self._measure_result = None
        self._uv_stop()
        self._mesh_stop()
        self._uv_saved, self._uv_data = {}, []
        self._uv_ready = False
        self.uv_tests, self.uv_heat = set(), "off"   # settings belong to the previous model
        self._mesh_data = None
        self.mesh_tests = set()                    # tests belong to the previous model; run them again
        self._ao_stop()
        self._uv_tex_cache = {}
        for a in self.actors:
            self.renderer.RemoveActor(a)
        self.actors = []
        self.overlay.hide()
        self._remove_shadow()
        self._remove_ground()
        self._remove_outline()
        self._sync_env_lights()
        if getattr(self, "info_panel", None) is not None:
            self.info_panel.hide()
        self._sync_axes()
        self._split_sync()
        self.rw.Render()

    def show_loading(self, name: str):
        self.clear_scene()
        self.overlay.show_text(f"Loading {name} …", error=False)

    def show_error(self, msg: str):
        self.overlay.show_text("⚠  Could not open asset\n\n" + msg, error=True)

    def show_model(self, actors: list, name: str, path: str = ""):
        self.clear_scene()
        self.path = path
        self.up_axis = ORIENT.get(path) if path else "Y"
        self.act_upz.blockSignals(True)
        self.act_upz.setChecked(self.up_axis == "Z")
        self.act_upz.blockSignals(False)
        for a in actors:
            a.GetProperty().SetPointSize(2.5)
            self.renderer.AddActor(a)
        self.actors = actors
        self._sync_transp_action(self.transparent)
        self._apply_transparency()
        self.set_mode("surface")
        self.set_view("front")
        self._bookmarks = {}                       # saved views belong to the previous model
        for a in actors:
            a._orig_um = self._user_matrix_list(a)  # so "Reset position" can undo moves
        self._apply_edges()
        self._env_refresh()
        self._sync_axes()
        self._place_hud()
        self._update_info()
        self.uv_part = -1
        self.uv_refresh()
        if self.section_on:
            self._section_apply()
        self.measure_changed.emit()
        if self._materials_panel is not None and self._materials_panel.isVisible():
            self._materials_panel.refresh()

    # ----- shading modes ----------------------------------------------------
    def cycle_matcap(self):
        """M: Frosted Glass -> Goosh -> RealSkin -> Glossy -> normal shading."""
        if not self.actors:
            return
        nxt = 0 if self.mode != "matcap" else self.matcap_idx + 1
        if nxt >= len(self._matcaps()):
            self.set_mode("surface")
        else:
            self.matcap_idx = nxt
            self.set_mode("matcap", force=True)

    def set_mode(self, mode: str, force: bool = False):
        if not self.actors:
            return
        if mode == self.mode and mode != "surface" and not force:
            mode = "surface"  # pressing W/P again toggles back to shaded
        entries = self._matcaps()
        self.matcap_idx = min(self.matcap_idx, len(entries) - 1)
        self._ao_mode = mode                      # the mode being installed (self.mode still has the old one)
        log_pos = _log_size()
        for a in self.actors:
            prop = a.GetProperty()
            try:                                  # always start from stock VTK shading
                a.GetShaderProperty().ClearAllFragmentShaderReplacements()
            except Exception:
                pass
            self._ao_detach(a)
            if mode == "wire":
                prop.SetRepresentationToWireframe()
            elif mode == "points":
                prop.SetRepresentationToPoints()
            else:
                prop.SetRepresentationToSurface()
        if mode == "matcap":
            try:
                self._install_matcap(entries[self.matcap_idx][1], entries[self.matcap_idx][2])
            except Exception:                     # VTK < 9.0 has no per-actor shader property
                self._clear_replacements()
                mode = "surface"
        elif mode in VIEW_SHADERS:
            try:
                self._install_view_shader(mode)
            except Exception:
                self._clear_replacements()
                mode = "surface"
        self._env_code = ""
        self._ao_mode = mode
        if mode == "surface" and self._env_code_all():
            try:
                self._install_env()
            except Exception:
                self._clear_replacements()
                self._env_code = ""
        self._sync_env_lights(mode)
        self._apply_edges(mode)
        self.mode = mode
        self._ao_mode = None
        self._split_sync()
        label = entries[self.matcap_idx][0]
        self.matcap_btn.setText((label if len(label) <= 16 else label[:15] + "…")
                                if mode == "matcap" else "MatCap")
        self._place_hud()
        self.rw.Render()
        if mode == "surface" and self._env_code and _shader_error_since(log_pos):
            self._env_failed()
        if mode in VIEW_SHADERS and _shader_error_since(log_pos):
            self._view_failed()
        if mode == "matcap" and _shader_error_since(log_pos):
            alt = entries[self.matcap_idx][3]
            if alt is not None:                   # full image table rejected: try the lite one
                after = _log_size()
                try:
                    self._install_matcap(*alt)
                    self.rw.Render()
                except Exception:
                    pass
                if not _shader_error_since(after):
                    self.message.emit("Your GPU rejected the full image MatCap, so a lower-detail "
                                      "version is being used")
                    return
            self._matcap_failed()

    def _matcaps(self) -> list:
        """(name, impl, decl, fallback) for every MatCap in the M cycle."""
        entries = [(n, code, "", None) for n, code in MATCAPS]
        if self.custom is not None:
            entries.append((self.custom.get("name") or "Custom", *self._custom_parts))
        return entries

    def _clear_replacements(self):
        for a in self.actors:
            try:
                a.GetShaderProperty().ClearAllFragmentShaderReplacements()
            except Exception:
                pass

    def _install_matcap(self, impl: str, decl: str):
        if self.split_on:
            impl = self._wrap_split(impl)
        for a in self.actors:
            sp = a.GetShaderProperty()
            sp.ClearAllFragmentShaderReplacements()
            if decl:                              # global declarations (e.g. the image table)
                sp.AddFragmentShaderReplacement(
                    "//VTK::Light::Dec", True, "//VTK::Light::Dec\n" + decl, False)
            sp.AddFragmentShaderReplacement("//VTK::Light::Impl", True, impl, False)

    def _matcap_failed(self):
        """The GPU/driver rejected a MatCap shader: restore normal shading instead of a blank view."""
        for a in self.actors:
            try:
                a.GetShaderProperty().ClearAllFragmentShaderReplacements()
            except Exception:
                pass
            a.GetProperty().SetRepresentationToSurface()
        self.mode = "surface"
        self.matcap_btn.setText("MatCap")
        self._split_sync()
        self.rw.Render()
        self.message.emit("That MatCap shader failed to compile on this GPU, so normal shading was "
                          "restored (details are in the VTK log in your temp folder)")

    def set_custom_matcap(self, spec: dict):
        """Called by the editor: store the custom MatCap and show it."""
        spec = copy.deepcopy(spec)
        try:
            parts = custom_matcap_parts(spec)
        except Exception as e:
            self.message.emit(f"Could not build that MatCap: {e}")
            return
        self.custom, self._custom_parts = spec, parts
        try:
            self.settings.setValue("custom_matcap", json.dumps(spec_to_preset(spec)))
        except Exception:
            pass
        if self.actors:
            self.matcap_idx = len(MATCAPS)
            self.set_mode("matcap", force=True)

    def matcap_editor(self):
        if self._editor is None:
            self._editor = MatCapEditor(None, self.custom if self.custom is not None else default_spec())
            self._editor.changed.connect(self.set_custom_matcap)
        return self._editor

    def open_matcap_editor(self):
        if not self.actors and self.custom is None:
            self.message.emit("Open a model first, then edit its MatCap")
        spec = self.custom if self.custom is not None else default_spec()
        self.matcap_editor().set_spec(spec)
        self.panel_requested.emit("matcap")
        if self.custom is None:
            self.set_custom_matcap(spec)

    # ----- split compare: MatCap on one side, normal shading on the other ----------------
    # One render only. The fragment shader chooses the look per pixel from its screen position
    # (gl_FragCoord), so there is no second pass. The divider position is baked into the shader as
    # a literal (this app avoids custom uniforms), so while the divider is dragged the shader is
    # re-baked on a short throttle; the divider line itself is a 2D overlay and follows instantly.
    def _split_visible(self) -> bool:
        return bool(self.split_on and self.actors and self.mode == "matcap")

    def _view_px(self):
        try:
            w, h = self.rw.GetSize()
        except Exception:
            w = h = 0
        if w < 2 or h < 2:
            dpr = self.vtk_widget.devicePixelRatioF()
            w, h = self.vtk_widget.width() * dpr, self.vtk_widget.height() * dpr
        return max(int(w), 2), max(int(h), 2)

    def _split_geom(self, w: int, h: int):
        """(line start, line end, handle centre, GLSL condition that is true on the MatCap side)."""
        pos = min(1.0, max(0.0, self.split_pos))
        if self.split_style == "horizontal":
            cy = (1.0 - pos) * h
            p0, p1, hp, cond = (0.0, cy), (float(w), cy), (w / 2.0, cy), f"gl_FragCoord.y > {cy:.1f}"
        elif self.split_style == "diagonal":
            cx, cy = pos * w, h / 2.0
            s = cx + cy
            p0, p1, hp, cond = (s - 2.0 * h, 2.0 * h), (s + h, -float(h)), (cx, cy), \
                f"gl_FragCoord.x + gl_FragCoord.y < {s:.1f}"
        else:
            cx = pos * w
            p0, p1, hp, cond = (cx, 0.0), (cx, float(h)), (cx, h / 2.0), f"gl_FragCoord.x < {cx:.1f}"
        if self.split_swap:
            cond = f"!({cond})"
        return p0, p1, hp, cond

    def _wrap_split(self, impl: str) -> str:
        """Matcap on one side of the divider; the other side keeps the normal look (the
        environment lighting if it is on, otherwise stock VTK shading)."""
        w, h = self._view_px()
        cond = self._split_geom(w, h)[3]
        base = self._current_env_code() if self._env_on("lighting") else "//VTK::Light::Impl\n"
        return f"{base}\n  if ({cond}) {{\n{impl}\n  }}\n"

    def _split_build(self):
        if self._split_props is not None or vtkActor2D is None:
            return
        props = []
        for layer, colour, width, opacity in ((0, (0, 0, 0), 5, 0.45), (1, (1, 1, 1), 2, 1.0),
                                              (2, (0, 0, 0), 0, 0.85), (3, (1, 1, 1), 0, 1.0)):
            pd = vtkPolyData()
            pd.SetPoints(vtkPoints())
            m = vtkPolyDataMapper2D()
            m.SetInputData(pd)
            a = vtkActor2D()
            a.SetMapper(m)
            a.SetLayerNumber(layer)
            a.GetProperty().SetColor(*colour)
            a.GetProperty().SetOpacity(opacity)
            if width:
                a.GetProperty().SetLineWidth(width)
            a.SetVisibility(False)
            self.renderer.AddViewProp(a)
            props.append((pd, a))
        self._split_props = props

    def _split_fill(self):
        if self._split_props is None:
            return
        w, h = self._view_px()
        scale = w / max(self.vtk_widget.width(), 1)
        p0, p1, hp, _c = self._split_geom(w, h)

        def disc(radius):
            pts, cells = vtkPoints(), vtkCellArray()
            n = 28
            cells.InsertNextCell(n)
            for i in range(n):
                ang = 2.0 * math.pi * i / n
                cells.InsertCellPoint(pts.InsertNextPoint(hp[0] + radius * math.cos(ang),
                                                          hp[1] + radius * math.sin(ang), 0.0))
            return pts, cells

        for idx in (0, 1):                                    # shadow + line
            pd = self._split_props[idx][0]
            pts, cells = vtkPoints(), vtkCellArray()
            cells.InsertNextCell(2)
            cells.InsertCellPoint(pts.InsertNextPoint(p0[0], p0[1], 0.0))
            cells.InsertCellPoint(pts.InsertNextPoint(p1[0], p1[1], 0.0))
            pd.SetPoints(pts)
            pd.SetLines(cells)
            pd.Modified()
        for idx, radius in ((2, 13.0 * scale), (3, 10.0 * scale)):   # handle: dark ring, white disc
            pd = self._split_props[idx][0]
            pts, cells = disc(radius)
            pd.SetPoints(pts)
            pd.SetPolys(cells)
            pd.Modified()

    def _split_sync(self):
        """Show or hide the divider and bring its geometry up to date."""
        vis = self._split_visible()
        if vis:
            self._split_build()
        if self._split_props is not None:
            for _pd, a in self._split_props:
                a.SetVisibility(bool(vis))
            if vis:
                self._split_fill()
        if not vis and self._split_cursor:
            self.vtk_widget.unsetCursor()
            self._split_cursor = False

    def _split_request_rebake(self):
        if not self._split_visible():
            return
        heavy = False
        try:
            heavy = self._matcaps()[self.matcap_idx][3] is not None      # image MatCaps compile slower
        except Exception:
            pass
        if not self._split_timer.isActive():
            self._split_timer.start(260 if heavy else 70)

    def _split_rebake(self):
        if self._split_visible():
            self.set_mode("matcap", force=True)

    def _split_after_resize(self):
        if self._split_visible():
            self._split_fill()
            self._split_rebake()

    def set_split(self, on: bool):
        if on and not self.actors:
            self.message.emit("Open a model first")
            self.act_split.blockSignals(True)
            self.act_split.setChecked(False)
            self.act_split.blockSignals(False)
            return
        had_ao = self._ao_wanted()
        self.split_on = bool(on)
        if self.actors:
            self._split_timer.stop()
            if self.split_on or self.mode == "matcap":
                self.set_mode("matcap", force=True)   # re-bakes (and switches to MatCap when turning on)
        if on and had_ao:
            self.message.emit("Split compare on (Fake AO is paused while it is on): drag the line, "
                              "double-click it to centre, D hides it")
            return
        self.message.emit("Split compare on: drag the line, double-click it to centre, D hides it"
                          if on else "Split compare off")

    def toggle_split(self):
        self.act_split.toggle()

    def set_split_style(self, style: str):
        if style not in ("vertical", "horizontal", "diagonal"):
            return
        self.split_style = style
        self._split_style_acts[style].setChecked(True)
        if self.split_on:
            self._split_sync()
            self._split_rebake()
        else:
            self.act_split.setChecked(True)            # choosing a style implies you want to see it

    def cycle_split_style(self):
        order = ["vertical", "horizontal", "diagonal"]
        self.set_split_style(order[(order.index(self.split_style) + 1) % 3])

    def swap_split_sides(self):
        self.split_swap = not self.split_swap
        if self._split_visible():
            self._split_rebake()

    def reset_split(self):
        self.split_pos = 0.5
        if self._split_visible():
            self._split_fill()
            self.rw.Render()
            self._split_rebake()

    def _split_hit(self, dx: float, dy: float, w: int, h: int, scale: float) -> bool:
        p0, p1, hp, _c = self._split_geom(w, h)
        if math.hypot(dx - hp[0], dy - hp[1]) < 16.0 * scale:
            return True
        reach = 8.0 * scale
        if self.split_style == "horizontal":
            return abs(dy - p0[1]) < reach
        if self.split_style == "diagonal":
            return abs(dx + dy - (p0[0] + p0[1])) / 1.4142 < reach
        return abs(dx - p0[0]) < reach

    def _split_move_to(self, dx: float, dy: float, w: int, h: int):
        if self.split_style == "horizontal":
            pos = 1.0 - dy / h
        elif self.split_style == "diagonal":
            pos = (dx + dy - h / 2.0) / w
        else:
            pos = dx / w
        self.split_pos = min(1.0, max(0.0, pos))
        self._split_fill()
        self.rw.Render()
        self._split_request_rebake()

    def _split_event(self, ev, t) -> bool:
        """Mouse handling for the divider. Only the visible line / handle is grabbed, so normal
        orbit, pan and zoom elsewhere in the viewport are untouched."""
        w, h = self._view_px()
        scale = w / max(self.vtk_widget.width(), 1)
        pos = ev.position()
        dx, dy = pos.x() * scale, h - pos.y() * scale
        if self._split_drag:
            if t == QEvent.MouseMove:
                self._split_move_to(dx, dy, w, h)
            elif t == QEvent.MouseButtonRelease:
                self._split_drag = False
                self._split_timer.stop()
                self._split_rebake()
            return True
        near = self._split_hit(dx, dy, w, h, scale)
        if t == QEvent.MouseMove:
            if ev.buttons() == Qt.NoButton:
                if near != self._split_cursor:
                    self._split_cursor = near
                    if near:
                        shape = {"horizontal": Qt.SizeVerCursor, "diagonal": Qt.SizeAllCursor}.get(
                            self.split_style, Qt.SizeHorCursor)
                        self.vtk_widget.setCursor(shape)
                    else:
                        self.vtk_widget.unsetCursor()
            return False
        if near and ev.button() == Qt.LeftButton:
            if t == QEvent.MouseButtonPress:
                self._split_drag = True
                return True
            if t == QEvent.MouseButtonDblClick:
                self.reset_split()
                return True
        return False

    # ----- camera -----------------------------------------------------------
    def _axes_vectors(self):
        if self.up_axis == "Z":
            u, f, r = (0, 0, 1), (0, -1, 0), (1, 0, 0)
        else:
            u, f, r = (0, 1, 0), (0, 0, 1), (1, 0, 0)
        return np.array(u, float), np.array(f, float), np.array(r, float)

    def set_view(self, name: str):
        """Front/back/left/right/top/bottom/iso relative to the model's up axis."""
        if not self.actors:
            return
        u, f, r = self._axes_vectors()
        views = {"front": (f, u), "back": (-f, u), "right": (r, u), "left": (-r, u),
                 "top": (u, -f), "bottom": (-u, f), "iso": (f + r + u, u)}
        d, up = views.get(name, views["front"])
        d = d / np.linalg.norm(d)
        self.renderer.ResetCamera()                      # recentre on the model
        cam = self.renderer.GetActiveCamera()
        fp = np.array(cam.GetFocalPoint())
        dist = cam.GetDistance()
        cam.SetPosition(*(fp + d * dist))
        cam.SetViewUp(*up)
        self.renderer.ResetCamera()
        cam.Zoom(1.05)
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    def reset_camera(self):
        self.set_view("front")

    def set_ortho(self, on: bool):
        cam = self.renderer.GetActiveCamera()
        cam.SetParallelProjection(bool(on))
        if on:
            cam.SetParallelScale(cam.GetDistance() * math.tan(math.radians(cam.GetViewAngle() / 2)))
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()
        self.message.emit("Orthographic view" if on else "Perspective view")

    def toggle_up_axis(self):
        """U: treat the model as Z-up (CAD/Blender) or Y-up; remembered per file."""
        if not self.actors:
            return
        self.up_axis = "Y" if self.up_axis == "Z" else "Z"
        self.act_upz.blockSignals(True)
        self.act_upz.setChecked(self.up_axis == "Z")
        self.act_upz.blockSignals(False)
        if self.path:
            ORIENT.set(self.path, self.up_axis)
            self.orientation_changed.emit(self.path)
        self.set_view("front")
        self._env_refresh()
        self._update_info()
        self.message.emit(f"{self.up_axis}-up (remembered for this file)")

    # ----- environment: sky, hemispheric lighting, sun, blob shadow ---------
    def _env_on(self, flag: str) -> bool:
        return bool(self.env.get("enabled") and self.env.get(flag))

    def _sun_frame_dir(self):
        return sun_dir_frame(math.radians(self.env["sun_az"]), math.radians(self.env["sun_el"]))

    def _pbr_wanted(self) -> bool:
        return bool(self.env.get("pbr") and not getattr(self, "_pbr_broken", False))

    @staticmethod
    def _pbr_values(a):
        """(metallic, roughness) for one actor: the glTF material if it has one, else a plain non-metal
        whose roughness follows the Phong specular power."""
        v = getattr(a, "_pbr", None)
        if v:
            return v
        try:
            power = float(a.GetProperty().GetSpecularPower())
        except Exception:
            power = 30.0
        return (0.0, min(1.0, max(0.35, math.sqrt(2.0 / (power + 2.0)))))

    def _current_env_code(self, a=None) -> str:
        """The environment shader; with an actor, in the PBR form for that actor's material when PBR is on."""
        if not self._env_on("lighting"):
            return ""
        pbr = self._pbr_values(a) if (a is not None and self._pbr_wanted()) else None
        sh = None
        p = self._pano
        if p is not None and p.get("sh") is not None and (self.env.get("pano_light", 0) > 0 or pbr is not None):
            sh = (p["sh"], pano_frame_matrix(self.up_axis, self.env["yaw"]), p.get("sh_rad"))
        return env_shader_code(self.env, self._sun_frame_dir(), self._env_view_locked, self._ao_wanted(),
                               sh, self.up_axis, pbr)

    def _env_code_all(self) -> str:
        """Every actor's environment shader joined: changes whenever any actor would need a new one."""
        if not self.actors:
            return self._current_env_code()
        codes = [self._current_env_code(a) for a in self.actors]
        return "\n//--\n".join(codes) if any(codes) else ""      # "" = no environment shader at all

    def _install_env(self):
        code = self._env_code_all()
        ao = self._ao_wanted()
        if ao:
            self._ao_update()
        for a in self.actors:
            sp = a.GetShaderProperty()
            sp.ClearAllFragmentShaderReplacements()
            self._ao_detach(a)
            own = self._current_env_code(a)
            if own:                               # never install an empty replacement: it would delete the lighting
                sp.AddFragmentShaderReplacement("//VTK::Light::Impl", True, own, False)
            if ao:
                self._ao_attach(a)
        self._env_code = code

    # ----- Fake AO: crease darkening + a gentle height gradient, as a per-vertex attribute -----
    AO_ARRAY = "gk_fake_ao"

    def _ao_wanted(self) -> bool:
        return bool(self._env_on("lighting") and self.env.get("fake_ao") and self.env.get("ao_strength", 0) > 0
                    and self.actors and not self._ao_split_blocks() and not self.edges_on
                    and not getattr(self, "_ao_broken", False))

    def _ao_split_blocks(self) -> bool:
        """Split compare pauses Fake AO only while the MatCap | normal split is actually showing. The setting
        itself stays on after you leave MatCap, so it must not block AO in plain shaded mode."""
        m = getattr(self, "_ao_mode", None) or self.mode
        return bool(self.split_on and m == "matcap")

    def _ao_live(self) -> bool:
        return bool(self._ao_wanted() and self._ao_on and self.mode == "surface" and self._env_code)

    def _ao_attach(self, a):
        pd = _mapper_data(a.GetMapper())
        arr = getattr(a, "_ao_arr", None)
        if pd is None or arr is None or not isinstance(pd, vtkPolyData):
            return
        pd.GetPointData().AddArray(arr)
        sp = a.GetShaderProperty()
        sp.AddVertexShaderReplacement("//VTK::PositionVC::Dec", True,
                                      "//VTK::PositionVC::Dec\nin vec2 gkAO;\nout vec2 gkAOv;\n", False)
        sp.AddVertexShaderReplacement("//VTK::PositionVC::Impl", True,
                                      "//VTK::PositionVC::Impl\ngkAOv = gkAO;\n", False)
        sp.AddFragmentShaderReplacement("//VTK::Light::Dec", True,
                                        "//VTK::Light::Dec\nin vec2 gkAOv;\n", False)
        a.GetMapper().MapDataArrayToVertexAttribute("gkAO", self.AO_ARRAY, 0, -1)   # 0 = point data
        self._ao_on = True

    def _ao_detach(self, a):
        if not self._ao_on:
            return
        try:
            a.GetShaderProperty().ClearAllVertexShaderReplacements()
            a.GetMapper().RemoveAllVertexAttributeMappings()
            pd = _mapper_data(a.GetMapper())
            if pd is not None and pd.GetPointData().GetArray(self.AO_ARRAY) is not None:
                pd.GetPointData().RemoveArray(self.AO_ARRAY)
        except Exception:
            pass

    def _ao_heights(self):
        """Per part: height of every vertex in world space, scaled 0 (lowest point of the model) to 1 (highest)."""
        vax = 2 if self.up_axis == "Z" else 1
        hs = []
        for a in self.actors:
            pd = _mapper_data(a.GetMapper())
            if pd is None or pd.GetPoints() is None or pd.GetNumberOfPoints() == 0:
                hs.append(None)
                continue
            m = a.GetMatrix()
            row = np.array([m.GetElement(vax, j) for j in range(4)])
            p = numpy_support.vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64)
            hs.append(p @ row[:3] + row[3])
        got = [h for h in hs if h is not None]
        if not got:
            return hs
        lo, hi = min(h.min() for h in got), max(h.max() for h in got)
        span = max(hi - lo, 1e-12)
        return [None if h is None else ((h - lo) / span).astype(np.float32) for h in hs]

    def _ao_update(self):
        """(Re)build the attribute arrays from the cached crease values and the current placement.
        The crease values come from a worker thread the first time; until then they are zero."""
        hs = self._ao_heights()
        for i, a in enumerate(self.actors):
            h = hs[i]
            if h is None:
                a._ao_arr = None
                continue
            cav = self._ao_cav[i] if (self._ao_cav is not None and i < len(self._ao_cav)) else None
            data = np.zeros((len(h), 2), np.float32)
            if cav is not None and len(cav) == len(h):
                data[:, 0] = cav
            data[:, 1] = h
            arr = numpy_support.numpy_to_vtk(data, deep=True, array_type=None)
            arr.SetName(self.AO_ARRAY)
            a._ao_arr = arr
        if self._ao_cav is None and self._ao_task is None:
            self._ao_start()

    def _ao_start(self):
        self._ao_token += 1
        task = AnalysisTask(self._ao_token, cavity_part, self._task_inputs(), "Fake AO")
        task.signals.done.connect(self._ao_done)
        task.signals.failed.connect(self._ao_failed)
        self._ao_task = task
        QThreadPool.globalInstance().start(task)

    def _ao_stop(self):
        if self._ao_task is not None:
            self._ao_task.cancelled = True
        self._ao_task = None
        self._ao_token += 1
        self._ao_cav = None
        self._ao_on = False
        self._ao_broken = False
        self._pbr_broken = False

    def _ao_failed(self, token: int, msg: str):
        if token == self._ao_token:
            self._ao_task = None                  # no crease values: the height gradient still works
            self._ao_cav = [None] * len(self.actors)

    def _ao_done(self, token: int, data: list):
        if token != self._ao_token:
            return
        self._ao_task = None
        self._ao_cav = data
        if self._ao_live():
            self._ao_refresh_arrays()

    def _ao_refresh_arrays(self):
        """New values for the live attribute (no shader change): after the crease values arrive or a part moves."""
        self._ao_update()
        for a in self.actors:
            pd = _mapper_data(a.GetMapper())
            arr = getattr(a, "_ao_arr", None)
            if pd is not None and arr is not None and isinstance(pd, vtkPolyData):
                pd.GetPointData().AddArray(arr)      # replaces the array of the same name
                pd.Modified()
        self.rw.Render()

    def _sync_env_lights(self, mode=None):
        """Three scene lights carry 'world up', 'the sun' and 'world +X' into the shader (surface mode only,
        so every other mode keeps VTK's normal headlight)."""
        mode = mode or self.mode
        if mode == "matcap" and self.split_on:
            mode = "surface"                      # the 'normal' half of a split needs the scene lights
        want = (self._env_on("lighting") and mode == "surface" and bool(self.actors)
                and not self._env_view_locked)
        if want:
            if self._env_lights is None:
                self._env_lights = (vtkLight(), vtkLight(), vtkLight())
                for light in self._env_lights:
                    light.SetLightTypeToSceneLight()
                    light.SetPositional(False)
                    light.SetFocalPoint(0.0, 0.0, 0.0)
            up_l, sun_l, x_l = self._env_lights
            x_l.SetPosition(1.0, 0.0, 0.0)             # only its direction is used (panorama light)
            x_l.SetColor(0.3, 0.3, 0.3)
            x_l.SetIntensity(1.0)
            up_l.SetPosition(*((0.0, 0.0, 1.0) if self.up_axis == "Z" else (0.0, 1.0, 0.0)))
            up_l.SetColor(*[v * 0.3 for v in self.env["sky"]])
            sun_l.SetPosition(*[float(x) for x in frame_to_world(self._sun_frame_dir(), self.up_axis)])
            sun_l.SetColor(*self.env["sun_color"])
            sun_l.SetIntensity(self.env["sun_int"])
            if not self._env_lights_added:
                self.renderer.RemoveAllLights()
                self.renderer.AutomaticLightCreationOff()
                self.renderer.AddLight(up_l)
                self.renderer.AddLight(sun_l)
                self.renderer.AddLight(x_l)
                self._env_lights_added = True
        elif self._env_lights_added:
            for light in self._env_lights:
                self.renderer.RemoveLight(light)
            self.renderer.AutomaticLightCreationOn()
            self._env_lights_added = False

    def _ensure_pano(self):
        path = self.env.get("path") or ""
        if not path and self._pano_path:
            self._pano, self._pano_path, self._sky_key = None, "", None
            return
        if path and path != self._pano_path:
            if os.path.isfile(path):
                try:
                    self._pano = prepare_panorama(read_panorama(path))
                    self._pano_path = path
                    self._sky_key = None
                    return
                except Exception as e:
                    self.message.emit(f"Could not load the panorama: {e}")
            self.env["path"] = ""
            self._pano, self._pano_path, self._sky_key = None, "", None

    def _sync_skybox(self, preview: bool = False):
        want = self._env_on("skybox") and self._pano is not None
        if want:
            blur = float(self.env.get("sky_blur", 0.0))      # blur = a smaller texture, smoothly enlarged
            ow = 256 if preview else max(64, int(SKY_TEX_W * (1.0 - 0.94 * blur)) // 2 * 2)
            key = (self._pano_path, self.up_axis, round(self.env["yaw"], 1), ow)
            if key != self._sky_key:
                img = numpy_to_vtk_image(reproject_panorama(self._pano["disp"], self.up_axis,
                                                            self.env["yaw"], ow))
                if self._sky_tex is None:
                    self._sky_tex = vtkTexture()
                    self._sky_tex.InterpolateOn()
                    self._sky_tex.MipmapOn()
                    self._sky_tex.SetColorModeToDirectScalars()
                    self._skybox = vtkSkybox()
                    self._skybox.SetProjectionToSphere()
                    self._skybox.SetTexture(self._sky_tex)
                    self._skybox.UseBoundsOff()          # never let the sky affect camera framing
                self._sky_tex.SetInputData(img)
                self._sky_tex.Modified()
                self._sky_key = key
            if not self._sky_added:
                self.renderer.AddActor(self._skybox)
                self._sky_added = True
        elif self._sky_added:
            self.renderer.RemoveActor(self._skybox)
            self._sky_added = False

    def _remove_shadow(self):
        if self._blob_added:
            self.renderer.RemoveActor(self._blob)
            self._blob_added = False

    def _sync_shadow(self):
        """A soft dark blob on a plane under the model: no shadow map, no extra render pass."""
        if not (self._env_on("shadow") and self.actors):
            self._remove_shadow()
            return
        lo, hi = self._model_bounds()
        ext = np.maximum(hi - lo, 1e-9)
        ctr = (lo + hi) / 2
        z_up = self.up_axis == "Z"
        h0, h1, vax = (0, 1, 2) if z_up else (0, 2, 1)
        ground = lo[vax] - 0.002 * float(ext.max())
        r0 = 0.5 * ext[h0] * 1.15 * self.env["shadow_size"]
        r1 = 0.5 * ext[h1] * 1.15 * self.env["shadow_size"]
        sun = frame_to_world(self._sun_frame_dir(), self.up_axis)
        sh = np.array([sun[h0], sun[h1]])
        n = float(np.linalg.norm(sh))
        off = (-(sh / n) * min(0.35 * ext[vax] * n, 0.5 * max(r0, r1))) if n > 1e-6 else np.zeros(2)
        c0, c1 = ctr[h0] + off[0], ctr[h1] + off[1]
        if self._blob is None:
            self._blob_src = vtkPlaneSource()
            m = vtkPolyDataMapper()
            m.SetInputConnection(self._blob_src.GetOutputPort())
            tex = vtkTexture()
            tex.SetInputData(numpy_to_vtk_image(blob_texture_array()))
            tex.SetColorModeToDirectScalars()
            tex.InterpolateOn()
            tex.RepeatOff()
            tex.EdgeClampOn()
            self._blob = vtkActor()
            self._blob.SetMapper(m)
            self._blob.SetTexture(tex)
            self._blob.GetProperty().LightingOff()
            self._blob.GetProperty().BackfaceCullingOn()    # only visible from above
            self._blob.UseBoundsOff()
            self._blob.SetPickable(False)
        if z_up:
            o, p1, p2 = (c0 - r0, c1 - r1, ground), (c0 + r0, c1 - r1, ground), (c0 - r0, c1 + r1, ground)
        else:
            o, p1, p2 = (c0 - r0, ground, c1 - r1), (c0 - r0, ground, c1 + r1), (c0 + r0, ground, c1 - r1)
        self._blob_src.SetOrigin(*o)
        self._blob_src.SetPoint1(*p1)
        self._blob_src.SetPoint2(*p2)
        self._blob_src.Update()
        self._blob.GetProperty().SetOpacity(self.env["shadow_opacity"])
        if not self._blob_added:
            self.renderer.AddActor(self._blob)
            self._blob_added = True

    def _sync_background(self):
        """A colour-only environment can tint the background with a sky gradient."""
        if self._env_on("gradient_bg") and not self._sky_added:
            self.renderer.SetBackground(*self.env["equator"])
            self.renderer.SetBackground2(*self.env["sky"])
            self.renderer.SetGradientBackground(True)
            self._bg_from_env = True
            self._style_axes()
        elif self._bg_from_env:
            self._bg_from_env = False
            self.set_background(self.bg_idx, announce=False)

    def apply_builtin_preset(self, name: str):
        ov = ENV_BUILTIN_PRESETS.get(name)
        if ov is None:
            return
        self._preset_idx = list(ENV_BUILTIN_PRESETS).index(name)
        keep = {k: self.env.get(k, ENV_DEFAULTS[k]) for k in ("fake_ao", "ao_strength")}
        self.apply_environment_preset(clean_env({**ENV_DEFAULTS, **keep, **ov, "path": ""}), "", name)

    def cycle_lighting_preset(self):
        names = list(ENV_BUILTIN_PRESETS)
        self.apply_builtin_preset(names[(self._preset_idx + 1) % len(names)])

    # ----- Shift + right-drag: rotate the lighting (and the sky) around the model -----
    def eventFilter(self, obj, ev):
        if obj is self.stage:
            if ev.type() == QEvent.Resize and hasattr(self, "overlay"):
                self._place_hud()
                if self.overlay.isVisible():
                    self.overlay.reposition()
                if self._split_visible():
                    self._split_resize_timer.start(150)
            return False
        if obj is not self.vtk_widget:
            return super().eventFilter(obj, ev)
        t = ev.type()
        if t in (QEvent.KeyPress, QEvent.KeyRelease):
            # Every key is handled by the app's own shortcuts. VTK's built-in letter keys (S = solid,
            # W = wireframe, P = pick, E/Q = exit, ...) must never reach the scene: they changed the
            # ground grid and could alter other props.
            return True
        if self.measure_on and self.actors:
            # a click without a drag picks a point; drags still orbit, pan and zoom as normal
            if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._meas_press = (ev.position().x(), ev.position().y())
            elif t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton and self._meas_press is not None:
                x0, y0 = self._meas_press
                self._meas_press = None
                if math.hypot(ev.position().x() - x0, ev.position().y() - y0) < 5.0:
                    self._measure_pick(ev.position().x(), ev.position().y())
        if self.split_on and t in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease,
                                   QEvent.MouseButtonDblClick) and self._split_visible():
            if self._split_event(ev, t):
                return True
        # Shift + right-drag: rotate the lighting
        if (t == QEvent.MouseButtonPress and ev.button() == Qt.RightButton
                and bool(ev.modifiers() & Qt.ShiftModifier) and self.env.get("enabled") and self.actors):
            self._light_drag = (ev.position().x(), self.env["sun_az"], self.env["yaw"])
            return True                                    # keep VTK from also starting a zoom
        if self._light_drag is not None:
            if t == QEvent.MouseMove:
                self._rotate_lighting(ev.position().x() - self._light_drag[0])
                return True
            if t == QEvent.MouseButtonRelease:
                self._finish_lighting_drag()
                return True
        # Plain left-drag with the horizon locked: turntable orbit instead of trackball
        if (self.turntable and self.actors and t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton
                and not bool(ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier))):
            self._tt_drag = (ev.position().x(), ev.position().y())
            self._dragging = True                          # pauses auto-orbit while you drag
            self._level_horizon()
            return True
        if self._tt_drag is not None:
            if t == QEvent.MouseMove:
                x, y = ev.position().x(), ev.position().y()
                self._turntable_rotate(x - self._tt_drag[0], y - self._tt_drag[1])
                self._tt_drag = (x, y)
                return True
            if t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                self._tt_drag = None
                self._dragging = False
                return True
        return super().eventFilter(obj, ev)

    # ----- turntable (locked horizon) vs trackball rotation -----
    def _level_horizon(self):
        """Snap the camera's up direction to the model's up axis (unless looking straight along it)."""
        cam = self.renderer.GetActiveCamera()
        u = np.array(self._axes_vectors()[0])
        d = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
        n = float(np.linalg.norm(d))
        if n > 1e-12 and abs(float(np.dot(d / n, u))) < 0.9995:
            cam.SetViewUp(*u)
            cam.OrthogonalizeViewUp()

    def _turntable_rotate(self, dx: float, dy: float):
        cam = self.renderer.GetActiveCamera()
        u = np.array(self._axes_vectors()[0])
        fp = np.array(cam.GetFocalPoint())
        w, h = max(self.vtk_widget.width(), 1), max(self.vtk_widget.height(), 1)
        rel = turntable_rel(np.array(cam.GetPosition()) - fp, u, np.array(cam.GetViewUp()),
                            math.radians(-dx * 200.0 / w), math.radians(dy * 200.0 / h))
        cam.SetPosition(*(fp + rel))
        cam.SetViewUp(*u)
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    def set_turntable(self, on: bool):
        self.turntable = bool(on)
        self.settings.setValue("turntable", "true" if on else "false")
        if on:
            self._level_horizon()
            self.rw.Render()
        self.message.emit("Horizon locked: turntable rotation" if on else "Free rotation: trackball")

    def toggle_turntable(self):
        self.act_turntable.toggle()

    def _rotate_lighting(self, dx: float):
        _x0, az0, yaw0 = self._light_drag
        deg = dx * 0.4
        self.env["sun_az"] = (az0 + deg + 180.0) % 360.0 - 180.0
        if self._pano is not None:                         # the sky turns with the sun
            self.env["yaw"] = (yaw0 + deg + 180.0) % 360.0 - 180.0
        self._sync_skybox(preview=True)                    # small texture while dragging: stays smooth
        self._sync_shadow()
        self._sync_env_lights()
        self.rw.Render()

    def _finish_lighting_drag(self):
        self._light_drag = None
        self._sync_skybox()                                # full-quality sky once the drag ends
        self._save_env()
        if self._env_panel is not None:
            self._env_panel.set_env(self.env, self._pano_path)
        self.rw.Render()

    def _sync_env_scene(self):
        if self.env["enabled"]:
            self._ensure_pano()
        self._sync_skybox()
        self._sync_background()
        self._sync_shadow()
        self._sync_ground()
        self._sync_env_lights()

    def _env_refresh(self):
        """Bring sky, shadow, lights and shader in line with self.env."""
        self._sync_env_scene()
        if self.mode == "surface" and self._env_code_all() != self._env_code:
            self.set_mode("surface")              # reinstalls (or removes) the shader and renders
        elif self._split_visible():
            self._split_request_rebake()          # the 'normal' half follows the environment
            self.rw.Render()
        else:
            self.rw.Render()

    def _env_failed(self):
        """The environment shader didn't compile: drop PBR first, then Fake AO, then follow the camera instead, then switch off."""
        if self._pbr_wanted():
            self._pbr_broken = True
            self.env["pbr"] = False
            after = _log_size()
            try:
                self._install_env()
                self.rw.Render()
            except Exception:
                pass
            if not _shader_error_since(after):
                self.message.emit("This GPU rejected the PBR look, so it was switched off")
                if self._env_panel is not None:
                    self._env_panel.set_env(self.env)
                return
        if self._ao_wanted():
            self._ao_broken = True
            self._ao_on = True
            for a in self.actors:
                self._ao_detach(a)
            self._ao_on = False
            after = _log_size()
            try:
                self._install_env()
                self.rw.Render()
            except Exception:
                pass
            if not _shader_error_since(after):
                self.message.emit("This GPU rejected Fake AO, so it was switched off")
                if self._env_panel is not None:
                    self._env_panel.set_env(self.env)
                return
        if not self._env_view_locked:
            self._env_view_locked = True
            self._sync_env_lights()
            after = _log_size()
            try:
                self._install_env()
                self.rw.Render()
            except Exception:
                pass
            if not _shader_error_since(after):
                self.message.emit("Environment lighting is following the camera on this GPU")
                return
        self.env["lighting"] = False
        self._clear_replacements()
        self._env_code = ""
        self._sync_env_lights()
        self.rw.Render()
        self.message.emit("This GPU rejected the environment shader, so environment lighting was "
                          "switched off (details are in the VTK log in your temp folder)")
        if self._env_panel is not None:
            self._env_panel.set_env(self.env)

    def _save_env(self):
        try:
            self.settings.setValue("environment", json.dumps(self.env))
        except Exception:
            pass

    def apply_environment(self, env: dict):
        """From the panel: adopt the new settings (the panorama path is managed by the viewer)."""
        path = self.env.get("path", "")
        self.env = clean_env(env)
        self.env["path"] = path
        self._sync_env_action()
        self._save_env()
        self._env_refresh()

    def _sync_env_action(self):
        self.act_env.blockSignals(True)
        self.act_env.setChecked(bool(self.env["enabled"]))
        self.act_env.blockSignals(False)

    def set_environment_enabled(self, on: bool):
        self.env["enabled"] = bool(on)
        self._save_env()
        if self._env_panel is not None:
            self._env_panel.set_env(self.env, self._pano_path)
        self._env_refresh()
        self.message.emit("Environment: on" if on else "Environment: off")

    def toggle_environment(self):
        self.act_env.toggle()

    def load_panorama(self, path: str):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pano = prepare_panorama(read_panorama(path))
        except Exception as e:
            self.message.emit(f"Could not load the panorama: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._pano, self._pano_path, self._sky_key = pano, path, None
        self.env["path"] = path
        self.env["enabled"] = True
        self._env_view_locked = False
        self.fit_to_panorama(announce=False)
        self.message.emit(f"Panorama loaded: {Path(path).name} (lighting fitted to it)")

    def fit_to_panorama(self, announce: bool = True):
        if self._pano is None:
            self.message.emit("Load a panorama first")
            return
        info = self._pano["info"]
        az, el = dir_to_azel(info["sun_dir"])
        self.env.update(sky=info["sky"], equator=info["equator"], ground=info["ground"],
                        sun_color=info["sun_color"], sun_int=info["sun_int"],
                        sun_az=(az + self.env["yaw"] + 180.0) % 360.0 - 180.0,
                        sun_el=min(90.0, max(-10.0, el)))
        self._sync_env_action()
        self._save_env()
        if self._env_panel is not None:
            self._env_panel.set_env(self.env, self._pano_path)
        self._env_refresh()
        if announce:
            self.message.emit("Lighting fitted to the panorama")

    def clear_panorama(self):
        self.env["path"] = ""
        self._pano, self._pano_path, self._sky_key = None, "", None
        self._save_env()
        if self._env_panel is not None:
            self._env_panel.set_env(self.env, "")
        self._env_refresh()

    def apply_environment_preset(self, env: dict, missing: str = "", name: str = "Environment"):
        """A preset replaces the colours, sun, shadow and (if found) the panorama."""
        self.env = clean_env(env)
        self.env["enabled"] = True
        self._env_view_locked = False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._env_refresh()                   # loads the panorama if the preset names one
        finally:
            QApplication.restoreOverrideCursor()
        self._sync_env_action()
        self._save_env()
        if self._env_panel is not None:
            self._env_panel.set_env(self.env, self._pano_path)
        note = f" (panorama '{missing}' was not found, so it uses the saved colours only)" if missing else ""
        self.message.emit(f"Environment preset loaded: {name}{note}")

    def environment_panel(self):
        if self._env_panel is None:
            self._env_panel = EnvironmentPanel(None, self.env, self._pano_path)
            self._env_panel.changed.connect(self.apply_environment)
            self._env_panel.load_requested.connect(self.load_panorama)
            self._env_panel.fit_requested.connect(self.fit_to_panorama)
            self._env_panel.clear_requested.connect(self.clear_panorama)
            self._env_panel.preset_loaded.connect(self.apply_environment_preset)
            self._env_panel.builtin_requested.connect(self.apply_builtin_preset)
        return self._env_panel

    def open_environment_panel(self):
        self.environment_panel().set_env(self.env, self._pano_path)
        self.panel_requested.emit("environment")

    # ----- model info panel -------------------------------------------------
    def _place_info(self):
        p = getattr(self, "info_panel", None)
        if p is not None:
            p.adjustSize()
            p.move(12, self.hud.y() + self.hud.height() + 10)
            p.raise_()

    def _update_info(self):
        p = getattr(self, "info_panel", None)
        if p is None:
            return
        if not (self.info_on and self.actors):
            p.hide()
            return
        try:
            p.set_info(collect_model_info(self.actors, self.path, self.up_axis))
        except Exception as e:
            self.message.emit(f"Could not read the model details: {e}")
            p.hide()
            return
        p.show()
        self._place_info()

    def toggle_info(self):
        self.act_info.toggle()

    def set_info_visible(self, on: bool):
        self.info_on = bool(on)
        self.settings.setValue("info_on", "true" if on else "false")
        self._update_info()

    # ----- export / convert --------------------------------------------------
    def open_export_dialog(self):
        if not self.actors:
            self.message.emit("Open a model first, then export it")
            return
        if self._export_task is not None:
            self.message.emit("An export is already running")
            return
        shown = [a for a in self.actors if a.GetVisibility()]
        if not shown:
            self.message.emit("All parts are hidden, so there is nothing to export")
            return
        info = collect_model_info(shown, self.path, self.up_axis)
        dlg = ExportDialog(self.window(), info["name"], info["tris"],
                           _setting_int(self.settings, "export_fmt", 0),
                           str(self.settings.value("export_simplify", "false")).lower() in ("1", "true"),
                           _setting_int(self.settings, "export_keep", 50))
        if dlg.exec() != QDialog.Accepted:
            return
        idx, keep = dlg.values()
        self.settings.setValue("export_fmt", idx)
        self.settings.setValue("export_simplify", "true" if keep is not None else "false")
        if keep is not None:
            self.settings.setValue("export_keep", int(round(keep * 100)))
        label, ext, kind, binary = EXPORT_FORMATS[idx]
        start = str(self.settings.value("export_dir", "")) or os.path.dirname(self.path) or str(Path.home())
        if not os.path.isdir(start):
            start = str(Path.home())
        fn, _ = QFileDialog.getSaveFileName(
            self.window(), "Export model",
            os.path.join(start, export_default_name(self.path, idx, keep is not None)),
            f"{label} (*{ext})")
        if not fn:
            return
        if not fn.lower().endswith(ext):
            fn += ext
        self.settings.setValue("export_dir", os.path.dirname(fn))
        parts = snapshot_export_parts(self.actors)
        if not parts:
            self.message.emit("There is no mesh data to export")
            return
        task = ExportTask(parts, fn, kind, binary, keep)
        task.signals.done.connect(self._export_done)
        task.signals.failed.connect(self._export_failed)
        self._export_task = task                  # keeps the task and its signals alive
        self.message.emit("Exporting…")
        QThreadPool.globalInstance().start(task)

    def _export_done(self, msg: str):
        self._export_task = None
        self.message.emit(msg)

    def _export_failed(self, msg: str):
        self._export_task = None
        self.message.emit("Export failed")
        QMessageBox.warning(self.window(), "Export / convert", f"The export did not finish.\n\n{msg}")

    # ----- scene helpers: fit, field of view, saved views, ground, edges ----
    def fit_view(self):
        """F: re-centre and re-fit the model without changing the viewing direction."""
        if not self.actors:
            return
        self.renderer.ResetCamera()
        self.renderer.GetActiveCamera().Zoom(1.05)
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    def set_fov(self, deg: float):
        """Change the field of view; the camera moves so the model stays the same size."""
        deg = max(10.0, min(90.0, float(deg)))
        cam = self.renderer.GetActiveCamera()
        if not cam.GetParallelProjection():
            fp = np.array(cam.GetFocalPoint())
            offset = np.array(cam.GetPosition()) - fp
            n = float(np.linalg.norm(offset))
            if n > 1e-9:
                new_dist = fov_distance(n, cam.GetViewAngle(), deg)
                cam.SetViewAngle(deg)
                cam.SetPosition(*(fp + offset / n * new_dist))
            else:
                cam.SetViewAngle(deg)
        else:
            cam.SetViewAngle(deg)
        self.fov = deg
        self.settings.setValue("fov", int(round(deg)))
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    def save_bookmark(self, n: int):
        if not self.actors:
            return
        cam = self.renderer.GetActiveCamera()
        self._bookmarks[n] = {"pos": cam.GetPosition(), "fp": cam.GetFocalPoint(), "up": cam.GetViewUp(),
                              "angle": cam.GetViewAngle(), "par": cam.GetParallelProjection(),
                              "scale": cam.GetParallelScale()}
        self.message.emit(f"Saved camera view {n}  (Alt+{n} to return)")

    def go_bookmark(self, n: int):
        b = self._bookmarks.get(n)
        if b is None:
            self.message.emit(f"No camera view {n} saved yet  (Ctrl+Shift+{n} saves one)")
            return
        cam = self.renderer.GetActiveCamera()
        cam.SetPosition(*b["pos"])
        cam.SetFocalPoint(*b["fp"])
        cam.SetViewUp(*b["up"])
        cam.SetViewAngle(b["angle"])
        cam.SetParallelProjection(bool(b["par"]))
        cam.SetParallelScale(b["scale"])
        self.fov = b["angle"]
        self.act_ortho.blockSignals(True)
        self.act_ortho.setChecked(bool(b["par"]))
        self.act_ortho.blockSignals(False)
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    # -- placement
    def _model_bounds(self):
        vis = [a for a in self.actors if a.GetVisibility()] or self.actors     # hidden parts don't count
        bb = np.array([a.GetBounds() for a in vis], dtype=float).reshape(-1, 3, 2)
        return bb[:, :, 0].min(0), bb[:, :, 1].max(0)

    @staticmethod
    def _user_matrix_list(a):
        m = a.GetUserMatrix()
        return None if m is None else [m.GetElement(i, j) for i in range(4) for j in range(4)]

    def _translate_world(self, delta):
        """Shift every part by `delta` in world space (composed after any placement the file has)."""
        t = vtkMatrix4x4()
        for i in range(3):
            t.SetElement(i, 3, float(delta[i]))
        for a in self.actors:
            old = a.GetUserMatrix()
            new = vtkMatrix4x4()
            vtkMatrix4x4.Multiply4x4(t, old if old is not None else vtkMatrix4x4(), new)
            a.SetUserMatrix(new)
        self._after_move()

    def _after_move(self):
        if self._ao_live():
            self._ao_refresh_arrays()
        self._sync_ground()
        self._sync_shadow()
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    def move_to_ground(self):
        if not self.actors:
            return
        lo, _hi = self._model_bounds()
        vax = 2 if self.up_axis == "Z" else 1
        d = [0.0, 0.0, 0.0]
        d[vax] = -lo[vax]
        self._translate_world(d)
        self.message.emit("Moved to the ground (lowest point at height 0)")

    def move_to_origin(self):
        if not self.actors:
            return
        lo, hi = self._model_bounds()
        self._translate_world(-(lo + hi) / 2.0)
        self.message.emit("Moved to the origin (centre of the model at 0, 0, 0)")

    def reset_position(self):
        if not self.actors:
            return
        for a in self.actors:
            flat = getattr(a, "_orig_um", None)
            m = vtkMatrix4x4()
            if flat is not None:
                for i in range(4):
                    for j in range(4):
                        m.SetElement(i, j, flat[i * 4 + j])
            a.SetUserMatrix(m)
        self._after_move()
        self.message.emit("Position reset to the file's own placement")

    # -- ground grid
    def _remove_ground(self):
        if self._grid_added:
            self.renderer.RemoveActor(self._grid)
            self._grid_added = False

    def _sync_ground(self):
        if not (self.grid_on and self.actors):
            self._remove_ground()
            return
        lo, hi = self._model_bounds()
        o, p1, p2, n, _cell = ground_grid_geometry(lo, hi, self.up_axis)
        if self._grid is None:
            self._grid_src = vtkPlaneSource()
            m = vtkPolyDataMapper()
            m.SetInputConnection(self._grid_src.GetOutputPort())
            self._grid = vtkActor()
            self._grid.SetMapper(m)
            prop = self._grid.GetProperty()
            prop.SetRepresentationToWireframe()
            prop.LightingOff()
            prop.SetColor(0.62, 0.68, 0.78)
            prop.SetOpacity(0.35)
            prop.SetLineWidth(1.0)
            self._grid.UseBoundsOff()
            self._grid.SetPickable(False)
        self._grid.GetProperty().SetRepresentationToWireframe()   # stays a grid whatever else happens
        self._grid_src.SetOrigin(*o)
        self._grid_src.SetPoint1(*p1)
        self._grid_src.SetPoint2(*p2)
        self._grid_src.SetXResolution(n)
        self._grid_src.SetYResolution(n)
        self._grid_src.Update()
        if not self._grid_added:
            self.renderer.AddActor(self._grid)
            self._grid_added = True

    def set_grid(self, on: bool):
        self.grid_on = bool(on)
        self.settings.setValue("grid_on", "true" if on else "false")
        self._sync_ground()
        self.rw.Render()

    def toggle_grid(self):
        self.act_grid.toggle()

    # -- edges over shaded
    def _apply_edges(self, mode=None):
        m = mode or self.mode
        # In a split compare the edges belong on the normal-shaded half (the MatCap half covers them).
        on = self.edges_on and (m == "surface" or (m == "matcap" and self.split_on))
        for a in self.actors:
            p = a.GetProperty()
            if on:
                p.EdgeVisibilityOn()
                p.SetEdgeColor(0.08, 0.10, 0.14)
            else:
                p.EdgeVisibilityOff()

    def set_edges(self, on: bool):
        had_ao = self._ao_wanted()
        self.edges_on = bool(on)
        self.settings.setValue("edges_on", "true" if on else "false")
        self._apply_edges()
        if self.actors and self.mode == "surface" and had_ao != self._ao_wanted():
            self.set_mode("surface")              # Fake AO is paused while the wireframe overlay is on
            if on:
                self.message.emit("Wireframe overlay on (Fake AO is paused while it is on)")
            return
        self.rw.Render()

    def toggle_edges(self):
        self.act_edges.toggle()

    def scene_panel(self):
        if self._scene_panel is None:
            self._scene_panel = ScenePanel(None, self)
        return self._scene_panel

    def open_scene_panel(self):
        self.scene_panel().sync()
        self.panel_requested.emit("scene")

    # ----- material views (albedo / normals) and parts -----------------------
    def set_view_channel(self, name: str):
        self.set_mode(name, force=True)
        label = dict(VIEW_CHANNELS).get(name, name)
        self.message.emit(f"View: {label}")

    def cycle_view_channel(self):
        """V: shaded -> albedo (no lighting) -> normals -> shaded."""
        order = [k for k, _l in VIEW_CHANNELS]
        nxt = order[(order.index(self.mode) + 1) % len(order)] if self.mode in order else "albedo"
        self.set_view_channel(nxt)

    def _install_view_shader(self, mode: str):
        for a in self.actors:
            sp = a.GetShaderProperty()
            sp.ClearAllFragmentShaderReplacements()
            sp.AddFragmentShaderReplacement("//VTK::Light::Impl", True, VIEW_SHADERS[mode], False)

    def _view_failed(self):
        self._clear_replacements()
        self.mode = "surface"
        self.matcap_btn.setText("MatCap")
        self.rw.Render()
        self.message.emit("This GPU rejected that view's shader, so normal shading was restored")

    def set_part_visible(self, idx: int, on: bool):
        if 0 <= idx < len(self.actors):
            self.actors[idx].SetVisibility(bool(on))
            self._after_visibility()

    def isolate_part(self, idx: int):
        for i, a in enumerate(self.actors):
            a.SetVisibility(i == idx)
        self._after_visibility()

    def show_all_parts(self):
        for a in self.actors:
            a.SetVisibility(True)
        self._after_visibility()

    def invert_parts(self):
        for a in self.actors:
            a.SetVisibility(not a.GetVisibility())
        self._after_visibility()

    def _after_visibility(self):
        self._section_sync_vis()
        self._sync_ground()
        self._sync_shadow()
        self._update_info()
        self.rw.Render()

    def _remove_outline(self):
        if self._outline_added:
            self.renderer.RemoveActor(self._outline)
            self._outline_added = False

    def highlight_part(self, idx):
        """Outline one part with a bounding box (None clears it)."""
        if idx is None or not (0 <= idx < len(self.actors)):
            if self._outline_added:
                self._remove_outline()
                self.rw.Render()
            return
        if self._outline is None:
            self._outline_src = vtkOutlineSource()
            m = vtkPolyDataMapper()
            m.SetInputConnection(self._outline_src.GetOutputPort())
            self._outline = vtkActor()
            self._outline.SetMapper(m)
            prop = self._outline.GetProperty()
            prop.SetColor(0.42, 0.66, 0.91)
            prop.SetLineWidth(2.0)
            prop.LightingOff()
            self._outline.UseBoundsOff()
            self._outline.SetPickable(False)
        self._outline_src.SetBounds(*self.actors[idx].GetBounds())
        if not self._outline_added:
            self.renderer.AddActor(self._outline)
            self._outline_added = True
        self.rw.Render()

    def materials_panel(self):
        if self._materials_panel is None:
            self._materials_panel = MaterialsPanel(None, self)
        return self._materials_panel

    def open_materials_panel(self):
        self.materials_panel().refresh()
        self.panel_requested.emit("materials")

    # ----- transparency (solid by default) ---------------------------------
    def _tr_actors(self):
        return [a for a in self.actors if getattr(a, "_tr", None) is not None]

    def _has_transparency(self) -> bool:
        return any(a._tr.has_effect for a in self._tr_actors())

    def _sync_transp_action(self, on: bool):
        self.act_transp.blockSignals(True)
        self.act_transp.setChecked(bool(on))
        self.act_transp.blockSignals(False)

    def _apply_transparency(self):
        for a in self._tr_actors():
            a._tr.apply(a, solid=not self.transparent)

    def toggle_transparency(self):
        """T: switch between solid (default) and the material's own transparency."""
        if not self.actors:
            return
        if not self._has_transparency():
            self.message.emit("This model has no transparent materials")
            return
        self.act_transp.toggle()

    def set_transparency(self, on: bool):
        if not self._has_transparency():
            self._sync_transp_action(False)
            self.message.emit("This model has no transparent materials")
            return
        self.transparent = bool(on)
        self.settings.setValue("transparency_on", "true" if on else "false")
        self._apply_transparency()
        self.rw.Render()
        self.message.emit("Transparency: respecting the material (may look rough where layers overlap)"
                          if on else "Transparency: off (solid)")

    # ----- auto-orbit -------------------------------------------------------
    def toggle_orbit(self):
        self.orbit_btn.toggle()

    def set_orbit(self, on: bool):
        if on:
            self._orbit_timer.start(20)
        else:
            self._orbit_timer.stop()

    def set_orbit_speed(self, idx: int):
        self.orbit_speed_idx = idx
        self.settings.setValue("orbit_speed", idx)

    def _orbit_tick(self):
        if self._dragging or not self.actors or not self.isVisible():
            return
        theta = math.radians(ORBIT_SPEEDS[self.orbit_speed_idx][1] * 0.02)
        u, _f, _r = self._axes_vectors()
        cam = self.renderer.GetActiveCamera()
        fp = np.array(cam.GetFocalPoint())
        rel = np.array(cam.GetPosition()) - fp
        rel = (rel * math.cos(theta) + np.cross(u, rel) * math.sin(theta)
               + u * np.dot(u, rel) * (1 - math.cos(theta)))     # turntable about the up axis
        cam.SetPosition(*(fp + rel))
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    # ----- background + axes gizmo -----------------------------------------
    def set_background(self, idx: int, announce: bool = True):
        if announce and self._bg_from_env:
            self.env["gradient_bg"] = False              # the user chose a background: stop overriding it
            self._bg_from_env = False
            self._save_env()
            if self._env_panel is not None:
                self._env_panel.set_env(self.env)
        if idx >= CUSTOM_BG:
            c = QColor(str(self.settings.value("bg_custom", "#202428")))
            col = (c.redF(), c.greenF(), c.blueF())
            name, c1, c2 = "Custom", col, col
            idx = CUSTOM_BG
        else:
            idx = max(0, idx)
            name, c1, c2 = BACKGROUNDS[idx]
        self.bg_idx = idx
        self.settings.setValue("bg_idx", idx)
        self.renderer.SetBackground(*c1)
        self.renderer.SetBackground2(*c2)
        self.renderer.SetGradientBackground(tuple(c1) != tuple(c2))
        self._style_axes()
        self.rw.Render()
        if announce:
            self.message.emit(f"Background: {name}")

    def cycle_background(self):
        self.set_background(0 if self.bg_idx >= len(BACKGROUNDS) - 1 else self.bg_idx + 1)

    def pick_background(self):
        initial = QColor(str(self.settings.value("bg_custom", "#202428")))
        c = QColorDialog.getColor(initial, self, "Background colour")
        if c.isValid():
            self.settings.setValue("bg_custom", c.name())
            self.set_background(CUSTOM_BG)

    def _style_axes(self):
        if self._axes_actor is None:
            return
        c1 = self.renderer.GetBackground()
        c2 = self.renderer.GetBackground2()
        lum = sum(c1) / 6 + sum(c2) / 6
        text = (0.08, 0.08, 0.1) if lum > 0.55 else (0.92, 0.94, 0.97)
        for cap in (self._axes_actor.GetXAxisCaptionActor2D(),
                    self._axes_actor.GetYAxisCaptionActor2D(),
                    self._axes_actor.GetZAxisCaptionActor2D()):
            tp = cap.GetCaptionTextProperty()
            tp.SetColor(*text)
            tp.ShadowOff()

    def _sync_axes(self):
        want = self.axes_on and bool(self.actors)
        if want and self._axes_widget is None:
            try:
                self._axes_actor = vtkAxesActor()
                w = vtkOrientationMarkerWidget()
                w.SetOrientationMarker(self._axes_actor)
                w.SetInteractor(self.iren)
                w.SetViewport(0.0, 0.0, 0.16, 0.26)
                w.SetEnabled(1)
                w.InteractiveOff()
                self._axes_widget = w
                self._style_axes()
            except Exception:
                self._axes_widget = None
                self.axes_on = False
                return
        if self._axes_widget is not None:
            self._axes_widget.SetEnabled(1 if want else 0)

    def set_axes(self, on: bool):
        self.axes_on = bool(on)
        self.settings.setValue("axes_on", "true" if on else "false")
        self._sync_axes()
        self.rw.Render()

    # ----- UV diagnostics: layout beside the model + heatmap on the model ----------------
    def _uv_collect(self) -> list:
        data = []
        for a in self.actors:
            try:
                data.append(uv_collect_part(_mapper_data(a.GetMapper())))
            except Exception:
                data.append(None)
        return data

    def _uv_selected(self) -> list:
        if 0 <= self.uv_part < len(self._uv_data):
            return [self.uv_part]
        return [i for i, d in enumerate(self._uv_data) if d is not None]

    def uv_counts(self) -> dict:
        """Totals for the chosen part(s): triangles, how many fail each test, and whether UVs exist."""
        out = {"has_uv": False, "tris": 0, "islands": 0, "isl_ok": True,
               **{k: 0 for k, *_r in UV_TESTS}, **{"inv_" + k: 0 for k in UV_ISLAND_TESTS}}
        for i in self._uv_selected():
            d = self._uv_data[i]
            if d is None:
                continue
            out["has_uv"] = True
            out["tris"] += len(d["tris"])
            for k, *_r in UV_TESTS:
                out[k] += int(d["flags"][k].sum())
            if d.get("isl") is None:
                out["isl_ok"] = False                   # too large (or failed): island tests were not run
            else:
                out["islands"] += d["isl"]["n"]
                for k in UV_ISLAND_TESTS:
                    out["inv_" + k] += d["isl"]["involved"][k]
        return out

    def uv_refresh(self):
        """A model opened: forget the old analysis. Nothing is calculated until the user asks (uv_ensure)."""
        self._uv_stop()
        self._uv_restore_heatmap()
        self._uv_data = []
        self._uv_ready = False
        self._uv_update_layout()
        if self.actors:
            self.rw.Render()
        self.uv_changed.emit()

    def _task_inputs(self) -> list:
        """Read-only copies of every part's geometry for a worker (the live data is never handed over)."""
        out = []
        for a in self.actors:
            ds = _mapper_data(a.GetMapper())
            if ds is not None and isinstance(ds, vtkPolyData):
                c = vtkPolyData()
                c.ShallowCopy(ds)                   # shared arrays, read-only
                out.append(c)
            else:
                out.append(None)
        return out

    def uv_ensure(self):
        """Start the UV analysis for the open model (once). It runs in the background: the window stays usable and
        the Run button turns into Cancel until it finishes."""
        if self._uv_ready or not self.actors or self._uv_task is not None:
            return
        self._uv_restore_heatmap()
        self._uv_token += 1
        task = AnalysisTask(self._uv_token, uv_collect_part, self._task_inputs(), "Analysing UVs")
        task.signals.progress.connect(self._uv_progress)
        task.signals.done.connect(self._uv_done)
        task.signals.failed.connect(self._uv_failed)
        self._uv_task = task
        self.uv_status = "Analysing UVs …"
        self.uv_changed.emit()
        QThreadPool.globalInstance().start(task)

    def uv_run_or_cancel(self):
        if self._uv_task is not None:
            self._uv_task.cancelled = True
            self.uv_status = "Cancelling …"
            self.uv_changed.emit()
        else:
            self.uv_ensure()

    def _uv_stop(self):
        """Drop a running UV analysis without waiting for it (a model was opened or the geometry changed)."""
        if self._uv_task is not None:
            self._uv_task.cancelled = True
        self._uv_task = None
        self._uv_token += 1
        self.uv_status = ""

    def _uv_progress(self, text: str):
        if self._uv_task is not None and not self._uv_task.cancelled:
            self.uv_status = text
            self.analysis_progress.emit("uv", text)

    def _mesh_progress(self, text: str):
        if self._mesh_task is not None and not self._mesh_task.cancelled:
            self.mesh_status = text
            self.analysis_progress.emit("mesh", text)

    def _uv_failed(self, token: int, msg: str):
        if token != self._uv_token:
            return                                   # another model was opened meanwhile
        self._uv_task = None
        self.uv_status = "" if msg == "cancelled" else "The UV analysis failed: " + msg
        self.uv_changed.emit()

    def _uv_done(self, token: int, data: list):
        if token != self._uv_token:
            return
        self._uv_task = None
        self.uv_status = ""
        self._uv_data = data
        dens, w = [], []
        for d in self._uv_data:
            if d is not None:
                ok = d["m"]["valid"]
                dens.append(d["m"]["dens"][ok])
                w.append(d["m"]["area3"][ok])
        self._uv_ref = weighted_median(np.concatenate(dens), np.concatenate(w)) if dens else 0.0
        self._uv_ready = True
        self._uv_recolor()

    def _uv_heat_active(self) -> bool:
        return bool(self.uv_tests) or bool(self.mesh_tests) or self.uv_heat != "off"

    def _uv_heat_colors(self, i: int):
        """Per-triangle colours of the chosen heatmap for part i (None when the heatmap is off)."""
        d = self._uv_data[i] if i < len(self._uv_data) else None
        if d is None or self.uv_heat == "off":
            return None
        m = d["m"]
        if self.uv_heat == "density":
            return uv_heat_density(m["dens"], m["valid"], self._uv_ref, self.uv_th["dens_low"], self.uv_th["dens_high"])
        return uv_heat_stretch(m["stretch"], self.uv_th["stretch"])

    def uv_heat_stats(self) -> dict:
        """Share of triangles (of the chosen parts) outside the thresholds, for the tab."""
        n = lo = hi = bad = 0
        for i in self._uv_selected():
            d = self._uv_data[i]
            if d is None:
                continue
            m = d["m"]
            n += len(m["dens"])
            if self.uv_heat == "density" and self._uv_ref > 0:
                r = m["dens"] / self._uv_ref
                lo += int(((r < self.uv_th["dens_low"]) & m["valid"]).sum())
                hi += int(((r > self.uv_th["dens_high"]) & m["valid"]).sum())
            elif self.uv_heat == "stretch":
                bad += int((m["stretch"] > self.uv_th["stretch"]).sum())
        return {"n": n, "low": lo, "high": hi, "bad": bad}

    def _uv_update_layout(self):
        if not self.uv_on:
            return
        idx = self._uv_selected()
        names = [getattr(self.actors[i], "_name", "") or f"Part {i + 1}" for i in idx]
        idx = [i for i in idx if self._uv_data[i] is not None]        # a part without UVs has nothing to draw
        parts = [{"uv": self._uv_data[i]["uv"], "tris": self._uv_data[i]["tris"],
                  "flags": self._uv_data[i]["flags"], "heat": self._uv_heat_colors(i)} for i in idx]
        title = names[0] if (len(names) == 1 or 0 <= self.uv_part < len(self.actors)) else f"All parts ({len(names)})"
        c = self.uv_counts()
        if not self.actors:
            summary = "Open a model to see its UV layout."
        elif not self._uv_ready:
            summary = "Press “Run UV tests” in the UV tab of the Materials panel to analyse the UVs."
        elif not c["has_uv"]:
            summary = ("This part has no UV coordinates." if self.uv_part >= 0
                       else "This model has no UV coordinates.")
        else:
            bits = [f"{c['tris']:,} triangles"]
            bits += [f"{c[k]:,} {label.lower()}" for k, label, _t, _c in UV_TESTS if k in self.uv_tests]
            st = self.uv_heat_stats()
            if self.uv_heat == "density" and st["n"]:
                bits.append(f"{100.0 * st['low'] / st['n']:.1f}% low, {100.0 * st['high'] / st['n']:.1f}% high density")
            elif self.uv_heat == "stretch" and st["n"]:
                bits.append(f"{100.0 * st['bad'] / st['n']:.1f}% stretched past {self.uv_th['stretch']:g}")
            summary = "  ·  ".join(bits)
        backdrop = None
        if self.uv_backdrop_on:
            for i in idx:
                backdrop = self._uv_texture_image(self.actors[i])
                if backdrop is not None:
                    break
        legend = None
        if self.uv_heat == "density":
            lo, hi = self.uv_th["dens_low"], self.uv_th["dens_high"]
            legend = {"title": "Texel density (relative to the median)", "stops": _HEAT_STOPS,
                      "labels": [(0.0, f"≤ ×{lo:g}"), (0.5, "×1"), (1.0, f"≥ ×{hi:g}")]}
        elif self.uv_heat == "stretch":
            w = self.uv_th["stretch"]
            legend = {"title": "Stretch (1 = undistorted)", "stops": _STRETCH_STOPS,
                      "labels": [(0.0, "1"), (0.5, f"{(1 + w) / 2:g}"), (1.0, f"≥ {w:g}")]}
        self.uv_view.set_data(parts, sorted(self.uv_tests, key=[k for k, *_r in UV_TESTS].index),
                              backdrop, title, summary, legend)

    def _uv_texture_image(self, actor):
        tex = actor.GetTexture()
        if tex is None:
            return None
        key = id(tex)
        if key not in self._uv_tex_cache:
            arr = texture_to_array(tex, 1024)
            self._uv_tex_cache[key] = None if arr is None else _rgb_to_qimage(texture_channel_rgb(arr))
        return self._uv_tex_cache[key]

    def _uv_apply_heatmap(self):
        for i, a in enumerate(self.actors):
            d = self._uv_data[i] if i < len(self._uv_data) else None
            md = None
            if self.mesh_tests and self._mesh_data and i < len(self._mesh_data):
                md = self._mesh_data[i]
            src = d if d is not None else md
            if src is None or id(a) in self._uv_saved:
                continue
            try:
                m = a.GetMapper()
                pd = _mapper_data(m)
                flags = dict(d["flags"]) if d is not None else {}
                if md is not None:
                    flags.update(md["flags"])
                active = (list(self.uv_tests) if d is not None else []) + (list(self.mesh_tests) if md is not None else [])
                colors, _bad = uv_poly_colors(src["npoly"], src["parent"], flags, active,
                                              base=self._uv_heat_colors(i))
                full = np.tile(np.array(UV_COLOR_OK, np.uint8), (pd.GetNumberOfCells(), 1))
                full[src["first"]:src["first"] + src["npoly"]] = colors
                arr = numpy_support.numpy_to_vtk(np.ascontiguousarray(full), deep=True)
                arr.SetName("gk_uvdiag")
                cd = pd.GetCellData()
                self._uv_saved[id(a)] = {"actor": a, "m": m, "pd": pd, "old": cd.GetScalars(),
                                         "vis": m.GetScalarVisibility(), "smode": m.GetScalarMode(),
                                         "cmode": m.GetColorMode(), "tex": a.GetTexture()}
                cd.SetScalars(arr)
                m.SetScalarModeToUseCellData()
                m.SetColorModeToDirectScalars()
                m.ScalarVisibilityOn()
                a.SetTexture(None)                  # the heatmap replaces the texture while it is on
            except Exception:
                self._uv_saved.pop(id(a), None)

    def _uv_restore_heatmap(self):
        for st in list(self._uv_saved.values()):
            try:
                cd = st["pd"].GetCellData()
                cd.RemoveArray("gk_uvdiag")
                if st["old"] is not None:
                    cd.SetScalars(st["old"])
                m = st["m"]
                m.SetScalarVisibility(st["vis"])
                m.SetScalarMode(st["smode"])
                m.SetColorMode(st["cmode"])
                if st["tex"] is not None:
                    st["actor"].SetTexture(st["tex"])
            except Exception:
                pass
        self._uv_saved = {}

    def set_uv_view(self, on: bool):
        self.uv_on = bool(on)
        self.uv_view.setVisible(self.uv_on)
        if self.act_uv.isChecked() != self.uv_on:
            self.act_uv.blockSignals(True)
            self.act_uv.setChecked(self.uv_on)
            self.act_uv.blockSignals(False)
        if self.uv_on:
            tot = max(sum(self.view_split.sizes()), 2)
            self.view_split.setSizes([int(tot * 0.58), int(tot * 0.42)])
            self._uv_update_layout()
        self.uv_changed.emit()

    def toggle_uv_view(self):
        self.act_uv.toggle()

    def _uv_recolor(self):
        """Colours changed (a test or heatmap setting): redo the model colours and the layout."""
        self._uv_restore_heatmap()
        if self._uv_heat_active():
            self._uv_apply_heatmap()
        self._uv_update_layout()
        if self.actors:
            self.rw.Render()
        self.uv_changed.emit()
        self.mesh_changed.emit()

    def _uv_need_view(self):
        if self.mode != "surface":
            self.set_mode("surface")                # the heatmap shows in the shaded view
        if not self.uv_on:
            self.set_uv_view(True)

    def set_uv_test(self, key: str, on: bool):
        if on:
            self.uv_tests.add(key)
            self._uv_need_view()
        else:
            self.uv_tests.discard(key)
        self._uv_recolor()

    # ----- measurements: size / volume, point-to-point tool, cross-section ------------------
    def _world_parts(self) -> list:
        """[(world-space points, triangles)] for the visible parts."""
        return world_parts(self.actors)

    def measure_calculate(self):
        if not self.actors:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._measure_result = measure_model(self._world_parts()) or None
        finally:
            QApplication.restoreOverrideCursor()
        self.measure_changed.emit()

    def set_units(self, src: str, disp: str):
        keys = [k for k, _l, _f in UNITS]
        if src in keys:
            self.unit_src = src
            self.settings.setValue("measure_src", src)
        if disp in keys:
            self.unit_disp = disp
            self.settings.setValue("measure_disp", disp)
        self._measure_rebuild()
        self.measure_changed.emit()

    def _annot_visible(self, on: bool):
        for pr in self._meas_props:
            pr.SetVisibility(bool(on))
        for _a, _tr, cut in self._sec_items:
            cut.SetVisibility(bool(on) and bool(_a.GetVisibility()))

    # point-to-point tool
    def set_measure_mode(self, on: bool):
        self.measure_on = bool(on)
        if not self.measure_on:
            self._measure_clear()
        else:
            self.message.emit("Measure: click 2 or 3 points on the model (distance, then the angle at the middle point). "
                              "Drag still orbits. Shift+R to stop.")
        self.measure_changed.emit()

    def toggle_measure_mode(self):
        if not self.actors:
            self.message.emit("Open a model first")
            return
        self.set_measure_mode(not self.measure_on)

    def _measure_pick(self, x: float, y: float):
        vis = [a for a in self.actors if a.GetVisibility()]
        if not vis:
            return
        try:
            pk = vtkCellPicker()
            pk.SetTolerance(0.0005)
            pk.PickFromListOn()
            for a in vis:
                pk.AddPickList(a)
            dpr = self.vtk_widget.devicePixelRatioF()
            _w, h = self._view_px()
            ok = pk.Pick(x * dpr, h - y * dpr, 0, self.renderer)
            if not ok or pk.GetCellId() < 0:
                self.message.emit("No surface there: click on the model")
                return
            pos = np.array(pk.GetPickPosition(), float)
        except Exception:
            self.message.emit("That point could not be picked")
            return
        if len(self._meas_pts) >= 3:
            self._measure_clear(render=False)
        self._meas_pts.append(pos)
        self._measure_rebuild()
        self.measure_changed.emit()

    def measure_readout(self):
        """Raw numbers (model units) for the picked points, or None."""
        pts = self._meas_pts
        if not pts:
            return None
        out = {"n": len(pts)}
        if len(pts) >= 2:
            d = pts[1] - pts[0]
            out.update(ab=float(np.linalg.norm(d)), delta=d)
        if len(pts) == 3:
            out.update(bc=float(np.linalg.norm(pts[2] - pts[1])), angle=angle_at(pts[0], pts[1], pts[2]))
        return out

    def _measure_clear(self, render: bool = True):
        for pr in self._meas_props:
            self.renderer.RemoveViewProp(pr)
        self._meas_props = []
        self._meas_pts = []
        if render and self.actors:
            self.rw.Render()
            self.measure_changed.emit()

    def measure_clear_points(self):
        self._measure_clear()

    def _measure_rebuild(self):
        for pr in self._meas_props:
            self.renderer.RemoveViewProp(pr)
        self._meas_props = []
        pts = self._meas_pts
        if not pts or not self.actors:
            if self.actors:
                self.rw.Render()
            return
        lo, hi = self._model_bounds()
        rad = max(float(np.linalg.norm(np.asarray(hi) - np.asarray(lo))) * 0.007, 1e-9)
        cols = [(1.0, 0.55, 0.1), (0.1, 0.85, 0.95), (0.95, 0.3, 0.8)]
        for i, q in enumerate(pts):
            sp = vtkSphereSource()
            sp.SetCenter(*q)
            sp.SetRadius(rad)
            sp.SetThetaResolution(18)
            sp.SetPhiResolution(18)
            m = vtkPolyDataMapper()
            m.SetInputConnection(sp.GetOutputPort())
            a = vtkActor()
            a.SetMapper(m)
            a.GetProperty().SetColor(*cols[i])
            a.GetProperty().LightingOff()
            a.PickableOff()
            self.renderer.AddActor(a)
            self._meas_props.append(a)
        k = unit_scale(self.unit_src, self.unit_disp)
        for i in range(len(pts) - 1):
            ls = vtkLineSource()
            ls.SetPoint1(*pts[i])
            ls.SetPoint2(*pts[i + 1])
            m = vtkPolyDataMapper()
            m.SetInputConnection(ls.GetOutputPort())
            a = vtkActor()
            a.SetMapper(m)
            a.GetProperty().SetColor(1.0, 0.85, 0.1)
            a.GetProperty().SetLineWidth(2.5)
            a.GetProperty().LightingOff()
            a.PickableOff()
            self.renderer.AddActor(a)
            self._meas_props.append(a)
            if vtkBillboardTextActor3D is not None:
                try:
                    t = vtkBillboardTextActor3D()
                    t.SetInput(f"{fmt_num(float(np.linalg.norm(pts[i + 1] - pts[i])) * k)} {self.unit_disp}")
                    t.SetPosition(*((pts[i] + pts[i + 1]) / 2.0))
                    tp = t.GetTextProperty()
                    tp.SetFontSize(18)
                    tp.SetBold(True)
                    tp.SetColor(1.0, 0.95, 0.4)
                    tp.SetBackgroundColor(0.0, 0.0, 0.0)
                    tp.SetBackgroundOpacity(0.55)
                    t.PickableOff()
                    self.renderer.AddActor(t)
                    self._meas_props.append(t)
                except Exception:
                    pass
        r = self.measure_readout()
        if r and "ab" in r:
            txt = f"Distance {fmt_num(r['ab'] * k)} {self.unit_disp}"
            if "angle" in r:
                txt += f"  ·  angle {r['angle']:.1f}°"
            self.message.emit(txt)
        self.rw.Render()

    # cross-section: a clipping plane on every part plus a bright outline where the plane cuts
    def _section_clear(self):
        for a, _tr, cut in self._sec_items:
            self.renderer.RemoveActor(cut)
            try:
                a.GetMapper().RemoveAllClippingPlanes()
            except Exception:
                pass
        self._sec_items = []
        self._sec_plane = None

    def _section_apply(self):
        """Build (or tear down) the clipping and outline for the current settings."""
        self._section_clear()
        if not (self.section_on and self.actors):
            if self.actors:
                self.rw.Render()
            return
        self._sec_plane = vtkPlane()
        for a in self.actors:
            try:
                pd = _mapper_data(a.GetMapper())
                a.GetMapper().AddClippingPlane(self._sec_plane)
                tr = vtkTransform()
                tf = vtkTransformPolyDataFilter()
                tf.SetInputData(pd)
                tf.SetTransform(tr)
                cu = vtkCutter()
                cu.SetCutFunction(self._sec_plane)
                cu.SetInputConnection(tf.GetOutputPort())
                m = vtkPolyDataMapper()
                m.SetInputConnection(cu.GetOutputPort())
                m.ScalarVisibilityOff()
                cut = vtkActor()
                cut.SetMapper(m)
                cut.GetProperty().SetColor(1.0, 0.8, 0.1)
                cut.GetProperty().SetLineWidth(3.0)
                cut.GetProperty().LightingOff()
                cut.PickableOff()
                self.renderer.AddActor(cut)
                self._sec_items.append((a, tr, cut))
            except Exception:
                continue
        self._section_update()

    def _section_update(self):
        if self._sec_plane is None or not self.actors:
            return
        lo, hi = self._model_bounds()
        ax = self.section_axis
        o = (np.asarray(lo, float) + np.asarray(hi, float)) / 2.0
        o[ax] = lo[ax] + (hi[ax] - lo[ax]) * self.section_pos
        n = np.zeros(3)
        n[ax] = -1.0 if self.section_flip else 1.0
        self._sec_plane.SetOrigin(*o)
        self._sec_plane.SetNormal(*n)
        for a, tr, _cut in self._sec_items:
            try:
                a.ComputeMatrix()
                tr.SetMatrix(a.GetMatrix())
            except Exception:
                pass
        self._section_sync_vis()
        self.rw.Render()

    def _section_sync_vis(self):
        for a, _tr, cut in self._sec_items:
            cut.SetVisibility(bool(a.GetVisibility()))

    def set_section(self, on: bool):
        self.section_on = bool(on)
        self._section_apply()
        self.measure_changed.emit()

    def set_section_axis(self, ax: int):
        self.section_axis = max(0, min(2, int(ax)))
        self._section_update()

    def set_section_pos(self, frac: float):
        self.section_pos = min(1.0, max(0.0, float(frac)))
        self._section_update()

    def set_section_flip(self, on: bool):
        self.section_flip = bool(on)
        self._section_update()

    # ----- LOD / decimation preview ------------------------------------------------------------
    def _lod_reset(self):
        if self._lod_task is not None:
            self._lod_task.cancelled = True
        self._lod_task = None
        self._lod_token += 1
        self._lod_sets, self._lod_info, self._lod_level, self.lod_status = None, {}, 0, ""

    def lod_generate(self):
        if not self.actors or self._lod_task is not None:
            return
        inputs = []
        for a in self.actors:
            ds = getattr(a, "_lod_orig", None) or _mapper_data(a.GetMapper())
            if ds is not None and isinstance(ds, vtkPolyData):
                c = vtkPolyData()
                c.ShallowCopy(ds)                   # shared arrays, read-only: the worker never touches the live one
                inputs.append(c)
            else:
                inputs.append(None)
        if not any(i is not None for i in inputs):
            self.message.emit("There is no mesh data to simplify")
            return
        self._lod_token += 1
        task = LodTask(self._lod_token, inputs)
        task.signals.progress.connect(self._lod_progress)
        task.signals.done.connect(self._lod_done)
        task.signals.failed.connect(self._lod_failed)
        self._lod_task = task
        self.lod_status = "Simplifying …"
        self.lod_changed.emit()
        QThreadPool.globalInstance().start(task)

    def _lod_progress(self, text: str):
        if self._lod_task is not None:
            self.lod_status = text
            self.lod_changed.emit()

    def _lod_failed(self, token: int, msg: str):
        if token != self._lod_token:
            return
        self._lod_task = None
        self.lod_status = "Simplification failed: " + msg if msg != "cancelled" else ""
        self.lod_changed.emit()

    def _lod_done(self, token: int, results: dict):
        if token != self._lod_token:
            return                                   # a different model was opened meanwhile
        self._lod_task = None
        orig_t = orig_v = 0
        for a in self.actors:
            ds = getattr(a, "_lod_orig", None) or _mapper_data(a.GetMapper())
            if ds is not None:
                orig_t += _face_count(ds)
                orig_v += ds.GetNumberOfPoints()
        self._lod_orig_counts = (orig_t, orig_v)
        info = {}
        for lvl, outs in results.items():
            t = v = 0
            for a, o in zip(self.actors, outs):
                src = o if o is not None else (getattr(a, "_lod_orig", None) or _mapper_data(a.GetMapper()))
                if src is not None:
                    t += _face_count(src)
                    v += src.GetNumberOfPoints()
            info[lvl] = {"tris": t, "verts": v, "tcoords": all(
                o is None or o.GetPointData().GetTCoords() is not None or
                (getattr(a, "_lod_orig", None) or _mapper_data(a.GetMapper())).GetPointData().GetTCoords() is None
                for a, o in zip(self.actors, outs))}
        self._lod_sets, self._lod_info = results, info
        self.lod_status = "Done. Pick a level to preview."
        self.lod_changed.emit()

    def set_lod(self, level: int):
        """Show the original geometry (0) or a generated level (50, 25, 10)."""
        level = int(level)
        if not self.actors or (level != 0 and not (self._lod_sets and level in self._lod_sets)):
            return
        if level == self._lod_level:
            return
        self._uv_restore_heatmap()                  # colours live on the geometry that is about to change
        for i, a in enumerate(self.actors):
            m = a.GetMapper()
            if not hasattr(a, "_lod_orig"):
                ds = _mapper_data(m)
                if ds is None or not isinstance(ds, vtkPolyData):
                    continue
                a._lod_orig = ds
                a._lod_orig_faces = getattr(a, "_faces", None)
                a._lod_orig_verts = getattr(a, "_verts", None)
            new = None
            if level != 0:
                outs = self._lod_sets[level]
                new = outs[i] if i < len(outs) else None
            if new is None:
                m.SetInputData(a._lod_orig)
                a._faces, a._verts = a._lod_orig_faces, a._lod_orig_verts
            else:
                m.SetInputData(new)
                a._faces, a._verts = _face_count(new), new.GetNumberOfPoints()
        self._lod_level = level
        # everything measured on the old geometry no longer applies
        self.uv_tests, self.uv_heat = set(), "off"
        self.mesh_tests = set()
        self._mesh_stop()
        self._mesh_data = None
        self._measure_result = None
        self.uv_refresh()
        if self.section_on:
            self._section_apply()
        self._update_info()
        self.rw.Render()
        t = self._lod_info.get(level, {}).get("tris") if level else self._lod_orig_counts[0]
        self.message.emit(f"Showing {'the original' if level == 0 else f'the {level}% LOD'}"
                          + (f": {t:,} triangles" if t else ""))
        self.lod_changed.emit()
        self.mesh_changed.emit()
        self.measure_changed.emit()

    # ----- mesh integrity diagnostics ------------------------------------------------------
    def mesh_ensure(self):
        """Start the integrity analysis of every part (once per model). It runs in the background: the window stays
        usable and the Run button turns into Cancel until it finishes."""
        if self._mesh_data is not None or not self.actors or self._mesh_task is not None:
            return
        self._mesh_token += 1
        task = AnalysisTask(self._mesh_token, mesh_part_analysis, self._task_inputs(), "Analysing the mesh")
        task.signals.progress.connect(self._mesh_progress)
        task.signals.done.connect(self._mesh_done)
        task.signals.failed.connect(self._mesh_failed)
        self._mesh_task = task
        self.mesh_status = "Analysing the mesh …"
        self.mesh_changed.emit()
        QThreadPool.globalInstance().start(task)

    def mesh_run_or_cancel(self):
        if self._mesh_task is not None:
            self._mesh_task.cancelled = True
            self.mesh_status = "Cancelling …"
            self.mesh_changed.emit()
        else:
            self.mesh_ensure()

    def _mesh_stop(self):
        """Drop a running integrity analysis without waiting for it (a model was opened or the geometry changed)."""
        if self._mesh_task is not None:
            self._mesh_task.cancelled = True
        self._mesh_task = None
        self._mesh_token += 1
        self.mesh_status = ""

    def _mesh_failed(self, token: int, msg: str):
        if token != self._mesh_token:
            return
        self._mesh_task = None
        self.mesh_status = "" if msg == "cancelled" else "The mesh analysis failed: " + msg
        self.mesh_changed.emit()

    def _mesh_done(self, token: int, data: list):
        if token != self._mesh_token:
            return
        self._mesh_task = None
        self.mesh_status = ""
        self._mesh_data = data
        self.mesh_changed.emit()

    def mesh_summary(self) -> dict:
        """Totals over all parts for the Mesh tab (empty dict when nothing is analysed yet)."""
        return mesh_totals(self._mesh_data) if self._mesh_data else {}

    def _mesh_need_view(self):
        if self.mode != "surface":
            self.set_mode("surface")                # the colours show in the shaded view

    def set_mesh_test(self, key: str, on: bool):
        if on:
            if self._mesh_data is None:              # the tests need the analysis first (the checkboxes are off until then)
                self.mesh_ensure()
                return
            self.mesh_tests.add(key)
            self._mesh_need_view()
        else:
            self.mesh_tests.discard(key)
        self._uv_recolor()

    def set_uv_heat(self, mode: str):
        self.uv_heat = mode if mode in ("off", "density", "stretch") else "off"
        if self.uv_heat != "off":
            self._uv_need_view()
        self._uv_recolor()

    def set_uv_threshold(self, key: str, value: float):
        if key in self.uv_th:
            self.uv_th[key] = float(value)
            if self.uv_heat != "off":
                self._uv_recolor()

    def set_uv_part(self, idx: int):
        self.uv_part = int(idx)
        self._uv_update_layout()
        self.uv_changed.emit()

    def set_uv_backdrop(self, on: bool):
        self.uv_backdrop_on = bool(on)
        self._uv_update_layout()

    def set_uv_below(self, below: bool):
        self.view_split.setOrientation(Qt.Vertical if below else Qt.Horizontal)

    # ----- reference sheet for AI 3D tools ----------------------------------------------
    def open_reference_sheet_dialog(self):
        if not self.actors:
            self.message.emit("Open a model first")
            return
        if not [a for a in self.actors if a.GetVisibility()]:
            self.message.emit("All parts are hidden, so there is nothing to capture")
            return
        dlg = ReferenceSheetDialog(self.window(), self.settings)
        if dlg.exec() != QDialog.Accepted:
            return
        opt = dlg.values()
        for k, v in (("sheet_layout", opt["layout"]), ("sheet_bg", opt["bg"]), ("sheet_cell", opt["cell"]),
                     ("sheet_labels", "true" if opt["labels"] else "false"),
                     ("sheet_single", "true" if opt["single"] else "false")):
            self.settings.setValue(k, v)
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
        stem = Path(self.path).stem if self.path else "model"
        fn, _ = QFileDialog.getSaveFileName(self, "Save reference sheet",
                                            os.path.join(pics, f"{stem}_reference_sheet.png"), "PNG image (*.png)")
        if not fn:
            return
        if not fn.lower().endswith(".png"):
            fn += ".png"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sheet, cells = self.render_reference_sheet(opt)
        except Exception as e:
            sheet, cells = None, []
            self.message.emit(f"Could not render the reference sheet: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        if sheet is None:
            return
        ok = sheet.save(fn, "PNG")
        if ok and opt["single"]:
            base = fn[:-4]
            for label, img in cells:
                img.save(f"{base}_{label}.png", "PNG")
        self.message.emit(f"Saved reference sheet: {fn}" if ok else "Could not save the reference sheet")

    def render_reference_sheet(self, opt: dict):
        """Capture every view with temporary overrides, always restoring the viewer afterwards.
        Returns (sheet QImage, [(file label, cell QImage)])."""
        u, f, r = self._axes_vectors()
        views = sheet_views(opt["layout"], u, f, r)
        lo, hi = self._model_bounds()
        centre, half = sheet_framing(lo, hi, [v[2] for v in views], u)
        cell = int(opt["cell"])
        bg = next(c for k, _l, c in SHEET_BACKGROUNDS if k == opt["bg"])

        cam = self.renderer.GetActiveCamera()
        saved = {"cam": (cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetViewAngle(),
                         cam.GetParallelProjection(), cam.GetParallelScale()),
                 "env": copy.deepcopy(self.env), "mode": self.mode, "split": self.split_on,
                 "edges": self.edges_on, "grid": self.grid_on,
                 "axes": self._axes_widget is not None and self.axes_on,
                 "orbit": self._orbit_timer.isActive()}
        self._orbit_timer.stop()
        if saved["axes"]:
            self._axes_widget.SetEnabled(0)
        self._annot_visible(False)                         # measurement marks and section outline stay out of the sheet
        cells = []
        try:
            # --- temporary scene: flat light, no sky/grid/edges/shadow, solid background, orthographic
            self.split_on = False
            self.edges_on = False
            self.grid_on = False
            self.env = clean_env({**saved["env"], **SHEET_ENV})
            self._env_refresh()
            self.set_mode("surface", force=True)           # shaded look, with the flat environment lighting
            self._sync_ground()
            self.renderer.SetBackground(*bg)
            self.renderer.SetBackground2(*bg)
            self.renderer.SetGradientBackground(False)

            cam.SetParallelProjection(True)
            wpx, hpx = self._view_px()
            side = max(1, min(wpx, hpx))
            aspect = wpx / float(hpx)
            cam.SetParallelScale(half if aspect >= 1.0 else half / aspect)   # the square cell is exactly `half` wide
            scale = max(1, min(4, int(math.ceil(cell / float(side)))))
            dist = half * 6.0 + float(np.linalg.norm(np.asarray(hi) - np.asarray(lo)))
            for label, _caption, d in views:
                cam.SetFocalPoint(*centre)
                cam.SetPosition(*(centre + np.asarray(d, float) * dist))
                cam.SetViewUp(*u)
                self.renderer.ResetCameraClippingRange()
                arr, _s = self._grab_pass(bg, scale)
                if arr is None:
                    raise RuntimeError("the viewport could not be captured")
                h, w, _ = arr.shape
                sq = min(h, w)
                y0, x0 = (h - sq) // 2, (w - sq) // 2
                crop = np.ascontiguousarray(arr[y0:y0 + sq, x0:x0 + sq])
                img = QImage(crop.data, sq, sq, 3 * sq, QImage.Format_RGB888).copy()
                if sq != cell:
                    img = img.scaled(cell, cell, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                cells.append((label, img))
        finally:
            # --- put everything back
            cam.SetPosition(*saved["cam"][0])
            cam.SetFocalPoint(*saved["cam"][1])
            cam.SetViewUp(*saved["cam"][2])
            cam.SetViewAngle(saved["cam"][3])
            cam.SetParallelProjection(bool(saved["cam"][4]))
            cam.SetParallelScale(saved["cam"][5])
            self.env = saved["env"]
            self.split_on = saved["split"]
            self.edges_on = saved["edges"]
            self.grid_on = saved["grid"]
            self._env_refresh()
            self.set_mode(saved["mode"], force=True)
            self._sync_ground()
            if self._bg_from_env:
                self._sync_background()
            else:
                self.set_background(self.bg_idx, announce=False)
            if saved["axes"]:
                self._axes_widget.SetEnabled(1)
            self._annot_visible(True)
            self.renderer.ResetCameraClippingRange()
            if saved["orbit"]:
                self._orbit_timer.start(20)
            self.rw.Render()

        sheet = QImage(cell * len(cells), cell, QImage.Format_RGB888)
        sheet.fill(QColor.fromRgbF(*bg))
        p = QPainter(sheet)
        for i, (label, img) in enumerate(cells):
            p.drawImage(i * cell, 0, img)
        if opt.get("labels"):
            p.setPen(QColor(60, 60, 60) if sum(bg) > 2.0 else QColor(235, 235, 235))
            fnt = QFont()
            fnt.setPixelSize(max(12, cell // 40))
            p.setFont(fnt)
            for i, (label, _caption, _d) in enumerate(views):
                p.drawText(i * cell + cell // 40, cell - cell // 40, _caption)
        p.end()
        return sheet, cells

    # ----- screenshots ------------------------------------------------------
    def _grab_pass(self, background, scale: int):
        """One capture of the render window. background=None keeps what the viewer shows;
        a colour tuple temporarily replaces it with a flat colour (no sky, no gradient)."""
        if background is not None:
            self.renderer.SetBackground(*background)
            self.renderer.SetBackground2(*background)
            self.renderer.SetGradientBackground(False)
            if self._sky_added:
                self.renderer.RemoveActor(self._skybox)
        self.rw.Render()
        for s in [x for x in dict.fromkeys([scale, 2, 1]) if x <= scale]:
            try:
                w2i = vtkWindowToImageFilter()
                w2i.SetInput(self.rw)
                w2i.SetScale(s)
                w2i.SetInputBufferTypeToRGB()
                w2i.ReadFrontBufferOff()
                w2i.Update()
                vimg = w2i.GetOutput()
                w, h, _ = vimg.GetDimensions()
                if w == 0 or h == 0:
                    continue
                arr = numpy_support.vtk_to_numpy(vimg.GetPointData().GetScalars())
                return np.ascontiguousarray(arr.reshape(h, w, 3)[::-1]), s
            except Exception:
                continue
        return None, scale

    def grab_image(self):
        if not self.actors:
            return None
        scale = int(self.shot_scale)
        axes_were_on = self._axes_widget is not None and self.axes_on
        if axes_were_on:
            self._axes_widget.SetEnabled(0)               # clean shot without the gizmo
        # Enlarged captures are rendered in tiles, which would shift the split's screen positions,
        # so those shots show the plain MatCap. At 1x the split is captured as you see it.
        split_paused = scale > 1 and self._split_visible()
        if split_paused:
            self.split_on = False
            self.set_mode("matcap", force=True)
            self.message.emit("Screenshot taken without the split (use screenshot scale 1x to include it)")
        try:
            if self.shot_transparent:
                black, s = self._grab_pass((0.0, 0.0, 0.0), scale)
                white, _ = self._grab_pass((1.0, 1.0, 1.0), s) if black is not None else (None, s)
                if black is None or white is None or black.shape != white.shape:
                    return None
                rgba = matte_rgba(black, white)
                h, w, _ = rgba.shape
                return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
            arr, _s = self._grab_pass(None, scale)
            if arr is None:
                return None
            h, w, _ = arr.shape
            return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        finally:
            if split_paused:
                self.split_on = True
                self.set_mode("matcap", force=True)
            if self._sky_added:
                self.renderer.AddActor(self._skybox)
            if self._bg_from_env:
                self._sync_background()
            else:
                self.set_background(self.bg_idx, announce=False)
            if axes_were_on:
                self._axes_widget.SetEnabled(1)
            self.rw.Render()

    def save_screenshot(self):
        img = self.grab_image()
        if img is None:
            self.message.emit("Nothing to capture yet")
            return
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
        stem = Path(self.path).stem if self.path else "screenshot"
        fn, _ = QFileDialog.getSaveFileName(self, "Save screenshot",
                                            os.path.join(pics, f"{stem}.png"), "PNG image (*.png)")
        if fn:
            if not fn.lower().endswith(".png"):
                fn += ".png"
            ok = img.save(fn, "PNG")
            self.message.emit(f"Saved {fn}" if ok else "Could not save the screenshot")

    def copy_screenshot(self):
        img = self.grab_image()
        if img is None:
            self.message.emit("Nothing to capture yet")
            return
        QApplication.clipboard().setImage(img)
        self.message.emit("Screenshot copied to clipboard")

    def shutdown(self):
        self._uv_stop()
        self._mesh_stop()
        self._orbit_timer.stop()
        self.vtk_widget.Finalize()
