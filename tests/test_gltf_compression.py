"""Draco / Meshopt GLB support. The real decoders are optional packages, so these tests plug in stand-ins and
check everything around them: the glTF rewriting, the filters and the error messages."""
import json
import os
import shutil
import struct
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import formats


def make_glb(doc: dict, binc: bytes) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * ((-len(js)) % 4)
    binc += b"\0" * ((-len(binc)) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binc), 0x004E4942) + binc
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def run(tmp_path, doc, binc):
    p = tmp_path / "m.glb"
    p.write_bytes(make_glb(doc, binc))
    out, tmp = formats._fix_glb_webp(str(p))
    assert tmp is not None
    try:
        g = json.load(open(out))
        b = open(os.path.join(tmp, "scene.bin"), "rb").read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return g, b


def read_acc(g, b, i, dtype):
    a = g["accessors"][i]
    v = g["bufferViews"][a["bufferView"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    off = v["byteOffset"] + a.get("byteOffset", 0)
    return np.frombuffer(b, dtype=dtype, count=a["count"] * n, offset=off).reshape(a["count"], n)


def test_draco_primitive_is_rewritten(tmp_path, monkeypatch):
    pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 1]], np.float32)
    fac = np.array([[0, 1, 2], [1, 3, 2]], np.uint32)
    uv = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], np.float32)
    fake = SimpleNamespace(points=pts, faces=fac, normals=None, tex_coord=uv, colors=None)
    monkeypatch.setattr(formats, "_draco_decode", lambda data: fake)
    doc = {"asset": {"version": "2.0"}, "extensionsUsed": ["KHR_draco_mesh_compression"],
           "extensionsRequired": ["KHR_draco_mesh_compression"],
           "buffers": [{"byteLength": 8}], "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 8}],
           "accessors": [{"componentType": 5126, "count": 4, "type": "VEC3"},
                         {"componentType": 5125, "count": 6, "type": "SCALAR"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4,
                                       "extensions": {"KHR_draco_mesh_compression": {
                                           "bufferView": 0, "attributes": {"POSITION": 0, "TEXCOORD_0": 1}}}}]}]}
    g, b = run(tmp_path, doc, b"\x01" * 8)
    prim = g["meshes"][0]["primitives"][0]
    assert "extensions" not in prim
    assert "extensionsUsed" not in g and "extensionsRequired" not in g
    assert np.array_equal(read_acc(g, b, prim["attributes"]["POSITION"], "<f4"), pts)
    assert np.array_equal(read_acc(g, b, prim["attributes"]["TEXCOORD_0"], "<f4"), uv)
    assert np.array_equal(read_acc(g, b, prim["indices"], "<u4").reshape(-1, 3), fac)
    pa = g["accessors"][prim["attributes"]["POSITION"]]
    assert pa["min"] == [0.0, 0.0, 0.0] and pa["max"] == [1.0, 1.0, 1.0]


def test_draco_uses_unique_ids_when_available(monkeypatch):
    class M:
        points = np.zeros((2, 3), np.float32)

        def get_attribute_by_unique_id(self, uid):
            return {"data": np.full((2, 3), float(uid), np.float32)}
    arr = formats._draco_attribute(M(), "NORMAL", 7)
    assert arr.shape == (2, 3) and float(arr[0, 0]) == 7.0


def test_meshopt_views_are_replaced(tmp_path, monkeypatch):
    verts = np.arange(12, dtype="<f4").tobytes()                 # 4 vertices x 12 bytes
    idx = np.array([0, 1, 2, 1, 3, 2], "<u2").tobytes()
    seen = []

    def fake(mode, count, stride, data):
        seen.append((mode, count, stride))
        return verts if mode == "ATTRIBUTES" else idx
    monkeypatch.setattr(formats, "_meshopt_decode", fake)
    ext = lambda mode, off, ln, count, stride: {"EXT_meshopt_compression": {
        "buffer": 0, "byteOffset": off, "byteLength": ln, "byteStride": stride, "count": count, "mode": mode}}
    doc = {"asset": {"version": "2.0"}, "extensionsUsed": ["EXT_meshopt_compression"],
           "extensionsRequired": ["EXT_meshopt_compression"],
           "buffers": [{"byteLength": 16}, {"byteLength": 60, "extensions": {"EXT_meshopt_compression": {"fallback": True}}}],
           "bufferViews": [{"buffer": 1, "byteOffset": 0, "byteLength": 48, "byteStride": 12,
                            "extensions": ext("ATTRIBUTES", 0, 8, 4, 12)},
                           {"buffer": 1, "byteOffset": 48, "byteLength": 12,
                            "extensions": ext("TRIANGLES", 8, 8, 6, 2)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
                         {"bufferView": 1, "componentType": 5123, "count": 6, "type": "SCALAR"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
    g, b = run(tmp_path, doc, b"\x02" * 16)
    assert ("ATTRIBUTES", 4, 12) in seen and ("TRIANGLES", 6, 2) in seen
    assert read_acc(g, b, 0, "<f4").tolist() == np.arange(12, dtype="<f4").reshape(4, 3).tolist()
    assert read_acc(g, b, 1, "<u2").reshape(-1).tolist() == [0, 1, 2, 1, 3, 2]
    assert all(v["buffer"] == 0 and "extensions" not in v for v in g["bufferViews"])
    assert len(g["buffers"]) == 1                                # the unused fallback buffer is dropped
    assert "extensionsRequired" not in g


def test_undecodable_animation_view_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(formats, "_meshopt_decode", lambda m, c, s, d: bytes(c * s))
    doc = {"asset": {"version": "2.0"}, "extensionsUsed": ["EXT_meshopt_compression"],
           "buffers": [{"byteLength": 8}],
           "bufferViews": [{"buffer": 0, "byteLength": 8, "extensions": {"EXT_meshopt_compression": {
               "buffer": 0, "byteOffset": 0, "byteLength": 8, "byteStride": 8, "count": 1, "mode": "ATTRIBUTES",
               "filter": "QUATERNION"}}}],
           "animations": [{"channels": [], "samplers": []}], "meshes": []}
    g, _ = run(tmp_path, doc, b"\0" * 8)
    assert "animations" not in g


def test_missing_decoders_give_install_hints(monkeypatch):
    monkeypatch.setitem(sys.modules, "DracoPy", None)
    monkeypatch.setitem(sys.modules, "meshoptimizer", None)
    with pytest.raises(formats.LoadError, match="pip install DracoPy"):
        formats._draco_decode(b"x")
    with pytest.raises(formats.LoadError, match="pip install meshoptimizer"):
        formats._meshopt_decode("ATTRIBUTES", 1, 4, b"x")


def test_exponential_filter():
    # mantissa 3, exponent -1 -> 1.5 ; mantissa -8, exponent 2 -> -32
    vals = np.array([(((-1) & 0xFF) << 24) | 3, ((2 & 0xFF) << 24) | (-8 & 0xFFFFFF)], dtype="<u4")
    out = np.frombuffer(formats._meshopt_filter("EXPONENTIAL", vals.tobytes(), 2, 4), "<f4")
    assert out.tolist() == [1.5, -32.0]


def test_octahedral_filter():
    # (x, y, one, w) as int8: +Z, +X and a diagonal in the upper hemisphere
    v = np.array([[0, 0, 127, 5], [127, 0, 127, 5], [127, 127, 127, 5]], np.int8)
    out = np.frombuffer(formats._meshopt_filter("OCTAHEDRAL", v.tobytes(), 3, 4), np.int8).reshape(3, 4)
    assert out[0].tolist() == [0, 0, 127, 5]
    assert out[1].tolist() == [127, 0, 0, 5]
    d = out[2, :3].astype(float) / 127
    assert abs(np.linalg.norm(d) - 1) < 0.02 and d[2] < 0                       # folded to the lower hemisphere
    with pytest.raises(formats.LoadError):
        formats._meshopt_filter("QUATERNION", bytes(8), 1, 8)
