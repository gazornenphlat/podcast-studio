"""VoiceStudio batch queue: numbering, blank lines, failures, progress and the queue order.
Uses a stand-in VoiceStudio server, and a temp folder for the data."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import voicestudio_batch as VB  # noqa: E402


class Fake(BaseHTTPRequestHandler):
    fail_on = set()          # input texts that should fail
    calls = []

    def do_GET(self):
        body = {"voices": [{"type": "profile", "voice_id": "v1", "name": "Blue Nun"},
                           {"type": "profile", "voice_id": "v2", "name": "Bad/Name"},
                           {"type": "preset", "voice_id": "x", "name": "skip me"}]}
        self._send(200, json.dumps(body).encode(), "application/json")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        Fake.calls.append((req["voice"], req["input"]))
        if req["input"] in Fake.fail_on:
            self._send(500, b"boom", "text/plain")
        else:
            self._send(200, b"RIFF0000WAVE", "audio/wav")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(VB, "API_BASE", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    monkeypatch.setattr(VB, "DATA_DIR", tmp_path / "data")
    Fake.fail_on = set()
    Fake.calls = []
    yield tmp_path
    srv.shutdown()


def _wait_idle():
    for _ in range(300):
        with VB._LOCK:
            busy = VB._WORKER is not None
        if not busy:
            return
        time.sleep(0.05)
    raise AssertionError("queue did not finish")


def _text(tmp, lines, name="story.txt"):
    p = tmp / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_profiles_only_lists_profiles(env):
    assert VB.list_profiles() == [{"voice_id": "v1", "name": "Blue Nun"},
                                  {"voice_id": "v2", "name": "Bad/Name"}]


def test_run_skips_blank_lines_and_numbers_files(env):
    txt = _text(env, ["first", "", "second", "   ", "third"])
    out = env / "out"
    jobs = [{"id": "j1", "input_file": str(txt), "output_folder": str(out), "voice_id": "v1",
             "voice_name": "Blue Nun", "status": "Pending"}]
    VB._save_jobs(jobs)
    VB.start_queue()
    _wait_idle()
    names = sorted(p.name for p in out.glob("*.wav"))
    assert names == ["Blue Nun_0001.wav", "Blue Nun_0002.wav", "Blue Nun_0003.wav"]
    job = VB._load_jobs()[0]
    assert job["status"] == "Completed"
    assert job["progress"] == {"total": 3, "done": 3, "failed": 0, "skipped": 2}
    assert (out / "generation-report-j1.csv").exists()


def test_numbering_continues_and_bad_name_is_cleaned(env):
    txt = _text(env, ["hello"])
    out = env / "out"
    out.mkdir(parents=True)
    (out / "BadName_0007.wav").write_bytes(b"x")
    VB._save_jobs([{"id": "j2", "input_file": str(txt), "output_folder": str(out), "voice_id": "v2",
                    "voice_name": "Bad/Name", "status": "Pending"}])
    VB.start_queue()
    _wait_idle()
    assert (out / "BadName_0008.wav").exists()


def test_failed_line_is_recorded_and_run_continues(env):
    txt = _text(env, ["good", "bad", "good again"])
    Fake.fail_on = {"bad"}
    out = env / "out"
    VB._save_jobs([{"id": "j3", "input_file": str(txt), "output_folder": str(out), "voice_id": "v1",
                    "voice_name": "Blue Nun", "status": "Pending"}])
    VB.start_queue()
    _wait_idle()
    job = VB._load_jobs()[0]
    assert job["progress"]["done"] == 2 and job["progress"]["failed"] == 1
    assert job["result"] == "OK 2, Failed 1, Skipped 0"
    assert sorted(p.name for p in out.glob("*.wav")) == ["Blue Nun_0001.wav", "Blue Nun_0002.wav"]


def test_queue_runs_in_order_and_pending_only(env):
    a = _text(env, ["a1"], "a.txt")
    b = _text(env, ["b1"], "b.txt")
    VB._save_jobs([
        {"id": "first", "input_file": str(a), "output_folder": str(env / "o"), "voice_id": "v1",
         "voice_name": "Blue Nun", "status": "Pending"},
        {"id": "second", "input_file": str(b), "output_folder": str(env / "o"), "voice_id": "v2",
         "voice_name": "Bad/Name", "status": "Pending"},
    ])
    VB.start_queue()
    _wait_idle()
    assert [c[1] for c in Fake.calls] == ["a1", "b1"]
    assert [j["status"] for j in VB._load_jobs()] == ["Completed", "Completed"]


def test_interrupted_run_is_put_back_as_pending(env):
    txt = _text(env, ["x"])
    VB._save_jobs([{"id": "j9", "input_file": str(txt), "output_folder": str(env / "o"), "voice_id": "v1",
                    "voice_name": "Blue Nun", "status": "Running"}])
    VB.start_queue()
    _wait_idle()
    assert VB._load_jobs()[0]["status"] == "Completed"


def test_cannot_remove_running_job(env):
    VB._save_jobs([{"id": "r1", "input_file": "x", "output_folder": "o", "voice_id": "v1",
                    "voice_name": "n", "status": "Running"}])
    app = __import__("flask").Flask(__name__)
    app.register_blueprint(VB.bp)
    c = app.test_client()
    assert c.delete("/api/vs/jobs/r1").status_code == 409
    assert len(VB._load_jobs()) == 1
