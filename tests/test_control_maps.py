"""Depth / normal / Canny control maps: the maths behind them."""
import numpy as np
from analysis import combine_lines, control_scale, cutout_code, background_mask, canny_edges, canny_from_passes, depth_range, depth_shader


def test_depth_range_uses_distance_along_view_axis():
    # camera at the origin looking down -z: the view matrix is the identity, distance = -z
    pts = [(0, 0, -2), (1, 1, -5), (-1, 0, -3)]
    near, far = depth_range(pts, np.eye(4))
    assert (near, far) == (2.0, 5.0)


def test_depth_range_never_zero_or_empty():
    near, far = depth_range([(0, 0, -1), (0, 0, -1)], np.eye(4))
    assert near > 0 and far > near
    near, _ = depth_range([(0, 0, 3)], np.eye(4))     # behind the camera
    assert near > 0


def test_depth_shader_mentions_the_range():
    code = depth_shader(2.0, 6.0)
    assert "vertexVC.z" in code and "fragOutput0" in code
    assert "2" in code and "4" in code                # near and span


def test_background_mask():
    img = np.zeros((4, 4, 3), np.uint8)
    img[1:3, 1:3] = 50
    m = background_mask(img, (0, 0, 0))
    assert m.sum() == 4 and m[1, 1] and not m[0, 0]


def _square(n=64):
    img = np.zeros((n, n), np.float32)
    img[16:48, 16:48] = 1.0
    return img


def test_canny_finds_square_outline_and_not_inside():
    e = canny_edges(_square(), mask=_square() > 0, high=0.2)
    assert e.sum() > 60                                # a ring of pixels
    assert not e[28:36, 28:36].any()                   # nothing in the flat middle
    assert not e[:8].any()                             # nothing in the flat background
    ys, xs = np.nonzero(e)
    assert 12 <= ys.min() and ys.max() <= 52


def test_canny_flat_image_has_no_edges():
    assert not canny_edges(np.full((32, 32), 0.5, np.float32)).any()


def test_canny_from_passes_is_white_on_black():
    d = np.zeros((64, 64, 3), np.uint8)
    d[16:48, 16:48] = 200
    n = np.full((64, 64, 3), 128, np.uint8)
    out = canny_from_passes(d, n, d[..., 0] > 0)
    assert out.shape == (64, 64, 3) and out.dtype == np.uint8
    assert set(np.unique(out)) <= {0, 255} and out.max() == 255


def test_control_scale():
    assert control_scale(0, 800, 600, 2) == 2           # 0 = keep the screenshot scale
    assert control_scale(1024, 800, 600, 2) == 2        # ceil(1024 / 800)
    assert control_scale(512, 800, 600, 2) == 1
    assert control_scale(3072, 400, 300, 2) == 4        # capped; the rest is resampled


def test_cutout_code():
    assert "discard" not in cutout_code(False)          # no alpha channel: just drop VTK's colour multiply
    code = cutout_code(True, 0.5)
    assert "discard" in code and "texture_0" in code and "0.500" in code


def test_combine_lines_merges_feature_lines_and_outline():
    d = np.zeros((64, 64, 3), np.uint8)
    d[16:48, 16:48] = 200
    feat = np.zeros((64, 64, 3), np.uint8)
    feat[30, 20:44] = 255                              # a crease line inside the model
    out = combine_lines(feat, d, d[..., 0] > 0)
    assert out.dtype == np.uint8 and set(np.unique(out)) <= {0, 255}
    assert out[30, 25, 0] == 255                       # the crease survives
    assert out[16:48, 14:18].max() == 255              # and the outline is added
    assert out[:8].max() == 0
    thick = combine_lines(feat, d, d[..., 0] > 0, thickness=3)
    assert (thick > 0).sum() > (out > 0).sum()
