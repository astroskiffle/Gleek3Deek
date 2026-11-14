import numpy as np

from analysis import mesh_diagnose
from fakes import box


def test_closed_box_is_clean():
    P, T, _ = box()
    r = mesh_diagnose(P, T)
    s = r["stats"]
    assert s["watertight"] and s["pieces"] == 1 and s["inverted_pieces"] == 0
    assert abs(s["volume"] - 1.0) < 1e-9
    assert not any(f.any() for f in r["flags"].values())


def test_inside_out_box_is_flagged():
    P, T, _ = box()
    r = mesh_diagnose(P, T[:, ::-1].copy())
    assert r["flags"]["inverted"].all() and r["stats"]["inverted_pieces"] == 1


def test_missing_triangle_gives_open_edges():
    P, T, _ = box()
    r = mesh_diagnose(P, T[1:])
    assert r["stats"]["boundary_edges"] == 3
    assert r["flags"]["boundary"].sum() == 3
    assert not r["stats"]["watertight"]


def test_single_flipped_triangle_marks_it_and_its_neighbours():
    P, T, _ = box()
    T2 = T.copy()
    T2[3] = T2[3][::-1]
    r = mesh_diagnose(P, T2)
    assert r["flags"]["winding"][3] and r["stats"]["winding_edges"] == 3 and r["flags"]["winding"].sum() == 4


def test_split_vertices_at_seams_are_not_holes():
    P, T, _ = box()
    P3 = np.vstack([P, P[T[:, 0]]])
    T3 = T.copy()
    T3[::2, 0] = 8 + np.arange(0, 12, 2)
    r = mesh_diagnose(P3, T3)
    assert r["stats"]["boundary_edges"] == 0 and r["stats"]["dup_verts"] > 0


def test_loose_vertex_degenerate_duplicate_and_second_piece():
    P, T, _ = box()
    P4 = np.vstack([P, [[5, 5, 5]], P + [3, 0, 0]])
    T4 = np.vstack([T, T + 9, [[0, 1, 1]], T[:1]])
    r = mesh_diagnose(P4, T4)
    assert r["stats"]["loose"] == 1 and r["stats"]["pieces"] == 2
    assert r["flags"]["degen"][-2] and r["flags"]["dupface"][0] and r["flags"]["dupface"][-1]


def test_non_manifold_edge():
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]], float)
    T = np.array([[0, 1, 2], [1, 0, 3], [0, 1, 4]])
    r = mesh_diagnose(P, T)
    assert r["stats"]["nonman_edges"] == 1 and r["flags"]["nonman"].all()


def test_empty_mesh():
    assert mesh_diagnose(np.zeros((0, 3)), np.zeros((0, 3), int))["stats"]["tris"] == 0


def test_large_grid_boundary_count():
    n = 120
    xs, ys = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
    P = np.c_[xs.ravel(), ys.ravel(), np.zeros((n + 1) ** 2)].astype(float)
    idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    T = np.r_[np.c_[a, b, c], np.c_[a, c, d]]
    assert mesh_diagnose(P, T)["stats"]["boundary_edges"] == 4 * n
