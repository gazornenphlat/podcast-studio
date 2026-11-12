import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from utils import load_json_file, load_config  # noqa: E402


def test_duplicate_key_names_file_and_key():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text('{"tts_engine": "google", "tts_engine": "kokoro"}', encoding="utf-8")
        with pytest.raises(ValueError) as err:
            load_json_file(p)
        assert "tts_engine" in str(err.value) and str(p) in str(err.value)


def test_duplicate_nested_key_is_caught():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text('{"kokoro": {"voice": "a"}, "x": {"kokoro": 1, "kokoro": 2}}', encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(p)


def test_valid_json_loads():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        p.write_text('{"a": {"b": 1}, "c": [1, 2]}', encoding="utf-8")
        assert load_json_file(p) == {"a": {"b": 1}, "c": [1, 2]}
