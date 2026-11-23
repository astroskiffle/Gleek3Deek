"""Import every module of the program. A missing import or a misspelled name at module level (the kind of mistake
that otherwise only shows when the app is started) fails here. Runs with the stand-ins for Qt and VTK on CI."""
import importlib

import pytest


@pytest.mark.parametrize("name", ["formats", "analysis", "environment", "matcap", "panels", "library", "fileops",
                                  "gallery", "viewer", "main", "cli"])
def test_module_imports(name):
    importlib.import_module(name)


def test_viewer_does_not_depend_on_main():
    import ast
    import os
    root = os.path.join(os.path.dirname(__file__), "..")
    tree = ast.parse(open(os.path.join(root, "viewer.py"), encoding="utf-8").read())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "main" not in mods
