#!/usr/bin/env python3
"""
Gleek3Deek command-line mode: audit 3D assets from a console and print the results as text or JSON.

    python cli.py model.glb --all
    python cli.py ./assets --recursive --mesh --textures --fail-on holes,flipped --json --report audit.json
    python main.py model.glb --info          (the same thing; any option starting with "-" selects this mode)

This mode is READ-ONLY. It never modifies, moves, copies or deletes an asset. The only file it can write is
the optional --report file, which will not overwrite an existing file (unless --force), will not follow
a symbolic link, and will not be written inside the folder being scanned.

Exit codes:  0 = everything passed   1 = a --fail-on / --max-* check failed
             2 = bad usage (wrong path, bad option, unsafe --report)   3 = some files could not be loaded
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from formats import ALL_EXTS, NO_MESH, UNSUPPORTED_PROPRIETARY, LoadError, asset_ext, human_size, load_scene
from analysis import AUDIT_SECTIONS, MESH_TESTS, UNITS, UV_TESTS, audit_model, fmt_num

FAIL_ON = {
    "holes": "open (boundary) edges",
    "nonmanifold": "non-manifold edges",
    "degenerate": "zero-area triangles",
    "flipped": "inconsistent winding or inside-out pieces",
    "duplicates": "duplicate faces",
    "open": "mesh is not watertight",
    "uv-missing": "a part without UVs",
    "uv-overlap": "overlapping or stacked UV islands",
    "uv-bounds": "UVs outside the 0 to 1 square",
    "uv-flipped": "flipped or mirrored UVs",
    "npot": "a texture that is not a power of two",
}


# ----- discovery --------------------------------------------------------------------------------
def find_files(root: str, recursive: bool, max_files: int):
    """(files to audit, [(path, reason it was skipped)]). Never follows symbolic links."""
    files, skipped = [], []
    if os.path.isfile(root):
        return [root], skipped
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if recursive:
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d)))
        else:
            dirnames[:] = []
        for fn in sorted(filenames, key=str.lower):
            p = os.path.join(dirpath, fn)
            ext = asset_ext(fn)
            if ext not in ALL_EXTS:
                continue
            if os.path.islink(p):
                skipped.append((p, "symbolic link"))
            elif ext in NO_MESH:
                skipped.append((p, NO_MESH[ext] + ": no surface to audit"))
            elif ext in UNSUPPORTED_PROPRIETARY:
                skipped.append((p, UNSUPPORTED_PROPRIETARY[ext] + ": proprietary format"))
            elif len(files) >= max_files:
                skipped.append((p, f"over the --max-files limit ({max_files})"))
            else:
                files.append(p)
    return files, skipped


# ----- checks -----------------------------------------------------------------------------------
def run_checks(res: dict, fail_on: set, lim: dict) -> list:
    """Reasons this file fails the requested checks (an empty list means it passed)."""
    out = []
    mesh, uv, tex = res.get("mesh") or {}, res.get("uv") or {}, res.get("textures") or {}
    t = mesh.get("tests", {})
    if "holes" in fail_on and mesh.get("boundary_edges"):
        out.append(f"holes: {mesh['boundary_edges']:,} open edges")
    if "nonmanifold" in fail_on and mesh.get("nonman_edges"):
        out.append(f"nonmanifold: {mesh['nonman_edges']:,} edges")
    if "degenerate" in fail_on and t.get("degen"):
        out.append(f"degenerate: {t['degen']:,} zero-area triangles")
    if "flipped" in fail_on and (t.get("winding") or t.get("inverted")):
        out.append(f"flipped: {t.get('winding', 0):,} triangles with inconsistent winding, "
                   f"{mesh.get('inverted_pieces', 0)} inside-out piece(s)")
    if "duplicates" in fail_on and t.get("dupface"):
        out.append(f"duplicates: {t['dupface']:,} duplicate faces")
    if "open" in fail_on and mesh and not mesh.get("watertight", True):
        out.append("open: the mesh is not watertight")
    if "uv-missing" in fail_on and uv and not uv.get("has_uv"):
        out.append("uv-missing: no UV coordinates")
    ut = uv.get("tests", {}) if uv else {}
    if "uv-overlap" in fail_on and (ut.get("overlap") or ut.get("stack")):
        out.append(f"uv-overlap: {ut.get('overlap', 0):,} overlapping and {ut.get('stack', 0):,} stacked triangles")
    if "uv-bounds" in fail_on and ut.get("oob"):
        out.append(f"uv-bounds: {ut['oob']:,} triangles outside 0 to 1")
    if "uv-flipped" in fail_on and (ut.get("flip") or ut.get("mirror")):
        out.append(f"uv-flipped: {ut.get('flip', 0):,} flipped and {ut.get('mirror', 0):,} mirrored triangles")
    if "npot" in fail_on and any(e["non_power_of_two"] for e in tex.get("entries", [])):
        out.append("npot: a texture is not a power of two")
    tris = res["info"].get("tris", 0)
    if lim.get("triangles") is not None and tris > lim["triangles"]:
        out.append(f"max-triangles: {tris:,} > {lim['triangles']:,}")
    if lim.get("texture_mb") is not None and tex and tex["vram_bytes"] / 1048576.0 > lim["texture_mb"]:
        out.append(f"max-texture-mb: {tex['vram_bytes'] / 1048576.0:.1f} > {lim['texture_mb']:g}")
    if lim.get("texture_px") is not None and tex and tex["largest_side"] > lim["texture_px"]:
        out.append(f"max-texture-px: {tex['largest_side']} > {lim['texture_px']}")
    if lim.get("materials") is not None and res["materials"]["materials"] > lim["materials"]:
        out.append(f"max-materials: {res['materials']['materials']} > {lim['materials']}")
    return out


# ----- text output ------------------------------------------------------------------------------
def _n(v) -> str:
    return f"{int(v):,}"


def format_text(res: dict, want: set) -> str:
    u = res["units"]["report"]
    info, mats = res["info"], res["materials"]
    L = [f"{os.path.basename(res['file'])}  [{info['format']}, {info['size']}]"]

    def row(label, text):
        L.append(f"  {label:<10} {text}")

    bits = [f"{_n(info['parts'])} part{'s' if info['parts'] != 1 else ''}", f"{_n(info['tris'])} triangles",
            f"{_n(info['verts'])} vertices", f"{mats['materials']} material{'s' if mats['materials'] != 1 else ''}",
            f"{info['texs']} texture{'s' if info['texs'] != 1 else ''}", "UVs: " + ("yes" if info["uvs"] else "no")]
    row("Model", " · ".join(bits))
    if info.get("dims"):
        d = info["dims"]
        row("Size", f"{fmt_num(d[0])} × {fmt_num(d[1])} × {fmt_num(d[2])} {u}  (bounding box)")

    tx = res.get("textures")
    if tx is not None:
        if not tx["entries"]:
            row("Textures", "none (colours only)")
        else:
            row("Textures", f"{tx['unique_images']} unique image{'s' if tx['unique_images'] != 1 else ''} · "
                            f"≈ {human_size(tx['vram_bytes'])} in GPU memory (≈ {human_size(tx['vram_compressed_bytes'])} compressed)")
            for e in tx["entries"]:
                flags = (["not a power of two"] if e["non_power_of_two"] else []) + (["very large"] if e["very_large"] else []) \
                    + (["repeat, counted once"] if e["repeat_of_earlier_entry"] else [])
                L.append(f"    {e['role']:<26} {e['width']}×{e['height']}  {e['bits']}-bit {e['channels']}ch  "
                         f"{e['colour_space_inferred']} (inferred)  ≈ {human_size(e['vram_bytes'])}"
                         + (f"  [{', '.join(flags)}]" if flags else ""))

    me = res.get("mesh")
    if me is not None:
        if not me:
            row("Mesh", "no polygon surface to analyse")
        else:
            row("Mesh", ("watertight" if me["watertight"] else "NOT watertight") + f" · {_n(me['pieces'])} piece(s) · "
                f"{_n(me['loose'])} loose vertices · {_n(me['dup_verts'])} vertices share a position")
            found = [(lab, me["tests"][k]) for k, lab, *_r in MESH_TESTS if me["tests"].get(k)]
            L.append(f"    open edges {_n(me['boundary_edges'])} · non-manifold edges {_n(me['nonman_edges'])}")
            if found:
                L.append("    triangles failing: " + " · ".join(f"{lab.lower()} {_n(n)}" for lab, n in found))
            else:
                L.append("    no failing triangles")

    uv = res.get("uv")
    if uv is not None:
        if not uv["has_uv"]:
            row("UV", "no UV coordinates")
        else:
            row("UV", f"{_n(uv['tris'])} triangles · {_n(uv['islands'])} islands"
                      + ("" if uv["island_tests_ran"] else " · island tests skipped (mesh too large)"))
            found = [(lab, uv["tests"][k]) for k, lab, *_r in UV_TESTS if uv["tests"].get(k)]
            L.append("    triangles failing: " + (" · ".join(f"{lab.lower()} {_n(n)}" for lab, n in found) if found else "none"))
            th = uv["thresholds"]
            L.append(f"    texel density: {_n(uv['density_low'])} below ×{th['dens_low']:g} and {_n(uv['density_high'])} above "
                     f"×{th['dens_high']:g} of the median · {_n(uv['stretched'])} triangles stretched past {th['stretch']:g}")

    ms = res.get("measure")
    if ms is not None:
        if not ms:
            row("Measure", "no polygon surface to measure")
        else:
            b, o = ms["bounding_box_size"], ms["oriented_box_size"]
            row("Measure", f"box {fmt_num(b[0])} × {fmt_num(b[1])} × {fmt_num(b[2])} {u} · oriented "
                           f"{fmt_num(o[0])} × {fmt_num(o[1])} × {fmt_num(o[2])} {u}")
            vol = (f"{fmt_num(ms['volume'])} {u}³ (≈ {fmt_num(ms['volume_litres'])} litres)" if ms["volume"] is not None
                   else "not available (no closed part)")
            c = ms["centre_of_mass"]
            L.append(f"    area {fmt_num(ms['surface_area'])} {u}² · volume {vol}")
            L.append(f"    centre of mass {fmt_num(c[0])}, {fmt_num(c[1])}, {fmt_num(c[2])} {u}"
                     + ("" if ms["centre_of_mass_basis"] == "volume" else " (of the surface)")
                     + (f" · {ms['open_parts']} open part(s) not in the volume" if ms["open_parts"] else ""))

    lo = res.get("lod")
    if lo is not None:
        t0 = lo["original_triangles"] or 1
        row("LOD", f"original {_n(lo['original_triangles'])} · " + " · ".join(
            f"{k}% target → {_n(v)} ({100.0 * v / t0:.0f}%)" for k, v in lo["levels"].items()) + " triangles")

    fails = res.get("failed_checks")
    if fails is not None:
        if fails:
            row("Checks", "FAILED")
            L.extend("    - " + f for f in fails)
        else:
            row("Checks", "passed")
    return "\n".join(L)


def format_summary(results: list, skipped: list) -> str:
    L = ["", "Summary", "-------"]
    w = max([len(os.path.basename(r["file"])) for r in results] + [4])
    L.append(f"{'File':<{w}}  {'Triangles':>12}  Result")
    for r in results:
        name = os.path.basename(r["file"])
        if r["status"] != "ok":
            L.append(f"{name:<{w}}  {'':>12}  ERROR: {r['error'].splitlines()[0][:90]}")
        else:
            f = r.get("failed_checks")
            res = "ok" if not f else "FAILED: " + "; ".join(x.split(":")[0] for x in f)
            L.append(f"{name:<{w}}  {r['info']['tris']:>12,}  {res}")
    n_ok = sum(1 for r in results if r["status"] == "ok" and not r.get("failed_checks"))
    n_fail = sum(1 for r in results if r["status"] == "ok" and r.get("failed_checks"))
    n_err = sum(1 for r in results if r["status"] != "ok")
    L.append(f"{len(results)} file(s): {n_ok} passed, {n_fail} failed checks, {n_err} could not be loaded"
             + (f", {len(skipped)} skipped" if skipped else ""))
    for p, why in skipped:
        L.append(f"  skipped {os.path.basename(p)}: {why}")
    return "\n".join(L)


# ----- running ----------------------------------------------------------------------------------
def audit_file(path: str, want: set, units: tuple) -> dict:
    """Load one file and audit it. Never raises: problems come back as status 'error'."""
    t0 = time.time()
    try:
        actors = load_scene(path)
        res = audit_model(actors, path, want, units)
        res["status"] = "ok"
    except LoadError as e:
        res = {"file": path, "status": "error", "error": str(e)}
    except MemoryError:
        res = {"file": path, "status": "error", "error": "Out of memory while loading this asset."}
    except Exception as e:
        res = {"file": path, "status": "error", "error": f"{type(e).__name__}: {e}"}
    res["seconds"] = round(time.time() - t0, 2)
    return res


def audit_isolated(path: str, argv_opts: list, timeout: int) -> dict:
    """Audit in a child process, so a file that crashes the loader or runs forever cannot stop the batch."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--worker", path] + argv_opts
    else:
        cmd = [sys.executable, os.path.abspath(__file__), "--worker", path] + argv_opts
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"file": path, "status": "error", "error": f"Timed out after {timeout} s", "seconds": float(timeout)}
    for line in reversed(p.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    why = (p.stderr or "").strip().splitlines()
    return {"file": path, "status": "error", "seconds": round(time.time() - t0, 2),
            "error": f"The loader stopped unexpectedly (exit code {p.returncode})" + (": " + why[-1][:200] if why else "")}


def parse_units(text: str):
    keys = [k for k, _l, _f in UNITS]
    src, _, disp = text.partition(":")
    disp = disp or src
    if src not in keys or disp not in keys:
        raise ValueError(f"units must be one of {', '.join(keys)} (for example m or mm:cm), not '{text}'")
    return src, disp


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gleek3deek", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Audit 3D assets from the command line (read-only). Give a file or a folder.",
        epilog="Sections (default: --info only):\n"
               "  --info --textures --mesh --uv --measure --lod, or --all (everything except --lod)\n\n"
               "--fail-on takes a comma-separated list of: " + ", ".join(FAIL_ON) + "\n\n"
               "Exit codes: 0 passed, 1 a check failed, 2 bad usage, 3 a file could not be loaded.\n"
               "This mode never changes, moves, copies or deletes assets.")
    p.add_argument("path", help="a model file, or a folder of models")
    p.add_argument("-r", "--recursive", action="store_true", help="include sub-folders (symbolic links are never followed)")
    for s, h in (("info", "counts and size (always shown)"), ("textures", "texture sizes and estimated GPU memory"),
                 ("mesh", "mesh integrity: holes, bad edges, flipped faces, pieces"),
                 ("uv", "UV tests, texel density and stretch"), ("measure", "size, area, volume, centre of mass"),
                 ("lod", "triangle counts after simplifying to 50%%, 25%% and 10%% (slow)")):
        p.add_argument("--" + s, action="store_true", help=h)
    p.add_argument("--all", action="store_true", help="info, textures, mesh, uv and measure")
    p.add_argument("--units", default="m", metavar="SRC[:SHOWN]",
                   help="what one model unit means, and the unit to report in, e.g. m, mm or mm:cm (default m). "
                        "Choices: " + ", ".join(k for k, _l, _f in UNITS))
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("--report", metavar="FILE", help="also write the output to this new file (never overwrites unless --force)")
    p.add_argument("--force", action="store_true", help="allow --report to replace an existing file")
    p.add_argument("--fail-on", default="", metavar="LIST", help="checks that make the exit code 1 (see the list below)")
    p.add_argument("--max-triangles", type=int, metavar="N", help="fail a file with more triangles than this")
    p.add_argument("--max-texture-mb", type=float, metavar="MB", help="fail a file whose textures need more estimated GPU memory")
    p.add_argument("--max-texture-px", type=int, metavar="PX", help="fail a file with a texture larger than this on either side")
    p.add_argument("--max-materials", type=int, metavar="N", help="fail a file with more distinct materials than this")
    p.add_argument("--max-files", type=int, default=2000, metavar="N", help="stop after this many files in a folder (default 2000)")
    p.add_argument("--max-size-mb", type=float, default=1024.0, metavar="MB", help="skip files larger than this (default 1024)")
    p.add_argument("--timeout", type=int, default=300, metavar="SEC", help="per-file time limit in folder mode (default 300)")
    p.add_argument("--no-isolate", action="store_true", help="folder mode: load files in this process (faster, but a crash stops the run)")
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing except errors (use with --report or the exit code)")
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return p


def _safe_report_target(report: str, scanned_root: str, force: bool):
    """Return an error message when writing the report would be unsafe, else None."""
    target = os.path.abspath(report)
    if os.path.islink(report):
        return "the report path is a symbolic link"
    if os.path.isdir(target):
        return "the report path is a folder"
    if not os.path.isdir(os.path.dirname(target)):
        return "the report's folder does not exist"
    if os.path.exists(target) and not force:
        return "that file already exists (use --force to replace it)"
    root = os.path.realpath(scanned_root)
    root_dir = root if os.path.isdir(root) else os.path.dirname(root)
    real_target = os.path.join(os.path.realpath(os.path.dirname(target)), os.path.basename(target))
    try:
        inside = os.path.commonpath([root_dir, real_target]) == root_dir
    except ValueError:                                # different drives
        inside = False
    if inside and os.path.isdir(root):
        return "the report would be written inside the folder being scanned"
    if real_target == root:
        return "the report path is the model file itself"
    return None


def _setup_streams():
    """UTF-8 output (the text uses × and ≈), and a console for a windowed Windows exe started from a terminal."""
    if sys.stdout is None and os.name == "nt":
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run(argv: list) -> int:
    _setup_streams()
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    want = {s for s in AUDIT_SECTIONS if getattr(args, s, False)}
    if args.all:
        want |= {"info", "textures", "mesh", "uv", "measure"}
    want.add("info")
    try:
        units = parse_units(args.units)
    except ValueError as e:
        print("error: " + str(e), file=sys.stderr)
        return 2
    fail_on = {x.strip() for x in args.fail_on.split(",") if x.strip()}
    if fail_on - set(FAIL_ON):
        print("error: unknown --fail-on value(s): " + ", ".join(sorted(fail_on - set(FAIL_ON))) +
              "\n       choose from: " + ", ".join(FAIL_ON), file=sys.stderr)
        return 2
    # checks need their data: switch the sections on automatically
    if fail_on & {"holes", "nonmanifold", "degenerate", "flipped", "duplicates", "open"}:
        want.add("mesh")
    if fail_on & {"uv-missing", "uv-overlap", "uv-bounds", "uv-flipped"}:
        want.add("uv")
    if fail_on & {"npot"} or args.max_texture_mb is not None or args.max_texture_px is not None:
        want.add("textures")
    lim = {"triangles": args.max_triangles, "texture_mb": args.max_texture_mb,
           "texture_px": args.max_texture_px, "materials": args.max_materials}
    checking = bool(fail_on) or any(v is not None for v in lim.values())

    if args.worker:                                   # child process: one file, one JSON line
        res = audit_file(args.path, want, units)
        sys.stdout.write(json.dumps(res) + "\n")
        return 0

    if not os.path.exists(args.path):
        print(f"error: '{args.path}' does not exist", file=sys.stderr)
        return 2
    if args.report:
        why = _safe_report_target(args.report, args.path, args.force)
        if why:
            print("error: cannot write the report: " + why, file=sys.stderr)
            return 2

    files, skipped = find_files(args.path, args.recursive, args.max_files)
    if os.path.isfile(args.path):
        pass
    elif not files:
        print("error: no supported 3D files found" + ("" if args.recursive else " (add --recursive to include sub-folders)"),
              file=sys.stderr)
        return 2
    batch = os.path.isdir(args.path)
    results, texts = [], []
    # options handed to child processes: only the ones that change the audit itself
    child = ["--units", args.units] + [f"--{s}" for s in sorted(want) if s != "info"]
    for i, f in enumerate(files):
        try:
            too_big = os.path.getsize(f) > args.max_size_mb * 1048576.0
        except OSError:
            too_big = False
        if too_big:
            res = {"file": f, "status": "error", "error": f"Skipped: larger than --max-size-mb ({args.max_size_mb:g})", "seconds": 0.0}
        elif batch and not args.no_isolate:
            res = audit_isolated(f, child, args.timeout)
        else:
            res = audit_file(f, want, units)
        if res["status"] == "ok" and checking:
            res["failed_checks"] = run_checks(res, fail_on, lim)
        results.append(res)
        if not args.json:
            block = format_text(res, want | ({"checks"} if checking else set())) if res["status"] == "ok" \
                else f"{os.path.basename(f)}\n  ERROR: {res['error']}"
            texts.append(block)
            if not args.quiet:
                print(block + ("\n" if batch else ""), flush=True)

    if args.json:
        out = json.dumps({"files": results, "skipped": [{"file": p, "reason": w} for p, w in skipped]}, indent=2)
        if not args.quiet:
            print(out)
    else:
        out = "\n\n".join(texts) + ("\n" + format_summary(results, skipped) if batch else "")
        if batch and not args.quiet:
            print(format_summary(results, skipped))
    if args.report:
        try:
            with open(args.report, "w" if args.force else "x", encoding="utf-8") as fh:
                fh.write(out + "\n")
        except OSError as e:
            print(f"error: could not write the report: {e}", file=sys.stderr)
            return 2

    if any(r.get("failed_checks") for r in results):
        return 1
    if any(r["status"] != "ok" for r in results):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
