#!/usr/bin/env python3
"""Aesop process - image-story flow.

  1. Title + up to 3 image prompts per story (one per part of the story), then
     the run PAUSES while you create the images and save them under the printed
     names (<episode>_1.jpg, _2.jpg, _3.jpg; just <episode>.jpg for one).
  2. intro -> middle video (plays once, normal speed, no script) -> your images
     while the script is read (first line, short pause, the rest; each later
     image fades in as its part of the story begins) -> outro, all crossfaded.
  3. Optional music bed: assets/middle.mp3 plays under the middle video and the
     story segment (not intro/outro) at video.music.volume (or --music-volume).

    python aesop/aesop.py --script script.txt [--tiktok] [--images 1-3] [--music-volume 0.3]

Needs an interactive terminal (it waits for Enter). Everything lives in this
folder: config.json, assets/{intro,middle,outro}.* (+ optional middle.mp3),
sequence.json, output/. The engine is shared in common/image_flow.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from image_flow import run

if __name__ == "__main__":
    run(__file__, "Aesop process")
