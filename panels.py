"""Gleek3Deek side panels and dialogs: materials and parts (textures, UV, mesh, measure, LOD), model info, scene and display options, export."""
from __future__ import annotations

import html
import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QPushButton, QSlider, QTabWidget)
from PySide6.QtWidgets import QScrollArea, QDoubleSpinBox
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from formats import _cells, human_size
from analysis import (
    EXPORT_FORMATS, LOD_LEVELS, MESH_TESTS, UNITS, UV_HEAT_DEFAULTS, UV_HEAT_MODES, UV_ISLAND_TESTS,
    UV_TESTS, _fmt_len, collect_textures, fmt_num, material_summary, texture_channel_rgb, texture_facts,
    texture_fingerprint, texture_to_array, unit_scale)


class InfoPanel(QFrame):
    """Small read-only card of facts about the open model (native child, like the HUD)."""
    ROWS = [("format", "Format"), ("size", "File size"), ("parts", "Parts"), ("verts", "Vertices"),
            ("faces", "Faces"), ("x", "Width (X)"), ("y", "Height (Y)"), ("z", "Depth (Z)"),
            ("mats", "Materials"), ("texs", "Textures"), ("has", "Has")]

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setObjectName("hud")
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("infoTitle")
        grid.addWidget(self.title, 0, 0, 1, 2)
        self._keys: dict = {}
        self._vals: dict = {}
        for i, (key, label) in enumerate(self.ROWS, 1):
            k, v = QLabel(label), QLabel("")
            k.setObjectName("infoKey")
            v.setObjectName("infoVal")
            grid.addWidget(k, i, 0)
            grid.addWidget(v, i, 1)
            self._keys[key], self._vals[key] = k, v
        note = QLabel("Sizes are in the file's own units.")
        note.setObjectName("infoKey")
        grid.addWidget(note, len(self.ROWS) + 1, 0, 1, 2)

    def set_info(self, d: dict):
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(d["name"], Qt.ElideMiddle, 260))
        self.title.setToolTip(d["name"])
        v = self._vals
        v["format"].setText(d["format"])
        v["size"].setText(d["size"])
        v["parts"].setText(f"{d['parts']:,}" + (f"  ({d['hidden']} hidden)" if d.get("hidden") else ""))
        v["verts"].setText(f"{d['verts']:,}")
        v["faces"].setText(f"{d['faces']:,}" + (f"  ({d['tris']:,} triangles)" if d["tris"] != d["faces"] else ""))
        names = ("Width (X)", "Height (Y)", "Depth (Z)") if d["up"] != "Z" else ("Width (X)", "Depth (Y)", "Height (Z)")
        for i, key in enumerate(("x", "y", "z")):
            self._keys[key].setText(names[i])
            v[key].setText(_fmt_len(d["dims"][i]) if d["dims"] else "—")
        v["mats"].setText("none (plain mesh)" if d["mats"] is None else f"{d['mats']:,}")
        v["texs"].setText(f"{d['texs']:,}")
        extras = [n for n, on in (("vertex colours", d["colors"]), ("UV coordinates", d["uvs"])) if on]
        v["has"].setText(", ".join(extras) if extras else "—")
        self.adjustSize()


class ExportDialog(QDialog):
    def __init__(self, parent, name: str, tris: int, fmt_idx: int, simplify: bool, keep_pct: int):
        super().__init__(parent)
        self.setWindowTitle("Export / convert")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.tris = tris
        root = QVBoxLayout(self)
        root.setSpacing(10)
        head = QLabel(f"<b>{html.escape(name)}</b><br>{tris:,} triangles")
        head.setTextFormat(Qt.RichText)
        root.addWidget(head)
        form = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.addItems([f[0] for f in EXPORT_FORMATS])
        self.fmt.setCurrentIndex(max(0, min(fmt_idx, len(EXPORT_FORMATS) - 1)))
        form.addRow("Format", self.fmt)
        root.addLayout(form)
        self.simp = QCheckBox("Simplify mesh (reduce the number of faces)")
        self.simp.setChecked(simplify)
        self.simp.toggled.connect(self._refresh)
        root.addWidget(self.simp)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(max(1, min(keep_pct, 100)))
        self.slider.valueChanged.connect(self._refresh)
        self.keep_label = QLabel("")
        self.keep_label.setMinimumWidth(190)
        row.addWidget(self.slider, 1)
        row.addWidget(self.keep_label)
        root.addLayout(row)
        self.warn = QLabel("")
        self.warn.setObjectName("barLabel")
        self.warn.setWordWrap(True)
        root.addWidget(self.warn)
        note = QLabel("Exports the geometry as it is shown, including its placement; hidden parts are left out. "
                      "Materials and textures are not written; vertex colours are kept in PLY files.")
        note.setObjectName("barLabel")
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        go = QPushButton("Export…")
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        root.addLayout(buttons)
        self._refresh()

    def _refresh(self, *_):
        on, pct = self.simp.isChecked(), self.slider.value()
        self.slider.setEnabled(on)
        self.keep_label.setText(f"Keep {pct}%  (about {int(self.tris * pct / 100):,} triangles)"
                                if on else "Keeps every face")
        msgs = []
        if on and self.tris > 500_000:
            msgs.append("This is a large model, so simplifying may take a while.")
        if on and pct < 10:
            msgs.append("Very strong simplification can change the shape noticeably.")
        self.warn.setText(" ".join(msgs))

    def values(self):
        """(format index, fraction of faces to keep or None)."""
        return self.fmt.currentIndex(), (self.slider.value() / 100.0 if self.simp.isChecked() else None)


SHOT_SCALES = [1, 2, 4]


class ScenePanel(QWidget):
    """Floating panel for ground, camera, display and screenshot options. It talks to the
    viewer directly; every control has a matching menu item or key as well."""

    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self.setWindowTitle("Scene")
        self.setMinimumWidth(300)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        def heading(text):
            lab = QLabel(text)
            lab.setObjectName("aboutHeading")
            root.addWidget(lab)

        heading("Ground")
        self.grid_cb = QCheckBox("Ground grid  (G)")
        self.grid_cb.toggled.connect(viewer.act_grid.setChecked)
        root.addWidget(self.grid_cb)
        row = QHBoxLayout()
        for text, fn in (("Move to ground", viewer.move_to_ground), ("Move to origin", viewer.move_to_origin),
                         ("Reset position", viewer.reset_position)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        root.addLayout(row)
        note = QLabel("The grid sits at the model's lowest point. Moving the model changes where it "
                      "sits in the world, and in files you export.")
        note.setObjectName("barLabel")
        note.setWordWrap(True)
        root.addWidget(note)

        heading("Camera")
        row = QHBoxLayout()
        row.addWidget(QLabel("Field of view"))
        self.fov = QSlider(Qt.Horizontal)
        self.fov.setRange(10, 90)
        self.fov.valueChanged.connect(self._fov_changed)
        self.fov_label = QLabel("")
        self.fov_label.setFixedWidth(40)
        row.addWidget(self.fov, 1)
        row.addWidget(self.fov_label)
        root.addLayout(row)
        self.turn_cb = QCheckBox("Lock horizon: turntable rotation  (H)")
        self.turn_cb.toggled.connect(viewer.act_turntable.setChecked)
        root.addWidget(self.turn_cb)
        row = QHBoxLayout()
        self.ortho_cb = QCheckBox("Orthographic  (C)")
        self.ortho_cb.toggled.connect(viewer.act_ortho.setChecked)
        row.addWidget(self.ortho_cb)
        fit = QPushButton("Fit view  (F)")
        fit.clicked.connect(viewer.fit_view)
        row.addWidget(fit)
        root.addLayout(row)
        grid = QGridLayout()
        grid.addWidget(QLabel("Saved views"), 0, 0)
        for n in (1, 2, 3):
            save, go = QPushButton(f"Save {n}"), QPushButton(f"Go {n}")
            save.setToolTip(f"Ctrl+Shift+{n}")
            go.setToolTip(f"Alt+{n}")
            save.clicked.connect(lambda _=False, n=n: viewer.save_bookmark(n))
            go.clicked.connect(lambda _=False, n=n: viewer.go_bookmark(n))
            grid.addWidget(save, 1, n - 1)
            grid.addWidget(go, 2, n - 1)
        root.addLayout(grid)

        heading("Display")
        self.edges_cb = QCheckBox("Edges over shaded  (Shift+W)")
        self.edges_cb.toggled.connect(viewer.act_edges.setChecked)
        root.addWidget(self.edges_cb)

        heading("Screenshot")
        row = QHBoxLayout()
        row.addWidget(QLabel("Size"))
        self.scale_box = QComboBox()
        self.scale_box.addItems(["1×  (window size)", "2×", "4×"])
        self.scale_box.currentIndexChanged.connect(self._scale_changed)
        row.addWidget(self.scale_box, 1)
        self.trans_cb = QCheckBox("Transparent background")
        self.trans_cb.toggled.connect(self._trans_changed)
        row.addWidget(self.trans_cb)
        root.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Save screenshot…  (F12)", viewer.save_screenshot),
                         ("Copy to clipboard  (Ctrl+C)", viewer.copy_screenshot)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        root.addLayout(row)

        root.addStretch(1)
        for act in (viewer.act_grid, viewer.act_edges, viewer.act_ortho, viewer.act_turntable):
            act.toggled.connect(self.sync)             # keep in step when a key is used instead
        self.sync()

    def showEvent(self, e):
        self.sync()
        super().showEvent(e)

    def sync(self, *_):
        v = self.viewer
        for cb, on in ((self.grid_cb, v.grid_on), (self.edges_cb, v.edges_on),
                       (self.ortho_cb, v.act_ortho.isChecked()), (self.trans_cb, v.shot_transparent),
                       (self.turn_cb, v.turntable)):
            cb.blockSignals(True)
            cb.setChecked(bool(on))
            cb.blockSignals(False)
        self.fov.blockSignals(True)
        self.fov.setValue(int(round(v.fov)))
        self.fov.blockSignals(False)
        self.fov_label.setText(f"{int(round(v.fov))}°")
        self.scale_box.blockSignals(True)
        self.scale_box.setCurrentIndex(SHOT_SCALES.index(v.shot_scale) if v.shot_scale in SHOT_SCALES else 1)
        self.scale_box.blockSignals(False)

    def _fov_changed(self, deg: int):
        self.fov_label.setText(f"{deg}°")
        self.viewer.set_fov(deg)

    def _scale_changed(self, idx: int):
        self.viewer.shot_scale = SHOT_SCALES[idx]
        self.viewer.settings.setValue("shot_scale", self.viewer.shot_scale)

    def _trans_changed(self, on: bool):
        self.viewer.shot_transparent = bool(on)
        self.viewer.settings.setValue("shot_transparent", "true" if on else "false")


VIEW_CHANNELS = [("surface", "Shaded"), ("albedo", "Albedo (no lighting)"),
                 ("normals", "Normals (red = back faces)")]


def _rgb_to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class TexturePreview(QDialog):
    """Large preview of one texture, with buttons to look at a single colour channel."""

    def __init__(self, parent, title: str, arr: np.ndarray, subtitle: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.arr = arr
        root = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(360, 360)
        root.addWidget(self.view, 1)
        row = QHBoxLayout()
        for ch, label in (("rgb", "RGB"), ("r", "R"), ("g", "G"), ("b", "B"), ("a", "A")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, c=ch: self._show(c))
            row.addWidget(b)
        root.addLayout(row)
        sub = QLabel(subtitle)
        sub.setObjectName("barLabel")
        sub.setWordWrap(True)
        root.addWidget(sub)
        self._show("rgb")

    def _show(self, channel: str):
        pm = QPixmap.fromImage(_rgb_to_qimage(texture_channel_rgb(self.arr, channel)))
        self.view.setPixmap(pm.scaled(720, 720, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class MaterialsPanel(QWidget):
    """Floating panel: pick a material view, hide or isolate parts, inspect textures."""

    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self._textures: list = []
        self.setWindowTitle("Materials & parts")
        self.setMinimumSize(300, 300)
        root = QVBoxLayout(self)
        root.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("View"))
        self.view_box = QComboBox()
        self.view_box.addItems([label for _k, label in VIEW_CHANNELS])
        self.view_box.currentIndexChanged.connect(lambda i: viewer.set_view_channel(VIEW_CHANNELS[i][0]))
        row.addWidget(self.view_box, 1)
        root.addLayout(row)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.parts = QListWidget()
        self.parts.itemChanged.connect(self._part_toggled)
        self.parts.currentRowChanged.connect(viewer.highlight_part)
        pl.addWidget(self.parts, 1)
        row = QHBoxLayout()
        for text, fn in (("Show all", self._show_all), ("Invert", self._invert), ("Isolate selected", self._isolate)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        pl.addLayout(row)
        hint = QLabel("Untick a part to hide it. Selecting a part outlines it in the view. "
                      "Hidden parts are left out of exports.")
        hint.setObjectName("barLabel")
        hint.setWordWrap(True)
        pl.addWidget(hint)
        self.tabs.addTab(pw, "Parts")

        tw = QWidget()
        tl = QVBoxLayout(tw)
        self.tex_list = QListWidget()
        self.tex_list.setIconSize(QSize(64, 64))
        self.tex_list.itemDoubleClicked.connect(self._open_texture)
        tl.addWidget(self.tex_list, 1)
        self.tex_total = QLabel("")
        self.tex_total.setWordWrap(True)
        tl.addWidget(self.tex_total)
        thint = QLabel("Double-click a texture to preview it and look at its channels. Memory figures are "
                       "estimates for a graphics card: 3-channel images are stored as 4, and mipmaps add a "
                       "third. “Compressed” assumes a typical block format (BC7). Colour space is inferred "
                       "from the texture's role, because image pixels do not say which they are.")
        thint.setObjectName("barLabel")
        thint.setWordWrap(True)
        tl.addWidget(thint)
        self.tabs.addTab(tw, "Textures")

        uw = QWidget()
        ul = QVBoxLayout(uw)
        self.uv_show = QCheckBox("Show the UV layout beside the model  (Shift+U)")
        self.uv_show.toggled.connect(viewer.set_uv_view)
        ul.addWidget(self.uv_show)
        self.uv_run = QPushButton("Run UV tests")
        self.uv_run.setToolTip("Analyse the UVs (tests, islands, texel density and stretch). This is not done "
                               "automatically, so models open quickly.")
        self.uv_run.clicked.connect(lambda: viewer.uv_ensure())
        ul.addWidget(self.uv_run)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Part"))
        self.uv_part_box = QComboBox()
        self.uv_part_box.currentIndexChanged.connect(lambda i: viewer.set_uv_part(i - 1))
        prow.addWidget(self.uv_part_box, 1)
        ul.addLayout(prow)
        hrow = QHBoxLayout()
        hrow.addWidget(QLabel("Heatmap"))
        self.uv_heat_box = QComboBox()
        for key, label in UV_HEAT_MODES:
            self.uv_heat_box.addItem(label, key)
        self.uv_heat_box.setToolTip("Texel density: how much texture resolution each part of the surface gets, "
                                    "relative to the model's median. Stretch: how much the UVs distort the "
                                    "surface (1 = none; scale and rotation do not count).")
        self.uv_heat_box.currentIndexChanged.connect(lambda _i: viewer.set_uv_heat(self.uv_heat_box.currentData()))
        hrow.addWidget(self.uv_heat_box, 1)
        ul.addLayout(hrow)
        self.uv_spins = {}
        for key, label, lo, hi, step, tip in (
                ("dens_low", "Density is too low below ×", 0.05, 0.95, 0.05, "Triangles with less than this share of the median density turn blue"),
                ("dens_high", "Density is too high above ×", 1.05, 20.0, 0.25, "Triangles with more than this multiple of the median density turn red"),
                ("stretch", "Stretch warning above", 1.05, 20.0, 0.1, "Triangles distorted more than this turn red (1 = undistorted)")):
            r = QHBoxLayout()
            r.addWidget(QLabel(label))
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(2)
            sp.setValue(UV_HEAT_DEFAULTS[key])
            sp.setToolTip(tip)
            sp.valueChanged.connect(lambda val, k=key: viewer.set_uv_threshold(k, val))
            r.addStretch(1)
            r.addWidget(sp)
            ul.addLayout(r)
            self.uv_spins[key] = sp
        self.uv_heat_stats = QLabel("")
        self.uv_heat_stats.setObjectName("barLabel")
        self.uv_heat_stats.setWordWrap(True)
        ul.addWidget(self.uv_heat_stats)
        ul.addWidget(QLabel("Tests (they colour the model and the layout)"))
        self.uv_checks, self.uv_count_labels = {}, {}
        for key, label, tip, col in UV_TESTS:
            row = QHBoxLayout()
            sw = QLabel()
            pix = QPixmap(14, 14)
            pix.fill(QColor(*col))
            sw.setPixmap(pix)
            cb = QCheckBox(label)
            cb.setToolTip(tip)
            cb.toggled.connect(lambda on, k=key: viewer.set_uv_test(k, on))
            cnt = QLabel("")
            cnt.setObjectName("barLabel")
            row.addWidget(sw)
            row.addWidget(cb, 1)
            row.addWidget(cnt)
            ul.addLayout(row)
            self.uv_checks[key], self.uv_count_labels[key] = cb, cnt
        self.uv_tex_cb = QCheckBox("Show the texture behind the layout")
        self.uv_tex_cb.setChecked(True)
        self.uv_tex_cb.toggled.connect(viewer.set_uv_backdrop)
        self.uv_below_cb = QCheckBox("Put the layout below the model instead of beside it")
        self.uv_below_cb.toggled.connect(viewer.set_uv_below)
        ul.addWidget(self.uv_tex_cb)
        ul.addWidget(self.uv_below_cb)
        self.uv_note = QLabel("")
        self.uv_note.setObjectName("barLabel")
        self.uv_note.setWordWrap(True)
        ul.addWidget(self.uv_note)
        uhint = QLabel("In the layout: mouse wheel zooms, drag pans, double-click fits. Grey is fine; a test colour "
                       "marks a failing triangle, and magenta means it fails more than one. “Flipped” means the "
                       "opposite winding to most of the model, so a deliberately mirrored half is reported too.")
        uhint.setObjectName("barLabel")
        uhint.setWordWrap(True)
        ul.addWidget(uhint)
        ul.addStretch(1)
        self.tabs.addTab(uw, "UV")

        mw = QWidget()
        ml = QVBoxLayout(mw)
        self.mesh_stats = QLabel("")
        self.mesh_stats.setWordWrap(True)
        self.mesh_stats.setTextFormat(Qt.RichText)
        self.mesh_stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ml.addWidget(self.mesh_stats)
        self.mesh_run = QPushButton("Run integrity tests")
        self.mesh_run.setToolTip("Analyse the geometry for holes, bad edges, flipped faces and more. "
                                 "This is not done automatically, so models open quickly.")
        self.mesh_run.clicked.connect(lambda: viewer.mesh_ensure())
        ml.addWidget(self.mesh_run)
        ml.addWidget(QLabel("Integrity tests (they colour the model)"))
        self.mesh_checks, self.mesh_count_labels = {}, {}
        for key, label, tip, col in MESH_TESTS:
            row = QHBoxLayout()
            sw = QLabel()
            pix = QPixmap(14, 14)
            pix.fill(QColor(*col))
            sw.setPixmap(pix)
            cb = QCheckBox(label)
            cb.setToolTip(tip)
            cb.toggled.connect(lambda on, k=key: viewer.set_mesh_test(k, on))
            cnt = QLabel("")
            cnt.setObjectName("barLabel")
            row.addWidget(sw)
            row.addWidget(cb, 1)
            row.addWidget(cnt)
            ml.addLayout(row)
            self.mesh_checks[key], self.mesh_count_labels[key] = cb, cnt
        self.mesh_note = QLabel("")
        self.mesh_note.setObjectName("barLabel")
        self.mesh_note.setWordWrap(True)
        ml.addWidget(self.mesh_note)
        mhint = QLabel("Counts are triangles. Vertices at the same position count as joined, so seams made for "
                       "UVs or hard edges are not reported as holes. Failing triangles are coloured, grey is fine, "
                       "white fails more than one test. A colour test replaces the texture on the model while it is on.")
        mhint.setObjectName("barLabel")
        mhint.setWordWrap(True)
        ml.addWidget(mhint)
        ml.addStretch(1)
        self._mesh_tab = self.tabs.addTab(mw, "Mesh")

        # ---- Measure tab: size and volume, point-to-point tool, cross-section
        ms_inner = QWidget()
        sl = QVBoxLayout(ms_inner)
        urow = QHBoxLayout()
        urow.addWidget(QLabel("Model units"))
        self.ms_src = QComboBox()
        self.ms_disp = QComboBox()
        for k, label, _f in UNITS:
            self.ms_src.addItem(f"{label} ({k})", k)
            self.ms_disp.addItem(f"{label} ({k})", k)
        self.ms_src.setToolTip("What one unit in the file means. Most formats do not say: glTF/GLB is metres by "
                               "convention, STL and OBJ files are often millimetres.")
        self.ms_disp.setToolTip("The unit the results are shown in")
        urow.addWidget(self.ms_src, 1)
        urow.addWidget(QLabel("show in"))
        urow.addWidget(self.ms_disp, 1)
        sl.addLayout(urow)
        self.ms_src.currentIndexChanged.connect(lambda _i: viewer.set_units(self.ms_src.currentData(), self.ms_disp.currentData()))
        self.ms_disp.currentIndexChanged.connect(lambda _i: viewer.set_units(self.ms_src.currentData(), self.ms_disp.currentData()))
        self.ms_calc = QPushButton("Calculate size, volume and centre of mass")
        self.ms_calc.setToolTip("Measures the visible parts. Not done automatically, so models open quickly.")
        self.ms_calc.clicked.connect(lambda: viewer.measure_calculate())
        sl.addWidget(self.ms_calc)
        self.ms_result = QLabel("")
        self.ms_result.setWordWrap(True)
        self.ms_result.setTextFormat(Qt.RichText)
        self.ms_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.ms_result)

        sl.addWidget(QLabel("Measure between points"))
        self.ms_mode = QCheckBox("Measure mode  (Shift+R): click 2 or 3 points on the model")
        self.ms_mode.toggled.connect(viewer.set_measure_mode)
        sl.addWidget(self.ms_mode)
        self.ms_clear = QPushButton("Clear points")
        self.ms_clear.clicked.connect(lambda: viewer.measure_clear_points())
        sl.addWidget(self.ms_clear)
        self.ms_readout = QLabel("")
        self.ms_readout.setWordWrap(True)
        self.ms_readout.setTextFormat(Qt.RichText)
        sl.addWidget(self.ms_readout)

        sl.addWidget(QLabel("Cross-section"))
        self.sec_on = QCheckBox("Cut the model with a plane")
        self.sec_on.toggled.connect(viewer.set_section)
        sl.addWidget(self.sec_on)
        srow = QHBoxLayout()
        self.sec_axis = QComboBox()
        self.sec_axis.addItems(["X", "Y", "Z"])
        self.sec_axis.setCurrentIndex(viewer.section_axis)
        self.sec_axis.currentIndexChanged.connect(viewer.set_section_axis)
        srow.addWidget(QLabel("Axis"))
        srow.addWidget(self.sec_axis)
        self.sec_slider = QSlider(Qt.Horizontal)
        self.sec_slider.setRange(0, 1000)
        self.sec_slider.setValue(int(viewer.section_pos * 1000))
        self.sec_slider.valueChanged.connect(lambda v: viewer.set_section_pos(v / 1000.0))
        srow.addWidget(self.sec_slider, 1)
        sl.addLayout(srow)
        self.sec_flip = QCheckBox("Keep the other side")
        self.sec_flip.toggled.connect(viewer.set_section_flip)
        sl.addWidget(self.sec_flip)
        mshint = QLabel("Size and volume use the parts that are visible. Volume and the centre of mass need closed "
                        "parts; open parts are left out of the volume (the Mesh tab shows which are open). The "
                        "oriented box is the smallest box, turned to fit, that holds the model. Measure mode: a click "
                        "that does not move picks a point; dragging still orbits. The cross-section hides one side "
                        "of the plane and outlines the cut in yellow; it is left out of reference sheets.")
        mshint.setObjectName("barLabel")
        mshint.setWordWrap(True)
        sl.addWidget(mshint)
        sl.addStretch(1)
        msa = QScrollArea()
        msa.setWidgetResizable(True)
        msa.setFrameShape(QFrame.NoFrame)
        msa.setWidget(ms_inner)
        self.tabs.addTab(msa, "Measure")

        lw = QWidget()
        ll = QVBoxLayout(lw)
        intro = QLabel("Preview how the model looks with fewer triangles. Levels are made from the original, one "
                       "part at a time, in the background.")
        intro.setWordWrap(True)
        ll.addWidget(intro)
        self.lod_btn = QPushButton("Generate LOD previews (50%, 25%, 10%)")
        self.lod_btn.setToolTip("Not done automatically: simplifying a large model takes a while")
        self.lod_btn.clicked.connect(lambda: viewer.lod_generate())
        ll.addWidget(self.lod_btn)
        self.lod_state = QLabel("")
        self.lod_state.setWordWrap(True)
        self.lod_state.setObjectName("barLabel")
        ll.addWidget(self.lod_state)
        lrow = QHBoxLayout()
        lrow.addWidget(QLabel("Show"))
        self.lod_box = QComboBox()
        self.lod_box.currentIndexChanged.connect(lambda _i: viewer.set_lod(self.lod_box.currentData() or 0))
        lrow.addWidget(self.lod_box, 1)
        ll.addLayout(lrow)
        self.lod_table = QLabel("")
        self.lod_table.setWordWrap(True)
        self.lod_table.setTextFormat(Qt.RichText)
        ll.addWidget(self.lod_table)
        lhint = QLabel("A level shows the model as it would look after simplifying; it does not change your file. "
                       "Texture seams are kept as borders, so UVs hold up, but very low levels can still stretch "
                       "textures. Exports always use the original geometry. Switching level clears the UV, mesh and "
                       "measurement results, because they describe the geometry that was showing.")
        lhint.setObjectName("barLabel")
        lhint.setWordWrap(True)
        ll.addWidget(lhint)
        ll.addStretch(1)
        self.tabs.addTab(lw, "LOD")
        viewer.uv_changed.connect(self._uv_sync)
        viewer.mesh_changed.connect(self._mesh_sync)
        viewer.measure_changed.connect(self._measure_sync)
        viewer.lod_changed.connect(self._lod_sync)
        self.tabs.currentChanged.connect(lambda _i: viewer.highlight_part(None))
        self.tabs.currentChanged.connect(lambda _i: self._mesh_sync())

        self.parts.setMinimumHeight(180)
        self.tex_list.setMinimumHeight(180)
        self.refresh()

    def hideEvent(self, e):
        self.viewer.highlight_part(None)
        super().hideEvent(e)

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    def refresh(self):
        v = self.viewer
        self.view_box.blockSignals(True)
        keys = [k for k, _l in VIEW_CHANNELS]
        self.view_box.setCurrentIndex(keys.index(v.mode) if v.mode in keys else 0)
        self.view_box.blockSignals(False)

        self.parts.blockSignals(True)
        self.parts.clear()
        for i, a in enumerate(v.actors):
            name = getattr(a, "_name", "") or f"Part {i + 1}"
            tag = "  ·  textured" if a.GetTexture() is not None else ""
            it = QListWidgetItem(f"{name}  ·  {_cells(a):,} faces{tag}")
            pix = QPixmap(14, 14)
            pix.fill(QColor.fromRgbF(*a.GetProperty().GetColor()))
            it.setIcon(QIcon(pix))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if a.GetVisibility() else Qt.Unchecked)
            self.parts.addItem(it)
        self.parts.blockSignals(False)

        self.tex_list.clear()
        self._textures = collect_textures(v.actors)
        tot_raw = tot_comp = 0
        seen = set()                                # an image counts toward memory once, however often it is used
        for e in self._textures:
            arr = texture_to_array(e["tex"], 128)
            icon = QIcon(QPixmap.fromImage(_rgb_to_qimage(texture_channel_rgb(arr)))) if arr is not None else QIcon()
            n = len(e["parts"])
            f = texture_facts(e["tex"], e["role"])
            if f is None:
                text = f"{e['role']}\nsize unknown  ·  used by {n} part{'s' if n != 1 else ''}"
            else:
                fp = texture_fingerprint(e["tex"])
                dup = fp in seen
                seen.add(fp)
                if not dup:
                    tot_raw += f["vram"]
                    tot_comp += f["vram_comp"]
                ch = f"{f['channels']} channel{'s' if f['channels'] != 1 else ''}"
                notes = (["not a power of two"] if f["npot"] else []) + (["very large"] if f["large"] else [])
                text = (f"{e['role']}\n{f['w']}×{f['h']}  ·  {f['bits']}-bit, {ch}  ·  {f['space']} (inferred)  ·  "
                        f"used by {n} part{'s' if n != 1 else ''}\n"
                        f"≈ {human_size(f['vram'])} in GPU memory  ·  ≈ {human_size(f['vram_comp'])} compressed"
                        + ("".join("  ·  " + t for t in notes))
                        + ("\nsame image as an entry above: counted once in the total" if dup else ""))
            self.tex_list.addItem(QListWidgetItem(icon, text))
        if not self._textures:
            self.tex_list.addItem(QListWidgetItem("This model has no textures (colours only)."))
        if self._textures:
            nu = len(seen)
            self.tex_total.setText(f"{nu} unique image{'s' if nu != 1 else ''}  ·  "
                                   f"≈ {human_size(tot_raw)} in GPU memory  ·  ≈ {human_size(tot_comp)} compressed")
        else:
            self.tex_total.setText("")
        self._uv_sync()
        self._mesh_sync()
        self._measure_sync()
        self._lod_sync()

    def _uv_sync(self):
        v = self.viewer
        if not hasattr(self, "uv_part_box"):
            return
        self.uv_part_box.blockSignals(True)
        self.uv_part_box.clear()
        self.uv_part_box.addItem("All parts")
        for i, a in enumerate(v.actors):
            self.uv_part_box.addItem(getattr(a, "_name", "") or f"Part {i + 1}")
        self.uv_part_box.setCurrentIndex(v.uv_part + 1 if -1 <= v.uv_part < len(v.actors) else 0)
        self.uv_part_box.blockSignals(False)
        for w, state in ((self.uv_show, v.uv_on), *[(self.uv_checks[k], k in v.uv_tests) for k in self.uv_checks]):
            w.blockSignals(True)
            w.setChecked(bool(state))
            w.blockSignals(False)
        ready = v._uv_ready
        self.uv_run.setEnabled(bool(v.actors) and not ready)
        self.uv_run.setText("UV tests done" if ready else "Run UV tests")
        for w in (self.uv_heat_box, *self.uv_checks.values()):
            w.setEnabled(ready)
        c = v.uv_counts()
        for k, lab in self.uv_count_labels.items():
            if not c["has_uv"]:
                lab.setText("")
            elif k in UV_ISLAND_TESTS:
                lab.setText(f"{c['inv_' + k]:,} islands" if c["isl_ok"] else "not run")
            else:
                lab.setText(f"{c[k]:,}")
        self.uv_heat_box.blockSignals(True)
        self.uv_heat_box.setCurrentIndex(max(0, self.uv_heat_box.findData(v.uv_heat)))
        self.uv_heat_box.blockSignals(False)
        for k, sp in self.uv_spins.items():
            sp.blockSignals(True)
            sp.setValue(v.uv_th[k])
            sp.blockSignals(False)
            sp.setEnabled(ready and v.uv_heat == ("stretch" if k == "stretch" else "density"))
        st = v.uv_heat_stats()
        if v.uv_heat == "density" and st["n"]:
            self.uv_heat_stats.setText(f"{100.0 * st['low'] / st['n']:.1f}% of triangles are too low (blue), "
                                       f"{100.0 * st['high'] / st['n']:.1f}% too high (red) against the median.")
        elif v.uv_heat == "stretch" and st["n"]:
            self.uv_heat_stats.setText(f"{100.0 * st['bad'] / st['n']:.1f}% of triangles are stretched past "
                                       f"{v.uv_th['stretch']:g} (red).")
        else:
            self.uv_heat_stats.setText("")
        if not v.actors:
            self.uv_note.setText("Open a model to analyse its UVs.")
        elif not ready:
            self.uv_note.setText("Press “Run UV tests” to analyse the UVs. Nothing is calculated until you do, "
                                 "so models open quickly.")
        elif not c["has_uv"]:
            self.uv_note.setText("This model (or part) has no UV coordinates, so there is nothing to test. "
                                 "STL, PLY and most CAD files carry no UVs.")
        else:
            extra = f", {c['islands']:,} islands" if c["isl_ok"] else (
                ". Island tests were skipped because the model is very large")
            self.uv_note.setText(f"{c['tris']:,} triangles analysed{extra}.")

    def _mesh_sync(self):
        if not hasattr(self, "mesh_stats"):
            return
        v = self.viewer
        analysed = v._mesh_data is not None
        for k, cb in self.mesh_checks.items():
            cb.blockSignals(True)
            cb.setChecked(k in v.mesh_tests)
            cb.blockSignals(False)
            cb.setEnabled(analysed)
        self.mesh_run.setEnabled(bool(v.actors) and not analysed)
        self.mesh_run.setText("Integrity tests done" if analysed else "Run integrity tests")
        if not v.actors:
            self.mesh_stats.setText("Open a model to analyse its mesh.")
            self.mesh_note.setText("")
            for lab in self.mesh_count_labels.values():
                lab.setText("")
            return
        if not analysed:
            ms = material_summary(v.actors)
            tris = sum(_cells(a) for a in v.actors)
            self.mesh_stats.setText(
                f"<table><tr><td style='padding-right:10px'>Polygons</td><td><b>{tris:,}</b></td></tr>"
                f"<tr><td>Parts (draw calls here)</td><td><b>{ms['parts']:,}</b></td></tr>"
                f"<tr><td>Distinct materials</td><td><b>{ms['materials']:,}</b></td></tr></table>")
            self.mesh_note.setText("Press “Run integrity tests” for the full mesh statistics and the colour tests. "
                                   "Nothing is calculated until you do, so models open quickly.")
            for lab in self.mesh_count_labels.values():
                lab.setText("")
            return
        t = v.mesh_summary()
        ms = material_summary(v.actors)
        if not t or not t["parts"]:
            self.mesh_stats.setText("This model has no polygon surfaces to analyse (points or lines only).")
            return
        rows = [("Triangles", f"{t['tris']:,}"),
                ("Vertices", f"{t['verts']:,}  ({t['unique_pos']:,} at unique positions)"),
                ("Parts (draw calls here)", f"{ms['parts']:,}"
                 + (f"  ({ms['visible']:,} visible)" if ms["visible"] != ms["parts"] else "")),
                ("Distinct materials", f"{ms['materials']:,}  (an engine needs at least this many draw calls)"),
                ("Loose vertices", f"{t['loose']:,}  (used by no triangle)"),
                ("Vertices sharing a position", f"{t['dup_verts']:,}  (normal and UV seams count)"),
                ("Separate pieces", f"{t['pieces']:,}"),
                ("Open edges", f"{t['boundary_edges']:,}"),
                ("Non-manifold edges", f"{t['nonman_edges']:,}")]
        html_rows = "".join(f"<tr><td style='padding-right:10px'>{a}</td><td><b>{b}</b></td></tr>" for a, b in rows)
        verdict = ("Closed and consistent (watertight)." if t["watertight"] else
                   "Not watertight: it has open or non-manifold edges, or inconsistent winding.")
        self.mesh_stats.setText(f"<table>{html_rows}</table>")
        for k, lab in self.mesh_count_labels.items():
            lab.setText(f"{t['n_' + k]:,}")
        self.mesh_note.setText(verdict + (f" {t['inverted_pieces']} closed piece(s) face inwards." if t["inverted_pieces"] else ""))

    def _measure_sync(self):
        if not hasattr(self, "ms_result"):
            return
        v = self.viewer
        for w, val in ((self.ms_src, v.unit_src), (self.ms_disp, v.unit_disp)):
            w.blockSignals(True)
            w.setCurrentIndex(max(0, w.findData(val)))
            w.blockSignals(False)
        for w, val in ((self.ms_mode, v.measure_on), (self.sec_on, v.section_on)):
            w.blockSignals(True)
            w.setChecked(bool(val))
            w.blockSignals(False)
        has = bool(v.actors)
        self.ms_calc.setEnabled(has)
        self.ms_clear.setEnabled(has and bool(v._meas_pts))
        k = unit_scale(v.unit_src, v.unit_disp)
        u = v.unit_disp
        r = v._measure_result
        if not has:
            self.ms_result.setText("Open a model to measure it.")
        elif r is None:
            self.ms_result.setText("Press the button above to measure the visible parts.")
        else:
            d = (np.asarray(r["aabb_max"]) - np.asarray(r["aabb_min"])) * k
            o = np.asarray(r["obb"]) * k
            f = {kk: ff for kk, _l, ff in UNITS}
            if r["volume"] is not None:
                m3 = r["volume"] * f.get(v.unit_src, 1.0) ** 3
                vol = f"{fmt_num(r['volume'] * k ** 3)} {u}³  (≈ {fmt_num(m3 * 1000.0)} litres)"
                if r["open_parts"]:
                    vol += f"<br><i>{r['open_parts']} open part(s) are not counted</i>"
            else:
                vol = "not available: no part is closed (watertight)"
            c = np.asarray(r["com"]) * k
            rows = [("Size (x × y × z)", f"{fmt_num(d[0])} × {fmt_num(d[1])} × {fmt_num(d[2])} {u}"),
                    ("Oriented box", f"{fmt_num(o[0])} × {fmt_num(o[1])} × {fmt_num(o[2])} {u}"),
                    ("Surface area", f"{fmt_num(r['area'] * k * k)} {u}²"),
                    ("Volume", vol),
                    ("Centre of mass" + ("" if r["com_kind"] == "volume" else " (of the surface)"),
                     f"{fmt_num(c[0])}, {fmt_num(c[1])}, {fmt_num(c[2])} {u}")]
            self.ms_result.setText("<table>" + "".join(
                f"<tr><td style='padding-right:10px'>{a}</td><td><b>{b}</b></td></tr>" for a, b in rows) + "</table>")
        ro = v.measure_readout()
        if not ro:
            self.ms_readout.setText("Turn on measure mode, then click points on the model." if not v.measure_on
                                    else "Click a point on the model.")
        elif ro["n"] == 1:
            self.ms_readout.setText("Point A set. Click a second point.")
        else:
            dl = np.abs(ro["delta"]) * k
            t = (f"A → B: <b>{fmt_num(ro['ab'] * k)} {u}</b><br>"
                 f"Δx {fmt_num(dl[0])}  ·  Δy {fmt_num(dl[1])}  ·  Δz {fmt_num(dl[2])} {u}")
            if "angle" in ro:
                t += (f"<br>B → C: <b>{fmt_num(ro['bc'] * k)} {u}</b>"
                      f"<br>Angle at B (A–B–C): <b>{ro['angle']:.1f}°</b>")
            self.ms_readout.setText(t)

    def _lod_sync(self):
        if not hasattr(self, "lod_box"):
            return
        v = self.viewer
        busy = v._lod_task is not None
        self.lod_btn.setEnabled(bool(v.actors) and not busy and v._lod_sets is None)
        self.lod_state.setText(v.lod_status if v.actors else "Open a model to preview its levels of detail.")
        self.lod_box.blockSignals(True)
        self.lod_box.clear()
        self.lod_box.addItem("Original", 0)
        if v._lod_sets:
            for lvl, _r in LOD_LEVELS:
                if lvl in v._lod_sets:
                    self.lod_box.addItem(f"{lvl}% of the triangles", lvl)
        self.lod_box.setCurrentIndex(max(0, self.lod_box.findData(v._lod_level)))
        self.lod_box.blockSignals(False)
        self.lod_box.setEnabled(bool(v._lod_sets) and not busy)
        if v._lod_sets and v._lod_orig_counts[0]:
            t0, v0 = v._lod_orig_counts
            rows = [("Original", f"{t0:,}", f"{v0:,}", "100%")]
            note = ""
            for lvl, _r in LOD_LEVELS:
                inf = v._lod_info.get(lvl)
                if inf:
                    rows.append((f"{lvl}% level", f"{inf['tris']:,}", f"{inf['verts']:,}", f"{100.0 * inf['tris'] / t0:.0f}%"))
                    if not inf["tcoords"]:
                        note = "<br><i>Some parts lost their UVs in simplification.</i>"
            self.lod_table.setText("<table><tr><td style='padding-right:12px'></td><td style='padding-right:12px'><b>Triangles</b></td>"
                                   "<td style='padding-right:12px'><b>Vertices</b></td><td><b>Kept</b></td></tr>"
                                   + "".join(f"<tr><td style='padding-right:12px'>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td></tr>"
                                             for a, b, c, d in rows) + "</table>" + note)
        else:
            self.lod_table.setText("")

    def _part_toggled(self, item):
        self.viewer.set_part_visible(self.parts.row(item), item.checkState() == Qt.Checked)

    def _show_all(self):
        self.viewer.show_all_parts()
        self.refresh()

    def _invert(self):
        self.viewer.invert_parts()
        self.refresh()

    def _isolate(self):
        row = self.parts.currentRow()
        if row < 0:
            self.viewer.message.emit("Select a part first")
            return
        self.viewer.isolate_part(row)
        self.refresh()
        self.parts.setCurrentRow(row)

    def _open_texture(self, item):
        row = self.tex_list.row(item)
        if not (0 <= row < len(self._textures)):
            return
        e = self._textures[row]
        arr = texture_to_array(e["tex"], 1024)
        if arr is None:
            self.viewer.message.emit("That texture's pixels can't be read")
            return
        size = f"{e['size'][0]}×{e['size'][1]}" if e["size"] else ""
        TexturePreview(self, e["role"], arr, f"{e['role']}  ·  {size}  ·  {arr.shape[2]} channel(s)").exec()
