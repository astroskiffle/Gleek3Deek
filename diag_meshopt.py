"""Diagnostic for Meshopt GLB files. Run from the Gleek3Deek folder:

    .venv\\Scripts\\python diag_meshopt.py path\\to\\model.glb

It prints what the meshoptimizer package returns and whether the decoded triangles look sane."""
import inspect
import json
import os
import shutil
import sys

import numpy as np

import formats

try:
    import meshoptimizer as mo
    print("meshoptimizer", getattr(mo, "__version__", "?"), "from", mo.__file__)
    for n in ("decode_vertex_buffer", "decode_index_buffer", "decode_index_sequence"):
        f = getattr(mo, n, None)
        print(" ", n, inspect.signature(f) if f else "MISSING")
except Exception as e:
    print("import failed:", e)

path = sys.argv[1]
out, tmp = formats._fix_glb_webp(path)
g = json.load(open(out))
b = open(os.path.join(tmp, "scene.bin"), "rb").read()
shutil.rmtree(tmp, ignore_errors=True)
prim = g["meshes"][0]["primitives"][0]


def acc(i):
    a = g["accessors"][i]
    v = g["bufferViews"][a["bufferView"]]
    ct = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    st = v.get("byteStride") or n * np.dtype(ct).itemsize
    off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    isz = np.dtype(ct).itemsize
    raw = np.ndarray((a["count"], n), dtype=ct, buffer=b, offset=off, strides=(st, isz))
    return raw


idx = acc(prim["indices"]).reshape(-1)
pos = acc(prim["attributes"]["POSITION"]).astype(np.float64)
print("indices:", idx.dtype, idx.size, "max", idx.max(), "min", idx.min(), "vertices", len(pos))
print("position range:", pos.min(0), pos.max(0))
tri = idx.reshape(-1, 3).astype(np.int64)
ok = (tri < len(pos)).all(1)
print("triangles with an index out of range:", int((~ok).sum()))
tri = tri[ok]
p = pos[tri]
diag = np.linalg.norm(pos.max(0) - pos.min(0))
e = np.maximum.reduce([np.linalg.norm(p[:, 0] - p[:, 1], axis=1), np.linalg.norm(p[:, 1] - p[:, 2], axis=1),
                       np.linalg.norm(p[:, 2] - p[:, 0], axis=1)])
print("longest edge / model size: median %.4f  99%% %.4f  max %.4f" % (np.median(e) / diag, np.percentile(e, 99) / diag, e.max() / diag))
print("triangles with an edge longer than 10%% of the model: %d of %d" % (int((e > 0.1 * diag).sum()), len(e)))
print("degenerate triangles (repeated index):", int(((tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2]) | (tri[:, 0] == tri[:, 2])).sum()))
print("vertices never used:", len(pos) - len(np.unique(tri)))
print("first 12 indices:", idx[:12].tolist())
print("first 4 positions:", pos[:4].tolist())
