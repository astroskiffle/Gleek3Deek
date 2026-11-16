# RetroGleek

A small, fast, **fully offline** image browser and viewer for Windows 10/11, with built-in support for
**retro-computer picture formats** (Amiga, Atari, Commodore 64, ZX Spectrum, MSX, Amstrad CPC and hundreds more)
through [RECOIL](https://github.com/pfusik/recoil).

It builds into **one small `.exe`** using the C# compiler that already ships with Windows: no SDK, no installer,
no NuGet packages and no internet connection.

## Features

- **Folder tree + thumbnail grid.** The tree is lazy-loaded; folders are scanned and thumbnails are decoded on
  background threads, so large folders stay responsive.
- **Filter, sort and thumbnail size in one bar** above the thumbnails: filter the folder as you type (part of a name,
  or `*` / `?` wildcards), pick a sort order (name, date modified, size, type) with a reverse arrow, and drag the size
  slider to grow or shrink the thumbnails. Optional dimensions / platform line under every thumbnail, and a details
  tooltip when you rest the pointer on a tile.
- **Address bar** with back / forward / up buttons for navigating local folders.
- **Full-canvas viewer.** Zoom, pan, a Fit-to-Screen toggle that stays on or off as you move between pictures, rotate,
  flip, a checkerboard for transparent pictures, copy to the clipboard, delete, fullscreen, keyboard / mouse-wheel navigation through the
  folder, and a **slideshow**.
- **Pixel-art tools** in the viewer: whole-number zoom, a pixel grid, crisp, sharp or smooth enlargement, and a readout of
  the x, y position and colour under the pointer.
- **Formats.** JPEG, PNG, GIF, BMP and TIFF (Windows GDI+); WebP, AVIF, HEIC, JPEG XL, JPEG XR and camera RAW through
  the decoders installed in Windows (see [Modern formats](#modern-formats-webp-avif-heic-jpeg-xl-camera-raw)); plus 567
  retro file extensions (RECOIL).
- **Save as PNG (lossless).** One picture or a whole selection; every PNG is read back and compared pixel by pixel
  before it is kept.
- **File management.** Rename, cut / copy / paste, drag-and-drop to move or copy, delete to the Recycle Bin, new folder.
  Nothing is ever overwritten: a name that is already taken gets a number added.
- **Menu bar** with every command and its shortcut.
- Dark interface, high-DPI aware.

## Privacy and security

- **No network code at all.** No sockets, HTTP, telemetry, update checks, licensing or cloud APIs. The program uses
  only the .NET Framework that ships with Windows (`System`, `System.Drawing`, `System.Windows.Forms`,
  `Microsoft.VisualBasic` for Recycle Bin deletes, `System.Xml`, and WPF's imaging classes, which reach the picture
  decoders installed in Windows) plus the bundled `RECOIL.cs`, which is pure C# with no `unsafe` or native code. You can check this yourself: the whole program is a handful of readable C# files plus `RECOIL.cs`.
- **Writes files only when you ask** (save, copy / cut / paste, drag-and-drop, rename, delete, new folder, audit report, retro-format conversion (new files only), a
  lossless JPEG turn or a star rating written into a JPEG or PNG file after you confirm it, and
  **marks.tsv** when you rate, label or tag a picture), plus one small plain-text **settings.ini** next to `RetroGleek.exe`, written when you close RetroGleek. It remembers the window
  size and position, the folder-tree width, sort order, thumbnail size, details on tiles, retro formats on / off, the
  viewer options (Fit to screen, checkerboard, enlarged pixels, True TV aspect, scanlines, phosphor mask, video signal, glow, curvature, automatic effects, presets, recent copy / move folders, favourite and recent folders, filmstrip, preview pane, info bar, EXIF panel, slideshow interval) and the last
  folder. If that folder can't be written (for example Program Files), it goes to `%LOCALAPPDATA%\RetroGleek\` instead.
  Never on a network location, and never in the registry. Delete it, or use Settings > Reset to default settings, to
  start again with the defaults.
- **Cloud placeholder files are never opened.** Files that OneDrive and similar services keep online-only are shown
  as "cloud-only" tiles, so browsing cannot trigger a download. Network drives are not listed in the tree. Copying a
  folder leaves the cloud-only files and folders inside it out, and says how many. Moving a folder that holds some to
  another drive (which Windows does by copying, downloading them first) asks before it starts: move anyway, leave
  that folder where it is, or cancel. Moves on the same drive download nothing.
- **The address bar opens local drives only.** Network paths (`\\server\share`) are refused.
- **Retro decoders are managed, bounds-checked code** with hard limits (32 MB per file, 16 million pixels per
  picture). Any decoding error is caught and shown as a message instead of crashing the viewer.
- The five standard formats are decoded by Windows' own GDI+, which Windows Update keeps patched.

## Build

Requirements: Windows 10 or 11 (which includes .NET Framework 4.x and its C# compiler).

1. Keep all the `.cs` files, `RetroGleek.manifest` and `build.bat` together in one folder.
2. Double-click **`build.bat`**. It produces `RetroGleek.exe` next to them, and `RetroGleekCli.exe`, the optional
   console companion for command-line audits (you only need it if you use the command line).

The source is written in C# 5 so that the compiler built into Windows can build it.

Run it with `RetroGleek.exe`, optionally followed by a folder or an image path, e.g. `RetroGleek.exe C:\Pictures`.
You can also drag a file or folder onto the window, or use **Ctrl+O**.

## Using it

Everything is in the **menu bar** (File, Edit, View, Effects, Go, Tools, Settings, Help; press **Alt** to use it from the
keyboard), and every menu entry shows its keyboard shortcut. Entries that don't apply right now (for example viewer
commands while you are browsing) are greyed out. **F1** lists every key on one page. The menu bar is hidden in
fullscreen.

**Browser (folder tree and thumbnails)**

| Action | Keys / mouse |
|---|---|
| Open a picture in the viewer | Double-click or Enter |
| Move / select | Arrows, Home / End, PgUp / PgDn; Shift / Ctrl for multi-select; Ctrl+A; Ctrl+I inverts the selection (or right-click) |
| Rubber-band select | Drag with the mouse, starting anywhere except on a selected picture; hold Ctrl to add to the selection. Dragging past the top or bottom edge scrolls |
| Move or copy by dragging | Drag a **selected** picture (it carries the whole selection) onto a folder in the tree, or into Explorer. As in Explorer: same drive moves, another drive copies; hold **Ctrl** to copy or **Shift** to move. Files dropped onto the tree from Explorer work the same way |
| Move or copy a folder | Drag the folder in the folder tree onto another folder (same rules), or right-click it > Cut, then Paste. Drives and Windows' own folders (Desktop, Documents, Pictures, your user folder, Windows, Program Files ...) can't be moved |
| Copy to / Move to a folder | Ctrl+Shift+Y (copy) or Ctrl+Shift+M (move), or Edit > Copy to / Move to. Choose a folder, or one of the last 8 you used (remembered next time). Works on the selected pictures, on the folder chosen in the tree, and on the picture in the viewer (after a move the viewer shows the next picture). Same rules as every copy and move: local drives only, nothing is overwritten (a name that is taken gets a number), and Ctrl+Z undoes a move. Handy after culling: Edit > Select tagged, then Ctrl+Shift+M |
| Cut and paste (move) | Ctrl+X, then Ctrl+V in another folder (or in Explorer). Works the other way round too |
| Scroll / change thumbnail size | Mouse wheel / the **Size** slider (or Ctrl + wheel) |
| Filter the folder by name | The **Filter** box is always visible: type in it (`*` and `?` are wildcards, spaces mean "and"); Ctrl+F jumps to it, Esc clears it |
| Undo | Ctrl+Z (or Edit > Undo, which names what it will undo) puts back the last rename, batch rename or move, up to 20 steps while RetroGleek runs. Nothing is overwritten: an item whose old name has been taken since, or that is gone, is skipped and listed. Copies and deletes are not undone (deleted files are in the Recycle Bin) |
| Folder audit report | Ctrl+Shift+A (or Tools > Folder audit report). Checks every picture file in the open folder (not subfolders), including retro files that can't be opened, and saves one self-contained HTML page where you choose. For each file: name, your rating, colour label and tag, type, platform (Amiga, ZX Spectrum, C64, Atari ST ...), whether it opened (and why not), size, dimensions, frames, number of colours, date, a thumbnail and a SHA-256 fingerprint (exact duplicates are marked). The page can be searched, filtered by platform, type, status and marks (tagged, rated, stars, colour label, no marks), sorted by any column, and exported as CSV. It works offline and loads nothing from the internet. For a much smaller file, use Tools > Folder audit report, no thumbnails. Files with very generic extensions (`.raw`, `.img` ...) are listed only if they really are pictures |
| Compare side by side | Select exactly two pictures, then Ctrl+Shift+C (or View > Compare side by side, or right-click). Each picture gets half the window with its own info bar. Zooming (Ctrl + wheel, + / -, 1..9) or dragging in either one moves the other to the same zoom and position, so pictures of the same size line up pixel for pixel; fit (0, double-click) fits each picture to its half. Rotate, flip, pixel grid, crisp / sharp / smooth, info bar, checkerboard and EXIF apply to both. Esc (or Ctrl+Shift+C) goes back to the browser |
| Contact sheet | Select pictures, then Tools > Contact sheet (lossless PNG). Choose small, medium or large thumbnails (12, 10 or 8 per row), a dark or light background (light is better for printing), and whether to show ratings, colour labels and tags. Each thumbnail gets its name and its original resolution and platform (retro pictures) or size and type (photos) underneath; retro pictures are enlarged with hard edges, photos are never enlarged. At most 100 pictures per sheet: a bigger selection becomes numbered pages (`name_001.png`, `name_002.png` ...), and one export takes at most 2,000 pictures (for a whole collection, use the audit report). Before anything is written you see how many pages it will be and roughly how big, and RetroGleek checks there is enough free space. Built one page and one picture at a time in the background, so memory use stays bounded however many pictures there are (well under 100 MB while a page is saved and checked). Every page is a verified lossless PNG; nothing is overwritten without asking. Pictures that can't be opened keep their place, marked |
| Convert to a retro format | Select pictures (or open one in the viewer), then Ctrl+Shift+E (or Tools > Convert to a retro format). Makes a new file for each picture in a retro-computer format: **ZX Spectrum screen** (`.scr`: 256 x 192, ink and paper per 8 x 8 block), **C64 Koala Painter** (`.koa`: 160 x 200 multicolour, a shared background plus 3 colours per 4 x 8 cell), **C64 Doodle** (`.dd`: 320 x 200 hires, 2 colours per 8 x 8 cell), **Amstrad CPC screen** (`.scr`: mode 0, 160 x 200 with 16 of the CPC's 27 colours, or mode 1, 320 x 200 with 4 of them; the mode and colours are stored in the screen's unused bytes, and the file has an AMSDOS header so a real CPC can load it at &C000; a name with a `.pal` file beside it is skipped, as RECOIL would use that file's colours), **Atari ST Degas** (`.pi1`: 320 x 200, the 16 colours that suit the picture best, from the ST's 512), **Amiga IFF** (`.iff`: 320 x 256, 32 colours from the Amiga's 4096), **MSX Screen 2** (`.sc2`: 256 x 192, foreground and background colour per 8 x 1 strip) or **MSX2 Screen 8** (`.sc8`: 256 x 212, 256 fixed colours). Choose whole picture (black borders) or fill the screen (edges cropped), and dithering: none, an ordered pattern (the typical look of the time) or error diffusion; a preview shows the first picture exactly as the new file will look. The originals are never changed and nothing is overwritten (a name that is taken gets a number). Converting is lossy by nature: each picture is reduced to the machine's colours and colour rules. Every new file is checked before it is kept: RECOIL decodes it and every pixel must match what the converter meant; the machine's colours are taken from RECOIL too, so the viewer shows exactly the same picture. The last format and options chosen are kept while RetroGleek runs |
| Batch rename | Select pictures, then Ctrl+F2 (or Tools > Batch rename, or right-click). Type a pattern: `#` is the number (`###` gives 001, 002 ...), `[name]` is the current name, so `holiday_###` or `C64_[name]` both work; choose the first number. A preview lists every old and new name; names that would clash with an existing file, appear twice or are not allowed are shown in orange and stop the rename. Extensions are kept, pictures are numbered in grid order, and nothing is overwritten |
| Details list | Ctrl+Shift+D, the **Details** button next to the filter box, or View > Details list: one row per picture with a small thumbnail, Name, Rating, Label, Type, Platform, Dimensions, Size, Modified and Status (cloud-only, or why a picture could not be opened). Click a column title to sort by it, click again to reverse. The Size slider sets the row height; the list and the thumbnails each keep their own size. Platform and dimensions fill in as pictures are read; when you sort by them, RetroGleek reads the rest of the folder in the background and sorts once more when it has them all. Remembered next time |
| Analyse folder | Tools > Analyse folder reads every listed picture in the background (with the Subfolders switch, those below too) and fills in the Details list's **Frames** and **Colours** columns and duplicate marking ("Duplicate of ..." in Status, from a SHA-256 fingerprint), with the same full checks as the audit. Progress shows in the status bar; the menu entry becomes Stop analysing; opening another folder stops it. Sorting by Frames or Colours starts it by itself. Results are kept for each file while RetroGleek runs, so coming back or refreshing doesn't repeat the work |
| Search subfolders | The **Subfolders** switch next to the filter box (or Ctrl+Shift+F, Edit > Include subfolders): lists the pictures in this folder and every folder below it, so the filter searches them all. Hidden and system folders are skipped, and a search stops at 20,000 pictures. The switch turns itself off when you open another folder or drive (refreshing the same folder keeps it on); resting the pointer on a tile shows which subfolder it is in |
| Address bar | Ctrl+L, type or paste a local path, Enter |
| Preview pane | Alt+P (or View > Preview pane) shows a large preview of the focused picture to the right of the thumbnails or the Details list, with its name, dimensions, platform, size, date, marks (and its subfolder when Subfolders is on). Retro pictures are enlarged with hard edges. Drag its left edge to make it wider or narrower. Off by default; on / off and its width are remembered next time |
| Favourite folders | Ctrl+D (or Go > Favourites > Add this folder, or right-click a folder in the tree) adds the open folder; it appears with a star in the folder tree after Desktop, Documents, Downloads and Pictures, and in Go > Favourites. Ctrl+D again, or right-click > Remove from favourites, takes it off the list (the folder itself is never touched). Up to 20, remembered next time. A favourite in the tree is a shortcut: it can't be dragged, renamed or deleted from there |
| Recent folders | Go > Recent folders lists the last 10 folders you opened, remembered next time |
| Back / forward / up one folder | Alt+Left / Alt+Right / Alt+Up (or Backspace), or the buttons |
| Sort | The **Sort** pull-down (name, date modified, size, type, platform, dimensions, frames, colours, status, rating, label) and its arrow button to reverse; or right-click > Sort by |
| Details on tiles | Right-click > Show details on tiles; rest the pointer on a tile for a tooltip |
| Rate, colour-label and tag pictures | `Alt+1` .. `Alt+5` give 1 to 5 stars (`Alt+0` removes the rating); `Shift+1` .. `Shift+5` give a red, yellow, green, blue or purple colour label (`Shift+0` removes it); `X` tags or untags. They work on the selected pictures here, and on the picture shown in the viewer (also during a slideshow); Edit > Rating / Colour label / Tag do the same. Marks show on the thumbnails (stars at the bottom left, a colour strip along the top, a tick for the tag), in the Details list's Rating and Label columns, and in the viewer's info bar. Settings > Move to the next picture after marking makes culling quicker. Marks are kept in `marks.tsv` next to `settings.ini`, not inside the pictures, so they work for every format (Edit > Rating > Write my ratings into the files copies your stars into JPEG and PNG files, see below). They follow pictures you rename or move in RetroGleek (and undo), and pictures moved in Explorer (or whose folder was moved or renamed there): a picture with no mark gets the mark of a file with the same name, size and date that is no longer where it was (on a drive that is still connected, so an unplugged USB stick keeps its marks; a copy never takes a mark). A picture renamed in Explorer keeps its mark too, when that is certain: exactly one marked picture has gone from the same folder, and the renamed picture is the only file there with its size and date. A mark stops applying if its file is changed or replaced |
| Ratings stored in photos | Star ratings that Windows Explorer, Lightroom and other programs store inside JPEG, TIFF and PNG files (the EXIF Rating tag or XMP `xmp:Rating`) are shown too, in silver instead of gold: on the thumbnails, in the Details list, the viewer's info bar ("(in the file)"), the preview pane, the audit report (with a Rating source column in the CSV) and contact sheets. They count for the Show pull-down and for sorting by rating; while you filter or sort by rating, RetroGleek reads them in the background for the rest of the folder. RetroGleek reads them, and changes them (in JPEG and PNG files) only when you ask (next row). Your own rating (Alt+1..5) takes their place; Alt+0 removes yours, and the file's rating shows again |
| Write ratings into JPEG and PNG files | Edit > Rating > Write my ratings into the files (JPEG, PNG), on the selected pictures or the picture in the viewer. Copies your RetroGleek star rating into each file's XMP (`xmp:Rating`, and the Windows EXIF rating tags if the file already has them), so Windows Explorer, Lightroom and other programs that read XMP see it. In a PNG the XMP goes into the standard `iTXt` chunk (`XML:com.adobe.xmp`) just before the picture data. Always asks first, because it changes the files. Only the information block changes; the picture data (and in a PNG every other chunk) is copied byte for byte, so no quality is lost and every other XMP property is kept. Each new file is checked (same picture data, the rating reads back) before it replaces the old one. Pictures with no RetroGleek rating, other formats (TIFF included), and files whose XMP can't be changed safely (extended or compressed XMP, unreadable XML, a damaged PNG chunk) are left alone, with the reason. Colour labels and tags stay in RetroGleek only |
| Show only marked pictures | The **Show** pull-down next to the filter box (or View > Show): all pictures, tagged / not tagged, 1 to 5 stars or more, no rating, one colour label, or no label. Works together with the name filter. Edit > Select tagged selects the tagged pictures, ready to copy, move, rename, export or delete; Edit > Clear tags in this view removes the tags. Sort by Rating or Label with the Sort pull-down or the column titles. The status bar shows how many pictures are tagged |
| Rename, Cut, Copy, Paste, Delete (Recycle Bin), Refresh | F2, Ctrl+X, Ctrl+C, Ctrl+V, Del, F5 (or right-click). The open folder also refreshes by itself when files in it are added, changed, renamed or deleted, and keeps your selection. The folder tree updates itself too when folders are created, deleted or renamed (also in Explorer), without closing the folders you have open, and USB sticks / memory cards appear and disappear as you plug them in or out |
| Turn JPEG photos on disk, without loss | Ctrl+Shift+R (clockwise) / Ctrl+Shift+L (counter-clockwise), or Edit > Turn the file (also 180 degrees), on the selected JPEG photos or the photo in the viewer; in the viewer, File > Save the turn into the JPEG saves the turn you made with R / L. Always asks first, because it changes the files. Nothing is re-compressed, so no quality is lost: a photo with an EXIF orientation tag just gets a new tag value (Windows, browsers and RetroGleek all honour it); one without a tag is turned block by block with Windows' lossless JPEG transform, only when its width and height are whole multiples of the JPEG block size (otherwise it is left alone, with the reason). Each new file is written under a temporary name and checked (the orientation read back, or the picture compared with the original turned) before it replaces the old one. Ratings, labels and tags stay with the photo. Other formats are never changed (Save as PNG keeps a turned copy) |
| Save selection as lossless PNG | Ctrl+S (or right-click) |
| Save every frame / page as PNG | Ctrl+Shift+S (or File > Export all frames as PNG, or right-click): each frame of an animated GIF or WebP, or each page of a multi-page TIFF, becomes its own verified lossless PNG (`name_frame001.png` ...) in a folder you choose. Frames are saved as they are shown. Pictures with only one frame are skipped and listed |
| Show / hide retro-computer formats | F8 (or right-click) |

While you are typing in the filter or address box, editing keys (Del, Backspace, Ctrl+C / V ...) act on the text,
never on your files.

**Viewer**

| Action | Keys / mouse |
|---|---|
| Previous / next picture | Left / Right, PgUp / PgDn, Space / Backspace, mouse wheel |
| First / last picture | Home / End |
| Zoom | Ctrl + wheel; `+` / `-` (whole-number steps above 100 %); `1`..`9` jump to 100 %..900 % |
| Pan | Click and drag |
| Fit-to-Screen on / off | `F`. Off: every picture opens at 100 % (the default). On: every picture is scaled to fit the window. The choice stays for the following pictures and is remembered next time |
| Fit this picture / actual size | `0` / `1`; double-click toggles |
| Flip left-right / top-bottom | `H` / `V` (included when you save or copy the picture) |
| Checkerboard behind transparent pictures | `B` (remembered next time) |
| True TV aspect (retro pictures) | `T` (or Effects > True TV aspect). RECOIL already doubles pixels by whole numbers (a C64 multicolour picture of 160 x 200 is shown 320 x 200); this also gives each pixel the exact shape it had on a PAL / NTSC TV, from RECOIL's figures for that machine (for example C64 PAL pixels are 0.94 wide for 1 high, ZX Spectrum 1.05). Pictures without known figures are shown unchanged. The info bar shows the original resolution and "TV aspect". Display only: saved and copied pictures are never changed. Remembered next time |
| Scanlines (retro pictures) | `K` cycles off / light / medium / strong (or Effects > Scanlines). Each original screen line is drawn as a soft beam with a dark gap between lines, as on a CRT, one per original line (an interlaced 640 x 400 picture of 200 lines gets 200). Bright colours make a wider beam that fills more of the gap, and the picture is brightened to make up for the gaps. Shown from about 300%; with scanlines on, fitting uses the largest whole-number size so every line is equally thick. Hidden while the picture is turned on its side (R / L to 90 or 270 degrees) and back when it is upright again. Display only. Remembered next time |
| Video signal (retro pictures) | `C` cycles RGB / S-Video / composite (or Effects > Video signal). RGB shows the picture as decoded. S-Video and composite show it as it reached a TV through those cables: the picture's brightness and colour are blurred along each line by the signal's limited bandwidth, colour much more than brightness, and composite more than S-Video. That is what made 1-pixel dithering (checkerboards and stripes, common in C64, Amiga and Atari ST art) blend into solid in-between colours on a real TV. Lines stay separate, and hires pictures get the same blur on screen as lores ones. Worked out once per picture. Not shown: the rainbow fringes and crawling dots of real composite video, which depend on each machine's exact timing. Display only; the colour readout still shows the picture's own colours. Remembered next time |
| Glow (retro pictures) | `W` cycles off / soft / strong (or Effects > Glow). Bright areas light up their surroundings with a soft halo, as on a CRT, most visible with white or bright text on a dark background. The halo spreads about one and a half original screen lines and is added on top of scanlines and mask. Worked out once per picture. Display only. Remembered next time |
| Screen curvature (retro pictures) | `U` cycles off / slight / strong (or Effects > Screen curvature). The picture bulges like the glass of a CRT, with darker, rounded corners. The visible part of the picture is the screen: when you zoom in, the window is the glass. Because it bends the picture's pixels, it switches itself off at 800% and above, where the pixel grid and the pixel outline need exact pixels; near the edges, the x, y readout gives the pixel before bending. Automatic mode keeps your own curvature setting, since it is a matter of taste, and stays on when you change it; presets include it. Display only. Remembered next time |
| Automatic screen effects | `A` (or Effects > Automatic) gives every retro picture the effects of the screen its computer was usually seen on, from the platform RECOIL reports: for example a Commodore 64 gets the S-Video look of a 1702 / 1084 monitor with a slot mask, a ZX Spectrum a home TV through the aerial socket (composite), an Amiga the RGB picture of a 1084S, an Atari ST in 640 x 400 the sharp SM124 mono monitor (no scanlines, no mask), and LCD machines (Portfolio, HP 48, Psion) no CRT effects at all. True TV aspect is always on. These are typical set-ups; many machines were used with more than one kind of screen. The flash message and the Effects menu say which screen was chosen. Your own settings are kept aside meanwhile and `A` again brings them back; changing any single effect while automatic is on keeps what you see, with your change, as your own settings. Curvature is the exception: automatic never chooses it, so `U` changes it and automatic stays on. Remembered next time |
| Screen effects presets | Effects > Save these effects as a preset... saves the current TV aspect, scanlines, mask, video signal, glow and curvature under a name (up to 9). Use one with `Ctrl+1` .. `Ctrl+9` (top row or keypad) or from the Effects menu; Effects > Delete a preset removes one. A preset also ends automatic mode. Saving with automatic on suggests the computer's name. Presets are written to settings.ini straight away |
| All screen effects off / on | `O` (or Effects > Show screen effects) turns True TV aspect, scanlines, mask, video signal, glow and curvature off together, to compare with the picture as decoded; `O` again, or changing any effect, brings them back. Each effect keeps its own setting. Every start shows the effects |
| Phosphor mask (retro pictures) | `M` cycles off / aperture grille / slot mask / dot mask (or Effects > Phosphor mask). The fine pattern of red, green and blue phosphors on a CRT: aperture grille is the stripes of a Sony Trinitron, slot mask the staggered slots of most TVs and monitors such as the Commodore 1084S, dot mask a fine pattern of dots. Drawn in screen pixels (twice as wide on very high-resolution screens), so it stays still while you pan. Shown from 200%; works with or without scanlines. Hidden while the picture is turned on its side. Display only. Remembered next time |
| Copy the picture to the clipboard | Ctrl+C (as you see it: rotation and flips included) |
| Delete the picture (Recycle Bin) | Del, then the next picture is shown |
| Rotate clockwise / counter-clockwise | `R` / `L` |
| Slideshow | `S` starts / stops; Up / Down change the interval while it runs; Esc also stops it |
| Pixel grid | `G` (drawn at 800 % and above) |
| Filmstrip | `J` (or View > Filmstrip) shows a row of small thumbnails of the folder along the bottom, with the current picture in the middle and outlined; click one to show it. The picture is fitted above the strip. Hidden during a slideshow and when the folder has only one picture. Remembered next time |
| Loupe | Hold `Z` over the picture: a round magnifier around the pointer at 4 times the current size (at least 400 %), showing the picture's own pixels sharply with the pixel under the pointer outlined. Handy with Fit-to-Screen. Gone when you let go of `Z` |
| Rate, colour-label, tag | `Alt+0` .. `Alt+5`, `Shift+0` .. `Shift+5`, `X`, as in the browser; the info bar shows the picture's marks |
| Crisp / sharp / smooth enlargement | `N` cycles crisp, sharp and smooth (retro pictures default to sharp, photos to smooth). Sharp keeps every pixel the same size when the zoom is not a whole number (for example with Fit-to-Screen or True TV aspect): the picture is enlarged with hard edges to the next whole number, then shrunk smoothly to the exact size, so only the screen pixel where two picture pixels meet is blended. Display only |
| Info bar | `I` (also shows the x, y and colour under the pointer, and the frame number of an animated GIF or WebP) |
| EXIF details (camera, lens, date, exposure, GPS ...) | `E`. Works for JPEG and TIFF photos, and for HEIC, AVIF, camera RAW and the other formats Windows' own decoders open, whenever the file holds these details |
| Animated GIF or WebP: pause / play, previous / next frame | `P`; `,` / `.`. Animated WebPs play in the viewer with their own frame times; each frame is decoded by Windows' WebP decoder and the frames are put together as browsers do. A very long or very large animation (more than about 384 MB of frames) shows its first frame |
| Save current picture as lossless PNG | Ctrl+S |
| Back to the browser / leave fullscreen | Esc |

Everywhere: **F11** fullscreen, **Ctrl+O** open, **F1** every key on one page, plus about / credits.

## Command-line audit

The folder audit can also run from a batch file, PowerShell or Windows Task Scheduler, with no window:

```
RetroGleek.exe --audit "D:\Retro\Amiga" --out "D:\Reports\amiga.html"
```

| Option | Meaning |
|---|---|
| `--audit <folder>` | The folder to audit (its pictures only, not subfolders). Required. |
| `--out <file>` | Where to write the report. Without it, the report goes into the audited folder with the usual name (`RetroGleek audit - <folder> - <date>.html`). |
| `--no-thumbs` | Leave the thumbnails out (a much smaller file). |
| `--csv` | Write a CSV file (for Excel or other tools) instead of the HTML page. |
| `--overwrite` | Replace the report if it already exists. Without it, an existing file is never touched. |

The **exit code** says how it went: **0** = every picture file opened, **1** = some could not be opened,
**2** = error (unknown option, folder missing or not on a local drive, report already exists, or it could not be
written). There are no dialog boxes, so a scheduled run never waits for a click. `settings.ini` is not used;
`marks.tsv` is read (never written), so the report includes your ratings, colour labels and tags.

RetroGleek is a Windows program, not a console program, so it prints nothing in the console window. A batch file
waits for it to finish (as does PowerShell's `Start-Process -Wait`); typed directly at a command prompt, it runs in
the background.

For console use, `build.bat` also builds **`RetroGleekCli.exe`**, a console companion made from the same source
files. It takes the same options (the folder can be given on its own: `RetroGleekCli.exe "D:\Retro\Amiga"`),
shows a progress count while it works, then prints a summary: totals, pictures by platform and every file that could
not be opened, with the reason. It always waits until it is done, and errors are explained in plain words.
`--quiet` turns the progress and summary off, `--help` lists the options. Exit codes are the same.

In a batch file:

```
RetroGleek.exe --audit "D:\Retro\Amiga" --no-thumbs --overwrite
if errorlevel 2 (echo Audit failed) else if errorlevel 1 (echo Some pictures could not be opened) else (echo All OK)
```

One report per subfolder:

```
for /d %%F in ("D:\Retro\*") do RetroGleek.exe --audit "%%F" --out "D:\Reports\%%~nxF.html" --overwrite
```

## Retro-computer formats (RECOIL)

- RECOIL supports 567 file extensions. They are **shown by default**; press **F8**, use the right-click menu, or start
  with `--no-retro` to hide them.
- Opening a retro picture directly turns them on for that folder. The viewer shows the platform name (for example
  "ZX Spectrum") in the info bar.
- RECOIL itself marks some extensions as too generic (`.cs`, `.obj`, `.map`, `.raw`, `.img` ...) or made-up. Those
  are never listed automatically, but still open when you open the file directly. `.scr` (ZX Spectrum) stays
  listed; `.fnt` and `.3` are excluded.
- Pictures that flicker between sub-pictures on the original hardware are blended into one image.
- Some formats keep their palette in a companion file; those are read only from the picture's own folder.
- `RECOIL.cs` is a **modified, machine-generated copy** of RECOIL's C# output (C# 5 syntax, lower memory caps). See
  [`THIRD-PARTY-NOTICES.txt`](THIRD-PARTY-NOTICES.txt). Regenerate it with `tools/downgrade_recoil.py`.

## Modern formats (WebP, AVIF, HEIC, JPEG XL, camera RAW)

RetroGleek opens these through the **decoders installed in Windows** (the Windows Imaging Component, reached through
WPF's imaging classes in the .NET Framework). It bundles no decoder of its own and adds no native code: the decoders
are Microsoft's, and Windows Update or the Microsoft Store keeps them patched. Image decoders read untrusted files and
are a favourite target for attackers (WebP's
[CVE-2023-4863](https://nvd.nist.gov/vuln/detail/CVE-2023-4863), for example), so a decoder bundled with an app,
which stays at the version shipped until the app is updated, was ruled out.

| Files | What Windows needs (free unless noted, from the Microsoft Store) |
|---|---|
| `.webp` | WebP Image Extensions (already installed on most PCs) |
| `.avif` | AV1 Video Extension (and HEIF Image Extensions) |
| `.heic` `.heif` `.hif` | HEIF Image Extensions and HEVC Video Extensions (HEVC is a small paid extension unless the PC came with it) |
| `.jxl` | JPEG XL Image Extension (Windows 11 24H2 or later) |
| `.jxr` `.wdp` `.hdp` | Nothing: JPEG XR is built into Windows |
| Camera RAW (`.dng` `.cr2` `.cr3` `.nef` `.arw` `.orf` `.rw2` `.raf` `.pef` `.srw` and more) | Raw Image Extension |

These files are always listed. If a PC has no decoder for one, its thumbnail and the viewer say which extension to
install; RetroGleek never opens the Store or goes online itself. Because the decoders are the PC's own, what opens
can differ from one PC to another.

Animated WebPs play in the viewer (`P` pauses, `,` / `.` step) and Ctrl+Shift+S saves every frame: RetroGleek reads the animation's frame layout from the file itself and has Windows' WebP decoder decode each frame, so it works whatever Windows does with animations. Thumbnails, the preview pane and Save as PNG show the first frame.

Limits: colour profiles are ignored, as for the other formats; `.raw` and
`.rwl` stay with RECOIL, which claims those extensions. They can be saved as PNG, put on contact sheets and checked by
the folder audit like any other picture.

Big JPEG photos get faster thumbnails the same way: Windows' JPEG decoder can decode straight to a half, a quarter or
an eighth of the full size, so a 50-megapixel photo no longer has to be decoded in full for a 200-pixel thumbnail.

## Antivirus note

RetroGleek is an unsigned executable with no reputation yet, and it does the kinds of things file managers do
(enumerates drives, copies, renames and deletes files). A few heuristic / machine-learning scanners may therefore flag
a freshly built copy as suspicious. Because the program is a few readable source files, the safest approach is to read
the source and build it yourself with `build.bat`.

## Project layout

| File | Purpose |
|---|---|
| `Program.cs` | Overview comment, version info and start-up (`Main`) |
| `Util.cs` | Shared helpers |
| `Imaging.cs` | Picture decoding, the RECOIL wrapper, lossless PNG export |
| `Thumbnails.cs` | Thumbnail cache and background decoding |
| `Controls.cs` | Rename dialog and the custom dark controls |
| `Canvas.cs` | The full-canvas viewer |
| `ThumbGrid.cs` | The thumbnail grid |
| `MainForm.Undo.cs` | Undo for renames, batch renames and moves |
| `BatchRename.cs` | Batch rename: pattern, preview and safe renaming |
| `Settings.cs` | Remembered settings (`settings.ini`) |
| `Audit.cs` | Folder audit: the offline HTML report |
| `ScreenEffects.cs` | Screen effect presets and the automatic choice of effects for each computer |
| `Marks.cs` | Ratings, colour labels and tags (`marks.tsv`) |
| `ContactSheet.cs` | Contact sheet: lossless PNG index sheets |
| `JpegRotate.cs` | Lossless JPEG changes: the turn on disk, and writing your rating into the photo |
| `RetroConvert.cs` | Converting pictures into retro formats (ZX Spectrum, C64 Koala, Atari ST Degas, Amiga IFF, MSX Screen 2 and 8), checked with RECOIL |
| `WinCodecs.cs` | Pictures decoded by Windows' own codecs (WebP, AVIF, HEIC, JPEG XL, camera RAW); fast thumbnails of big JPEGs |
| `MainForm.cs`, `MainForm.Files.cs` | The main window (one class in two files: layout and browsing; menus, file operations and keys) |
| `RECOIL.cs` | Bundled, modified C# build of RECOIL (retro formats) |
| `RetroGleek.manifest` | Windows manifest: high-DPI awareness, Windows 10/11 compatibility |
| `build.bat` | One-click build using the compiler included in Windows (`RetroGleek.exe` and the console companion `RetroGleekCli.exe`) |
| `LICENSE` | MIT License for RetroGleek's own code |
| `THIRD-PARTY-NOTICES.txt` | RECOIL's MIT license and a description of the modifications |
| `tools/downgrade_recoil.py` | Regenerates `RECOIL.cs` from a RECOIL checkout (needs the `fut` translator) |

## License

RetroGleek is Copyright (c) 2026 Mark Billson and released under the [MIT License](LICENSE).

The bundled `RECOIL.cs` is a separate work by Piotr Fusik under its own MIT License; see
`THIRD-PARTY-NOTICES.txt`. Keep both notices when you redistribute RetroGleek.

## Credits

Retro-computer picture decoding by **[RECOIL](https://github.com/pfusik/recoil)** by Piotr Fusik, used under the MIT
License. See `THIRD-PARTY-NOTICES.txt`.
