"""ComfyUI image client, tested against a small fake ComfyUI server (no GPU needed)."""
import json
import shutil
import sys
import threading
import zlib
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

import imagegen as G  # noqa: E402


def tiny_png():
    raw = b"\x00" + b"\x80\x40\x20" * 4
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeComfy(BaseHTTPRequestHandler):
    posted = []

    def do_GET(self):
        if self.path.startswith("/system_stats"):
            return self._json({"system": {}})
        if self.path.startswith("/history/"):
            pid = self.path.split("/")[-1]
            return self._json({pid: {"status": {"status_str": "success"},
                                     "outputs": {"7": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}}}})
        if self.path.startswith("/view"):
            body = tiny_png()
            self.send_response(200); self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        FakeComfy.posted.append(body)
        self._json({"prompt_id": "pid-1", "number": 1})

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def comfy():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeComfy.posted.clear()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def cfg_for(url, extra=None):
    c = {"enabled": True, "workflow_file": "comfy_txt2img.json", "checkpoint": "model.safetensors",
         "width": 896, "height": 512, "steps": 12, "cfg": 6.5, "negative_prompt": "blurry",
         "timeout_seconds": 30, "workers": [{"name": "dead", "url": "http://127.0.0.1:9"},
                                            {"name": "live", "url": url}]}
    c.update(extra or {})
    return c


def test_workflow_placeholders_are_filled_and_types_kept():
    wf = G.build_workflow(cfg_for("http://x"), "a fox in a meadow", "AESOP-001")
    assert wf["4"]["inputs"]["width"] == 896 and isinstance(wf["4"]["inputs"]["width"], int)
    assert wf["2"]["inputs"]["text"] == "a fox in a meadow"
    assert wf["7"]["inputs"]["filename_prefix"] == "AESOP-001"
    assert wf["5"]["inputs"]["cfg"] == 6.5
    assert "{{" not in json.dumps(wf)


def test_pick_worker_skips_dead_machine(comfy):
    w = G.pick_worker(cfg_for(comfy))
    assert w and w["name"] == "live"


def test_pick_worker_named_and_missing(comfy):
    assert G.pick_worker(cfg_for(comfy), "live")["name"] == "live"
    assert G.pick_worker(cfg_for(comfy), "dead") is None
    with pytest.raises(ValueError):
        G.pick_worker(cfg_for(comfy), "nobody")


def test_generate_missing_saves_png(comfy, tmp_path):
    target = tmp_path / "AESOP-001_Title.png"
    prep = {"stem": "AESOP-001_Title", "images": [{"n": 1, "prompt": "a crow on a branch", "path": target}]}
    made = G.generate_missing([prep], {"image_gen": cfg_for(comfy)}, tmp_path)
    assert made == 1 and target.exists() and target.read_bytes().startswith(b"\x89PNG")
    sent = FakeComfy.posted[-1]["prompt"]
    assert sent["2"]["inputs"]["text"] == "a crow on a branch"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg needed to write .jpg")
def test_generate_missing_writes_jpg(comfy, tmp_path):
    target = tmp_path / "WITN-001_Title.jpg"
    prep = {"stem": "WITN-001_Title", "images": [{"n": 1, "prompt": "p", "path": target}]}
    assert G.generate_missing([prep], {"image_gen": cfg_for(comfy)}, tmp_path) == 1
    assert target.exists() and target.read_bytes()[:2] == b"\xff\xd8"


def test_disabled_or_no_worker_does_nothing(tmp_path):
    prep = {"stem": "s", "images": [{"n": 1, "prompt": "p", "path": tmp_path / "a.jpg"}]}
    assert G.generate_missing([prep], {"image_gen": {"enabled": False}}, tmp_path) == 0
    assert G.generate_missing([prep], {"image_gen": {"enabled": True, "workers": [
        {"name": "dead", "url": "http://127.0.0.1:9"}]}}, tmp_path) == 0
