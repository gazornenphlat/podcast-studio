import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as scheduler_app


def test_series_cfg_unknown_returns_none():
    scheduler_app.load_config()
    assert scheduler_app.series_cfg("__does_not_exist__") is None


def test_api_token_defaults_none(monkeypatch):
    monkeypatch.delenv("CONTENT_SCHEDULER_API_TOKEN", raising=False)
    scheduler_app.CFG = {}
    assert scheduler_app.api_token() is None