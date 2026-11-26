"""Scene OBJ writer: objects, quads/n-gons, UVs, normals, vertex colours, .mtl and PNG textures."""
import os
import struct
import zlib
import numpy as np
import pytest

from exporters import png_bytes, safe_name, unique_names, write_obj_scene


def cells(*faces):
    off, conn = [0], []
    for f in faces:
        conn.extend(f)
        off.append(len(conn))
    return np.array(off), np.array(conn)


def part(name, material=None, uv=True, nrm=True, col=False, shift=0.0):
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0.5, 0]], float) + [shift, 0, 0]
    return {"name": name, "points": pts, "faces": cells([0, 1, 2, 3], [1, 4, 2]),
            "lines": cells([0, 2]),
            "normals": np.tile([0.0, 0.0, 1.0], (5, 1)) if nrm else None,
            "uvs": np.array([[0, 0], [1, 0], [1, 1], [0, 1], [.5, .5]]) if uv else None,
            "colors": np.array([[1, 0, 0]] * 5, float) if col else None, "material": material}


def mat(name="Metal", tex=True):
    m = {"name": name, "kd": (0.5, 0.25, 0.1), "opacity": 1.0, "metallic": 1.0, "roughness": 0.4,
         "tex": {}, "tex_ids": {}}
    if tex:
        img = np.full((4, 4, 3), 200, np.uint8)
        m["tex"] = {"base": img, "roughness": img[:, :, 0], "metallic": img[:, :, 0], "normal": img}
        m["tex_ids"] = {"base": 1, "roughness": 2, "metallic": 2, "normal": 3}
    return m


def read(p):
    return open(p, encoding="utf-8").read().splitlines()


def test_png_roundtrip_is_valid(tmp_path):
    data = png_bytes(np.arange(12, dtype=np.uint8).reshape(2, 2, 3))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    assert (w, h) == (2, 2)
    i = data.index(b"IDAT")
    n = struct.unpack(">I", data[i - 4:i])[0]
    raw = zlib.decompress(data[i + 4:i + 4 + n])
    assert len(raw) == 2 * (1 + 6)
    assert png_bytes(np.zeros((3, 3), np.uint8))[:4] == b"\x89PNG"


def test_names_are_made_safe_and_unique():
    assert safe_name("Blade 01/x", "p") == "Blade_01_x"
    assert unique_names(["a", "a", ""], "P") == ["a", "a_2", "P_3"]


def test_objects_quads_ngons_edges_and_offsets(tmp_path):
    p = str(tmp_path / "m.obj")
    st = write_obj_scene([part("Body"), part("Body", shift=5)], {}, p, write_materials=False)
    L = read(p)
    assert [l for l in L if l.startswith("o ")] == ["o Body", "o Body_2"]
    assert st["objects"] == 2 and st["faces"] == 4 and st["edges"] == 2
    assert "f 1/1/1 2/2/2 3/3/3 4/4/4" in L                 # the quad survives
    assert "f 6/6/6 7/7/7 8/8/8 9/9/9" in L                 # indices continue across objects
    assert "l 1 3" in L and "l 6 8" in L
    assert not (tmp_path / "m.mtl").exists()


def test_vertex_colours_and_missing_uv_normals(tmp_path):
    p = str(tmp_path / "c.obj")
    write_obj_scene([part("A", uv=False, nrm=False, col=True)], {}, p, False)
    L = read(p)
    assert "v 0 0 0 1.0000 0.0000 0.0000" in L
    assert "f 1 2 3 4" in L and "s off" in L
    p2 = str(tmp_path / "d.obj")
    write_obj_scene([part("A", uv=False)], {}, p2, False)
    assert "f 1//1 2//2 3//3 4//4" in read(p2) and "s 1" in read(p2)


def test_materials_mtl_and_textures(tmp_path):
    p = str(tmp_path / "scene.obj")
    st = write_obj_scene([part("A", 0), part("B", 0)], {0: mat("Brass")}, p, True)
    L = read(p)
    assert "mtllib scene.mtl" in L and L.count("usemtl Brass") == 2
    m = read(str(tmp_path / "scene.mtl"))
    assert "newmtl Brass" in m and "Pr 0.4000" in m and "Pm 1.0000" in m
    assert "map_Kd scene_textures/Brass_basecolor.png" in m
    assert "map_Pr scene_textures/Brass_roughness.png" in m
    assert "map_Pm scene_textures/Brass_metallic.png" in m
    assert "map_Bump -bm 1.000 scene_textures/Brass_normal.png" in m
    for f in ("basecolor", "roughness", "metallic", "normal"):
        assert (tmp_path / "scene_textures" / f"Brass_{f}.png").stat().st_size > 0
    assert st["materials"] == 1 and st["textures"] == 4


def test_shared_image_is_written_once_and_no_materials_means_no_folder(tmp_path):
    m = mat("Same")
    m["tex_ids"]["metallic"] = m["tex_ids"]["roughness"] = 7
    write_obj_scene([part("A", 0)], {0: m}, str(tmp_path / "a.obj"), True)
    write_obj_scene([part("A", 0)], {0: m}, str(tmp_path / "b.obj"), False)
    assert not (tmp_path / "b.mtl").exists() and not (tmp_path / "b_textures").exists()


def test_empty_scene_raises(tmp_path):
    with pytest.raises(ValueError):
        write_obj_scene([{"name": "x", "points": np.zeros((0, 3)), "faces": None}], {}, str(tmp_path / "e.obj"))


def read_glb(path):
    import json
    b = open(path, "rb").read()
    magic, ver, total = struct.unpack("<III", b[:12])
    assert (magic, ver, total) == (0x46546C67, 2, len(b))
    jl, jt = struct.unpack("<II", b[12:20])
    doc = json.loads(b[20:20 + jl])
    bl, bt = struct.unpack("<II", b[20 + jl:28 + jl])
    assert jt == 0x4E4F534A and bt == 0x004E4942 and (20 + jl) % 4 == 0 and bl % 4 == 0
    return doc, b[28 + jl:28 + jl + bl]


def test_glb_structure_uv_flip_and_materials(tmp_path):
    from exporters import write_glb_scene
    p = str(tmp_path / "m.glb")
    st = write_glb_scene([part("A", 0, col=True), part("B", 0, uv=False)], {0: mat("Brass")}, p)
    doc, binc = read_glb(p)
    assert len(doc["meshes"]) == 2 and st["faces"] == 6          # quad + triangle, twice
    prim = doc["meshes"][0]["primitives"][0]
    assert set(prim["attributes"]) == {"POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"}
    uvacc = doc["accessors"][prim["attributes"]["TEXCOORD_0"]]
    bv = doc["bufferViews"][uvacc["bufferView"]]
    uv = np.frombuffer(binc, "<f4", count=uvacc["count"] * 2, offset=bv["byteOffset"]).reshape(-1, 2)
    assert np.allclose(uv[2], [1, 0])                           # v = 1 in the OBJ convention is 0 in glTF
    pos = doc["accessors"][prim["attributes"]["POSITION"]]
    assert pos["max"] == [2.0, 1.0, 0.0]
    m = doc["materials"][0]["pbrMetallicRoughness"]
    assert {"baseColorTexture", "metallicRoughnessTexture"} <= set(m) and "normalTexture" in doc["materials"][0]
    assert len(doc["materials"]) == 1 and doc["images"][0]["mimeType"] == "image/png"
    idx = doc["accessors"][prim["indices"]]
    assert idx["componentType"] == 5125 and idx["count"] == 9


def test_glb_without_materials_and_empty(tmp_path):
    from exporters import write_glb_scene
    p = str(tmp_path / "n.glb")
    write_glb_scene([part("A", 0)], {0: mat()}, p, write_materials=False)
    doc, _ = read_glb(p)
    assert "materials" not in doc and "images" not in doc
    with pytest.raises(ValueError):
        write_glb_scene([{"name": "x", "points": np.zeros((0, 3)), "faces": None}], {}, str(tmp_path / "e.glb"))
