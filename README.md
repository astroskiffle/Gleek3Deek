# Gleek3Deek

<img width="982" height="624" alt="gleek3deek-05 235235" src="https://github.com/user-attachments/assets/4476916a-3f80-4fda-a77a-eea7e2065feb" />


A fast, minimalist, native 3D asset browser and viewer. Browse a folder of models as a thumbnail gallery, double-click to open any of them in an interactive 3D viewer. No Electron, no web view, just Python, Qt and VTK.

> **Status:** early release. Expect rough edges, and please report them in the Issues tab.

<!-- Add a screenshot: put an image in a /docs folder and uncomment the line below
![Gleek3Deek screenshot](docs/screenshot.png)
-->

## Features

- **Folder tree + visual gallery:** nested folder navigation on the left, a grid of cards on the right. Only 3D formats are shown. The last opened folder is remembered.
- **Real thumbnails:** rendered in the background and cached on disk, so revisiting a folder is instant.
- **Instant viewer:** double-click a card (or a file in the tree). Auto-fits the camera to the model.
- **Textures and colours:** glTF/GLB, OBJ+MTL and FBX/DAE/LWO materials, vertex colours and face colours.
- **Never freezes:** all file parsing runs on background threads.
- **Friendly errors:** a file that fails to load shows an error box inside the viewer instead of crashing the app.

<img width="977" height="621" alt="gleek3deek 235119" src="https://github.com/user-attachments/assets/d4984017-dc40-4a37-a7e2-3d76e2bca680" />

## Quick start

You need **Python 3.10 – 3.12** (3.9 and 3.13 may work depending on the VTK wheel available for your platform).

**Windows:** double-click `run.bat`

**macOS / Linux:**
```bash
./run.sh
```

On first launch the script creates a private `.venv` folder, installs the dependencies, then starts the app. Later launches start immediately.

You can also pass a folder or a model file:
```bash
./run.sh path/to/models
run.bat C:\Models\chair.glb
```

### Manual install

```bash
pip install -r requirements.txt
pip install assimp-py      # optional: FBX / DAE / LWO / 3DS
python main.py
```

## Controls

| Action | Input |
|---|---|
| Open an asset | Double-click a card or a file in the tree |
| Orbit | Left mouse drag |
| Zoom | Right mouse drag (or scroll) |
| Pan | Middle mouse drag |
| Wireframe | `W` (press again to return to shaded) |
| Point cloud | `P` (press again to return to shaded) |
| Shaded surface | `S` |
| Red Wax MatCap | `M` (press again to return to shaded) |
| Reset camera | `R` |
| Close viewer | `Esc` or the ✕ button |

## Supported formats

| Format | Extensions | How it's read | Notes |
|---|---|---|---|
| glTF / GLB | `.gltf` `.glb` | VTK glTF importer | Base colour textures; PBR is shown as simple shading |
| OBJ | `.obj` | VTK OBJ reader / importer | Uses the `.mtl` file if present; reads `v x y z r g b` vertex colours |
| STL | `.stl` | VTK | No colour data in the format, so it's shown grey |
| PLY | `.ply` | VTK | Vertex and face colours |
| FBX, Collada, LightWave, 3DS | `.fbx` `.dae` `.lwo` `.3ds` | Assimp (`assimp-py`) | Requires `pip install assimp-py` |
| STEP | `.step` `.stp` | VTK OpenCASCADE, else CadQuery | Requires `pip install cadquery` on most setups |
| Blender | `.blend` | Blender command line | Needs Blender installed (set `BLENDER_PATH` if it isn't on your PATH) |
| Cinema 4D, Maya, 3ds Max | `.c4d` `.mb` `.ma` `.max` | not readable | Closed formats. Export to glTF, FBX or OBJ from the original app |

Thumbnails are skipped for `.blend` and the closed formats, and for files over 200 MB (change with the `GLEEK_THUMB_MAX_MB` environment variable).

## Troubleshooting

- **App won't start / install fails:** check `python --version`. Use Python 3.10–3.12 if a package can't be found for your version.
- **FBX / DAE / LWO won't open:** make sure `assimp-py` installed (`pip install assimp-py` inside `.venv`). The error box shows the exact reason.
- **STEP files won't open:** run `pip install cadquery`.
- **Black or blank 3D view:** update your graphics driver. VTK needs OpenGL 3.2 or newer.
- **Thumbnails missing:** the generic icon stays if a file is too large, in an unsupported format, or can't be parsed. Thumbnail cache lives in your OS user cache folder under `Gleek3Deek/thumbs` and is safe to delete.

## Project layout

```
Gleek3Deek/
├── main.py                   # the whole application
├── requirements.txt          # required packages
├── requirements-optional.txt # optional format support
├── run.bat                   # Windows launcher
├── run.sh                    # macOS / Linux launcher
├── LICENSE
└── README.md
```

## Contributing

Issues and pull requests are welcome. When reporting a model that won't open, please include the file format, the exact text of the error box, and (if you can share it) a small sample file.

## License

Gleek3Deek is released under the MIT License (see `LICENSE`). It depends on [PySide6](https://doc.qt.io/qtforpython/) (LGPL), [VTK](https://vtk.org/) (BSD), [NumPy](https://numpy.org/) (BSD) and, optionally, [assimp-py](https://pypi.org/project/assimp-py/) / [Assimp](https://github.com/assimp/assimp) (BSD) and [CadQuery](https://github.com/CadQuery/cadquery) (Apache-2.0), each under its own license.
