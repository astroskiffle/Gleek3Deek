"""Gleek3Deek analysis: texture audit, mesh diagnostics, measurements, UV maths, LOD, export building.

No Qt in here, so it works without a window (command-line use, tests).
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import numpy as np
from vtkmodules.util import numpy_support
from vtkmodules.vtkCommonCore import VTK_UNSIGNED_CHAR
from vtkmodules.vtkCommonDataModel import vtkPolyData
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkCleanPolyData, vtkPolyDataNormals, vtkQuadricDecimation, vtkTriangleFilter
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

from formats import _cells, _color_array, _face_count, _mapper_data, asset_ext, human_size


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
        ds = getattr(a, "_lod_orig", None) or _mapper_data(a.GetMapper())    # never export a LOD preview
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


LOD_LEVELS = [(50, 0.5), (25, 0.75), (10, 0.9)]       # (label: % of triangles kept, reduction asked of the decimator)


def lod_decimate(pd, reduction: float):
    """Quadric-decimated copy of one part, keeping UVs and normals where the filter allows. Texture seams
    are borders of the mesh (their vertices are split), and the decimator protects borders. None on failure."""
    if pd is None:
        return None
    tf = vtkTriangleFilter()
    tf.SetInputData(pd)
    tf.PassLinesOff()
    tf.PassVertsOff()
    tf.Update()
    tri = tf.GetOutput()
    if tri.GetNumberOfPolys() < 100:
        out = vtkPolyData()
        out.ShallowCopy(tri)
        return out
    had_normals = tri.GetPointData().GetNormals() is not None
    dec = vtkQuadricDecimation()
    dec.SetInputData(tri)
    dec.SetTargetReduction(float(reduction))
    for name in ("AttributeErrorMetricOn", "TCoordsAttributeOn", "NormalsAttributeOn"):
        try:
            getattr(dec, name)()
        except Exception:
            pass
    dec.Update()
    out = dec.GetOutput()
    if out.GetNumberOfPolys() == 0:
        return None
    if had_normals and out.GetPointData().GetNormals() is None:
        nf = vtkPolyDataNormals()
        nf.SetInputData(out)
        nf.SplittingOff()
        nf.ConsistencyOff()
        nf.AutoOrientNormalsOff()
        nf.Update()
        out = nf.GetOutput()
    res = vtkPolyData()
    res.ShallowCopy(out)
    return res


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


def texture_fingerprint(tex):
    """Identity of a texture's pixels, so the same image used by several materials (or loaded twice by an
    importer) is recognised as one. Cached on the texture object."""
    fp = getattr(tex, "_gk_fp", None)
    if fp is not None:
        return fp
    try:
        img = tex.GetInput()
        sc = img.GetPointData().GetScalars()
        arr = np.ascontiguousarray(numpy_support.vtk_to_numpy(sc))
        h = hashlib.blake2b(arr.view(np.uint8).ravel(), digest_size=16).hexdigest()
        fp = (tuple(img.GetDimensions()), sc.GetNumberOfComponents(), h)
    except Exception:
        fp = ("id", id(tex))
    try:
        tex._gk_fp = fp
    except Exception:
        pass
    return fp


def texture_facts(tex, role: str):
    """texture_audit() for a VTK texture (bit depth and channel count read from the stored pixels)."""
    try:
        img = tex.GetInput()
        w, h, _ = img.GetDimensions()
        sc = img.GetPointData().GetScalars()
        nc = sc.GetNumberOfComponents()
        bits = numpy_support.vtk_to_numpy(sc).dtype.itemsize * 8
        return texture_audit(w, h, nc, bits, role)
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


# ---------------------------------------------------------------------------
# Texture audit and mesh diagnostics (pure numpy, so they are easy to test)
# ---------------------------------------------------------------------------
def texture_audit(width: int, height: int, channels: int, bits: int, role: str) -> dict:
    """Memory and format facts about one texture. VRAM is an estimate: GPUs store 3-channel images as 4,
    and a full mipmap chain adds a third. 'Compressed' assumes a typical block format (BC7 / BC5, BC4 for
    one channel). Colour space cannot be read from pixels, so it is inferred from the texture's role
    (glTF convention: colour and emissive are sRGB; normal and occlusion/roughness/metallic are linear)."""
    w, h = max(int(width), 0), max(int(height), 0)
    ch = max(int(channels), 1)
    stored = 4 if ch == 3 else ch
    raw = w * h * stored * (max(int(bits), 8) // 8)
    comp = w * h * (0.5 if ch == 1 else 1.0)
    npot = bool(w and h and ((w & (w - 1)) or (h & (h - 1))))
    return {"w": w, "h": h, "channels": ch, "bits": int(bits),
            "space": "sRGB" if role in ("Base colour", "Emissive") else "Linear",
            "vram": int(raw * 4 / 3), "vram_comp": int(comp * 4 / 3), "npot": npot,
            "large": max(w, h) >= 4096}


MESH_TESTS = [
    ("boundary", "Open (boundary) edges", "Triangles with an edge that only one triangle uses: a hole, a gap or an open border. Vertices at the same position count as joined, so UV and normal seams are not reported",
     (40, 120, 255)),
    ("nonman", "Non-manifold edges", "Triangles with an edge shared by three or more triangles (fins, internal faces, T-junction geometry)",
     (150, 235, 40)),
    ("degen", "Zero-area triangles", "Triangles squashed to a line or point (they render nothing and upset normals and bakes)",
     (150, 100, 50)),
    ("winding", "Inconsistent winding", "Triangles next to a neighbour that is wound the opposite way round (flipped normals and black patches). For a whole flipped region this marks its border",
     (0, 190, 150)),
    ("inverted", "Inside-out pieces", "Closed pieces whose volume comes out negative: the whole piece faces inwards",
     (255, 0, 110)),
    ("dupface", "Duplicate faces", "Triangles that sit exactly on top of another triangle (z-fighting, double cost)",
     (255, 110, 0)),
]


FLAG_TESTS = None          # UV_TESTS + MESH_TESTS, assembled after UV_TESTS is defined


def mesh_diagnose(points, tris) -> dict:
    """Topology checks on a triangle mesh. Vertices at the same position (to a tolerance of one millionth of
    the model size) are treated as one, because exporters split vertices for UV and normal seams.
    Returns per-triangle bool flags (keys of MESH_TESTS) plus counts."""
    P = np.asarray(points, np.float64)[:, :3]
    T = np.asarray(tris, np.int64).reshape(-1, 3)
    M = len(T)
    nv = len(P)
    flags = {k: np.zeros(M, bool) for k, *_r in MESH_TESTS}
    st = {"verts": nv, "tris": M, "used": 0, "loose": nv, "unique_pos": 0, "dup_verts": 0, "pieces": 0,
          "boundary_edges": 0, "nonman_edges": 0, "winding_edges": 0, "watertight": False, "volume": 0.0}
    if M == 0 or nv == 0:
        return {"flags": flags, "stats": st}
    lo, hi = P.min(0), P.max(0)
    diag = float(np.linalg.norm(hi - lo)) or 1.0
    tol = max(diag * 1e-6, 1e-12)
    q = np.round((P - lo) / tol).astype(np.int64)
    _u, weld = np.unique(_hash_rows([q[:, 0], q[:, 1], q[:, 2]]), return_inverse=True)
    weld = weld.astype(np.int64)
    nw = int(weld.max()) + 1
    used = np.unique(T)
    st["used"], st["loose"] = int(len(used)), int(nv - len(used))
    st["unique_pos"] = int(len(np.unique(weld[used])))
    st["dup_verts"] = st["used"] - st["unique_pos"]

    W = weld[T]
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    cross = np.cross(b - a, c - a)
    area2 = np.linalg.norm(cross, axis=1)
    degen = (W[:, 0] == W[:, 1]) | (W[:, 1] == W[:, 2]) | (W[:, 0] == W[:, 2]) | (area2 < 1e-12 * diag * diag)
    flags["degen"] = degen
    ok = np.nonzero(~degen)[0]
    if len(ok) == 0:
        return {"flags": flags, "stats": st}
    Wo = W[ok]

    # duplicate faces: same three joined vertices, any order
    srt = np.sort(Wo, axis=1)
    keys = _hash_rows([srt[:, 0], srt[:, 1], srt[:, 2]])
    _k, kinv, kcnt = np.unique(keys, return_inverse=True, return_counts=True)
    flags["dupface"][ok] = kcnt[kinv] > 1

    # edges: undirected key, direction sign, owner triangle
    ea = np.concatenate([Wo[:, 0], Wo[:, 1], Wo[:, 2]])
    eb = np.concatenate([Wo[:, 1], Wo[:, 2], Wo[:, 0]])
    owner = np.tile(np.arange(len(ok)), 3)
    ekey = np.minimum(ea, eb) * nw + np.maximum(ea, eb)
    sign = np.where(ea < eb, 1.0, -1.0)
    _e, einv, ecnt = np.unique(ekey, return_inverse=True, return_counts=True)
    cnt = ecnt[einv]
    sdir = np.bincount(einv, weights=sign, minlength=len(ecnt))
    bnd = cnt == 1
    non = cnt > 2
    wind = (cnt == 2) & (np.abs(sdir[einv]) == 2)
    fb = np.zeros(len(ok), bool); fb[owner[bnd]] = True
    fn = np.zeros(len(ok), bool); fn[owner[non]] = True
    fw = np.zeros(len(ok), bool); fw[owner[wind]] = True
    flags["boundary"][ok] = fb
    flags["nonman"][ok] = fn
    flags["winding"][ok] = fw
    st["boundary_edges"] = int((ecnt == 1).sum())
    st["nonman_edges"] = int((ecnt > 2).sum())
    st["winding_edges"] = int(((ecnt == 2) & (np.abs(sdir) == 2)).sum())

    # pieces (connected through joined vertices) and inside-out detection
    comp = connected_components(nw, np.concatenate([Wo[:, 0], Wo[:, 1]]), np.concatenate([Wo[:, 1], Wo[:, 2]]))
    piece_of = comp[Wo[:, 0]]
    _p, pidx = np.unique(piece_of, return_inverse=True)
    npieces = len(_p)
    st["pieces"] = int(npieces)
    bad = (fb | fn | fw).astype(np.float64)
    piece_bad = np.bincount(pidx, weights=bad, minlength=npieces) > 0
    cen = P.mean(0)
    vol = np.einsum("ij,ij->i", a[ok] - cen, np.cross(b[ok] - cen, c[ok] - cen)) / 6.0
    pvol = np.bincount(pidx, weights=vol, minlength=npieces)
    inv_piece = (~piece_bad) & (pvol < -1e-12 * diag ** 3)
    flags["inverted"][ok] = inv_piece[pidx]
    st["inverted_pieces"] = int(inv_piece.sum())
    st["watertight"] = bool(not piece_bad.any())
    st["volume"] = float(abs(pvol[~piece_bad].sum())) if (~piece_bad).any() else 0.0
    return {"flags": flags, "stats": st}


def material_summary(actors: list) -> dict:
    """Parts versus distinct materials. Each part is one draw call in this viewer; a game engine needs at
    least one draw call per distinct material, and parts that share one can be merged."""
    keys = set()
    for a in actors:
        try:
            prop = a.GetProperty()
            tex = [id(a.GetTexture())] if a.GetTexture() is not None else []
            for name, _l in OTHER_TEXTURE_SLOTS:
                try:
                    t = prop.GetTexture(name)
                except Exception:
                    t = None
                if t is not None:
                    tex.append(id(t))
            col = tuple(round(float(x), 3) for x in prop.GetColor())
            keys.add((tuple(tex), col if not tex else (), round(float(prop.GetOpacity()), 2)))
        except Exception:
            keys.add((id(a),))
    vis = [a for a in actors if a.GetVisibility()]
    return {"parts": len(actors), "visible": len(vis), "materials": len(keys)}


# ----- measurements (Phase B)
UNITS = [("mm", "Millimetres", 0.001), ("cm", "Centimetres", 0.01), ("m", "Metres", 1.0),
         ("in", "Inches", 0.0254), ("ft", "Feet", 0.3048)]


def unit_scale(src: str, dst: str) -> float:
    """Factor that turns a length in `src` units into `dst` units."""
    f = {k: v for k, _l, v in UNITS}
    return f.get(src, 1.0) / f.get(dst, 1.0)


def fmt_num(v: float) -> str:
    v = float(v)
    a = abs(v)
    if a >= 1000:
        return f"{v:,.1f}"
    if a >= 100:
        return f"{v:.2f}"
    if a >= 1:
        return f"{v:.3f}"
    return f"{v:.4f}"


def angle_at(a, b, c) -> float:
    """Angle in degrees at b between the lines b-a and b-c (0 when a point repeats)."""
    u, w = np.asarray(a, float) - np.asarray(b, float), np.asarray(c, float) - np.asarray(b, float)
    nu, nw = np.linalg.norm(u), np.linalg.norm(w)
    if nu < 1e-15 or nw < 1e-15:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(np.dot(u, w) / (nu * nw), -1.0, 1.0))))


def _rot_about(axis, deg):
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    t = np.radians(deg)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * (K @ K)


def obb_fit(points, ndir: int = 96):
    """Oriented bounding box: (axes as columns, extents along them), largest extent first. Starts from the
    principal axes of the extreme points, then turns the box about each axis to make its volume smallest."""
    V = np.asarray(points, np.float64)[:, :3]
    rng = np.random.default_rng(0)
    D = rng.normal(size=(ndir, 3))
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    D32 = D.astype(np.float32)
    best = np.full(ndir, -np.inf)
    worst = np.full(ndir, np.inf)
    ib = np.zeros(ndir, np.int64)
    iw = np.zeros(ndir, np.int64)
    for s0 in range(0, len(V), 40000):                 # chunked so a huge mesh needs no giant matrix
        pr = V[s0:s0 + 40000].astype(np.float32) @ D32.T
        j = pr.argmax(0)
        v = pr[j, np.arange(ndir)]
        m = v > best
        best[m], ib[m] = v[m], j[m] + s0
        j = pr.argmin(0)
        v = pr[j, np.arange(ndir)]
        m = v < worst
        worst[m], iw[m] = v[m], j[m] + s0
    C = V[np.unique(np.concatenate([ib, iw]))]
    if len(C) < 4:
        C = V
    X = C - C.mean(0)
    _ev, R = np.linalg.eigh(X.T @ X / len(C))
    R = R[:, ::-1].copy()

    def vol(M):
        q = C @ M
        return float(np.prod(q.max(0) - q.min(0)))

    cur = vol(R)
    for step, span in ((5.0, 45.0), (1.0, 5.0), (0.2, 1.0), (0.04, 0.2), (0.008, 0.04)):
        for _pass in range(2):
            for i in range(3):
                for ang in np.arange(-span, span + step * 0.5, step):
                    if ang == 0:
                        continue
                    M = _rot_about(R[:, i], ang) @ R
                    v = vol(M)
                    if v < cur * (1 - 1e-12):
                        R, cur = M, v
    q = V @ R
    ext = q.max(0) - q.min(0)
    order = np.argsort(-ext)
    return R[:, order], ext[order]


def mesh_measure(points, tris) -> dict:
    """Surface area, signed volume and centroids of one triangle mesh (points already in world space).
    The signed volume is only a real volume for a closed, consistently wound mesh."""
    P = np.asarray(points, np.float64)[:, :3]
    T = np.asarray(tris, np.int64).reshape(-1, 3)
    if len(T) == 0:
        z = np.zeros(3)
        return {"area": 0.0, "vol": 0.0, "com_vol": z, "com_surf": z, "tri_c": np.zeros((0, 3)), "tri_a": np.zeros(0)}
    o = P[np.unique(T)].mean(0)                        # work near the model: keeps the sums accurate
    a, b, c = P[T[:, 0]] - o, P[T[:, 1]] - o, P[T[:, 2]] - o
    cr = np.cross(b - a, c - a)
    ta = 0.5 * np.linalg.norm(cr, axis=1)
    sv = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    cen = (a + b + c) / 3.0
    vol = float(sv.sum())
    area = float(ta.sum())
    com_vol = (sv[:, None] * (a + b + c) / 4.0).sum(0) / vol if abs(vol) > 1e-300 else cen.mean(0)
    com_surf = (ta[:, None] * cen).sum(0) / area if area > 0 else cen.mean(0)
    return {"area": area, "vol": vol, "com_vol": com_vol + o, "com_surf": com_surf + o,
            "tri_c": cen + o, "tri_a": ta}


def measure_model(parts: list) -> dict:
    """Size and volume of a model from [(world points, triangles), ...].
    Volume and the volume-based centre of mass count closed parts only; open parts are reported."""
    used = []
    area = vol = 0.0
    com_w = np.zeros(3)
    surf_w = np.zeros(3)
    closed_parts = open_parts = 0
    for pts, tris in parts:
        T = np.asarray(tris, np.int64).reshape(-1, 3)
        if len(T) == 0:
            continue
        P = np.asarray(pts, np.float64)[:, :3]
        m = mesh_measure(P, T)
        d = mesh_diagnose(P, T)
        area += m["area"]
        surf_w += m["com_surf"] * m["area"]
        u = P[np.unique(T)]
        used.append(u)
        if d["stats"]["watertight"]:
            v = abs(m["vol"])
            vol += v
            com_w += m["com_vol"] * v
            closed_parts += 1
        else:
            open_parts += 1
    if not used:
        return {}
    allv = np.vstack(used)
    lo, hi = allv.min(0), allv.max(0)
    axes, ext = obb_fit(allv)
    if closed_parts and vol > 0:
        com, kind = com_w / vol, "volume"
    else:
        com, kind = surf_w / max(area, 1e-300), "surface"
    return {"aabb_min": lo, "aabb_max": hi, "obb": ext, "obb_axes": axes, "area": area,
            "volume": vol if closed_parts else None, "com": com, "com_kind": kind,
            "closed_parts": closed_parts, "open_parts": open_parts}


# ---------------------------------------------------------------------------
# UV diagnostics (pure numpy, so they are easy to test)
# ---------------------------------------------------------------------------
UV_TESTS = [
    ("oob", "Out-of-bounds UVs", "Triangles with a UV outside the 0 to 1 square (they sample a repeated or empty texture)",
     (255, 150, 30)),
    ("flip", "Flipped UVs", "Stray triangles whose UV winding is opposite to the rest of the model (they sample the texture mirrored). Whole mirrored islands are reported under Mirrored islands instead",
     (230, 40, 50)),
    ("zero", "Zero-area UVs", "Triangles squashed to a line or point in UV space (they have no texture of their own)",
     (240, 215, 40)),
    ("overlap", "Overlapping islands", "Islands that partly cover each other in UV space (they share texture pixels by accident)",
     (50, 200, 230)),
    ("stack", "Stacked islands", "Islands that sit (almost) exactly on top of each other (they share the same texture pixels on purpose or by mistake)",
     (150, 95, 235)),
    ("mirror", "Mirrored islands", "Whole islands laid out the opposite way round to the model (their texture reads mirrored)",
     (235, 115, 175)),
]


UV_ISLAND_TESTS = ("overlap", "stack", "mirror")      # need island detection, which is computed on demand


FLAG_TESTS = UV_TESTS + MESH_TESTS                  # everything that can colour triangles in the 3D view


UV_COLOR_OK = (176, 184, 194)


UV_COLOR_MIX = (250, 250, 250)                     # more than one problem on the same triangle


def fan_triangulate(offsets, conn):
    """Polygon connectivity (VTK offsets + connectivity) -> (triangles Mx3, parent polygon index per triangle)."""
    offsets = np.asarray(offsets, np.int64)
    conn = np.asarray(conn, np.int64)
    sizes = np.diff(offsets)
    if len(sizes) == 0:
        return np.empty((0, 3), np.int64), np.empty(0, np.int64)
    if (sizes == 3).all():
        return conn[offsets[0]:offsets[0] + 3 * len(sizes)].reshape(-1, 3), np.arange(len(sizes))
    tris, parents = [], []
    for k in np.unique(sizes):
        if k < 3:
            continue
        idx = np.nonzero(sizes == k)[0]
        st = offsets[idx]
        for i in range(1, int(k) - 1):
            tris.append(np.stack([conn[st], conn[st + i], conn[st + i + 1]], 1))
            parents.append(idx)
    if not tris:
        return np.empty((0, 3), np.int64), np.empty(0, np.int64)
    return np.concatenate(tris), np.concatenate(parents)


def uv_diagnose(uv, tris, tol: float = 1e-4):
    """Per-triangle UV tests. Returns bool arrays oob / flip / zero plus the winding that counts as normal.
    'Flipped' means: opposite winding to the majority of the model (the majority sets the UV convention,
    which differs between exporters), so a mirrored half of a symmetrical model is reported too."""
    uv = np.asarray(uv, np.float64)[:, :2]
    tris = np.asarray(tris, np.int64)
    a, b, c = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    area2 = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    tri_uv = np.stack([a, b, c], 1)
    oob = ((tri_uv < -tol) | (tri_uv > 1.0 + tol)).any(axis=(1, 2))
    zero = np.abs(area2) < 1e-12
    sign = np.sign(area2)
    pos, neg = int((sign > 0).sum()), int((sign < 0).sum())
    ref = 1.0 if pos >= neg else -1.0
    flip = (~zero) & (sign != ref)
    return {"oob": oob, "flip": flip, "zero": zero, "ref": ref, "area2": area2}


# ----- islands, overlaps, stacking, mirroring (UV Phase 3)
def _hash_rows(cols):
    """One 64-bit key per row from several int64 columns (collisions are astronomically unlikely)."""
    h = np.zeros(len(cols[0]), np.uint64)
    for k, c in enumerate(cols):
        h = (h * np.uint64(0x9E3779B97F4A7C15) + c.astype(np.uint64) + np.uint64(k + 1)) * np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(29)
    return h


def connected_components(n: int, a, b):
    """Component label per node for an undirected edge list (vectorised union-find with pointer jumping)."""
    parent = np.arange(n)
    a, b = np.asarray(a, np.int64), np.asarray(b, np.int64)
    while True:
        pa, pb = parent[a], parent[b]
        diff = pa != pb
        if not diff.any():
            break
        lo, hi = np.minimum(pa[diff], pb[diff]), np.maximum(pa[diff], pb[diff])
        np.minimum.at(parent, hi, lo)
        while True:
            pp = parent[parent]
            if (pp == parent).all():
                break
            parent = pp
    return parent


def uv_islands(points, uv, tris):
    """Island index per triangle. Vertices that share both their 3D position and their UV count as one (so
    vertices split only for normals do not break an island), and islands are what stays connected through
    shared vertices. Stacked copies of a part stay separate because they sit at different 3D positions."""
    P = np.asarray(points, np.float64)[:, :3]
    uv = np.asarray(uv, np.float64)[:, :2]
    tris = np.asarray(tris, np.int64)
    size = max(float(np.ptp(P, axis=0).max()) if len(P) else 1.0, 1e-12)
    q3 = np.round(P / (size * 1e-6)).astype(np.int64)
    q2 = np.round(uv * 1e6).astype(np.int64)
    key = _hash_rows([q3[:, 0], q3[:, 1], q3[:, 2], q2[:, 0], q2[:, 1]])
    _u, weld = np.unique(key, return_inverse=True)
    weld = weld.ravel()
    t = weld[tris]
    comp = connected_components(len(_u), np.concatenate([t[:, 0], t[:, 1], t[:, 2]]),
                                np.concatenate([t[:, 1], t[:, 2], t[:, 0]]))
    _c, island = np.unique(comp[t[:, 0]], return_inverse=True)
    return island.ravel(), len(_c)


def uv_raster_overlaps(uv, tris, island, n_islands: int, res: int = 512, max_candidates: int = 24_000_000):
    """Rasterise every triangle on a pixel grid (pixel centres, so the result does not depend on vertex order)
    and count: pixels covered per island, and pixels shared by each pair of islands.
    Returns (area[n_islands], {(a, b): shared pixels}) with a < b."""
    uv = np.clip(np.asarray(uv, np.float64)[:, :2], -16.0, 16.0)
    tris = np.asarray(tris, np.int64)
    lo = np.floor(uv.min(0))
    tri_uv = uv[tris]                                       # (M, 3, 2)
    d = (tri_uv[:, 1, 0] - tri_uv[:, 0, 0]) * (tri_uv[:, 2, 1] - tri_uv[:, 0, 1]) \
        - (tri_uv[:, 1, 1] - tri_uv[:, 0, 1]) * (tri_uv[:, 2, 0] - tri_uv[:, 0, 0])
    keep = np.abs(d) > 1e-14
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return np.zeros(n_islands), {}
    R = float(res)
    for _ in range(6):                                      # lower the resolution if the work would explode
        X = (tri_uv[idx, :, 0] - lo[0]) * R
        Y = (tri_uv[idx, :, 1] - lo[1]) * R
        x0, x1 = np.floor(X.min(1)).astype(np.int64), np.floor(X.max(1)).astype(np.int64)
        y0, y1 = np.floor(Y.min(1)).astype(np.int64), np.floor(Y.max(1)).astype(np.int64)
        w, h = x1 - x0 + 1, y1 - y0 + 1
        cnt = w * h
        if cnt.sum() <= max_candidates:
            break
        R *= 0.6
    NI = np.int64(max(n_islands, 1))
    W = np.int64(1 << 20)
    found = []
    start, total = 0, len(idx)
    cum = np.cumsum(cnt)
    while start < total:
        base = cum[start - 1] if start else 0
        end = int(np.searchsorted(cum, base + 3_000_000, side="right"))
        end = min(max(end, start + 1), total)
        c, ww = cnt[start:end], w[start:end]
        rep_i = np.repeat(np.arange(start, end), c)
        k = np.arange(int(c.sum())) - np.repeat(np.cumsum(c) - c, c)
        wr = ww[rep_i - start]
        px = x0[rep_i] + (k % wr)
        py = y0[rep_i] + (k // wr)
        cx, cy = px + 0.5, py + 0.5
        ax, ay = X[rep_i, 0], Y[rep_i, 0]
        bx, by = X[rep_i, 1], Y[rep_i, 1]
        qx, qy = X[rep_i, 2], Y[rep_i, 2]
        dd = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax)
        w0 = ((bx - cx) * (qy - cy) - (by - cy) * (qx - cx)) / dd
        w1 = ((qx - cx) * (ay - cy) - (qy - cy) * (ax - cx)) / dd
        w2 = 1.0 - w0 - w1
        ok = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        pix = (py[ok] + 4096) * W + (px[ok] + 4096)
        isl = island[idx[rep_i[ok]]].astype(np.int64)
        found.append(np.unique(pix * NI + isl))
        start = end
    keys = np.unique(np.concatenate(found)) if found else np.empty(0, np.int64)
    if not len(keys):
        return np.zeros(n_islands), {}
    pix, isl = keys // NI, keys % NI
    area = np.bincount(isl, minlength=n_islands).astype(float)
    # pixels shared by islands: keys are sorted by pixel, then island, so islands that share a pixel are
    # neighbours in the list. Distances 1..3 cover every pair in groups of up to four islands.
    pairs = {}
    for dist in (1, 2, 3):
        if len(keys) <= dist:
            break
        same = pix[dist:] == pix[:-dist]
        if not same.any():
            continue
        a, b = isl[:-dist][same], isl[dist:][same]
        pk, pc = np.unique(a * NI + b, return_counts=True)
        for k, c in zip(pk, pc):
            key2 = (int(k // NI), int(k % NI))
            pairs[key2] = pairs.get(key2, 0) + int(c)
    return area, pairs


def uv_island_tests(points, uv, tris, flip, stack_ratio: float = 0.8, min_ratio: float = 0.05):
    """Overlapping / stacked / mirrored islands. Returns per-triangle bool flags, the island count, the
    number of islands involved in each test, and the 'flip' flags with whole mirrored islands taken out
    (those are reported as mirrored islands instead of as thousands of single flipped triangles)."""
    island, n = uv_islands(points, uv, tris)
    flip = np.asarray(flip, bool)
    ntri = np.bincount(island, minlength=n).astype(float)
    nflip = np.bincount(island, weights=flip.astype(float), minlength=n)
    mirrored = nflip > 0.5 * np.maximum(ntri, 1)
    area, pairs = uv_raster_overlaps(uv, tris, island, n)
    over = np.zeros(n, bool)
    stack = np.zeros(n, bool)
    for (a, b), px in pairs.items():
        r = px / max(min(area[a], area[b]), 1.0)
        if r >= stack_ratio:
            stack[a] = stack[b] = True
        elif r >= min_ratio:
            over[a] = over[b] = True
    return {"overlap": over[island], "stack": stack[island], "mirror": mirrored[island],
            "flip": flip & ~mirrored[island], "n": n,
            "involved": {"overlap": int(over.sum()), "stack": int(stack.sum()), "mirror": int(mirrored.sum())}}


# ----- texel density and stretch (UV Phase 2)
UV_HEAT_MODES = [("off", "Off"), ("density", "Texel density"), ("stretch", "Stretch (distortion)")]


UV_HEAT_DEFAULTS = {"dens_low": 0.5, "dens_high": 2.0, "stretch": 2.0}


_HEAT_STOPS = [(0.0, (50, 110, 255)), (0.5, (60, 200, 100)), (1.0, (230, 50, 50))]      # blue, green, red


_STRETCH_STOPS = [(0.0, (60, 200, 100)), (0.5, (240, 215, 60)), (1.0, (230, 50, 50))]    # green, yellow, red


def uv_metrics(points, uv, tris):
    """Per-triangle texel density and stretch.
    dens   = sqrt(UV area / 3D area): UV units per model unit (0 when either area is degenerate)
    stretch = larger / smaller singular value of the 3D->UV mapping (1 = no distortion apart from uniform
              scale; independent of density; 1000 stands in for 'infinitely squashed')
    area3  = 3D area of the triangle (used to weight the reference density)."""
    P = np.asarray(points, np.float64)[:, :3]
    uv = np.asarray(uv, np.float64)[:, :2]
    tris = np.asarray(tris, np.int64)
    p0, p1, p2 = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    q0, q1, q2 = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    area3 = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    a2 = (q1[:, 0] - q0[:, 0]) * (q2[:, 1] - q0[:, 1]) - (q1[:, 1] - q0[:, 1]) * (q2[:, 0] - q0[:, 0])
    auv = 0.5 * np.abs(a2)
    ok = (auv > 1e-12) & (area3 > 1e-18)
    dens = np.zeros(len(tris))
    dens[ok] = np.sqrt(auv[ok] / area3[ok])
    stretch = np.full(len(tris), 1000.0)
    if ok.any():
        d = np.where(ok, a2, 1.0)[:, None]                                  # 2A, avoiding 0/0
        ss = (p0 * (q1[:, 1] - q2[:, 1])[:, None] + p1 * (q2[:, 1] - q0[:, 1])[:, None]
              + p2 * (q0[:, 1] - q1[:, 1])[:, None]) / d
        st = (p0 * (q2[:, 0] - q1[:, 0])[:, None] + p1 * (q0[:, 0] - q2[:, 0])[:, None]
              + p2 * (q1[:, 0] - q0[:, 0])[:, None]) / d
        a, b, c = (ss * ss).sum(1), (ss * st).sum(1), (st * st).sum(1)
        root = np.sqrt(np.maximum((a - c) ** 2 + 4 * b * b, 0.0))
        big = np.sqrt(np.maximum((a + c + root) / 2, 0.0))
        small = np.sqrt(np.maximum((a + c - root) / 2, 0.0))
        good = ok & (small > 1e-12)
        stretch[good] = np.minimum(big[good] / small[good], 1000.0)
    return {"dens": dens, "stretch": stretch, "area3": area3, "valid": ok}


def weighted_median(values, weights):
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    if not len(values):
        return 0.0
    order = np.argsort(values)
    cum = np.cumsum(weights[order])
    return float(values[order][min(np.searchsorted(cum, cum[-1] / 2.0), len(values) - 1)])


def _ramp(u, stops):
    u = np.clip(np.asarray(u, float), 0.0, 1.0)
    xs = [x for x, _c in stops]
    return np.stack([np.interp(u, xs, [c[k] for _x, c in stops]) for k in range(3)], 1).astype(np.uint8)


def uv_heat_density(dens, valid, ref, low, high):
    """Colours for texel density relative to the reference: blue when below `low` x, green at 1 x, red above
    `high` x (all in log space). Invalid triangles are grey."""
    low = min(max(low, 0.01), 0.99)
    high = max(high, 1.01)
    lr = np.log2(np.maximum(np.asarray(dens, float), 1e-12) / max(ref, 1e-12))
    u = np.where(lr < 0, 0.5 * (1 - lr / np.log2(low)), 0.5 + 0.5 * lr / np.log2(high))
    out = _ramp(u, _HEAT_STOPS)
    out[~np.asarray(valid, bool)] = UV_COLOR_OK
    return out


def uv_heat_stretch(stretch, warn):
    """Colours for stretch: green at 1 (undistorted), yellow half way, red at `warn` and beyond."""
    warn = max(warn, 1.05)
    return _ramp((np.asarray(stretch, float) - 1.0) / (warn - 1.0), _STRETCH_STOPS)


def uv_poly_colors(npoly: int, parent, flags: dict, active: list, base=None):
    """RGB (uint8, npoly x 3) per polygon for the 3D heatmap: grey (or the density / stretch colour given in
    `base`, one per triangle) when fine, a test colour when it fails one of the active tests, magenta when it
    fails several."""
    colors = np.tile(np.array(UV_COLOR_OK, np.uint8), (npoly, 1))
    if base is not None:
        colors[np.asarray(parent)] = base
    hits = np.zeros(npoly, np.int32)
    last = np.zeros(npoly, np.int32)
    for n, (key, _l, _t, col) in enumerate(FLAG_TESTS):
        if key not in active or key not in flags:
            continue
        poly = np.zeros(npoly, bool)
        poly[np.asarray(parent)[flags[key]]] = True
        hits += poly
        last[poly] = n
    for n, (_k, _l, _t, col) in enumerate(FLAG_TESTS):
        colors[(hits == 1) & (last == n)] = col
    colors[hits > 1] = UV_COLOR_MIX
    return colors, hits > 0


# ---------------------------------------------------------------------------
# Reference sheets for 2D-to-3D AI tools (Meshy, Tripo, Rodin, Luma ...)
# ---------------------------------------------------------------------------
SHEET_LAYOUTS = [
    ("ortho4", "4-view orthographic: Front, Back, Left, Right  (recommended)"),
    ("hybrid4", "4-view 3/4 hybrid: Front, 3/4 Front, Side, Back"),
]


SHEET_BACKGROUNDS = [("white", "White", (1.0, 1.0, 1.0)), ("grey", "Neutral mid grey", (0.5, 0.5, 0.5))]


SHEET_CELLS = [512, 768, 1024, 1536, 2048]


# Flat, even light: with no sun, the hemispheric ambient depends only on how much a surface faces
# up, so every side of the model is lit identically (no hard shadows, nothing that changes with angle).
SHEET_ENV = {"enabled": True, "skybox": False, "lighting": True, "shadow": False, "gradient_bg": False,
             "sky": [0.95, 0.95, 0.95], "equator": [0.88, 0.88, 0.88], "ground": [0.76, 0.76, 0.76],
             "sun_int": 0.0, "highlight": 0.0, "ambient": 1.0, "exposure": 0.0, "tonemap": "none",
             "sky_blur": 0.0, "yaw": 0.0}


def sheet_views(layout: str, u, f, r):
    """[(file label, caption, direction from the model towards the camera)] for a layout.
    Every view is level with the horizon (no elevation), which is what keeps the baselines identical."""
    if layout == "hybrid4":
        d34 = (f + r) / np.linalg.norm(f + r)
        return [("front", "Front", f), ("three_quarter", "3/4 Front", d34), ("side", "Side", r), ("back", "Back", -f)]
    return [("front", "Front", f), ("back", "Back", -f), ("left", "Left", -r), ("right", "Right", r)]


def sheet_framing(lo, hi, dirs, up, pad: float = 0.06):
    """One shared orthographic framing for all views: (centre, half-size of a square cell in model units).
    Same centre height and same scale in every view => head and feet land on the same pixel rows."""
    lo, hi, up = np.asarray(lo, float), np.asarray(hi, float), np.asarray(up, float)
    c = (lo + hi) / 2.0
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) - c
    half = float(np.abs(corners @ up).max())
    for d in dirs:
        right = np.cross(-np.asarray(d, float), up)
        right /= np.linalg.norm(right)
        half = max(half, float(np.abs(corners @ right).max()))
    return c, max(half, 1e-9) * (1.0 + pad)


# ---------------------------------------------------------------------------
# Whole-model audit: shared by the viewer panels and the command-line mode
# ---------------------------------------------------------------------------
def world_parts(actors: list) -> list:
    """[(world-space points, triangles)] for the visible parts."""
    out = []
    for a in actors:
        if not a.GetVisibility():
            continue
        try:
            pd = _mapper_data(a.GetMapper())
            if pd is None or pd.GetNumberOfPolys() == 0:
                continue
            polys = pd.GetPolys()
            tris, _par = fan_triangulate(numpy_support.vtk_to_numpy(polys.GetOffsetsArray()),
                                         numpy_support.vtk_to_numpy(polys.GetConnectivityArray()))
            if not len(tris):
                continue
            pts = numpy_support.vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64)[:, :3]
            try:
                a.ComputeMatrix()
            except Exception:
                pass
            m = a.GetMatrix()
            M = np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)])
            out.append((pts @ M[:3, :3].T + M[:3, 3], tris))
        except Exception:
            continue
    return out


def mesh_part_analysis(pd):
    """Integrity analysis of one part's polygons, or None when it has no polygon surface."""
    if pd is None or pd.GetNumberOfPolys() == 0:
        return None
    polys = pd.GetPolys()
    tris, parent = fan_triangulate(numpy_support.vtk_to_numpy(polys.GetOffsetsArray()),
                                   numpy_support.vtk_to_numpy(polys.GetConnectivityArray()))
    if not len(tris):
        return None
    pts = numpy_support.vtk_to_numpy(pd.GetPoints().GetData())
    r = mesh_diagnose(pts, tris)
    return {"flags": r["flags"], "stats": r["stats"], "parent": parent, "npoly": polys.GetNumberOfCells(),
            "first": pd.GetNumberOfVerts() + pd.GetNumberOfLines()}


def mesh_totals(infos: list) -> dict:
    """Totals over the parts' mesh_part_analysis() results (empty dict when there are none)."""
    if not infos:
        return {}
    out = {"parts": 0, "watertight": True, "volume": 0.0,
           **{k: 0 for k in ("verts", "tris", "used", "loose", "unique_pos", "dup_verts", "pieces",
                             "boundary_edges", "nonman_edges", "winding_edges", "inverted_pieces")},
           **{"n_" + k: 0 for k, *_r in MESH_TESTS}}
    for d in infos:
        if d is None:
            continue
        out["parts"] += 1
        st = d["stats"]
        for k in ("verts", "tris", "used", "loose", "unique_pos", "dup_verts", "pieces",
                  "boundary_edges", "nonman_edges", "winding_edges"):
            out[k] += st[k]
        out["inverted_pieces"] += st.get("inverted_pieces", 0)
        out["watertight"] = out["watertight"] and st["watertight"]
        out["volume"] += st["volume"]
        for k, *_r in MESH_TESTS:
            out["n_" + k] += int(d["flags"][k].sum())
    return out


def uv_collect_part(pd):
    """UV analysis of one part (tests, islands, density and stretch), or None when it has no UVs."""
    tc = pd.GetPointData().GetTCoords() if pd is not None else None
    if tc is None or pd.GetNumberOfPolys() == 0:
        return None
    uv = numpy_support.vtk_to_numpy(tc).astype(np.float64)[:, :2]
    polys = pd.GetPolys()
    tris, parent = fan_triangulate(numpy_support.vtk_to_numpy(polys.GetOffsetsArray()),
                                   numpy_support.vtk_to_numpy(polys.GetConnectivityArray()))
    if not len(tris):
        return None
    diag = uv_diagnose(uv, tris)
    pts = numpy_support.vtk_to_numpy(pd.GetPoints().GetData())
    flags = {"oob": diag["oob"], "flip": diag["flip"], "zero": diag["zero"],
             **{k: np.zeros(len(tris), bool) for k in UV_ISLAND_TESTS}}
    isl = None
    if len(tris) <= 2_000_000:                          # island tests need real work: skip huge meshes
        try:
            isl = uv_island_tests(pts, uv, tris, diag["flip"])
            for k in UV_ISLAND_TESTS + ("flip",):
                flags[k] = isl[k]
        except Exception:
            isl = None
    return {"m": uv_metrics(pts, uv, tris), "uv": uv, "tris": tris, "parent": parent,
            "npoly": polys.GetNumberOfCells(), "first": pd.GetNumberOfVerts() + pd.GetNumberOfLines(),
            "flags": flags, "isl": isl, "ref": diag["ref"]}


def uv_report(infos: list, th: dict | None = None) -> dict:
    """Totals of uv_collect_part() results: failures per test, islands, and the share of triangles whose
    texel density or stretch is outside the thresholds (density is compared with the area-weighted median)."""
    th = {**UV_HEAT_DEFAULTS, **(th or {})}
    out = {"has_uv": False, "tris": 0, "islands": 0, "island_tests_ran": True,
           "tests": {k: 0 for k, *_r in UV_TESTS}, "islands_involved": {k: 0 for k in UV_ISLAND_TESTS},
           "density_ref": 0.0, "density_low": 0, "density_high": 0, "stretched": 0, "thresholds": th}
    dens, w = [], []
    for d in infos:
        if d is None:
            continue
        out["has_uv"] = True
        out["tris"] += len(d["tris"])
        for k, *_r in UV_TESTS:
            out["tests"][k] += int(d["flags"][k].sum())
        if d.get("isl") is None:
            out["island_tests_ran"] = False
        else:
            out["islands"] += d["isl"]["n"]
            for k in UV_ISLAND_TESTS:
                out["islands_involved"][k] += d["isl"]["involved"][k]
        ok = d["m"]["valid"]
        dens.append(d["m"]["dens"][ok])
        w.append(d["m"]["area3"][ok])
    if dens:
        ref = weighted_median(np.concatenate(dens), np.concatenate(w))
        out["density_ref"] = ref
        for d in infos:
            if d is None:
                continue
            m = d["m"]
            if ref > 0:
                r = m["dens"] / ref
                out["density_low"] += int(((r < th["dens_low"]) & m["valid"]).sum())
                out["density_high"] += int(((r > th["dens_high"]) & m["valid"]).sum())
            out["stretched"] += int((m["stretch"] > th["stretch"]).sum())
    return out


def to_plain(x):
    """numpy values to plain Python, so results can be written as JSON."""
    if isinstance(x, dict):
        return {str(k): to_plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return to_plain(x.tolist())
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    return x


AUDIT_SECTIONS = ("info", "textures", "mesh", "uv", "measure", "lod")


def audit_model(actors: list, path: str, want, units=("m", "m")) -> dict:
    """Everything the panels show, as plain data. `want` picks the sections (see AUDIT_SECTIONS); 'info' is
    always included. `units` = (what a model unit means, the unit to report in)."""
    want = set(want) | {"info"}
    src, disp = units
    k = unit_scale(src, disp)
    res: dict = {"file": path, "units": {"model": src, "report": disp}}
    info = collect_model_info(actors, path, "")
    info.pop("up", None)
    if info.get("dims"):
        info["dims"] = [d * k for d in info["dims"]]
    res["info"] = info
    res["materials"] = material_summary(actors)
    pds = [_mapper_data(a.GetMapper()) for a in actors]

    if "textures" in want:
        ents, seen, rows = collect_textures(actors), set(), []
        raw = comp = 0
        for e in ents:
            f = texture_facts(e["tex"], e["role"])
            if f is None:
                continue
            fp = texture_fingerprint(e["tex"])
            dup = fp in seen
            seen.add(fp)
            if not dup:
                raw += f["vram"]
                comp += f["vram_comp"]
            rows.append({"role": e["role"], "width": f["w"], "height": f["h"], "channels": f["channels"],
                         "bits": f["bits"], "colour_space_inferred": f["space"], "vram_bytes": f["vram"],
                         "vram_compressed_bytes": f["vram_comp"], "non_power_of_two": f["npot"],
                         "very_large": f["large"], "used_by_parts": len(e["parts"]), "repeat_of_earlier_entry": dup})
        res["textures"] = {"entries": rows, "unique_images": len(seen), "vram_bytes": raw,
                           "vram_compressed_bytes": comp,
                           "largest_side": max([max(r["width"], r["height"]) for r in rows], default=0)}

    if "mesh" in want:
        infos = []
        for pd in pds:
            try:
                infos.append(mesh_part_analysis(pd))
            except Exception:
                infos.append(None)
        t = mesh_totals(infos)
        res["mesh"] = ({} if not t else {
            **{k2: v for k2, v in t.items() if k2 != "volume" and not k2.startswith("n_")},
            "tests": {key: t.get("n_" + key, 0) for key, *_r in MESH_TESTS}})

    if "uv" in want:
        infos = []
        for pd in pds:
            try:
                infos.append(uv_collect_part(pd))
            except Exception:
                infos.append(None)
        res["uv"] = uv_report(infos)

    if "measure" in want:
        r = measure_model(world_parts(actors))
        if r:
            f = {kk: ff for kk, _l, ff in UNITS}
            vol = r["volume"]
            res["measure"] = {
                "bounding_box_size": ((np.asarray(r["aabb_max"]) - np.asarray(r["aabb_min"])) * k),
                "oriented_box_size": np.asarray(r["obb"]) * k,
                "surface_area": r["area"] * k * k,
                "volume": None if vol is None else vol * k ** 3,
                "volume_litres": None if vol is None else vol * f.get(src, 1.0) ** 3 * 1000.0,
                "centre_of_mass": np.asarray(r["com"]) * k, "centre_of_mass_basis": r["com_kind"],
                "closed_parts": r["closed_parts"], "open_parts": r["open_parts"], "unit": disp}
        else:
            res["measure"] = {}

    if "lod" in want:
        tri0 = sum(_face_count(pd) for pd in pds if pd is not None)
        levels = {}
        for lvl, red in LOD_LEVELS:
            n = 0
            for pd in pds:
                if pd is None:
                    continue
                try:
                    c = vtkPolyData()
                    c.ShallowCopy(pd)
                    o = lod_decimate(c, red)
                    n += _face_count(o) if o is not None else _face_count(pd)
                except Exception:
                    n += _face_count(pd)
            levels[str(lvl)] = n
        res["lod"] = {"original_triangles": tri0, "levels": levels}
    return to_plain(res)
