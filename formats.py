"""Gleek3Deek file loading: format registry, importers, GLB fixes and scene building.

No windows or widgets in here (Qt is only used to decode WebP images), so it works without a display.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import struct
import tempfile
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from vtkmodules.util import numpy_support
from vtkmodules.vtkCommonCore import VTK_UNSIGNED_CHAR, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkPolyDataNormals
from vtkmodules.vtkFiltersGeometry import vtkCompositeDataGeometryFilter
from vtkmodules.vtkIOGeometry import vtkGLTFReader, vtkOBJReader, vtkSTLReader
from vtkmodules.vtkIOPLY import vtkPLYReader
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer, vtkRenderWindow, vtkTexture
from vtkmodules.vtkIOImage import vtkImageReader2Factory
try:
    from vtkmodules.vtkIOImport import vtkGLTFImporter, vtkOBJImporter
except Exception:  # pragma: no cover
    vtkGLTFImporter = vtkOBJImporter = None
try:
    from vtkmodules.vtkIOOCCT import vtkOCCTReader
except Exception:  # pragma: no cover
    vtkOCCTReader = None


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


# ---------------------------------------------------------------------------
# glTF compatibility (GLB only). VTK's loader rejects two things that modern exporters (Tripo,
# Meshy, gltfpack ...) produce, so a temp copy is made in which they are converted away:
#   * EXT_texture_webp        -> WebP textures are re-encoded as PNG
#   * KHR_mesh_quantization   -> 8/16-bit (often normalised) vertex data is expanded to float32
# VTK is then handed an equivalent .gltf + .bin + .png set.
# ---------------------------------------------------------------------------
_GLTF_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}


_GLTF_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


_GLTF_NORM = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


def _dequantize_gltf(doc: dict, binc: bytes) -> bytes:
    """Expand every non-float vertex attribute accessor (positions, normals, UVs, colours, tangents,
    morph targets) to float32. Returns the (possibly longer) binary buffer and edits `doc` in place.
    Node transforms are left alone: they already carry the de-quantisation scale/offset."""
    accessors, views = doc.get("accessors", []), doc.get("bufferViews", [])
    wanted = set()
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            groups = [prim.get("attributes", {})] + list(prim.get("targets", []))
            for g in groups:
                for idx in g.values():
                    wanted.add(int(idx))
    extra = bytearray()
    pad = (-len(binc)) % 4                            # appended data starts on a 4-byte boundary
    base = len(binc) + pad
    for ai in sorted(wanted):
        if ai >= len(accessors):
            continue
        acc = accessors[ai]
        ct = acc.get("componentType")
        if ct == 5126 or ct not in _GLTF_COMP or acc.get("sparse") or "bufferView" not in acc:
            continue
        ncomp = _GLTF_NCOMP.get(acc.get("type"))
        if ncomp is None:
            continue
        view = views[acc["bufferView"]]
        dt = np.dtype(_GLTF_COMP[ct]).newbyteorder("<")
        count = int(acc["count"])
        stride = int(view.get("byteStride") or ncomp * dt.itemsize)
        off = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        raw = np.ndarray(shape=(count, ncomp), dtype=dt, buffer=binc, offset=off, strides=(stride, dt.itemsize))
        vals = raw.astype(np.float32)
        if acc.get("normalized") and ct in _GLTF_NORM:
            vals = vals / np.float32(_GLTF_NORM[ct])
            if ct in (5120, 5122):
                vals = np.maximum(vals, -1.0)
        data = np.ascontiguousarray(vals, dtype="<f4").tobytes()
        while len(extra) % 4:
            extra.append(0)
        views.append({"buffer": view.get("buffer", 0), "byteOffset": base + len(extra), "byteLength": len(data)})
        extra += data
        acc["bufferView"] = len(views) - 1
        acc["byteOffset"] = 0
        acc["componentType"] = 5126
        acc.pop("normalized", None)
        if count:
            acc["min"] = [float(x) for x in vals.min(0)]
            acc["max"] = [float(x) for x in vals.max(0)]
    if not extra:
        return binc
    return bytes(binc) + b"\0" * pad + bytes(extra)


def _fix_glb_webp(path: str):
    with open(path, "rb") as f:
        if f.read(4) != b"glTF":
            return path, None
        f.seek(12)
        ln, _typ = struct.unpack("<II", f.read(8))
        raw = f.read(ln)                           # first chunk is always the JSON
        if b"EXT_texture_webp" not in raw and b"KHR_mesh_quantization" not in raw:
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
        if binc is not None and "KHR_mesh_quantization" in (doc.get("extensionsUsed", []) + doc.get("extensionsRequired", [])):
            binc = _dequantize_gltf(doc, binc)
            if doc.get("buffers"):
                doc["buffers"][0]["byteLength"] = len(binc)
        for key in ("extensionsUsed", "extensionsRequired"):
            if key in doc:
                doc[key] = [e for e in doc[key] if e not in ("EXT_texture_webp", "KHR_mesh_quantization")]
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
            from PySide6.QtGui import QImage    # only needed to decode WebP textures
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
# Small shared helpers
# ---------------------------------------------------------------------------
def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
