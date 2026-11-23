# Gleek3Deek user guide

The full details behind the [README](README.md): controls, every panel and tool, the command-line mode, supported formats and troubleshooting. If you are new, start with the README, then come back here when you want to know how something works.

## Contents

- **Getting started**
  - [Quick start (from source)](#quick-start-from-source)
- **Controls**
  - [Controls](#controls)
- **Your library**
  - [Managing files from the gallery](#managing-files-from-the-gallery)
  - [Favourite and recent folders](#favourite-and-recent-folders)
  - [Tags, colour labels, ratings and smart folders](#tags-colour-labels-ratings-and-smart-folders)
- **Viewing**
  - [Side panels (a collapsible drawer on the right)](#side-panels-a-collapsible-drawer-on-the-right)
  - [Material views, textures and parts](#material-views-textures-and-parts)
  - [Scene settings (ground, camera, display, screenshots)](#scene-settings-ground-camera-display-screenshots)
  - [Environment (sky, lighting, shadow)](#environment-sky-lighting-shadow)
  - [MatCap editor and presets](#matcap-editor-and-presets)
  - [Split compare (MatCap vs normal shading)](#split-compare-matcap-vs-normal-shading)
  - [Model info panel](#model-info-panel)
- **Inspecting**
  - [UV inspection](#uv-inspection)
  - [Texture audit and mesh diagnostics](#texture-audit-and-mesh-diagnostics)
  - [Measurements and cross-section](#measurements-and-cross-section)
  - [LOD preview (simplification)](#lod-preview-simplification)
- **Output and automation**
  - [Export / convert and mesh simplification](#export--convert-and-mesh-simplification)
  - [Reference sheets for AI 3D tools](#reference-sheets-for-ai-3d-tools)
  - [Command-line mode](#command-line-mode)
- **Reference**
  - [Supported formats](#supported-formats)
  - [Building the Windows .exe](#building-the-windows-exe)
  - [Troubleshooting](#troubleshooting)
  - [Project layout](#project-layout)
  - [Running the tests](#running-the-tests)
  - [About dialog](#about-dialog)

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
pip install DracoPy meshoptimizer   # optional: Draco / Meshopt compressed GLB
python main.py
```

## Controls

**Gallery**

| Action | Input |
|---|---|
| Open an asset | Double-click a card or a file in the tree |
| Go to a folder | Type or paste a path in the address bar at the left of the toolbar and press Enter (`Alt+D` jumps there). A file path opens that file. The bar turns red if the path does not exist. The **↑** button goes to the parent folder (`Alt+Up`) |
| Search | Type in the search box (matches name and extension) |
| Sort | Drop-down: name, date, size or type |
| Card size | Slider at the right of the toolbar (remembered) |
| Rate, colour-label or tag the selected files | `Ctrl+1`…`5` (`Ctrl+0` clears), right-click → **Colour label**, `Ctrl+T` (see *Tags, colour labels, ratings and smart folders*) |
| Favourite and recent folders | **Go** menu, or right-click a folder in the tree |
| Select several files | `Ctrl` / `Shift` + click |

**Viewer**

| Action | Input |
|---|---|
| Orbit / Zoom / Pan | Left / Right / Middle mouse drag (scroll also zooms). Orbit is a turntable by default; press `H` for free rotation |
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
| Cycle MatCaps | `M` (Frosted Glass, Goosh, RealSkin, Glossy, then normal shading) |
| MatCap editor | `E` (or **Panels → MatCap**) |
| Environment on/off | `L` |
| Model info panel | `I` (or **Main ▾ → Model info**; remembered) |
| Scene settings panel | `Shift+G` (or **Panels → Scene**) |
| Hide/show the whole side panel | `Ctrl+B` (or the arrow on the right edge) |
| Cycle material view: shaded, albedo, normals | `V` |
| Reference sheet for AI 3D tools (Meshy, Tripo, Rodin, Luma) | `Shift+F12` (or **Main ▾ → Reference sheet…**) |
| UV layout beside the model | `Shift+U` (or **Main ▾ → UV layout beside the model**) |
| Measure between points (Measure tab) | `Shift+R` |
| Split compare (MatCap on one side, normal shading on the other) | `D` (hide/show, keeps its position) |
| Split style: vertical, horizontal, diagonal | `Shift+D` |
| Materials & parts panel | `Shift+M` (or **Panels → Materials**) |
| Ground grid on/off | `G` |
| Fit the model in view (keeps your angle) | `F` |
| Lock the horizon (turntable) / free rotation | `H` (on by default) |
| Edges over shaded | `Shift+W` |
| Save / return to a camera view (1–3) | `Ctrl+Shift+1…3` / `Alt+1…3` |
| Export / convert | `Ctrl+E` (or **File → Export / convert…**) |
| About | `F1` (or **Help → About**) |
| Open folder | `Ctrl+O` (**File → Open folder…**) |
| Environment settings | `Shift+L` (or **Panels → Environment**) |
| Cycle built-in lighting presets | `Ctrl+L` (or **Main ▾ → Lighting preset**) |
| Rotate the lighting and sky | `Shift` + right-drag in the viewer (with the environment on) |
| Reset camera | `R` |
| Close viewer | `Esc` or the ✕ button |

## Managing files from the gallery

Select one or several thumbnails (`Ctrl` / `Shift` + click, `Ctrl+A` for all, `Ctrl+I` to invert the selection) and right-click, or use the keys:

| Action | Key |
|---|---|
| Open | double-click |
| Rename (one file) | `F2` |
| Batch rename (2 or more files) | `Ctrl+F2` |
| Cut / Copy / Paste | `Ctrl+X` / `Ctrl+C` / `Ctrl+V` |
| Copy to a folder… | `Ctrl+Shift+Y` |
| Move to a folder… | `Ctrl+Shift+M` |
| Undo the last rename or move | `Ctrl+Z` |
| Delete (to the Recycle Bin / Trash) | `Del` |
| Refresh the thumbnail | `F5` |

**Models and the files they need.** An OBJ needs its `.mtl` file and the textures that names, a glTF needs its `.bin` and images, a Collada (`.dae`) file its images. Copying, cutting, pasting and moving take those along (**companion files**), keeping their folder layout, so the model still works afterwards. The *Copy to / Move to* window has a tick box to turn this off; the choice is remembered, and also applies to Paste. Other formats are transferred as a single file. FBX and other binary formats are not read for their textures.

- **Nothing is overwritten.** A model whose name is taken at the destination gets a number ("chair (2).obj"; a copy into the same folder becomes "chair - Copy.obj"). A companion that is already there and identical is reused. If a companion of the same name is there but is a *different* file, that model is left alone and listed, because renaming the file would break the model.
- **Shared files are copied, not moved.** If another model in the same folder uses the same `.mtl` or texture, Move leaves the original in place and copies it, so the other model keeps working.
- **If a move fails part-way** for one model, whatever it had already moved is put back, and the other models carry on.
- **Local drives only.** Network locations are refused.
- **Cut and paste** works with Explorer/Finder in both directions: files cut in Explorer move when pasted here, and files cut here move when pasted in Explorer. A cut can be pasted once.
- **Tags, colour labels, ratings and the Y-up/Z-up choice follow a moved model**, and so does its thumbnail. A copy starts with the same thumbnail but not the tags.
- **Copy to / Move to** shows the last 8 folders you used, plus a Browse button. Both also work from the right-click menu on the selection.
- **Undo** (`Ctrl+Z`, or **Edit → Undo**, which names what it will undo) puts back the last rename or move, up to 20 steps while the app is open. A moved model goes back with its companion files, and its tags, colours, ratings and thumbnail go back with it. Nothing is overwritten: a file that has been changed or removed since, or whose old name has been taken, is skipped and listed. Copies and deletes are not undone (deleted files are in the Recycle Bin / Trash).
- **Batch rename** (`Ctrl+F2`, or right-click with 2 or more files selected) renames the selected files with a pattern: `#` is a number (`###` gives 001, 002 …), `[name]` is the current name, extensions are kept, and the numbers follow the gallery order. A table shows every old and new name; the Rename button stays off while any name is invalid, taken, or given to two files. Swaps and shifts work, and if anything fails nothing is renamed. It can be undone with `Ctrl+Z`.
- **Rename** works on one file at a time: it asks for the new name and keeps the extension. Invalid names and names that already exist are refused. For OBJ and glTF, rename only the model, not its `.mtl`, `.bin` or textures, because the model refers to those by name.
- **Delete** moves the selected files to the Recycle Bin / Trash after asking. If that isn't possible you are asked before anything is deleted permanently. Companion files are **not** deleted, because other models may use them.
- **The open folder updates itself** within a couple of seconds when files are added, removed, renamed or changed outside the app (copied in with Explorer, say). It waits until a big copy has stopped growing, then adds the new thumbnails, and keeps your search, selection and scroll position. It looks at the folder every second or two rather than holding it open, so you can still rename or delete it in Explorer.
- **Thumbnails:** **Refresh thumbnail** (or `F5` with a file selected) throws away the saved picture and renders it again. Right-click empty space, or press `F5` with nothing selected, to refresh every thumbnail in the folder.

**Large STEP files:** thumbnails for `.step` / `.stp` files above 20 MB are skipped (the file shows the generic icon and still opens normally), because the STEP reader holds Python's global lock and would freeze the window while it loads. Set the environment variable `GLEEK_THUMB_CAD_MAX_MB` to change the limit.

## Favourite and recent folders

- **Favourites:** right-click a folder in the tree → **Add to favourites**, or **Go → Favourites → Add this folder to favourites**. A favourite gets a small yellow star on its icon in the tree, is listed in **Go → Favourites** and appears in a **★ Favourites** list above the tree (the list is hidden while you have none). Click one to jump to it. Right-click a favourite (in the list or in the tree) → **Remove from favourites**, or use **Go → Favourites → Remove a favourite**. Only the shortcut is removed; the folder itself is never touched. Up to 20, remembered in the library file (so they move with it).
- **Recent folders:** **Go → Recent folders** lists the last 10 folders you opened, newest first, remembered next time, with **Clear this list**.
- A favourite or recent folder that cannot be found (an unplugged drive, say) is greyed out and shows a message instead of failing.

## Tags, colour labels, ratings and smart folders

Organise your assets without touching them. Everything is stored in one small text file, `gleek3deek-library.json`, **next to the program** (next to `main.py` when run from source, next to the `.exe` when packaged). Nothing is ever written into a model file or its folder.

- **Rating:** right-click a thumbnail → **Rating**, or press `Ctrl+1` to `Ctrl+5` (`Ctrl+0` clears). Yellow stars (one per point, no empty stars) show over the thumbnail's corner.
- **Colour label:** right-click → **Colour label** (red, orange, yellow, green, blue, purple, gray). The card gets a coloured border.
- **Tags:** right-click → **Tags…** or `Ctrl+T`. Type tags separated by commas, or double-click an existing tag to add it.
- **Several files at once:** select with `Ctrl`/`Shift`-click, then use the same menu or keys. The tag box shows the tags every selected file shares; each file keeps its own extra tags. Rename acts on the one current file (use Batch rename for several).
- **Search:** the search box understands `tag:rock`, `-tag:old`, `tag:"hard surface"`, `#rock`, `color:red` (or `color:none`), `rating:4`, `rating:>=3` and plain words (matched against the file name and tags). Terms combine with AND.
- **Smart folders:** type a search, then **Library ▾ → Save this search as a smart folder…**. A smart folder shows every matching file from **all** folders in one list, and updates itself as tags change. **Library ▾** also has quick **Browse by tag / colour / rating**, and **Back to the folder view**.
- **Where the file lives:** next to the program when that folder is writable, otherwise in your user application-data folder. **Library ▾ → Library file…** shows the path and lets you choose another location (for example a synced folder). The file is saved safely (temporary file, then rename) and a `.bak` copy is kept. If it is damaged it is set aside as `.damaged-…`, never overwritten. Two copies of the app running at once merge their changes.
- **Renamed or moved files:** renaming in the app moves the data with the file. A file renamed outside the app is found again by a size-and-content fingerprint when you open its folder. A file moved to a different folder outside the app loses its entry (it shows as missing and is skipped in smart folders).
- Data does not travel with the model file itself: share the library file too if you want the tags elsewhere. Add `gleek3deek-library.json*` to `.gitignore`. `build_exe.bat` keeps the library across rebuilds.

## Side panels (a collapsible drawer on the right)

The four side panels (**Materials**, **MatCap**, **Environment** and **Scene**) live in one drawer on the right edge of the window, so they sit beside the viewer instead of covering it. This helps most on a laptop screen.

- **Open a panel** with its key (`Shift+M`, `E`, `Shift+L`, `Shift+G`) or by ticking it in the **Panels** menu. The menu lists the panels in the same left-to-right order as the tabs: Materials, MatCap, Environment, Scene. Untick a panel, or use the ✕ on its title bar, to put it away.
- **Collapse and expand the whole drawer:** click the slim arrow button on the right edge of the workspace, use **Panels → Show/Hide Panel**, or press `Ctrl+B`. The drawer slides out of the way and the workspace grows to fill the space; the arrow stays visible so you can bring it back. Which panels were open, and which tab was in front, are remembered.
- **In the gallery** the drawer closes by itself and the arrow button is hidden, because the panels only apply to an open model. It comes back, as you left it, when you open a model.
- **Docking is right-edge only.** Panels can't be docked to the top, left or bottom. Within the right edge you can rearrange them: drag a tab to reorder it, drag a panel's title bar onto another to group them as tabs, or to the top or bottom half of another to stack the two vertically. Drag a whole tab group by its title bar to move the group.
- **Floating panels:** drag a panel out of the drawer and release it anywhere to leave it as its own window, for instance on a second screen. Drag either the tab itself or the panel's title text out of the drawer. Drag it back onto the right edge to dock it again. Floating panels are independent windows: they can overlap each other freely, and clicking one brings it to the front. A floating panel is not part of the drawer, so **Show/Hide Panel** and `Ctrl+B` leave it where it is. All panels, floating ones included, are put away in the gallery and return when you open a model.
- **Scrolling:** every panel scrolls on its own, so nothing is clipped when a panel is short or narrow.
- **Remembered:** your arrangement, the open panels, whether the drawer is expanded, its width and the window size are saved automatically and restored the next time you start the app. **Panels → Reset panel layout** puts the four tabs back in the default order (Materials, MatCap, Environment, Scene) with the drawer open.

## Material views, textures and parts

Press **V** to cycle the view through **Shaded**, **Albedo** and **Normals**, or pick one from **Main ▾ → Material view**. `Shift+M` opens the **Materials & parts** panel, which has the same view choice plus two tabs.

**Views**
- **Albedo (no lighting):** the model's colours and textures exactly as stored, with no light, shadow or shading. This is the quickest way to judge a texture that looks dark under normal lighting.
- **Normals:** each surface is coloured by the direction it faces (relative to the camera). Surfaces that face away from the camera, which usually means flipped normals or inside-out geometry, are tinted red.
- Pressing the same view again, or `S`, returns to shaded. `M` (MatCaps), `W` and `P` still work as before.

**Parts tab**
- Every separate object in the file is listed with a colour swatch, its face count, and whether it is textured. FBX, DAE and the other formats read through Assimp show the part's own name when the file has one.
- Untick a part to hide it. Selecting a part outlines it in the view. **Show all**, **Invert** and **Isolate selected** speed things up.
- Hidden parts are ignored by the ground grid, the shadow, **Fit view**, the Model info panel (which says how many are hidden) and **Export / convert**, so you can export just the pieces you want.

**Textures tab**
- Lists the distinct textures with a thumbnail, size and how many parts use them. Base colour is always shown; occlusion/roughness/metallic, normal and emissive maps appear when the file provides them (glTF/GLB does).
- Double-click one for a large preview, with **R, G, B and A** buttons to look at a single channel. This is handy for checking a roughness map or whether a texture hides stray transparency.

## Scene settings (ground, camera, display, screenshots)

Press **Shift+G** (or **Panels → Scene**) for a small panel with:

- **Ground grid (`G`):** a flat grid under the model. Its lines follow the world axes and its cell size adapts to the model. It sits at the model's lowest point, next to the blob shadow.
- **Move to ground, Move to origin, Reset position:** *Move to ground* drops the model so its lowest point is at height 0. *Move to origin* puts the centre of the model at 0, 0, 0. *Reset position* undoes both. These change where the model sits in the world, so they also affect files you export.
- **Field of view:** 10° to 90°. The camera moves as you change it so the model stays the same size, which gives you a flatter or more dramatic perspective.
- **Lock horizon (`H`), on by default:** left-drag orbits like a turntable. The model's up direction always stays up, so the horizon never tilts, and the camera stops just short of looking straight up or down. Switch it off for free trackball rotation. `Shift`+left-drag still pans, and holding `Ctrl` while left-dragging still rolls in trackball mode.
- **Orthographic (`C`) and Fit view (`F`):** *Fit* re-centres and re-frames the model without changing the angle you are looking from (`R` still resets to the front view).
- **Saved views:** save up to three camera positions with `Ctrl+Shift+1…3` and come back with `Alt+1…3`. They belong to the open model and are cleared when you open another.
- **Edges over shaded (`Shift+W`):** draws the mesh edges on top of the solid surface. It applies in the normal shaded view.
- **Screenshot size and transparency:** choose 1×, 2× or 4× the window size, and optionally a **transparent background**. `F12` and `Ctrl+C` use these settings. The shadow blob stays semi-transparent in the PNG, so it drops straight onto another image.

## Environment (sky, lighting, shadow)

Press **L** to switch the environment on or off, or **Shift+L** to open its settings. It is off by default, so models look as they always did until you turn it on.

What it does:

1. **Infinite skybox:** a panorama wrapped around the scene. It is locked to the camera, so zooming never gets you closer to the background.
2. **Hemispheric ambient light:** three flat colours (sky, equator and ground) are blended onto the model by which way each surface faces. There is no per-pixel image lookup: it is a few lines of shader maths.
3. **Sun:** one directional light with a direction, colour and intensity, plus a simple highlight.
4. **Blob shadow:** a soft dark patch on a plane under the model. It scales with the model, shifts away from the sun and fades with the opacity slider. There is no shadow map and no extra render pass.

Load a panorama with **Load panorama…** (an equirectangular 2:1 image: `.hdr`, PNG, JPG, TIFF, BMP or WebP). The colours and sun are fitted to it automatically: the three bands are averaged from the image and the sun is the brightest spot. **Fit lighting to panorama** repeats that after you have made changes. Without a panorama you can still use the lighting and shadow with your own three colours.

**Built-in lighting presets:** you don't need a panorama to get a good look. The **Light preset** box in the Environment panel (or **Main ▾ → Lighting preset**, or `Ctrl+L` to cycle) offers Studio Soft, Overcast, Midday Sun, Golden Hour, Blue Hour, Dramatic Rim and Neutral Grey. Each sets the three ambient colours, the sun and the shadow, and tints the background with a matching sky gradient.

**Panorama light:** with a panorama loaded, the **Panorama light** slider blends the ambient light from the three colours toward the light of the whole panorama. When the panorama loads, nine numbers describing its diffuse light are worked out once (spherical harmonics); the shader then lights every surface by which part of the sky it faces, so a warm sunset on one side tints that side of the model, and the ground colour comes from the actual floor of the image. 0 keeps the three colours (the default); 1 uses the panorama fully. It follows Rotate environment and the Y-up/Z-up setting. It is soft, directional diffuse light only: no reflections and no shadows from the panorama. It needs a loaded panorama and is ignored if lighting falls back to following the camera. It works together with Fake AO, which then darkens the result in creases.

**Surface lighting:** this box chooses how models are shaded: **Off** (VTK's plain shading), **Standard** (sky, sun and shadow with a simple highlight) or **PBR materials**. Fake AO and Panorama light need Standard or PBR and are greyed out when it is Off.

**PBR materials:** choose *PBR materials* in *Surface lighting* to give glTF/GLB models a physically-based look in shaded mode, using each material's **metallic** and **roughness**. Metals lose their diffuse colour and reflect the sky tinted by their base colour; rough surfaces get a wide, soft sun highlight and smooth ones a tight one (GGX highlight with Fresnel, so surfaces also gain reflection at grazing angles). The reflection is a very soft copy of the sky: with a panorama loaded it comes from the panorama (nine numbers describing the whole image, blurred more for rougher materials, following Rotate environment and Y-up/Z-up), otherwise from the Sky/Equator/Ground colours. It shows a smooth tint and gradient, not a crisp image. *Sun highlight* scales the sun's specular (0.25 is the physically plausible default, 0 turns it off). Other formats are shown as a plain non-metal whose roughness follows the file's gloss. It works with Fake AO (which also darkens the reflection in creases), but not with split compare, whose normal-shaded half keeps the classic look.

*What it does not do:* the viewer does not read the metallic-roughness map per pixel. When a model has one, its **average** is used for the whole material, so a model that is part metal and part plastic in one material shows a single in-between look. Normal maps, occlusion maps and emissive maps are not applied to this look either (the albedo texture is). If your GPU rejects the shader, the option switches itself off with a message.

**Fake AO:** tick *Fake AO* in the Environment panel (Surface lighting must not be Off) and set its strength. It darkens the ambient light in two cheap ways: creases and corners (a value per vertex, worked out once per model on a background thread) and a gentle fall-off toward the ground (following the Y-up/Z-up setting and any move you make). There is no screen-space pass and no ray tracing, so it costs almost nothing per frame. It sees only local creases, not a part shadowing a distant one, and it looks best on reasonably dense meshes. It is paused while split compare or the wireframe overlay is on. It affects the ambient light only, never the sun, and works in shaded mode with environment lighting on. If a GPU rejects it, it switches itself off with a message.

**Exposure and tone mapping:** the **Exposure** slider brightens or darkens the lighting in stops (it doesn't change the sky image or MatCaps). **Tone mapping** can be left off, set to *Soft highlights* (Reinhard) or *Filmic* (ACES), which are cheap curves that keep bright areas from clipping. **Sky blur** softens the panorama behind the model. **Sky gradient** replaces the background with a gradient from the equator colour up to the sky colour when no panorama is showing.

**Rotate the lighting:** hold `Shift` and right-drag in the viewer to swing the sun, and the panorama with it, around the model. The shadow follows.

**Presets:** **Save preset…** writes your sky colours, sun, ambient, shadow and on/off choices to a small JSON file, and **Load preset…** brings them back (loading also switches the environment on). A preset looks like this:

```json
{
  "gleek3deek_environment": 1,
  "name": "Golden hour",
  "settings": { "sky": [0.5, 0.65, 0.85], "sun_az": 35, "sun_el": 20, "sun_int": 0.9 },
  "panorama": "C:/Panoramas/sunset.hdr"
}
```

The panorama is stored as a path, not embedded. When a preset is loaded on another machine, the viewer also looks for the same file name next to the preset file, so you can share a preset together with its panorama in one folder. If the panorama can't be found, the preset's colours and sun are still applied. Values left out fall back to the defaults, and out-of-range values are clamped.

Notes:
- **Rotate environment** turns the panorama and carries the sun with it, so you can line the lighting up with the picture.
- The environment follows the model's up axis (`U` switches between Y-up and Z-up).
- `.exr` panoramas aren't supported; save them as `.hdr` or a PNG/JPG first. Large panoramas are shrunk to 2048 pixels wide when loaded.
- Environment lighting applies in the normal shaded view. Wireframe, points and MatCaps keep their own look.
- Deliberately excluded to keep it light: reflections, roughness and microfacet maths, and bounced light.
- If a graphics driver rejects the environment shader, the viewer falls back to lighting that follows the camera, or switches the lighting off, and says so in the status bar.

## MatCap editor and presets

Press **E** (or **Panels → MatCap**) with a model open. The editor opens as a dockable panel (see *Side panels* below) and changes the model live. Your work appears as one extra entry at the end of the **M** cycle, and it is remembered between sessions.

- **Live preview:** a small sphere at the top of the editor shows the MatCap and updates as you move the sliders or change colours, with no wait for the model.
- **Start from:** Frosted Glass, Goosh or RealSkin as a starting point.
- **Colours:** shadow, body, light, rim and gloss.
- **Sliders:** light direction and height, how far shadows and highlights spread, rim glow and tightness, gloss and sheen amount and tightness.
- **Save preset… / Load preset…:** presets are small JSON files you can share. A procedural preset looks like this:

```json
{
  "gleek3deek_matcap": 1,
  "name": "My Wax",
  "type": "procedural",
  "params": { "body": [0.78, 0.10, 0.07], "light_az": -33, "spec_tight": 0.55 }
}
```

Any value you leave out falls back to the editor's default value (a glossy red wax look), and out-of-range values are clamped.

- **Load image MatCap…:** pick a picture of a lit sphere (PNG, JPG, TIFF, BMP or WebP), including MatCap images exported from ZBrush. The image is cropped to a square, shrunk to a 32×32 colour table and fitted with a smooth formula that is used as the material. A saved image preset stores that table inside the JSON, so it doesn't depend on the original picture.

Notes:
- Image MatCaps are deliberately low resolution, so smooth materials look right but very sharp highlights get softened.
- The image is turned into a compact smooth formula inside the shader (no lookup table or texture), which keeps rendering fast. If a graphics driver rejects the full-detail version, the viewer automatically retries with a simpler one.
- ZBrush's own `.ZMT` material files can't be read; export the sphere as an image first.
- If your graphics driver rejects a MatCap shader, the viewer returns to normal shading and says so in the status bar. Details go to `gleek3deek_vtk.log` in your temp folder.

## Split compare (MatCap vs normal shading)

Press **D** with a model open. The viewport is split by a line: the MatCap on one side, the model's normal shading (including the Environment lighting if it is on) on the other. Both sides are the same mesh and camera. The model is rendered once; the shader chooses the look from each pixel's screen position.

- **Drag the line or its round handle** to move the split. Dragging anywhere else orbits, pans and zooms as usual.
- **Double-click** the line to snap it back to the centre.
- **`D`** hides or shows the split without losing its position. **`Shift+D`** cycles vertical, horizontal and diagonal. **Main ▾ → Split style** also has *Swap sides* and *Reset divider to centre*.
- **Edges over shaded** (`Shift+W`) is drawn on the normal-shaded half of the split.
- The split shows while a MatCap is active (`M`). Cycling back to normal shading hides it and it returns with the next MatCap.
- The MatCap shader is re-baked with the new position shortly after you move the line, so with image MatCaps the shading can trail the line slightly while you drag.
- Screenshots at 2x/4x do not include the split (they show the full MatCap); set the screenshot scale to 1x to capture it.

## Model info panel

Press **I** (or **Main ▾ → Model info**) to show a small card under the top toolbar. It lists:

- **Format and file size**
- **Parts:** how many separate objects the file contains
- **Vertices:** counted as the file stores them (not inflated by the viewer's smooth shading)
- **Faces:** polygon count, with the triangle count in brackets when the model uses quads or larger polygons
- **Width, height, depth:** the bounding box, labelled for the model's up axis (it follows `U`). Sizes are in the file's own units, since most formats don't record a unit
- **Materials and textures:** distinct materials and texture images. Plain meshes such as STL show "none (plain mesh)"
- **Has:** vertex colours and UV coordinates, when present

## UV inspection

Open **Materials** and go to the **UV** tab, then press **Run UV tests**. The analysis only runs when you ask, so models open quickly; until then the tests and heatmaps are greyed out. It runs in the background, so you can keep looking around, and the button turns into **Cancel** while it works (it stops within a moment, between steps). Opening another model clears the results, and you run it again. **Shift+U** shows or hides the layout pane. The UV layout appears in a pane beside the 3D model (or below it; there is a tick box for that) and you can drag the divider between them.

- **The layout:** every triangle edge in 0 to 1 UV space, over the part's texture if it has one. Mouse wheel zooms, drag pans, double-click fits the view. Pick one **Part** or **All parts**.
- **Tests**, each shown on the model and in the layout (ticking one opens the layout and switches the model to the shaded view):
  - **Out-of-bounds UVs** (orange): triangles with a UV outside the 0 to 1 square.
  - **Flipped UVs** (red): stray triangles whose UV winding is opposite to most of the model (the majority sets the convention). Whole islands that are laid out the other way round are reported under *Mirrored islands* instead.
  - **Zero-area UVs** (yellow): triangles squashed to a line or a point in UV space.
  - **Overlapping islands** (cyan): islands that partly cover each other in UV space, so they share texture pixels, usually by accident.
  - **Stacked islands** (purple): islands that sit (almost) exactly on top of each other, for example repeated parts sharing one texture area. This is often deliberate, but check it is what you meant.
  - **Mirrored islands** (pink): whole islands whose layout is the opposite way round to the model, so their texture reads mirrored (text and logos show it first).
  - A triangle that fails more than one active test is white; fine triangles are grey. The counts sit next to each test (islands for the last three).
  - **How islands are found:** triangles that share vertices form an island, where vertices with the same 3D position and the same UV count as one (so a vertex split only for normals does not cut an island). Overlap is measured on a pixel grid (512 px per UV unit): more than about 80% shared with the smaller island counts as stacked, between about 5% and 80% as overlapping. Islands that only touch along their borders are not flagged. Parts over 4 million triangles skip the island tests (they take about a second per million triangles, and memory grows with them), and the UV tab and reports say so.
- **Heatmap** (the drop-down above the tests). The tests are drawn on top of the heatmap colours.
  - **Texel density:** how much texture resolution each triangle gets (UV area against 3D area), compared with the model's median (weighted by surface area, across all parts, so parts can be compared). Green is the median, blue is below the *too low* threshold, red is above the *too high* threshold. Defaults are ×0.5 and ×2; both are adjustable in the tab.
  - **Stretch (distortion):** how much the UVs distort the surface. 1 means no distortion; scale, rotation and mirroring do not count, only squashing and shearing. Green is 1, yellow half way and red at the warning value (default 2, adjustable).
  - A colour bar in the layout pane shows the scale, and the tab and the layout footer give the share of triangles outside the thresholds.
  - Density compares triangles on the model as stored, so a part scaled differently by its node transform in the file can read differently from how it looks.
- The texture on the model is replaced by the heatmap while a test or heatmap is on, and comes back when you switch them all off.
- Models with no UV coordinates (STL, PLY, most CAD files) show "no UV data".

## Texture audit and mesh diagnostics

**Materials & parts → Textures** lists every texture with its size, bit depth, channel count, colour space, and how many parts use it. It also shows an estimate of the graphics-card memory it needs, uncompressed and with typical block compression, and flags textures that are not a power of two or are 4096 px or larger. A total sits above the list; an image that appears more than once (shared by several materials, or loaded twice by the importer) is counted once, and the repeat entries say so. Memory figures are estimates (3-channel images are stored as 4, and mipmaps add a third). Colour space is inferred from the texture's role (base colour and emissive are sRGB, normal and occlusion/roughness/metallic are linear), because the pixels don't say.

**Materials & parts → Mesh** analyses the geometry only when you press **Run integrity tests**, so models open quickly. It also runs in the background, with a **Cancel** button. Until then it shows just the polygon, part and material counts. After the run:
- Counts: triangles, vertices (and how many are at unique positions), parts (draw calls in the viewer), distinct materials (the minimum draw calls an engine needs), loose vertices, vertices sharing a position, separate pieces, open edges, non-manifold edges.
- Integrity tests that colour the failing triangles on the model, each with a count: **open (boundary) edges**, **non-manifold edges**, **zero-area triangles**, **inconsistent winding** (a patch of triangles wound the opposite way round to the surface around it is coloured whole, so you see the flipped area itself rather than just its edge), **inside-out pieces** (closed pieces with a negative volume) and **duplicate faces**.
- Vertices at the same position count as joined, so UV and hard-edge seams are not reported as holes. A colour test replaces the texture while it is on, like the UV tests, and can be combined with them.

## Measurements and cross-section

**Materials & parts → Measure** has three tools. Set the **Model units** first, because most formats don't say what one unit means (glTF/GLB is metres by convention; STL and OBJ files are often millimetres). Results can be shown in mm, cm, m, in or ft.

- **Calculate size, volume and centre of mass** (on request, so models open quickly) measures the visible parts and shows: bounding-box size, the oriented bounding box (the smallest box, turned to fit), surface area, volume (also in litres), and centre of mass. Volume and centre of mass need closed parts: open parts are left out of the volume and reported, and with no closed part the centre is that of the surface.
- **Measure between points** (`Shift+R`): click 2 or 3 points on the model. You get the distance, the x/y/z differences, the second distance and the angle at the middle point. Markers and distance labels are drawn on the model. A click that doesn't move picks a point, while dragging still orbits, so the model can be turned between picks. Switching the mode off clears the points.
- **Cross-section**: cut the model with a plane along X, Y or Z using the slider; the cut is outlined in yellow. **Keep the other side** flips which half is hidden. Measurement marks and the section outline are left out of reference sheets.

## LOD preview (simplification)

**Materials & parts → LOD** shows how the model looks with fewer triangles. Press **Generate LOD previews**; the 50%, 25% and 10% levels are built from the original in the background (quadric decimation, one part at a time), so the app stays usable while a large model is processed. A table lists the triangle and vertex counts of each level. Pick a level in the **Show** list to see it on the model, and go back to **Original** at any time.

- Texture seams are borders of the mesh, and the decimator protects borders, so UVs hold up well. Very low levels can still stretch textures; look at the UV tab results on the original for a reference.
- A level is a preview only: your file is not changed and **exports always use the original geometry**.
- Switching level clears the UV, mesh and measurement results, because they describe the geometry that was showing. Run them again on the level you want to inspect.
- Nothing is calculated until you press the button, so loading stays fast.

## Export / convert and mesh simplification

Open a model, then press **Ctrl+E** (or use **File → Export / convert…** or **Main ▾ → Export / convert…**).

- **Formats:** STL (binary or ASCII), OBJ, and PLY (binary or ASCII). This also works as a converter: open a GLB, FBX or any other supported file and export it as STL, OBJ or PLY.
- **Simplify mesh:** tick the box and choose what percentage of the triangles to keep. The dialog shows the resulting triangle count. Simplification uses quadric decimation, which removes the faces that change the shape least.
- **What is exported:** the geometry as it is shown, including each part's placement. Parts are merged into one mesh, duplicate vertices are welded, and every polygon is turned into triangles first.
- **Colours:** vertex colours are kept in PLY files when the model has them. OBJ gets smooth normals. Materials and textures are **not** written.
- The export runs in the background, so the viewer stays responsive. Large models can take a while to simplify.

Very strong simplification (under about 10%) can visibly change the shape, and open edges aren't specially protected, so thin or open surfaces may shrink at their edges.

## Reference sheets for AI 3D tools

Press **Shift+F12** (or **Main ▾ → Reference sheet for AI 3D tools…**) to render the model from several angles onto one image, ready to upload to Meshy, Tripo, Rodin, Luma and similar 2D-to-3D tools.

- **Layouts:** *4-view orthographic* (Front, Back, Left, Right; the best default) or *4-view 3/4 hybrid* (Front, 3/4 Front, Side, Back; helps with layered or overlapping geometry).
- **Background:** pure white or neutral mid grey. **Size:** 512 to 2048 px per view (the sheet is four views wide). Optionally write the view names under each view (off is best for AI tools) and save every view as its own PNG too.
- **Applied automatically, then undone:** orthographic projection, flat even lighting (no sun, so every side is lit the same and there are no hard shadows), grid, sky, sky gradient, blob shadow, edge overlay, axes gizmo and the split compare are switched off, and the background becomes solid. Your camera, lighting, background and display settings are restored afterwards.
- **Shared baseline:** every view uses the same scale and the same centre height, so the top and the bottom of the model sit on exactly the same pixel rows in every view. All views look horizontally (no tilt), including the 3/4 view.
- Views come from the live viewport, so a larger window gives a sharper result at the bigger sizes. The model uses its current colours and textures; hidden parts stay hidden.

## Command-line mode

Run an audit from a console, without opening the window. Give a model file or a folder; any option starting with `-` selects this mode (`python main.py ...` and `python cli.py ...` do the same thing).

```
python cli.py model.glb --all
python cli.py ./assets --recursive --mesh --textures --fail-on holes,flipped
python cli.py ./assets -r --all --units mm:cm --json --report audit.json
python cli.py ./assets -r --all --report audit.csv      # one row per file, for a spreadsheet
python cli.py ./assets -r --all --report audit.html     # one self-contained web page
```

| Option | What it adds |
|---|---|
| *(none)* | triangles, vertices, parts, materials, textures, UVs present, size |
| `--textures` | each texture's size, bit depth, inferred colour space and estimated GPU memory (an image used twice counts once) |
| `--mesh` | holes, non-manifold edges, zero-area and duplicate faces, inconsistent winding, inside-out pieces, loose vertices, pieces |
| `--uv` | the UV tests, island counts, texel-density and stretch outliers |
| `--measure` | bounding box, oriented box, surface area, volume, centre of mass |
| `--lod` | triangle counts at the 50%, 25% and 10% levels (slow) |
| `--all` | info, textures, mesh, uv and measure |
| `--units m` / `--units mm:cm` | what one model unit means, and the unit to report in (mm, cm, m, in, ft) |
| `--format text\|json\|csv\|html` | the output format (`--json` is short for `--format json`). `html` is for `--report` files only, because the console shows text |
| `--report FILE` | also write the output to a new file. Its format follows `--format`, else the extension (`.csv`, `.html`, `.json`, `.txt`), else the console format |
| `-r`, `--recursive` | include sub-folders |
| `-q`, `--quiet` | print nothing except errors |

**Checks for scripts and CI.** `--fail-on` takes a comma-separated list of `holes`, `nonmanifold`, `degenerate`, `flipped`, `duplicates`, `open`, `uv-missing`, `uv-overlap`, `uv-bounds`, `uv-flipped`, `npot`. Limits: `--max-triangles N`, `--max-texture-mb MB`, `--max-texture-px PX`, `--max-materials N`. The data a check needs is switched on automatically.

| Exit code | Meaning |
|---|---|
| 0 | everything passed |
| 1 | a `--fail-on` or `--max-*` check failed |
| 2 | bad usage: wrong path, unknown option, or an unsafe `--report` |
| 3 | some files could not be loaded |

**Report formats.**
- **CSV** has one row per file and one column per figure: triangles, materials, texture memory, each mesh and UV test, size, volume and so on. The columns depend on the sections you ask for, so every row has the same columns. Failed loads still get a row (`result` is `ERROR`). The file is UTF-8 with a byte-order mark so Excel reads it correctly, and text that a spreadsheet would run as a formula (starting with `=`, `+`, `-` or `@`) is prefixed with a quote.
- **HTML** is a single page with no external files: summary cards, a sortable and filterable table (click a heading, filter by name, or show only failures or errors), and a collapsible detail block for every file. It follows your light or dark setting and blocks any outside loading. File names and error messages are escaped, so a hostile file name cannot add anything to the page.

**Folders.** Supported files are audited one at a time and a summary table follows. By default each file is loaded in its own child process, so a corrupt file that crashes the loader or hangs (`--timeout`, default 300 s) is reported as an error and the run carries on; `--no-isolate` is faster but loses that protection. Files larger than `--max-size-mb` (default 1024) and anything past `--max-files` (default 2000) are skipped and listed.

**Read-only by design.** This mode never changes, moves, copies or deletes a model, and has no commands that could. Symbolic links are skipped and never followed. The only file it can write is the `--report` file, which refuses to replace an existing file (unless `--force`), refuses a symbolic link, and refuses a place inside the folder being scanned.

**Notes.** The text output uses × and ≈, so it is written as UTF-8. The windowed Windows `.exe` prints to the terminal it was started from; for scripting, use `python cli.py` or a console build. Texel density and stretch figures use the default thresholds (×0.5 and ×2 of the median density, stretch 2).

## Supported formats

| Format | Extensions | How it's read | Notes |
|---|---|---|---|
| glTF / GLB | `.gltf` `.glb` | VTK glTF importer | Base colour textures; PBR is shown as simple shading. WebP textures and quantized geometry (`KHR_mesh_quantization`, used by Tripo AI and gltfpack) in GLB files are converted automatically. Draco (`KHR_draco_mesh_compression`) and Meshopt (`EXT_meshopt_compression`) compressed geometry in GLB files is decoded when the optional packages are installed: `pip install DracoPy meshoptimizer`. KTX2-compressed textures are not supported, and compressed `.gltf` files with separate buffers are not converted |
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
- **A compressed GLB says to install a decoder:** run `pip install DracoPy meshoptimizer` inside `.venv` (use the one the message names).
- **STEP files won't open:** run `pip install cadquery`.
- **Black or blank 3D view:** update your graphics driver. VTK needs OpenGL 3.2 or newer.
- **Thumbnails missing:** the generic icon stays if a file is too large, in an unsupported format, or can't be parsed. Thumbnail cache lives in your OS user cache folder under `Gleek3Deek/thumbs` and is safe to delete.

## Project layout

```
Gleek3Deek/
├── main.py                   # the main window: folder tree, gallery page, menus (start here: python main.py)
├── viewer.py                 # the 3D viewer widget, its tools, and the About-box wording (ABOUT)
├── formats.py                # file loading: format list, importers, GLB fixes (no windows)
├── analysis.py               # texture audit, mesh checks, measurements, UV maths, LOD, export (no windows)
├── cli.py                    # command-line mode (read-only audit of a file or folder)
├── matcap.py                 # MatCap shaders, custom MatCap parameters, editor and preview
├── gallery.py                # thumbnail grid, thumbnails, file icons, background loading
├── library.py                # tags, colour labels, ratings and smart folders (one JSON file, no windows)
├── fileops.py                # copying and moving models with their companion files (no windows)
├── environment.py            # sky, lighting and tone mapping, panorama handling, Environment panel
├── panels.py                 # Materials, Info and Scene panels, export dialog
├── requirements.txt          # required packages
├── requirements-optional.txt # optional format support
├── run.bat                   # Windows launcher
├── run.sh                    # macOS / Linux launcher
├── build_exe.bat             # builds the Windows .exe
├── gleek3deek.spec           # PyInstaller recipe
├── requirements-build.txt    # build-only packages
├── .github/workflows/build-windows.yml   # automatic exe builds
├── .github/workflows/tests.yml           # runs the tests on every push
├── tests/                    # automated tests (no VTK or Qt needed)
├── pytest.ini, requirements-dev.txt, .gitignore
├── LICENSE
├── README.md                 # the short introduction
└── GUIDE.md                  # the full user guide
```

## Running the tests

```
pip install -r requirements-dev.txt
python -m pytest -q
```
The tests cover the mesh checks, measurements, UV maths, texture audit, the command-line mode and reports, compressed-GLB conversion, Fake AO and panorama light, the tags/ratings library, and an import check of every module (about 110 tests, a few seconds). They need only numpy and pytest: VTK and Qt are replaced by stand-ins when they are not installed, so they also run on a plain CI machine. `.github/workflows/tests.yml` runs them on every push.

## About dialog

Press **F1**, or choose **Help → About** (also in **Main ▾** while a model is open). It shows the app name, who made it, the legal notice, the MIT licence text and the open-source attributions. Close it with the ✕ button, the **Close** button, the window's own close button or **Esc**.

All of its wording lives in one dictionary named `ABOUT`, just under `APP_NAME` at the top of `viewer.py`: your name and alias, copyright line, legal notice, licence text, the list of third-party projects, and an optional version string (blank means it is hidden). Edit those values and nothing else needs to change.
