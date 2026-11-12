#!/usr/bin/env python3
"""
Gleek3Deek - ultra-light native 3D asset manager + viewer.

    pip install PySide6 vtk numpy
    # optional extras:
    pip install assimp-py      # in-process FBX / 3DS / LWO / DAE / etc. via Assimp
    pip install cadquery       # STEP/STP fallback if VTK has no OpenCASCADE module

    python main.py [optional_folder_or_file]
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import math
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import threading
import traceback
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QByteArray, QDir, QEasingCurve, QEvent, QFile, QMimeData, QObject, QRunnable, QSettings, QSize,
                            QStandardPaths, Qt, QThreadPool, QTimer, QUrl, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter,
                           QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtCore import QPointF
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QTextBrowser, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGridLayout, QInputDialog, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSizePolicy,
                               QSlider, QTabWidget)
from PySide6.QtWidgets import QDockWidget, QScrollArea, QTabBar
from PySide6.QtWidgets import (QApplication, QFileSystemModel, QFrame,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QListView, QMainWindow,
                               QSplitter, QStackedWidget, QToolButton,
                               QTreeView, QVBoxLayout, QWidget, QAbstractItemView)

# --- VTK (import only what we need: faster startup than `import vtk`) -------
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401  (registers GL backend)
import vtkmodules.vtkInteractionStyle  # noqa: F401  (registers styles)
import vtkmodules.vtkRenderingFreeType  # noqa: F401  (text for the axes gizmo)
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.util import numpy_support
from vtkmodules.vtkCommonCore import VTK_UNSIGNED_CHAR, vtkPoints
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkImageData, vtkPolyData
from vtkmodules.vtkFiltersCore import (vtkAppendPolyData, vtkCleanPolyData, vtkPolyDataNormals,
                                       vtkQuadricDecimation, vtkTriangleFilter)
from vtkmodules.vtkFiltersGeometry import vtkCompositeDataGeometryFilter
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkIOGeometry import (vtkGLTFReader, vtkOBJReader,
                                      vtkSTLReader)
from vtkmodules.vtkIOPLY import vtkPLYReader
from vtkmodules.vtkRenderingCore import (vtkActor, vtkPolyDataMapper,
                                         vtkRenderer, vtkRenderWindow,
                                         vtkLight, vtkSkybox, vtkTexture, vtkWindowToImageFilter)
from vtkmodules.vtkIOImage import vtkImageReader2Factory
from vtkmodules.vtkFiltersSources import vtkOutlineSource, vtkPlaneSource
try:                                          # exporters: optional so the viewer never depends on them
    from vtkmodules.vtkIOGeometry import vtkOBJWriter, vtkSTLWriter
except Exception:  # pragma: no cover
    vtkOBJWriter = vtkSTLWriter = None
try:
    from vtkmodules.vtkIOPLY import vtkPLYWriter
except Exception:  # pragma: no cover
    vtkPLYWriter = None
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter
try:
    from vtkmodules.vtkIOImage import vtkHDRReader
except Exception:  # pragma: no cover
    vtkHDRReader = None
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

# Scene importers (materials/textures): glTF + OBJ/MTL
try:
    from vtkmodules.vtkIOImport import vtkGLTFImporter, vtkOBJImporter
except Exception:  # pragma: no cover
    vtkGLTFImporter = vtkOBJImporter = None

# Optional VTK OpenCASCADE module (not in every wheel)
try:
    from vtkmodules.vtkIOOCCT import vtkOCCTReader
except Exception:  # pragma: no cover
    vtkOCCTReader = None

APP_NAME = "Gleek3Deek"

# ---------------------------------------------------------------------------
# About dialog text. EDIT FREELY: everything the About dialog shows comes from this block.
# ---------------------------------------------------------------------------
ABOUT = {
    "app_name": APP_NAME,
    "tagline": "A fast, minimal 3D asset viewer and manager.",
    "version": "0.6.8",                      # leave empty to hide; set e.g. "0.4.0" when you are ready
    # --- who made it
    "author_heading": "Created by",
    "author_name": "Mark Billson",
    "author_alias": "Astroskiffle",
    "author_note": "https://github.com/astroskiffle/",                  # optional extra line, e.g. a website or contact address
    # --- legal
    "legal_heading": "Legal",
    "copyright": "Copyright (c) 2026 Mark Billson (Astroskiffle)",
    "legal_notice": ("[Placeholder]"
                     ""),
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
        ("CadQuery (optional)", "Apache-2.0", "https://github.com/CadQuery/cadquery"),
    ],
    "third_party_note": "Each project remains under its own licence; see its website for the full terms.",
    "close_label": "Close",
}

# --- VTK messages: never pop up a window; log to a file and surface the useful part in our UI
_tls = threading.local()
_VTK_LOG_PATH = os.path.join(tempfile.gettempdir(), "gleek3deek_vtk.log")
try:
    from vtkmodules.vtkCommonCore import vtkFileOutputWindow, vtkOutputWindow
    _vtk_win = vtkFileOutputWindow()
    _vtk_win.SetFileName(_VTK_LOG_PATH)
    _vtk_win.SetFlush(1)
    vtkOutputWindow.SetInstance(_vtk_win)
except Exception:  # pragma: no cover
    pass


def _log_size() -> int:
    try:
        return os.path.getsize(_VTK_LOG_PATH)
    except OSError:
        return 0


def _vtk_hint() -> str:
    """Pull the human-readable part of VTK errors raised during the current load."""
    try:
        with open(_VTK_LOG_PATH, "rb") as f:
            f.seek(getattr(_tls, "log_pos", 0))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    msgs = []
    for k, ln in enumerate(lines[:-1]):
        if ln.startswith("ERROR: In") and k + 1 < len(lines):
            m = lines[k + 1].split("): ", 1)[-1].strip()
            if m and m not in msgs:
                msgs.append(m)
    return ("\n\nDetails: " + " | ".join(msgs[:2])) if msgs else ""


def _shader_error_since(pos: int) -> str:
    """Text VTK logged after `pos` if a shader failed to compile/link, else ''."""
    try:
        with open(_VTK_LOG_PATH, "rb") as f:
            f.seek(pos)
            txt = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    low = txt.lower()
    return txt if ("error" in low and ("shader" in low or "glsl" in low or "compile" in low)) else ""


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
# glTF compatibility: VTK can't read EXT_texture_webp, so convert those textures to PNG
# in a temp folder (GLB only) and hand VTK an equivalent .gltf + .bin + .png set.
# ---------------------------------------------------------------------------
def _fix_glb_webp(path: str):
    with open(path, "rb") as f:
        if f.read(4) != b"glTF":
            return path, None
        f.seek(12)
        ln, _typ = struct.unpack("<II", f.read(8))
        raw = f.read(ln)                           # first chunk is always the JSON
        if b"EXT_texture_webp" not in raw:
            return path, None
        doc = json.loads(raw.decode("utf-8"))
        binc = None
        while True:
            ch = f.read(8)
            if len(ch) < 8:
                break
            ln, typ = struct.unpack("<II", ch)
            if typ == 0x004E4942:                  # BIN
                binc = f.read(ln)
                break
            f.seek(ln, 1)
    tmp = tempfile.mkdtemp(prefix="gleek_glb_")
    try:
        for key in ("extensionsUsed", "extensionsRequired"):
            if key in doc:
                doc[key] = [e for e in doc[key] if e != "EXT_texture_webp"]
                if not doc[key]:
                    del doc[key]
        for t in doc.get("textures", []):
            ext = t.get("extensions", {})
            w = ext.pop("EXT_texture_webp", None)
            if w is not None:
                t["source"] = w.get("source", t.get("source"))
            if not ext:
                t.pop("extensions", None)
        views = doc.get("bufferViews", [])
        for i, im in enumerate(doc.get("images", [])):
            if "bufferView" not in im or binc is None:
                continue
            v = views[im["bufferView"]]
            off = v.get("byteOffset", 0)
            data = binc[off:off + v["byteLength"]]
            if data[8:12] != b"WEBP":
                continue
            qi = QImage.fromData(data)
            if qi.isNull():
                raise LoadError("This model uses WebP textures and Qt's WebP decoder is unavailable.")
            name = f"img_{i}.png"
            qi.save(os.path.join(tmp, name), "PNG")
            im.pop("bufferView")
            im["uri"] = name
            im["mimeType"] = "image/png"
        if binc is not None and doc.get("buffers"):
            with open(os.path.join(tmp, "scene.bin"), "wb") as bf:
                bf.write(binc)
            doc["buffers"][0]["uri"] = "scene.bin"
        out = os.path.join(tmp, "scene.gltf")
        with open(out, "w", encoding="utf-8") as jf:
            json.dump(doc, jf)
        return out, tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


@contextmanager
def _glb_compat(path: str):
    tmp = None
    out = path
    try:
        if path.lower().endswith(".glb"):
            try:
                out, tmp = _fix_glb_webp(path)
            except LoadError:
                raise
            except Exception:
                out, tmp = path, None
        yield out
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Format registry
# ---------------------------------------------------------------------------
NATIVE = {".stl", ".ply", ".obj", ".gltf", ".glb"}
CAD = {".step", ".stp"}
# Everything below is routed through Assimp (assimp-py, or the assimp CLI as a fallback).
# Which of these actually open depends on the Assimp build inside your assimp-py wheel;
# anything it can't read simply shows the error box and keeps the generic cube icon.
ASSIMP = {
    # modern interchange
    ".fbx", ".dae", ".usd", ".usda", ".usdc", ".usdz", ".3mf", ".amf", ".x3d", ".x3db",
    # CAD / BIM / 3D printing
    ".dxf", ".ifc",
    # DCC and legacy modellers
    ".3ds", ".ase", ".lwo", ".lws", ".lxo", ".ac", ".ac3d", ".acc", ".b3d", ".cob", ".scn",
    ".ms3d", ".ndo", ".nff", ".off", ".sib", ".x", ".xgl", ".zgl", ".m3d", ".q3o", ".q3d",
    ".irr", ".irrmesh", ".ogex", ".pmx", ".mesh.xml",
    # game engines
    ".md2", ".md3", ".md5mesh", ".mdc", ".mdl", ".bsp", ".smd", ".vta", ".hmp", ".ter",
}
# Skeleton / motion data only: recognised, but there is no surface to draw.
NO_MESH = {".bvh": "BVH motion capture", ".csm": "Character Studio motion"}
BLENDER = {".blend"}
UNSUPPORTED_PROPRIETARY = {
    ".c4d": "Cinema 4D", ".mb": "Maya (binary)", ".ma": "Maya (ASCII)",
    ".max": "3ds Max",
}
ALL_EXTS = NATIVE | CAD | ASSIMP | BLENDER | set(UNSUPPORTED_PROPRIETARY) | set(NO_MESH)


def asset_ext(name: str) -> str:
    """Lower-case extension, treating the double extension .mesh.xml (Ogre) as one."""
    n = os.path.basename(name).lower()
    return ".mesh.xml" if n.endswith(".mesh.xml") else os.path.splitext(n)[1]

EXT_COLORS = {
    **{e: "#4FC3F7" for e in NATIVE},
    **{e: "#FFB74D" for e in CAD},
    **{e: "#81C784" for e in ASSIMP},
    **{e: "#BA68C8" for e in BLENDER},
    **{e: "#E57373" for e in UNSUPPORTED_PROPRIETARY},
    **{e: "#90A4AE" for e in NO_MESH},
}


class LoadError(Exception):
    """User-presentable load failure."""


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def arrays_to_polydata(verts: np.ndarray, faces: np.ndarray) -> vtkPolyData:
    verts = np.ascontiguousarray(verts, dtype=np.float32).reshape(-1, 3)
    faces = np.ascontiguousarray(faces, dtype=np.int64)
    n, k = faces.shape
    pts = vtkPoints()
    pts.SetData(numpy_support.numpy_to_vtk(verts, deep=True))
    offsets = np.arange(0, (n + 1) * k, k, dtype=np.int64)
    cells = vtkCellArray()
    cells.SetData(numpy_support.numpy_to_vtkIdTypeArray(offsets, deep=True),
                  numpy_support.numpy_to_vtkIdTypeArray(faces.ravel(), deep=True))
    pd = vtkPolyData()
    pd.SetPoints(pts)
    pd.SetPolys(cells)
    return pd


def flatten_to_polydata(data_obj) -> vtkPolyData:
    """Collapse any VTK dataset (multiblock assemblies included) into polydata."""
    if isinstance(data_obj, vtkPolyData):
        return data_obj
    geo = vtkCompositeDataGeometryFilter()
    geo.SetInputData(data_obj)
    geo.Update()
    return geo.GetOutput()


def finalize(pd: vtkPolyData) -> vtkPolyData:
    if pd is None or pd.GetNumberOfPoints() == 0:
        raise LoadError("File parsed but contains no renderable geometry." + _vtk_hint())
    orig_points = pd.GetNumberOfPoints()          # before normals may split vertices
    if pd.GetPointData().GetNormals() is None and pd.GetNumberOfPolys() > 0 \
            and pd.GetNumberOfPolys() < 3_000_000:
        nrm = vtkPolyDataNormals()
        nrm.SetInputData(pd)
        nrm.SetFeatureAngle(60.0)
        nrm.SplittingOn()
        nrm.ConsistencyOff()
        nrm.AutoOrientNormalsOff()
        nrm.Update()
        pd = nrm.GetOutput()
    pd._orig_points = orig_points
    return pd


# ---------------------------------------------------------------------------
# Loaders (all run on worker threads; they never touch Qt or the render window)
# ---------------------------------------------------------------------------
def _simple_reader(reader, path: str) -> vtkPolyData:
    reader.SetFileName(path)
    reader.Update()
    return reader.GetOutput()


def _load_gltf(path: str) -> vtkPolyData:
    r = vtkGLTFReader()
    r.SetFileName(path)
    r.Update()
    return flatten_to_polydata(r.GetOutput())


def _load_step(path: str) -> vtkPolyData:
    errors = []
    if vtkOCCTReader is not None:
        try:
            r = vtkOCCTReader()
            r.SetFileName(path)
            r.SetFileFormatToSTEP()
            r.SetLinearDeflection(0.1)
            r.SetAngularDeflection(0.5)
            r.Update()
            return flatten_to_polydata(r.GetOutput())
        except Exception as e:
            errors.append(f"vtkOCCTReader: {e}")
    try:
        import cadquery as cq  # type: ignore
        wp = cq.importers.importStep(path)
        comp = cq.Compound.makeCompound(list(wp.vals()))
        verts, tris = comp.tessellate(0.05, 0.3)
        v = np.array([(p.x, p.y, p.z) for p in verts], dtype=np.float32)
        return arrays_to_polydata(v, np.array(tris, dtype=np.int64))
    except ImportError:
        errors.append("cadquery not installed")
    except Exception as e:
        errors.append(f"cadquery: {e}")
    raise LoadError("STEP/STP needs an OpenCASCADE backend.\n"
                    "Install one:  pip install cadquery   (or a VTK build with IOOCCT).\n\n"
                    + "\n".join(errors))


def _run(cmd: list[str], timeout: int = 600):
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=flags)


def _faces_array(idx) -> np.ndarray:
    """assimp-py index layouts vary (nested, flat, ragged with line/point prims): normalise to Nx3."""
    try:
        a = np.asarray(idx)
        if a.dtype != object:
            if a.ndim == 2 and a.shape[1] == 3:
                return a.astype(np.int64)
            if a.ndim == 1 and a.size and a.size % 3 == 0 and not hasattr(idx[0], "__len__"):
                return a.reshape(-1, 3).astype(np.int64)
    except Exception:
        pass
    tris = []
    for f in idx:
        f = list(f) if hasattr(f, "__len__") else []
        for i in range(1, len(f) - 1):          # fan-triangulate polygons, drop lines/points
            tris.append((f[0], f[i], f[i + 1]))
    return np.array(tris, dtype=np.int64).reshape(-1, 3)


def _material_color(mat):
    if not hasattr(mat, "items"):
        return None
    for k, v in mat.items():
        ku = str(k).upper()
        if ("DIFFUSE" in ku or "BASE_COLOR" in ku) and "TEXTURE" not in ku:
            try:
                a = np.asarray(v, dtype=np.float32).ravel()
            except Exception:
                continue
            if a.size in (3, 4):
                return tuple(float(x) for x in np.clip(a[:3], 0, 1))
    return None


def _material_texture(mat, mdir: str):
    tex = mat.get("TEXTURES") if hasattr(mat, "get") else None
    if not isinstance(tex, dict):
        return None
    for k in (1, 12, "1", "12"):                  # aiTextureType DIFFUSE / BASE_COLOR
        lst = tex.get(k)
        if not lst:
            continue
        name = lst[0] if isinstance(lst, (list, tuple)) else lst
        if isinstance(name, str) and not name.startswith("*"):
            for cand in (os.path.join(mdir, name),
                         os.path.join(mdir, os.path.basename(name.replace("\\", "/")))):
                if os.path.isfile(cand):
                    return cand
    return None


def _assimp_py_meshes(path: str) -> list:
    import assimp_py  # type: ignore
    flags = assimp_py.Process_Triangulate | assimp_py.Process_JoinIdenticalVertices
    scene = assimp_py.import_file(path, flags)
    mats = list(getattr(scene, "materials", None) or [])
    mdir = os.path.dirname(path)
    out = []
    for m in scene.meshes:
        v = np.asarray(m.vertices, dtype=np.float32).reshape(-1, 3)
        n = len(v)
        faces = _faces_array(m.indices) if n else np.empty((0, 3), np.int64)
        if len(faces):
            faces = faces[(faces >= 0).all(1) & (faces < n).all(1)]
        if len(faces) == 0:
            continue
        pd = arrays_to_polydata(v, faces)
        try:                                      # normals
            nr = np.asarray(m.normals, dtype=np.float32)
            if nr.size == n * 3:
                pd.GetPointData().SetNormals(
                    numpy_support.numpy_to_vtk(np.ascontiguousarray(nr.reshape(n, 3)), deep=True))
        except Exception:
            pass
        try:                                      # vertex colours (ignore all-white defaults)
            cols = getattr(m, "colors", None)
            if cols is not None and len(cols):
                c = np.asarray(cols, dtype=np.float32)
                c = c[0] if c.ndim == 3 else c
                if c.ndim == 2 and c.shape[0] == n and c.shape[1] in (3, 4) \
                        and not (c[:, :3].min() > 0.99):
                    arr = numpy_support.numpy_to_vtk(np.ascontiguousarray(
                        (np.clip(c, 0, 1) * 255).astype(np.uint8)), deep=True)
                    arr.SetName("Colors")
                    pd.GetPointData().SetScalars(arr)
        except Exception:
            pass
        has_uv = False
        try:                                      # texture coordinates
            tc = getattr(m, "texcoords", None)
            if tc is not None and len(tc):
                t = np.asarray(tc[0], dtype=np.float32)
                if t.ndim == 2 and t.shape[0] == n and t.shape[1] >= 2:
                    uv = numpy_support.numpy_to_vtk(np.ascontiguousarray(t[:, :2]), deep=True)
                    uv.SetName("TCoords")
                    pd.GetPointData().SetTCoords(uv)
                    has_uv = True
        except Exception:
            pass
        try:
            pd = finalize(pd)
        except LoadError:
            continue
        mi = getattr(m, "material_index", -1)
        mat = mats[mi] if isinstance(mi, int) and 0 <= mi < len(mats) else None
        out.append({"pd": pd,
                    "color": _material_color(mat) if mat is not None else None,
                    "texture": _material_texture(mat, mdir) if (mat is not None and has_uv) else None,
                    "mat": mi if mat is not None else -1,
                    "name": str(getattr(m, "name", "") or "")})
    if not out:
        raise LoadError("Assimp loaded the file but found no triangle meshes.")
    return out


def _make_texture(p: str):
    r = vtkImageReader2Factory.CreateImageReader2(p)
    if r is None:
        return None
    r.SetFileName(p)
    r.Update()
    t = vtkTexture()
    t.SetInputConnection(r.GetOutputPort())
    t.InterpolateOn()
    t.MipmapOn()
    return t


def _assimp_actors(path: str) -> list:
    cache, actors = {}, []
    for info in _assimp_py_meshes(path):
        a = make_actor(info["pd"])
        if info.get("mat", -1) >= 0:
            a._mat = ("assimp", info["mat"])
        a._name = info.get("name", "")
        m = a.GetMapper()
        tp = info["texture"]
        if tp:
            if tp not in cache:
                try:
                    cache[tp] = _make_texture(tp)
                except Exception:
                    cache[tp] = None
            if cache[tp] is not None:
                a.SetTexture(cache[tp])
                m.ScalarVisibilityOff()
                a.GetProperty().SetColor(1, 1, 1)
                actors.append(a)
                continue
        if not m.GetScalarVisibility() and info["color"]:
            a.GetProperty().SetColor(*info["color"])
        actors.append(a)
    return actors


def _load_assimp(path: str) -> vtkPolyData:
    errors = []
    # 1) in-process via assimp-py
    try:
        parts = vtkAppendPolyData()
        for info in _assimp_py_meshes(path):
            parts.AddInputData(info["pd"])
        parts.Update()
        return parts.GetOutput()
    except ImportError:
        errors.append("assimp-py not installed (pip install assimp-py)")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)[-1]
        errors.append(f"assimp-py: {type(e).__name__}: {e} (main.py line {tb.lineno})")
    # 2) assimp CLI -> OBJ
    exe = shutil.which("assimp")
    if exe:
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out.obj")
            res = _run([exe, "export", path, out])
            if os.path.exists(out):
                return _simple_reader(vtkOBJReader(), out)
            errors.append(f"assimp CLI: {res.stderr.strip() or 'export failed'}")
    raise LoadError(f"Could not read {asset_ext(path).upper()} via Assimp.\n\n"
                    + "\n".join(errors))


def _find_blender() -> str | None:
    env = os.environ.get("BLENDER_PATH")
    if env and os.path.exists(env):
        return env
    exe = shutil.which("blender")
    if exe:
        return exe
    for p in (r"C:\Program Files\Blender Foundation",):
        if os.path.isdir(p):
            for d in sorted(os.listdir(p), reverse=True):
                c = os.path.join(p, d, "blender.exe")
                if os.path.exists(c):
                    return c
    mac = "/Applications/Blender.app/Contents/MacOS/Blender"
    return mac if os.path.exists(mac) else None


def _load_blend(path: str) -> vtkPolyData:
    exe = _find_blender()
    if not exe:
        try:
            return _load_assimp(path)             # Assimp's legacy .blend reader (older files only)
        except LoadError as e:
            raise LoadError(".blend files are converted through Blender's CLI.\n"
                            "Install Blender and add it to PATH, or set BLENDER_PATH.\n\n"
                            "Assimp's built-in fallback also failed:\n" + str(e))
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out.glb")
        expr = f"import bpy; bpy.ops.export_scene.gltf(filepath=r'{out}', export_format='GLB')"
        res = _run([exe, "-b", path, "--python-expr", expr])
        if not os.path.exists(out):
            raise LoadError("Blender failed to convert the file.\n\n"
                            + (res.stderr or res.stdout)[-600:])
        return _load_gltf(out)


def load_any(path: str) -> vtkPolyData:
    ext = asset_ext(path)
    if ext == ".stl":
        pd = _simple_reader(vtkSTLReader(), path)
    elif ext == ".ply":
        pd = _simple_reader(vtkPLYReader(), path)
    elif ext == ".obj":
        pd = _simple_reader(vtkOBJReader(), path)
        _obj_vertex_colors(path, pd)
    elif ext in (".gltf", ".glb"):
        pd = _load_gltf(path)
    elif ext in CAD:
        pd = _load_step(path)
    elif ext in ASSIMP:
        pd = _load_assimp(path)
    elif ext in BLENDER:
        pd = _load_blend(path)
    elif ext in UNSUPPORTED_PROPRIETARY:
        raise LoadError(f"{UNSUPPORTED_PROPRIETARY[ext]} ({ext}) is a closed, proprietary "
                        "format with no licensed open reader.\n\n"
                        "Export it from the source application as glTF/GLB, FBX or OBJ "
                        "and open that instead.")
    elif ext in NO_MESH:
        raise LoadError(f"{NO_MESH[ext]} ({ext}) files contain skeleton animation only, "
                        "so there is no surface to display.")
    else:
        raise LoadError(f"Unsupported file type: {ext or '(none)'}")
    return finalize(pd)


# ---------------------------------------------------------------------------
# Scene loading: textured actors via importers, plain mesh as fallback
# ---------------------------------------------------------------------------
def _color_array(ds):
    """Find per-vertex or per-face colours: uchar RGB(A), or any 3/4-comp array named like a colour."""
    for data, mode in ((ds.GetPointData(), "point"), (ds.GetCellData(), "cell")):
        cands = [data.GetScalars()] + [data.GetArray(i) for i in range(data.GetNumberOfArrays())]
        for a in cands:
            if a is None or a.GetNumberOfComponents() not in (3, 4):
                continue
            name = (a.GetName() or "").lower()
            if a.GetDataType() == VTK_UNSIGNED_CHAR or any(k in name for k in ("color", "colour", "rgb")):
                if not a.GetName():
                    a.SetName("Colors")
                return a, mode
    return None, None


def _apply_color_mode(mapper, ds) -> bool:
    arr, mode = _color_array(ds)
    if arr is None:
        return False
    if mode == "point":
        ds.GetPointData().SetActiveScalars(arr.GetName())
        mapper.SetScalarModeToUsePointData()
    else:
        ds.GetCellData().SetActiveScalars(arr.GetName())
        mapper.SetScalarModeToUseCellData()
    mapper.SetColorModeToDirectScalars()
    mapper.ScalarVisibilityOn()
    return True


def _obj_vertex_colors(path: str, pd: vtkPolyData):
    """vtkOBJReader ignores the common 'v x y z r g b' extension; read it ourselves."""
    try:
        with open(path, "rb") as f:
            rows = [ln[2:].split()[:6] for ln in f if ln.startswith(b"v ")]
        if not rows or len(rows) != pd.GetNumberOfPoints() or len(rows[0]) < 6:
            return
        c = np.array(rows, dtype=np.float32)[:, 3:6]
        if c.max() <= 1.0:
            c *= 255.0
        arr = numpy_support.numpy_to_vtk(np.ascontiguousarray(np.clip(c, 0, 255).astype(np.uint8)), deep=True)
        arr.SetName("Colors")
        pd.GetPointData().SetScalars(arr)
    except Exception:
        pass


def make_actor(pd: vtkPolyData) -> vtkActor:
    m = vtkPolyDataMapper()
    m.SetInputData(pd)
    if not _apply_color_mode(m, pd):
        m.ScalarVisibilityOff()
    a = vtkActor()
    a.SetMapper(m)
    a._faces = _face_count(pd)
    a._verts = getattr(pd, "_orig_points", None) or pd.GetNumberOfPoints()
    p = a.GetProperty()
    p.SetColor(0.78, 0.82, 0.88)
    p.SetSpecular(0.25)
    p.SetSpecularPower(30)
    return a


def _mapper_data(m):
    """The dataset feeding a mapper. Tries GetInput() first, then GetInputAsDataSet()."""
    for name in ("GetInput", "GetInputAsDataSet"):
        fn = getattr(m, name, None)
        if fn is None:
            continue
        try:
            ds = fn()
        except Exception:
            continue
        if ds is not None:
            return ds
    return None


def _face_count(ds) -> int:
    """Polygon count (triangle strips included); other dataset types fall back to cell count."""
    if ds is None:
        return 0
    if hasattr(ds, "GetNumberOfPolys"):
        return ds.GetNumberOfPolys() + ds.GetNumberOfStrips()
    return ds.GetNumberOfCells()


def _cells(a: vtkActor) -> int:
    n = getattr(a, "_faces", None)                # recorded when the actor was built
    if n:
        return n
    try:
        return _face_count(_mapper_data(a.GetMapper()))
    except Exception:
        return 0


def _phongify(a: vtkActor):
    """PBR needs image-based lighting to look right; use Phong but keep the albedo texture."""
    p = a.GetProperty()
    if p.GetInterpolation() == 3:                 # VTK_PBR
        tex = p.GetTexture("albedoTex")
        if tex is not None:
            a.SetTexture(tex)
        p.SetInterpolationToPhong()
        p.SetSpecular(0.2)
    p.SetAmbient(max(p.GetAmbient(), 0.15))


class _Transp:
    """An imported actor's original transparency, so 'solid' can be switched off again.

    Imported glTF/OBJ materials often arrive translucent (alpha in the texture or vertex
    colours, or an unneeded BLEND mode), which shows the mesh see-through. We start every
    model solid and keep what is needed to restore the real material on demand."""

    def __init__(self, a: vtkActor, ds):
        self.opacity = a.GetProperty().GetOpacity()
        self.force_opaque = bool(a.GetForceOpaque())
        self.force_translucent = bool(a.GetForceTranslucent())
        try:
            was_translucent = bool(a.HasTranslucentPolygonalGeometry())
        except Exception:
            was_translucent = False
        self.layers = []                        # (vtk array, owners, numpy view, original alpha)
        tex = a.GetTexture()
        if tex is not None:
            img = tex.GetInput()
            if img is not None:
                self._add(img.GetPointData().GetScalars(), (tex, img))
        arr, _mode = _color_array(ds)
        self._add(arr, (ds,))
        self.has_effect = (self.opacity < 0.99 or self.force_translucent or was_translucent
                           or any(o.size and o.min() < 255 for _a, _w, _v, o in self.layers))

    def _add(self, arr, owners):
        try:
            if arr is None or arr.GetNumberOfComponents() not in (2, 4):
                return
            view = numpy_support.vtk_to_numpy(arr)
            if view.dtype == np.uint8:
                self.layers.append((arr, owners, view, view[:, -1].copy()))
        except Exception:
            pass

    def apply(self, a: vtkActor, solid: bool):
        prop = a.GetProperty()
        if solid:
            prop.SetOpacity(1.0)
            a.SetForceTranslucent(False)
            a.SetForceOpaque(True)
        else:
            prop.SetOpacity(self.opacity)
            a.SetForceTranslucent(self.force_translucent)
            a.SetForceOpaque(self.force_opaque)
        for arr, owners, view, orig in self.layers:
            view[:, -1] = 255 if solid else orig
            arr.Modified()
            for o in owners:
                o.Modified()
        m = a.GetMapper()
        if m is not None:
            m.Modified()


def _prepare_transparency(a: vtkActor, ds):
    """Remember the original material, then make the actor solid (the default)."""
    try:
        info = _Transp(a, ds)
        a._tr = info
        info.apply(a, solid=True)
    except Exception:                           # last resort: plain opaque, not reversible
        a.GetProperty().SetOpacity(1.0)
        try:
            a.ForceOpaqueOn()
        except Exception:
            pass


def _import_actors(path: str, ext: str) -> list:
    rw = vtkRenderWindow()                        # never rendered: no GL context is created
    ren = vtkRenderer()
    rw.AddRenderer(ren)
    if ext in (".gltf", ".glb"):
        imp = vtkGLTFImporter()
        imp.SetFileName(path)
    else:
        imp = vtkOBJImporter()
        imp.SetFileName(path)
        imp.SetFileNameMTL(str(Path(path).with_suffix(".mtl")))
        imp.SetTexturePath(os.path.dirname(path))
    imp.SetRenderWindow(rw)
    imp.Update()
    col = ren.GetActors()
    col.InitTraversal()
    found = [col.GetNextActor() for _ in range(col.GetNumberOfItems())]
    out, seen = [], []
    for a in found:
        ren.RemoveActor(a)
        m = a.GetMapper()
        if m is None:
            continue
        m.Update()
        ds = _mapper_data(m)
        if ds is not None and ds.GetNumberOfPoints() > 0:
            a._faces = _face_count(ds)
            a._verts = ds.GetNumberOfPoints()
            _phongify(a)
            tex = a.GetTexture()
            if tex is not None:
                seen.append(tex)                  # keep the wrapper alive so id() stays unique
            a._mat = (tuple(round(c, 3) for c in a.GetProperty().GetColor()),
                      id(tex) if tex is not None else 0)
            if a.GetTexture() is None:
                _apply_color_mode(m, ds)
            _prepare_transparency(a, ds)
            out.append(a)
    return out


def load_scene(path: str) -> list:
    _tls.log_pos = _log_size()
    with _glb_compat(path) as p:
        ext = asset_ext(p)
        can_import = vtkGLTFImporter is not None and (
            ext in (".gltf", ".glb")
            or (ext == ".obj" and Path(p).with_suffix(".mtl").exists()))
        if can_import:
            try:
                actors = _import_actors(p, ext)
                if actors:
                    return actors
            except Exception:
                pass                              # fall back to untextured mesh
        if ext in ASSIMP:
            try:
                actors = _assimp_actors(p)
                if actors:
                    return actors
            except Exception:
                pass                              # load_any reports the detailed error
        return [make_actor(load_any(p))]


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


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


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

    def _style_color(self, key: str):
        c = self.spec["params"][key]
        lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        self._color_btns[key].setStyleSheet(
            f"background:rgb({int(c[0] * 255)},{int(c[1] * 255)},{int(c[2] * 255)});"
            f"color:{'#101418' if lum > 0.55 else '#f2f5f8'};border:1px solid #3a4656;")

    def _touched(self):
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


# ---------------------------------------------------------------------------
# Model info panel
# ---------------------------------------------------------------------------
def _fmt_len(v: float) -> str:
    v = abs(v)
    if v >= 1000:
        return f"{v:,.1f}"
    if v >= 100:
        return f"{v:.1f}"
    if v >= 1:
        return f"{v:.3f}"
    return f"{v:.4f}"


def _triangles(ds) -> int:
    """Triangles needed to draw the polygons (an n-gon is n-2); falls back to the face count."""
    try:
        total = 0
        for cells in (ds.GetPolys(), ds.GetStrips()):
            if cells.GetNumberOfCells():
                sizes = np.diff(numpy_support.vtk_to_numpy(cells.GetOffsetsArray()))
                total += int(np.maximum(sizes - 2, 0).sum())
        return total
    except Exception:
        return _face_count(ds)


def collect_model_info(actors: list, path: str, up: str) -> dict:
    nv = nf = nt = 0
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    mats, texs, alive = set(), set(), []
    has_color = has_uv = False
    for a in actors:
        ds = _mapper_data(a.GetMapper())
        nv += getattr(a, "_verts", None) or (ds.GetNumberOfPoints() if ds is not None else 0)
        nf += _cells(a)
        if ds is not None:
            nt += _triangles(ds)
            has_color = has_color or _color_array(ds)[0] is not None
            has_uv = has_uv or ds.GetPointData().GetTCoords() is not None
        b = a.GetBounds()
        if b is not None and b[0] <= b[1]:
            for i in range(3):
                lo[i], hi[i] = min(lo[i], b[2 * i]), max(hi[i], b[2 * i + 1])
        key = getattr(a, "_mat", None)
        if key is not None:
            mats.add(key)
        tex = a.GetTexture()
        if tex is not None:
            alive.append(tex)                     # keep wrappers alive so id() is unique
            texs.add(id(tex))
    try:
        size = human_size(os.path.getsize(path))
    except OSError:
        size = "unknown"
    return {"name": os.path.basename(path), "format": asset_ext(path).lstrip(".").upper() or "?",
            "size": size, "parts": len(actors), "hidden": sum(1 for a in actors if not a.GetVisibility()), "verts": nv, "faces": nf, "tris": nt,
            "dims": [hi[i] - lo[i] for i in range(3)] if lo[0] <= hi[0] else None, "up": up,
            "mats": len(mats) if mats else None, "texs": len(texs),
            "colors": has_color, "uvs": has_uv}


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


# ---------------------------------------------------------------------------
# Export / convert (with optional mesh simplification)
# ---------------------------------------------------------------------------
# (label, extension, kind, binary)
EXPORT_FORMATS = [
    ("STL (binary)", ".stl", "stl", True), ("STL (ASCII)", ".stl", "stl", False),
    ("OBJ", ".obj", "obj", True),
    ("PLY (binary)", ".ply", "ply", True), ("PLY (ASCII)", ".ply", "ply", False),
]
IDENTITY16 = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def export_default_name(src_path: str, fmt_index: int, simplified: bool) -> str:
    stem = Path(src_path).stem if src_path else "model"
    return stem + ("_simplified" if simplified else "") + EXPORT_FORMATS[fmt_index][1]


def snapshot_export_parts(actors: list) -> list:
    """Private, thread-safe copies of each actor's mesh plus its world matrix, so the worker
    thread never touches objects the render loop is using."""
    parts = []
    for a in actors:
        if not a.GetVisibility():
            continue                                   # hidden parts are left out of exports
        ds = _mapper_data(a.GetMapper())
        if ds is None or not isinstance(ds, vtkPolyData):
            continue
        pd = vtkPolyData()
        pd.ShallowCopy(ds)                           # arrays are shared, read-only
        m = a.GetMatrix()
        parts.append((pd, [m.GetElement(i, j) for i in range(4) for j in range(4)]))
    return parts


def build_export_polydata(parts: list, keep=None, normals: bool = False):
    """Merge -> weld -> triangulate -> (optional) quadric decimation. Returns (mesh, n_in, n_out)."""
    app = vtkAppendPolyData()
    for pd, flat in parts:
        if flat != IDENTITY16:                       # bake the actor's placement into the points
            t = vtkTransform()
            t.SetMatrix(flat)
            f = vtkTransformPolyDataFilter()
            f.SetTransform(t)
            f.SetInputData(pd)
            f.Update()
            app.AddInputData(f.GetOutput())
        else:
            app.AddInputData(pd)
    app.Update()

    def weld(poly):
        c = vtkCleanPolyData()
        c.SetInputData(poly)
        c.ConvertPolysToLinesOff()
        c.ConvertLinesToPointsOff()
        c.Update()
        return c.GetOutput()

    tri = vtkTriangleFilter()
    tri.SetInputData(weld(app.GetOutput()))
    tri.PassVertsOff()
    tri.PassLinesOff()
    tri.Update()
    out = tri.GetOutput()
    n_in = out.GetNumberOfPolys()
    if n_in == 0:
        raise ValueError("This model has no surface to export.")
    if keep is not None and keep < 0.999:
        dec = vtkQuadricDecimation()
        dec.SetInputData(out)
        dec.SetTargetReduction(1.0 - float(keep))
        dec.Update()
        out = weld(dec.GetOutput())
        if out.GetNumberOfPolys() == 0:
            raise ValueError("Simplification removed the whole mesh; try keeping more faces.")
    if normals:
        nrm = vtkPolyDataNormals()
        nrm.SetInputData(out)
        nrm.SetFeatureAngle(60.0)
        nrm.SplittingOn()
        nrm.ConsistencyOff()
        nrm.Update()
        out = nrm.GetOutput()
    return out, n_in, out.GetNumberOfPolys()


def write_mesh(pd, path: str, kind: str, binary: bool):
    if kind == "stl":
        w = vtkSTLWriter() if vtkSTLWriter is not None else None
    elif kind == "obj":
        w = vtkOBJWriter() if vtkOBJWriter is not None else None
    else:
        w = vtkPLYWriter() if vtkPLYWriter is not None else None
    if w is None:
        raise ValueError(f"This VTK build has no {kind.upper()} writer.")
    if kind in ("stl", "ply"):
        (w.SetFileTypeToBinary if binary else w.SetFileTypeToASCII)()
    if kind == "ply":
        arr, mode = _color_array(pd)
        if arr is not None and mode == "point" and arr.GetDataType() == VTK_UNSIGNED_CHAR:
            w.SetArrayName(arr.GetName())
            w.SetColorModeToDefault()
        else:
            w.SetColorModeToOff()
    w.SetFileName(path)
    w.SetInputData(pd)
    w.Write()
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise ValueError("The file could not be written (check the folder is writable).")


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


# ---------------------------------------------------------------------------
# About dialog (all wording lives in the ABOUT dictionary near the top of this file)
# ---------------------------------------------------------------------------
def about_html() -> str:
    a, esc = ABOUT, html.escape
    items = "".join(
        f"<li><b>{esc(n)}</b> &mdash; {esc(lic)}"
        + (f' <span style="color:#7c8794">({esc(url)})</span>' if url else "") + "</li>"
        for n, lic, url in a["third_party"])
    licence = esc(a["licence_text"].format(copyright=a["copyright"]))
    h = "color:#6aa8e8; margin:14px 0 4px 0;"
    return (f'<h4 style="{h}">{esc(a["legal_heading"])}</h4>'
            f'<p>{esc(a["copyright"])}</p><p>{esc(a["legal_notice"])}</p>'
            f'<h4 style="{h}">{esc(a["licence_heading"])}</h4>'
            f'<p>{esc(a["licence_intro"])}</p>'
            f'<pre style="white-space:pre-wrap; font-size:11px; color:#aeb8c4;">{licence}</pre>'
            f'<h4 style="{h}">{esc(a["third_party_heading"])}</h4>'
            f'<p>{esc(a["third_party_intro"])}</p><ul>{items}</ul>'
            f'<p style="color:#7c8794;">{esc(a["third_party_note"])}</p>')


class AboutDialog(QDialog):
    """Closes with the title-bar X, the ✕ button, the Close button, or Esc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        a, esc = ABOUT, html.escape
        self.setWindowTitle(f"About {a['app_name']}")
        self.setModal(True)
        self.setMinimumSize(540, 580)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel(a["app_name"] + (f"  {a['version']}" if a.get("version") else ""))
        title.setObjectName("aboutTitle")
        head.addWidget(title, 1)
        x = QToolButton()
        x.setText("✕")
        x.setToolTip("Close (Esc)")
        x.setObjectName("aboutClose")
        x.clicked.connect(self.close)
        head.addWidget(x)
        root.addLayout(head)
        tag = QLabel(a["tagline"])
        tag.setObjectName("aboutTagline")
        tag.setWordWrap(True)
        root.addWidget(tag)

        heading = QLabel(a["author_heading"])
        heading.setObjectName("aboutHeading")
        root.addWidget(heading)
        who = QLabel(f"<span style='font-size:15px'><b>{esc(a['author_name'])}</b>"
                     f" &nbsp;/&nbsp; {esc(a['author_alias'])}</span>"
                     + (f"<br><span style='color:#8d99a8'>{esc(a['author_note'])}</span>"
                        if a.get("author_note") else ""))
        who.setTextFormat(Qt.RichText)
        who.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(who)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(about_html())
        root.addWidget(browser, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(a["close_label"])
        close.setDefault(True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)


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
VIEW_CHANNELS = [("surface", "Shaded"), ("albedo", "Albedo (no lighting)"),
                 ("normals", "Normals (red = back faces)")]
OTHER_TEXTURE_SLOTS = [("materialTex", "Occlusion / roughness / metallic"),
                       ("normalTex", "Normal map"), ("emissiveTex", "Emissive")]


def collect_textures(actors: list) -> list:
    """Distinct (texture, role) pairs and the parts that use them. Base colour is always looked
    for; the other roles show up when the importer attached them to the material."""
    order = {"Base colour": 0, **{label: i + 1 for i, (_n, label) in enumerate(OTHER_TEXTURE_SLOTS)}}
    found = {}
    for idx, a in enumerate(actors):
        cands = [("Base colour", a.GetTexture())]
        prop = a.GetProperty()
        for name, label in OTHER_TEXTURE_SLOTS:
            try:
                cands.append((label, prop.GetTexture(name)))
            except Exception:
                pass
        for label, tex in cands:
            if tex is None:
                continue
            e = found.setdefault((id(tex), label), {"role": label, "tex": tex, "parts": []})
            e["parts"].append(idx)               # e["tex"] keeps the wrapper alive, so id() is unique
    for e in found.values():
        img = e["tex"].GetInput()
        e["size"] = tuple(img.GetDimensions()[:2]) if img is not None else None
    return sorted(found.values(), key=lambda e: (order[e["role"]], e["parts"][0]))


def texture_to_array(tex, max_side: int = 1024):
    """Texture pixels as a top-down uint8 array (H, W, C), thinned to roughly max_side. None if unreadable."""
    try:
        img = tex.GetInput()
        if img is None:
            return None
        w, h, _ = img.GetDimensions()
        sc = img.GetPointData().GetScalars()
        if sc is None or w == 0 or h == 0:
            return None
        arr = numpy_support.vtk_to_numpy(sc).reshape(h, w, sc.GetNumberOfComponents())[::-1]
        k = max(1, max(w, h) // max_side)
        arr = arr[::k, ::k]
        if arr.dtype == np.uint16:
            arr = (arr >> 8).astype(np.uint8)
        elif arr.dtype != np.uint8:
            arr = arr.astype(np.float32)
            arr = np.clip(arr * (255.0 if float(arr.max()) <= 1.0001 else 1.0), 0, 255).astype(np.uint8)
        return np.ascontiguousarray(arr)
    except Exception:
        return None


def texture_channel_rgb(arr: np.ndarray, channel: str = "rgb") -> np.ndarray:
    """RGB view of a texture: full colour, or a single channel shown as grey."""
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr[..., None]
    nc = arr.shape[2]
    if channel == "rgb":
        if nc >= 3:
            return arr[..., :3]
        return np.dstack([arr[..., 0]] * 3)
    if channel == "a":
        plane = arr[..., 3] if nc == 4 else arr[..., 1] if nc == 2 else np.full(arr.shape[:2], 255, np.uint8)
    else:
        i = {"r": 0, "g": 1, "b": 2}[channel]
        plane = arr[..., i] if nc >= 3 else arr[..., 0]
    return np.dstack([plane] * 3)


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
        thint = QLabel("Double-click a texture to preview it and look at its channels.")
        thint.setObjectName("barLabel")
        thint.setWordWrap(True)
        tl.addWidget(thint)
        self.tabs.addTab(tw, "Textures")
        self.tabs.currentChanged.connect(lambda _i: viewer.highlight_part(None))

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
        for e in self._textures:
            arr = texture_to_array(e["tex"], 128)
            icon = QIcon(QPixmap.fromImage(_rgb_to_qimage(texture_channel_rgb(arr)))) if arr is not None else QIcon()
            size = f"{e['size'][0]}×{e['size'][1]}" if e["size"] else "size unknown"
            n = len(e["parts"])
            self.tex_list.addItem(QListWidgetItem(
                icon, f"{e['role']}\n{size}  ·  used by {n} part{'s' if n != 1 else ''}"))
        if not self._textures:
            self.tex_list.addItem(QListWidgetItem("This model has no textures (colours only)."))

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


class Viewer(QWidget):
    closed = Signal()
    step = Signal(int)                    # -1 previous model, +1 next model
    message = Signal(str)                 # short status text for the main window
    orientation_changed = Signal(str)     # path whose up-axis changed
    about_requested = Signal()            # open the About dialog
    panel_requested = Signal(str)         # show/raise a docked panel: environment, matcap, scene, materials

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
        self._materials_panel = None
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
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.installEventFilter(self)       # Shift + right-drag rotates the lighting
        lay.addWidget(self.vtk_widget)

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
        self.hud = QFrame(self)
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

        self.info_panel = InfoPanel(self)
        self.info_panel.hide()
        self.overlay = Overlay(self)
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
        self.hud.move(max(8, self.width() - self.hud.width() - 12), 12)
        self.hud.raise_()
        self._place_info()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_hud()
        if self.overlay.isVisible():
            self.overlay.reposition()

    # ----- scene state ------------------------------------------------------
    def clear_scene(self):
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
        if self._materials_panel is not None and self._materials_panel.isVisible():
            self._materials_panel.refresh()

    # ----- shading modes ----------------------------------------------------
    def cycle_matcap(self):
        """M: Red Wax -> Clay Green -> RealSkin -> Framer -> RoughMetal -> normal shading."""
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
        log_pos = _log_size()
        for a in self.actors:
            prop = a.GetProperty()
            try:                                  # always start from stock VTK shading
                a.GetShaderProperty().ClearAllFragmentShaderReplacements()
            except Exception:
                pass
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
        if mode == "surface" and self._current_env_code():
            try:
                self._install_env()
            except Exception:
                self._clear_replacements()
                self._env_code = ""
        self._sync_env_lights(mode)
        self._apply_edges(mode)
        self.mode = mode
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

    def _current_env_code(self) -> str:
        if not self._env_on("lighting"):
            return ""
        return env_shader_code(self.env, self._sun_frame_dir(), self._env_view_locked)

    def _install_env(self):
        code = self._current_env_code()
        for a in self.actors:
            sp = a.GetShaderProperty()
            sp.ClearAllFragmentShaderReplacements()
            sp.AddFragmentShaderReplacement("//VTK::Light::Impl", True, code, False)
        self._env_code = code

    def _sync_env_lights(self, mode=None):
        """Two scene lights carry 'world up' and 'the sun' into the shader (surface mode only,
        so every other mode keeps VTK's normal headlight)."""
        mode = mode or self.mode
        want = (self._env_on("lighting") and mode == "surface" and bool(self.actors)
                and not self._env_view_locked)
        if want:
            if self._env_lights is None:
                self._env_lights = (vtkLight(), vtkLight())
                for light in self._env_lights:
                    light.SetLightTypeToSceneLight()
                    light.SetPositional(False)
                    light.SetFocalPoint(0.0, 0.0, 0.0)
            up_l, sun_l = self._env_lights
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
        self.apply_environment_preset(clean_env({**ENV_DEFAULTS, **ov, "path": ""}), "", name)

    def cycle_lighting_preset(self):
        names = list(ENV_BUILTIN_PRESETS)
        self.apply_builtin_preset(names[(self._preset_idx + 1) % len(names)])

    # ----- Shift + right-drag: rotate the lighting (and the sky) around the model -----
    def eventFilter(self, obj, ev):
        if obj is not self.vtk_widget:
            return super().eventFilter(obj, ev)
        t = ev.type()
        if t in (QEvent.KeyPress, QEvent.KeyRelease):
            # Every key is handled by the app's own shortcuts. VTK's built-in letter keys (S = solid,
            # W = wireframe, P = pick, E/Q = exit, ...) must never reach the scene: they changed the
            # ground grid and could alter other props.
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
        if self.mode == "surface" and self._current_env_code() != self._env_code:
            self.set_mode("surface")              # reinstalls (or removes) the shader and renders
        else:
            self.rw.Render()

    def _env_failed(self):
        """The environment shader didn't compile: follow the camera instead, or switch off."""
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
        on = self.edges_on and (mode or self.mode) == "surface"
        for a in self.actors:
            p = a.GetProperty()
            if on:
                p.EdgeVisibilityOn()
                p.SetEdgeColor(0.08, 0.10, 0.14)
            else:
                p.EdgeVisibilityOff()

    def set_edges(self, on: bool):
        self.edges_on = bool(on)
        self.settings.setValue("edges_on", "true" if on else "false")
        self._apply_edges()
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
        self._orbit_timer.stop()
        self.vtk_widget.Finalize()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
DARK_QSS = """
* { font-family: 'Segoe UI', 'Inter', 'Ubuntu', sans-serif; }
QMainWindow, QWidget { background:#14181e; color:#d5dbe3; }
QTreeView, QListWidget { background:#14181e; border:none; outline:0; }
QTreeView::item { padding:3px 0; }
QTreeView::item:selected, QListWidget::item:selected { background:#27486b; color:#fff; border-radius:6px; }
QTreeView::item:hover, QListWidget::item:hover { background:#1f2630; border-radius:6px; }
QListWidget::item { color:#c3cad4; padding:4px; }
QSplitter::handle { background:#0e1116; width:2px; }
QScrollBar:vertical { background:#0b0e12; width:16px; margin:0; border-left:1px solid #1c232c; }
QScrollBar::handle:vertical { background:#6f86a3; border-radius:6px; margin:2px 3px; min-height:48px; }
QScrollBar::handle:vertical:hover { background:#8fa8c6; }
QScrollBar::handle:vertical:pressed { background:#6aa8e8; }
QScrollBar:horizontal { background:#0b0e12; height:16px; margin:0; border-top:1px solid #1c232c; }
QScrollBar::handle:horizontal { background:#6f86a3; border-radius:6px; margin:3px 2px; min-width:48px; }
QScrollBar::handle:horizontal:hover { background:#8fa8c6; }
QScrollBar::handle:horizontal:pressed { background:#6aa8e8; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; background:none; border:none; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
QAbstractScrollArea::corner { background:#0b0e12; }
QToolTip { background:#1b2028; color:#e0e6ed; border:1px solid #3a4656; }
#hud { background:#1b2028; border:1px solid #2f3947; border-radius:10px; }
#hudTitle { color:#8d99a8; font-size:11px; padding:0 8px; background:transparent; }
#hud QToolButton { background:#252d38; border:none; border-radius:6px; padding:4px 9px; color:#d5dbe3; }
#hud QToolButton:hover { background:#34506f; }
#hud QToolButton:checked { background:#3d6fa5; color:#fff; }
#hud QToolButton::menu-indicator { image:none; }
#hudClose { color:#9aa5b2; } #hudClose:hover { background:#8e2a2a !important; color:#fff; }
QMenu { background:#1b2028; border:1px solid #2f3947; color:#d5dbe3; padding:4px; }
QMenu::item { padding:5px 24px 5px 12px; border-radius:4px; }
QMenu::item:selected { background:#34506f; }
QMenu::separator { height:1px; background:#2f3947; margin:4px 8px; }
#galleryBar { background:#10141a; border-bottom:1px solid #0b0e12; }
QLineEdit, QComboBox { background:#1b2028; border:1px solid #2f3947; border-radius:6px; padding:4px 8px; color:#d5dbe3; }
QLineEdit:focus, QComboBox:focus { border-color:#3d6fa5; }
QComboBox QAbstractItemView { background:#1b2028; selection-background-color:#34506f; border:1px solid #2f3947; }
QSlider::groove:horizontal { height:4px; background:#2c3542; border-radius:2px; }
QSlider::handle:horizontal { width:12px; margin:-5px 0; background:#6aa8e8; border-radius:6px; }
#barLabel { color:#7c8794; background:transparent; }
#drawerBtn { background:#10141a; border:none; border-left:1px solid #1c232c; color:#aeb8c4; }
#drawerBtn:hover { background:#27486b; }
QDockWidget { color:#d5dbe3; }
QDockWidget::title { background:#10141a; padding:6px 8px; border-bottom:1px solid #1c232c; }
QMainWindow::separator { background:#0e1116; width:4px; height:4px; }
QMainWindow::separator:hover { background:#34506f; }
QTabBar::tab { background:#1b2028; color:#aeb8c4; padding:6px 12px; border:1px solid #2f3947; border-bottom:none; border-top-left-radius:6px; border-top-right-radius:6px; margin-right:2px; }
QTabBar::tab:selected { background:#27486b; color:#ffffff; }
QTabBar::tab:hover:!selected { background:#252d38; }
QTabWidget::pane { border:1px solid #2f3947; border-radius:4px; top:-1px; }
QScrollArea { background:#14181e; border:none; }
QMenuBar { background:#10141a; color:#d5dbe3; }
QMenuBar::item { padding:4px 10px; background:transparent; }
QMenuBar::item:selected { background:#34506f; border-radius:4px; }
QTextBrowser { background:#10141a; border:1px solid #2f3947; border-radius:6px; padding:8px; color:#d5dbe3; }
#aboutTitle { color:#e6ebf1; font-size:22px; font-weight:700; background:transparent; }
#aboutTagline { color:#8d99a8; background:transparent; }
#aboutHeading { color:#6aa8e8; font-weight:600; font-size:12px; background:transparent; }
#aboutClose { background:transparent; border:none; color:#9aa5b2; font-size:14px; padding:4px 9px; }
#aboutClose:hover { background:#8e2a2a; color:#fff; border-radius:6px; }
#infoTitle { color:#e6ebf1; font-weight:600; background:transparent; }
#infoKey { color:#7c8794; font-size:11px; background:transparent; }
#infoVal { color:#d5dbe3; font-size:11px; background:transparent; }
QPushButton { background:#252d38; border:1px solid #2f3947; border-radius:6px; padding:5px 12px; color:#d5dbe3; }
QPushButton:hover { background:#34506f; }
QPushButton:disabled { color:#5c6672; background:#1b2028; }
QDialog { background:#14181e; }
QCheckBox { color:#d5dbe3; spacing:6px; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #3a4656; border-radius:3px; background:#1b2028; }
QCheckBox::indicator:checked { background:#3d6fa5; }
"""


class PanelDock(QDockWidget):
    """A dock for one side panel. Tells us when the user closes it with its own title-bar button
    (hiding it from code does not count)."""
    closed = Signal(str)

    def __init__(self, key: str, title: str, parent=None):
        super().__init__(title, parent)
        self.key = key

    def closeEvent(self, e):
        self.closed.emit(self.key)
        super().closeEvent(e)


class TabDragOut(QObject):
    """Lets a panel be torn off by dragging its TAB out of the tab strip (Qt only does this itself
    with 'grouped dragging', which we keep off because it merges overlapping floating panels).
    Reordering tabs inside the strip is left entirely to Qt."""
    MARGIN = 36                                      # px beyond the tab strip before we tear off

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.bar = None
        self.start = None
        self.text = ""
        self.done = False

    def _is_panel_bar(self, obj) -> bool:
        return (isinstance(obj, QTabBar) and obj.metaObject().className() == "QMainWindowTabBar"
                and obj.window() is self.win)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            return False
        if not self._is_panel_bar(obj):
            return False
        try:
            if t == QEvent.Type.MouseButtonPress:
                self.done = False
                self.bar = None
                if ev.button() == Qt.MouseButton.LeftButton:
                    i = obj.tabAt(ev.position().toPoint())
                    if i >= 0:
                        self.bar, self.start, self.text = obj, ev.position().toPoint(), obj.tabText(i)
                return False
            if t == QEvent.Type.MouseButtonRelease:
                swallow = self.done
                self.bar = None
                self.done = False
                return swallow
            # mouse move
            if self.done:
                return True
            if self.bar is obj and (ev.buttons() & Qt.MouseButton.LeftButton):
                zone = obj.rect().adjusted(-self.MARGIN, -self.MARGIN, self.MARGIN, self.MARGIN)
                if not zone.contains(ev.position().toPoint()):
                    self.done = True
                    text = self.text
                    QTimer.singleShot(0, lambda: self._tear_off(obj, text))
                    return True
        except RuntimeError:
            pass
        return False

    def _tear_off(self, bar, text):
        """Runs after the current event, because floating the panel can delete the tab strip."""
        from PySide6.QtGui import QCursor, QMouseEvent
        dock = next((d for d in self.win.docks.values() if d.windowTitle().replace("&", "") == text.replace("&", "")), None)
        if dock is None or dock.isFloating():
            return
        try:
            pos = bar.mapFromGlobal(QCursor.pos())
            QApplication.sendEvent(bar, QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pos),
                                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        except RuntimeError:
            pass
        w, h = max(dock.width(), 340), max(dock.height(), 480)
        dock.setFloating(True)
        c = QCursor.pos()
        dock.setGeometry(c.x() - w // 2, c.y() - 14, w, h)      # title bar under the pointer
        dock.show()
        dock.raise_()
        dock.activateWindow()
        h_ = dock.windowHandle()
        if h_ is not None:
            try:
                h_.startSystemMove()                 # keep dragging the new window with the mouse
            except Exception:
                pass


class MainWindow(QMainWindow):
    def __init__(self, start: str | None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 820)
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.pool = QThreadPool.globalInstance()
        self.token = 0
        self.current_path = ""
        self._tasks: dict[int, LoadTask] = {}

        # ---- left: file tree
        self.fs = QFileSystemModel()
        self.fs.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.fs.setNameFilters([f"*{e}" for e in sorted(ALL_EXTS)])
        self.fs.setNameFilterDisables(False)  # hide non-3D files
        self.fs.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs)
        self.tree.setRootIndex(self.fs.index(""))
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        self.tree.selectionModel().currentChanged.connect(self._tree_changed)
        self.tree.doubleClicked.connect(self._tree_double)

        # ---- right: gallery page (toolbar + grid) and viewer, stacked
        self.gallery = Gallery()
        self.gallery.open_asset.connect(self.open_asset)
        self.gallery.open_folder.connect(self.goto_folder)
        self.gallery.rename_requested.connect(self._rename_file)
        self.gallery.copy_requested.connect(self._copy_file)
        self.gallery.paste_requested.connect(self._paste_files)
        self.gallery.delete_requested.connect(self._delete_file)
        self.gallery.refresh_thumb_requested.connect(self._refresh_thumbnail)
        self.gallery.refresh_all_requested.connect(self._refresh_all_thumbnails)
        self.thumbs = ThumbnailManager()
        self.thumbs.ready.connect(self.gallery.set_thumb)

        self.gallery_page = QWidget()
        gl = QVBoxLayout(self.gallery_page)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("galleryBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search models…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.gallery.set_filter)
        self.sort_box = QComboBox()
        self.sort_box.addItems([s[0] for s in SORTS])
        self.sort_box.setCurrentIndex(min(_setting_int(self.settings, "sort_idx", 0), len(SORTS) - 1))
        self.gallery.set_sort(self.sort_box.currentIndex())
        self.sort_box.currentIndexChanged.connect(self._sort_changed)
        self.count_label = QLabel("")
        self.count_label.setObjectName("barLabel")
        self.gallery.counts.connect(self._counts_changed)
        size_label = QLabel("Size")
        size_label.setObjectName("barLabel")
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(64, 192)
        self.size_slider.setFixedWidth(120)
        self.size_slider.setToolTip("Card size")
        card = _setting_int(self.settings, "card_px", 88)
        self.size_slider.setValue(max(64, min(card, 192)))
        self.gallery.set_card_size(self.size_slider.value())
        self.size_slider.valueChanged.connect(self._size_changed)
        bl.addWidget(self.search)
        bl.addWidget(self.sort_box)
        bl.addStretch(1)
        bl.addWidget(self.count_label)
        bl.addWidget(size_label)
        bl.addWidget(self.size_slider)
        gl.addWidget(bar)
        gl.addWidget(self.gallery)

        self.viewer = Viewer()
        self.viewer.closed.connect(self.close_viewer)
        self.viewer.step.connect(self._step)
        self.viewer.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.viewer.orientation_changed.connect(self.thumbs.refresh)
        self.viewer.about_requested.connect(self.show_about)
        self.viewer.panel_requested.connect(self._show_panel)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gallery_page)
        self.stack.addWidget(self.viewer)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1060])
        split.setChildrenCollapsible(False)
        holder = QWidget()                           # workspace + a slim edge button that stays visible
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(split, 1)
        self.drawer_btn = QToolButton()
        self.drawer_btn.setObjectName("drawerBtn")
        self.drawer_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.drawer_btn.setFixedWidth(18)
        self.drawer_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.drawer_btn.clicked.connect(self._toggle_drawer)
        hl.addWidget(self.drawer_btn)
        self.setCentralWidget(holder)

        # ---- viewer hotkeys: only enabled while the viewer is showing, so the
        #      tree and gallery keep normal keyboard navigation (arrows, type-ahead)
        v = self.viewer
        bindings = [
            ("W", lambda: v.set_mode("wire")), ("P", lambda: v.set_mode("points")),
            ("S", lambda: v.set_mode("surface")), ("M", v.cycle_matcap),
            ("R", v.reset_camera), ("O", v.toggle_orbit), ("B", v.cycle_background),
            ("A", v.act_axes.toggle), ("C", v.act_ortho.toggle), ("U", v.toggle_up_axis),
            ("T", v.toggle_transparency),
            ("F12", v.save_screenshot), ("Ctrl+C", v.copy_screenshot),
            ("Left", lambda: self._step(-1)), ("Right", lambda: self._step(1)),
            ("E", v.open_matcap_editor),
            ("L", v.toggle_environment), ("Shift+L", v.open_environment_panel),
            ("Ctrl+L", v.cycle_lighting_preset),
            ("I", v.toggle_info),
            ("G", v.toggle_grid), ("F", v.fit_view), ("H", v.toggle_turntable),
            ("V", v.cycle_view_channel), ("Shift+M", v.open_materials_panel),
            ("Shift+W", v.toggle_edges), ("Shift+G", v.open_scene_panel),
            ("Esc", self.close_viewer),
        ]
        for i, key in enumerate(("front", "back", "right", "left", "top", "bottom", "iso"), 1):
            bindings.append((str(i), lambda k=key: v.set_view(k)))
        for n in (1, 2, 3):                        # saved camera views
            bindings.append((f"Ctrl+Shift+{n}", lambda n=n: v.save_bookmark(n)))
            bindings.append((f"Alt+{n}", lambda n=n: v.go_bookmark(n)))
        self._viewer_shortcuts = [QShortcut(QKeySequence(k), self, activated=fn)
                                  for k, fn in bindings]
        self._build_docks()
        self._build_menus()
        self._sync_shortcuts()

        self.statusBar().setStyleSheet("color:#7c8794;")
        self._restore(start)
        self._drawer_animate_ok = True               # animate from now on, not while starting up

    # ----- toolbar slots
    def _sort_changed(self, idx: int):
        self.settings.setValue("sort_idx", idx)
        self.gallery.set_sort(idx)

    def _size_changed(self, px: int):
        self.settings.setValue("card_px", px)
        self.gallery.set_card_size(px)

    def _counts_changed(self, shown: int, total: int):
        self.count_label.setText(f"{total} models" if shown == total else f"{shown} of {total} models")

    def _build_menus(self):
        """A real menu bar so everything is reachable by mouse, keyboard and screen readers."""
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        act = fm.addAction("Open folder…")
        act.setShortcut(QKeySequence("Ctrl+O"))
        act.triggered.connect(self._choose_folder)
        self.act_export = fm.addAction("Export / convert…")
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.triggered.connect(self.viewer.open_export_dialog)
        self.act_export.setEnabled(False)
        fm.addSeparator()
        quit_act = fm.addAction("Quit")
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        pm = mb.addMenu("&Panels")
        self.act_drawer = QAction("Show/Hide Panel", pm, checkable=True)
        self.act_drawer.setShortcut(QKeySequence("Ctrl+B"))
        self.act_drawer.triggered.connect(self._set_drawer_pref)
        pm.addAction(self.act_drawer)
        pm.addSeparator()
        self._panel_actions = {}
        for key, title, _factory in self.DOCK_SPECS:       # same left-to-right order as the tabs
            act = QAction(title, pm, checkable=True)
            act.triggered.connect(lambda checked, k=key: self._set_panel_open(k, checked))
            pm.addAction(act)
            self._panel_actions[key] = act
        pm.addSeparator()
        reset = pm.addAction("Reset panel layout")
        reset.triggered.connect(self._reset_layout)
        hm = mb.addMenu("&Help")
        about = hm.addAction("About " + ABOUT["app_name"])
        about.setShortcut(QKeySequence("F1"))
        about.triggered.connect(self.show_about)

    def show_about(self):
        AboutDialog(self).exec()

    # ----- dockable panels: right edge only, one collapsible drawer -----------------
    # Native QDockWidget does the tabbing and vertical stacking. Panels may only dock on the right.
    # The whole right-hand group slides in and out as a "drawer" (YouTube-style), driven by the
    # edge button, the Panels menu or Ctrl+B, and it collapses automatically in the gallery.
    DOCK_STATE_VERSION = 3                           # bumped: older layouts allowed other edges / grouped floating windows
    DOCK_SPECS = [("materials", "Materials", "materials_panel"),
                  ("matcap", "MatCap", "matcap_editor"),
                  ("environment", "Environment", "environment_panel"),
                  ("scene", "Scene", "scene_panel")]
    DRAWER_DEFAULT_WIDTH = 380

    def _make_dock(self, key: str, title: str, panel) -> "PanelDock":
        scroll = QScrollArea()                       # scrolls cleanly when the dock is short or narrow
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setMinimumSize(280, 220)              # a panel can never be squeezed to nothing
        dock = PanelDock(key, title, self)
        dock.setObjectName(f"dock_{key}")            # required for saveState / restoreState
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)      # right edge only
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)   # can float; re-docks right only
        dock.setWidget(scroll)
        dock.closed.connect(self._on_dock_closed)
        return dock

    def _group_docks(self):
        """Default arrangement: one tabbed group on the right, in DOCK_SPECS order, left to right."""
        for dock in self.docks.values():
            if self._docks_added and dock.isFloating():
                dock.setFloating(False)              # bring floating panels home first
            if self.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea:
                self.removeDockWidget(dock)          # forgets any old stacking or tab order
        first = None
        for key, _title, _factory in self.DOCK_SPECS:
            dock = self.docks[key]
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            if first is None:
                first = dock
            else:
                self.tabifyDockWidget(first, dock)
            dock.hide()
        self._docks_added = True

    def _build_docks(self):
        # No GroupedDragging: with it Qt merges floating panels that are dropped on top of each other
        # into nested group windows, which shrank/minimised them and broke the drawer bookkeeping.
        # Without it each floating panel stays an independent window with normal OS stacking.
        self.setDockOptions(QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AnimatedDocks)
        self.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea, QTabWidget.TabPosition.North)
        self.docks = {key: self._make_dock(key, title, getattr(self.viewer, factory)())
                      for key, title, factory in self.DOCK_SPECS}
        valid = [k for k, _t, _f in self.DOCK_SPECS]
        saved = [k for k in str(self.settings.value("open_docks", "")).split(",") if k in valid]
        self._open_keys = set(saved) or set(valid)           # first run: all four tabs
        cur = str(self.settings.value("current_dock", valid[0]))
        self._current_key = cur if cur in valid else valid[0]
        self._drawer_pref = str(self.settings.value("drawer_expanded", "true")).lower() in ("1", "true")
        self._drawer_width = max(280, _setting_int(self.settings, "drawer_width", self.DRAWER_DEFAULT_WIDTH))
        self._drawer_open = None                              # unknown until the first _apply_drawer
        self._drawer_busy = False
        self._drawer_anim = None
        self._drawer_animate_ok = False
        self._docks_added = False
        self._group_docks()
        geo = self.settings.value("window_geometry")
        if geo:
            self.restoreGeometry(geo if isinstance(geo, QByteArray) else QByteArray(geo))
        state = self.settings.value("dock_state")
        if state:
            self.restoreState(state if isinstance(state, QByteArray) else QByteArray(state),
                              self.DOCK_STATE_VERSION)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._save_layout)
        for dock in self.docks.values():
            dock.visibilityChanged.connect(self._layout_changed)
            dock.dockLocationChanged.connect(self._layout_changed)
            dock.topLevelChanged.connect(lambda floating, k=dock.key: self._on_float_changed(k, floating))
        self.tabifiedDockWidgetActivated.connect(self._on_tab_activated)
        self._tab_dragout = TabDragOut(self)
        QApplication.instance().installEventFilter(self._tab_dragout)

    # -- bookkeeping: which panels the user has open is kept here, not read back from Qt, so
    #    collapsing the drawer (which hides every dock) never forgets the arrangement.
    def _on_tab_activated(self, dock):
        if not self._drawer_busy and isinstance(dock, PanelDock):
            self._current_key = dock.key
            self._layout_changed()

    def _on_dock_closed(self, key: str):
        """The user pressed the dock's own close button."""
        if self._drawer_busy:
            return
        self._open_keys.discard(key)
        if key == self._current_key and self._open_keys:
            self._current_key = next(k for k, _t, _f in self.DOCK_SPECS if k in self._open_keys)
        if not self._open_keys:
            self._set_drawer_pref(False)             # nothing left open: collapse the drawer
        else:
            self._update_drawer_ui()
        self._layout_changed()

    def _on_float_changed(self, key: str, floating: bool):
        """A panel was dragged out into its own window, or dropped back onto the right edge."""
        if self._drawer_busy:
            return
        self._open_keys.add(key)
        # Qt is still in the middle of its own drag when this fires: change nothing about the layout
        # now, only after the event loop has settled.
        QTimer.singleShot(0, lambda k=key, f=floating: self._after_float_changed(k, f))

    def _after_float_changed(self, key: str, floating: bool):
        try:
            dock = self.docks.get(key)
            if dock is None or dock.isFloating() != floating:
                return                               # stale: the panel moved again meanwhile
            if floating:
                dock.raise_()                        # new window comes to the front
            else:
                self._current_key = key
                if not self._drawer_open:
                    self._set_drawer_pref(True)      # dropped onto an empty edge: bring the drawer back
            self._update_drawer_ui()
            self._layout_changed()
        except RuntimeError:
            pass

    def _sync_floating(self):
        """Floating panels follow the viewer: shown with an open model, put away in the gallery."""
        want = self._in_viewer()
        self._drawer_busy = True
        try:
            for key, dock in self.docks.items():
                if dock.isFloating():
                    dock.setVisible(want and key in self._open_keys)
        finally:
            self._drawer_busy = False

    def _in_viewer(self) -> bool:
        return self.stack.currentWidget() is self.viewer

    def _set_docks_visible(self, on: bool):
        """Show or hide the DOCKED panels. Floating panels are their own windows and are left alone."""
        self._drawer_busy = True
        try:
            for key, dock in self.docks.items():
                if dock.isFloating():
                    continue
                if on and key in self._open_keys:
                    dock.show()
                else:
                    dock.hide()
            cur = self.docks[self._current_key]
            if on and self._current_key in self._open_keys and not cur.isFloating():
                cur.raise_()                                     # selects its tab
        finally:
            self._drawer_busy = False

    def _apply_drawer(self, animate: bool = True):
        """Bring the drawer in line with what is wanted: open in the viewer if the user wants it,
        always closed in the gallery."""
        target = self._drawer_pref and self._in_viewer()
        if self._drawer_open is None:                # first call at start-up: no animation
            self._set_docks_visible(target)
            self._drawer_open = target
        elif target != self._drawer_open:
            (self._expand_drawer if target else self._collapse_drawer)(animate)
        self._sync_floating()
        self._update_drawer_ui()

    def _stop_drawer_anim(self):
        if self._drawer_anim is not None:
            try:
                self._drawer_anim.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._drawer_anim.stop()
            self._drawer_anim = None

    def _animate_drawer(self, dock, w0: int, w1: int, done=None):
        """Slide the right-hand column between two widths. The workspace resizes with it."""
        self._stop_drawer_anim()
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(int(w0))
        anim.setEndValue(int(w1))
        anim.valueChanged.connect(lambda v: self.resizeDocks([dock], [int(v)], Qt.Orientation.Horizontal))
        if done is not None:
            anim.finished.connect(done)
        self._drawer_anim = anim
        anim.start()

    def _expand_drawer(self, animate: bool):
        self._stop_drawer_anim()
        if not self._open_keys:
            self._open_keys.add(self.DOCK_SPECS[0][0])
        docked = [k for k, _t, _f in self.DOCK_SPECS if k in self._open_keys and not self.docks[k].isFloating()]
        self._set_docks_visible(True)
        self._drawer_open = True
        if not docked:                               # every open panel is floating: nothing to slide
            return
        lead = self.docks[self._current_key if self._current_key in docked else docked[0]]
        start_w = lead.width() if not lead.isHidden() else 40
        if animate:
            self._animate_drawer(lead, start_w, self._drawer_width)
        else:
            self.resizeDocks([lead], [self._drawer_width], Qt.Orientation.Horizontal)

    def _collapse_drawer(self, animate: bool):
        self._stop_drawer_anim()
        shown = [d for d in self.docks.values() if not d.isHidden() and not d.isFloating()]
        if shown:
            self._drawer_width = max(280, max(d.width() for d in shown))   # remember for next time
        self._drawer_open = False
        if animate and shown:
            self._animate_drawer(shown[0], shown[0].width(), 0, lambda: self._set_docks_visible(False))
        else:
            self._set_docks_visible(False)

    def _update_drawer_ui(self):
        in_viewer = self._in_viewer()
        opened = bool(self._drawer_open)
        self.drawer_btn.setVisible(in_viewer)                 # no panel to bring back in the gallery
        self.drawer_btn.setArrowType(Qt.ArrowType.RightArrow if opened else Qt.ArrowType.LeftArrow)
        self.drawer_btn.setToolTip(("Hide side panel" if opened else "Show side panel") + "  (Ctrl+B)")
        for act, checked in [(self.act_drawer, opened)] + [(a, k in self._open_keys)
                                                           for k, a in self._panel_actions.items()]:
            act.blockSignals(True)
            act.setChecked(checked)
            act.blockSignals(False)
            act.setEnabled(in_viewer)

    def _set_drawer_pref(self, on: bool):
        self._drawer_pref = bool(on)
        self.settings.setValue("drawer_expanded", "true" if on else "false")
        self._apply_drawer(True)
        self._layout_changed()

    def _toggle_drawer(self):
        if self._in_viewer():
            self._set_drawer_pref(not bool(self._drawer_open))

    def _set_panel_open(self, key: str, on: bool):
        dock = self.docks.get(key)
        if dock is None:
            return
        if on:
            self._open_keys.add(key)
            self._current_key = key
            if self._drawer_open:
                self._drawer_busy = True
                dock.show()
                dock.raise_()
                self._drawer_busy = False
            self._set_drawer_pref(True)
        else:
            self._open_keys.discard(key)
            self._drawer_busy = True
            dock.hide()
            self._drawer_busy = False
            if not self._open_keys:
                self._set_drawer_pref(False)
        self._update_drawer_ui()
        self._layout_changed()

    def _show_panel(self, key: str):
        """A panel's own key or button was used: make sure it is open and in front."""
        self._set_panel_open(key, True)

    def _layout_changed(self, *_):
        self._layout_timer.start(600)

    def _save_layout(self):
        shown = [d for d in self.docks.values() if not d.isHidden() and not d.isFloating()]
        if shown and self._drawer_open:
            self._drawer_width = max(280, max(d.width() for d in shown))
        s = self.settings
        s.setValue("dock_state", self.saveState(self.DOCK_STATE_VERSION))
        s.setValue("window_geometry", self.saveGeometry())
        s.setValue("open_docks", ",".join(k for k, _t, _f in self.DOCK_SPECS if k in self._open_keys))
        s.setValue("current_dock", self._current_key)
        s.setValue("drawer_expanded", "true" if self._drawer_pref else "false")
        s.setValue("drawer_width", int(self._drawer_width))

    def _reset_layout(self):
        """Back to the default: Materials, MatCap, Environment, Scene as tabs on the right."""
        self._stop_drawer_anim()
        self._group_docks()
        self._open_keys = {k for k, _t, _f in self.DOCK_SPECS}
        self._current_key = self.DOCK_SPECS[0][0]
        self._drawer_width = self.DRAWER_DEFAULT_WIDTH
        self._drawer_pref = True
        self.settings.remove("dock_state")
        self.settings.setValue("drawer_expanded", "true")
        self._drawer_open = None                     # re-evaluate from scratch, without animation
        self._apply_drawer(False)
        self._layout_changed()
        self.statusBar().showMessage("Panel layout reset", 6000)

    # ----- file operations from the gallery (rename / copy / paste / delete) --------
    @staticmethod
    def _split_name(name: str):
        ext = asset_ext(name)
        return (name[:-len(ext)] if ext else name), ext

    def _refresh_gallery(self, select: str = ""):
        folder = self.gallery.folder
        if not folder:
            return
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.thumbs.request_batch(self.gallery.populate(folder))
        if select:
            self.gallery.select_path(select)

    def _rename_file(self, path: str):
        folder, old = os.path.split(path)
        base, ext = self._split_name(old)
        label = f"New name (the {ext} ending is kept):" if ext else "New name:"
        new_base, ok = QInputDialog.getText(self, "Rename", label, QLineEdit.Normal, base)
        new_base = new_base.strip()
        if not ok or not new_base or new_base == base:
            return
        if new_base in (".", "..") or any(c in new_base for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Rename", 'A file name can\'t contain any of:  \\ / : * ? " < > |')
            return
        dst = os.path.join(folder, new_base + ext)
        if os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(path):
            QMessageBox.warning(self, "Rename", f"A file called “{new_base + ext}” already exists here.")
            return
        old_cache = self.thumbs._cache_file(path)      # remember the thumbnail before the name changes
        try:
            os.rename(path, dst)
        except OSError as e:
            QMessageBox.warning(self, "Rename", f"Could not rename the file.\n\n{e}")
            return
        ORIENT.set(dst, ORIENT.get(path))              # keep its Y-up / Z-up choice
        ORIENT.set(path, "Y")
        self.thumbs.adopt(old_cache, dst)              # the renamed file keeps its thumbnail
        if self.current_path == path:
            self.current_path = dst
        self._refresh_gallery(select=dst)
        self.statusBar().showMessage(f"Renamed to {new_base + ext}", 6000)

    def _copy_file(self, path: str):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(path)])         # lets Explorer/Finder paste it too
        md.setText(path)
        QApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage(f"Copied {os.path.basename(path)}", 6000)

    @staticmethod
    def _unique_path(folder: str, name: str) -> str:
        cand = os.path.join(folder, name)
        if not os.path.exists(cand):
            return cand
        base, ext = MainWindow._split_name(name)
        n = 1
        while os.path.exists(cand):
            cand = os.path.join(folder, f"{base} - Copy" + (f" ({n})" if n > 1 else "") + ext)
            n += 1
        return cand

    def _paste_files(self):
        folder = self.gallery.folder
        md = QApplication.clipboard().mimeData()
        srcs = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md is not None and md.hasUrls() else []
        files = [p for p in srcs if os.path.isfile(p)]
        if not folder or not files:
            self.statusBar().showMessage("Nothing to paste: copy a file first", 6000)
            return
        last, done, errors = "", 0, []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for src in files:
                dst = self._unique_path(folder, os.path.basename(src))
                old_cache = self.thumbs._cache_file(src)
                try:
                    shutil.copy2(src, dst)
                    self.thumbs.adopt(old_cache, dst)  # a pasted copy starts with the same thumbnail
                    last, done = dst, done + 1
                except OSError as e:
                    errors.append(f"{os.path.basename(src)}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_gallery(select=last)
        self.statusBar().showMessage(f"Pasted {done} file{'s' if done != 1 else ''}", 6000)
        if errors:
            QMessageBox.warning(self, "Paste", "Some files could not be copied:\n\n" + "\n".join(errors[:8]))

    def _refresh_thumbnail(self, path: str):
        self.gallery.clear_thumb(path)
        self.thumbs.refresh(path, force=True)
        self.statusBar().showMessage(f"Refreshing the thumbnail for {os.path.basename(path)}…", 6000)

    def _refresh_all_thumbnails(self):
        paths = self.gallery.file_paths()
        for p in paths:
            self.thumbs.forget(p)
        self._refresh_gallery()
        self.statusBar().showMessage(f"Refreshing {len(paths)} thumbnails…", 6000)

    def _delete_file(self, path: str):
        name = os.path.basename(path)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete")
        box.setText(f"Move “{name}” to the Recycle Bin / Trash?")
        extra = {".obj": "Its .mtl material file and texture images are not deleted.",
                 ".gltf": "Its .bin and texture files are not deleted."}.get(asset_ext(name))
        if extra:
            box.setInformativeText(extra)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        res = QFile.moveToTrash(path)
        if not (res[0] if isinstance(res, tuple) else bool(res)):
            answer = QMessageBox.question(
                self, "Delete", f"“{name}” could not be moved to the Recycle Bin / Trash.\n\n"
                                "Delete it permanently instead?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            try:
                os.remove(path)
            except OSError as e:
                QMessageBox.warning(self, "Delete", f"Could not delete the file.\n\n{e}")
                return
        if self.current_path == path:
            self.current_path = ""
        self._refresh_gallery()
        self.statusBar().showMessage(f"Deleted {name}", 6000)

    def _choose_folder(self):
        start = str(self.settings.value("last_dir", str(Path.home())))
        d = QFileDialog.getExistingDirectory(self, "Open folder", start)
        if d:
            self.goto_folder(d)

    def _sync_shortcuts(self):
        on = self.stack.currentWidget() is self.viewer
        self.act_export.setEnabled(on)
        for sc in self._viewer_shortcuts:
            sc.setEnabled(on)
        self._apply_drawer(self._drawer_animate_ok)      # closes in the gallery, reopens in the viewer

    # ----- helpers
    def _restore(self, start: str | None):
        target = start or self.settings.value("last_dir", str(Path.home()))
        if os.path.isfile(target):
            folder, file = os.path.dirname(target), target
        else:
            folder, file = target, None
        if not os.path.isdir(folder):
            folder = str(Path.home())
        self.goto_folder(folder)
        if file:
            self.open_asset(file)

    def goto_folder(self, folder: str):
        idx = self.fs.index(folder)
        self.tree.setCurrentIndex(idx)   # triggers _tree_changed -> gallery
        self.tree.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        self.tree.expand(idx)

    def _tree_changed(self, cur, _prev):
        path = self.fs.filePath(cur)
        if os.path.isdir(path):
            self.settings.setValue("last_dir", path)
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.thumbs.request_batch(self.gallery.populate(path))
            self.statusBar().showMessage(path)
            if self.stack.currentWidget() is self.viewer:
                self.close_viewer()

    def _tree_double(self, idx):
        path = self.fs.filePath(idx)
        if os.path.isfile(path):
            self.open_asset(path)

    # ----- open / close / step
    def open_asset(self, path: str):
        self.token += 1
        self.current_path = path
        name = os.path.basename(path)
        self.stack.setCurrentWidget(self.viewer)
        self._sync_shortcuts()
        self.viewer.show_loading(name)
        self.setWindowTitle(f"{name} — {APP_NAME}")
        task = LoadTask(self.token, path)
        task.signals.done.connect(self._on_loaded)
        task.signals.failed.connect(self._on_failed)
        self._tasks[self.token] = task   # keep signal QObject alive until delivered
        self.pool.start(task)

    def _step(self, delta: int):
        """Open the previous/next model in the folder (as sorted/filtered in the gallery)."""
        if self.stack.currentWidget() is not self.viewer:
            return
        paths = self.gallery.asset_paths()
        cur_dir = os.path.dirname(self.current_path)
        if self.current_path not in paths:
            paths = scan_assets(cur_dir) if cur_dir else []
        if not paths:
            return
        if self.current_path in paths:
            nxt = paths[(paths.index(self.current_path) + delta) % len(paths)]
        else:
            nxt = paths[0] if delta > 0 else paths[-1]
        self.open_asset(nxt)
        self.gallery.select_path(nxt)

    def _on_loaded(self, token: int, actors, path: str):
        self._tasks.pop(token, None)
        if token != self.token or self.stack.currentWidget() is not self.viewer:
            return
        try:
            self.viewer.show_model(actors, os.path.basename(path), path)
        except Exception as e:
            self.viewer.show_error(f"Render failed:\n{e}")

    def _on_failed(self, token: int, msg: str):
        self._tasks.pop(token, None)
        if token == self.token and self.stack.currentWidget() is self.viewer:
            self.viewer.show_error(msg)

    def close_viewer(self):
        self.token += 1                  # invalidate in-flight loads
        self.viewer.clear_scene()
        self.stack.setCurrentWidget(self.gallery_page)
        self._sync_shortcuts()
        self.setWindowTitle(APP_NAME)
        self.gallery.setFocus()
        if self.current_path:
            self.gallery.select_path(self.current_path)

    def closeEvent(self, e):
        self._save_layout()
        self.thumbs.shutdown()
        self.viewer.shutdown()
        super().closeEvent(e)


def _install_crash_handler():
    """The packaged exe has no console, so surface unexpected errors in a dialog + log file."""
    from PySide6.QtWidgets import QMessageBox
    log = os.path.join(tempfile.gettempdir(), "gleek3deek_crash.log")

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        try:
            QMessageBox.critical(None, APP_NAME,
                                 f"Unexpected error:\n\n{value}\n\nDetails were saved to:\n{log}")
        except Exception:
            pass

    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    _install_crash_handler()
    app.setStyleSheet(DARK_QSS)
    start = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(start)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
