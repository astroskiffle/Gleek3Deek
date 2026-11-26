"""Gleek3Deek scene export: Wavefront OBJ with one object per part, UVs, normals, vertex colours, and a .mtl
with PNG textures (Base Color, Roughness, Metallic, Normal, Emissive).

The writer itself (`write_obj_scene`) works on plain numpy data, so it needs neither VTK nor Qt and is unit tested
without them. `snapshot_export_scene` is the only part that reads VTK actors; call it on the main thread, then
hand the result to the worker thread.
"""
from __future__ import annotations

import os
import re
import struct
import zlib
from pathlib import Path
import numpy as np

TEX_MAX_SIDE = 4096


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def png_bytes(arr) -> bytes:
    """Encode a uint8 array (H, W) / (H, W, 1..4) as PNG. Pure python + zlib, so no imaging library is needed."""
    a = np.asarray(arr)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, c = a.shape
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), a.reshape(h, w * c)], axis=1).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def safe_name(s: str, fallback: str) -> str:
    """OBJ and MTL names are space separated, so spaces and odd characters become underscores."""
    s = re.sub(r"[^\w.\-]+", "_", str(s or "").strip()).strip("_")
    return s or fallback


def unique_names(names: list, fallback: str) -> list:
    seen, out = {}, []
    for i, n in enumerate(names):
        base = safe_name(n, f"{fallback}_{i + 1}")
        k = seen.get(base, 0)
        seen[base] = k + 1
        out.append(base if k == 0 else f"{base}_{k + 1}")
    return out


def _cells_iter(cells):
    """cells is (offsets, connectivity) numpy arrays; yields one index array per cell."""
    off, conn = cells
    for i in range(len(off) - 1):
        yield conn[off[i]:off[i + 1]]


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------
def write_obj_scene(parts: list, materials: dict, path: str, write_materials: bool = True) -> dict:
    """Write `parts` to `path` (.obj) and, when asked, `<stem>.mtl` plus a `<stem>_textures` folder.

    parts: list of dicts with name, points (N,3) world space, faces (offsets, connectivity), and optional
           normals (N,3), uvs (N,2), colors (N,3 in 0-1), lines (offsets, connectivity), material (key).
    materials: key -> dict with name, kd, opacity, metallic, roughness, tex {base, roughness, metallic, normal,
           emissive: uint8 arrays}, and tex_ids {slot: hashable} so a shared image is written once.
    Returns counts for the status message."""
    path = str(path)
    stem = Path(path).stem
    folder = os.path.dirname(os.path.abspath(path))
    mtl_name, tex_dir_name = stem + ".mtl", stem + "_textures"
    names = unique_names([p.get("name") for p in parts], "Part")
    stats = {"objects": 0, "faces": 0, "materials": 0, "textures": 0, "uvs": False, "colors": False,
             "normals": False, "edges": 0}

    used = []                                              # material keys in first-use order
    if write_materials:
        for p in parts:
            k = p.get("material")
            if k is not None and k in materials and k not in used:
                used.append(k)
    mat_names = dict(zip(used, unique_names([materials[k].get("name") for k in used], "Material")))

    out = ["# Gleek3Deek OBJ export"]
    if used:
        out.append(f"mtllib {mtl_name}")
    vbase = tbase = nbase = 1
    for p, name in zip(parts, names):
        pts = np.asarray(p["points"], dtype=np.float64)
        faces, lines = p.get("faces"), p.get("lines")
        nf = max(0, len(faces[0]) - 1) if faces is not None else 0
        nl = max(0, len(lines[0]) - 1) if lines is not None else 0
        if len(pts) == 0 or nf + nl == 0:
            continue
        nrm, uvs, col = p.get("normals"), p.get("uvs"), p.get("colors")
        out.append(f"o {name}")
        if col is not None:
            c = np.clip(np.asarray(col, dtype=np.float64), 0, 1)
            out.extend(f"v {x:.6g} {y:.6g} {z:.6g} {r:.4f} {g:.4f} {b:.4f}"
                       for (x, y, z), (r, g, b) in zip(pts.tolist(), c.tolist()))
            stats["colors"] = True
        else:
            out.extend(f"v {x:.6g} {y:.6g} {z:.6g}" for x, y, z in pts.tolist())
        if uvs is not None:
            out.extend(f"vt {u:.6g} {v:.6g}" for u, v in np.asarray(uvs, dtype=np.float64)[:, :2].tolist())
            stats["uvs"] = True
        if nrm is not None:
            out.extend(f"vn {x:.5g} {y:.5g} {z:.5g}" for x, y, z in np.asarray(nrm, dtype=np.float64).tolist())
            stats["normals"] = True
        mk = p.get("material")
        if mk in mat_names:
            out.append(f"usemtl {mat_names[mk]}")
        out.append("s 1" if nrm is not None else "s off")   # smooth groups follow the normals the mesh carries
        if faces is not None:
            for idx in _cells_iter(faces):
                if len(idx) < 3:
                    continue
                if uvs is not None and nrm is not None:
                    out.append("f " + " ".join(f"{i + vbase}/{i + tbase}/{i + nbase}" for i in idx.tolist()))
                elif uvs is not None:
                    out.append("f " + " ".join(f"{i + vbase}/{i + tbase}" for i in idx.tolist()))
                elif nrm is not None:
                    out.append("f " + " ".join(f"{i + vbase}//{i + nbase}" for i in idx.tolist()))
                else:
                    out.append("f " + " ".join(str(i + vbase) for i in idx.tolist()))
                stats["faces"] += 1
        if lines is not None:
            for idx in _cells_iter(lines):
                if len(idx) >= 2:
                    out.append("l " + " ".join(str(i + vbase) for i in idx.tolist()))
                    stats["edges"] += 1
        stats["objects"] += 1
        vbase += len(pts)
        if uvs is not None:
            tbase += len(uvs)
        if nrm is not None:
            nbase += len(nrm)
    if stats["objects"] == 0:
        raise ValueError("This model has no surface to export.")

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")

    if used:
        tex_dir = os.path.join(folder, tex_dir_name)
        written = {}                                       # (slot-agnostic image id) -> relative file name

        def save(mat_label: str, slot: str, arr, ident) -> str:
            key = (ident, slot) if ident is not None else None
            if key is not None and key in written:
                return written[key]
            os.makedirs(tex_dir, exist_ok=True)
            fn = f"{mat_label}_{slot}.png"
            with open(os.path.join(tex_dir, fn), "wb") as fh:
                fh.write(png_bytes(arr))
            rel = f"{tex_dir_name}/{fn}"
            if key is not None:
                written[key] = rel
            stats["textures"] += 1
            return rel

        m = ["# Gleek3Deek material library", ""]
        for k in used:
            mat, nm = materials[k], mat_names[k]
            kd = mat.get("kd") or (0.8, 0.8, 0.8)
            rough = mat.get("roughness")
            metal = mat.get("metallic")
            tex, ids = mat.get("tex") or {}, mat.get("tex_ids") or {}
            m.append(f"newmtl {nm}")
            m.append(f"Kd {kd[0]:.4f} {kd[1]:.4f} {kd[2]:.4f}")
            m.append("Ka 0.0000 0.0000 0.0000")
            m.append("Ks 0.5000 0.5000 0.5000")
            if "emissive" in tex:
                m.append("Ke 1.0000 1.0000 1.0000")
            else:
                m.append("Ke 0.0000 0.0000 0.0000")
            m.append(f"Ns {((1.0 - rough) ** 2) * 1000.0:.3f}" if rough is not None else "Ns 250.000")
            m.append("Ni 1.500")
            op = float(mat.get("opacity", 1.0))
            m.append(f"d {op:.4f}")
            m.append("illum 2")
            if rough is not None:
                m.append(f"Pr {rough:.4f}")
            if metal is not None:
                m.append(f"Pm {metal:.4f}")
            for slot, tag in (("base", "map_Kd"), ("roughness", "map_Pr"), ("metallic", "map_Pm"),
                              ("normal", "map_Bump -bm 1.000"), ("emissive", "map_Ke")):
                if slot in tex:
                    rel = save(nm, {"base": "basecolor"}.get(slot, slot), tex[slot], ids.get(slot))
                    m.append(f"{tag} {rel}")
                    if slot == "normal":
                        m.append(f"norm {rel}")
            m.append("")
        with open(os.path.join(folder, mtl_name), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(m))
        stats["materials"] = len(used)
    return stats


# ---------------------------------------------------------------------------
# Reading the scene (VTK; main thread only)
# ---------------------------------------------------------------------------
def _cell_arrays(cells):
    """(offsets, connectivity) from a vtkCellArray, VTK 9 or older."""
    from vtkmodules.util import numpy_support
    if cells is None or cells.GetNumberOfCells() == 0:
        return None
    try:
        return (numpy_support.vtk_to_numpy(cells.GetOffsetsArray()).astype(np.int64),
                numpy_support.vtk_to_numpy(cells.GetConnectivityArray()).astype(np.int64))
    except Exception:
        flat = numpy_support.vtk_to_numpy(cells.GetData()).astype(np.int64)
        off, i = [0], 0
        conn = []
        while i < len(flat):
            n = int(flat[i])
            conn.extend(flat[i + 1:i + 1 + n].tolist())
            i += n + 1
            off.append(len(conn))
        return np.asarray(off, np.int64), np.asarray(conn, np.int64)


def part_from_polydata(pd, flat16, name: str = "", material=None) -> dict:
    """Convert one vtkPolyData plus its 4x4 matrix (row-major, 16 numbers) to the writer's part dict."""
    from vtkmodules.util import numpy_support
    from formats import _color_array, uv_v_down
    mat = np.asarray(flat16, dtype=np.float64).reshape(4, 4)
    if pd.GetNumberOfStrips() > 0:                         # strips become triangles
        from vtkmodules.vtkFiltersCore import vtkTriangleFilter
        tf = vtkTriangleFilter()
        tf.SetInputData(pd)
        tf.PassVertsOff()
        tf.PassLinesOn()
        tf.Update()
        pd = tf.GetOutput()
    pts = numpy_support.vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64) if pd.GetNumberOfPoints() else np.zeros((0, 3))
    rot, trans = mat[:3, :3], mat[:3, 3]
    world = pts @ rot.T + trans
    faces = _cell_arrays(pd.GetPolys())
    lines = _cell_arrays(pd.GetLines())
    if faces is not None and np.linalg.det(rot) < 0:       # a mirroring matrix flips the winding
        off, conn = faces
        conn = conn.copy()
        for i in range(len(off) - 1):
            conn[off[i]:off[i + 1]] = conn[off[i]:off[i + 1]][::-1]
        faces = (off, conn)
    nrm = pd.GetPointData().GetNormals()
    normals = None
    if nrm is not None and nrm.GetNumberOfTuples() == len(pts):
        n = numpy_support.vtk_to_numpy(nrm).astype(np.float64)
        try:
            n = n @ np.linalg.inv(rot)                     # inverse-transpose for row vectors
        except np.linalg.LinAlgError:
            pass
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        normals = n / np.where(ln > 1e-12, ln, 1.0)
    tc = pd.GetPointData().GetTCoords()
    uvs = None
    if tc is not None and tc.GetNumberOfTuples() == len(pts):
        uvs = numpy_support.vtk_to_numpy(tc).astype(np.float64)[:, :2]
        if uv_v_down(pd):                                  # glTF V runs down the image; OBJ V runs up
            uvs[:, 1] = 1.0 - uvs[:, 1]
    colors = None
    arr, mode = _color_array(pd)
    if arr is not None and mode == "point" and arr.GetNumberOfTuples() == len(pts):
        c = numpy_support.vtk_to_numpy(arr).astype(np.float64)[:, :3]
        colors = c / 255.0 if arr.GetDataType() == 3 or c.max() > 1.0 else c
    return {"name": name, "points": world, "faces": faces, "lines": lines, "normals": normals,
            "uvs": uvs, "colors": colors, "material": material}


def _channel(arr, ch: int, factor):
    """One channel of an RGB(A) map as an (H, W) uint8 image, scaled by a glTF factor."""
    a = np.asarray(arr)
    g = a[:, :, min(ch, a.shape[2] - 1)] if a.ndim == 3 else a
    if factor is not None and factor < 0.999:
        g = np.clip(g.astype(np.float32) * float(factor), 0, 255)
    return np.ascontiguousarray(g.astype(np.uint8))


def material_from_actor(a, label: str) -> dict:
    from analysis import texture_to_array
    prop = a.GetProperty()
    r, g, b = prop.GetColor()
    mat = {"name": label, "kd": (r, g, b), "opacity": float(prop.GetOpacity()), "metallic": None,
           "roughness": None, "tex": {}, "tex_ids": {}}
    pm = getattr(a, "_pbr_map", None)
    pbr = getattr(a, "_pbr", None)

    mat["_keep"] = []                                   # keeps the texture wrappers alive so id() stays unique

    def grab(tex, slot):
        if tex is None:
            return None
        mat["_keep"].append(tex)
        arr = texture_to_array(tex, TEX_MAX_SIDE)
        if arr is not None:
            mat["tex_ids"][slot] = id(tex)
        return arr

    base = grab(a.GetTexture(), "base")
    if base is not None:
        mat["tex"]["base"] = base
    orm_tex = prop.GetTexture("materialTex")
    if orm_tex is not None:
        mat["_keep"].append(orm_tex)
    orm = texture_to_array(orm_tex, TEX_MAX_SIDE) if orm_tex is not None else None
    if orm is not None and orm.ndim == 3 and orm.shape[2] >= 3:
        metal_f, rough_f = pm if pm is not None else (1.0, 1.0)
        mat["tex"]["roughness"] = _channel(orm, 1, rough_f)
        mat["tex"]["metallic"] = _channel(orm, 2, metal_f)
        mat["tex_ids"]["roughness"] = mat["tex_ids"]["metallic"] = id(orm_tex)
        mat["metallic"], mat["roughness"] = 1.0, 1.0
    elif pbr is not None:
        mat["metallic"], mat["roughness"] = float(pbr[0]), float(pbr[1])
    for slot, tname in (("normal", "normalTex"), ("emissive", "emissiveTex")):
        arr = grab(prop.GetTexture(tname), slot)
        if arr is not None:
            mat["tex"][slot] = arr
    return mat


def snapshot_export_scene(actors: list):
    """(parts, materials) for every visible actor; call on the main thread. Parts sharing a material share one
    entry, so the .mtl and the image files are not duplicated."""
    from formats import _mapper_data
    parts, materials, key_of, alive = [], {}, {}, []
    for a in actors:
        if not a.GetVisibility():
            continue
        ds = getattr(a, "_lod_orig", None) or _mapper_data(a.GetMapper())
        if ds is None or not hasattr(ds, "GetPolys"):
            continue
        m = a.GetMatrix()
        flat = [m.GetElement(i, j) for i in range(4) for j in range(4)]
        sig = getattr(a, "_mat", None)
        texs = [t for t in (a.GetTexture(), a.GetProperty().GetTexture("materialTex"),
                            a.GetProperty().GetTexture("normalTex"),
                            a.GetProperty().GetTexture("emissiveTex")) if t is not None]
        alive.extend(texs)                                  # wrappers must outlive the loop or id() can repeat
        tex_ids = tuple(id(t) for t in texs)
        key = (repr(sig), tex_ids, tuple(round(c, 3) for c in a.GetProperty().GetColor()),
               round(a.GetProperty().GetOpacity(), 3), repr(getattr(a, "_pbr", None)))
        if key not in key_of:
            key_of[key] = len(key_of)
            label = safe_name(getattr(a, "_name", ""), "") or f"Material_{len(key_of)}"
            materials[key_of[key]] = material_from_actor(a, label)
        name = getattr(a, "_name", "") or f"Part_{len(parts) + 1}"
        parts.append(part_from_polydata(ds, flat, name, key_of[key]))
    return parts, materials


# ---------------------------------------------------------------------------
# glTF binary (.glb)
# ---------------------------------------------------------------------------
def _pad4(b: bytes, fill: bytes = b"\x00") -> bytes:
    return b + fill * (-len(b) % 4)


def write_glb_scene(parts: list, materials: dict, path: str, write_materials: bool = True) -> dict:
    """Write `parts` as one .glb: a node and mesh per part, POSITION / NORMAL / TEXCOORD_0 / COLOR_0, triangle
    indices (quads and n-gons are fan-triangulated, glTF has no polygons), metallic-roughness materials with the
    textures embedded as PNG. Loose edges are not written. Input as for write_obj_scene."""
    import json
    names = unique_names([p.get("name") for p in parts], "Part")
    blob = bytearray()
    views, accessors, images, textures, meshes, nodes = [], [], [], [], [], []
    stats = {"objects": 0, "faces": 0, "materials": 0, "textures": 0, "uvs": False, "colors": False,
             "normals": False, "edges": 0}

    def add_view(data: bytes, target=None) -> int:
        while len(blob) % 4:
            blob.append(0)
        v = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            v["target"] = target
        blob.extend(data)
        views.append(v)
        return len(views) - 1

    def add_acc(arr, ctype: str, comp: int, target: int, bounds=False) -> int:
        a = {"bufferView": add_view(arr.tobytes(), target), "componentType": comp, "count": int(len(arr)),
             "type": ctype}
        if bounds:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accessors.append(a)
        return len(accessors) - 1

    gl_mats, mat_index, img_cache = [], {}, {}

    def add_tex(arr, ident, slot="") -> int:
        key = (ident, slot) if ident is not None else id(arr)
        if key not in img_cache:
            images.append({"bufferView": add_view(png_bytes(arr)), "mimeType": "image/png"})
            textures.append({"source": len(images) - 1, "sampler": 0})
            img_cache[key] = len(textures) - 1
            stats["textures"] += 1
        return img_cache[key]

    def material_for(key):
        if not write_materials or key is None or key not in materials:
            return None
        if key in mat_index:
            return mat_index[key]
        m = materials[key]
        kd, tex, ids = m.get("kd") or (0.8, 0.8, 0.8), m.get("tex") or {}, m.get("tex_ids") or {}
        pbr = {"baseColorFactor": [float(kd[0]), float(kd[1]), float(kd[2]), float(m.get("opacity", 1.0))],
               "metallicFactor": float(m["metallic"]) if m.get("metallic") is not None else 0.0,
               "roughnessFactor": float(m["roughness"]) if m.get("roughness") is not None else 1.0}
        out = {"name": safe_name(m.get("name"), "Material"), "pbrMetallicRoughness": pbr}
        if "base" in tex:
            pbr["baseColorTexture"] = {"index": add_tex(tex["base"], ids.get("base"), "base")}
        if "roughness" in tex and "metallic" in tex:       # glTF packs them: green = roughness, blue = metallic
            r, mt = np.asarray(tex["roughness"]), np.asarray(tex["metallic"])
            if r.shape == mt.shape:
                orm = np.stack([np.full_like(r, 255), r, mt], axis=-1)
                pbr["metallicRoughnessTexture"] = {"index": add_tex(orm, ids.get("roughness"), "orm")}
        if "normal" in tex:
            out["normalTexture"] = {"index": add_tex(tex["normal"], ids.get("normal"), "normal")}
        if "emissive" in tex:
            out["emissiveTexture"] = {"index": add_tex(tex["emissive"], ids.get("emissive"), "emissive")}
            out["emissiveFactor"] = [1.0, 1.0, 1.0]
        if float(m.get("opacity", 1.0)) < 0.999:
            out["alphaMode"] = "BLEND"
        gl_mats.append(out)
        mat_index[key] = len(gl_mats) - 1
        return mat_index[key]

    for p, name in zip(parts, names):
        pts = np.asarray(p["points"], dtype=np.float32)
        faces = p.get("faces")
        if len(pts) == 0 or faces is None or len(faces[0]) < 2:
            continue
        tris = []
        for idx in _cells_iter(faces):
            for i in range(1, len(idx) - 1):
                tris.append((idx[0], idx[i], idx[i + 1]))
        if not tris:
            continue
        tri = np.asarray(tris, dtype=np.uint32).reshape(-1)
        attrs = {"POSITION": add_acc(pts, "VEC3", 5126, 34962, bounds=True)}
        if p.get("normals") is not None:
            attrs["NORMAL"] = add_acc(np.asarray(p["normals"], np.float32), "VEC3", 5126, 34962)
            stats["normals"] = True
        if p.get("uvs") is not None:
            uv = np.asarray(p["uvs"], np.float32)[:, :2].copy()
            uv[:, 1] = 1.0 - uv[:, 1]                      # back to glTF's top-down V
            attrs["TEXCOORD_0"] = add_acc(uv, "VEC2", 5126, 34962)
            stats["uvs"] = True
        if p.get("colors") is not None:
            attrs["COLOR_0"] = add_acc(np.clip(np.asarray(p["colors"], np.float32)[:, :3], 0, 1), "VEC3", 5126, 34962)
            stats["colors"] = True
        prim = {"attributes": attrs, "indices": add_acc(tri.reshape(-1, 1), "SCALAR", 5125, 34963)}
        mi = material_for(p.get("material"))
        if mi is not None:
            prim["material"] = mi
        meshes.append({"name": name, "primitives": [prim]})
        nodes.append({"name": name, "mesh": len(meshes) - 1})
        stats["objects"] += 1
        stats["faces"] += len(tris)
    if not stats["objects"]:
        raise ValueError("This model has no surface to export.")
    stats["materials"] = len(gl_mats)
    doc = {"asset": {"version": "2.0", "generator": "Gleek3Deek"}, "scene": 0,
           "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
           "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors}
    if gl_mats:
        doc["materials"] = gl_mats
    if textures:
        doc["images"], doc["textures"] = images, textures
        doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    js = _pad4(json.dumps(doc, separators=(",", ":")).encode("utf-8"), b" ")
    bn = _pad4(bytes(blob))
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bn)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(bn), 0x004E4942) + bn)
    return stats
