"""Gleek3Deek environment: sky, lighting and tone-mapping settings, panorama loading and re-projection, shader code, and the Environment panel."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import numpy as np
from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGridLayout, QMessageBox, QPushButton,
    QSlider)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from vtkmodules.util import numpy_support
from vtkmodules.vtkCommonDataModel import vtkImageData
try:
    from vtkmodules.vtkIOImage import vtkHDRReader
except Exception:  # pragma: no cover
    vtkHDRReader = None
from matcap import _vec3


# ---------------------------------------------------------------------------
# Environment: panorama sky, hemispheric ambient, one sun, blob shadow.
# Deliberately cheap: no reflections, no roughness maths, no bounces.
# ---------------------------------------------------------------------------
ENV_DEFAULTS = {
    "enabled": False, "skybox": True, "lighting": True, "shadow": True, "path": "",
    "sky": [0.50, 0.65, 0.85], "equator": [0.78, 0.80, 0.82], "ground": [0.30, 0.27, 0.24],
    "sun_color": [1.0, 0.95, 0.85], "sun_az": 35.0, "sun_el": 50.0, "sun_int": 0.85,
    "highlight": 0.25, "ambient": 1.0, "yaw": 0.0, "shadow_opacity": 0.5, "shadow_size": 1.0,
    "exposure": 0.0, "tonemap": "none", "sky_blur": 0.0, "gradient_bg": False,
}


ENV_FLAGS = [("enabled", "Environment on"), ("skybox", "Skybox"), ("lighting", "Lighting"),
             ("shadow", "Blob shadow"), ("gradient_bg", "Sky gradient")]


TONEMAPS = [("none", "None (clamp)"), ("reinhard", "Soft highlights (Reinhard)"),
            ("aces", "Filmic (ACES)")]


ENV_COLORS = [("sky", "Sky"), ("equator", "Equator"), ("ground", "Ground"), ("sun_color", "Sun")]


# (key, label, min, max, step, decimals)
ENV_SLIDERS = [
    ("sun_az", "Sun direction °", -180, 180, 1, 0),
    ("sun_el", "Sun height °", -10, 90, 1, 0),
    ("sun_int", "Sun intensity", 0.0, 2.0, 0.01, 2),
    ("highlight", "Sun highlight", 0.0, 1.0, 0.01, 2),
    ("ambient", "Ambient strength", 0.0, 1.5, 0.01, 2),
    ("yaw", "Rotate environment °", -180, 180, 1, 0),
    ("shadow_opacity", "Shadow opacity", 0.0, 1.0, 0.01, 2),
    ("shadow_size", "Shadow size", 0.5, 2.0, 0.05, 2),
    ("exposure", "Exposure (stops)", -3.0, 3.0, 0.1, 1),
    ("sky_blur", "Sky blur", 0.0, 1.0, 0.01, 2),
]


# Built-in lighting presets: colours only (no panorama needed). Applied on top of ENV_DEFAULTS.
ENV_BUILTIN_PRESETS = {
    "Studio Soft": {"sky": [0.82, 0.84, 0.88], "equator": [0.62, 0.63, 0.66], "ground": [0.26, 0.26, 0.28],
                    "sun_color": [1.0, 0.97, 0.92], "sun_az": 35.0, "sun_el": 45.0, "sun_int": 0.65,
                    "highlight": 0.25, "shadow_opacity": 0.45, "gradient_bg": True},
    "Overcast": {"sky": [0.74, 0.77, 0.80], "equator": [0.64, 0.66, 0.68], "ground": [0.38, 0.38, 0.38],
                 "sun_color": [0.95, 0.96, 1.0], "sun_az": 0.0, "sun_el": 75.0, "sun_int": 0.15,
                 "highlight": 0.05, "shadow_opacity": 0.22, "gradient_bg": True},
    "Midday Sun": {"sky": [0.45, 0.62, 0.90], "equator": [0.78, 0.82, 0.86], "ground": [0.36, 0.32, 0.27],
                   "sun_color": [1.0, 0.96, 0.88], "sun_az": 30.0, "sun_el": 62.0, "sun_int": 1.0,
                   "highlight": 0.35, "shadow_opacity": 0.6, "gradient_bg": True,
                   "tonemap": "reinhard", "exposure": 0.5},
    "Golden Hour": {"sky": [0.38, 0.48, 0.75], "equator": [0.95, 0.62, 0.38], "ground": [0.30, 0.20, 0.14],
                    "sun_color": [1.0, 0.72, 0.42], "sun_az": -60.0, "sun_el": 12.0, "sun_int": 1.0,
                    "highlight": 0.35, "shadow_opacity": 0.5, "gradient_bg": True},
    "Blue Hour": {"sky": [0.10, 0.14, 0.30], "equator": [0.30, 0.34, 0.52], "ground": [0.08, 0.08, 0.12],
                  "sun_color": [0.62, 0.72, 1.0], "sun_az": 140.0, "sun_el": 25.0, "sun_int": 0.45,
                  "highlight": 0.2, "shadow_opacity": 0.4, "exposure": 0.3, "gradient_bg": True},
    "Dramatic Rim": {"sky": [0.12, 0.13, 0.16], "equator": [0.10, 0.10, 0.13], "ground": [0.05, 0.05, 0.06],
                     "sun_color": [1.0, 0.95, 0.9], "sun_az": 80.0, "sun_el": 25.0, "sun_int": 1.2,
                     "highlight": 0.5, "shadow_opacity": 0.6, "gradient_bg": True},
    "Neutral Grey": {"sky": [0.56, 0.56, 0.56], "equator": [0.50, 0.50, 0.50], "ground": [0.40, 0.40, 0.40],
                     "sun_color": [1.0, 1.0, 1.0], "sun_az": 20.0, "sun_el": 40.0, "sun_int": 0.55,
                     "highlight": 0.2, "shadow_opacity": 0.35, "gradient_bg": True},
}


PANO_MAX_W = 2048                       # panoramas are shrunk to this width on load


SKY_TEX_W = 1024                        # width of the (re-projected) skybox texture


def clean_env(raw) -> dict:
    e = copy.deepcopy(ENV_DEFAULTS)
    if isinstance(raw, dict):
        for k, _l in ENV_FLAGS:
            if k in raw:
                e[k] = bool(raw[k])
        if isinstance(raw.get("path"), str):
            e["path"] = raw["path"]
        if raw.get("tonemap") in dict(TONEMAPS):
            e["tonemap"] = raw["tonemap"]
        for key, _l, lo, hi, _s, _d in ENV_SLIDERS:
            if key in raw:
                try:
                    e[key] = min(hi, max(lo, float(raw[key])))
                except (TypeError, ValueError):
                    pass
        for key, _l in ENV_COLORS:
            v = raw.get(key)
            if isinstance(v, (list, tuple)) and len(v) == 3:
                try:
                    e[key] = [min(1.0, max(0.0, float(x))) for x in v]
                except (TypeError, ValueError):
                    pass
    return e


PRESET_ENV_KEYS = [k for k, _l in ENV_FLAGS if k != "enabled"] + ["tonemap"] + \
                  [k for k, _l in ENV_COLORS] + [k for k, _l, *_rest in ENV_SLIDERS]


def env_to_preset(env: dict, name: str) -> dict:
    """Everything except the on/off master switch. The panorama is stored as a path."""
    return {"gleek3deek_environment": 1, "name": name,
            "settings": {k: env[k] for k in PRESET_ENV_KEYS},
            "panorama": env.get("path", "")}


def preset_to_env(d, base_dir: str = ""):
    """-> (env, missing_panorama_name, preset_name). Raises ValueError for non-presets.
    A missing panorama is looked for next to the preset file before giving up."""
    if not isinstance(d, dict) or d.get("gleek3deek_environment") != 1:
        raise ValueError("This is not a Gleek3Deek environment preset.")
    settings = d.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("The preset has no settings.")
    env = clean_env({k: v for k, v in settings.items() if k in PRESET_ENV_KEYS})
    env["enabled"] = True
    env["path"], missing = "", ""
    pano = d.get("panorama")
    if isinstance(pano, str) and pano:
        base = os.path.basename(pano.replace("\\", "/"))
        for cand in (pano, os.path.join(base_dir, base) if base_dir else ""):
            if cand and os.path.isfile(cand):
                env["path"] = cand
                break
        else:
            missing = base
    return env, missing, str(d.get("name") or "Environment")[:40]


# ----- direction maths. "Frame" = Y-up coordinates; Z-up worlds map into it with M ---------
def _rot_y(v, a):
    c, s = math.cos(a), math.sin(a)
    x, y, z = v[..., 0], v[..., 1], v[..., 2]
    return np.stack([x * c + z * s, y, -x * s + z * c], -1)


def frame_to_world(v, up: str):
    v = np.asarray(v, dtype=np.float64)
    return v if up != "Z" else np.stack([v[..., 0], -v[..., 2], v[..., 1]], -1)


def world_to_frame(v, up: str):
    v = np.asarray(v, dtype=np.float64)
    return v if up != "Z" else np.stack([v[..., 0], v[..., 2], -v[..., 1]], -1)


def sun_dir_frame(az: float, el: float):
    return np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])


def dir_to_azel(d):
    d = np.asarray(d, dtype=np.float64)
    d = d / max(np.linalg.norm(d), 1e-9)
    return math.degrees(math.atan2(d[0], d[2])), math.degrees(math.asin(max(-1.0, min(1.0, d[1]))))


def equirect_dir(u, v):
    """VTK's sphere-skybox convention: u = 0.5 + atan2(z, x)/2pi, v = 0.5 + elevation/pi."""
    phi, theta = (u - 0.5) * 2 * math.pi, (v - 0.5) * math.pi
    return np.stack([np.cos(theta) * np.cos(phi), np.sin(theta), np.cos(theta) * np.sin(phi)], -1)


def dir_to_equirect(d):
    return (0.5 + np.arctan2(d[..., 2], d[..., 0]) / (2 * math.pi),
            0.5 + np.arctan2(d[..., 1], np.hypot(d[..., 0], d[..., 2])) / math.pi)


def _block_mean(arr: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return arr
    h, w = arr.shape[0] // k * k, arr.shape[1] // k * k
    return arr[:h, :w].reshape(h // k, k, w // k, k, arr.shape[2]).mean((1, 3))


def read_panorama(path: str) -> np.ndarray:
    """Equirectangular panorama -> float32 HxWx3 (row 0 = top), at most PANO_MAX_W wide."""
    ext = Path(path).suffix.lower()
    if ext == ".exr":
        raise ValueError("EXR isn't supported. Save the panorama as .hdr (Radiance) or PNG/JPG.")
    if ext == ".hdr":
        if vtkHDRReader is None:
            raise ValueError("This VTK build has no .hdr reader.")
        r = vtkHDRReader()
        r.SetFileName(path)
        r.Update()
        img = r.GetOutput()
        w, h, _ = img.GetDimensions()
        sc = img.GetPointData().GetScalars()
        if sc is None or w == 0:
            raise ValueError("The .hdr file could not be read.")
        arr = numpy_support.vtk_to_numpy(sc).reshape(h, w, -1)[..., :3][::-1].astype(np.float32)
    else:
        q = QImage(path)
        if q.isNull():
            raise ValueError("That image could not be read.")
        q = q.convertToFormat(QImage.Format_RGB888)
        w, h, bpl = q.width(), q.height(), q.bytesPerLine()
        raw = np.frombuffer(q.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 3]
        arr = raw.reshape(h, w, 3).astype(np.float32) / 255.0
    return _block_mean(arr, max(1, math.ceil(arr.shape[1] / PANO_MAX_W))).astype(np.float32)


_LUMA = np.array([0.2126, 0.7152, 0.0722])


def tonemap_exposure(lin: np.ndarray):
    """None for ordinary 0-1 images; an exposure factor for HDR data."""
    if float(lin.max()) <= 1.0001:
        return None
    p90 = float(np.percentile((lin @ _LUMA)[::4, ::4], 90))
    return 0.5 / max(p90, 1e-6)


def tonemap(arr: np.ndarray, k) -> np.ndarray:
    if k is None:
        return np.clip(arr, 0.0, 1.0)
    x = arr * k
    return np.clip((x / (1.0 + x)) ** (1 / 2.2), 0.0, 1.0)


def analyze_panorama(lin: np.ndarray, k) -> dict:
    """Pick sky/equator/ground colours and the brightest spot (the 'sun') from a panorama."""
    ds = _block_mean(lin, max(1, lin.shape[1] // 256))
    h, w, _ = ds.shape
    disp = tonemap(ds, k)
    lum = ds @ _LUMA
    lat = (0.5 - (np.arange(h) + 0.5) / h) * math.pi
    cosw = np.cos(lat)

    def band(lo, hi):
        rows = (np.degrees(lat) >= lo) & (np.degrees(lat) <= hi)
        if not rows.any():
            return [0.5, 0.5, 0.5]
        wt = cosw[rows][:, None, None]
        return [float(v) for v in (disp[rows] * wt).sum((0, 1)) / (wt.sum() * w)]

    pad = np.pad(lum, 1, mode="edge")
    blur = sum(pad[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)) / 9.0
    r, c = np.unravel_index(int(np.argmax(blur)), blur.shape)
    uu, vv = np.meshgrid((np.arange(w) + 0.5) / w, 1.0 - (np.arange(h) + 0.5) / h)
    dirs = equirect_dir(uu, vv)                                    # (h, w, 3)
    d0 = dirs[r, c]
    near = (dirs @ d0) > math.cos(math.radians(20))
    lmax = float(lum[near].max())
    wts = np.maximum(lum - 0.6 * lmax, 0.0) * near
    if wts.sum() <= 0:
        wts = near * lum
    sun = (dirs * wts[..., None]).sum((0, 1))
    sun = sun / max(np.linalg.norm(sun), 1e-9)
    col = (disp * wts[..., None]).sum((0, 1)) / max(float(wts.sum()), 1e-9)
    col = col / max(float(col.max()), 1e-6)
    col = 0.8 * col + 0.2
    mean_lum = float((lum * cosw[:, None]).sum() / (cosw.sum() * w))
    ratio = lmax / max(mean_lum, 1e-6)
    return {"sky": band(30, 90), "equator": band(-15, 15), "ground": band(-90, -30),
            "sun_dir": sun, "sun_color": [float(x) for x in col],
            "sun_int": float(np.clip(0.35 + 0.13 * math.log2(max(ratio, 1.0)), 0.35, 1.2))}


def prepare_panorama(lin: np.ndarray) -> dict:
    k = tonemap_exposure(lin)
    return {"disp": tonemap(lin, k).astype(np.float32), "info": analyze_panorama(lin, k)}


def reproject_panorama(disp: np.ndarray, up: str, yaw_deg: float, out_w: int = SKY_TEX_W) -> np.ndarray:
    """Resample the panorama so its 'up' matches the model's up axis and apply the yaw."""
    oh, ow = out_w // 2, out_w
    jj, ii = np.meshgrid((np.arange(ow) + 0.5) / ow, 1.0 - (np.arange(oh) + 0.5) / oh)
    d_img = _rot_y(world_to_frame(equirect_dir(jj, ii), up), -math.radians(yaw_deg))
    us, vs = dir_to_equirect(d_img)
    k = max(1, disp.shape[1] // out_w)               # pre-filter so small textures blur, not alias
    if k > 1:
        disp = _block_mean(disp, k)
    sh, sw, _ = disp.shape
    col = us * sw - 0.5
    row = np.clip((1.0 - vs) * sh - 0.5, 0, sh - 1)
    c0 = np.floor(col).astype(int)
    r0 = np.clip(np.floor(row).astype(int), 0, sh - 2)
    fx, fy = (col - c0)[..., None], (row - r0)[..., None]
    c0w, c1w = c0 % sw, (c0 + 1) % sw
    out = (disp[r0, c0w] * (1 - fx) * (1 - fy) + disp[r0, c1w] * fx * (1 - fy)
           + disp[r0 + 1, c0w] * (1 - fx) * fy + disp[r0 + 1, c1w] * fx * fy)
    return np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)


def numpy_to_vtk_image(arr: np.ndarray):
    """uint8 HxWxC (row 0 = top) -> vtkImageData (VTK rows run bottom to top)."""
    h, w, c = arr.shape
    img = vtkImageData()
    img.SetDimensions(w, h, 1)
    img.GetPointData().SetScalars(
        numpy_support.numpy_to_vtk(np.ascontiguousarray(arr[::-1]).reshape(-1, c), deep=True))
    return img


def blob_texture_array(n: int = 128) -> np.ndarray:
    u = np.linspace(-1.0, 1.0, n)
    r = np.hypot(*np.meshgrid(u, u))
    alpha = (1.0 - np.clip(r, 0.0, 1.0)) ** 2
    out = np.zeros((n, n, 4), np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return out


def env_shader_code(env: dict, sun_frame, view_locked: bool = False) -> str:
    """Hemispheric ambient + one sun, as GLSL for the 'Light::Impl' slot (literals only).
    World-up and the sun come from two VTK scene lights (lightDirectionVC0 / 1), so they stay
    fixed in the world as the camera orbits. view_locked=True is the fallback that keeps them
    fixed relative to the screen instead."""
    amb = env["ambient"]

    def col(key):
        return _vec3([v * amb for v in env[key]])
    sun = [v * env["sun_int"] for v in env["sun_color"]]
    if view_locked:
        up_src, sun_src = "vec3(0.0, 1.0, 0.0)", f"normalize({_vec3(sun_frame)})"
    else:
        up_src, sun_src = "normalize(-lightDirectionVC0)", "normalize(-lightDirectionVC1)"
    expo = 2.0 ** float(env.get("exposure", 0.0))
    tone = {"reinhard": "  envCol = envCol * (1.0 + envCol * 0.25) / (1.0 + envCol);\n",
            "aces": ("  envCol = (envCol * (2.51 * envCol + 0.03)) / "
                     "(envCol * (2.43 * envCol + 0.59) + 0.14);\n")}.get(env.get("tonemap"), "")
    return f"""
  vec3 envN = normalize(normalVCVSOutput);
  if (!gl_FrontFacing) envN = -envN;
  vec3 envUp = {up_src};
  vec3 envSun = {sun_src};
  float envH = dot(envN, envUp);
  vec3 envAmb = mix(mix({col('equator')}, {col('sky')}, max(envH, 0.0)), {col('ground')}, max(-envH, 0.0));
  float envNL = max(dot(envN, envSun), 0.0);
  vec3 envHalf = normalize(envSun + vec3(0.0, 0.0, 1.0));
  float envSpec = pow(max(dot(envN, envHalf), 0.0), 32.0) * step(0.001, envNL);
  vec3 envCol = diffuseColor * (envAmb + {_vec3(sun)} * envNL)
              + {_vec3(env['sun_color'])} * (envSpec * {env['highlight'] * env['sun_int']:.4f});
  envCol *= {expo:.4f};
{tone}  fragOutput0 = vec4(clamp(envCol, 0.0, 1.0), opacity);
"""


class EnvironmentPanel(QWidget):
    """Floating panel for the environment: panorama, three ambient colours, sun and shadow."""
    changed = Signal(object)
    load_requested = Signal(str)
    fit_requested = Signal()
    clear_requested = Signal()
    preset_loaded = Signal(object, str, str)      # env, missing panorama name, preset name
    builtin_requested = Signal(str)

    def __init__(self, parent, env: dict, pano_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Environment")
        self.setMinimumWidth(300)
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.env = copy.deepcopy(env)
        self._checks: dict = {}
        self._sliders: dict = {}
        self._labels: dict = {}
        self._color_btns: dict = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.changed.emit(copy.deepcopy(self.env)))

        root = QVBoxLayout(self)
        root.setSpacing(8)
        row = QHBoxLayout()
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Light preset"))
        self.preset_box = QComboBox()
        self.preset_box.addItem("Choose…")
        self.preset_box.addItems(list(ENV_BUILTIN_PRESETS))
        self.preset_box.activated.connect(self._builtin_chosen)
        prow.addWidget(self.preset_box, 1)
        root.addLayout(prow)
        for text, fn in (("Load panorama…", self.load_pano),
                         ("Fit lighting to panorama", lambda _=False: self.fit_requested.emit()),
                         ("Clear panorama", lambda _=False: self.clear_requested.emit())):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        root.addLayout(row)
        self.pano_label = QLabel("")
        self.pano_label.setObjectName("barLabel")
        self.pano_label.setWordWrap(True)
        root.addWidget(self.pano_label)
        row = QHBoxLayout()
        for text, fn in (("Load preset…", self.load_preset), ("Save preset…", self.save_preset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)

        flags = QGridLayout()
        for i, (key, label) in enumerate(ENV_FLAGS):
            cb = QCheckBox(label)
            cb.toggled.connect(lambda on, k=key: self._flag(k, on))
            self._checks[key] = cb
            flags.addWidget(cb, i // 3, i % 3)
        root.addLayout(flags)

        grid = QGridLayout()
        for i, (key, label) in enumerate(ENV_COLORS):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=key, lb=label: self.pick_color(k, lb))
            self._color_btns[key] = b
            grid.addWidget(b, 0, i)
        root.addLayout(grid)

        form = QFormLayout()
        self.tone_box = QComboBox()
        self.tone_box.addItems([lab for _k, lab in TONEMAPS])
        self.tone_box.currentIndexChanged.connect(self._tone_changed)
        form.addRow("Tone mapping", self.tone_box)
        for key, label, lo, hi, step, dec in ENV_SLIDERS:
            s = QSlider(Qt.Horizontal)
            s.setRange(round(lo / step), round(hi / step))
            lab = QLabel("")
            lab.setFixedWidth(48)
            s.valueChanged.connect(lambda v, k=key, st=step, d=dec: self._slider_changed(k, v * st, d))
            holder = QHBoxLayout()
            holder.addWidget(s, 1)
            holder.addWidget(lab)
            form.addRow(label, holder)
            self._sliders[key] = (s, step, dec)
            self._labels[key] = lab
        root.addLayout(form)

        row = QHBoxLayout()
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)
        self.set_env(self.env, pano_path)

    def set_env(self, env: dict, pano_path=None):
        self.env = copy.deepcopy(env)
        for key, cb in self._checks.items():
            cb.blockSignals(True)
            cb.setChecked(bool(self.env[key]))
            cb.blockSignals(False)
        for key in self._sliders:
            self._set_slider(key, self.env[key])
        self.tone_box.blockSignals(True)
        self.tone_box.setCurrentIndex(max(0, [k for k, _l in TONEMAPS].index(self.env.get("tonemap", "none"))))
        self.tone_box.blockSignals(False)
        for key in self._color_btns:
            self._style_color(key)
        if pano_path is not None:
            self.pano_label.setText(f"Panorama: {Path(pano_path).name}" if pano_path else
                                    "No panorama loaded: using the three colours below.")

    def _builtin_chosen(self, index: int):
        if index > 0:
            self.builtin_requested.emit(self.preset_box.itemText(index))
        self.preset_box.setCurrentIndex(0)

    def _tone_changed(self, index: int):
        self.env["tonemap"] = TONEMAPS[index][0]
        self._touched()

    def _set_slider(self, key: str, value: float):
        s, step, dec = self._sliders[key]
        s.blockSignals(True)
        s.setValue(round(value / step))
        s.blockSignals(False)
        self._labels[key].setText(f"{value:.{dec}f}")

    def _style_color(self, key: str):
        c = self.env[key]
        lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        self._color_btns[key].setStyleSheet(
            f"background:rgb({int(c[0] * 255)},{int(c[1] * 255)},{int(c[2] * 255)});"
            f"color:{'#101418' if lum > 0.55 else '#f2f5f8'};border:1px solid #3a4656;")

    def _touched(self):
        self._timer.start(120)

    def _flag(self, key: str, on: bool):
        self.env[key] = bool(on)
        self._touched()

    def _slider_changed(self, key: str, value: float, dec: int):
        if key == "yaw" and self.env.get("path"):          # keep the sun glued to the image
            az = (self.env["sun_az"] + (value - self.env["yaw"]) + 180.0) % 360.0 - 180.0
            self.env["sun_az"] = az
            self._set_slider("sun_az", az)
        self.env[key] = value
        self._labels[key].setText(f"{value:.{dec}f}")
        self._touched()

    def pick_color(self, key: str, label: str):
        c0 = self.env[key]
        c = QColorDialog.getColor(QColor.fromRgbF(c0[0], c0[1], c0[2]), self, f"{label} colour")
        if c.isValid():
            self.env[key] = [c.redF(), c.greenF(), c.blueF()]
            self._style_color(key)
            self._touched()

    def _preset_dir(self) -> str:
        d = str(self.settings.value("env_dir", ""))
        return d if d and os.path.isdir(d) else (
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home()))

    def load_preset(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Load environment preset", self._preset_dir(),
                                            "Environment preset (*.json)")
        if not fn:
            return
        self.settings.setValue("env_dir", os.path.dirname(fn))
        try:
            with open(fn, "r", encoding="utf-8") as f:
                env, missing, name = preset_to_env(json.load(f), os.path.dirname(fn))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Environment preset", f"Could not load this preset.\n\n{e}")
            return
        self.preset_loaded.emit(env, missing, name or Path(fn).stem)

    def save_preset(self):
        safe = "".join(ch for ch in (self.env.get("name") or "Environment") if ch.isalnum() or ch in " -_")
        fn, _ = QFileDialog.getSaveFileName(self, "Save environment preset",
                                            os.path.join(self._preset_dir(), f"{safe.strip() or 'Environment'}.json"),
                                            "Environment preset (*.json)")
        if not fn:
            return
        if not fn.lower().endswith(".json"):
            fn += ".json"
        self.settings.setValue("env_dir", os.path.dirname(fn))
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(env_to_preset(self.env, Path(fn).stem[:40]), f, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "Environment preset", f"Could not save the preset.\n\n{e}")

    def reset(self):
        keep = {"path": self.env.get("path", ""), "enabled": self.env["enabled"]}
        self.set_env({**copy.deepcopy(ENV_DEFAULTS), **keep})
        self._touched()

    def load_pano(self):
        d = str(self.settings.value("pano_dir", ""))
        d = d if d and os.path.isdir(d) else (
            QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home()))
        fn, _ = QFileDialog.getOpenFileName(
            self, "Load an equirectangular panorama (2:1)", d,
            "Panoramas (*.hdr *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
        if fn:
            self.settings.setValue("pano_dir", os.path.dirname(fn))
            self.load_requested.emit(fn)
