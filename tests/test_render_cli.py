"""Render mode: the parts that do not need a GPU (arguments, names, safety)."""
import pytest
from render_cli import build_parser, parse_maps, parse_window, target_path, unique_stems


def test_parse_window():
    assert parse_window("1024x768") == (1024, 768)
    assert parse_window("800×600") == (800, 600)
    for bad in ("1024", "axb", "10x10", "9000x9000", ""):
        with pytest.raises(ValueError):
            parse_window(bad)


def test_parse_maps():
    assert parse_maps("lines,depth") == ["depth", "lines"]        # fixed order
    assert parse_maps("all") == ["depth", "normal", "canny", "lines", "parts"]
    assert parse_maps("") == []
    with pytest.raises(ValueError):
        parse_maps("depth,bogus")


def test_target_path_never_replaces_without_force(tmp_path):
    first = target_path(str(tmp_path), "car", "depth", False)
    assert first and first.endswith("car_depth.png")
    open(first, "w").close()
    assert target_path(str(tmp_path), "car", "depth", False) is None
    assert target_path(str(tmp_path), "car", "depth", True) == first


def test_unique_stems():
    assert unique_stems(["a/car.glb", "b/car.obj", "c/bike.glb"]) == ["car", "car_2", "bike"]


def test_parser_defaults_and_required_out():
    ap = build_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(["model.glb"])                              # --out is required
    a = ap.parse_args(["model.glb", "--out", "x"])
    assert a.view == "front" and a.size == 0 and a.canny == "mid" and not a.force and not a.no_cutout
    a = ap.parse_args(["m.glb", "--out", "x", "--view", "iso", "--fov", "40", "--ortho", "--detail", "high"])
    assert (a.view, a.fov, a.ortho, a.detail) == ("iso", 40.0, True, "high")
