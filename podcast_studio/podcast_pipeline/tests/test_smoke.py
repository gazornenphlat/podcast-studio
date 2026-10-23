import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from utils import load_config, parse_script_file, slugify_title


def test_parse_script_file_basic():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.txt"
        p.write_text("Story one line.\n\nStory two line.\n===TTS===\ntts two.\n", encoding="utf-8")
        # tts marker only applies within a block; second block has marker
        stories = parse_script_file(p)
        assert len(stories) == 2
        assert stories[0]["display"] == "Story one line."
        assert stories[0]["tts"] == "Story one line."
        assert stories[1]["display"] == "Story two line."
        assert stories[1]["tts"] == "tts two."


def test_slugify_title():
    assert slugify_title("Hello World! Test") == "Hello-World-Test"


def test_load_config_duplicate_keys_raises():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text('{"a": 1, "a": 2}', encoding="utf-8")
        try:
            load_config(p)
        except ValueError:
            return
        raise AssertionError("expected ValueError on duplicate key")