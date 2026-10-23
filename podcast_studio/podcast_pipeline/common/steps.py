"""Helpers shared by the separate podcast processes (witn/, cocku/,
confuscius/, aesop/, audio/). Each process has its own script, config.json,
assets/ folder, sequence.json and output/ folder; this module only holds
the plumbing they have in common."""

import argparse
import copy
import os
from pathlib import Path

from utils import (
    split_first_line, split_sentences, split_into_portions,
    load_config, peek_next_sequence, set_sequence, build_filename, filename_prefix,
    find_variation_file, generate_title, generate_image_prompt, resolve_canvas,
    extract_audio, concat_audio, loudnorm_audio, mix_music_bed, get_duration,
)


def setup(script_file, description, add_args=None, need_video=True):
    """Common start-up for a process script. Resolves the user's path
    arguments, switches into the process's own folder (so its config.json,
    assets/, sequence.json and output/ are all local to it), loads config
    and returns (args, config, proc, output_dir, intro, middle, outro)."""
    base = Path(script_file).resolve().parent
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--script", required=True, help="Script text file (may hold several stories)")
    if need_video:
        p.add_argument("--intro", default=None, help="Override: intro video")
        p.add_argument("--middle", default=None, help="Override: middle video")
        p.add_argument("--outro", default=None, help="Override: outro video")
        p.add_argument("--tiktok", action="store_true", help="Also export a TikTok (9:16) version")
    p.add_argument("--config", default=None, help="Config file (default: config.json next to this script)")
    p.add_argument("--output-dir", default=None, help="Override output directory")
    p.add_argument("--tts-engine", choices=["google", "piper", "kokoro"], default=None)
    p.add_argument("--tts-marker", default=None)
    p.add_argument("--start-over", action="store_true",
                   help="Forget which stories of this script are done and start from the first")
    if add_args:
        add_args(p)
    args = p.parse_args()

    # Resolve anything the user typed relative to where they ran it from.
    for name in ("script", "intro", "middle", "outro", "outro2", "config", "output_dir"):
        v = getattr(args, name, None)
        if v:
            setattr(args, name, str(Path(v).resolve()))
    os.chdir(base)

    config = load_config(args.config or "config.json")
    if need_video and (config.get("scheduler") or {}).get("enabled"):
        args.tiktok = True      # scheduled episodes also go to 9:16 sites, so always make that version
    if args.tts_engine:
        config["tts_engine"] = args.tts_engine
    proc = config["process"]
    config = copy.deepcopy(config)
    config["naming"]["prefix"] = proc["prefix"]

    if need_video:
        output_dir = Path(args.output_dir or config["video"]["output_dir"])
    else:
        output_dir = Path(args.output_dir or config["audio"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    intro = middle = outro = None
    if need_video:
        intro = args.intro or find_variation_file(proc["folder"], "intro")
        middle = args.middle or find_variation_file(proc["folder"], "middle")
        outro = args.outro or find_variation_file(proc["folder"], "outro")
        print(f"→ Process: {proc['prefix']}  (folder: {base})")
        print(f"  intro:  {intro}\n  middle: {middle}\n  outro:  {outro}")
    return args, config, proc, output_dir, intro, middle, outro


def tts_marker(args, config):
    return args.tts_marker or config.get("script_parsing", {}).get("tts_marker", "===TTS===")


def save_script(story, final_path, output_dir):
    """Save the story's script next to the episode as <episode>_script.txt
    (the display text). If a separate TTS-only version was given with the
    ===TTS=== marker and it differs, it is saved as <episode>_script_tts.txt."""
    path = output_dir / f"{final_path.stem}_script.txt"
    path.write_text(story["display"].strip() + "\n", encoding="utf-8")
    print(f"📝 Script saved: {path}")
    if story["tts"].strip() != story["display"].strip():
        tts_path = output_dir / f"{final_path.stem}_script_tts.txt"
        tts_path.write_text(story["tts"].strip() + "\n", encoding="utf-8")
        print(f"📝 TTS script saved: {tts_path}")


def save_image_prompt(display_text, config, proc, final_path, output_dir):
    print("→ Generating episode art prompt...")
    prompt = generate_image_prompt(display_text, config,
                                   style=proc.get("image_style"), tone=proc.get("image_tone"))
    path = output_dir / f"{final_path.stem}_image_prompt.txt"
    path.write_text(prompt, encoding="utf-8")
    print(f"🎨 Image prompt saved to: {path}")


def build_companion_audio(intro, outro, narration_path, mp3_name, config, output_dir,
                          music=None, music_volume=0.25, music_fade=1.0):
    """Build an audio-only episode to go with a video: audio is extracted
    from the video's own intro/outro plus the same narration used in the
    video. `mp3_name` is the exact output filename to use (so it can share
    the primary episode's naming, or a variant's)."""
    intro_audio = output_dir / "_companion_intro_audio_tmp.mp3"
    outro_audio = output_dir / "_companion_outro_audio_tmp.mp3"
    extract_audio(intro, intro_audio)
    extract_audio(outro, outro_audio)

    combined_path = output_dir / "_companion_combined_tmp.mp3"
    concat_audio([intro_audio, narration_path, outro_audio], combined_path)

    if music:  # music bed under the narration only (not the intro/outro)
        mixed = output_dir / "_companion_music_tmp.mp3"
        mix_music_bed(combined_path, music, get_duration(intro_audio), get_duration(narration_path),
                      music_volume, music_fade, mixed, has_video=False)
        combined_path.unlink()
        combined_path = mixed

    if config["audio"].get("loudnorm", True):
        normalized_path = output_dir / "_companion_normalized_tmp.mp3"
        loudnorm_audio(combined_path, normalized_path)
        combined_path.unlink()
        combined_path = normalized_path

    final_path = output_dir / mp3_name
    combined_path.rename(final_path)

    for tmp in [intro_audio, outro_audio]:
        Path(tmp).unlink(missing_ok=True)

    return final_path


# ---------------------------------------------------------------------------
# Aesop: prepare (title + up to 3 image prompts) -> pause for images -> build
# ---------------------------------------------------------------------------

def story_portions(story, max_images):
    """Split one story into up to `max_images` portions for image purposes.
    Returns (tts_first, tts_rest_chunks, display_portions): the first line
    (narrated alone, then a pause), the rest of the narration split into one
    chunk per portion, and the display-text for each portion (used for the
    image prompt; portion 1 includes the first line). Short stories get fewer
    portions — never more than one per sentence of the rest."""
    tts_first, tts_rest = split_first_line(story["tts"])
    disp_first, disp_rest = split_first_line(story["display"])
    k = max(1, min(max_images, len(split_sentences(disp_rest)), len(split_sentences(tts_rest))))
    if not tts_rest.strip() or k == 1:
        rest_chunks = [tts_rest] if tts_rest.strip() else []
        return tts_first, rest_chunks, [story["display"]]
    tts_chunks = split_into_portions(tts_rest, k)
    disp_chunks = split_into_portions(disp_rest, k)
    k = min(len(tts_chunks), len(disp_chunks))
    tts_chunks, disp_chunks = tts_chunks[:k - 1] + [" ".join(tts_chunks[k - 1:])], \
                              disp_chunks[:k - 1] + [" ".join(disp_chunks[k - 1:])]
    disp_chunks[0] = disp_first + "\n" + disp_chunks[0]
    return tts_first, tts_chunks, disp_chunks


def prepare_aesop_batch(stories, config, proc, output_dir, intro, max_images=None):
    """Before any narration or video work: generate each story's title and
    up to `max_images` Aesop's-Fables-style image prompts (one per portion of
    the story), reserve its sequence number, save the prompts, and show them
    with the exact .jpg filenames to save the images as. One dict per story."""
    aesop_cfg = config["video"]["aesop"]
    max_images = max(1, min(3, int(max_images or aesop_cfg.get("max_images", 3))))
    canvas_w, canvas_h, _ = resolve_canvas(intro, config["video"].get("canvas"))
    base_seq = peek_next_sequence(proc["sequence_file"])
    style, tone = proc.get("image_style"), proc.get("image_tone")

    prepared = []
    for i, story in enumerate(stories):
        seq = base_seq + i
        print(f"\n=== Preparing story {i + 1}/{len(stories)} ===")
        if proc.get("title_from_first_line"):
            title = split_first_line(story["display"])[0]
        else:
            print("→ Generating title...")
            title = generate_title(story["display"], config)
        print(f"  Title: {title}")

        _, _, portions = story_portions(story, max_images)
        n = len(portions)
        stem = Path(build_filename(config, seq, title, "jpg")).stem
        images = []
        for j, text in enumerate(portions, start=1):
            print(f"→ Generating image prompt {j}/{n}...")
            note = None
            if n > 1:
                note = (f"This is scene {j} of {n} illustrating ONE story, in order. Keep the "
                        "characters, their look and the setting consistent across all scenes. "
                        "Describe only the moment in the portion of the script below.")
            prompt = generate_image_prompt(text, config, style=style, tone=tone, scene_note=note)
            name = f"{stem}.jpg" if n == 1 else f"{stem}_{j}.jpg"
            images.append({"n": j, "prompt": prompt, "path": output_dir / name})

        prompt_path = output_dir / f"{stem}_image_prompt.txt"
        if n == 1:
            prompt_path.write_text(images[0]["prompt"], encoding="utf-8")
        else:
            prompt_path.write_text(
                "\n\n".join(f"IMAGE {im['n']} of {n} — save as {im['path'].name}\n{im['prompt']}"
                             for im in images), encoding="utf-8")
        prepared.append({"title": title, "seq": seq, "stem": stem, "images": images,
                         "prompt_path": prompt_path})

    bar = "=" * 72
    for i, prep in enumerate(prepared, start=1):
        n = len(prep["images"])
        for im in prep["images"]:
            which = f" — image {im['n']} of {n}" if n > 1 else ""
            print(f"\n{bar}")
            print(f"🎨 IMAGE NEEDED — story {i}/{len(prepared)}: {prep['title']}{which}")
            print("-" * 72)
            print(im["prompt"])
            print("-" * 72)
            print("Save your image as:")
            print(f"    {im['path']}")
        print(f"(Prompts also saved to: {prep['prompt_path']})")
    print(f"\n{bar}")
    print(f"Tip: your video canvas is {canvas_w}x{canvas_h} — images with that "
          "aspect ratio fill the frame; anything else is fitted "
          f"({aesop_cfg.get('image_fit', 'blur_pad')}). Make images in order — "
          "each one fades in over the last as the story reaches its part.")
    return prepared


def locate_images(prep, config, output_dir):
    """Find every image for one story. Exact expected names are used as-is.
    If some are missing and there are exactly as many other jpg/jpeg files
    carrying this episode's number (e.g. left over from an earlier run whose
    generated title differed), they are renamed, in filename order, to the
    expected names. Returns the list of missing paths (empty when complete)."""
    images = prep["images"]
    missing = [im for im in images if not im["path"].exists()]
    if missing:
        prefix = filename_prefix(config, prep["seq"])
        expected = {im["path"].name for im in images}
        for ext in ("jpg", "jpeg"):
            extras = [f for f in sorted(output_dir.glob(f"{prefix}*.{ext}")) if f.name not in expected]
            if len(extras) == len(missing):
                for im, found in zip(missing, extras):
                    found.rename(im["path"])
                    print(f"  (found {found.name} — renamed to {im['path'].name} to match the episode)")
                missing = []
                break
    return [im["path"] for im in images if not im["path"].exists()]


def wait_for_images(prepared, config, output_dir):
    """Pause until every story's images are all in place."""
    total = sum(len(p["images"]) for p in prepared)
    plural = "s" if total > 1 else ""
    while True:
        try:
            answer = input(f"\nCreate the image{plural} and save {'them' if plural else 'it'} "
                           "as shown above, then press Enter to continue (or q to quit): ")
        except EOFError:
            raise SystemExit("Aesop mode pauses for you to create the images, so it needs "
                             "an interactive terminal.")
        if answer.strip().lower() in ("q", "quit", "exit"):
            print(f"Stopped before building anything. Prompts are saved in {output_dir}.")
            raise SystemExit(0)

        missing = [m for p in prepared for m in locate_images(p, config, output_dir)]
        if not missing:
            print("✓ All images found — continuing.")
            return
        print("\n⚠️  Still missing:")
        for m in missing:
            print(f"    {m}")
