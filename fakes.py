"""Tiny stand-ins for VTK actors and poly data, so the whole-model audit can run without VTK."""
import types

import numpy as np


class Arr:
    def __init__(self, arr, name=None, nc=1):
        self.arr, self.name, self.nc = arr, name, nc

    def GetNumberOfComponents(self):
        return self.nc

    def GetName(self):
        return self.name

    def GetDataType(self):
        return 0


class Cells:
    def __init__(self, off, conn):
        self.o, self.c = off, conn

    def GetOffsetsArray(self):
        return Arr(self.o)

    def GetConnectivityArray(self):
        return Arr(self.c)

    def GetNumberOfCells(self):
        return max(len(self.o) - 1, 0)


class PointData:
    def __init__(self, tc=None):
        self.tc = tc

    def GetTCoords(self):
        return Arr(self.tc, nc=2) if self.tc is not None else None

    def GetScalars(self):
        return None

    def GetNumberOfArrays(self):
        return 0

    def GetArray(self, i):
        return None


class PolyData:
    def __init__(self, points, tris, uv=None):
        self.P, self.T, self.uv = points, tris, uv

    def GetNumberOfPolys(self):
        return len(self.T)

    def GetNumberOfStrips(self):
        return 0

    def GetNumberOfVerts(self):
        return 0

    def GetNumberOfLines(self):
        return 0

    def GetNumberOfPoints(self):
        return len(self.P)

    def GetNumberOfCells(self):
        return len(self.T)

    def GetPolys(self):
        return Cells(np.arange(len(self.T) + 1) * 3, self.T.ravel())

    def GetStrips(self):
        return Cells(np.zeros(0, int), np.zeros(0, int))

    def GetPoints(self):
        return types.SimpleNamespace(GetData=lambda: Arr(self.P))

    def GetPointData(self):
        return PointData(self.uv)

    def GetCellData(self):
        return PointData()


class Mapper:
    def __init__(self, pd):
        self.pd = pd

    def GetInput(self):
        return self.pd


class Image:
    def GetDimensions(self):
        return (100, 64, 1)

    def GetPointData(self):
        return types.SimpleNamespace(GetScalars=lambda: Arr(np.zeros((100 * 64, 4), np.uint8), nc=4))


class Texture:
    def GetInput(self):
        return Image()


class Matrix:
    def GetElement(self, i, j):
        return 1.0 if i == j else 0.0


class Prop:
    def GetColor(self):
        return (1, 1, 1)

    def GetOpacity(self):
        return 1.0

    def GetTexture(self, name):
        return None


class Actor:
    def __init__(self, pd, tex=None):
        self.pd, self.tex = pd, tex

    def GetMapper(self):
        return Mapper(self.pd)

    def GetBounds(self):
        return (0, 1, 0, 2, 0, 3)

    def GetVisibility(self):
        return True

    def GetTexture(self):
        return self.tex

    def GetProperty(self):
        return Prop()

    def ComputeMatrix(self):
        pass

    def GetMatrix(self):
        return Matrix()


def box(sx=1.0, sy=1.0, sz=1.0):
    """A closed, outward-wound box: (points, triangles, uv)."""
    P = np.array([[x * sx, y * sy, z * sz] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    T = []
    for a, b, c, d in quads:
        T += [(a, b, c), (a, c, d)]
    T = np.array(T)
    if np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])).sum() < 0:
        T = T[:, ::-1].copy()
    return P, T, np.c_[P[:, 0] / max(sx, 1e-9), P[:, 1] / max(sy, 1e-9)]


def actors(kind="good"):
    P, T, uv = box(1, 2, 3)
    if kind == "hole":
        T = T[1:]
    return [Actor(PolyData(P, T, uv), Texture())]
