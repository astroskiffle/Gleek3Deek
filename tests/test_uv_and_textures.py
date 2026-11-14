import numpy as np

from analysis import (connected_components, fan_triangulate, texture_audit, uv_diagnose, uv_metrics,
                      weighted_median)

QUAD_P = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.]])
QUAD_T = np.array([[0, 1, 2], [0, 2, 3]])


def test_fan_triangulate_splits_polygons():
    tris, parent = fan_triangulate(np.array([0, 4, 7]), np.arange(7))
    assert len(tris) == 3 and sorted(parent.tolist()) == [0, 0, 1]


def test_connected_components():
    comp = connected_components(6, np.array([0, 1, 3]), np.array([1, 2, 4]))
    assert comp[0] == comp[1] == comp[2] and comp[3] == comp[4] and comp[5] not in (comp[0], comp[3])


def test_uv_out_of_bounds():
    uv = QUAD_P[:, :2].copy()
    assert not uv_diagnose(uv, QUAD_T)["oob"].any()
    uv[2] = [1.5, 1.0]
    assert uv_diagnose(uv, QUAD_T)["oob"].all()


def test_uv_metrics_density_and_stretch():
    uv = QUAD_P[:, :2]
    m = uv_metrics(QUAD_P, uv * 0.5, QUAD_T)
    assert np.allclose(m["dens"], 0.5) and np.allclose(m["stretch"], 1.0) and m["valid"].all()
    assert np.allclose(uv_metrics(QUAD_P, uv * [1.0, 3.0], QUAD_T)["stretch"], 3.0)


def test_weighted_median():
    assert weighted_median([1, 2, 3], [1, 1, 1]) == 2.0
    assert weighted_median([], []) == 0.0


def test_texture_audit_memory_and_flags():
    a = texture_audit(2048, 2048, 3, 8, "Base colour")
    assert a["vram"] == int(2048 * 2048 * 4 * 4 / 3) and a["space"] == "sRGB" and not a["npot"] and not a["large"]
    b = texture_audit(1000, 512, 4, 8, "Normal map")
    assert b["npot"] and b["space"] == "Linear"
    assert texture_audit(4096, 4096, 4, 8, "Base colour")["large"]
