"""The image-story flow shared by the aesop/ and witn/ processes (each keeps
its own script, config, assets, counter and output).

  1. Title + up to 3 image prompts per story, then PAUSE for you to make the
     images (<episode>_1.jpg, _2.jpg, _3.jpg; just <episode>.jpg for one).
  2. intro -> middle video (once, normal speed, no script) -> your images
     while the script is read (first line, pause, the rest; each later image
     fades in as its part begins) -> outro, all crossfaded.
  3. Optional music bed: assets/middle.mp3 plays under the middle video and
     the story segment (not the intro/outro), at video.music.volume.
"""

import copy
from pathlib import Path

from schedule_handoff import hand_off
from steps import (setup, tts_marker, build_companion_audio, prepare_aesop_batch,
                   wait_for_images, story_portions, save_script)
from utils import (
    build_filename, set_sequence, parse_script_file, find_music_bed, mix_music_bed,
    synthesize_narration, get_duration, crossfade_many, tiktok_export,
    build_aesop_story_segment, ensure_audio_stream, pad_audio_to_duration, concat_audio,
    run as run_cmd,
)


def process_story(story, args, config, proc, output_dir, intro, middle, outro, prepared, music):
    fade = config["video"].get("crossfade_seconds", 0.5)
    canvas = config["video"].get("canvas")
    mcfg = config["video"].get("music", {})
    volume = args.music_volume if args.music_volume is not None else mcfg.get("volume", 0.25)
    music_fade = mcfg.get("fade_seconds", 1.0)
    title = prepared["title"]
    first, rest_chunks, _ = story_portions(story, len(prepared["images"]))
    image_paths = [im["path"] for im in prepared["images"]]

    print(f"→ Synthesizing first-line narration ({config['tts_engine']} TTS)...")
    n1 = synthesize_narration(first, config, output_dir, base_name="_narration1_tmp")
    rest_audio = []
    for j, chunk in enumerate(rest_chunks, start=1):
        print(f"→ Synthesizing narration part {j}/{len(rest_chunks)}...")
        rest_audio.append(synthesize_narration(chunk, config, output_dir, base_name=f"_narration_part{j}_tmp"))

    title_img = find_title_image(proc)
    if title_img:
        return process_story_title_card(story, args, config, proc, output_dir, intro, outro,
                                        prepared, music, title, image_paths, n1, rest_audio, title_img)

    pause = config["video"]["aesop"].get("pause_after_first_line_seconds", 2)
    print(f"→ Building the image segment ({len(image_paths)} image(s), {pause}s pause after the first line)...")
    story_seg = output_dir / "_story_tmp.mp4"
    narration = output_dir / "_narration_full_tmp.mp3"
    build_aesop_story_segment(image_paths, n1, rest_audio, intro, config, story_seg, narration)
    for tmp in [n1, *rest_audio]:
        tmp.unlink(missing_ok=True)

    print("→ Preparing the middle clip (plays once, normal speed, no script)...")
    middle_ready = ensure_audio_stream(middle, output_dir / "_middle_audio_tmp.mp4")

    print("→ Crossfading intro → middle → image segment → outro...")
    combined = output_dir / "_combined_tmp.mp4"
    crossfade_many([intro, middle_ready, story_seg, outro], combined, fade, canvas)
    print(f"  Narration length (incl. pause): {get_duration(narration):.1f}s")

    if music:
        i_dur, m_dur, s_dur = get_duration(intro), get_duration(middle_ready), get_duration(story_seg)
        start = i_dur - fade                       # where the middle begins
        end = i_dur + m_dur + s_dur - 2 * fade     # where the story segment ends
        print(f"→ Mixing music bed ({Path(music).name}, volume {volume}) under the middle and story...")
        mixed = output_dir / "_combined_music_tmp.mp4"
        mix_music_bed(combined, music, start, end - start, volume, music_fade, mixed)
        combined.unlink()
        combined = mixed

    set_sequence(proc["sequence_file"], prepared["seq"])
    final_path = output_dir / build_filename(config, prepared["seq"], title, "mp4")
    combined.rename(final_path)

    print("→ Building companion audio episode...")
    print("🎧 Audio version: " + str(build_companion_audio(
        intro, outro, narration, build_filename(config, prepared["seq"], title, "mp3"),
        config, output_dir, music=music, music_volume=volume, music_fade=music_fade)))

    saved = output_dir / f"{final_path.stem}_story.mp4"
    story_seg.replace(saved)
    print(f"🎬 Narrated image segment saved: {saved}")

    if proc.get("save_narration"):
        nsave = output_dir / f"{final_path.stem}_narration.mp3"
        narration.replace(nsave)
        print(f"🗣️ Narration-only file saved: {nsave}")
    narration.unlink(missing_ok=True)
    if middle_ready is not middle:
        middle_ready.unlink(missing_ok=True)

    print(f"\n✅ Done: {final_path}")
    if args.tiktok:
        tk = output_dir / f"{final_path.stem}_tiktok.mp4"
        tiktok_export(final_path, tk, config)
        print(f"📱 TikTok version: {tk}")
    save_script(story, final_path, output_dir)
    print(f"🎨 Image prompts (saved before the pause): {prepared['prompt_path']}")
    hand_off(config, title, final_path,
             tiktok=output_dir / f"{final_path.stem}_tiktok.mp4" if args.tiktok else None,
             mp3=final_path.with_suffix(".mp3"),
             script=output_dir / f"{final_path.stem}_script.txt")


IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def find_title_image(proc):
    """assets/middle.jpg (or .jpeg/.png) when process.title_image is on, else None."""
    if not proc.get("title_image"):
        return None
    for ext in IMAGE_EXTS:
        for name in ("middle", "MIDDLE", "Middle"):
            f = Path(proc["folder"]) / f"{name}{ext}"
            if f.exists():
                return f
    raise FileNotFoundError(f"process.title_image is on, but there is no middle.jpg/.jpeg/.png in "
                            f"{Path(proc['folder']).resolve()}. Add one, or set title_image to false.")


def process_story_title_card(story, args, config, proc, output_dir, intro, outro,
                             prepared, music, title, image_paths, n1, rest_audio, title_img):
    """intro -> middle.jpg while the title is read -> story images while the rest
    is read (each later image fades in as its part begins) -> outro."""
    fade = config["video"].get("crossfade_seconds", 0.5)
    canvas = config["video"].get("canvas")
    mcfg = config["video"].get("music", {})
    volume = args.music_volume if args.music_volume is not None else mcfg.get("volume", 0.25)
    music_fade = mcfg.get("fade_seconds", 1.0)
    pause = config["video"]["aesop"].get("pause_after_first_line_seconds", 2)

    print(f"→ Building the title card ({Path(title_img).name}, title read over it)...")
    title_audio = output_dir / "_title_audio_tmp.mp3"
    pad_audio_to_duration(n1, get_duration(n1) + pause, title_audio)
    title_seg = output_dir / "_title_seg_tmp.mp4"
    title_narr = output_dir / "_title_narr_tmp.mp3"
    build_aesop_story_segment([title_img], title_audio, [], intro, config, title_seg, title_narr)

    clips = [intro, title_seg]
    narr_parts = [title_narr]
    story_seg = None
    if rest_audio:
        print(f"→ Building the story segment ({len(image_paths)} image(s))...")
        cfg = copy.deepcopy(config)
        cfg["video"]["aesop"]["pause_after_first_line_seconds"] = 0
        story_seg = output_dir / "_story_tmp.mp4"
        story_narr = output_dir / "_story_narr_tmp.mp3"
        imgs = image_paths[:len(rest_audio)]
        lead = output_dir / "_lead_silence_tmp.mp3"          # images line up with their own parts
        run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-t", "0.05", "-i",
                 "anullsrc=channel_layout=stereo:sample_rate=48000", "-c:a", "libmp3lame", str(lead)])
        build_aesop_story_segment(imgs, lead, rest_audio, intro, cfg, story_seg, story_narr)
        lead.unlink(missing_ok=True)
        clips.append(story_seg)
        narr_parts.append(story_narr)
    clips.append(outro)

    narration = output_dir / "_narration_full_tmp.mp3"
    concat_audio(narr_parts, narration)
    for tmp in [n1, *rest_audio, title_audio, *narr_parts]:
        Path(tmp).unlink(missing_ok=True)

    print("→ Crossfading intro → title card → story images → outro...")
    combined = output_dir / "_combined_tmp.mp4"
    crossfade_many(clips, combined, fade, canvas)
    print(f"  Narration length (incl. pause): {get_duration(narration):.1f}s")

    if music:
        durs = [get_duration(c) for c in clips]
        start = durs[0] - fade
        end = sum(durs[:-1]) - (len(clips) - 2) * fade
        print(f"→ Mixing music bed ({Path(music).name}, volume {volume}) under the title card and story...")
        mixed = output_dir / "_combined_music_tmp.mp4"
        mix_music_bed(combined, music, start, end - start, volume, music_fade, mixed)
        combined.unlink()
        combined = mixed

    set_sequence(proc["sequence_file"], prepared["seq"])
    final_path = output_dir / build_filename(config, prepared["seq"], title, "mp4")
    combined.rename(final_path)

    print("→ Building companion audio episode...")
    print("🎧 Audio version: " + str(build_companion_audio(
        intro, outro, narration, build_filename(config, prepared["seq"], title, "mp3"),
        config, output_dir, music=music, music_volume=volume, music_fade=music_fade)))

    title_save = output_dir / f"{final_path.stem}_title.mp4"
    title_seg.replace(title_save)
    print(f"🎬 Title card segment saved: {title_save}")
    if story_seg:
        saved = output_dir / f"{final_path.stem}_story.mp4"
        story_seg.replace(saved)
        print(f"🎬 Narrated image segment saved: {saved}")

    if proc.get("save_narration"):
        nsave = output_dir / f"{final_path.stem}_narration.mp3"
        narration.replace(nsave)
        print(f"🗣️ Narration-only file saved: {nsave}")
    narration.unlink(missing_ok=True)

    print(f"\n✅ Done: {final_path}")
    if args.tiktok:
        tk = output_dir / f"{final_path.stem}_tiktok.mp4"
        tiktok_export(final_path, tk, config)
        print(f"📱 TikTok version: {tk}")
    save_script(story, final_path, output_dir)
    print(f"🎨 Image prompts (saved before the pause): {prepared['prompt_path']}")
    hand_off(config, title, final_path,
             tiktok=output_dir / f"{final_path.stem}_tiktok.mp4" if args.tiktok else None,
             mp3=final_path.with_suffix(".mp3"),
             script=output_dir / f"{final_path.stem}_script.txt")


def run(script_file, description, rewrite_in=None):
    """rewrite_in: WITN's script-in.txt. Each story is rewritten just before it is
    made (and cached), and script.txt is kept up to date as stories are rewritten."""
    def extra(p):
        p.add_argument("--images", type=int, choices=[1, 2, 3], default=None,
                       help="Max images per story (default: video.aesop.max_images, 3)")
        p.add_argument("--music-volume", type=float, default=None,
                       help="Music bed volume (1.0 = file's own level; default: video.music.volume)")

    args, config, proc, output_dir, intro, middle, outro = setup(script_file, description, extra)
    title_img = find_title_image(proc)
    if title_img:
        print(f"  title card: {title_img} (title is read over it, then the story images)")
    music = find_music_bed(proc["folder"], "middle")
    print(f"  music bed: {music if music else 'none (add assets/middle.mp3 to use one)'}")

    from progress import Progress, ask_continue, first_line
    if rewrite_in:
        from rewrite import rewrite_one, write_script
        source = rewrite_in
        stories = parse_script_file(rewrite_in, "\0no-marker\0")    # raw stories
    else:
        source = args.script
        stories = parse_script_file(args.script, tts_marker(args, config))
    print(f"Found {len(stories)} story(ies) in {source}")
    prog = Progress(source, args.start_over)
    todo = prog.pending(stories)

    for n, (i, raw) in enumerate(todo):
        print(f"\n=== Story {i}/{len(stories)} ===")
        story = raw
        if rewrite_in:
            done = prog.get_rewrite(raw)
            if done:
                print(f"  (already rewritten earlier) Title: {done['title']}")
            else:
                done = rewrite_one(raw["display"], config)
                prog.set_rewrite(raw, done)
            entries = [prog.get_rewrite(s) for s in stories if prog.get_rewrite(s)]
            write_script(args.script, entries)
            print(f"📝 Rewritten script saved: {args.script}")
            text = f"{done['title']}\n{done['story']}"
            story = {"display": text, "tts": text}

        prepared = prepare_aesop_batch([story], config, proc, output_dir, intro, args.images)
        if proc.get("export_story_files") and not prog.flag(raw, "exported"):
            from rewrite import export_story_files
            export_story_files([story], prepared, config, output_dir)
            prog.flag(raw, "exported", True)
        wait_for_images(prepared, config, output_dir)
        process_story(story, args, config, proc, output_dir, intro, middle, outro, prepared[0], music)
        prog.mark_done(raw)

        left = len(todo) - n - 1
        if left:
            nxt = todo[n + 1][1]
            label = (prog.get_rewrite(nxt) or {}).get("title") or first_line(nxt)
            if not ask_continue(left, label):
                break
