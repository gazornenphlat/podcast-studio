# memory.md — Podcast Studio

A running record of what's been built, decided and found out. Newest first within each section.
Add to it when something changes.

## Current state (2026-10-22)

**Pipeline → scheduler hand-off**
- Every video process (cocku, confuscius, witn, aesop) hands finished episodes to the
  scheduler. The mapping is in each `config.json → scheduler`: COCKu-YT, Confuscius-YT,
  WITN-YT, Aesop's Fables-YT. Audio-only episodes aren't scheduled.

**Scheduler**
- 12 sites, each tagged `format: wide` (16:9) or `format: vertical` (9:16):
  - Wide: YouTube, Instagram, Facebook, X/Twitter, Rumble, Odysee, Spotify, Substack.
  - Vertical: TikTok, YouTube Shorts, Instagram Reels, Facebook Reels.
- Only YouTube and YouTube Shorts can auto-upload (Google OAuth). The rest get a reminder
  with the file path. Twitter and Instagram auto-post only send text and images, so they're left off for video.
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

## Owner setup and preferences

- Windows, Python 3.14. The project is at `T:\sync\PODCAST_MAKER\podcast_studio\`.
- Piper: `C:/piper/piper.exe`, voices in `C:/piper/voices/` (about 50, including custom ones).
- Kokoro server: `http://10.120.1.147:8880`, voice `bm_atten_inno`.
  - That's not a stock Kokoro voice; whether the server has it was still unconfirmed (see below).
- Wants changes delivered as small zips of the changed code files only, with config edits as snippets.
- Declined direct shell access to their computer once (2026-10-17). Ask first.

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
- **Scheduler:** `series.yaml` overrides `config.yaml`'s series list, so new sites must be ticked in the GUI there.

## Open items

- Confirm that the Kokoro server has `bm_atten_inno`. The run now prints the voice in use and validates it.
- The scheduler isn't set to start with Windows yet. The owner asked about it on 2026-10-17
  but stopped the check. `content_scheduler/service/install_windows.ps1` exists for this.
- COCKu, Confuscius and audio have only been checked to compile after the per-story change, not run end to end.
- `rewrite.instructions` is still the generic placeholder. The WITN tone hasn't been set.
