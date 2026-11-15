"""Studio – run the podcast pipeline from the browser.

Adds /studio (the page) and /api/studio/* to the Content Scheduler's Flask app.
A run is the normal process script started as a subprocess; its output is
streamed to the page, and the page answers its prompts (image pause, "Continue
with the next story?") by writing to the process's stdin – exactly what you
would type in the terminal.
"""
import codecs
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request, send_file

bp = Blueprint("studio", __name__)
PIPE = (Path(__file__).resolve().parent.parent / "podcast_pipeline").resolve()


def _load_pipeline_module(name, relpath):
    """Load a pipeline module by file path, so the Studio uses the pipeline's own
    marker strings and JSON rules instead of copies of them."""
    spec = importlib.util.spec_from_file_location(name, PIPE / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_pipeline_module("pipeline_markers", "common/markers.py")   # printed-line markers
U = _load_pipeline_module("pipeline_utils", "common/utils.py")       # strict JSON loader

PROCESSES = {
    "witn":       {"label": "WITN",            "script": "witn/witn.py",             "images": True,
                   "source": "script-in.txt", "note": "Stories are rewritten by the language model first."},
    "aesop":      {"label": "Aesop's Fables",  "script": "aesop/aesop.py",           "images": True,  "source": "script.txt"},
    "cocku":      {"label": "COCKu",           "script": "cocku/cocku.py",           "images": False, "source": "script.txt"},
    "confuscius": {"label": "Confuscius",      "script": "confuscius/confuscius.py", "images": False, "source": "script.txt"},
    "audio":      {"label": "Audio only",      "script": "audio/audio_pipeline.py",  "images": False, "source": "script.txt"},
}

JOBS = {}
LOCK = threading.Lock()


def proc_dir(key):
    if key not in PROCESSES:
        abort(404)
    return PIPE / key


def safe_path(p):
    """Resolve a path and make sure it stays inside podcast_pipeline/."""
    full = (PIPE / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
    if full != PIPE and PIPE not in full.parents:
        abort(403)
    return full


def load_cfg(key):
    """(config, error). A broken config.json is reported and blocks the run; it is not hidden."""
    try:
        return U.load_json_file(proc_dir(key) / "config.json"), ""
    except (OSError, ValueError) as ex:
        return {}, str(ex)


# ---------------------------------------------------------------- jobs
class Job:
    def __init__(self, key, cmd, cwd):
        self.id = uuid.uuid4().hex[:10]
        self.key, self.cmd = key, cmd
        self.lines, self.pending = [], ""
        self.state, self.code = "running", None
        self.started = time.time()
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, env=env, creationflags=flags)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            chunk = os.read(self.p.stdout.fileno(), 4096)
            if not chunk:
                break
            text = dec.decode(chunk)
            with LOCK:
                buf = self.pending + text
                *done, self.pending = buf.replace("\r\n", "\n").split("\n")
                self.lines.extend(done)
                if M.PROMPT_IMAGES in self.pending:
                    self.state = "waiting_images"
                elif M.PROMPT_CONTINUE in self.pending:
                    self.state = "waiting_continue"
        self.p.wait()
        with LOCK:
            if self.pending:
                self.lines.append(self.pending); self.pending = ""
            self.code = self.p.returncode
            self.state = "done" if self.code == 0 else "failed"

    def send(self, text):
        with LOCK:
            if self.state not in ("waiting_images", "waiting_continue"):
                return False
            self.lines.append(self.pending + text); self.pending = ""
            self.state = "running"
        try:
            self.p.stdin.write((text + "\n").encode("utf-8")); self.p.stdin.flush()
        except OSError:
            return False
        return True

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()

    def snapshot(self, since=0):
        with LOCK:
            lines = list(self.lines)
            pending, state = self.pending, self.state
        return {"id": self.id, "process": self.key, "state": state, "code": self.code,
                "test": getattr(self, "test", False),
                "lines": lines[since:], "total": len(lines), "pending": pending,
                "images": needed_images(lines, self.key) if state == "waiting_images" else [],
                "missing": missing_images(lines) if state == "waiting_images" else [],
                "next": next_label(pending) if state == "waiting_continue" else "",
                "episodes": [l.split(M.DONE, 1)[1].strip() for l in lines if M.DONE in l],
                "scheduled": [l.split(M.SCHEDULED, 1)[1].strip() for l in lines if M.SCHEDULED in l],
                "elapsed": int(time.time() - self.started)}


def _rel_to_pipe(full):
    """Path relative to podcast_pipeline/ when inside it, otherwise the full path."""
    try:
        return str(full.relative_to(PIPE)).replace("\\", "/")
    except ValueError:
        return str(full)


def needed_images(lines, key):
    """Image requests from the most recent prompt block in the output."""
    start = max((i for i, l in enumerate(lines) if M.STORY_HEADER in l), default=0)
    out, i = [], start
    while i < len(lines):
        m = M.IMAGE_NEEDED_RE.match(lines[i].strip())
        if m:
            j, prompt = i + 2, []                       # skip the dashed line
            while j < len(lines) and not lines[j].startswith("-" * 20):
                prompt.append(lines[j]); j += 1
            path = ""
            while j < len(lines) and not path:
                if lines[j].strip() == M.SAVE_AS and j + 1 < len(lines):
                    path = lines[j + 1].strip()
                j += 1
            raw = Path(path) if path else None
            full = (raw if raw.is_absolute() else PIPE / key / raw).resolve() if path else None
            out.append({"title": m.group(1), "n": int(m.group(2) or 1), "of": int(m.group(3) or 1),
                        "prompt": "\n".join(prompt).strip(),
                        "path": _rel_to_pipe(full) if full else "",
                        "have": bool(full and full.exists())})
            i = j
        else:
            i += 1
    return out


def missing_images(lines):
    for i in range(len(lines) - 1, -1, -1):
        if M.STILL_MISSING in lines[i]:
            return [l.strip() for l in lines[i + 1:] if l.strip() and not l.strip().startswith(M.CREATE_PROMPT)]
    return []


def next_label(pending):
    m = M.NEXT_LABEL_RE.search(pending)
    return m.group(1) if m else ""


def running_job(key):
    return next((j for j in JOBS.values() if j.key == key and j.state not in ("done", "failed")), None)


# ---------------------------------------------------------------- pages / api
@bp.route("/studio")
def page():
    return render_template("studio.html")


@bp.route("/api/studio/processes")
def processes():
    out = []
    for key, meta in PROCESSES.items():
        d = PIPE / key
        if not d.is_dir():
            continue
        cfg, cfg_error = load_cfg(key)
        src = d / meta["source"]
        try:
            prog = U.load_json_file(d / "progress.json").get(str(src.resolve()).lower(), {})
        except (OSError, ValueError):
            prog = {}
        text = src.read_text(encoding="utf-8") if src.exists() else ""
        stories = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()] if text.strip() else []
        outs = sorted((d / "output").glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True) if (d / "output").is_dir() else []
        eps = [f for f in outs if not re.search(r"_(title|story|middle|intro|tiktok|alt-ending)(_tiktok)?\.mp4$", f.name)]
        try:
            seq = U.load_json_file(d / "sequence.json").get("seq", 0)
        except (OSError, ValueError):
            seq = 0
        j = running_job(key)
        out.append({"key": key, **meta, "series": (cfg.get("scheduler") or {}).get("series", ""),
                    "prefix": (cfg.get("process") or {}).get("prefix", key.upper()),
                    "config_error": cfg_error,
                    "tts": cfg.get("tts_engine", "google"), "text": text, "stories": len(stories),
                    "done": len(prog.get("done", [])), "episodes": len(eps), "seq": seq,
                    "latest": [{"name": f.name, "path": str(f.relative_to(PIPE)).replace("\\", "/")} for f in eps[:4]],
                    "job": j.id if j else None})
    return jsonify(processes=out)


@bp.route("/api/studio/script", methods=["POST"])
def save_script():
    b = request.get_json(silent=True) or {}
    d = proc_dir(b.get("process"))
    text = (b.get("text") or "").replace("\r\n", "\n")
    path = d / PROCESSES[b["process"]]["source"]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text.rstrip() + "\n" if text.strip() else "", encoding="utf-8")
    os.replace(tmp, path)
    return jsonify(ok=True, path=str(path))


@bp.route("/api/studio/run", methods=["POST"])
def run():
    b = request.get_json(silent=True) or {}
    key = b.get("process")
    d = proc_dir(key)
    if running_job(key):
        return jsonify(error="That process is already running."), 400
    _, cfg_error = load_cfg(key)
    if cfg_error:
        return jsonify(error=f"Not started: {cfg_error}"), 400
    meta = PROCESSES[key]
    cmd = [sys.executable, "-u", str(PIPE / meta["script"])]
    if key == "witn":
        cmd += ["--script-in", str(d / "script-in.txt")]
    else:
        cmd += ["--script", str(d / "script.txt")]
    if key == "audio":
        cmd += ["--intro", str(b.get("intro") or PIPE / "intro.mp3"), "--outro", str(b.get("outro") or PIPE / "outro.mp3")]
    else:
        if b.get("tiktok", True):
            cmd.append("--tiktok")
        if meta["images"] and b.get("images"):
            try:
                n_images = int(b["images"])
            except (TypeError, ValueError):
                return jsonify(error="images must be a number 1-3."), 400
            cmd += ["--images", str(max(1, min(3, n_images)))]
    if b.get("tts") in ("google", "piper", "kokoro", "voicestudio"):
        cmd += ["--tts-engine", b["tts"]]
    if b.get("start_over"):
        cmd.append("--start-over")
    if b.get("test"):
        cmd.append("--test")
    j = Job(key, cmd, str(PIPE))
    j.test = bool(b.get("test"))
    JOBS[j.id] = j
    return jsonify(ok=True, job=j.id)


@bp.route("/api/studio/job/<jid>")
def job(jid):
    j = JOBS.get(jid) or abort(404)
    return jsonify(j.snapshot(int(request.args.get("since", 0))))


@bp.route("/api/studio/job/<jid>/<action>", methods=["POST"])
def job_action(jid, action):
    j = JOBS.get(jid) or abort(404)
    if action == "continue":
        ok = j.send("" if j.state == "waiting_images" else "y")
    elif action == "pause":
        ok = j.send("n")
    elif action == "quit":
        ok = j.send("q") if j.state == "waiting_images" else (j.stop() or True)
    elif action == "stop":
        j.stop(); ok = True
    else:
        abort(400)
    return jsonify(ok=bool(ok))


@bp.route("/api/studio/upload", methods=["POST"])
def upload():
    dest = safe_path(request.form.get("path", ""))
    rel = dest.relative_to(PIPE).parts                 # <process>/output/[test/]name.jpg
    if dest.suffix.lower() not in (".jpg", ".jpeg") or len(rel) < 3 or rel[1] != "output" \
            or rel[0] not in PROCESSES or (len(rel) == 4 and rel[2] != "test") or len(rel) > 4:
        abort(400)
    f = request.files.get("file") or abort(400)
    data = f.read()
    try:                                    # store a real JPEG whatever was dropped (png, webp…)
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        tmp = dest.with_suffix(".upload.jpg")
        im.convert("RGB").save(tmp, "JPEG", quality=95)
    except ImportError:
        tmp = dest.with_suffix(".upload.jpg"); tmp.write_bytes(data)
    os.replace(tmp, dest)
    return jsonify(ok=True)


@bp.route("/api/studio/file")
def file():
    p = safe_path(request.args.get("path", ""))
    if not p.is_file():
        abort(404)
    return send_file(p, conditional=True)
