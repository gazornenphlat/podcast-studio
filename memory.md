# memory.md — Podcast Studio

A running record of what's been built, decided and found out. Newest first within each section.
Add to it when something changes.

## Current state (2026-11-02)

**Test runs** (`--test`, or the Studio's "Test run" checkbox).
- Nothing is recorded: `sequence.json`, scheduling, `progress.json` (done) and the Word file are all left alone.
- Files go to `output/test/`. Numbers count up within the run only.
- WITN rewrites are still cached, so a later real run reuses them.
- Implemented by setting the env var `PODCAST_TEST_RUN=1`, which the shared helpers check.

**Studio web interface** at `/studio`, part of the Content Scheduler app.
- **Make tab:** series tiles, an autosaved script editor, options (TikTok, images, voice,
  start over), and live run status. Each image prompt has a copy button and a drop zone;
  uploads are converted to JPEG at the expected path. Continue / Stop here after each story.
- **Queue tab:** shows each series' posting dates and queue.
- **Voices tab** (2026-11-13): VoiceStudio batch queue, ported from the owner's two PowerShell
  scripts. Backend is `content_scheduler/voicestudio_batch.py` (`/api/vs/*`). One run per voice,
  runs in order, files `<Voice>_NNNN.wav` with numbering continuing from the folder. Skip-existing
  works through `generated.json` in each output folder (voice + text → file), because continuing
  numbers never collide by name. Stop finishes the current line and returns the run to Pending.
  Settings are the `voicestudio:` block in config.yaml (api_key in secrets.yaml).
  The queue is saved as `studio-batch-jobs.json` in the data folder. It must not share the PowerShell
  script's `batch-jobs.json` (BOM, capitalised keys): reading that file gave "Queue unavailable / Internal server error".
- **Design:** the owner's DESIGN.md, "Cream Watercolor Contemplative Mobile".
- **Fonts and icons** come from Google Fonts and the Iconify CDN, so the page needs internet for them.
- Tested end to end with a stand-in LLM and Kokoro: rewrite → images → build → scheduled.


**SEO per episode** (2026-11-13): `generate_seo` in `common/utils.py` asks the LLM for JSON and
`save_seo` in `common/steps.py` writes `<episode>_seo.json`. The hand-off carries it, the scheduler
stores it on the queued episode, and templates get `{meta_description}`, `{focus_keyphrase}` and
`{keyphrases}`. The default description template includes `{meta_description}`. An unusable LLM
reply falls back to the first sentence and is marked `"fallback": true`.

**TTS engines:** google, piper, kokoro, voicestudio (`voicestudio` block in a process config.json;
VoiceStudio's OpenAI-style `/v1/audio/speech`, default port 3900).

**Repo:** all work is merged through PRs on `gazornenphlat/podcast-studio`. CI (Windows, Python
3.14) runs `podcast_studio/check_all.py` on main and on PRs to main. The owner's git clone is at
`T:\sync\PROJECTS\podcast_studio_github\podcast-studio`; the older `T:\sync\PROJECTS\podcast_studio`
folder is not a git repository.

**Pipeline → scheduler hand-off**
- Every video process (cocku, confuscius, witn, aesop) hands finished episodes to the
  scheduler. The mapping is in each `config.json → scheduler`: COCKu-YT, Confuscius-YT,
  WITN-YT, Aesop's Fables-YT. Audio-only episodes aren't scheduled.

**Scheduler**
- 12 sites, each tagged `format: wide` (16:9) or `format: vertical` (9:16):
  - Wide: YouTube, Instagram, Facebook, X/Twitter, Rumble, Odysee, Spotify, Substack.
  - Vertical: TikTok, YouTube Shorts, Instagram Reels, Facebook Reels.
- Only YouTube and YouTube Shorts can auto-upload (Google OAuth). The rest get a reminder
  with the file path. Twitter and Instagram are reminder-only for video episodes: the scheduler never auto-posts a video to them (`VIDEO_REMINDER_ONLY` in `app.py`).
- All four series are set to all 12 sites in `config.yaml`. If `series.yaml` exists on the
  owner's machine, it overrides that list.
- GUI: the series dropdown is sorted alphabetically. The calendar shows each series'
  "Need more content by" date as a dashed tag.
- Reminders: "nothing scheduled in the next 30 days" fires per series and repeats weekly
  until something is queued (`empty_window_days`, `empty_repeat_days`).

**WITN flow**
- `script-in.txt`: the language model rewrites each story and titles it.
- `script.txt` is filled in story by story: the title on the first line, then the story.
- Per story: image prompts, then a `.txt` file and an entry in the running Word file `output/WITN_Stories.docx`.
- Then the run pauses for images.
- Video: intro → `assets/middle.jpg` while the title is read (plus a 2-second pause) →
  story images while the rest is read (each fades in at its part) → outro.
  - `process.title_image: true` turns this on.
  - `false` brings back the middle-video flow.
- `--script X` skips the rewrite, unless X is named `script-in*`.

**All processes**
- One story at a time, with "Continue with the next story? [Y/n]" after each.
- Resume skips finished stories (`progress.json`). `--start-over` resets it.
- WITN rewrites are cached, so quitting at the image pause doesn't rewrite again.

**TTS engines:** `google`, `piper`, `kokoro`.
- Kokoro runs either in-process (`kokoro-onnx`) or through a server (`kokoro.server_url`).
- The server URL is normalised: `http://` and `:8880` are added if missing.
- The server's voice list is checked, and an unknown voice stops the run with the available list.

**LLM:** `llm.backend` is `ollama` (default) or `lmstudio` (OpenAI-compatible, port 1234).
`<think>` blocks are stripped from the output.

## Machines (owner, 2026-11-02)

- Pipeline runs on the Radeon 780M machine (32 GB; 4 GB given to the GPU, rest is system RAM).
- Also: Ryzen 9 6900HX with Radeon 680M (32 GB), Ryzen 7 PRO 5850U with Vega 8 (32 GB).
- Image generation: ComfyUI was removed on 2026-11-12 (owner's choice). Images are still made by hand from the printed prompts.

## Owner setup and preferences

- Windows, Python 3.14. The project is at `T:\sync\PODCAST_MAKER\podcast_studio\`.
- Piper: `C:/piper/piper.exe`, voices in `C:/piper/voices/` (about 50, including custom ones).
- Kokoro server: `http://10.120.1.147:8880`, voice `bm_atten_inno` (confirmed by the owner 2026-11-02).
  - That's not a stock Kokoro voice; whether the server has it was still unconfirmed (see below).
- Wants changes delivered as small zips of the changed code files only, with config edits as snippets.
- Declined direct shell access to their computer once (2026-10-17). On 2026-11-02 said direct edits to the linked folder and pushes to GitHub are OK.

## Decisions and why

- **One story at a time, instead of batching every image prompt up front.** The owner wanted
  to stop after any story. A batch pause would have wasted work on stories that never get made.
- **Kokoro via HTTP server:** `kokoro` and `kokoro-onnx` both declare Python <3.14.
- **Running Word file instead of one per run:** the owner asked for it. Each later story starts on a new page.
- **Title read over a still `middle.jpg`, not the middle video:** the owner asked for it.
- **Alt-ending videos are never scheduled:** the owner asked for it.
- **Title is taken from the first line of `script.txt`** (`title_from_first_line`) rather than
  generated again, so the spoken title, the filename and the scheduler entry all match.

## Gotchas found

- **Two `"kokoro"` sections in one config.json:** JSON keeps the last one silently.
  This caused a "bare URL" error and possibly the wrong voice. Search for duplicates first.
- **`piper.executable` pointing at the `C:\piper\piper` folder** gives WinError 2. Fixed in code:
  a folder resolves to `piper.exe` inside it, and a missing `.exe` is added.
- **Relative `piper.model_path`** resolves inside the process folder, not `C:\piper`.
- **The LLM preamble stripper** used to delete a story's first line when it began "Sure…" or "Okay…".
  It now only strips lines ending in ":".
- **`--script script-in.txt`** used to skip the rewrite and use the raw first sentence as the
  title (this produced the bad WITN-002). It now rewrites.
- **Running Word file open in Word:** the save fails. The code stops with "close it in Word".
- **Duplicate keys in config files were silent.** JSON and YAML keep the last value. Now JSON (pipeline, Studio) and YAML (scheduler) are refused with the file and key named. `tools/check_configs.py` finds them all.
- **A `--test --start-over` run erased real progress** (and WITN's rewrite cache). Fixed 2026-11-02: test runs merge only the rewrite cache to disk.
- **`import markers` before the `sys.path` line** broke cocku, confuscius and audio. Import it after the path is set.
- **Studio crashed on an absolute image path** from a config with an absolute `output_dir`. Fixed.
- **Aesop and WITN pause for images once per story**, not once per file. The READMEs said otherwise; fixed.
- **Scheduler:** `series.yaml` overrides `config.yaml`'s series list, so new sites must be ticked in the GUI there.

## Open items

- The scheduler isn't set to start with Windows yet. The owner asked about it on 2026-10-17
  but stopped the check. `content_scheduler/service/install_windows.ps1` exists for this.
- WITN `rewrite.instructions` is Claude's humorous draft (2026-11-12). The owner hasn't confirmed the tone.
- VoiceStudio (TTS engine `voicestudio`, the Voices tab) and the SEO text are tested only with stand-ins, not the real VoiceStudio or LLM.
- End-to-end runs with stand-ins (fake LLM, fake Kokoro, ffmpeg clips) are done for all five processes and the Studio API (2026-11-02). Not yet run with the real LLM, the real Kokoro server or real images.
