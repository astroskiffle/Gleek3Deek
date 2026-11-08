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
from PySide6.QtCore import (QDir, QObject, QRunnable, QSettings, QSize,
                            QStandardPaths, Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter,
                           QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtCore import QPointF
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGridLayout, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSlider)
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
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkPolyDataNormals
from vtkmodules.vtkFiltersGeometry import vtkCompositeDataGeometryFilter
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkIOGeometry import (vtkGLTFReader, vtkOBJReader,
                                      vtkSTLReader)
from vtkmodules.vtkIOPLY import vtkPLYReader
from vtkmodules.vtkRenderingCore import (vtkActor, vtkPolyDataMapper,
                                         vtkRenderer, vtkRenderWindow,
                                         vtkTexture, vtkWindowToImageFilter)
from vtkmodules.vtkIOImage import vtkImageReader2Factory
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
                    "texture": _material_texture(mat, mdir) if (mat is not None and has_uv) else None})
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
    out = []
    for a in found:
        ren.RemoveActor(a)
        m = a.GetMapper()
        if m is None:
            continue
        m.Update()
        ds = _mapper_data(m)
        if ds is not None and ds.GetNumberOfPoints() > 0:
            a._faces = _face_count(ds)
            _phongify(a)
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

    def refresh(self, path: str):
        """Re-render one thumbnail now (e.g. after its up-axis changed)."""
        cf = self._cache_file(path)
        if cf is not None and not self._disabled:
            self.pending.appendleft((path, cf))
            self._pump()

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


class MatCapEditor(QDialog):
    """Floating editor: sliders and colours for a procedural MatCap, plus preset and image loading."""
    changed = Signal(object)                      # emits a spec dict (debounced)

    def __init__(self, parent, spec: dict):
        super().__init__(parent)
        self.setWindowTitle("MatCap editor")
        self.setWindowFlag(Qt.Tool, True)
        self.setMinimumWidth(400)
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

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)
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

    def __init__(self):
        super().__init__()
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.mode = "surface"
        self.actors: list = []
        self.matcap_idx = 0
        self._editor = None
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
        self.title = QLabel("")
        self.title.setObjectName("hudTitle")
        h.addWidget(self.title)
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

        menu.addAction("MatCap editor…\tE", lambda _=False: self.open_matcap_editor())
        menu.addSeparator()
        menu.addAction("Save screenshot…\tF12", lambda _=False: self.save_screenshot())
        menu.addAction("Copy screenshot\tCtrl+C", lambda _=False: self.copy_screenshot())

        b = QToolButton()
        b.setText("View ▾")
        b.setToolTip("View options")
        b.setMenu(menu)
        b.setPopupMode(QToolButton.InstantPopup)
        return b

    # ----- layout -----------------------------------------------------------
    def _place_hud(self):
        self.hud.adjustSize()
        self.hud.move(max(8, self.width() - self.hud.width() - 12), 12)
        self.hud.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_hud()
        if self.overlay.isVisible():
            self.overlay.reposition()

    def _set_title(self, text: str):
        self.title.setText(self.title.fontMetrics().elidedText(text, Qt.ElideMiddle, 300))
        self.title.setToolTip(text)

    # ----- scene state ------------------------------------------------------
    def clear_scene(self):
        for a in self.actors:
            self.renderer.RemoveActor(a)
        self.actors = []
        self.overlay.hide()
        self._sync_axes()
        self.rw.Render()

    def show_loading(self, name: str):
        self.clear_scene()
        self._set_title(name)
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
        faces = 0
        for a in actors:
            a.GetProperty().SetPointSize(2.5)
            self.renderer.AddActor(a)
            faces += _cells(a)
        self.actors = actors
        self._sync_transp_action(self.transparent)
        self._apply_transparency()
        self._set_title(f"{name} · {faces:,} faces")
        self.set_mode("surface")
        self.set_view("front")
        self._sync_axes()
        self._place_hud()

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
        self.mode = mode
        label = entries[self.matcap_idx][0]
        self.matcap_btn.setText((label if len(label) <= 16 else label[:15] + "…")
                                if mode == "matcap" else "MatCap")
        self._place_hud()
        self.rw.Render()
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

    def open_matcap_editor(self):
        if not self.actors and self.custom is None:
            self.message.emit("Open a model first, then edit its MatCap")
        spec = self.custom if self.custom is not None else default_spec()
        if self._editor is None:
            self._editor = MatCapEditor(self.window(), spec)
            self._editor.changed.connect(self.set_custom_matcap)
        else:
            self._editor.set_spec(spec)
        self._editor.show()
        self._editor.raise_()
        self._editor.activateWindow()
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
        self.message.emit(f"{self.up_axis}-up (remembered for this file)")

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
    def grab_image(self):
        if not self.actors:
            return None
        axes_were_on = self._axes_widget is not None and self.axes_on
        if axes_were_on:
            self._axes_widget.SetEnabled(0)               # clean shot without the gizmo
        self.rw.Render()
        try:
            for scale in (2, 1):
                try:
                    w2i = vtkWindowToImageFilter()
                    w2i.SetInput(self.rw)
                    w2i.SetScale(scale)
                    w2i.SetInputBufferTypeToRGB()
                    w2i.ReadFrontBufferOff()
                    w2i.Update()
                    vimg = w2i.GetOutput()
                    w, h, _ = vimg.GetDimensions()
                    if w == 0 or h == 0:
                        continue
                    arr = numpy_support.vtk_to_numpy(vimg.GetPointData().GetScalars())
                    arr = np.ascontiguousarray(arr.reshape(h, w, 3)[::-1])
                    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
                except Exception:
                    continue
            return None
        finally:
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
QScrollBar:vertical { background:#14181e; width:10px; }
QScrollBar::handle:vertical { background:#2c3542; border-radius:5px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
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
QPushButton { background:#252d38; border:1px solid #2f3947; border-radius:6px; padding:5px 12px; color:#d5dbe3; }
QPushButton:hover { background:#34506f; }
QPushButton:disabled { color:#5c6672; background:#1b2028; }
QDialog { background:#14181e; }
"""


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
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gallery_page)
        self.stack.addWidget(self.viewer)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1060])
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)

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
            ("Esc", self.close_viewer),
        ]
        for i, key in enumerate(("front", "back", "right", "left", "top", "bottom", "iso"), 1):
            bindings.append((str(i), lambda k=key: v.set_view(k)))
        self._viewer_shortcuts = [QShortcut(QKeySequence(k), self, activated=fn)
                                  for k, fn in bindings]
        self._sync_shortcuts()

        self.statusBar().setStyleSheet("color:#7c8794;")
        self._restore(start)

    # ----- toolbar slots
    def _sort_changed(self, idx: int):
        self.settings.setValue("sort_idx", idx)
        self.gallery.set_sort(idx)

    def _size_changed(self, px: int):
        self.settings.setValue("card_px", px)
        self.gallery.set_card_size(px)

    def _counts_changed(self, shown: int, total: int):
        self.count_label.setText(f"{total} models" if shown == total else f"{shown} of {total} models")

    def _sync_shortcuts(self):
        on = self.stack.currentWidget() is self.viewer
        for sc in self._viewer_shortcuts:
            sc.setEnabled(on)

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
