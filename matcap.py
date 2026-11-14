"""Gleek3Deek MatCaps: built-in and procedural shaders, custom MatCap parameters and baking, the editor and its live preview."""
from __future__ import annotations

import base64
import copy
import json
import math
import os
from pathlib import Path
import numpy as np
from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QFileDialog, QFormLayout, QGridLayout, QLineEdit, QMenu, QMessageBox, QPushButton, QSlider)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


# --- Procedural MatCaps: original shaders in the spirit of ZBrush material captures.
# Shading depends only on the view-space normal, so a material looks identical from every angle.
_MC_PRELUDE = """
  vec3 mcN = normalize(normalVCVSOutput);
  if (!gl_FrontFacing) mcN = -mcN;
  vec3 mcL = normalize(vec3(-0.45, 0.55, 0.70));
  float mcD = dot(mcN, mcL) * 0.5 + 0.5;
  vec3 mcH = normalize(mcL + vec3(0.0, 0.0, 1.0));
  float mcS = clamp(dot(mcN, mcH), 0.0, 1.0);
  float mcRim = pow(1.0 - clamp(mcN.z, 0.0, 1.0), 3.0);
  vec3 mcCol;
"""


_MC_OUT = "  fragOutput0 = vec4(clamp(mcCol, 0.0, 1.0), opacity);\n"


_MC_BODIES = [
    ("Red Wax", """
  vec3 deep = vec3(0.24, 0.015, 0.02), mid = vec3(0.78, 0.10, 0.07), lite = vec3(0.98, 0.38, 0.26);
  mcCol = mix(deep, mid, smoothstep(0.05, 0.60, mcD));
  mcCol = mix(mcCol, lite, smoothstep(0.55, 1.0, mcD) * 0.75);
  mcCol += vec3(0.55, 0.10, 0.06) * mcRim * 0.45;
  mcCol += vec3(1.0, 0.78, 0.72) * (pow(mcS, 40.0) * 0.55 + pow(mcS, 8.0) * 0.10);
"""),
    ("Clay Matte Green", """
  vec3 deep = vec3(0.05, 0.12, 0.06), mid = vec3(0.28, 0.50, 0.20), lite = vec3(0.66, 0.84, 0.48);
  mcCol = mix(deep, mid, smoothstep(0.05, 0.65, mcD));
  mcCol = mix(mcCol, lite, smoothstep(0.62, 1.0, mcD) * 0.65);
  float fill = clamp(dot(mcN, normalize(vec3(0.7, -0.35, 0.5))), 0.0, 1.0);
  mcCol += vec3(0.10, 0.18, 0.08) * fill * 0.5;
  mcCol += vec3(0.9, 1.0, 0.8) * pow(mcS, 5.0) * 0.05;
"""),
    ("RealSkin", """
  vec3 deep = vec3(0.30, 0.11, 0.09), mid = vec3(0.86, 0.58, 0.47), lite = vec3(1.0, 0.84, 0.74);
  mcCol = mix(deep, mid, smoothstep(0.05, 0.62, mcD));
  mcCol = mix(mcCol, lite, smoothstep(0.58, 1.0, mcD) * 0.7);
  mcCol += vec3(0.60, 0.14, 0.09) * pow(1.0 - clamp(mcN.z, 0.0, 1.0), 2.0) * 0.30;
  mcCol += vec3(1.0, 0.92, 0.86) * (pow(mcS, 14.0) * 0.22 + pow(mcS, 70.0) * 0.18);
"""),
    ("Framer", """
  vec2 p = mcN.xy;
  mcCol = mix(vec3(0.06, 0.065, 0.075), vec3(0.62, 0.64, 0.68), smoothstep(-0.3, 0.9, mcD));
  float bx = 1.0 - smoothstep(0.0, 0.06, abs(p.x + 0.38) - 0.22);
  float by = 1.0 - smoothstep(0.0, 0.06, abs(p.y - 0.42) - 0.16);
  mcCol += vec3(0.95) * bx * by * 0.85;
  mcCol += vec3(0.80, 0.85, 1.0) * smoothstep(0.55, 0.95, length(p)) * smoothstep(-0.2, 0.6, p.x) * 0.5;
"""),
    ("RoughMetal", """
  float up = mcN.y;
  vec3 sky = vec3(0.70, 0.73, 0.78), horizon = vec3(0.30, 0.31, 0.33), ground = vec3(0.07, 0.065, 0.06);
  mcCol = mix(ground, horizon, smoothstep(-0.7, 0.0, up));
  mcCol = mix(mcCol, sky, smoothstep(0.0, 0.9, up));
  mcCol *= vec3(0.92, 0.94, 1.0);
  mcCol += vec3(0.85, 0.88, 0.95) * pow(mcS, 9.0) * 0.35;
  mcCol += vec3(0.20, 0.21, 0.24) * mcRim * 0.5;
"""),
]


MATCAPS = [(name, _MC_PRELUDE + body + _MC_OUT) for name, body in _MC_BODIES]


# ---------------------------------------------------------------------------
# Custom MatCaps: procedural parameters (editor) or a baked image, saved as small JSON
# ---------------------------------------------------------------------------
PARAM_DEFAULTS = {                      # reproduces the built-in "Red Wax"
    "shadow": [0.24, 0.015, 0.02], "body": [0.78, 0.10, 0.07], "light": [0.98, 0.38, 0.26],
    "rim_color": [0.55, 0.10, 0.06], "spec_color": [1.0, 0.78, 0.72],
    "light_az": -33.0, "light_el": 33.5,
    "shadow_start": 0.05, "light_start": 0.55,
    "rim_strength": 0.45, "rim_power": 3.0,
    "spec_tight": 0.55, "spec_tight_pow": 40.0, "spec_broad": 0.10, "spec_broad_pow": 8.0,
}


# (key, label, min, max, step, decimals)
PARAM_SPECS = [
    ("light_az", "Light direction °", -180, 180, 1, 0),
    ("light_el", "Light height °", -80, 80, 1, 0),
    ("shadow_start", "Shadow spread", 0.0, 0.6, 0.01, 2),
    ("light_start", "Highlight spread", 0.3, 0.9, 0.01, 2),
    ("rim_strength", "Rim glow", 0.0, 1.5, 0.01, 2),
    ("rim_power", "Rim tightness", 0.8, 8.0, 0.1, 1),
    ("spec_tight", "Gloss amount", 0.0, 1.5, 0.01, 2),
    ("spec_tight_pow", "Gloss tightness", 4, 150, 1, 0),
    ("spec_broad", "Sheen amount", 0.0, 0.6, 0.01, 2),
    ("spec_broad_pow", "Sheen tightness", 2, 40, 1, 0),
]


COLOR_KEYS = [("shadow", "Shadow"), ("body", "Body"), ("light", "Light"),
              ("rim_color", "Rim"), ("spec_color", "Gloss")]


START_PRESETS = {                       # overrides on top of PARAM_DEFAULTS
    "Red Wax": {},
    "Clay Matte Green": {"shadow": [0.05, 0.12, 0.06], "body": [0.28, 0.50, 0.20],
                         "light": [0.66, 0.84, 0.48], "light_start": 0.62, "rim_strength": 0.0,
                         "spec_color": [0.9, 1.0, 0.8], "spec_tight": 0.0,
                         "spec_broad": 0.05, "spec_broad_pow": 5.0},
    "RealSkin": {"shadow": [0.30, 0.11, 0.09], "body": [0.86, 0.58, 0.47],
                 "light": [1.0, 0.84, 0.74], "light_start": 0.58,
                 "rim_color": [0.60, 0.14, 0.09], "rim_strength": 0.30, "rim_power": 2.0,
                 "spec_color": [1.0, 0.92, 0.86], "spec_tight": 0.18, "spec_tight_pow": 70.0,
                 "spec_broad": 0.22, "spec_broad_pow": 14.0},
}


IMAGE_MATCAP_RES = 32                   # baked table is RES x RES texels (kept small: fast to compile)


def clean_params(raw) -> dict:
    p = copy.deepcopy(PARAM_DEFAULTS)
    if isinstance(raw, dict):
        for key, _label, lo, hi, _step, _dec in PARAM_SPECS:
            if key in raw:
                try:
                    p[key] = min(hi, max(lo, float(raw[key])))
                except (TypeError, ValueError):
                    pass
        for key, _label in COLOR_KEYS:
            v = raw.get(key)
            if isinstance(v, (list, tuple)) and len(v) == 3:
                try:
                    p[key] = [min(1.0, max(0.0, float(x))) for x in v]
                except (TypeError, ValueError):
                    pass
    return p


def default_spec(name: str = "Custom") -> dict:
    return {"name": name, "type": "procedural", "params": copy.deepcopy(PARAM_DEFAULTS)}


def spec_to_preset(spec: dict) -> dict:
    d = {"gleek3deek_matcap": 1, "name": spec.get("name") or "Custom", "type": spec["type"],
         "params": clean_params(spec.get("params"))}
    if spec["type"] == "image":
        d["size"] = spec["n"]
        d["data"] = base64.b64encode(spec["data"]).decode("ascii")
    return d


def preset_to_spec(d) -> dict:
    if not isinstance(d, dict) or d.get("gleek3deek_matcap") != 1:
        raise ValueError("This is not a Gleek3Deek MatCap preset.")
    name = str(d.get("name") or "Custom")[:40]
    params = clean_params(d.get("params"))
    kind = d.get("type")
    if kind == "procedural":
        return {"name": name, "type": "procedural", "params": params}
    if kind == "image":
        n = int(d.get("size", 0))
        if not 4 <= n <= 64:
            raise ValueError("The preset's image size is not valid.")
        data = base64.b64decode(str(d.get("data", "")), validate=True)
        if len(data) != n * n * 3:
            raise ValueError("The preset's image data is the wrong length.")
        return {"name": name, "type": "image", "n": n, "data": data, "params": params}
    raise ValueError("Unknown MatCap type in preset.")


def _vec3(c) -> str:
    return f"vec3({c[0]:.4f}, {c[1]:.4f}, {c[2]:.4f})"


def procedural_matcap_code(p: dict) -> str:
    """GLSL for the 'Light::Impl' slot. All values are baked in as literals (no uniforms)."""
    az, el = math.radians(p["light_az"]), math.radians(p["light_el"])
    lx, ly, lz = math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)
    a, b = p["shadow_start"], p["light_start"]
    return f"""
  vec3 mcN = normalize(normalVCVSOutput);
  if (!gl_FrontFacing) mcN = -mcN;
  vec3 mcL = normalize(vec3({lx:.4f}, {ly:.4f}, {lz:.4f}));
  float mcD = dot(mcN, mcL) * 0.5 + 0.5;
  vec3 mcH = normalize(mcL + vec3(0.0, 0.0, 1.0));
  float mcS = clamp(dot(mcN, mcH), 0.0, 1.0);
  float mcRim = pow(1.0 - clamp(mcN.z, 0.0, 1.0), {p['rim_power']:.3f});
  vec3 mcCol = mix({_vec3(p['shadow'])}, {_vec3(p['body'])}, smoothstep({a:.3f}, {a + 0.55:.3f}, mcD));
  mcCol = mix(mcCol, {_vec3(p['light'])}, smoothstep({b:.3f}, {b + 0.45:.3f}, mcD) * 0.75);
  mcCol += {_vec3(p['rim_color'])} * mcRim * {p['rim_strength']:.3f};
  mcCol += {_vec3(p['spec_color'])} * (pow(mcS, {p['spec_tight_pow']:.2f}) * {p['spec_tight']:.3f}
                                      + pow(mcS, {p['spec_broad_pow']:.2f}) * {p['spec_broad']:.3f});
  fragOutput0 = vec4(clamp(mcCol, 0.0, 1.0), opacity);
"""


IMAGE_MATCAP_DEGREE = 15                # polynomial degree used for the full-detail image MatCap


def cheb_matcap_code(data: bytes, n: int, deg: int = IMAGE_MATCAP_DEGREE, damp: float = 0.0) -> str:
    """Turn a baked n x n colour table into plain shader arithmetic (no array, no texture).

    The colour is fitted as a 2-D Chebyshev polynomial in the view-space normal's x and y:
    colour(x, y) = sum_j T_j(y) * sum_i C[j][i] * T_i(x), with the coefficients written in as
    literals. A per-pixel table lookup was what made image MatCaps crawl on many GPUs; this is a
    few hundred multiply-adds, which is cheap everywhere. `damp` > 0 smooths ringing."""
    t = np.frombuffer(data, np.uint8).reshape(n, n, 3).astype(np.float64) / 255.0   # [y, x, rgb]
    u = np.linspace(-1.0, 1.0, n)
    pinv = np.linalg.pinv(np.polynomial.chebyshev.chebvander(u, deg))              # (deg+1, n)
    coef = np.stack([pinv @ t[..., c] @ pinv.T for c in range(3)], -1)             # [y order, x order, rgb]
    if damp:
        sig = np.sinc(np.arange(deg + 1) / (deg + 1)) ** damp
        coef = coef * sig[:, None, None] * sig[None, :, None]
    out = ["",
           "  vec3 mcN = normalize(normalVCVSOutput);",
           "  if (!gl_FrontFacing) mcN = -mcN;",
           "  float mx = clamp(mcN.x, -1.0, 1.0);",
           "  float my = clamp(mcN.y, -1.0, 1.0);",
           "  float tx0 = 1.0;", "  float tx1 = mx;", "  float ty0 = 1.0;", "  float ty1 = my;"]
    for k in range(2, deg + 1):
        out.append(f"  float tx{k} = 2.0 * mx * tx{k - 1} - tx{k - 2};")
        out.append(f"  float ty{k} = 2.0 * my * ty{k - 1} - ty{k - 2};")
    out.append("  vec3 mcCol = vec3(0.0);")
    for j in range(deg + 1):
        terms = [f"vec3({coef[j, i, 0]:.4f}, {coef[j, i, 1]:.4f}, {coef[j, i, 2]:.4f}) * tx{i}"
                 for i in range(deg + 1) if np.abs(coef[j, i]).max() > 2e-4]
        if terms:
            out.append(f"  mcCol += ty{j} * (" + " + ".join(terms) + ");")
    out.append("  fragOutput0 = vec4(clamp(mcCol, 0.0, 1.0), opacity);")
    return "\n".join(out) + "\n"


def custom_matcap_parts(spec: dict):
    """(impl, decl, alt) for a custom MatCap; alt = (impl, decl) simpler fallback or None.
    Nothing here needs global declarations, uniforms or textures."""
    if spec["type"] == "image":
        full = cheb_matcap_code(spec["data"], spec["n"])
        lite = cheb_matcap_code(spec["data"], spec["n"], deg=9, damp=0.5)
        return full, "", (lite, "")
    return procedural_matcap_code(clean_params(spec.get("params"))), "", None


def bake_matcap_array(arr: np.ndarray, n: int = IMAGE_MATCAP_RES) -> bytes:
    """arr: MxMx3 float image of a lit sphere (row 0 = top). Returns n*n*3 uint8, row 0 = bottom.
    Samples stay inside 96% of the sphere radius so the image's background never leaks in."""
    m = arr.shape[0]
    pad = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="edge")
    arr = sum(pad[dy:dy + m, dx:dx + m] for dy in range(3) for dx in range(3)) / 9.0   # 3x3 blur
    u = np.linspace(-1.0, 1.0, n, dtype=np.float32)
    x, y = np.meshgrid(u, u)                      # row index = y, bottom -> top
    k = np.minimum(1.0, 0.96 / np.maximum(np.hypot(x, y), 1e-6))
    px = (x * k * 0.5 + 0.5) * (m - 1)
    py = (0.5 - y * k * 0.5) * (m - 1)            # image rows run top -> bottom
    x0 = np.clip(np.floor(px).astype(int), 0, m - 2)
    y0 = np.clip(np.floor(py).astype(int), 0, m - 2)
    fx = (px - x0)[..., None]
    fy = (py - y0)[..., None]
    c = (arr[y0, x0] * (1 - fx) * (1 - fy) + arr[y0, x0 + 1] * fx * (1 - fy)
         + arr[y0 + 1, x0] * (1 - fx) * fy + arr[y0 + 1, x0 + 1] * fx * fy)
    return np.clip(c + 0.5, 0, 255).astype(np.uint8).tobytes()


def bake_image_matcap(img: QImage, n: int = IMAGE_MATCAP_RES) -> bytes:
    m = 128
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    s = min(w, h)
    img = img.copy((w - s) // 2, (h - s) // 2, s, s)              # centre square crop
    img = img.scaled(m, m, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    img = img.convertToFormat(QImage.Format_RGB888)
    bpl = img.bytesPerLine()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * m).reshape(m, bpl)[:, :m * 3]
    return bake_matcap_array(raw.reshape(m, m, 3).astype(np.float32), n)


def _smoothstep(a: float, b: float, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def render_matcap_sphere(spec: dict, size: int = 132) -> QImage:
    """Software preview of a MatCap on a sphere (numpy; same maths as the shader, no GPU needed)."""
    r = size / 2.0
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    x = (xs + 0.5 - r) / r
    y = -(ys + 0.5 - r) / r
    d2 = x * x + y * y
    inside = d2 < 1.0
    z = np.sqrt(np.clip(1.0 - d2, 0.0, 1.0))
    if spec.get("type") == "image":
        n = int(spec["n"])
        tab = np.frombuffer(spec["data"], np.uint8).reshape(n, n, 3).astype(np.float32) / 255.0
        px = np.clip((x * 0.5 + 0.5) * (n - 1), 0, n - 1.001)
        py = np.clip((y * 0.5 + 0.5) * (n - 1), 0, n - 1.001)      # row 0 = bottom
        x0, y0 = px.astype(int), py.astype(int)
        fx, fy = (px - x0)[..., None], (py - y0)[..., None]
        col = (tab[y0, x0] * (1 - fx) * (1 - fy) + tab[y0, x0 + 1] * fx * (1 - fy)
               + tab[y0 + 1, x0] * (1 - fx) * fy + tab[y0 + 1, x0 + 1] * fx * fy)
    else:
        p = clean_params(spec.get("params"))
        az, el = math.radians(p["light_az"]), math.radians(p["light_el"])
        L = np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)], np.float32)
        L /= np.linalg.norm(L)
        dot = x * L[0] + y * L[1] + z * L[2]
        dd = (dot * 0.5 + 0.5)[..., None]
        H = L + np.array([0.0, 0.0, 1.0], np.float32)
        H /= np.linalg.norm(H)
        sp = np.clip(x * H[0] + y * H[1] + z * H[2], 0.0, 1.0)[..., None]
        rim = np.power(1.0 - np.clip(z, 0.0, 1.0), p["rim_power"])[..., None]
        a, b = p["shadow_start"], p["light_start"]
        c = lambda k: np.array(p[k], np.float32)
        col = c("shadow") + (c("body") - c("shadow")) * _smoothstep(a, a + 0.55, dd)
        col = col + (c("light") - col) * (_smoothstep(b, b + 0.45, dd) * 0.75)
        col = col + c("rim_color") * rim * p["rim_strength"]
        col = col + c("spec_color") * (np.power(sp, p["spec_tight_pow"]) * p["spec_tight"]
                                       + np.power(sp, p["spec_broad_pow"]) * p["spec_broad"])
    col = np.clip(col, 0.0, 1.0)
    bg = 0.10 + 0.05 * (((xs // 11).astype(int) + (ys // 11).astype(int)) % 2)    # faint checker
    alpha = np.clip((1.0 - np.sqrt(d2)) * r, 0.0, 1.0)[..., None]                 # soft edge
    out = col * alpha + bg[..., None] * (1.0 - alpha)
    img = np.ascontiguousarray((out * 255.0 + 0.5).astype(np.uint8))
    return QImage(img.data, size, size, size * 3, QImage.Format_RGB888).copy()


class MatCapPreview(QLabel):
    """Small live sphere shown in the MatCap editor."""
    SIZE = 132

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip("Live preview of this MatCap on a sphere")
        self.setStyleSheet("border:1px solid #2f3947; border-radius:6px;")

    def set_spec(self, spec: dict):
        try:
            self.setPixmap(QPixmap.fromImage(render_matcap_sphere(spec, self.SIZE)))
        except Exception:                         # a preview must never break the editor
            self.clear()


class MatCapEditor(QWidget):
    """Floating editor: sliders and colours for a procedural MatCap, plus preset and image loading."""
    changed = Signal(object)                      # emits a spec dict (debounced)

    def __init__(self, parent, spec: dict):
        super().__init__(parent)
        self.setWindowTitle("MatCap editor")
        self.setMinimumWidth(300)
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.spec = copy.deepcopy(spec)
        self._sliders: dict = {}
        self._labels: dict = {}
        self._color_btns: dict = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.changed.emit(copy.deepcopy(self.spec)))

        root = QVBoxLayout(self)
        root.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._name_edited)
        row.addWidget(self.name_edit, 1)
        start = QPushButton("Start from ▾")
        menu = QMenu(start)
        for nm in START_PRESETS:
            menu.addAction(nm, lambda _=False, nm=nm: self.start_from(nm))
        start.setMenu(menu)
        row.addWidget(start)
        root.addLayout(row)

        row = QHBoxLayout()
        for text, fn in (("Load preset…", self.load_preset), ("Save preset…", self.save_preset),
                         ("Load image MatCap…", self.load_image)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        root.addLayout(row)

        self.preview = MatCapPreview()
        root.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        self.note = QLabel("")
        self.note.setObjectName("barLabel")
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.back_btn = QPushButton("Switch back to the procedural controls")
        self.back_btn.clicked.connect(self.use_procedural)
        root.addWidget(self.back_btn)

        grid = QGridLayout()
        for i, (key, label) in enumerate(COLOR_KEYS):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=key, lb=label: self.pick_color(k, lb))
            self._color_btns[key] = b
            grid.addWidget(b, i // 3, i % 3)
        root.addLayout(grid)

        form = QFormLayout()
        for key, label, lo, hi, step, dec in PARAM_SPECS:
            s = QSlider(Qt.Horizontal)
            s.setRange(round(lo / step), round(hi / step))
            lab = QLabel("")
            lab.setFixedWidth(48)
            s.valueChanged.connect(
                lambda v, k=key, st=step, d=dec: self._slider_changed(k, v * st, d))
            holder = QHBoxLayout()
            holder.addWidget(s, 1)
            holder.addWidget(lab)
            form.addRow(label, holder)
            self._sliders[key] = (s, step, dec)
            self._labels[key] = lab
        root.addLayout(form)

        root.addStretch(1)
        self.set_spec(self.spec)

    # ----- state <-> widgets
    def set_spec(self, spec: dict):
        self.spec = copy.deepcopy(spec)
        self.spec["params"] = clean_params(self.spec.get("params"))
        self.name_edit.blockSignals(True)
        self.name_edit.setText(self.spec.get("name", "Custom"))
        self.name_edit.blockSignals(False)
        for key, (s, step, dec) in self._sliders.items():
            v = self.spec["params"][key]
            s.blockSignals(True)
            s.setValue(round(v / step))
            s.blockSignals(False)
            self._labels[key].setText(f"{v:.{dec}f}")
        for key in self._color_btns:
            self._style_color(key)
        is_img = self.spec["type"] == "image"
        for s, _st, _d in self._sliders.values():
            s.setEnabled(not is_img)
        for b in self._color_btns.values():
            b.setEnabled(not is_img)
        self.back_btn.setVisible(is_img)
        self.note.setVisible(is_img)
        self.note.setText(f"Image MatCap ({self.spec.get('n', 0)}×{self.spec.get('n', 0)} baked). "
                          "Colour and light controls are off while an image is used." if is_img else "")
        self.preview.set_spec(self.spec)

    def _style_color(self, key: str):
        c = self.spec["params"][key]
        lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        self._color_btns[key].setStyleSheet(
            f"background:rgb({int(c[0] * 255)},{int(c[1] * 255)},{int(c[2] * 255)});"
            f"color:{'#101418' if lum > 0.55 else '#f2f5f8'};border:1px solid #3a4656;")

    def _touched(self):
        self.preview.set_spec(self.spec)          # instant; only the 3D shader recompile is debounced
        self._timer.start(120)                    # debounce: shader recompiles on every change

    def _name_edited(self, text: str):
        self.spec["name"] = text.strip() or "Custom"
        self._touched()

    def _slider_changed(self, key: str, value: float, dec: int):
        self.spec["params"][key] = value
        self._labels[key].setText(f"{value:.{dec}f}")
        self._touched()

    def pick_color(self, key: str, label: str):
        c0 = self.spec["params"][key]
        c = QColorDialog.getColor(QColor.fromRgbF(c0[0], c0[1], c0[2]), self, f"{label} colour")
        if c.isValid():
            self.spec["params"][key] = [c.redF(), c.greenF(), c.blueF()]
            self._style_color(key)
            self._touched()

    def start_from(self, name: str):
        params = copy.deepcopy(PARAM_DEFAULTS)
        params.update(copy.deepcopy(START_PRESETS[name]))
        self.set_spec({"name": self.spec.get("name", "Custom"), "type": "procedural", "params": params})
        self._touched()

    def use_procedural(self):
        self.spec["type"] = "procedural"
        self.set_spec(self.spec)
        self._touched()

    # ----- files
    def _dir(self) -> str:
        d = str(self.settings.value("matcap_dir", ""))
        return d if d and os.path.isdir(d) else (
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home()))

    def load_preset(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Load MatCap preset", self._dir(),
                                            "MatCap preset (*.json)")
        if not fn:
            return
        self.settings.setValue("matcap_dir", os.path.dirname(fn))
        try:
            with open(fn, "r", encoding="utf-8") as f:
                spec = preset_to_spec(json.load(f))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "MatCap preset", f"Could not load this preset.\n\n{e}")
            return
        self.set_spec(spec)
        self._timer.start(0)

    def save_preset(self):
        name = self.spec.get("name") or "Custom"
        safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip() or "matcap"
        fn, _ = QFileDialog.getSaveFileName(self, "Save MatCap preset",
                                            os.path.join(self._dir(), f"{safe}.json"),
                                            "MatCap preset (*.json)")
        if not fn:
            return
        if not fn.lower().endswith(".json"):
            fn += ".json"
        self.settings.setValue("matcap_dir", os.path.dirname(fn))
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(spec_to_preset(self.spec), f, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "MatCap preset", f"Could not save the preset.\n\n{e}")

    def load_image(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Load MatCap image (a lit sphere)", self._dir(),
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        if not fn:
            return
        self.settings.setValue("matcap_dir", os.path.dirname(fn))
        img = QImage(fn)
        if img.isNull():
            QMessageBox.warning(self, "MatCap image", "That image could not be read.")
            return
        try:
            data = bake_image_matcap(img)
        except Exception as e:
            QMessageBox.warning(self, "MatCap image", f"Could not use that image.\n\n{e}")
            return
        self.set_spec({"name": Path(fn).stem[:40], "type": "image", "n": IMAGE_MATCAP_RES,
                       "data": data, "params": self.spec.get("params")})
        self._timer.start(0)
