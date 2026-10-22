#!/usr/bin/env python3
"""
Audio podcast pipeline.

The --script file can hold multiple stories, separated by one or more blank
lines — each produces its own episode, sharing one sequence counter. Within
a story, a line containing exactly the TTS marker (default "===TTS===")
splits it into a display version (used for the title/image-prompt) and a
TTS-only version (used only for narration — e.g. with phonetic spellings).
No marker: the same text is used for both, same as before this feature.

Usage:
    python audio/audio_pipeline.py --script script.txt --intro intro.mp3 --outro outro.mp3

Produces, per story:
    output/EP-001_Pithy-Title.mp3
    output/EP-001_Pithy-Title_image_prompt.txt
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from steps import save_script
from utils import (
    load_config, get_next_sequence, build_filename, parse_script_file,
    generate_title, generate_image_prompt,
    synthesize_narration, concat_audio, loudnorm_audio,
)


def process_story(story, args, config, output_dir):
    display_text = story["display"]
    tts_text = story["tts"]

    print("→ Generating title...")
    title = generate_title(display_text, config)
    print(f"  Title: {title}")

    print(f"→ Synthesizing narration ({config['tts_engine']} TTS)...")
    narration_path = synthesize_narration(tts_text, config, output_dir)

    print("→ Combining intro + narration + outro...")
    combined_path = output_dir / "_combined_tmp.mp3"
    concat_audio([args.intro, narration_path, args.outro], combined_path)

    if config["audio"].get("loudnorm", True):
        print("→ Normalizing loudness...")
        normalized_path = output_dir / "_normalized_tmp.mp3"
        loudnorm_audio(combined_path, normalized_path)
        combined_path.unlink()
        combined_path = normalized_path

    seq = get_next_sequence(config["audio"]["sequence_file"])
    final_name = build_filename(config, seq, title, "mp3")
    final_path = output_dir / final_name
    combined_path.rename(final_path)
    narration_path.unlink(missing_ok=True)

    save_script(story, final_path, output_dir)

    print("→ Generating episode art prompt...")
    image_prompt = generate_image_prompt(display_text, config)
    prompt_path = output_dir / f"{final_path.stem}_image_prompt.txt"
    prompt_path.write_text(image_prompt, encoding="utf-8")

    print(f"\n✅ Done: {final_path}")
    print(f"🎨 Image prompt saved to: {prompt_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate finished audio podcast episode(s).")
    parser.add_argument("--script", required=True, help="Path to the script text file (may hold multiple stories)")
    parser.add_argument("--intro", required=True, help="Path to the intro audio file")
    parser.add_argument("--outro", required=True, help="Path to the outro audio file")
    parser.add_argument("--config", default=None, help="Config file (default: config.json next to this script)")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument("--start-over", action="store_true",
                        help="Forget which stories of this script are done and start from the first")
    parser.add_argument("--tts-engine", choices=["google", "piper", "kokoro"], default=None,
                         help="Override config's tts_engine for this run")
    parser.add_argument("--tts-marker", default=None,
                         help="Override config's script_parsing.tts_marker for this run")
    args = parser.parse_args()
    for n in ("script", "intro", "outro", "config", "output_dir"):
        v = getattr(args, n, None)
        if v:
            setattr(args, n, str(Path(v).resolve()))
    os.chdir(Path(__file__).resolve().parent)  # config, sequence file and output/ live in this folder

    config = load_config(args.config or "config.json")
    if args.tts_engine:
        config["tts_engine"] = args.tts_engine

    output_dir = Path(args.output_dir or config["audio"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    tts_marker = args.tts_marker or config.get("script_parsing", {}).get("tts_marker", "===TTS===")
    stories = parse_script_file(args.script, tts_marker)
    print(f"Found {len(stories)} story(ies) in {args.script}")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
    from progress import Progress, ask_continue, first_line
    prog = Progress(args.script, args.start_over)
    todo = prog.pending(stories)
    for n, (idx, story) in enumerate(todo):
        print(f"\n=== Story {idx}/{len(stories)} ===")
        process_story(story, args, config, output_dir)
        prog.mark_done(story)
        left = len(todo) - n - 1
        if left and not ask_continue(left, first_line(todo[n + 1][1])):
            break


if __name__ == "__main__":
    main()
