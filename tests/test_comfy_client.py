"""ComfyUI client: workflow building, placeholders, and a full round trip against a fake local server."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import comfy_client as cc


def test_normalize_url():
    assert cc.normalize_url("") == "http://127.0.0.1:8188"
    assert cc.normalize_url("localhost:8188/") == "http://localhost:8188"
    assert cc.normalize_url("https://x.example:9/") == "https://x.example:9"
    with pytest.raises(cc.ComfyError):
        cc.normalize_url("ftp://x")


def test_fit_size_multiples_of_eight():
    assert cc.fit_size(1280, 960, 512) == (512, 384)
    w, h = cc.fit_size(1000, 333, 768)
    assert w % 8 == 0 and h % 8 == 0 and w == 768


def test_pick_controlnet_prefers_union_for_sdxl():
    cns = ["control_v11f1p_sd15_depth_fp16.safetensors", "xinsir-controlnet-union-sdxl-1.0-promax.safetensors"]
    assert "union" in cc.pick_controlnet(cns, "depth", "sd_xl_turbo_1.0_fp16.safetensors")
    assert "sd15_depth" in cc.pick_controlnet(cns, "depth", "DreamShaper_8.safetensors")


def test_build_workflow_turbo_and_union():
    wf = cc.build_workflow({"checkpoint": "sd_xl_turbo_1.0_fp16.safetensors", "controlnet": "x-union-sdxl.safetensors",
                            "map": "normal", "prompt": "p", "negative": "n", "seed": 5, "width": 512, "height": 384,
                            "strength": 0.7}, "img.png")
    kinds = {v["class_type"] for v in wf.values()}
    assert {"SDTurboScheduler", "SamplerCustom", "SetUnionControlNetType", "SaveImage"} <= kinds
    assert wf["5"]["inputs"]["type"] == "normal" and wf["7"]["inputs"]["control_net"] == ["5", 0]
    assert wf["6"]["inputs"]["image"] == "img.png" and wf["8"]["inputs"]["height"] == 384


def test_build_workflow_plain_checkpoint_has_no_union_node():
    wf = cc.build_workflow({"checkpoint": "DreamShaper_8.safetensors", "controlnet": "control_v11f1p_sd15_depth.pth",
                            "map": "depth", "prompt": "p", "seed": 1, "width": 512, "height": 512}, "i.png")
    assert "SetUnionControlNetType" not in {v["class_type"] for v in wf.values()}
    assert wf["11"]["class_type"] == "KSampler" and wf["7"]["inputs"]["control_net"] == ["4", 0]


def test_fill_template_keeps_types_and_leaves_other_strings():
    t = {"a": {"inputs": {"seed": "{{seed}}", "text": "{{prompt}}", "keep": "{{unknown}}", "x": "plain", "l": ["{{width}}", 1]}}}
    out = cc.fill_template(t, {"seed": 7, "prompt": "hi", "width": 512})
    assert out["a"]["inputs"] == {"seed": 7, "text": "hi", "keep": "{{unknown}}", "x": "plain", "l": [512, 1]}


def test_load_template_validates(tmp_path):
    good = tmp_path / "g.json"
    good.write_text(json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}}))
    assert "1" in cc.load_template(str(good))
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps({"nodes": [1, 2]}))
    with pytest.raises(cc.ComfyError):
        cc.load_template(str(bad))
    with pytest.raises(cc.ComfyError):
        cc.load_template(str(tmp_path / "missing.json"))


class FakeComfy(BaseHTTPRequestHandler):
    seen = {}
    polls = 0

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path
        if p == "/system_stats":
            self._send({"system": {"comfyui_version": "9.9"}, "devices": [{"name": "GPU", "vram_total": 8e9}]})
        elif p.startswith("/object_info/CheckpointLoaderSimple"):
            self._send({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["a.safetensors", "b-turbo.safetensors"]]}}}})
        elif p.startswith("/object_info/ControlNetLoader"):
            self._send({"ControlNetLoader": {"input": {"required": {"control_net_name": [["u-union.safetensors"]]}}}})
        elif p.startswith("/history/"):
            FakeComfy.polls += 1
            if FakeComfy.polls < 2:
                self._send({})
            else:
                self._send({"pid1": {"status": {"status_str": "success", "completed": True},
                                     "outputs": {"13": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}}})
        elif p == "/queue":
            self._send({"queue_running": [], "queue_pending": []})
        elif p.startswith("/view?"):
            self._send(None, raw=b"PNGDATA")
        else:
            self._send({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        if self.path == "/upload/image":
            FakeComfy.seen["upload"] = data
            self._send({"name": "up.png"})
        elif self.path == "/prompt":
            FakeComfy.seen["prompt"] = json.loads(data)
            self._send({"prompt_id": "pid1"})
        else:
            self._send({}, 404)


@pytest.fixture()
def server():
    FakeComfy.seen, FakeComfy.polls = {}, 0
    srv = HTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_server_info(server):
    info = cc.server_info(server)
    assert info["version"] == "9.9" and info["vram_gb"] == 8.0
    assert info["checkpoints"] == ["a.safetensors", "b-turbo.safetensors"] and info["controlnets"] == ["u-union.safetensors"]


def test_generate_round_trip(server):
    msgs = []
    out = cc.generate(server, b"\x89PNG-map", {"checkpoint": "b-turbo.safetensors", "controlnet": "u-union.safetensors",
                      "map": "depth", "prompt": "a car", "seed": 3, "width": 512, "height": 512}, progress=msgs.append)
    assert out == b"PNGDATA"
    assert b"\x89PNG-map" in FakeComfy.seen["upload"]
    sent = FakeComfy.seen["prompt"]["prompt"]
    assert sent["6"]["inputs"]["image"] == "up.png" and sent["2"]["inputs"]["text"] == "a car"
    assert any("Uploading" in m for m in msgs)


def test_generate_with_template(server, tmp_path):
    t = {"9": {"class_type": "SaveImage", "inputs": {"prompt": "{{prompt}}", "img": "{{image}}", "s": "{{seed}}"}}}
    cc.generate(server, b"x", {"prompt": "hello", "seed": 11, "width": 64, "height": 64, "map": "depth"}, template=t)
    assert FakeComfy.seen["prompt"]["prompt"]["9"]["inputs"] == {"prompt": "hello", "img": "up.png", "s": 11}


def test_unreachable_server_message():
    with pytest.raises(cc.ComfyError) as e:
        cc.get_json("http://127.0.0.1:9", "/system_stats", timeout=1)
    assert "Could not reach ComfyUI" in str(e.value)


def test_cancel_interrupts(server):
    with pytest.raises(cc.Cancelled):
        cc.wait_for_result(server, "pid1", cancelled=lambda: True)


def test_pick_checkpoint_by_quality():
    cks = ["DreamShaper_8.safetensors", "juggernautXL_v8Rundiffusion.safetensors", "sd_xl_refiner_1.0.safetensors",
           "realvisxlV30Turbo_v30TurboBakedvae.safetensors", "sd_xl_turbo_1.0_fp16.safetensors"]
    assert "Turbo" in cc.pick_checkpoint(cks, "fast")
    assert cc.pick_checkpoint(cks, "balanced") == "juggernautXL_v8Rundiffusion.safetensors"
    assert cc.pick_checkpoint(["a.safetensors"], "best") == "a.safetensors"


def test_hires_adds_a_second_pass_and_tiled_decode():
    o = {"checkpoint": "juggernautXL_v8Rundiffusion.safetensors", "controlnet": "u-union.safetensors", "map": "depth",
         "prompt": "p", "seed": 1, "width": 768, "height": 576, "hires": True}
    wf = cc.build_workflow(o, "i.png")
    assert wf["14"]["class_type"] == "LatentUpscaleBy" and wf["15"]["inputs"]["latent_image"] == ["14", 0]
    assert wf["12"]["class_type"] == "VAEDecodeTiled" and wf["12"]["inputs"]["samples"] == ["15", 0]
    plain = cc.build_workflow({**o, "hires": False}, "i.png")
    assert "14" not in plain and plain["12"]["inputs"]["samples"] == ["11", 0]


# ---- plain workflows (no placeholders): filled in automatically --------------------------------------------------
KLEIN = os.path.join(os.path.dirname(__file__), "klein_workflow.json")


def _klein():
    with open(KLEIN, encoding="utf-8") as fh:
        return json.load(fh)


def test_bind_fills_a_plain_workflow_without_touching_the_rest():
    t = _klein()
    wf, notes = cc.bind_workflow(t, ["map0.png"], {"prompt": "In <ref_image_0>, make a jade dragon", "seed": 42,
                                                    "negative": "ugly", "width": 768, "height": 576})
    assert wf["54"]["inputs"]["image"] == "map0.png"                      # the Load Image node
    assert wf["63"]["inputs"]["text"] == "In <ref_image_0>, make a jade dragon"
    assert wf["7"]["inputs"]["seed"] == 42
    assert wf["58"]["inputs"]["text"] == ""                                # empty negative stays empty
    assert wf["17"]["inputs"]["resolution.megapixels"] == 1                # size untouched by default
    assert wf["62"] == t["62"] and wf["2"] == t["2"] and t["54"]["inputs"]["image"] != "map0.png"   # input not mutated


def test_bind_keeps_the_workflows_prompt_when_the_box_is_empty():
    wf, notes = cc.bind_workflow(_klein(), ["m.png"], {"prompt": "  ", "seed": 1})
    assert wf["63"]["inputs"]["text"].startswith("In <ref_image_0>, convert") and any("own prompt" in n for n in notes)


def test_bind_adds_more_load_image_nodes_for_extra_maps():
    wf, notes = cc.bind_workflow(_klein(), ["a.png", "b.png", "c.png"], {"prompt": "p", "seed": 5})
    ins = wf["17"]["inputs"]
    assert wf["54"]["inputs"]["image"] == "a.png" and ins["images.image0"] == ["54", 0]
    n1, n2 = ins["images.image1"][0], ins["images.image2"][0]
    assert wf[n1]["class_type"] == "LoadImage" and wf[n1]["inputs"]["image"] == "b.png"
    assert wf[n2]["inputs"]["image"] == "c.png" and n1 != n2 and n1 not in _klein()


def test_bind_can_set_the_size_when_asked():
    wf, _ = cc.bind_workflow(_klein(), ["m.png"], {"prompt": "p", "seed": 1, "width": 1024, "height": 768}, set_size=True)
    assert wf["17"]["inputs"]["resolution.megapixels"] == 0.79


def test_bind_needs_a_load_image_node():
    with pytest.raises(cc.ComfyError):
        cc.bind_workflow({"1": {"class_type": "SaveImage", "inputs": {}}}, ["m.png"], {"prompt": "p"})


def test_bind_replaces_a_negative_that_has_text():
    t = {"1": {"class_type": "LoadImage", "inputs": {"image": "x"}},
         "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos", "clip": ["9", 0]}},
         "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative", "clip": ["9", 0]}},
         "4": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["2", 0], "negative": ["3", 0]}}}
    wf, _ = cc.bind_workflow(t, ["m.png"], {"prompt": "new", "negative": "blurry", "seed": 9})
    assert wf["2"]["inputs"]["text"] == "new" and wf["3"]["inputs"]["text"] == "blurry" and wf["4"]["inputs"]["seed"] == 9


def test_editor_format_gets_a_helpful_message(tmp_path):
    p = tmp_path / "ui.json"
    p.write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(cc.ComfyError) as e:
        cc.load_template(str(p))
    assert "API" in str(e.value)


def test_generate_with_a_plain_workflow_and_several_maps(server):
    cc.generate(server, [("normal", b"n"), ("depth", b"d")], {"prompt": "hello", "seed": 3, "width": 64, "height": 64},
                template=_klein())
    sent = FakeComfy.seen["prompt"]["prompt"]
    assert sent["54"]["inputs"]["image"] == "up.png" and sent["63"]["inputs"]["text"] == "hello"
    assert "images.image1" in sent["17"]["inputs"]
