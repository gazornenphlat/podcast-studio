import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as scheduler_app  # noqa: E402
import studio  # noqa: E402


def test_duplicate_yaml_key_is_refused():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.yaml"
        p.write_text("sites:\n  youtube:\n    api: youtube\n  youtube:\n    api: none\n", encoding="utf-8")
        with pytest.raises(ValueError) as err:
            scheduler_app.load_yaml_file(p)
        assert "youtube" in str(err.value)


def test_valid_yaml_loads():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.yaml"
        p.write_text("a:\n  b: 1\nlist: [x, y]\n", encoding="utf-8")
        assert scheduler_app.load_yaml_file(p) == {"a": {"b": 1}, "list": ["x", "y"]}


def test_video_never_auto_posted_to_x_or_instagram(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler_app, "CFG", {"sites": {
        "twitter": {"auto_post": True, "api": "twitter", "api_key": "k", "api_secret": "s",
                    "access_token": "t", "access_secret": "x"},
        "instagram": {"auto_post": True, "api": "instagram", "ig_user_id": "1", "access_token": "t"},
    }})
    monkeypatch.setattr(scheduler_app, "media_file", lambda site, m: "/fake/ep.mp4")
    monkeypatch.setattr(scheduler_app.os.path, "exists", lambda p: True)
    st = {"media": {"Ep 1": {"file": "ep.mp4"}}}
    post = {"title": "Ep 1", "description": "desc"}
    for site in ("twitter", "instagram"):
        assert scheduler_app.auto_post(site, post, st, "Ep 1") is False
    assert calls == []


def test_studio_parses_pipeline_output():
    lines = [
        "=== Story 1/1 ===",
        "🎨 IMAGE NEEDED — story 1/1: Fox Tale — image 2 of 3",
        "-" * 72,
        "A fox in a meadow.",
        "-" * 72,
        "Save your image as:",
        "    output/WITN-001_Fox_Tale_2.jpg",
    ]
    imgs = studio.needed_images(lines, "witn")
    assert imgs and imgs[0]["title"] == "Fox Tale" and imgs[0]["n"] == 2 and imgs[0]["of"] == 3
    assert imgs[0]["prompt"] == "A fox in a meadow."


def test_studio_survives_absolute_image_path():
    lines = ["🎨 IMAGE NEEDED — story 1/1: Abs Path", "-" * 72, "prompt", "-" * 72,
             "Save your image as:", "    D:/elsewhere/WITN-001.jpg"]
    imgs = studio.needed_images(lines, "witn")
    assert imgs and imgs[0]["path"].endswith("WITN-001.jpg")
