"""Side-by-side compare: the maths that keeps two cameras looking at their models the same way, and the
small helpers the main window uses. No Qt or VTK is imported here, so it can be tested on its own.

Two models are rarely the same size or the same way up, so the cameras are not simply copied. A camera is
described relative to its own model: the viewing direction in the model's own right/up/front directions,
the distance and the focus offset as fractions of the model's size. Orbiting, zooming or panning one view
then moves the other by the same relative amount."""
from __future__ import annotations

import numpy as np


def frame_of(lo, hi, basis) -> dict:
    """A model's frame: its centre, its radius and its (right, up, front) directions."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    radius = float(np.linalg.norm(hi - lo)) / 2.0
    return {"centre": (lo + hi) / 2.0, "radius": radius if radius > 1e-12 else 1.0,
            "basis": np.array(basis, float).reshape(3, 3)}       # rows: right, up, front


def _to_local(v, basis):
    return basis @ np.asarray(v, float)


def _from_local(local, basis):
    return basis.T @ np.asarray(local, float)


def map_camera(cam: dict, src: dict, dst: dict) -> dict:
    """The camera `cam` (pos, fp, up, angle, par, scale) of a view of model `src`, as the matching camera of a view
    of model `dst`."""
    rs, rd = src["radius"], dst["radius"]
    fp_rel = _to_local((np.asarray(cam["fp"], float) - src["centre"]) / rs, src["basis"])
    off_rel = _to_local((np.asarray(cam["pos"], float) - np.asarray(cam["fp"], float)) / rs, src["basis"])
    up_loc = _to_local(cam["up"], src["basis"])
    fp = dst["centre"] + _from_local(fp_rel, dst["basis"]) * rd
    pos = fp + _from_local(off_rel, dst["basis"]) * rd
    return {"pos": tuple(pos), "fp": tuple(fp), "up": tuple(_from_local(up_loc, dst["basis"])),
            "angle": cam["angle"], "par": bool(cam["par"]), "scale": float(cam["scale"]) / rs * rd}


def neighbour(paths: list, current: str, delta: int, avoid: str = "") -> str:
    """The model `delta` steps away from `current` in `paths` (wrapping round), skipping `avoid` (the model shown
    in the other pane). '' if there is nothing else to show."""
    if not paths:
        return ""
    others = [p for p in paths if p != avoid] or []
    if not others:
        return ""
    if current in others:
        return others[(others.index(current) + delta) % len(others)]
    if current in paths:                                    # current is the avoided one: go by its place in the list
        i = paths.index(current)
        for k in range(1, len(paths) + 1):
            p = paths[(i + delta * k) % len(paths)]
            if p != avoid:
                return p
        return ""
    return others[0] if delta > 0 else others[-1]


class CameraLink:
    """Keeps the cameras of two viewers in step (either one can be moved). The viewers are used through
    .renderer, .rw, .actors, ._model_bounds() and ._axes_vectors() only."""

    def __init__(self, a, b):
        self.a, self.b = a, b
        self.paused = False
        self._busy = False
        self._tags = []
        for src, dst in ((a, b), (b, a)):
            cam = src.renderer.GetActiveCamera()
            tag = cam.AddObserver("ModifiedEvent", lambda *_a, s=src, d=dst: self._changed(s, d))
            self._tags.append((cam, tag))

    @staticmethod
    def _frame(v) -> dict | None:
        if not v.actors:
            return None
        lo, hi = v._model_bounds()
        u, f, r = v._axes_vectors()
        return frame_of(lo, hi, (r, u, f))

    @staticmethod
    def _read(v) -> dict:
        cam = v.renderer.GetActiveCamera()
        return {"pos": cam.GetPosition(), "fp": cam.GetFocalPoint(), "up": cam.GetViewUp(),
                "angle": cam.GetViewAngle(), "par": cam.GetParallelProjection(), "scale": cam.GetParallelScale()}

    def _changed(self, src, dst):
        if self.paused or self._busy:
            return
        self.sync(src, dst)

    def sync(self, src=None, dst=None):
        """Make `dst` look at its model the way `src` looks at its own (default: b follows a)."""
        src, dst = src or self.a, dst or self.b
        fs, fd = self._frame(src), self._frame(dst)
        if fs is None or fd is None or self._busy:
            return
        self._busy = True
        try:
            m = map_camera(self._read(src), fs, fd)
            cam = dst.renderer.GetActiveCamera()
            cam.SetParallelProjection(m["par"])
            cam.SetViewAngle(m["angle"])
            cam.SetPosition(*m["pos"])
            cam.SetFocalPoint(*m["fp"])
            cam.SetViewUp(*m["up"])
            cam.SetParallelScale(m["scale"])
            dst.renderer.ResetCameraClippingRange()
            dst.rw.Render()
        finally:
            self._busy = False

    def detach(self):
        for cam, tag in self._tags:
            try:
                cam.RemoveObserver(tag)
            except Exception:
                pass
        self._tags = []
