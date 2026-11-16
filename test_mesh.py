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


def test_single_flipped_triangle_marks_only_itself():
    P, T, _ = box()
    T2 = T.copy()
    T2[3] = T2[3][::-1]
    r = mesh_diagnose(P, T2)
    assert r["flags"]["winding"].tolist() == [i == 3 for i in range(12)]
    assert r["stats"]["winding_edges"] == 3 and not r["stats"]["watertight"]


def grid(n=10):
    """A flat n x n sheet of quads (2 n^2 triangles), all facing +z."""
    xs, ys = np.meshgrid(np.arange(n + 1.0), np.arange(n + 1.0))
    P = np.column_stack([xs.ravel(), ys.ravel(), np.zeros((n + 1) ** 2)])
    idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    T = np.vstack([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    q = np.arange(n * n)
    return P, T, q


def test_flipped_patch_is_marked_whole_not_just_its_border():
    P, T, q = grid(10)
    qx, qy = q % 10, q // 10
    patch = (qx >= 3) & (qx < 6) & (qy >= 3) & (qy < 6)          # a 3 x 3 block of quads
    sel = np.concatenate([patch, patch])
    T2 = T.copy()
    T2[sel] = T2[sel][:, ::-1]
    r = mesh_diagnose(P, T2)
    assert r["flags"]["winding"].tolist() == sel.tolist()
    assert r["flags"]["winding"].sum() == 18


def test_a_mostly_flipped_sheet_marks_the_small_good_part():
    P, T, q = grid(10)
    good = (q % 10 < 2)                                           # 2 columns stay as they were
    sel = ~np.concatenate([good, good])
    T2 = T.copy()
    T2[sel] = T2[sel][:, ::-1]
    r = mesh_diagnose(P, T2)
    assert r["flags"]["winding"].tolist() == np.concatenate([good, good]).tolist()


def test_a_consistent_sheet_is_clean_even_when_every_triangle_is_flipped():
    P, T, _ = grid(6)
    for tri in (T, T[:, ::-1].copy()):
        r = mesh_diagnose(P, tri)
        assert not r["flags"]["winding"].any() and r["stats"]["winding_edges"] == 0


def test_two_separate_sheets_are_judged_separately():
    P, T, _ = grid(4)
    P2, T2 = P + [100, 0, 0], T + len(P)
    T2 = T2.copy(); T2[5] = T2[5][::-1]                            # one flipped triangle on the second sheet only
    r = mesh_diagnose(np.vstack([P, P2]), np.vstack([T, T2]))
    w = r["flags"]["winding"]
    assert w.sum() == 1 and w[len(T) + 5]


def test_moebius_strip_falls_back_to_marking_the_seam():
    n = 8                                                          # a strip of 2n triangles whose ends join with a twist
    P = np.array([[np.cos(t) * (2 + s * np.cos(t / 2)), np.sin(t) * (2 + s * np.cos(t / 2)), s * np.sin(t / 2)]
                  for t in np.linspace(0, 2 * np.pi, n, endpoint=False) for s in (-0.5, 0.5)])
    T = []
    for i in range(n):
        j = (i + 1) % n
        a, b, c, d = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
        if i == n - 1:
            c, d = d, c                                            # the half twist: the last rung joins crossed over
        T += [[a, b, c], [b, d, c]]
    r = mesh_diagnose(P, np.array(T))
    assert r["flags"]["winding"].any() and not r["stats"]["watertight"]


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
