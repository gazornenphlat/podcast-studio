# Podcast production pipeline

Script text in -> finished, sequentially named episodes out. Each series is its
own **separate process** with its own script, config, assets, sequence counter
and output folder. Run them from anywhere; each one works inside its own folder.

```
podcast_pipeline/
  common/      shared code only (utils.py, steps.py, image_flow.py) - no need to touch
  tools/       list_voices.py (list Google TTS voices)
  audio/       audio-only episodes         -> audio/audio_pipeline.py
  witn/        WITN   (same image flow as Aesop) -> witn/witn.py
  cocku/       COCku  (dim + scrolling text, optional alt ending) -> cocku/cocku.py
  confuscius/  Confuscius (dim + scrolling text) -> confuscius/confuscius.py
  aesop/       Aesop  (up to 3 fading images + optional music bed) -> aesop/aesop.py
```

Each process folder contains: its script, `config.json`, `assets/` (your
`intro.*`, `middle.*`, `outro.*`; audio has none), `sequence.json` (created on
first run) and `output/` (created on first run). Change one series' TTS voice,
prefix, fonts, etc. in its own `config.json` without affecting the others.

## Quick start
```bash
pip install -r requirements.txt          # ffmpeg must be installed too
# put your videos in <process>/assets/, set google_tts.api_key in <process>/config.json
python witn/witn.py       --script script.txt [--tiktok] [--images 1-3] [--music-volume 0.3]   # pauses for images
python cocku/cocku.py     --script script.txt [--tiktok] [--outro2 file]
python confuscius/confuscius.py --script script.txt [--tiktok]
python aesop/aesop.py     --script script.txt [--tiktok] [--images 1-3]   # pauses for your images
python audio/audio_pipeline.py --script script.txt --intro intro.mp3 --outro outro.mp3
```

## Shared behavior
- **Script file:** several stories separated by a blank line; each becomes an
  episode. A line with only `===TTS===` splits display text from TTS-only text.
- **TTS:** Google Cloud (key in `google_tts.api_key` or env `GOOGLE_TTS_API_KEY`)
  or Piper offline (`--tts-engine piper`). Speed: `google_tts.speaking_rate`,
  or `piper.length_scale` (inverted).
- **Kokoro TTS:** `"tts_engine": "kokoro"` in a process's config.json (or `--tts-engine kokoro`).
  Either in-process (`pip install kokoro-onnx`, plus `kokoro-v1.0.onnx` and `voices-v1.0.bin`
  from github.com/thewh1teagle/kokoro-onnx/releases at `kokoro.model_path` / `voices_path`),
  or a running Kokoro-FastAPI server (`kokoro.server_url`, e.g. `http://localhost:8880`).
  Voice: `kokoro.voice` (e.g. `af_heart`, `af_bella`, `am_adam`, `am_michael`, `bf_emma`, `bm_george`;
  combine with `af_heart+am_adam` on the server). Speed: `kokoro.speed` (0.5–2.0).
- **One story at a time:** with several stories in a script (or WITN's script-in.txt), each
  story is made completely, then you're asked "Continue with the next story? [Y/n]".
  Answer n to stop; the next run with the same script skips the finished stories and
  picks up at the next one. Progress lives in each process's `progress.json`;
  `--start-over` forgets it for that script. Quitting at the image pause keeps WITN's
  rewrite, so the story isn't rewritten again.
- **Titles / image prompts:** local Ollama (`llm.ollama` in config).
- **Naming:** `{PREFIX}-{SEQ}_{Title}.ext`, counter in the process's `sequence.json`.
- **Every episode** also gets its script saved as `<episode>_script.txt` (plus `_script_tts.txt` if you used a `===TTS===` version that differs).
- **Every video** also gets a companion `.mp3`. `--tiktok` adds a 9:16 blur-pad export.
- **Crossfade** is 0.5s (`video.crossfade_seconds`); clips are normalized to the intro's size/fps.

See each folder's README.md for what makes that process different.

## Note on moving from the old single-script version
The old `video_pipeline.py --mode X` and root `config.json` are gone. Old
asset folders (`WINT/`, `cocku/`...) become `<process>/assets/`, old sequence
files become `<process>/sequence.json` (copy the number over to continue counting,
e.g. `{"seq": 12}`), and output now goes to each process's own `output/`
instead of one shared folder.

## Automatic images with ComfyUI (optional)

Aesop and WITN can make their story images on a ComfyUI worker, so the pause only
waits for images that could not be made. It is off by default: set `image_gen.enabled`
to `true` in that process's `config.json`.

1. Install ComfyUI on each machine that will make images. On AMD Radeon APUs on Windows,
   use the ZLUDA build: https://github.com/patientx/ComfyUI-Zluda (it lists the 680M and 780M).
   Put a checkpoint in `ComfyUI/models/checkpoints/` and set `image_gen.checkpoint` to its file name.
2. Start ComfyUI with `--listen` so other computers can reach it. It has no login: use it on your home network only.
3. List the machines in `image_gen.workers`, in order of preference. A worker that doesn't answer is skipped.
4. In Studio, pick "Any worker" or a named machine before you start. From the terminal, add `--image-worker "6900HX"`.

The workflow is `common/comfy_txt2img.json`. Its size comes from `image_gen.width` and `image_gen.height`.
Use sizes that suit your VRAM: 4 GB runs better at 896×512 than at 1280×720.
Images are made in the same order and under the same names as the manual ones.
