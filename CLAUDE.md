# CLAUDE.md — Podcast Studio

Guidance for Claude when working in this project. Read `memory.md` too: it holds the
history, decisions and the owner's machine setup.

## What this is

Two Python apps in one folder, wired together:

- `podcast_pipeline/` makes episodes from script text: TTS narration, title and
  image prompts from a local LLM, and ffmpeg video. Each series is its own process.
- `content_scheduler/` is a Flask + tray app. It holds a queue per series, works out
  posting dates, sends reminders and auto-posts where an API allows.

When a video episode finishes, the pipeline drops a JSON note in
`content_scheduler/inbox/` (`common/schedule_handoff.py`). The scheduler queues it
with its file paths and gives it the next open posting day (`ingest_inbox()` in `app.py`).

## Layout

```
podcast_pipeline/
  common/            shared code – edit here, not in copies
    utils.py         config, naming, LLM calls (Ollama / LM Studio), TTS (Google / Piper / Kokoro / VoiceStudio), SEO text, ffmpeg
    steps.py         setup() + argparse shared by processes, image-prompt prep, image pause
    image_flow.py    WITN + Aesop engine (title card, story images, per-story loop)
    rewrite.py       WITN: LLM rewrite of script-in.txt, .txt per story, running Word file
    progress.py      per-story resume (progress.json), "Continue?" prompt
    schedule_handoff.py   hand finished episodes to the scheduler inbox
  witn/ aesop/ cocku/ confuscius/ audio/
    <name>.py, config.json, assets/, sequence.json, progress.json, output/
content_scheduler/
  app.py             all server logic; templates/index.html is the classic scheduler GUI
  studio.py          /studio + /api/studio/*: runs pipeline processes as subprocesses, streams
                     output, answers prompts via stdin, accepts image uploads
  voicestudio_batch.py   /api/vs/*: VoiceStudio batch queue behind the Studio page's Voices tab
  templates/studio.html   Studio page, built to DESIGN "Cream Watercolor" (cream page, white
                     40px pebbles, no shadows, Raleway Light, terracotta used once per screen)
  config.yaml        sites, series, reminders (secrets.yaml merges on top)
  series.yaml        if present, REPLACES the series list in config.yaml (GUI-managed)
```

## How to run

```
python podcast_pipeline/witn/witn.py --tiktok            # reads witn/script-in.txt, rewrites, builds
python podcast_pipeline/witn/witn.py --script witn/script.txt   # already-written script, no rewrite
python podcast_pipeline/cocku/cocku.py --script script.txt [--tiktok]
python content_scheduler/app.py                          # or tray.py / "Content Scheduler.pyw"
```

Common flags: `--tts-engine google|piper|kokoro|voicestudio`, `--start-over`, `--test` (records nothing; output/test/), `--images 1-3`, `--config`.

Tests and checks:

```
python podcast_studio/check_all.py                                # everything below, in one go
cd podcast_studio/podcast_pipeline && python -m pytest tests -q
cd podcast_studio/content_scheduler && python -m pytest tests -q
python podcast_studio/podcast_pipeline/tools/check_configs.py     # duplicate keys in any config
```

## Conventions to keep

- **Each process folder is self-contained.** `setup()` chdirs into it, so relative paths in a
  config.json are relative to that process folder. Use absolute paths for anything
  outside it, like Piper, Kokoro or fonts.
- **Shared behaviour goes in `common/`**, switched on per process with a `config.json` flag
  (for example `process.title_image`, `process.export_story_files`, `process.title_from_first_line`).
  Don't fork logic into one process's script.
- **Scripts:** stories are separated by a blank line, and a story itself must contain
  no blank lines. Optional `===TTS===` line splits display text from TTS text.
  WITN's `script.txt` has the title on the first line, then the story with no blank line after the title.
- **Naming:** `{PREFIX}-{SEQ:03}_{Title-Slug}.ext`. The number comes from `sequence.json`.
- **Stories run one at a time**, with a "Continue?" prompt after each. Progress is keyed by a
  story-text hash in `progress.json`. Mark a story done only after it's fully built.
- **Scheduler file choice:** a site with `format: wide` gets the 16:9 episode video, and a site
  with `format: vertical` gets `_tiktok.mp4`. Alt-ending videos are never scheduled.
  Scheduled processes always make the TikTok version.
- **JSON configs have no comments.** Don't suggest commenting lines out.
- **Anything that records state** (sequence, scheduler hand-off, progress, Word file) must check
  `is_test()` / `PODCAST_TEST_RUN`, so test runs stay invisible.
- **Write files atomically** (tmp + `os.replace`), as the existing code does.
- **Studio parses the pipeline's printed output through `common/markers.py`.** Change a prompt or
  `studio.py` reads the same constants. Never copy the text into another file: `tests/test_markers.py` fails if you do.
  The markers are: "press Enter to continue (or q to quit)", "Continue with the next story?",
  "🎨 IMAGE NEEDED — …", "Save your image as:", "✅ Done:", "📅 Scheduled:".
- **Keep error messages actionable:** say which path or URL was tried and what to set.

## Owner's environment (Windows)

- **Project:** `T:\sync\PROJECTS\podcast_studio\` (a network share, `\\10.120.1.147\t-tv7\sync\…`).
  Older copies were at `T:\sync\PODCAST_MAKER\…` and in `Downloads\PODCAST_MAKER\…`, so check which copy a traceback comes from.
- **Python 3.14.** Many ML packages (`kokoro`, `kokoro-onnx`) officially stop at 3.13.
  Prefer HTTP servers or packages that support 3.14.
- **Piper** is at `C:/piper/piper.exe`, with voices in `C:/piper/voices/`. `C:\piper\piper` is a folder, not the program.
- **Kokoro** runs as a Kokoro-FastAPI server on `http://10.120.1.147:8880`.
- **LLM:** Ollama (`localhost:11434`) or LM Studio (`llm.backend: lmstudio`, port 1234).
- **ffmpeg** is on PATH.

## Working with the owner

- **Deliver only the changed code files**, as a small zip with the same folder structure,
  so the owner's configs and API keys aren't overwritten. Config changes go in the reply
  as a JSON snippet to paste.
- **Direct changes are allowed.** On 2026-11-02 the owner said Claude may edit the linked project folder directly and push to GitHub. Earlier they had declined direct access, so keep changes small and say what changed.
- **Test with stand-ins before shipping:** a fake LLM HTTP server, fake TTS (an ffmpeg sine
  tone), and tiny ffmpeg-made intro/middle/outro clips and images. Check frame colours or
  durations rather than assuming. Say plainly what was and wasn't tested.
- **Keep replies short.** Lead with what changed and what to run.
- **Content is adult humor.** Work on it matter-of-factly.
