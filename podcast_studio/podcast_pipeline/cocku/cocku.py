#!/usr/bin/env python3
"""COCku process — middle video dims and the script scrolls over it while read
aloud (pause before/after), crossfaded with intro/outro. Saves the intro copy
and the processed middle alongside each episode. Optional assets/outro-2.* builds a full _alt-ending video, mp3 and TikTok.

    python cocku/cocku.py --script script.txt [--tiktok] [--outro2 file]

Everything lives in this folder: config.json, assets/{intro,middle,outro}.*,
sequence.json, output/.
"""
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

import markers as M
from schedule_handoff import hand_off
from steps import setup, tts_marker, build_companion_audio, save_image_prompt, save_script
from utils import (
    get_next_sequence, build_filename, parse_script_file, generate_title,
    synthesize_narration, get_duration, build_cocku_middle, crossfade_videos,
    tiktok_export, find_variation_file_optional,
)


def process_story(story, args, config, proc, output_dir, intro, middle, outro, outro2):
    fade = config["video"].get("crossfade_seconds", 0.5)
    canvas = config["video"].get("canvas")
    print("→ Generating title...")
    title = generate_title(story["display"], config)
    print(f"  Title: {title}")

    print(f"→ Synthesizing narration ({config['tts_engine']} TTS)...")
    narration_path = synthesize_narration(story["tts"], config, output_dir)
    print(f"  Narration length: {get_duration(narration_path):.1f}s")

    print("→ Looping middle, dimming and scrolling the script over it...")
    middle_final = output_dir / "_middle_final_tmp.mp4"
    build_cocku_middle(middle, narration_path, story["display"], config, middle_final)

    print("→ Crossfading intro → middle → outro...")
    combined = output_dir / "_combined_tmp.mp4"
    crossfade_videos(intro, middle_final, outro, combined, fade, canvas)

    seq = get_next_sequence(proc["sequence_file"])
    final_path = output_dir / build_filename(config, seq, title, "mp4")
    combined.rename(final_path)

    print("→ Building companion audio episode...")
    print("🎧 Audio version: " + str(build_companion_audio(
        intro, outro, narration_path, build_filename(config, seq, title, "mp3"), config, output_dir)))

    intro_save = output_dir / f"{final_path.stem}_intro{Path(intro).suffix}"
    shutil.copy2(intro, intro_save)
    print(f"🎬 Intro saved: {intro_save}")
    middle_save = output_dir / f"{final_path.stem}_middle.mp4"
    middle_final.replace(middle_save)
    print(f"🎬 Processed middle saved: {middle_save}")

    if outro2 is not None:
        print("→ Building alternate-ending version (outro-2)...")
        alt_tmp = output_dir / "_alt_combined_tmp.mp4"
        crossfade_videos(intro, middle_save, outro2, alt_tmp, fade, canvas)
        alt_final = output_dir / f"{final_path.stem}_alt-ending.mp4"
        alt_tmp.rename(alt_final)
        print(f"🎬 Alternate ending saved: {alt_final}")
        print("🎧 Alt-ending audio version: " + str(build_companion_audio(
            intro, outro2, narration_path, f"{final_path.stem}_alt-ending.mp3", config, output_dir)))
        if args.tiktok:
            tk = output_dir / f"{alt_final.stem}_tiktok.mp4"
            tiktok_export(alt_final, tk, config)
            print(f"📱 Alt-ending TikTok version: {tk}")

    narration_path.unlink(missing_ok=True)
    print(f"\n{M.DONE} {final_path}")
    if args.tiktok:
        tk = output_dir / f"{final_path.stem}_tiktok.mp4"
        tiktok_export(final_path, tk, config)
        print(f"📱 TikTok version: {tk}")
    save_script(story, final_path, output_dir)
    save_image_prompt(story["display"], config, proc, final_path, output_dir)
    hand_off(config, title, final_path,
             tiktok=output_dir / f"{final_path.stem}_tiktok.mp4" if args.tiktok else None,
             mp3=final_path.with_suffix(".mp3"),
             script=output_dir / f"{final_path.stem}_script.txt")


def main():
    def extra(p):
        p.add_argument("--outro2", default=None, help="Override: alternate-ending outro video")
    args, config, proc, output_dir, intro, middle, outro = setup(__file__, "COCku process", extra)
    outro2 = args.outro2 or find_variation_file_optional(proc["folder"], "outro-2")
    if outro2:
        print(f"  outro-2 (alt ending): {outro2}")
    stories = parse_script_file(args.script, tts_marker(args, config))
    print(f"Found {len(stories)} story(ies) in {args.script}")
    from progress import Progress, ask_continue, first_line
    prog = Progress(args.script, args.start_over)
    todo = prog.pending(stories)
    for n, (i, story) in enumerate(todo):
        print(f"\n{M.STORY_HEADER} {i}/{len(stories)} ===")
        process_story(story, args, config, proc, output_dir, intro, middle, outro, outro2)
        prog.mark_done(story)
        left = len(todo) - n - 1
        if left and not ask_continue(left, first_line(todo[n + 1][1])):
            break


if __name__ == "__main__":
    main()
