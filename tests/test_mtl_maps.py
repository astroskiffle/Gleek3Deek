"""The .mtl reader: maps, options, names with spaces, material order."""
import numpy as np
from formats import _mtl_file_name, obj_material_sequence, parse_mtl


def test_file_name_skips_options_and_keeps_spaces():
    assert _mtl_file_name("-bm 1.000 tex/a b.png") == "tex/a b.png"
    assert _mtl_file_name("-s 1 1 1 -o 0 0 0 n.png") == "n.png"
    assert _mtl_file_name('"x.png"') == "x.png"


def test_parse_mtl_reads_every_map_and_factor(tmp_path):
    for n in ("c.png", "r.png", "m.png", "n.png", "e.png", "ao.png", "my tex.png"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "s.mtl").write_text(
        "# c\nnewmtl A\nKd 0.5 0.25 0.1\nPr 0.4\nPm 1\nmap_Kd c.png\nmap_Pr r.png\nmap_Pm m.png\n"
        "map_Bump -bm 1.0 n.png\nmap_Ke e.png\nmap_Ka ao.png\n"
        "newmtl B\nmap_Kd my tex.png\nnorm missing.png\n", encoding="utf-8")
    m = parse_mtl(str(tmp_path / "s.mtl"))
    a = m["A"]
    assert a["kd"] == (0.5, 0.25, 0.1) and a["pr"] == 0.4 and a["pm"] == 1.0
    assert set(a["maps"]) == {"base", "roughness", "metallic", "normal", "emissive", "occlusion"}
    assert a["maps"]["normal"].endswith("n.png")
    assert m["B"]["maps"] == {"base": str(tmp_path / "my tex.png")}     # missing files are skipped


def test_material_sequence_and_missing_mtl(tmp_path):
    (tmp_path / "a.obj").write_text("o x\nusemtl M1\nf 1 2 3\no y\nusemtl M2\nusemtl M1\n")
    assert obj_material_sequence(str(tmp_path / "a.obj")) == ["M1", "M2", "M1"]
    assert parse_mtl(str(tmp_path / "none.mtl")) == {}


def test_importer_material_names_parse_the_description():
    from formats import importer_material_names

    class Imp:
        def GetOutputsDescription(self):
            return ("data output 0 with material named Mat A texture file none diffuse color (1, 1, 1)\n"
                    "data output 1 with material named B texture file x.png diffuse color (0, 0, 0)\n")
    assert importer_material_names(Imp()) == {0: "Mat A", 1: "B"}
    assert importer_material_names(object()) == {}


# --- faces without texture coordinates (vtkOBJImporter drops them) --------------------------------------------
def test_patch_obj_missing_uv_rewrites_only_uvless_faces():
    from formats import patch_obj_missing_uv
    src = (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\n"
           b"f 1/1/1 2/2/1 3/3/1\n"
           b"f 1//1 2//1 3//1\n"
           b"f 1 2 3\n")
    out = patch_obj_missing_uv(src).decode().split("\n")
    assert out[7] == "vt 0 0"                          # one placeholder, before the first face
    faces = [ln for ln in out if ln.startswith("f ")]
    assert faces[0] == "f 1/1/1 2/2/1 3/3/1"           # already complete: untouched
    assert faces[1] == "f 1/4/1 2/4/1 3/4/1"           # v//vn -> v/dummy/vn
    assert faces[2] == "f 1/4 2/4 3/4"                 # plain v -> v/dummy


def test_patch_obj_missing_uv_nothing_to_do():
    from formats import patch_obj_missing_uv
    assert patch_obj_missing_uv(b"v 0 0 0\nvt 0 0\nvn 0 0 1\nf 1/1/1 1/1/1 1/1/1\n") is None
    assert patch_obj_missing_uv(b"v 0 0 0\nf 1 1 1\nf -1 -1 -1\n") is None      # relative indices: leave alone
