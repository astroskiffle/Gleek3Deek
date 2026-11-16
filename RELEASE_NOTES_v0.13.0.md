# Gleek3Deek v0.13.0 – Draco and Meshopt compressed GLB files, and CSV and HTML audit reports

GLB models that use Draco or Meshopt compression now open, in the window, the thumbnail grid and the command line. Previously these files were rejected. The command line can also now write a CSV or a single-file HTML report for a batch run.

## What's new

### Compressed GLB support
- **Draco** (`KHR_draco_mesh_compression`) and **Meshopt** (`EXT_meshopt_compression`) geometry is decoded into ordinary glTF data when a model is opened. The original file is never changed.
- Both decoders are optional, like Assimp. Install them once, inside the project's `.venv`:

```
pip install DracoPy meshoptimizer
```
- If a decoder is missing, the error box says which package to install and which Python the app is using, so a wrong environment is easy to spot.
- Works together with the existing WebP and `KHR_mesh_quantization` fixes, so files from tools such as glTF-Transform and gltfpack open.
- Meshopt's octahedral (normals) and exponential (floats) filters are handled. Models with a quaternion filter still open; their animation data is skipped, because the viewer does not play animations.

### CSV and HTML reports (command line)
```
python cli.py ./assets -r --all --report audit.csv      # one row per file, for a spreadsheet
python cli.py ./assets -r --all --report audit.html     # one self-contained web page
python cli.py ./assets -r --mesh --format csv > audit.csv
```
- **`--format text|json|csv|html`** chooses the output format (`--json` still works). `html` is for `--report` files only; the console shows text. A `--report` file without an explicit format follows its extension (`.csv`, `.html`, `.json`, `.txt`).
- **CSV:** one row per file, one column per figure (counts, texture memory, each mesh and UV test, size, volume, centre of mass, check results). Columns depend only on the sections you asked for, failed loads get a row too, and the file opens correctly in Excel. Text that a spreadsheet could run as a formula is defused.
- **HTML:** a single page with summary cards, a sortable and filterable table, and a collapsible detail block per file. Nothing is loaded from outside, light and dark themes are supported, and file names and error messages are escaped.
- The report safety rules are unchanged: a report never overwrites a file (unless `--force`), is never written inside the scanned folder, and never follows a symbolic link.

### Flipped faces are marked whole
- The **Inconsistent winding** test used to colour only the border of a flipped patch. It now colours the flipped triangles themselves: where two sides of a seam disagree, the smaller side is marked. A single flipped triangle marks one triangle (it used to mark it and its neighbours).
- A surface that cannot be oriented at all (a Möbius strip) keeps the old border marking.
- Costs about 0.8 s extra on a million-triangle mesh, and only when a mesh has inconsistent seams.
- Fix: the command line could not open GLB files (it crashed in the glTF loader). It can now.
- UV island tests (overlapping, stacked and mirrored islands) now run on parts up to 4 million triangles (was 2 million). The skipped message states the limit.

### Analyses run in the background
- **Run UV tests** and **Run integrity tests** no longer freeze the window. They run on a worker thread, you can keep orbiting and looking around, and the button turns into **Cancel** while they work. Progress shows in the tab ("Analysing UVs: part 3 of 19 …").
- Cancel takes effect between parts and between the stages of a part, so on a very large part it can take a few seconds to stop. Opening another model, or switching the LOD level, cancels a running analysis and ignores its result.
- The results are identical to before; the command line is unchanged.

### Fake AO (Environment panel)
- A new **Fake AO** option with a **strength** slider darkens the ambient light in creases and corners, and slightly toward the ground. It is a per-vertex value, so there is no extra render pass and the cost per frame is negligible.
- The crease values are computed once per model on a background thread (about 1 s per million triangles); the height gradient follows Y-up/Z-up and moves. It is paused while split compare (D) or the wireframe overlay (Shift+W) is on, and does not change the sun, only works in shaded mode with environment lighting, and sees local creases only.
- If the GPU rejects the shader, Fake AO switches itself off with a message. Light presets keep your Fake AO settings.

### Panorama light (Environment panel)
- A new **Panorama light** slider blends the ambient light from the three colours toward the diffuse light of the whole panorama (nine spherical-harmonic coefficients computed once when it loads). Surfaces are lit by the part of the sky they face, in the colours of the image, with no extra render pass.
- Follows *Rotate environment* and Y-up/Z-up. Default 0 (off), so existing looks are unchanged. Needs a loaded panorama; works together with Fake AO.
- Not real global illumination: no reflections, no shadows from the panorama, no bounces.

### Tags, colour labels, ratings and smart folders
- Right-click a thumbnail (or use `Ctrl+1`–`5`, `Ctrl+0`, `Ctrl+T`) to set a **star rating**, a **colour label** and **tags**. Select several files to change them together. Yellow stars (filled only) and a coloured border shows on the cards; they are painted by the gallery, so they do not depend on the thumbnail.
- The search box now understands `tag:`, `-tag:`, `color:`, `rating:` (with `>=`, `<=` and so on) as well as plain words.
- **Library ▾** in the gallery bar saves searches as **smart folders** that list matching files from all folders, and offers quick browsing by tag, colour or rating.
- All of it is stored in one plain-text file, `gleek3deek-library.json`, next to the program (falling back to the application-data folder). Model files are never modified. Safe saving with a `.bak` copy, damaged files set aside, and renamed files re-found by fingerprint. **Library ▾ → Library file…** shows or changes the location.
- `build_exe.bat` keeps the library next to the exe across rebuilds. Add `gleek3deek-library.json*` to `.gitignore`.
- The gallery now allows selecting several files; rename, copy and delete still act on the current file.

### Small changes
- The built-in MatCap "Framer" is now called "Glossy".
- The About dialog's Legal section now reads "Provided as is, without warranty." instead of a placeholder.
- `requirements-optional.txt`, the README and the PyInstaller spec list the two new optional packages.
- New tests for the compressed-GLB conversion and for the reports (79 tests in total).

## Good to know
- Only `.glb` files are converted. A compressed `.gltf` with separate buffer files is not.
- KTX2-compressed textures are still not supported.
- To use the decoders in the packaged `.exe`, install both packages into the build environment before running `build_exe.bat`. The spec file already includes them.
- If you bundle them, check the licences of `DracoPy` and `meshoptimizer` and add them to the About dialog's third-party list.
- Tested on a Draco GLB and a Meshopt GLB without textures. Models that use Meshopt filters on normals or tangents have not yet been tried on real files.

## Upgrading
Replace `formats.py`, `cli.py`, `main.py`, `panels.py`, `analysis.py`, `environment.py`, `matcap.py`, `gallery.py`, `library.py` (new), `README.md`, `requirements-optional.txt`, `build_exe.bat` and `gleek3deek.spec`, and add `tests/test_gltf_compression.py`, `tests/test_reports.py` `tests/test_fake_ao.py` and `tests/test_library.py`. Then run `pip install DracoPy meshoptimizer` in your `.venv` if you want compressed GLB support.
