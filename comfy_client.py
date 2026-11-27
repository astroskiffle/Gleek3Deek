"""
A small client for a ComfyUI server (local or on your network). Standard library only, no Qt.

Gleek3Deek sends one of its control maps (depth, normal, Canny, lines or part-ID) to ComfyUI together with a
prompt, and gets the generated picture back. ComfyUI does the AI work; nothing here is bundled or downloaded.

The graph that is sent is either
  - the built-in one (checkpoint -> ControlNet -> sampler), chosen for SDXL Turbo style or ordinary checkpoints, or
  - your own workflow saved from ComfyUI with "Save (API Format)". If it has no placeholders it is filled in
    automatically: Load Image nodes get the maps (in order, so ref_image_0 is the first map), the positive prompt text
    is replaced (or kept if the Prompt box is empty), samplers get the seed. Extra maps are added as more Load Image
    nodes on a "Set Reference Multi Latent" style node. Or mark the values yourself with placeholders:
      "{{image}}" (uploaded file name)  "{{prompt}}"  "{{negative}}"  "{{seed}}"  "{{width}}"  "{{height}}"
      "{{strength}}"  "{{checkpoint}}"  "{{controlnet}}"
    A value that is exactly a placeholder is replaced and keeps its type (a number stays a number).
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:8188"

# Gleek3Deek map -> the mode name of a "union" ControlNet (xinsir promax and similar)
UNION_TYPES = {"depth": "depth", "normal": "normal", "canny": "canny/lineart/anime_lineart/mlsd",
               "lines": "canny/lineart/anime_lineart/mlsd", "parts": "segment",
               "screenshot": "auto"}
MAP_LABELS = {"depth": "Depth", "normal": "Normal", "canny": "Canny edges", "lines": "Line map", "parts": "Part IDs",
              "screenshot": "Screenshot (the view as shown)"}


class ComfyError(Exception):
    """Anything that stops a generation; the message is meant to be shown to the person."""


class Cancelled(ComfyError):
    pass


def normalize_url(text: str) -> str:
    t = (text or "").strip().rstrip("/")
    if not t:
        t = DEFAULT_URL
    if "://" not in t:
        t = "http://" + t
    p = urllib.parse.urlparse(t)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ComfyError("The server address must look like http://127.0.0.1:8188")
    return t


def _open(req, timeout):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:1500]
        except Exception:
            pass
        raise ComfyError(f"ComfyUI answered {e.code}: {_short_error(body) or e.reason}") from None
    except (urllib.error.URLError, OSError) as e:
        raise ComfyError(f"Could not reach ComfyUI at {req.full_url.split('/')[2]}: {getattr(e, 'reason', e)}") from None


def _short_error(body: str) -> str:
    """ComfyUI's JSON error (node_errors) boiled down to a sentence."""
    try:
        j = json.loads(body)
    except ValueError:
        return body.strip()[:300]
    parts = []
    err = j.get("error")
    if isinstance(err, dict):
        parts.append(str(err.get("message") or err.get("type") or ""))
        if err.get("details"):
            parts.append(str(err["details"]))
    for nid, ne in (j.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            parts.append(f"node {nid} ({ne.get('class_type', '?')}): {e.get('message', '')} {e.get('details', '')}".strip())
    return "; ".join(p for p in parts if p)[:600] or body.strip()[:300]


def get_json(base: str, path: str, timeout: float = 10.0):
    with _open(urllib.request.Request(base + path), timeout) as r:
        try:
            return json.loads(r.read().decode("utf-8"))
        except ValueError:
            raise ComfyError("That address answered, but it does not look like ComfyUI") from None


def server_info(base: str) -> dict:
    """{"version", "gpu", "vram_gb", "checkpoints": [...], "controlnets": [...]} from a running server."""
    stats = get_json(base, "/system_stats")
    dev = (stats.get("devices") or [{}])[0]

    def combo(node, field):
        try:
            return list(get_json(base, f"/object_info/{node}")[node]["input"]["required"][field][0])
        except (KeyError, IndexError, TypeError):
            return []
    return {"version": (stats.get("system") or {}).get("comfyui_version", ""),
            "gpu": dev.get("name", ""), "vram_gb": round(float(dev.get("vram_total", 0)) / 1e9, 1),
            "checkpoints": combo("CheckpointLoaderSimple", "ckpt_name"),
            "controlnets": combo("ControlNetLoader", "control_net_name")}


def _multipart(fields: dict, file_field: str, file_name: str, data: bytes):
    boundary = "----gleek" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
                "Content-Type: image/png\r\n\r\n").encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def upload_image(base: str, png: bytes, name: str) -> str:
    body, ctype = _multipart({"overwrite": "true", "type": "input"}, "image", name, png)
    req = urllib.request.Request(base + "/upload/image", data=body, headers={"Content-Type": ctype}, method="POST")
    with _open(req, 60) as r:
        try:
            return str(json.loads(r.read().decode("utf-8"))["name"])
        except (ValueError, KeyError):
            raise ComfyError("ComfyUI did not accept the uploaded image") from None


def pick_default(names: list, *needles: str) -> str:
    """The first name containing every needle (case-insensitive), else ''."""
    for n in names:
        low = n.lower()
        if all(x in low for x in needles):
            return n
    return ""


def is_turbo(ckpt: str) -> bool:
    low = ckpt.lower()
    return any(x in low for x in ("turbo", "lightning", "lcm", "hyper"))


def pick_controlnet(controlnets: list, map_key: str, ckpt: str) -> str:
    """A sensible installed ControlNet for a map: the union model if there is one, else a name match."""
    sdxl = any(x in ckpt.lower() for x in ("xl", "pony", "playground", "turbo", "juggernaut", "illustrious"))
    union = pick_default(controlnets, "union")
    if union and sdxl:
        return union
    want = {"depth": ("depth",), "normal": ("normal",), "canny": ("canny",), "lines": ("lineart", "canny"),
            "parts": ("seg",)}.get(map_key, ())
    for w in want:
        for n in controlnets:
            low = n.lower()
            if w in low and (("sd15" in low or "v11" in low) != sdxl):
                return n
    return union or (controlnets[0] if controlnets else "")


# Quality presets: what "Fast" / "Balanced" / "Best" mean for a checkpoint that is (or is not) a few-step Turbo model.
QUALITY = {
    "fast": {"label": "Fast (few steps, 512 px)", "size": 512, "hires": False},
    "balanced": {"label": "Balanced (full steps, 768 px, detail pass)", "size": 768, "hires": True},
    "best": {"label": "Best (full steps, 1024 px, detail pass)", "size": 1024, "hires": True},
}


def pick_checkpoint(checkpoints: list, quality: str) -> str:
    """Fast: a Turbo / Lightning checkpoint if installed. Otherwise a good full-step SDXL one."""
    if quality == "fast":
        t = pick_default(checkpoints, "turbo")
        if t:
            return t
    for needle in ("juggernautxl", "realvisxl_v", "realvisxl", "zavychroma", "sd_xl_base"):
        for n in checkpoints:
            if needle in n.lower() and "refiner" not in n.lower() and not is_turbo(n):
                return n
    return pick_default(checkpoints, "xl") or (checkpoints[0] if checkpoints else "")


def build_workflow(opt: dict, image_name: str) -> dict:
    """The built-in ComfyUI graph in API format. opt: checkpoint, controlnet, map, prompt, negative, seed, width,
    height, strength, end_percent, steps (0 = automatic), cfg (0 = automatic), hires (extra detail pass),
    hires_scale, hires_denoise."""
    ckpt, cn = opt["checkpoint"], opt["controlnet"]
    turbo = is_turbo(ckpt)
    steps = int(opt.get("steps") or (4 if turbo else 25))
    cfg = float(opt.get("cfg") or (1.0 if turbo else 6.0))
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": opt["prompt"]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": opt.get("negative", "")}},
        "4": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": cn}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image_name}},
    }
    cn_out = ["4", 0]
    if "union" in cn.lower():
        wf["5"] = {"class_type": "SetUnionControlNetType",
                   "inputs": {"control_net": ["4", 0], "type": UNION_TYPES.get(opt.get("map", "depth"), "auto")}}
        cn_out = ["5", 0]
    wf["7"] = {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["2", 0], "negative": ["3", 0], "control_net": cn_out, "image": ["6", 0],
                          "strength": float(opt.get("strength", 0.7)), "start_percent": 0.0,
                          "end_percent": float(opt.get("end_percent", 0.85)), "vae": ["1", 2]}}
    wf["8"] = {"class_type": "EmptyLatentImage",
               "inputs": {"width": int(opt["width"]), "height": int(opt["height"]), "batch_size": 1}}
    seed = int(opt.get("seed", 0))
    if turbo:
        wf["9"] = {"class_type": "SDTurboScheduler", "inputs": {"model": ["1", 0], "steps": steps, "denoise": 1.0}}
        wf["10"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}}
        wf["11"] = {"class_type": "SamplerCustom",
                    "inputs": {"model": ["1", 0], "add_noise": True, "noise_seed": seed, "cfg": cfg,
                               "positive": ["7", 0], "negative": ["7", 1], "sampler": ["10", 0], "sigmas": ["9", 0],
                               "latent_image": ["8", 0]}}
        latent = ["11", 0]
    else:
        wf["11"] = {"class_type": "KSampler",
                    "inputs": {"model": ["1", 0], "seed": seed, "steps": steps, "cfg": cfg,
                               "sampler_name": "dpmpp_2m", "scheduler": "karras", "positive": ["7", 0],
                               "negative": ["7", 1], "latent_image": ["8", 0], "denoise": 1.0}}
        latent = ["11", 0]
    if opt.get("hires"):
        # a second, gentler pass at a larger size adds fine detail; the VAE is run in tiles to stay inside small GPUs
        wf["14"] = {"class_type": "LatentUpscaleBy",
                    "inputs": {"samples": latent, "upscale_method": "bislerp", "scale_by": float(opt.get("hires_scale", 1.5))}}
        wf["15"] = {"class_type": "KSampler",
                    "inputs": {"model": ["1", 0], "seed": seed + 1, "steps": 4 if turbo else max(10, steps // 2),
                               "cfg": cfg, "sampler_name": "euler_ancestral" if turbo else "dpmpp_2m",
                               "scheduler": "simple" if turbo else "karras", "positive": ["2", 0], "negative": ["3", 0],
                               "latent_image": ["14", 0], "denoise": float(opt.get("hires_denoise", 0.5 if turbo else 0.45))}}
        latent = ["15", 0]
    wf["12"] = {"class_type": "VAEDecodeTiled",
                "inputs": {"samples": latent, "vae": ["1", 2], "tile_size": 512, "overlap": 64,
                           "temporal_size": 64, "temporal_overlap": 8}}
    wf["13"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "gleek3deek", "images": ["12", 0]}}
    return wf


def fill_template(template, values: dict):
    """Copy of a workflow (dict / list / scalar) with '{{name}}' values replaced from `values`."""
    if isinstance(template, dict):
        return {k: fill_template(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill_template(v, values) for v in template]
    if isinstance(template, str) and template.startswith("{{") and template.endswith("}}"):
        key = template[2:-2].strip()
        if key in values:
            return values[key]
    return template


def load_template(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            wf = json.load(fh)
    except (OSError, ValueError) as e:
        raise ComfyError(f"Could not read the workflow file: {e}") from None
    if isinstance(wf, dict) and "nodes" in wf and "links" in wf:
        raise ComfyError("That is a ComfyUI editor workflow. Save it again with the API format "
                         "(Workflow menu > Export (API), or 'Save (API Format)') and load that file")
    if not isinstance(wf, dict) or not wf or any(not isinstance(v, dict) or "class_type" not in v for v in wf.values()):
        raise ComfyError("That file is not a ComfyUI workflow in API format (use 'Save (API Format)' in ComfyUI)")
    return wf


def has_placeholders(template) -> bool:
    """True if any value is a '{{name}}' placeholder (the older, manual way of marking what to fill in)."""
    if isinstance(template, dict):
        return any(has_placeholders(v) for v in template.values())
    if isinstance(template, list):
        return any(has_placeholders(v) for v in template)
    return isinstance(template, str) and template.startswith("{{") and template.endswith("}}")


def _is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and isinstance(v[1], int)


def _num_key(k):
    try:
        return (0, int(k))
    except (TypeError, ValueError):
        return (1, str(k))


def _text_node_for(wf: dict, link, depth: int = 0):
    """The prompt (text-encode) node feeding a 'positive' / 'negative' link, following it through conditioning nodes."""
    if not _is_link(link) or depth > 8:
        return None
    nid = str(link[0])
    node = wf.get(nid)
    if not node:
        return None
    ins = node.get("inputs", {})
    if isinstance(ins.get("text"), str) and "encode" in node.get("class_type", "").lower():
        return nid
    for key in ("conditioning", "positive", "negative"):
        if key in ins:
            hit = _text_node_for(wf, ins[key], depth + 1)
            if hit:
                return hit
    return None


def _image_slots(wf: dict) -> list:
    """Load Image nodes in the order a workflow uses them: those wired to a numbered 'images.imageN' input first
    (N = 0, 1, ...), then any other Load Image nodes by node number. Returns [(node_id, slot_owner or None, key or None)]."""
    slots, seen = [], set()
    for nid in sorted(wf, key=_num_key):
        ins = wf[nid].get("inputs", {})
        keys = sorted((k for k in ins if k.startswith("images.image") and k[len("images.image"):].isdigit()),
                      key=lambda k: int(k[len("images.image"):]))
        for k in keys:
            if _is_link(ins[k]) and wf.get(str(ins[k][0]), {}).get("class_type") == "LoadImage":
                slots.append((str(ins[k][0]), nid, k))
                seen.add(str(ins[k][0]))
    for nid in sorted(wf, key=_num_key):
        if wf[nid].get("class_type") == "LoadImage" and nid not in seen:
            slots.append((nid, None, None))
    return slots


def bind_workflow(template: dict, images: list, opt: dict, set_size: bool = False):
    """Fill a plain ComfyUI API workflow (no placeholders) from the panel. Returns (workflow, notes).
      images   uploaded file names, in the order they are to be used (ref_image_0, ref_image_1, ...)
      opt      prompt (empty = keep the workflow's own), negative, seed, width, height
    What is changed: the Load Image nodes, the positive prompt text, the seed of every sampler, and optionally the
    size. Everything else is left exactly as saved."""
    wf = json.loads(json.dumps(template))
    notes = []
    slots = _image_slots(wf)
    if not slots:
        raise ComfyError("Your workflow has no Load Image node, so there is nowhere to put the control map")
    for i, name in enumerate(images):
        if i < len(slots):
            wf[slots[i][0]]["inputs"]["image"] = name
        else:
            owner = next((s for s in reversed(slots) if s[1]), None)
            if owner is None:
                notes.append(f"{len(images) - i} extra image(s) not used: the workflow has only {len(slots)} Load Image node(s)")
                break
            ids = [int(k) for k in wf if str(k).isdigit()] or [0]
            new_id = str(max(ids) + 1)
            wf[new_id] = {"class_type": "LoadImage", "inputs": {"image": name}, "_meta": {"title": "Load Image (Gleek3Deek)"}}
            prefix = "images.image"
            wf[owner[1]]["inputs"][f"{prefix}{i}"] = [new_id, 0]
            slots.append((new_id, owner[1], f"{prefix}{i}"))
    if len(images) < len(slots):
        notes.append(f"{len(slots) - len(images)} Load Image node(s) kept the picture saved in the workflow")
    notes.append(f"{len(images)} map(s) sent")

    pos_ids, neg_ids = [], []
    for nid in sorted(wf, key=_num_key):
        ins = wf[nid].get("inputs", {})
        for key, bucket in (("positive", pos_ids), ("negative", neg_ids)):
            t = _text_node_for(wf, ins.get(key))
            if t and t not in bucket:
                bucket.append(t)
    prompt = (opt.get("prompt") or "").strip()
    if prompt and pos_ids:
        for t in pos_ids:
            wf[t]["inputs"]["text"] = prompt
        notes.append("prompt replaced" if len(pos_ids) == 1 else f"prompt replaced in {len(pos_ids)} nodes")
    elif pos_ids:
        notes.append("your workflow's own prompt kept")
    elif prompt:
        notes.append("no positive prompt node found: the prompt was not applied")
    neg = (opt.get("negative") or "").strip()
    for t in neg_ids:
        if neg and str(wf[t]["inputs"].get("text", "")).strip() and t not in pos_ids:
            wf[t]["inputs"]["text"] = neg

    seeded = 0
    for nid in wf:
        ins = wf[nid].get("inputs", {})
        for key in ("seed", "noise_seed"):
            if key in ins and isinstance(ins[key], int) and not isinstance(ins[key], bool):
                ins[key] = int(opt.get("seed", 0))
                seeded += 1
    if seeded:
        notes.append(f"seed {int(opt.get('seed', 0))}")

    if set_size:
        w, h = int(opt["width"]), int(opt["height"])
        for nid in wf:
            ins = wf[nid].get("inputs", {})
            cls = wf[nid].get("class_type", "")
            if "width" in ins and "height" in ins and "latent" in cls.lower() and not _is_link(ins["width"]):
                ins["width"], ins["height"] = w, h
            if "resolution.megapixels" in ins and not _is_link(ins["resolution.megapixels"]):
                ins["resolution.megapixels"] = round(max(0.1, w * h / 1e6), 2)
    return wf, notes


def fit_size(w: int, h: int, long_side: int) -> tuple:
    """(width, height) with the same aspect and the long side = long_side, both multiples of 8 (what SD needs)."""
    s = long_side / max(w, h)
    return max(64, round(w * s / 8) * 8), max(64, round(h * s / 8) * 8)


def random_seed() -> int:
    return random.randint(0, 2 ** 31 - 1)


def queue_prompt(base: str, workflow: dict) -> str:
    data = json.dumps({"prompt": workflow, "client_id": "gleek3deek"}).encode("utf-8")
    req = urllib.request.Request(base + "/prompt", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with _open(req, 30) as r:
        try:
            return str(json.loads(r.read().decode("utf-8"))["prompt_id"])
        except (ValueError, KeyError):
            raise ComfyError("ComfyUI did not accept the request") from None


def interrupt(base: str):
    try:
        _open(urllib.request.Request(base + "/interrupt", data=b"", method="POST"), 5).close()
    except ComfyError:
        pass


def wait_for_result(base: str, prompt_id: str, progress=None, cancelled=None, timeout: float = 900.0,
                    poll: float = 0.7) -> list:
    """Block until the prompt has finished; returns [(filename, subfolder, type)] of its output images."""
    t0 = time.time()
    while True:
        if cancelled is not None and cancelled():
            interrupt(base)
            raise Cancelled("Cancelled")
        if time.time() - t0 > timeout:
            raise ComfyError("ComfyUI took too long (is a model still loading?)")
        h = get_json(base, "/history/" + prompt_id).get(prompt_id)
        if h:
            st = (h.get("status") or {})
            if st.get("status_str") == "error":
                msg = ""
                for m in st.get("messages", []):
                    if m and m[0] == "execution_error":
                        d = m[1]
                        msg = f"{d.get('node_type', '')}: {d.get('exception_message', '')}".strip()
                raise ComfyError("ComfyUI could not finish: " + (msg or "unknown error"))
            imgs = [(i["filename"], i.get("subfolder", ""), i.get("type", "output"))
                    for o in (h.get("outputs") or {}).values() for i in o.get("images", [])]
            if imgs or st.get("completed"):
                if not imgs:
                    raise ComfyError("The workflow finished but made no image (it needs a Save Image node)")
                return imgs
        if progress is not None:
            try:
                q = get_json(base, "/queue")
                running = any(len(x) > 1 and x[1] == prompt_id for x in q.get("queue_running", []))
                waiting = sum(1 for x in q.get("queue_pending", []))
                progress("Generating…" if running else (f"Waiting in ComfyUI's queue ({waiting} ahead)…" if waiting
                                                        else "Loading models…"))
            except ComfyError:
                pass
        time.sleep(poll)


def fetch_image(base: str, ref: tuple) -> bytes:
    name, sub, typ = ref
    q = urllib.parse.urlencode({"filename": name, "subfolder": sub, "type": typ})
    with _open(urllib.request.Request(base + "/view?" + q), 60) as r:
        return r.read()


def generate(base: str, images, opt: dict, template: dict | None = None, progress=None, cancelled=None,
             set_size: bool = False) -> bytes:
    """Upload the map(s), run the workflow, return the PNG bytes of the first result.
    images: PNG bytes of one map, or a list of (map_key, png_bytes) in the order they are to be used."""
    base = normalize_url(base)
    say = progress or (lambda _t: None)
    if isinstance(images, (bytes, bytearray)):
        images = [(opt.get("map", "map"), bytes(images))]
    if not images:
        raise ComfyError("No control map to send")
    say("Uploading the map…" if len(images) == 1 else f"Uploading {len(images)} maps…")
    tag = uuid.uuid4().hex[:8]
    names = [upload_image(base, png, f"gleek3deek_{key}_{tag}.png") for key, png in images]
    notes = []
    if template is not None:
        if has_placeholders(template):
            values = {"image": names[0], "prompt": opt["prompt"], "negative": opt.get("negative", ""),
                      "seed": int(opt.get("seed", 0)), "width": int(opt["width"]), "height": int(opt["height"]),
                      "strength": float(opt.get("strength", 0.8)), "checkpoint": opt.get("checkpoint", ""),
                      "controlnet": opt.get("controlnet", "")}
            values.update({f"image{i}": n for i, n in enumerate(names)})
            wf = fill_template(template, values)
        else:
            wf, notes = bind_workflow(template, names, opt, set_size)
    else:
        if not opt.get("checkpoint") or not opt.get("controlnet"):
            raise ComfyError("Choose a checkpoint and a ControlNet (none were found on the server)")
        wf = build_workflow(opt, names[0])
    if notes:
        say("Your workflow: " + "; ".join(notes))
    say("Sending to ComfyUI…")
    pid = queue_prompt(base, wf)
    refs = wait_for_result(base, pid, say, cancelled)
    say("Downloading the result…")
    return fetch_image(base, refs[0])
