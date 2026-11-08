# Gleek3Deek

A fast, minimalist, native 3D asset browser and viewer. Browse a folder of models as a thumbnail gallery, double-click to open any of them in an interactive 3D viewer. No Electron, no web view, just Python, Qt and VTK.

> **Status:** early release. Expect rough edges, and please report them in the Issues tab.

<img width="1110" height="729" alt="Gleek3Deek 6-11-08 103343" src="https://github.com/user-attachments/assets/8e5daa5e-3e4f-4ac9-b83f-b4691f90d6a9" />

## Features

- **Folder tree + visual gallery:** nested folder navigation on the left, a grid of cards on the right. Only 3D formats are shown. The last opened folder is remembered.
- **Real thumbnails:** rendered in the background and cached on disk, so revisiting a folder is instant.
- **MatCap editor:** tweak a material's colours, light and gloss live, save/load presets as small JSON files, or load a sphere image.
- **Gallery tools:** search, sort, and a card-size slider.
- **Viewer tools:** auto-orbit, backgrounds, axes gizmo, standard views, orthographic mode, Z-up fix, screenshots, and previous/next browsing with the arrow keys.
- **Instant viewer:** double-click a card (or a file in the tree). Auto-fits the camera to the model.
- **MatCap shading:** press `M` to cycle five ZBrush-style MatCap materials (Red Wax, Clay Matte Green, RealSkin, Framer, RoughMetal). They are original procedural shaders, not copies of ZBrush's images.
- **Textures and colours:** glTF/GLB, OBJ+MTL and FBX/DAE/LWO materials, vertex colours and face colours.
- **Never freezes:** all file parsing runs on background threads.
- **Friendly errors:** a file that fails to load shows an error box inside the viewer instead of crashing the app.

<img width="1066" height="697" alt="Gleek3Deek-11-07 213237" src="https://github.com/user-attachments/assets/e3873d03-5916-40b6-bf6b-6ed93987bdaf" />

## Download (Windows, no Python needed)

Go to the **[Releases](../../releases)** page, download `Gleek3Deek.exe` and double-click it. Nothing to install.

- The first launch takes a few seconds longer, because the single-file exe unpacks itself to a temporary folder each time it starts.
- The exe is not code-signed, so Windows SmartScreen may say "Windows protected your PC". Choose **More info → Run anyway**. Some antivirus tools also flag PyInstaller programs by mistake; you can always run from source instead (below).

## Quick start (from source)

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

**Gallery**

| Action | Input |
|---|---|
| Open an asset | Double-click a card or a file in the tree |
| Search | Type in the search box (matches name and extension) |
| Sort | Drop-down: name, date, size or type |
| Card size | Slider at the right of the toolbar (remembered) |

**Viewer**

| Action | Input |
|---|---|
| Orbit / Zoom / Pan | Left / Right / Middle mouse drag (scroll also zooms) |
| Previous / next model in the folder | `←` / `→` (or the ‹ › buttons) |
| Auto-orbit turntable | `O` (pauses while you drag; speed is in the **View** menu) |
| Cycle background | `B` (more options, including a custom colour, in the **View** menu) |
| Axes gizmo on/off | `A` |
| Perspective / orthographic | `C` |
| Standard views | `1` Front, `2` Back, `3` Right, `4` Left, `5` Top, `6` Bottom, `7` Isometric |
| Z-up model fix | `U` (remembered per file; also fixes its thumbnail) |
| Transparency on/off | `T` (models load solid; this restores a material's own transparency, for models that have any) |
| Save screenshot | `F12` (2x resolution PNG, without the gizmo) |
| Copy screenshot | `Ctrl+C` |
| Wireframe / points / shaded | `W` / `P` / `S` (`W` and `P` again return to shaded) |
| Cycle MatCaps | `M` (Red Wax, Clay Matte Green, RealSkin, Framer, RoughMetal, then normal shading) |
| MatCap editor | `E` (or **View ▾ → MatCap editor…**) |
| Reset camera | `R` |
| Close viewer | `Esc` or the ✕ button |

## MatCap editor and presets

<img width="398" height="540" alt="matcap" src="https://github.com/user-attachments/assets/3d4b81e6-af45-4aa5-91c8-e7cd3534096f" />

Press **E** (or **View ▾ → MatCap editor…**) with a model open. The editor floats beside the viewer and changes the model live. Your work appears as one extra entry at the end of the **M** cycle, and it is remembered between sessions.

- **Start from:** Red Wax, Clay Matte Green or RealSkin as a starting point.
- **Colours:** shadow, body, light, rim and gloss.
- **Sliders:** light direction and height, how far shadows and highlights spread, rim glow and tightness, gloss and sheen amount and tightness.
- **Save preset… / Load preset…:** presets are small JSON files you can share. A procedural preset looks like this:

```json
{
  "gleek3deek_matcap": 1,
  "name": "Custom",
  "type": "procedural",
  "params": {
    "shadow": [
      1.0,
      1.0,
      0.0
    ],
    "body": [
      0.26274511218070984,
      0.21568627655506134,
      0.7803921699523926
    ],
    "light": [
      0.9803921580314636,
      0.2823529541492462,
      0.7686274647712708
    ],
    "rim_color": [
      0.55,
      0.1,
      0.06
    ],
    "spec_color": [
      1.0,
      0.78,
      0.72
    ],
    "light_az": 45.0,
    "light_el": -7.0,
    "shadow_start": 0.06,
    "light_start": 0.56,
    "rim_strength": 0.91,
    "rim_power": 4.1000000000000005,
    "spec_tight": 1.02,
    "spec_tight_pow": 93.0,
    "spec_broad": 0.48,
    "spec_broad_pow": 6.0
  }
}
```

Any value you leave out falls back to the Red Wax default, and out-of-range values are clamped.

- **Load image MatCap…:** pick a picture of a lit sphere (PNG, JPG, TIFF, BMP). The image is cropped to a square, shrunk to a 32×32 colour table and fitted with a smooth formula that is used as the material. A saved image preset stores that table inside the JSON, so it doesn't depend on the original picture.

Notes:
- Image MatCaps are deliberately low resolution, so smooth materials look right but very sharp highlights get softened.
- The image is turned into a compact smooth formula inside the shader (no lookup table or texture), which keeps rendering fast. If a graphics driver rejects the full-detail version, the viewer automatically retries with a simpler one.
- ZBrush's own `.ZMT` material files can't be read
- If your graphics driver rejects a MatCap shader, the viewer returns to normal shading and says so in the status bar. Details go to `gleek3deek_vtk.log` in your temp folder.

## Supported formats

| Format | Extensions | How it's read | Notes |
|---|---|---|---|
| glTF / GLB | `.gltf` `.glb` | VTK glTF importer | Base colour textures; PBR is shown as simple shading. WebP textures in GLB files are converted automatically. Draco/Meshopt/KTX2-compressed models are not supported |
| OBJ | `.obj` | VTK OBJ reader / importer | Uses the `.mtl` file if present; reads `v x y z r g b` vertex colours |
| STL | `.stl` | VTK | No colour data in the format, so it's shown grey |
| PLY | `.ply` | VTK | Vertex and face colours |
| Assimp formats | `.fbx` `.dae` `.usd` `.usda` `.usdc` `.usdz` `.3mf` `.amf` `.x3d` `.dxf` `.ifc` `.3ds` `.ase` `.lwo` `.lws` `.lxo` `.ac` `.b3d` `.cob` `.scn` `.ms3d` `.ndo` `.nff` `.off` `.sib` `.x` `.xgl` `.m3d` `.q3o` `.irr` `.irrmesh` `.ogex` `.pmx` `.mesh.xml` `.md2` `.md3` `.md5mesh` `.mdc` `.mdl` `.bsp` `.smd` `.vta` `.hmp` `.ter` | Assimp (`assimp-py`) | Requires `pip install assimp-py`. Which of these open depends on the Assimp build inside your `assimp-py` wheel (for example, USD needs a recent one). Files that fail show an error and keep a generic icon |
| Motion capture | `.bvh` `.csm` | not displayable | Skeleton data only, no mesh |
| STEP | `.step` `.stp` | VTK OpenCASCADE, else CadQuery | Requires `pip install cadquery` on most setups |
| Blender | `.blend` | Blender command line | Needs Blender installed (set `BLENDER_PATH` if it isn't on your PATH). Without it, Assimp's legacy reader is tried, which only handles older files |
| Cinema 4D, Maya, 3ds Max | `.c4d` `.mb` `.ma` `.max` | not readable | Closed formats. Export to glTF, FBX or OBJ from the original app |

Any file whose thumbnail can't be generated keeps the generic cube icon. Thumbnails are skipped outright for `.blend`, motion-capture and the closed formats, and for files over 200 MB (change with the `GLEEK_THUMB_MAX_MB` environment variable).

## Building the Windows .exe

**On your own PC:** double-click `build_exe.bat` (or run `build_exe.bat onedir` for a folder build that starts faster). The result is `dist\Gleek3Deek.exe`. It needs Python 3.10–3.12 and an internet connection for the first build.

**Automatically on GitHub:** the workflow in `.github/workflows/build-windows.yml` builds the exe on a Windows runner. Publish a release by pushing a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub then attaches `Gleek3Deek.exe` to a Release. You can also run it by hand from the repository's **Actions** tab.

The `.exe` is large (VTK and Qt are bundled). STEP support through CadQuery is not included in it; use the source install for that.

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
├── build_exe.bat             # builds the Windows .exe
├── gleek3deek.spec           # PyInstaller recipe
├── requirements-build.txt    # build-only packages
├── .github/workflows/build-windows.yml   # automatic exe builds
├── LICENSE
└── README.md
```

## Contributing

Issues and pull requests are welcome. When reporting a model that won't open, please include the file format, the exact text of the error box, and (if you can share it) a small sample file.

## License

Gleek3Deek is released under the MIT License (see `LICENSE`). It depends on [PySide6](https://doc.qt.io/qtforpython/) (LGPL), [VTK](https://vtk.org/) (BSD), [NumPy](https://numpy.org/) (BSD) and, optionally, [assimp-py](https://pypi.org/project/assimp-py/) / [Assimp](https://github.com/assimp/assimp) (BSD) and [CadQuery](https://github.com/CadQuery/cadquery) (Apache-2.0), each under its own license.
