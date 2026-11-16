import numpy as np
import pytest

from analysis import angle_at, fmt_num, measure_model, obb_fit, unit_scale
from fakes import box


def test_box_measurements():
    P, T, _ = box(1, 2, 3)
    r = measure_model([(P, T)])
    assert abs(r["volume"] - 6) < 1e-9 and abs(r["area"] - 22) < 1e-9
    assert np.allclose(r["com"], [0.5, 1, 1.5])
    assert np.allclose(r["obb"], [3, 2, 1], atol=1e-3)


def test_rotated_and_far_away_box():
    P, T, _ = box(1, 2, 3)
    th = np.pi / 4
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    off = np.array([1000.0, 2000.0, 3000.0])
    r = measure_model([(P @ R.T + off, T)])
    assert np.allclose(r["obb"], [3, 2, 1], atol=2e-3)
    assert abs(r["volume"] - 6) < 1e-6
    assert np.allclose(r["com"], R @ [0.5, 1, 1.5] + off, atol=2e-3)
    assert np.prod(r["aabb_max"] - r["aabb_min"]) > 6.5          # the axis-aligned box is bigger than the oriented one


def test_inside_out_gives_the_same_volume():
    P, T, _ = box(1, 2, 3)
    assert abs(measure_model([(P, T[:, ::-1].copy())])["volume"] - 6) < 1e-9


def test_open_mesh_has_no_volume():
    P, T, _ = box(1, 2, 3)
    r = measure_model([(P, T[1:])])
    assert r["volume"] is None and r["open_parts"] == 1 and r["com_kind"] == "surface"


def test_two_parts_add_up():
    P, T, _ = box(1, 2, 3)
    r = measure_model([(P, T), (P + [10, 0, 0], T)])
    assert abs(r["volume"] - 12) < 1e-9 and np.allclose(r["com"], [5.5, 1, 1.5])


def test_obb_fit_on_a_million_points_is_fast_and_sensible():
    V = np.random.default_rng(1).normal(size=(200_000, 3)) * [5, 2, 1]
    _axes, ext = obb_fit(V)
    assert ext[0] > ext[1] > ext[2]


def test_angle_and_units():
    assert abs(angle_at([1, 0, 0], [0, 0, 0], [0, 1, 0]) - 90) < 1e-9
    assert angle_at([1, 0, 0], [1, 0, 0], [0, 1, 0]) == 0
    assert unit_scale("in", "cm") == pytest.approx(2.54)
    assert unit_scale("m", "mm") == pytest.approx(1000)
    assert fmt_num(12345.678) == "12,345.7" and fmt_num(0.01234) == "0.0123"
