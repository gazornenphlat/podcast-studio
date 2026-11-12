"""A --test run must never change which stories are done, or clear them."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

import progress as P  # noqa: E402


@pytest.fixture
def folder(monkeypatch):
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.chdir(d)
        script = Path(d) / "script.txt"
        script.write_text("x\n", encoding="utf-8")
        key = str(script.resolve()).lower()
        Path(d, "progress.json").write_text(json.dumps({key: {"done": ["abc"], "rewrites": {}}}), encoding="utf-8")
        try:
            yield Path(d), script, key
        finally:
            # Windows can't delete the folder while it is the working directory,
            # so leave it before the temp folder is removed.
            os.chdir(orig)
            monkeypatch.delenv("PODCAST_TEST_RUN", raising=False)


def test_test_run_start_over_keeps_real_progress(folder, monkeypatch):
    d, script, key = folder
    monkeypatch.setenv("PODCAST_TEST_RUN", "1")
    prog = P.Progress(script, start_over=True)
    assert prog.me["done"] == []                       # this run starts from the first story...
    prog.set_rewrite("raw story", "rewritten")          # ...and may cache a rewrite
    on_disk = json.loads((d / "progress.json").read_text(encoding="utf-8"))
    assert on_disk[key]["done"] == ["abc"]              # real progress untouched
    assert list(on_disk[key]["rewrites"].values()) == ["rewritten"]


def test_real_start_over_clears_progress(folder, monkeypatch):
    d, script, key = folder
    monkeypatch.delenv("PODCAST_TEST_RUN", raising=False)
    P.Progress(script, start_over=True)
    on_disk = json.loads((d / "progress.json").read_text(encoding="utf-8"))
    assert on_disk.get(key, {}).get("done", []) == []
