"""Side-by-side compare: the camera maths, the stepping rule and the camera link (with stand-in viewers)."""
import numpy as np
import pytest

from compare import CameraLink, frame_of, map_camera, neighbour

Y_UP = ((1, 0, 0), (0, 1, 0), (0, 0, 1))          # right, up, front
Z_UP = ((1, 0, 0), (0, 0, 1), (0, -1, 0))


def cam(pos, fp=(0, 0, 0), up=(0, 1, 0), angle=30.0, par=False, scale=1.0):
    return {"pos": pos, "fp": fp, "up": up, "angle": angle, "par": par, "scale": scale}


def test_same_model_maps_to_itself():
    f = frame_of((-1, -1, -1), (1, 1, 1), Y_UP)
    c = cam((2, 3, 5), (0.1, 0.2, 0.3))
    m = map_camera(c, f, f)
    assert np.allclose(m["pos"], c["pos"]) and np.allclose(m["fp"], c["fp"]) and np.allclose(m["up"], c["up"])


def test_bigger_model_gets_proportionally_bigger_camera():
    a = frame_of((-1, -1, -1), (1, 1, 1), Y_UP)
    b = frame_of((-10, -10, -10), (10, 10, 10), Y_UP)
    m = map_camera(cam((0, 0, 4), scale=2.0), a, b)
    assert np.allclose(m["pos"], (0, 0, 40)) and m["scale"] == pytest.approx(20.0)


def test_offset_centre_is_followed():
    a = frame_of((0, 0, 0), (2, 2, 2), Y_UP)
    b = frame_of((100, 0, 0), (102, 2, 2), Y_UP)
    m = map_camera(cam((1, 1, 6), fp=(1, 1, 1)), a, b)
    assert np.allclose(m["fp"], (101, 1, 1)) and np.allclose(m["pos"], (101, 1, 6))


def test_z_up_model_is_viewed_from_its_own_front():
    y = frame_of((-1, -1, -1), (1, 1, 1), Y_UP)
    z = frame_of((-1, -1, -1), (1, 1, 1), Z_UP)
    m = map_camera(cam((0, 0, 5)), y, z)             # in front of a Y-up model
    assert np.allclose(m["pos"], (0, -5, 0))         # in front of a Z-up model (its front is -Y)
    assert np.allclose(m["up"], (0, 0, 1))


def test_view_from_above_stays_above():
    y = frame_of((-1, -1, -1), (1, 1, 1), Y_UP)
    z = frame_of((-1, -1, -1), (1, 1, 1), Z_UP)
    m = map_camera(cam((0, 5, 0.001), up=(0, 0, -1)), y, z)
    assert m["pos"][2] > 4.9                         # above the Z-up model


def test_empty_bounds_do_not_divide_by_zero():
    f = frame_of((1, 1, 1), (1, 1, 1), Y_UP)
    m = map_camera(cam((1, 1, 2), fp=(1, 1, 1)), f, f)
    assert np.all(np.isfinite(m["pos"]))


def test_lens_is_copied():
    f = frame_of((-1, -1, -1), (1, 1, 1), Y_UP)
    m = map_camera(cam((0, 0, 5), angle=45.0, par=True), f, f)
    assert m["angle"] == 45.0 and m["par"] is True


# ----- stepping -----------------------------------------------------------------------------
P = ["a", "b", "c", "d"]


def test_neighbour_skips_the_other_pane():
    assert neighbour(P, "a", 1, avoid="b") == "c"
    assert neighbour(P, "c", -1, avoid="b") == "a"
    assert neighbour(P, "d", 1, avoid="a") == "b"       # wraps round


def test_neighbour_without_avoid_just_steps():
    assert neighbour(P, "d", 1) == "a" and neighbour(P, "a", -1) == "d"


def test_neighbour_nothing_to_show():
    assert neighbour([], "a", 1) == ""
    assert neighbour(["a"], "a", 1, avoid="a") == ""
    assert neighbour(["a"], "a", 1) == "a"


def test_neighbour_current_not_in_list():
    assert neighbour(P, "zzz", 1, avoid="a") == "b"
    assert neighbour(P, "zzz", -1, avoid="d") == "c"


def test_neighbour_when_current_is_the_avoided_one():
    assert neighbour(P, "b", 1, avoid="b") == "c"


# ----- the link, with stand-in viewers --------------------------------------------------------
class FakeCam:
    def __init__(self):
        self.pos, self.fp, self.up = (0.0, 0.0, 5.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        self.angle, self.par, self.scale = 30.0, False, 1.0
        self.obs = []

    def AddObserver(self, name, fn):
        self.obs.append(fn)
        return len(self.obs)

    def RemoveObserver(self, tag):
        self.obs[tag - 1] = None

    def _fire(self):
        for f in list(self.obs):
            if f:
                f()

    def GetPosition(self): return self.pos
    def GetFocalPoint(self): return self.fp
    def GetViewUp(self): return self.up
    def GetViewAngle(self): return self.angle
    def GetParallelProjection(self): return self.par
    def GetParallelScale(self): return self.scale
    def SetParallelProjection(self, v): self.par = bool(v); self._fire()
    def SetViewAngle(self, v): self.angle = v; self._fire()
    def SetPosition(self, *v): self.pos = tuple(v); self._fire()
    def SetFocalPoint(self, *v): self.fp = tuple(v); self._fire()
    def SetViewUp(self, *v): self.up = tuple(v); self._fire()
    def SetParallelScale(self, v): self.scale = v; self._fire()


class FakeViewer:
    def __init__(self, half, up="Y"):
        self.cam = FakeCam()
        self.half = half
        self.actors = [object()]
        self.up = up
        self.renders = 0
        self.renderer = self
        self.rw = self

    def GetActiveCamera(self): return self.cam
    def ResetCameraClippingRange(self): pass
    def Render(self): self.renders += 1
    def _model_bounds(self): return np.full(3, -self.half), np.full(3, self.half)

    def _axes_vectors(self):
        b = Y_UP if self.up == "Y" else Z_UP
        return np.array(b[1], float), np.array(b[2], float), np.array(b[0], float)   # up, front, right


def test_link_moves_the_other_view_both_ways():
    a, b = FakeViewer(1.0), FakeViewer(10.0)
    link = CameraLink(a, b)
    a.cam.SetPosition(0.0, 0.0, 8.0)
    assert np.allclose(b.cam.pos, (0, 0, 80))
    b.cam.SetPosition(0.0, 0.0, 20.0)
    assert np.allclose(a.cam.pos, (0, 0, 2))
    assert a.renders and b.renders
    link.detach()
    a.cam.SetPosition(0.0, 0.0, 3.0)
    assert np.allclose(b.cam.pos, (0, 0, 20))


def test_link_does_not_loop_or_move_when_paused():
    a, b = FakeViewer(1.0), FakeViewer(1.0)
    link = CameraLink(a, b)
    link.paused = True
    a.cam.SetPosition(0.0, 0.0, 9.0)
    assert b.cam.pos == (0.0, 0.0, 5.0)
    link.paused = False
    link.sync()
    assert np.allclose(b.cam.pos, (0, 0, 9))


def test_link_waits_for_both_models():
    a, b = FakeViewer(1.0), FakeViewer(1.0)
    b.actors = []
    CameraLink(a, b)
    a.cam.SetPosition(0.0, 0.0, 9.0)
    assert b.cam.pos == (0.0, 0.0, 5.0)
