"""The AI panel: a dockable panel (like Materials) that sends the viewer's control maps to a ComfyUI server.

Three sub-tabs: Generate (what to draw), Result (the picture; click it for a large pop-up) and Settings (server,
checkpoint, ControlNet and the finer controls). It stays open while you work, so you can move the camera in the
viewer and press Generate again.

The 3D capture happens on the main thread; the network work runs on a background thread so the interface never
freezes. Labels sit above their fields, so nothing is cut off however narrow the panel is.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QStandardPaths, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

import comfy_client as cc

SIZES = [512, 768, 1024]


def array_to_png(arr) -> bytes:
    h, w, _ = arr.shape
    img = QImage(np.ascontiguousarray(arr).data, w, h, 3 * w, QImage.Format_RGB888).copy()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("barLabel")
    lab.setTextFormat(Qt.PlainText)                     # text such as <ref_image_0> must show as typed
    lab.setWordWrap(True)
    return lab


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setRowWrapPolicy(QFormLayout.WrapAllRows)          # label above its field: never cut off
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    f.setContentsMargins(0, 0, 0, 0)
    f.setVerticalSpacing(4)
    return f


class _Worker(QThread):
    progress = Signal(str)
    done = Signal(bytes)
    failed = Signal(str)

    def __init__(self, base, images, opt, template, set_size=False):
        super().__init__()
        self.base, self.images, self.opt, self.template, self.set_size = base, images, opt, template, set_size
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.done.emit(cc.generate(self.base, self.images, self.opt, self.template, self.progress.emit,
                                       lambda: self._cancel, self.set_size))
        except cc.Cancelled:
            self.failed.emit("Cancelled")
        except cc.ComfyError as e:
            self.failed.emit(str(e))
        except Exception as e:                                    # never let a thread die silently
            self.failed.emit(f"Unexpected problem: {e}")


class ClickLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class ResultPreview(QDialog):
    """Large view of the generated picture, with Save and Copy."""

    def __init__(self, parent, png: bytes, save_cb):
        super().__init__(parent)
        self.setWindowTitle("AI picture")
        self.img = QImage.fromData(QByteArray(png))
        self.png, self.save_cb = png, save_cb
        root = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(480, 360)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        root.addWidget(self.view, 1)
        row = QHBoxLayout()
        for text, fn in (("Save…", self._save), ("Copy", self._copy)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(_hint(f"{self.img.width()}×{self.img.height()} px"))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)
        try:
            avail = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
            w = min(self.img.width() + 40, int(avail.width() * 0.85))
            h = min(self.img.height() + 90, int(avail.height() * 0.85))
            self.resize(max(520, w), max(420, h))
        except Exception:
            self.resize(900, 700)

    def _fit(self):
        if not self.img.isNull():
            self.view.setPixmap(QPixmap.fromImage(self.img).scaled(self.view.size(), Qt.KeepAspectRatio,
                                                                   Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def _save(self):
        self.save_cb()

    def _copy(self):
        QGuiApplication.clipboard().setImage(self.img)


class AIPanel(QWidget):
    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self.settings = viewer.settings
        self.info = None
        self.worker = None
        self.result = None
        self._popup = None
        self.setWindowTitle("AI")
        self.setMinimumSize(280, 300)
        S = lambda k, d: str(self.settings.value(k, d))

        # ---- widgets ----
        self.url = QLineEdit(S("comfy_url", cc.DEFAULT_URL))
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_server)
        self.status = _hint("Not connected")
        saved_maps = [k for k in S("comfy_maps", S("comfy_map", "depth")).split(",") if k in cc.MAP_LABELS] or ["depth"]
        self.map_checks = {}
        for k, label in cc.MAP_LABELS.items():
            cb = QCheckBox(label)
            cb.setChecked(k in saved_maps)
            cb.toggled.connect(self._maps_changed)
            self.map_checks[k] = cb
        self.map_info = _hint("")
        self.workflow_path = S("comfy_workflow", "")
        self.wf_label = QLabel("")
        self.wf_label.setWordWrap(True)
        self.wf_load_btn = QPushButton("Load workflow…")
        self.wf_load_btn.setToolTip("Use your own ComfyUI workflow (saved with Save (API Format)) instead of the built-in one")
        self.wf_load_btn.clicked.connect(self.pick_workflow)
        self.wf_clear_btn = QPushButton("Use built-in")
        self.wf_clear_btn.clicked.connect(self.clear_workflow)
        self.set_size_cb = QCheckBox("Apply the output size above to my workflow")
        self.set_size_cb.setChecked(S("comfy_set_size", "false").lower() in ("1", "true"))
        self.set_size_cb.setToolTip("Off: your workflow's own size settings are used as saved.")
        self.quality = QComboBox()
        for k, q in cc.QUALITY.items():
            self.quality.addItem(q["label"], k)
        self.quality.setCurrentIndex(max(0, self.quality.findData(S("comfy_quality", "balanced"))))
        self.quality.currentIndexChanged.connect(self._apply_quality)
        self.ckpt = QComboBox()
        self.cn = QComboBox()
        for box in (self.quality, self.ckpt, self.cn):
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(12)
        self.prompt = QPlainTextEdit(S("comfy_prompt", ""))
        self.prompt.setPlaceholderText("Describe the picture, e.g. “a red concept sports car, studio photo, soft light”")
        self.prompt.setMinimumHeight(90)
        self.neg = QLineEdit(S("comfy_neg", "text, watermark, blurry, low quality"))
        self.strength = QDoubleSpinBox()
        self.strength.setRange(0.0, 2.0)
        self.strength.setSingleStep(0.05)
        self.strength.setValue(float(S("comfy_strength", "0.7") or 0.7))
        self.end_pct = QDoubleSpinBox()
        self.end_pct.setRange(0.1, 1.0)
        self.end_pct.setSingleStep(0.05)
        self.end_pct.setValue(float(S("comfy_end", "0.85") or 0.85))
        self.end_pct.setToolTip("How far through the drawing the map is enforced. Below 1.0 gives the AI freedom to "
                                "add fine detail at the end.")
        self.steps = QSpinBox()
        self.steps.setRange(0, 80)
        self.steps.setSpecialValueText("automatic")
        self.steps.setValue(int(S("comfy_steps", "0") or 0))
        self.hires = QCheckBox("Detail pass: redraw at 1.5× size (slower)")
        self.hires.setChecked(S("comfy_hires", "true").lower() in ("1", "true"))
        self.size = QComboBox()
        for s in SIZES:
            self.size.addItem(f"{s} px on the long side", s)
        self.size.setCurrentIndex(max(0, self.size.findData(int(S("comfy_size", "768") or 768))))
        self.seed = QSpinBox()
        self.seed.setRange(0, 2 ** 31 - 1)
        self.seed.setValue(int(S("comfy_seed", "1") or 1))
        self.rand = QCheckBox("New random seed each time")
        self.rand.setChecked(S("comfy_rand", "true").lower() in ("1", "true"))

        self.tabs = QTabWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.tabs, 1)

        # ---- tab 1: Generate ----
        gw = QWidget()
        gl = QVBoxLayout(gw)
        f = _form()
        gl.addWidget(QLabel("Workflow"))
        gl.addWidget(self.wf_label)
        wrow = QHBoxLayout()
        wrow.addWidget(self.wf_load_btn)
        wrow.addWidget(self.wf_clear_btn)
        wrow.addStretch(1)
        gl.addLayout(wrow)
        gl.addWidget(QLabel("Maps to send"))
        for cb in self.map_checks.values():
            gl.addWidget(cb)
        gl.addWidget(self.map_info)
        f.addRow("Quality", self.quality)
        f.addRow("Prompt", self.prompt)
        f.addRow("Avoid", self.neg)
        gl.addLayout(f)
        gl.addWidget(self.rand)
        row = QHBoxLayout()
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.setDefault(True)
        self.gen_btn.clicked.connect(self.generate)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.gen_btn, 1)
        row.addWidget(self.cancel_btn)
        gl.addLayout(row)
        self.msg = _hint("Sends a control map of the current view to ComfyUI and shows the picture it makes. "
                         "Move the camera, then press Generate again.")
        gl.addWidget(self.msg)
        gl.addStretch(1)
        self.tabs.addTab(gw, "Generate")

        # ---- tab 2: Result ----
        rw = QWidget()
        rl = QVBoxLayout(rw)
        self.preview = ClickLabel("The result appears here")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(240, 200)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.preview.setStyleSheet("background:#14181d;color:#8a96a6;border:1px solid #2a313a;")
        self.preview.setToolTip("Click for a large view")
        self.preview.clicked.connect(self.open_popup)
        rl.addWidget(self.preview, 1)
        self.result_info = _hint("Click the picture for a large view.")
        rl.addWidget(self.result_info)
        brow = QHBoxLayout()
        self.save_btn = QPushButton("Save image…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy)
        brow.addWidget(self.save_btn, 1)
        brow.addWidget(self.copy_btn)
        rl.addLayout(brow)
        self.tabs.addTab(rw, "Result")

        # ---- tab 3: Settings ----
        sw = QWidget()
        sl = QVBoxLayout(sw)
        f = _form()
        srv = QHBoxLayout()
        srv.addWidget(self.url, 1)
        srv.addWidget(self.connect_btn)
        f.addRow("ComfyUI address", srv)
        sl.addLayout(f)
        sl.addWidget(self.status)
        f = _form()
        f.addRow("Checkpoint", self.ckpt)
        f.addRow("ControlNet", self.cn)
        f.addRow("Output size", self.size)
        f.addRow("Control strength", self.strength)
        f.addRow("Control ends at", self.end_pct)
        f.addRow("Steps", self.steps)
        f.addRow("Seed", self.seed)
        sl.addLayout(f)
        sl.addWidget(self.hires)
        sl.addWidget(self.set_size_cb)
        sl.addWidget(_hint("ComfyUI and its models are not part of Gleek3Deek; everything stays on your network."))
        sl.addStretch(1)
        self.tabs.addTab(sw, "Settings")

        self._fill_combos([], [], S("comfy_ckpt", ""), S("comfy_cn", ""))
        self.connect_server(quiet=True)
        self._maps_changed()
        self._update_workflow_ui()

    # ----- maps and workflow --------------------------------------------------------------------------------------
    def selected_maps(self) -> list:
        return [k for k, cb in self.map_checks.items() if cb.isChecked()]

    def _maps_changed(self, *_):
        keys = self.selected_maps()
        custom = bool(self.workflow_path)
        if not keys:
            self.map_info.setText("Tick at least one map.")
        elif custom:
            self.map_info.setText("In your prompt: " + ", ".join(
                f"<ref_image_{i}> = {cc.MAP_LABELS[k].split(' (')[0]}" for i, k in enumerate(keys)) +
                ". The order follows the list above.")
        elif len(keys) > 1:
            self.map_info.setText("The built-in workflow uses one map (" + cc.MAP_LABELS[keys[0]].split(" (")[0] +
                                  "). Load your own workflow to send several.")
        else:
            self.map_info.setText("")
        self._auto_controlnet()

    def _update_workflow_ui(self):
        custom = bool(self.workflow_path)
        self.wf_label.setText(("Your workflow: " + os.path.basename(self.workflow_path)) if custom
                              else "Built-in (SDXL + ControlNet)")
        self.wf_clear_btn.setEnabled(custom)
        self.quality.setEnabled(not custom)
        self.neg.setEnabled(not custom)
        self.set_size_cb.setEnabled(custom)
        self.prompt.setPlaceholderText(
            "Describe the picture. Leave empty to use the prompt saved in your workflow. "
            "Refer to the maps as <ref_image_0>, <ref_image_1>…" if custom else
            "Describe the picture, e.g. “a red concept sports car, studio photo, soft light”")
        self._maps_changed()

    def clear_workflow(self):
        self.workflow_path = ""
        self.settings.setValue("comfy_workflow", "")
        self._update_workflow_ui()

    # ----- called by the viewer when a model is opened ---------------------------------------------------------------
    def refresh(self):
        pass

    # ----- server ------------------------------------------------------------------------------------------------
    def _fill_combos(self, ckpts, cns, want_c="", want_n=""):
        for box, items, want in ((self.ckpt, ckpts, want_c), (self.cn, cns, want_n)):
            box.clear()
            box.addItems(items or ([want] if want else []))
            i = box.findText(want)
            if i >= 0:
                box.setCurrentIndex(i)

    def connect_server(self, quiet=False):
        try:
            base = cc.normalize_url(self.url.text())
            self.info = cc.server_info(base)
        except cc.ComfyError as e:
            self.info = None
            self.status.setText(str(e))
            return
        i = self.info
        self.url.setText(base)
        self._fill_combos(i["checkpoints"], i["controlnets"],
                          self.ckpt.currentText() or str(self.settings.value("comfy_ckpt", "")),
                          self.cn.currentText() or str(self.settings.value("comfy_cn", "")))
        if not str(self.settings.value("comfy_ckpt", "")):
            t = cc.pick_checkpoint(i["checkpoints"], self.quality.currentData())
            if t:
                self.ckpt.setCurrentIndex(max(0, self.ckpt.findText(t)))
        self._auto_controlnet()
        self.status.setText(f"Connected: ComfyUI {i['version']} · {i['gpu']} · {i['vram_gb']} GB · "
                            f"{len(i['checkpoints'])} checkpoints, {len(i['controlnets'])} ControlNets")

    def _apply_quality(self):
        q = cc.QUALITY[self.quality.currentData()]
        self.size.setCurrentIndex(max(0, self.size.findData(q["size"])))
        self.hires.setChecked(q["hires"])
        if self.info:
            c = cc.pick_checkpoint(self.info["checkpoints"], self.quality.currentData())
            if c:
                self.ckpt.setCurrentIndex(max(0, self.ckpt.findText(c)))
            self.settings.setValue("comfy_cn", "")
            self._auto_controlnet()

    def _auto_controlnet(self):
        if self.info and not str(self.settings.value("comfy_cn", "")):
            n = cc.pick_controlnet(self.info["controlnets"], (self.selected_maps() or ["depth"])[0], self.ckpt.currentText())
            if n:
                self.cn.setCurrentIndex(max(0, self.cn.findText(n)))

    def pick_workflow(self):
        fn, _ = QFileDialog.getOpenFileName(self, "ComfyUI workflow (API format)", self.workflow_path or str(Path.home()),
                                            "Workflow (*.json)")
        if not fn:
            return
        try:
            cc.load_template(fn)                                  # check it now, not at Generate time
        except cc.ComfyError as e:
            self.msg.setText(str(e))
            self.tabs.setCurrentIndex(0)
            return
        self.workflow_path = fn
        self.settings.setValue("comfy_workflow", fn)
        self.msg.setText("Workflow loaded. Maps are placed in its Load Image nodes; refer to them as <ref_image_0>… in the prompt.")
        self._update_workflow_ui()

    # ----- generation --------------------------------------------------------------------------------------------
    def remember(self):
        for k, v in (("comfy_url", self.url.text()), ("comfy_prompt", self.prompt.toPlainText()), ("comfy_neg", self.neg.text()),
                     ("comfy_strength", self.strength.value()), ("comfy_maps", ",".join(self.selected_maps())),
                     ("comfy_size", self.size.currentData()), ("comfy_seed", self.seed.value()),
                     ("comfy_rand", "true" if self.rand.isChecked() else "false"), ("comfy_workflow", self.workflow_path), ("comfy_set_size", "true" if self.set_size_cb.isChecked() else "false"),
                     ("comfy_ckpt", self.ckpt.currentText()), ("comfy_cn", self.cn.currentText()),
                     ("comfy_quality", self.quality.currentData()), ("comfy_end", self.end_pct.value()),
                     ("comfy_steps", self.steps.value()), ("comfy_hires", "true" if self.hires.isChecked() else "false")):
            self.settings.setValue(k, v)

    def _busy(self, on):
        self.gen_btn.setEnabled(not on)
        self.cancel_btn.setEnabled(on)

    def generate(self):
        if not self.viewer.actors:
            self.msg.setText("Open a model first.")
            return
        keys = self.selected_maps()
        if not keys:
            self.msg.setText("Tick at least one map to send.")
            return
        custom = bool(self.workflow_path)
        if not custom:
            keys = keys[:1]                                       # the built-in workflow takes one map
            if not self.prompt.toPlainText().strip():
                self.msg.setText("Type a prompt first.")
                return
        try:
            base = cc.normalize_url(self.url.text())
            template = cc.load_template(self.workflow_path) if custom else None
        except cc.ComfyError as e:
            self.msg.setText(str(e))
            return
        if self.rand.isChecked():
            self.seed.setValue(cc.random_seed())
        self.remember()
        long_side = int(self.size.currentData())
        self.msg.setText("Capturing the view…")
        win = self.window()
        floating = win is not self.viewer.window() and win.isWindow()
        if floating:
            win.hide()                                            # a floating panel must not cover the 3D view
        QApplication.processEvents()
        try:
            wanted = [k for k in keys if k != "screenshot"]
            arrs = (self.viewer.render_control_maps({"maps": wanted, "canny": "mid", "lines": "mid",
                                                     "size": long_side, "cutout": True}) if wanted else {})
            images, first = [], None
            for k in keys:
                if k == "screenshot":
                    shot = self.viewer.grab_image()
                    if shot is None or shot.isNull():
                        raise RuntimeError("the viewport could not be captured")
                    buf = QBuffer()
                    buf.open(QIODevice.WriteOnly)
                    shot.save(buf, "PNG")
                    images.append((k, bytes(buf.data())))
                    size_wh = (shot.width(), shot.height())
                else:
                    images.append((k, array_to_png(arrs[k])))
                    size_wh = (arrs[k].shape[1], arrs[k].shape[0])
                first = first or size_wh
        except Exception as e:
            self.msg.setText(f"Could not capture the view: {e}")
            return
        finally:
            if floating:
                win.show()
        width, height = cc.fit_size(first[0], first[1], long_side)
        opt = {"checkpoint": self.ckpt.currentText(), "controlnet": self.cn.currentText(), "map": keys[0],
               "prompt": self.prompt.toPlainText().strip(), "negative": self.neg.text(), "seed": self.seed.value(),
               "width": width, "height": height, "strength": self.strength.value(),
               "end_percent": self.end_pct.value(), "steps": self.steps.value(), "hires": self.hires.isChecked()}
        self._busy(True)
        self.worker = _Worker(base, images, opt, template, self.set_size_cb.isChecked())
        self.worker.progress.connect(self.msg.setText)
        self.worker.done.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def cancel(self):
        if self.worker is not None:
            self.worker.cancel()
            self.msg.setText("Cancelling…")

    def _finished(self, png: bytes):
        self._busy(False)
        img = QImage.fromData(QByteArray(png))
        if img.isNull():
            self.msg.setText("ComfyUI returned something that is not an image.")
            return
        self.result = png
        self.save_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self._show_result()
        self.result_info.setText(f"{img.width()}×{img.height()} px. Click the picture for a large view.")
        self.msg.setText("Done. See the Result tab; move the camera and press Generate again for another.")
        self.tabs.setCurrentIndex(1)

    def _failed(self, text: str):
        self._busy(False)
        self.msg.setText(text)

    def _show_result(self):
        if not self.result:
            return
        img = QImage.fromData(QByteArray(self.result))
        if not img.isNull():
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                                 Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show_result()

    def open_popup(self):
        if not self.result:
            return
        self._popup = ResultPreview(self.window(), self.result, self.save)
        self._popup.show()

    def copy(self):
        if self.result:
            QGuiApplication.clipboard().setImage(QImage.fromData(QByteArray(self.result)))
            self.result_info.setText("Copied to the clipboard.")

    def save(self):
        if not self.result:
            return
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
        stem = Path(self.viewer.path).stem if getattr(self.viewer, "path", None) else "model"
        fn, _ = QFileDialog.getSaveFileName(self, "Save the picture", os.path.join(pics, f"{stem}_ai.png"), "PNG image (*.png)")
        if fn:
            try:
                with open(fn, "wb") as fh:
                    fh.write(self.result)
                self.result_info.setText("Saved " + os.path.basename(fn))
            except OSError as e:
                self.result_info.setText(f"Could not save: {e}")

    def stop(self):
        """Cancel a running request and remember the settings (called when the app closes)."""
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        self.remember()

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)
