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

import hashlib
import json
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
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QDir, QObject, QRunnable, QSettings, QSize,
                            QStandardPaths, Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter,
                           QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QApplication, QFileSystemModel, QFrame,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QListView, QMainWindow,
                               QSplitter, QStackedWidget, QToolButton,
                               QTreeView, QVBoxLayout, QWidget, QAbstractItemView)

# --- VTK (import only what we need: faster startup than `import vtk`) -------
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401  (registers GL backend)
import vtkmodules.vtkInteractionStyle  # noqa: F401  (registers styles)
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
    p = a.GetProperty()
    p.SetColor(0.78, 0.82, 0.88)
    p.SetSpecular(0.25)
    p.SetSpecularPower(30)
    return a


def _cells(a: vtkActor) -> int:
    try:
        ds = a.GetMapper().GetInputAsDataSet()
        return ds.GetNumberOfCells() if ds is not None else 0
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
        ds = m.GetInputAsDataSet()
        if ds is not None and ds.GetNumberOfPoints() > 0:
            _phongify(a)
            if a.GetTexture() is None:
                _apply_color_mode(m, ds)
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
        key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}|v1".encode()).hexdigest()[:24]
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
            img = self._render(pd)
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

    def _render(self, actors) -> QImage:
        self._ensure_window()
        ren, rw = self._ren, self._rw
        for a in actors:
            ren.AddActor(a)
        try:
            ren.ResetCamera()
            cam = ren.GetActiveCamera()
            cam.Azimuth(35)
            cam.Elevation(25)
            cam.OrthogonalizeViewUp()
            ren.ResetCamera()
            cam.Zoom(1.1)
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
class Gallery(QListWidget):
    open_asset = Signal(str)
    open_folder = Signal(str)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setIconSize(QSize(88, 88))
        self.setGridSize(QSize(132, 138))
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFrameShape(QFrame.NoFrame)
        self.itemDoubleClicked.connect(self._activated)
        self._items: dict[str, QListWidgetItem] = {}

    def set_thumb(self, path: str, pm: QPixmap):
        it = self._items.get(path)
        if it is not None:
            it.setIcon(QIcon(pm))

    def populate(self, folder: str) -> list[str]:
        self.clear()
        self._items = {}
        try:
            entries = sorted(os.scandir(folder),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return []
        self.setUpdatesEnabled(False)
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                it = QListWidgetItem(asset_icon("folder"), e.name)
                it.setData(Qt.UserRole, (e.path, True))
                self.addItem(it)
            else:
                ext = asset_ext(e.name)
                if ext in ALL_EXTS:
                    it = QListWidgetItem(asset_icon(ext), e.name)
                    it.setData(Qt.UserRole, (e.path, False))
                    it.setToolTip(e.path)
                    self.addItem(it)
                    self._items[e.path] = it
        self.setUpdatesEnabled(True)
        return list(self._items)

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


class Viewer(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.mode = "surface"
        self.actors: list = []
        self.matcap_idx = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        lay.addWidget(self.vtk_widget)

        self.renderer = vtkRenderer()
        self.renderer.GradientBackgroundOn()
        self.renderer.SetBackground(0.07, 0.08, 0.10)
        self.renderer.SetBackground2(0.17, 0.19, 0.23)
        self.rw = self.vtk_widget.GetRenderWindow()
        self.rw.AddRenderer(self.renderer)
        self.rw.SetMultiSamples(4)
        self.iren = self.rw.GetInteractor()
        # Trackball: LMB orbit, RMB zoom, MMB pan
        self.iren.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
        self.iren.Initialize()

        # ----- floating HUD (native child so it sits above the GL surface)
        self.hud = QFrame(self)
        self.hud.setAttribute(Qt.WA_NativeWindow, True)
        self.hud.setObjectName("hud")
        h = QHBoxLayout(self.hud)
        h.setContentsMargins(8, 4, 6, 4)
        h.setSpacing(4)
        self.title = QLabel("")
        self.title.setObjectName("hudTitle")
        h.addWidget(self.title)
        for text, tip, fn in (("Wire", "Wireframe (W)", lambda: self.set_mode("wire")),
                              ("Points", "Point cloud (P)", lambda: self.set_mode("points")),
                              ("Shaded", "Shaded surface (S)", lambda: self.set_mode("surface")),
                              ("MatCap", "Cycle MatCaps (M)", lambda: self.cycle_matcap()),
                              ("Reset", "Reset camera (R)", self.reset_camera)):
            b = QToolButton()
            b.setText(text)
            if text == "MatCap":
                self.matcap_btn = b
            b.setToolTip(tip)
            b.clicked.connect(fn)
            h.addWidget(b)
        x = QToolButton()
        x.setText("✕")
        x.setObjectName("hudClose")
        x.setToolTip("Close (Esc)")
        x.clicked.connect(self.closed.emit)
        h.addWidget(x)

        self.overlay = Overlay(self)

    # ----- layout -----------------------------------------------------------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.hud.adjustSize()
        self.hud.move(self.width() - self.hud.width() - 12, 12)
        self.hud.raise_()
        if self.overlay.isVisible():
            self.overlay.reposition()

    # ----- state ------------------------------------------------------------
    def clear_scene(self):
        for a in self.actors:
            self.renderer.RemoveActor(a)
        self.actors = []
        self.overlay.hide()
        self.rw.Render()

    def show_loading(self, name: str):
        self.clear_scene()
        self.title.setText(name)
        self.overlay.show_text(f"Loading {name} …", error=False)

    def show_error(self, msg: str):
        self.overlay.show_text("⚠  Could not open asset\n\n" + msg, error=True)

    def show_model(self, actors: list, name: str):
        self.clear_scene()
        faces = 0
        for a in actors:
            a.GetProperty().SetPointSize(2.5)
            self.renderer.AddActor(a)
            faces += _cells(a)
        self.actors = actors
        self.title.setText(f"{name} · {faces:,} faces")
        self.set_mode("surface")
        self.reset_camera()
        self.hud.adjustSize()
        self.hud.move(self.width() - self.hud.width() - 12, 12)
        self.hud.raise_()

    def cycle_matcap(self):
        """M: Red Wax -> Clay Green -> RealSkin -> Framer -> RoughMetal -> normal shading."""
        if not self.actors:
            return
        nxt = 0 if self.mode != "matcap" else self.matcap_idx + 1
        if nxt >= len(MATCAPS):
            self.set_mode("surface")
        else:
            self.matcap_idx = nxt
            self.set_mode("matcap", force=True)

    def set_mode(self, mode: str, force: bool = False):
        if not self.actors:
            return
        if mode == self.mode and mode != "surface" and not force:
            mode = "surface"  # pressing W/P again toggles back to shaded
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
                    a.GetShaderProperty().AddFragmentShaderReplacement(
                        "//VTK::Light::Impl", True, MATCAPS[self.matcap_idx][1], False)
                except Exception:                 # VTK < 9.0 has no per-actor shader property
                    mode = "surface"
        self.mode = mode
        self.matcap_btn.setText(MATCAPS[self.matcap_idx][0] if mode == "matcap" else "MatCap")
        self.hud.adjustSize()
        self.hud.move(self.width() - self.hud.width() - 12, 12)
        self.rw.Render()

    def reset_camera(self):
        self.renderer.ResetCamera()
        self.renderer.GetActiveCamera().Zoom(1.05)
        self.renderer.ResetCameraClippingRange()
        self.rw.Render()

    def shutdown(self):
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
#hudTitle { color:#8d99a8; font-size:11px; padding-right:8px; background:transparent; }
#hud QToolButton { background:#252d38; border:none; border-radius:6px; padding:4px 9px; color:#d5dbe3; }
#hud QToolButton:hover { background:#34506f; }
#hudClose { color:#9aa5b2; } #hudClose:hover { background:#8e2a2a !important; color:#fff; }
"""


class MainWindow(QMainWindow):
    def __init__(self, start: str | None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 820)
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.pool = QThreadPool.globalInstance()
        self.token = 0
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

        # ---- right: stacked gallery / viewer
        self.gallery = Gallery()
        self.gallery.open_asset.connect(self.open_asset)
        self.gallery.open_folder.connect(self.goto_folder)
        self.thumbs = ThumbnailManager()
        self.thumbs.ready.connect(self.gallery.set_thumb)
        self.viewer = Viewer()
        self.viewer.closed.connect(self.close_viewer)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gallery)
        self.stack.addWidget(self.viewer)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1060])
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)

        # ---- hotkeys (only act while viewer is visible)
        for key, fn in (("W", lambda: self.viewer.set_mode("wire")),
                        ("P", lambda: self.viewer.set_mode("points")),
                        ("S", lambda: self.viewer.set_mode("surface")),
                        ("M", self.viewer.cycle_matcap),
                        ("R", self.viewer.reset_camera),
                        ("Esc", self.close_viewer)):
            QShortcut(QKeySequence(key), self, activated=self._guard(fn))

        self.statusBar().setStyleSheet("color:#7c8794;")
        self._restore(start)

    # ----- helpers
    def _guard(self, fn):
        return lambda: fn() if self.stack.currentWidget() is self.viewer else None

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
            self.thumbs.request_batch(self.gallery.populate(path))
            self.statusBar().showMessage(path)
            if self.stack.currentWidget() is self.viewer:
                self.close_viewer()

    def _tree_double(self, idx):
        path = self.fs.filePath(idx)
        if os.path.isfile(path):
            self.open_asset(path)

    # ----- open / close
    def open_asset(self, path: str):
        self.token += 1
        name = os.path.basename(path)
        self.stack.setCurrentWidget(self.viewer)
        self.viewer.show_loading(name)
        self.setWindowTitle(f"{name} — {APP_NAME}")
        task = LoadTask(self.token, path)
        task.signals.done.connect(self._on_loaded)
        task.signals.failed.connect(self._on_failed)
        self._tasks[self.token] = task   # keep signal QObject alive until delivered
        self.pool.start(task)

    def _on_loaded(self, token: int, actors, path: str):
        self._tasks.pop(token, None)
        if token != self.token or self.stack.currentWidget() is not self.viewer:
            return
        try:
            self.viewer.show_model(actors, os.path.basename(path))
        except Exception as e:
            self.viewer.show_error(f"Render failed:\n{e}")

    def _on_failed(self, token: int, msg: str):
        self._tasks.pop(token, None)
        if token == self.token and self.stack.currentWidget() is self.viewer:
            self.viewer.show_error(msg)

    def close_viewer(self):
        self.token += 1                  # invalidate in-flight loads
        self.viewer.clear_scene()
        self.stack.setCurrentWidget(self.gallery)
        self.setWindowTitle(APP_NAME)
        self.gallery.setFocus()

    def closeEvent(self, e):
        self.thumbs.shutdown()
        self.viewer.shutdown()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(DARK_QSS)
    start = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(start)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
