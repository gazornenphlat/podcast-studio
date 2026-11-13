"""VoiceStudio batch queue for the Studio page.

Turns a text file (one line = one WAV) into WAV files, one run per selected
voice profile, through VoiceStudio's local API. Runs go one after another in
the order they were added. Behaviour matches the Generate-VoiceStudioScheduled
PowerShell script:
  - blank lines are skipped
  - files are named "<Voice>_NNNN.wav"; numbering continues from the highest
    number already in the folder for that voice
  - each WAV is written to a .tmp file first, then moved into place
  - skip-existing: a line the same voice already made into this folder is
    skipped while its WAV is still there (generated.json in the folder records it)
  - a failed line is recorded and the run carries on
  - each run writes generation-report-<id>.csv into its output folder

Settings (environment variables, optional):
  VOICESTUDIO_URL     default http://127.0.0.1:3900/v1
  VOICESTUDIO_API_KEY sent as a Bearer token if the server needs one
  VOICESTUDIO_DATA    where batch-jobs.json lives; default ~/Music/VoiceStudio
"""
import csv
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

bp = Blueprint("voicestudio_batch", __name__)

API_BASE = os.environ.get("VOICESTUDIO_URL", "http://127.0.0.1:3900/v1").rstrip("/")
MODEL = "omnivoice"
SPEED = 1.0
FORMAT = "wav"
TIMEOUT = 3600
DATA_DIR = Path(os.environ.get("VOICESTUDIO_DATA") or (Path.home() / "Music" / "VoiceStudio"))

_LOCK = threading.Lock()          # guards batch-jobs.json
_WORKER = None                    # the one queue thread, if running
_INVALID_NAME = re.compile(r'[\\/:*?"<>|]')


def _jobs_file():
    return DATA_DIR / "batch-jobs.json"


def _auth_headers():
    key = os.environ.get("VOICESTUDIO_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


# ---------------------------------------------------------------- storage
def _load_jobs():
    path = _jobs_file()
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)                       # duplicate keys are rejected elsewhere; this is our own file
    return data if isinstance(data, list) else []


def _save_jobs(jobs):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _jobs_file()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _update_job(job_id, **fields):
    with _LOCK:
        jobs = _load_jobs()
        for j in jobs:
            if j["id"] == job_id:
                j.update(fields)
        _save_jobs(jobs)


# ---------------------------------------------------------------- VoiceStudio
def list_profiles():
    """Saved voice profiles from VoiceStudio: [{"voice_id", "name"}, ...]."""
    resp = requests.get(f"{API_BASE}/audio/voices", headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    body = resp.json()
    items = body if isinstance(body, list) else (body.get("voices") or body.get("data") or body.get("items") or [])
    return [{"voice_id": v["voice_id"], "name": v.get("name") or v["voice_id"]}
            for v in items if isinstance(v, dict) and v.get("type") == "profile" and v.get("voice_id")]


def safe_voice_name(name):
    cleaned = _INVALID_NAME.sub("", name or "").strip()
    return cleaned or "voice"


def next_file_number(folder, voice_name):
    """One more than the highest <Voice>_NNNN.wav already in the folder, or 1."""
    if not folder.is_dir():
        return 1
    pattern = re.compile("^" + re.escape(safe_voice_name(voice_name)) + r"_(\d{4})$")
    highest = 0
    for f in folder.glob("*.wav"):
        m = pattern.match(f.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def _ledger_path(folder):
    return folder / "generated.json"


def _line_key(voice_id, text):
    return hashlib.sha1(f"{voice_id}\n{text.strip()}".encode("utf-8")).hexdigest()


def _load_ledger(folder):
    """What each folder already has: {"<voice>|<text hash>": "<file name>"}."""
    path = _ledger_path(folder)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    return data if isinstance(data, dict) else {}


def _save_ledger(folder, ledger):
    tmp = _ledger_path(folder).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _ledger_path(folder))


def _speak(text, voice_id):
    resp = requests.post(f"{API_BASE}/audio/speech", headers={**_auth_headers(), "Content-Type": "application/json"},
                         data=json.dumps({"model": MODEL, "voice": voice_id, "input": text,
                                          "response_format": FORMAT, "speed": SPEED}),
                         timeout=TIMEOUT)
    if not resp.ok:
        raise RuntimeError(f"VoiceStudio error {resp.status_code}: {resp.text[:200]}")
    if not resp.content:
        raise RuntimeError("No audio data was returned.")
    return resp.content


# ---------------------------------------------------------------- running one run
def run_job(job):
    """Generate every non-blank line of the job's text file. Updates progress as it goes."""
    input_file = Path(job["input_file"])
    out_dir = Path(job["output_folder"])
    lines = input_file.read_text(encoding="utf-8-sig").splitlines()
    todo = [(i + 1, t) for i, t in enumerate(lines) if t.strip()]
    prog = {"total": len(todo), "done": 0, "failed": 0, "skipped": len(lines) - len(todo)}
    _update_job(job["id"], progress=dict(prog))
    out_dir.mkdir(parents=True, exist_ok=True)

    number = next_file_number(out_dir, job["voice_name"])
    safe = safe_voice_name(job["voice_name"])
    ledger = _load_ledger(out_dir)
    report = []
    for line_no, text in todo:
        key = _line_key(job["voice_id"], text)
        done_name = ledger.get(key)
        # Skip-existing: this voice already made this text into this folder, and the file is still there
        if done_name and (out_dir / done_name).exists():
            prog["skipped"] += 1
            report.append({"Line": line_no, "File": done_name, "Status": "Skipped", "Error": "Already exists"})
            _update_job(job["id"], progress=dict(prog))
            continue
        name = f"{safe}_{number:04d}.wav"
        final = out_dir / name
        tmp = out_dir / (name + ".tmp")
        try:
            tmp.write_bytes(_speak(text, job["voice_id"]))
            os.replace(tmp, final)
            ledger[key] = name
            _save_ledger(out_dir, ledger)
            number += 1
            prog["done"] += 1
            report.append({"Line": line_no, "File": name, "Status": "Success", "Error": ""})
        except Exception as ex:                   # one bad line must not stop the run
            tmp.unlink(missing_ok=True)
            prog["failed"] += 1
            report.append({"Line": line_no, "File": name, "Status": "Failed", "Error": str(ex)})
        _update_job(job["id"], progress=dict(prog))

    report_path = out_dir / f"generation-report-{job['id']}.csv"
    with report_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["Line", "File", "Status", "Error"])
        w.writeheader()
        w.writerows(report)
    return prog, report_path


def _queue_loop():
    global _WORKER
    try:
        while True:
            with _LOCK:
                pending = [j for j in _load_jobs() if j["status"] == "Pending"]
            if not pending:
                break
            job = pending[0]
            _update_job(job["id"], status="Running", started_at=datetime.now().isoformat(timespec="seconds"))
            try:
                prog, report = run_job(job)
                _update_job(job["id"], status="Completed", finished_at=datetime.now().isoformat(timespec="seconds"),
                            result=f"OK {prog['done']}, Failed {prog['failed']}, Skipped {prog['skipped']}",
                            report=str(report))
            except Exception as ex:
                _update_job(job["id"], status="Failed", finished_at=datetime.now().isoformat(timespec="seconds"),
                            result=str(ex))
    finally:
        with _LOCK:
            _WORKER = None


def start_queue():
    """Start the queue thread unless it is already running. Returns True if started."""
    global _WORKER
    with _LOCK:
        jobs = _load_jobs()
        for j in jobs:                             # a run left "Running" means the app stopped mid-run
            if j["status"] == "Running":
                j["status"] = "Pending"
        _save_jobs(jobs)
        if _WORKER and _WORKER.is_alive():
            return False
        _WORKER = threading.Thread(target=_queue_loop, daemon=True)
        _WORKER.start()
        return True


# ---------------------------------------------------------------- routes
def _err(msg, code=400):
    return jsonify({"error": msg}), code


@bp.route("/api/vs/profiles")
def api_profiles():
    try:
        return jsonify({"profiles": list_profiles(), "server": API_BASE})
    except requests.RequestException as ex:
        return _err(f"Couldn't reach VoiceStudio at {API_BASE}: {ex}. Start VoiceStudio, "
                    "or set VOICESTUDIO_URL.", 502)


@bp.route("/api/vs/jobs")
def api_jobs():
    with _LOCK:
        jobs = _load_jobs()
    return jsonify({"jobs": jobs, "running": bool(_WORKER and _WORKER.is_alive()),
                    "data_dir": str(DATA_DIR)})


@bp.route("/api/vs/jobs", methods=["POST"])
def api_add_jobs():
    b = request.get_json(silent=True) or {}
    input_file = (b.get("input_file") or "").strip().strip('"')
    out = (b.get("output_folder") or "").strip().strip('"') or str(DATA_DIR)
    voices = b.get("voices") or []
    if not input_file or not Path(input_file).is_file():
        return _err(f"Text file not found: {input_file or '(none given)'}. Give the full path to a .txt file.")
    if not voices:
        return _err("Pick at least one voice profile.")
    lines = Path(input_file).read_text(encoding="utf-8-sig").splitlines()
    total = sum(1 for t in lines if t.strip())
    prog = {"total": total, "done": 0, "failed": 0, "skipped": len(lines) - total}
    now = datetime.now().isoformat(timespec="seconds")
    new = [{"id": uuid.uuid4().hex[:8], "input_file": input_file, "name": Path(input_file).stem,
            "output_folder": out, "voice_id": v["voice_id"], "voice_name": v.get("name") or v["voice_id"],
            "status": "Pending", "result": "", "progress": dict(prog),
            "created_at": now, "finished_at": ""} for v in voices if v.get("voice_id")]
    with _LOCK:
        jobs = _load_jobs() + new
        _save_jobs(jobs)
    return jsonify({"added": len(new)})


@bp.route("/api/vs/jobs/<jid>", methods=["DELETE"])
def api_remove_job(jid):
    with _LOCK:
        jobs = _load_jobs()
        target = next((j for j in jobs if j["id"] == jid), None)
        if not target:
            return _err("No run with that id.", 404)
        if target["status"] == "Running":
            return _err("That run is in progress and can't be removed yet.", 409)
        _save_jobs([j for j in jobs if j["id"] != jid])
    return jsonify({"removed": jid})


@bp.route("/api/vs/queue/start", methods=["POST"])
def api_start():
    started = start_queue()
    return jsonify({"started": started, "message": "" if started else "The queue is already running."})
