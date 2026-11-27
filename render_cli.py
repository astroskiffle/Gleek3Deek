#!/usr/bin/env python3
"""
Gleek3Deek render mode: make images from the command line, no clicking.

    python main.py render model.glb --out renders                       (depth, normal and Canny maps)
    python main.py render model.glb --out renders --maps all --view iso --fov 35 --size 1024
    python main.py render ./assets -r --out renders --maps depth,lines --view front
    python main.py render model.glb --out renders --sheet ortho4 --screenshot
    python main.py render model.glb --out renders --view iso --comfy "a red concept car, studio photo"

Maps are the same ones as Ctrl+F12 in the viewer (depth, normal, canny, lines); --sheet makes the Shift+F12
reference sheet; --screenshot makes a plain screenshot. A window is opened briefly off to the side while it renders.

It never changes or deletes a model. Images are written to --out (created if needed) and an existing image is never
replaced unless you pass --force. Your viewer settings are not touched.

Exit codes:  0 = done   2 = bad usage   3 = some files could not be rendered
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

MAP_KEYS = ["depth", "normal", "canny", "lines", "parts"]
VIEWS = ["front", "back", "left", "right", "top", "bottom", "iso"]
LEVELS = ["low", "mid", "high"]
SHEETS = ["ortho4", "hybrid4"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gleek3deek render", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Render depth / normal / Canny / line maps, a reference sheet or a screenshot of a model "
                    "(or every model in a folder) without opening the app's interface.",
        epilog="Maps: " + ", ".join(MAP_KEYS) + ", or 'all'. Views: " + ", ".join(VIEWS) + ".\n"
               "With none of --maps, --sheet or --screenshot given, depth, normal and canny are made.\n"
               "Files are named <model>_<map>.png. Existing files are kept (use --force to replace them).\n"
               "Exit codes: 0 done, 2 bad usage, 3 some files could not be rendered.")
    p.add_argument("path", help="a model file, or a folder of models")
    p.add_argument("--out", required=True, metavar="DIR", help="folder for the images (created if needed)")
    p.add_argument("-r", "--recursive", action="store_true", help="include sub-folders (symbolic links are never followed)")
    p.add_argument("--maps", default="", metavar="LIST", help="comma-separated: depth,normal,canny,lines,parts or all")
    p.add_argument("--sheet", choices=SHEETS, help="also make the reference sheet (ortho4 or hybrid4 layout)")
    p.add_argument("--sheet-cell", type=int, default=1024, metavar="PX", help="reference sheet: size of each view (default 1024)")
    p.add_argument("--sheet-bg", choices=["white", "grey"], default="white", help="reference sheet background")
    p.add_argument("--screenshot", action="store_true", help="also make a plain screenshot")
    p.add_argument("--view", choices=VIEWS, default="front", help="camera direction (default front)")
    p.add_argument("--fov", type=float, metavar="DEG", help="field of view in degrees (10-90, default 30)")
    p.add_argument("--ortho", action="store_true", help="orthographic projection instead of perspective")
    p.add_argument("--size", type=int, default=0, metavar="PX", help="long side of the maps in pixels (default: the window size)")
    p.add_argument("--window", default="1024x768", metavar="WxH", help="render window size (default 1024x768)")
    p.add_argument("--canny", choices=LEVELS, default="mid", help="Canny sensitivity: low = fewer lines")
    p.add_argument("--detail", choices=LEVELS, default="mid", help="line map: low = only sharp creases, high = soft creases too")
    p.add_argument("--no-cutout", action="store_true", help="do not skip see-through texture pixels in depth and normal maps")
    p.add_argument("--force", action="store_true", help="replace images that already exist")
    g = p.add_argument_group("AI render (needs a running ComfyUI server)")
    g.add_argument("--comfy", metavar="PROMPT", nargs="?", const="", default=None,
                   help="also send control map(s) to ComfyUI with this prompt; saves <model>_ai.png. With --comfy-workflow "
                        "the prompt may be left out to use the one saved in the workflow")
    g.add_argument("--comfy-url", default="http://127.0.0.1:8188", metavar="URL", help="ComfyUI address (default http://127.0.0.1:8188)")
    g.add_argument("--comfy-map", default="depth", metavar="MAPS",
                   help="which map(s) to send, comma-separated, in the order the workflow uses them (ref_image_0, "
                        "ref_image_1, ...): depth, normal, canny, lines, parts, screenshot (default depth)")
    g.add_argument("--comfy-negative", default="text, watermark, blurry, low quality", metavar="TEXT", help="what to avoid")
    g.add_argument("--comfy-quality", choices=["fast", "balanced", "best"], default="balanced",
                   help="fast = few-step Turbo checkpoint at 512 px; balanced = full steps, 768 px, detail pass (default); "
                        "best = 1024 px")
    g.add_argument("--comfy-strength", type=float, default=0.7, metavar="X", help="ControlNet strength (default 0.7)")
    g.add_argument("--comfy-end", type=float, default=0.85, metavar="X", help="ControlNet stops at this fraction of the steps (default 0.85)")
    g.add_argument("--comfy-steps", type=int, default=0, metavar="N", help="sampling steps (default: automatic)")
    g.add_argument("--no-detail-pass", action="store_true", help="skip the extra 1.5x detail pass")
    g.add_argument("--comfy-seed", type=int, default=1, metavar="N", help="seed (default 1, so a run can be repeated)")
    g.add_argument("--comfy-size", type=int, default=0, metavar="PX", help="long side of the AI picture (default: set by the quality)")
    g.add_argument("--comfy-checkpoint", metavar="NAME", help="checkpoint file name (default: a Turbo one if installed)")
    g.add_argument("--comfy-controlnet", metavar="NAME", help="ControlNet file name (default: chosen for the checkpoint)")
    g.add_argument("--comfy-set-size", action="store_true", help="apply --comfy-size to your own workflow (otherwise its saved size is used)")
    g.add_argument("--comfy-workflow", metavar="FILE", help="your own workflow saved with ComfyUI's 'Save (API Format)'")
    p.add_argument("--max-files", type=int, default=500, metavar="N", help="stop after this many models in a folder (default 500)")
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing except errors")
    return p


def parse_window(text: str):
    """'1024x768' -> (1024, 768). Raises ValueError for anything else or sizes outside 64..4096."""
    try:
        w, h = [int(x) for x in text.lower().replace("×", "x").split("x")]
    except Exception:
        raise ValueError("--window must look like 1024x768")
    if not (64 <= w <= 4096 and 64 <= h <= 4096):
        raise ValueError("--window sides must be between 64 and 4096")
    return w, h


def parse_maps(text: str):
    """'depth,lines' -> ['depth', 'lines'] in a fixed order; 'all' -> every map. Raises ValueError for unknown names."""
    names = [x.strip().lower() for x in text.split(",") if x.strip()]
    if "all" in names:
        return list(MAP_KEYS)
    bad = [n for n in names if n not in MAP_KEYS]
    if bad:
        raise ValueError("unknown map(s): " + ", ".join(bad) + "; choose from " + ", ".join(MAP_KEYS + ["all"]))
    return [k for k in MAP_KEYS if k in names]


def target_path(folder: str, stem: str, suffix: str, force: bool):
    """Where to write <stem>_<suffix>.png, or None when it already exists and --force was not given."""
    fn = os.path.join(folder, f"{stem}_{suffix}.png")
    return fn if (force or not os.path.exists(fn)) else None


def unique_stems(paths):
    """A file-name stem per model; two models with the same name get _2, _3 ... so their images never collide."""
    seen, out = {}, []
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        n = seen.get(stem, 0) + 1
        seen[stem] = n
        out.append(stem if n == 1 else f"{stem}_{n}")
    return out


def _say(args, text):
    if not args.quiet:
        print(text)


def _once():
    """A progress printer that only speaks when the message changes."""
    last = [None]

    def say(t):
        if t != last[0]:
            last[0] = t
            print("  " + t)
    return say


def _models(path: str, recursive: bool, limit: int):
    if os.path.isfile(path):
        return [path]
    from gallery import scan_assets
    found = []
    if recursive:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
            found += scan_assets(root)
            if len(found) >= limit:
                break
    else:
        found = scan_assets(path)
    return [p for p in found if not os.path.islink(p)][:limit]


def run(argv: list) -> int:
    from cli import _setup_streams
    _setup_streams()
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    try:
        win = parse_window(args.window)
        maps = parse_maps(args.maps)
    except ValueError as e:
        print("error: " + str(e), file=sys.stderr)
        return 2
    use_comfy = args.comfy is not None or bool(args.comfy_workflow)
    if not maps and not args.sheet and not args.screenshot and not use_comfy:
        maps = ["depth", "normal", "canny"]
    comfy = None
    if use_comfy:
        import comfy_client as cc
        cmaps = [k.strip() for k in args.comfy_map.split(",") if k.strip()]
        bad = [k for k in cmaps if k not in cc.MAP_LABELS]
        if bad or not cmaps:
            print("error: --comfy-map must be a comma-separated list of: " + ", ".join(cc.MAP_LABELS), file=sys.stderr)
            return 2
        if not args.comfy_workflow:
            if not (args.comfy or "").strip():
                print("error: --comfy needs a prompt (or use --comfy-workflow with a prompt saved in it)", file=sys.stderr)
                return 2
            cmaps = cmaps[:1]
        try:
            base = cc.normalize_url(args.comfy_url)
            info = cc.server_info(base)
            template = cc.load_template(args.comfy_workflow) if args.comfy_workflow else None
        except cc.ComfyError as e:
            print("error: " + str(e), file=sys.stderr)
            return 2
        ckpt = args.comfy_checkpoint or cc.pick_checkpoint(info["checkpoints"], args.comfy_quality)
        cnet = args.comfy_controlnet or cc.pick_controlnet(info["controlnets"], cmaps[0], ckpt)
        if template is None and (not ckpt or not cnet):
            print("error: the server has no checkpoint or ControlNet to use; name them with --comfy-checkpoint / --comfy-controlnet",
                  file=sys.stderr)
            return 2
        qual = cc.QUALITY[args.comfy_quality]
        comfy = {"cc": cc, "base": base, "template": template, "checkpoint": ckpt, "controlnet": cnet, "maps": cmaps,
                 "size": args.comfy_size or qual["size"], "hires": qual["hires"] and not args.no_detail_pass}
        _say(args, f"ComfyUI {info['version']} at {base}: {ckpt} + {cnet}")
    if args.fov is not None and not (10.0 <= args.fov <= 90.0):
        print("error: --fov must be between 10 and 90", file=sys.stderr)
        return 2
    if not os.path.exists(args.path):
        print(f"error: '{args.path}' does not exist", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(args.out)
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        print("error: --out is not a folder", file=sys.stderr)
        return 2
    models = _models(args.path, args.recursive, args.max_files)
    if not models:
        print("error: no models found", file=sys.stderr)
        return 2
    os.makedirs(out_dir, exist_ok=True)

    # the viewer remembers things in QSettings; keep a throw-away copy so this mode never changes the user's settings
    from PySide6.QtCore import QSettings
    tmp = tempfile.mkdtemp(prefix="gleek_render_")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tmp)
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    import numpy as np
    from formats import load_scene
    from viewer import Viewer

    app = QApplication(sys.argv[:1])
    v = Viewer()
    v.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
    v.resize(*win)
    v.move(0, 0)
    v.show()
    v.shot_scale = 1

    def pump(n=6):
        for _ in range(n):
            app.processEvents()

    def save(img, stem, suffix):
        fn = target_path(out_dir, stem, suffix, args.force)
        if fn is None:
            _say(args, f"  kept existing {stem}_{suffix}.png (use --force to replace)")
            return False
        ok = img.save(fn, "PNG")
        _say(args, f"  wrote {os.path.basename(fn)}" if ok else f"  could not write {fn}")
        return bool(ok)

    def to_qimage(arr):
        h, w, _ = arr.shape
        return QImage(np.ascontiguousarray(arr).data, w, h, 3 * w, QImage.Format_RGB888).copy()

    failed = 0
    for path, stem in zip(models, unique_stems(models)):
        _say(args, os.path.basename(path))
        try:
            actors = load_scene(path)
            v.show_model(actors, os.path.basename(path), path)
            pump()
            if args.fov is not None:
                v.set_fov(args.fov)
            v.set_view(args.view)
            if args.ortho:
                v.set_ortho(True)
            pump()
            v.rw.Render()
            if maps:
                made = v.render_control_maps({"maps": maps, "canny": args.canny, "lines": args.detail,
                                              "size": args.size, "cutout": not args.no_cutout})
                for key, arr in made.items():
                    wrote = save(to_qimage(arr), stem, key)
                    if key == "parts" and wrote and getattr(v, "last_parts_legend", None):
                        with open(os.path.join(out_dir, f"{stem}_parts.json"), "w", encoding="utf-8") as fh:
                            json.dump(v.last_parts_legend, fh, indent=2)
                        _say(args, f"  wrote {stem}_parts.json")
            if comfy:
                cc, keys = comfy["cc"], comfy["maps"]
                wanted = [k for k in keys if k != "screenshot"]
                arrs = (v.render_control_maps({"maps": wanted, "canny": args.canny, "lines": args.detail,
                                               "size": comfy["size"], "cutout": not args.no_cutout}) if wanted else {})
                images, dims = [], None
                for k in keys:
                    if k == "screenshot":
                        qi = v.grab_image()
                        if qi is None or qi.isNull():
                            raise RuntimeError("the viewport could not be captured")
                        dims = dims or (qi.width(), qi.height())
                    else:
                        qi = to_qimage(arrs[k])
                        dims = dims or (qi.width(), qi.height())
                    buf = QBuffer()
                    buf.open(QIODevice.WriteOnly)
                    qi.save(buf, "PNG")
                    images.append((k, bytes(buf.data())))
                fw, fh = cc.fit_size(dims[0], dims[1], comfy["size"])
                opt = {"checkpoint": comfy["checkpoint"], "controlnet": comfy["controlnet"], "map": keys[0],
                       "prompt": args.comfy or "", "negative": args.comfy_negative, "seed": args.comfy_seed,
                       "width": fw, "height": fh, "strength": args.comfy_strength, "end_percent": args.comfy_end,
                       "steps": args.comfy_steps, "hires": comfy["hires"]}
                png = cc.generate(comfy["base"], images, opt, comfy["template"],
                                  None if args.quiet else _once(), args.comfy_set_size)
                ai = QImage.fromData(QByteArray(png))
                if ai.isNull():
                    raise RuntimeError("ComfyUI returned something that is not an image")
                save(ai, stem, "ai")
            if args.sheet:
                sheet, _cells = v.render_reference_sheet({"layout": args.sheet, "bg": args.sheet_bg,
                                                          "cell": args.sheet_cell, "labels": False, "single": False})
                save(sheet, stem, "sheet")
            if args.screenshot:
                shot = v.grab_image()
                if shot is None:
                    raise RuntimeError("the viewport could not be captured")
                save(shot, stem, "screenshot")
        except Exception as e:
            failed += 1
            print(f"  failed: {e}", file=sys.stderr)
    try:
        v.shutdown()
    except Exception:
        pass
    v.close()
    return 3 if failed else 0
