# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for Gleek3Deek.
#   Single .exe (default):   pyinstaller --noconfirm --clean gleek3deek.spec
#   Folder build (faster start-up):  set GLEEK_ONEDIR=1 first
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

onedir = os.environ.get("GLEEK_ONEDIR") == "1"

datas, binaries, hiddenimports = [], [], []
hiddenimports += collect_submodules("vtkmodules")        # VTK loads its modules lazily
hiddenimports += ["cli", "formats", "analysis", "matcap", "gallery", "environment", "panels"]          # cli is only imported when a command-line option is used
for pkg in ("assimp_py",):                               # optional; skipped if not installed
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Keep the bundle smaller: nothing here uses these.
excludes = [
    "tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest", "cadquery",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
    "PySide6.QtNetworkAuth", "PySide6.QtSensors", "PySide6.QtSerialPort",
]

icon = "assets/gleek3deek.ico" if os.path.exists("assets/gleek3deek.ico") else None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

if onedir:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Gleek3Deek",
              console=False, upx=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name="Gleek3Deek", upx=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="Gleek3Deek",
              console=False, upx=False, icon=icon)
