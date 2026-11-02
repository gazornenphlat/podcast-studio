"""Make the story images with ComfyUI, on one of the configured workers.

Off unless config.json has "image_gen": {"enabled": true, ...}. When it is on, any image
the pipeline asks for is generated before the manual pause; the pause only waits for
whatever could not be made. ComfyUI runs on each worker machine as its own process
(start it with --listen so other computers can reach it). No login: keep it on your LAN.
"""
import copy
import json
import os
import random
import subprocess
import time
import uuid
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PLACEHOLDERS = {"{{PROMPT}}", "{{NEGATIVE}}", "{{CKPT}}", "{{WIDTH}}", "{{HEIGHT}}",
                "{{STEPS}}", "{{CFG}}", "{{SEED}}", "{{PREFIX}}"}


def is_enabled(config):
    return bool((config.get("image_gen") or {}).get("enabled"))


def fill_workflow(template, values):
    """Replace {{PLACEHOLDER}} strings in a ComfyUI API-format workflow. A value that is the
    whole string keeps its type (so width stays a number); otherwise the text is substituted."""
    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            if node in values:
                return values[node]
            out = node
            for key, val in values.items():
                if key in out:
                    out = out.replace(key, str(val))
            return out
        return node
    return walk(copy.deepcopy(template))


def build_workflow(cfg, prompt, prefix, target_size=None):
    template = json.loads((HERE / cfg.get("workflow_file", "comfy_txt2img.json")).read_text(encoding="utf-8"))
    width, height = target_size or (cfg.get("width", 896), cfg.get("height", 512))
    values = {"{{PROMPT}}": prompt, "{{NEGATIVE}}": cfg.get("negative_prompt", ""),
              "{{CKPT}}": cfg.get("checkpoint", ""), "{{WIDTH}}": int(width), "{{HEIGHT}}": int(height),
              "{{STEPS}}": int(cfg.get("steps", 20)), "{{CFG}}": float(cfg.get("cfg", 7.0)),
              "{{SEED}}": random.randint(1, 2**31 - 1), "{{PREFIX}}": prefix}
    left = [p for p in PLACEHOLDERS if p in json.dumps(fill_workflow(template, values))]
    if left:
        raise ValueError(f"workflow still has placeholders {left}; check {cfg.get('workflow_file')}")
    return fill_workflow(template, values)


def pick_worker(cfg, prefer=None):
    """First worker that answers, in config order. prefer = a worker name (or None / 'auto')."""
    workers = cfg.get("workers") or []
    if prefer and prefer != "auto":
        workers = [w for w in workers if w.get("name") == prefer]
        if not workers:
            raise ValueError(f"No image worker named {prefer!r} in image_gen.workers.")
    for w in workers:
        try:
            if requests.get(w["url"].rstrip("/") + "/system_stats", timeout=3).ok:
                return w
        except requests.RequestException:
            continue
    return None


def _make_one(worker, cfg, prompt, target, prefix_stem):
    base = worker["url"].rstrip("/")
    wf = build_workflow(cfg, prompt, prefix_stem)
    r = requests.post(base + "/prompt", json={"prompt": wf, "client_id": uuid.uuid4().hex}, timeout=30)
    r.raise_for_status()
    pid = r.json()["prompt_id"]
    deadline = time.time() + int(cfg.get("timeout_seconds", 900))
    while True:
        if time.time() > deadline:
            raise TimeoutError(f"{worker['name']} didn't finish within {cfg.get('timeout_seconds', 900)}s")
        hist = requests.get(f"{base}/history/{pid}", timeout=30).json().get(pid, {})
        status = (hist.get("status") or {}).get("status_str")
        if status == "error":
            raise RuntimeError(f"ComfyUI reported an error: check the ComfyUI window on {worker['name']}")
        outputs = hist.get("outputs") or {}
        images = [img for node in outputs.values() for img in node.get("images", [])]
        if images:
            break
        time.sleep(2)
    img = images[0]
    data = requests.get(f"{base}/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                                  "type": img.get("type", "output")}, timeout=60).content
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp.png")
    tmp.write_bytes(data)
    if target.suffix.lower() in (".jpg", ".jpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-q:v", "2", str(target)], check=True)
        tmp.unlink()
    else:
        os.replace(tmp, target)


def generate_missing(prepared, config, output_dir):
    """Make every image that is not on disk yet. Returns the number made. Never raises for a
    single failed image: that one is left for the manual pause."""
    cfg = config.get("image_gen") or {}
    if not cfg.get("enabled"):
        return 0
    todo = [(prep, im) for prep in prepared for im in prep["images"] if not im["path"].exists()]
    if not todo:
        return 0
    worker = pick_worker(cfg, cfg.get("worker"))
    if worker is None:
        print("⚠️  No image worker answered (" + ", ".join(w.get("name", "?") for w in cfg.get("workers", []))
              + "). Make the images by hand, or start ComfyUI on a worker.")
        return 0
    print(f"🖼  Making {len(todo)} image(s) on {worker['name']} ...")
    made = 0
    for prep, im in todo:
        try:
            _make_one(worker, cfg, im["prompt"], im["path"], prep["stem"])
            made += 1
            print(f"✅ Image made: {im['path'].name}")
        except Exception as ex:
            print(f"⚠️  Couldn't make {im['path'].name}: {ex}. Make it by hand.")
    return made
