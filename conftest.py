"""Test setup. The logic under test needs only numpy, so VTK and Qt are replaced by stand-ins when they are not
installed (as on a CI runner). With the real packages installed, the tests use them."""
import importlib.abc
import importlib.machinery
import os
import sys
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _missing(name: str) -> bool:
    try:
        __import__(name)
        return False
    except Exception:
        return True


class _Stub(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, roots):
        self.roots = set(roots)

    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in self.roots:
            return importlib.machinery.ModuleSpec(name, self, is_package=True)

    def create_module(self, spec):
        m = MagicMock()
        m.__name__, m.__path__, m.__spec__, m.__loader__ = spec.name, [], spec, self
        return m

    def exec_module(self, module):
        pass


_stubbed = [r for r in ("vtkmodules", "PySide6") if _missing(r)]
if _stubbed:
    sys.meta_path.insert(0, _Stub(_stubbed))
