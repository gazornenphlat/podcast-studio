"""build_looped_video must produce the right length and decode cleanly, even when the
middle clip's codec differs from the reversed copy (the old stream-copy concat broke)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import utils  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="needs ffmpeg and ffprobe on PATH")


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout)


@pytest.mark.parametrize("codec", ["mpeg4", "libx264"])
def test_loop_length_and_decode(tmp_path, codec):
    src = tmp_path / "middle.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=25:duration=3", "-c:v", codec, "-pix_fmt", "yuv420p",
                    str(src)], check=True)
    out = utils.build_looped_video(str(src), 7.5, str(tmp_path / "loop.mp4"))
    assert abs(_duration(out) - 7.5) < 0.1
    errors = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"],
                            capture_output=True, text=True).stderr.strip()
    assert errors == ""
