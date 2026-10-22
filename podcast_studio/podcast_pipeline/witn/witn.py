#!/usr/bin/env python3
"""WITN process - rewrite + image-story flow.

  0. Rewrite: every story in script-in.txt (stories separated by a blank line)
     is rewritten by Ollama and titled, then saved to script.txt as
     "Title" on the first line, the story right under it, a blank line
     between stories. (Skip this by passing --script instead.)
  1. Title + up to 3 image prompts per story (one per part of the story), then
     the run PAUSES while you create the images and save them under the printed
     names (<episode>_1.jpg, _2.jpg, _3.jpg; just <episode>.jpg for one).
     Also saved before the pause: <episode>.txt per story and one
     WITN-<numbers>_Stories.docx with every title, story and image prompt.
  2. intro -> middle video (plays once, normal speed, no script) -> your images
     while the script is read (title, short pause, the story; each later
     image fades in as its part of the story begins) -> outro, all crossfaded.
  3. Optional music bed: assets/middle.mp3 plays under the middle video and the
     story segment (not intro/outro) at video.music.volume (or --music-volume).

    python witn/witn.py [--script-in script-in.txt] [--tiktok] [--images 1-3] [--music-volume 0.3]
    python witn/witn.py --script script.txt ...      # already-written script, no rewrite

Needs an interactive terminal (it waits for Enter). Everything lives in this
folder: config.json, assets/{intro,middle,outro}.* (+ optional middle.mp3),
sequence.json, output/. The engine is shared in common/image_flow.py.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from image_flow import run


def _pop_arg(argv, name):
    """Remove `name VALUE` / `name=VALUE` from argv and return VALUE (or None)."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            v = argv[i + 1]; del argv[i:i + 2]; return v
        if a.startswith(name + "="):
            del argv[i]; return a.split("=", 1)[1]
    return None


def _find(path):
    p = Path(path)
    if p.exists():
        return p.resolve()
    if not p.is_absolute() and (HERE / p).exists():
        return (HERE / p).resolve()
    return None


def _config_path(argv):
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            return Path(argv[i + 1]).resolve()
        if a.startswith("--config="):
            return Path(a.split("=", 1)[1]).resolve()
    return HERE / "config.json"


def main():
    argv = sys.argv[1:]
    script_in = _pop_arg(argv, "--script-in")
    script = _pop_arg(argv, "--script")
    if script and Path(script).stem.lower().startswith("script-in"):
        script_in, script = script, None        # --script script-in.txt still means "rewrite it"
    if script and not script_in:
        print(f"Using {script} as-is (no Ollama rewrite): first line = title, then the story.")
        argv += ["--script", script]
    else:
        if any(a in ("-h", "--help") for a in argv):
            print(__doc__)
        src = _find(script_in or "script-in.txt")
        if src is None:
            raise SystemExit(f"Can't find {script_in or 'script-in.txt'} (looked here and in {HERE}). "
                             "Pass --script-in FILE, or --script FILE to skip the rewrite.")
        out = src.with_name("script.txt")
        if not out.exists():
            out.write_text("", encoding="utf-8")
        argv += ["--script", str(out)]       # filled in story by story as each is rewritten
        sys.argv = [sys.argv[0]] + argv
        run(__file__, "WITN process", rewrite_in=src)
        return
    sys.argv = [sys.argv[0]] + argv
    run(__file__, "WITN process")


if __name__ == "__main__":
    main()
