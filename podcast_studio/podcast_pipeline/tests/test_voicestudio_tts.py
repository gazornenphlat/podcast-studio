"""VoiceStudio as a TTS engine: posts to /v1/audio/speech and writes the returned audio.
Uses a stand-in HTTP server, so no VoiceStudio install is needed."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import utils  # noqa: E402

WAV = b"RIFF" + b"\x00" * 40  # stand-in bytes; only the write is checked


class Fake(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        Fake.seen = {"path": self.path, "body": json.loads(self.rfile.read(n)),
                     "auth": self.headers.get("Authorization")}
        if Fake.seen["body"].get("voice") == "bad":
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"no such voice"}}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.end_headers()
        self.wfile.write(WAV)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_posts_speech_request_and_writes_audio(server, tmp_path):
    cfg = {"tts_engine": "voicestudio", "voicestudio": {"server_url": server, "voice": "Narrator", "model": "omnivoice"}}
    out = utils.synthesize_narration("Hello there.", cfg, tmp_path, base_name="t")
    assert out.name == "t.wav" and out.read_bytes() == WAV
    assert Fake.seen["path"] == "/v1/audio/speech"
    assert Fake.seen["body"]["voice"] == "Narrator"
    assert Fake.seen["body"]["response_format"] == "wav"
    assert Fake.seen["auth"] is None  # loopback-style call: no key sent


def test_api_key_sent_as_bearer(server, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICESTUDIO_API_KEY", "secret")
    cfg = {"tts_engine": "voicestudio", "voicestudio": {"server_url": server, "voice": "Narrator"}}
    utils.synthesize_narration("Hi.", cfg, tmp_path, base_name="k")
    assert Fake.seen["auth"] == "Bearer secret"


def test_server_error_is_actionable(server, tmp_path):
    cfg = {"tts_engine": "voicestudio", "voicestudio": {"server_url": server, "voice": "bad"}}
    with pytest.raises(RuntimeError, match="VoiceStudio error \\(400\\)"):
        utils.synthesize_narration("Hi.", cfg, tmp_path, base_name="e")


def test_unreachable_names_the_setting(tmp_path):
    cfg = {"tts_engine": "voicestudio", "voicestudio": {"server_url": "http://127.0.0.1:9", "voice": "x"}}
    with pytest.raises(RuntimeError, match="voicestudio.server_url"):
        utils.synthesize_narration("Hi.", cfg, tmp_path, base_name="u")
