"""
Shared helpers for the podcast/video automation pipeline.
Covers: sequential naming, pluggable TTS (Google Cloud TTS or Piper),
local/free LLM calls (Ollama) for title + image-prompt generation, and
ffmpeg/ffprobe wrappers.
"""

import base64
import json
import os
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import requests


# ---------------------------------------------------------------------------
# Config / sequencing
# ---------------------------------------------------------------------------

def _reject_duplicate_keys(pairs):
    """JSON silently keeps the LAST of two equal keys; refuse instead."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(key)
        seen[key] = value
    return seen


class DuplicateKeyError(ValueError):
    pass


def load_json_file(path):
    """Read a JSON file, refusing duplicate keys with the file and key named."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f, object_pairs_hook=_reject_duplicate_keys)
    except DuplicateKeyError as ex:
        raise ValueError(f"Duplicate key {ex.args[0]!r} in {path} — JSON keeps only the last one, "
                         "so the earlier value is silently ignored. Remove one of them.") from None


def load_config(config_path="config.json"):
    return load_json_file(config_path)


TEST_ENV = "PODCAST_TEST_RUN"
_TEST_SEQ = {}


def is_test():
    """True during a --test run: nothing is counted, scheduled or recorded."""
    return os.environ.get(TEST_ENV) == "1"


def get_next_sequence(sequence_file):
    """Read, increment, and persist a sequential counter. Starts at 1.
    In a test run the number is used but sequence.json is left alone."""
    if is_test():
        key = str(Path(sequence_file).resolve())
        _TEST_SEQ[key] = _TEST_SEQ.get(key, peek_next_sequence(sequence_file) - 1) + 1
        return _TEST_SEQ[key]
    path = Path(sequence_file)
    if path.exists():
        data = load_json_file(path)
    else:
        data = {"seq": 0}
    data["seq"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    return data["seq"]


def peek_next_sequence(sequence_file):
    """The number get_next_sequence() would return next, without consuming it."""
    if is_test() and str(Path(sequence_file).resolve()) in _TEST_SEQ:
        return _TEST_SEQ[str(Path(sequence_file).resolve())] + 1
    path = Path(sequence_file)
    if path.exists():
        return load_json_file(path).get("seq", 0) + 1
    return 1


def set_sequence(sequence_file, value):
    """Record `value` as the last-used sequence number (not in a test run)."""
    if is_test():
        _TEST_SEQ[str(Path(sequence_file).resolve())] = value
        return
    Path(sequence_file).write_text(json.dumps({"seq": value}), encoding="utf-8")


def slugify_title(title, max_words=6):
    """Turn a free-text title into Kebab-Case suitable for a filename."""
    title = title.strip().strip('"').strip("'")
    words = re.findall(r"[A-Za-z0-9']+", title)[:max_words]
    words = [re.sub(r"[^A-Za-z0-9]", "", w) for w in words]
    words = [w for w in words if w]
    return "-".join(w.capitalize() for w in words) if words else "Untitled"


def filename_prefix(config, seq):
    """The '{PREFIX}-{SEQ}_' start shared by every file of one episode."""
    naming = config["naming"]
    return f"{naming['prefix']}{naming['separator']}{seq:0{naming['seq_digits']}d}_"


def build_filename(config, seq, title, ext):
    slug = slugify_title(title, config["naming"].get("max_title_words", 6))
    return f"{filename_prefix(config, seq)}{slug}.{ext}"


# ---------------------------------------------------------------------------
# Script file parsing: a single file can hold multiple stories, separated by
# one or more blank lines. Within a story, an optional line matching
# `tts_marker` exactly splits it into a "display" version (used for title
# generation, image prompts, and COCku's scrolling text) and a "tts" version
# (used only for narration — e.g. with phonetic spellings). No marker means
# the same text is used for both, same as before this feature existed.
# ---------------------------------------------------------------------------

def parse_script_file(path, tts_marker="===TTS==="):
    """Returns a list of {"display": str, "tts": str} dicts, one per story,
    in file order."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    blocks = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)

    stories = []
    for block_lines in blocks:
        marker_idx = next(
            (i for i, l in enumerate(block_lines) if l.strip() == tts_marker),
            None,
        )
        if marker_idx is not None:
            display = "\n".join(block_lines[:marker_idx]).strip()
            tts = "\n".join(block_lines[marker_idx + 1:]).strip()
        else:
            display = tts = "\n".join(block_lines).strip()
        stories.append({"display": display, "tts": tts})

    return stories


def find_variation_file(folder, base_name):
    """Find `{base_name}.*` (e.g. 'intro.*') inside `folder`, trying common
    video extensions first, then falling back to any matching file."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    for ext in (".mp4", ".mov", ".mkv", ".avi", ".webm"):
        candidate = folder / f"{base_name}{ext}"
        if candidate.exists():
            return candidate

    matches = sorted(folder.glob(f"{base_name}.*"))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        f"Couldn't find a '{base_name}.*' file in {folder} — expected "
        f"e.g. {folder / (base_name + '.mp4')}."
    )


def find_variation_file_optional(folder, base_name):
    """Same as find_variation_file, but returns None instead of raising —
    for optional assets like an alternate outro."""
    try:
        return find_variation_file(folder, base_name)
    except FileNotFoundError:
        return None


def split_first_line(text):
    """Split text into (first_line, rest), both stripped. If there's no
    second line, rest is ''."""
    first, _, rest = text.strip().partition("\n")
    return first.strip(), rest.strip()


def split_sentences(text):
    """Split text into sentences (keeps end punctuation); newlines also break."""
    parts = []
    for line in text.strip().splitlines():
        line = line.strip()
        if line:
            parts.extend(x.strip() for x in re.split(r"(?<=[.!?])\s+", line) if x.strip())
    return parts


def split_into_portions(text, k):
    """Split text into at most k consecutive chunks at sentence boundaries,
    balanced by length. Returns fewer than k chunks if there aren't enough
    sentences. Every returned chunk is non-empty."""
    sentences = split_sentences(text)
    k = max(1, min(k, len(sentences)))
    if k <= 1:
        return [" ".join(sentences)] if sentences else []
    total = sum(len(x) for x in sentences)
    chunks, cur, cur_len = [], [], 0
    for idx, sent in enumerate(sentences):
        cur.append(sent)
        cur_len += len(sent)
        remaining_sents = len(sentences) - idx - 1
        remaining_chunks = k - len(chunks) - 1
        target = total * (len(chunks) + 1) / k
        done = sum(len(x) for c in chunks for x in c) + cur_len
        if remaining_chunks > 0 and (done >= target or remaining_sents == remaining_chunks):
            chunks.append(cur)
            cur, cur_len = [], 0
    if cur:
        chunks.append(cur)
    return [" ".join(c) for c in chunks]


# ---------------------------------------------------------------------------
# Local, free LLM calls (Ollama) for title + image prompt generation.
# Ollama runs entirely on your machine — no API key, no account, no cost.
# Install: https://ollama.com, then `ollama pull llama3.2` (or your model
# of choice) and leave `ollama serve` running in the background.
# ---------------------------------------------------------------------------

def _call_lmstudio(prompt, config, max_tokens=250):
    """LM Studio (or any OpenAI-compatible server) – llm.lmstudio in config.json."""
    llm = config["llm"].get("lmstudio", {})
    host = llm.get("host", "http://localhost:1234").strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    if host.endswith("/v1"):
        host = host[:-3]
    timeout = llm.get("timeout", 300)
    body = {"messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": llm.get("temperature", 0.7), "stream": False}
    if llm.get("model"):
        body["model"] = llm["model"]           # blank = whichever model is loaded in LM Studio
    try:
        resp = requests.post(f"{host}/v1/chat/completions", json=body, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Couldn't reach LM Studio at {host}. In LM Studio open the Developer "
                           "tab, load a model and start the server (and turn on 'Serve on Local "
                           "Network' if it's on another computer).") from e
    except requests.exceptions.ReadTimeout as e:
        raise RuntimeError(f"LM Studio didn't answer within {timeout}s. Try a smaller model or "
                           "raise llm.lmstudio.timeout in config.json.") from e
    if not resp.ok:
        raise RuntimeError(f"LM Studio error ({resp.status_code}): {resp.text[:300]}")
    text = resp.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # drop reasoning models' thinking


def _call_ollama(prompt, config, max_tokens=250):
    if config["llm"].get("backend", "ollama") == "lmstudio":
        return _call_lmstudio(prompt, config, max_tokens)
    llm = config["llm"]["ollama"]
    host = llm.get("host", "http://localhost:11434").strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    model = llm.get("model", "llama3.2")
    timeout = llm.get("timeout", 300)

    try:
        resp = requests.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Couldn't reach Ollama at {host}. Is it installed and running? "
            "Install from https://ollama.com, then run `ollama serve` "
            f"and `ollama pull {model}`."
        ) from e
    except requests.exceptions.ReadTimeout as e:
        raise RuntimeError(
            f"Ollama didn't respond within {timeout}s. The first request after "
            "starting Ollama loads the model into memory and can be slow, and "
            "larger models are slow on CPU-only hardware. Try: running the "
            "pipeline again (model may now be warm), switching to a smaller "
            "model (e.g. `ollama pull llama3.2:1b`), or raising llm.ollama.timeout "
            "in config.json."
        ) from e

    return resp.json()["response"].strip()


def generate_title(script_text, config):
    max_words = config["naming"].get("max_title_words", 6)
    prompt = textwrap.dedent(f"""\
        Summarize the following podcast script in one punchy, pithy title
        (max {max_words} words, no punctuation besides hyphens, suitable for
        use in a filename). Return ONLY the title, nothing else — no quotes,
        no preamble, no explanation.

        SCRIPT:
        {script_text}
    """)
    title = _call_ollama(prompt, config, max_tokens=30)
    # Local models are chattier than API models about following "return only
    # X" instructions, so defensively take just the first non-empty line.
    return next((line.strip() for line in title.splitlines() if line.strip()), title)


DEFAULT_IMAGE_STYLE = ("vector art cartoon style, clean vector, flat colors, "
                       "bold outlines, humorous")
DEFAULT_IMAGE_TONE = "humorous"


def generate_image_prompt(script_text, config, style=None, tone=None, scene_note=None):
    """Ask the local LLM for a scene description plus a ready-to-paste image
    prompt. `style` is the art-style suffix appended to the scene and `tone`
    colors how the scene is described; both fall back to config's
    `image_prompt.default_style` / `default_tone`, then to the built-in
    vector-cartoon look. A series can override them (see the Aesop variation
    in config.json)."""
    defaults = config.get("image_prompt", {})
    style = style or defaults.get("default_style", DEFAULT_IMAGE_STYLE)
    tone = tone or defaults.get("default_tone", DEFAULT_IMAGE_TONE)
    prompt = textwrap.dedent(f"""\
        In 2-3 sentences, describe a single {tone} visual scene that captures
        the core idea of the podcast script below. Then, on a new line, output a
        final ready-to-use image-generation prompt in exactly this format:

        "[scene description], {style}"

        SCRIPT:
        {script_text}
    """)
    if scene_note:  # e.g. "This is scene 2 of 3 ..." — only used for multi-image stories
        prompt = scene_note.strip() + "\n\n" + prompt
    return _call_ollama(prompt, config, max_tokens=300)


# ---------------------------------------------------------------------------
# TTS engines: Google Cloud TTS and Piper (offline/free), picked via
# config["tts_engine"]. Both are exposed through synthesize_narration().
# ---------------------------------------------------------------------------

def _chunk_text(text, max_chars):
    """Split text into chunks under max_chars, breaking on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _google_synthesize_chunk(text, config, out_path):
    g = config["google_tts"]
    api_key = g.get("api_key") or os.environ.get(g.get("api_key_env", "GOOGLE_TTS_API_KEY"))
    if not api_key:
        raise RuntimeError(
            "Set google_tts.api_key in config.json, or set the "
            f"{g.get('api_key_env', 'GOOGLE_TTS_API_KEY')} environment variable."
        )

    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": g.get("language_code", "en-US"),
            "name": g.get("voice_name", "en-US-Neural2-F"),
        },
        "audioConfig": {
            "audioEncoding": g.get("audio_encoding", "MP3"),
            "speakingRate": g.get("speaking_rate", 1.0),
        },
    }
    resp = requests.post(url, json=payload, timeout=60)
    if not resp.ok:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(
            f"Google TTS rejected the request ({resp.status_code}): {detail}\n"
            f"  voice: {payload['voice']['name']}  language: {payload['voice']['languageCode']}  "
            f"speakingRate: {payload['audioConfig']['speakingRate']}\n"
            f"  text chunk (first 80 chars): {text[:80]!r}"
        )
    audio_content = resp.json()["audioContent"]
    Path(out_path).write_bytes(base64.b64decode(audio_content))


def google_tts_long(text, config, out_path):
    """Synthesize arbitrarily long text via Google Cloud TTS by chunking
    (Google's per-request limit is ~5000 bytes) and stitching with ffmpeg."""
    g = config["google_tts"]
    max_chars = g.get("max_chars_per_request", 4500)
    chunks = _chunk_text(text, max_chars)

    with tempfile.TemporaryDirectory() as tmp:
        chunk_paths = []
        for i, chunk in enumerate(chunks):
            p = os.path.join(tmp, f"chunk_{i:03d}.mp3")
            _google_synthesize_chunk(chunk, config, p)
            chunk_paths.append(p)

        if len(chunk_paths) == 1:
            Path(chunk_paths[0]).replace(out_path)
        else:
            concat_audio(chunk_paths, out_path)

    return out_path


def piper_tts(text, config, out_path):
    """Synthesize speech fully offline/free using Piper. Requires the piper
    binary (or `pip install piper-tts`) and a downloaded .onnx voice model."""
    p = config["piper"]
    executable = p.get("executable", "piper")
    exe = Path(executable)
    if exe.is_dir():                                   # e.g. C:/piper or C:/piper/piper
        exe = exe / ("piper.exe" if os.name == "nt" else "piper")
    if os.name == "nt" and not exe.suffix and exe.with_suffix(".exe").exists():
        exe = exe.with_suffix(".exe")
    if (exe.is_absolute() or len(exe.parts) > 1) and not exe.exists():
        raise RuntimeError(f"Piper program not found at {exe}. Set piper.executable in "
                           "config.json to the full path of piper.exe (e.g. C:/piper/piper.exe).")
    executable = str(exe)
    model_path = p["model_path"]

    if not Path(model_path).exists():
        raise RuntimeError(
            f"Piper model not found at {Path(model_path).resolve()}. Set piper.model_path in "
            "this process's config.json to the full path of an .onnx voice, or download one "
            "from https://github.com/rhasspy/piper/blob/master/VOICES.md"
        )

    cmd = [executable, "--model", str(model_path), "--output_file", str(out_path)]
    length_scale = p.get("length_scale")
    if length_scale is not None:
        cmd += ["--length_scale", str(length_scale)]
    result = subprocess.run(cmd, input=text, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Piper failed: {result.stderr}")
    return out_path


_KOKORO = {}
_KOKORO_CHECKED = set()


def _kokoro_local(text, k, out_path):
    """Kokoro in-process via kokoro-onnx (pip install kokoro-onnx) plus the
    model + voices files from https://github.com/thewh1teagle/kokoro-onnx/releases."""
    try:
        from kokoro_onnx import Kokoro
    except ImportError as e:
        raise RuntimeError(
            "Kokoro isn't installed. Run: pip install kokoro-onnx  (if pip refuses your "
            "Python version, add --ignore-requires-python, or use a Kokoro server instead: "
            "set kokoro.server_url in config.json)."
        ) from e
    import wave
    import numpy as np
    model, voices = k.get("model_path", "C:/kokoro/kokoro-v1.0.onnx"), k.get("voices_path", "C:/kokoro/voices-v1.0.bin")
    for f in (model, voices):
        if not Path(f).exists():
            raise RuntimeError(f"Kokoro file not found: {Path(f).resolve()}. Download kokoro-v1.0.onnx and "
                               "voices-v1.0.bin from https://github.com/thewh1teagle/kokoro-onnx/releases "
                               "and set kokoro.model_path / kokoro.voices_path in config.json.")
    key = (model, voices)
    if key not in _KOKORO:
        _KOKORO[key] = Kokoro(model, voices)
    samples, rate = _KOKORO[key].create(text, voice=k.get("voice", "af_heart"),
                                        speed=float(k.get("speed", 1.0)), lang=k.get("lang", "en-us"))
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())


def _kokoro_server(text, k, out_path):
    """Kokoro through a local OpenAI-style server such as Kokoro-FastAPI
    (http://localhost:8880). Works whatever Python version the pipeline uses."""
    base = k["server_url"].strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base                     # "10.0.0.5" -> "http://10.0.0.5"
    host = base.split("://", 1)[1].split("/", 1)[0]
    if ":" not in host.split("]")[-1]:
        base = base.replace(host, host + ":8880", 1)  # Kokoro-FastAPI's default port
    k = {**k, "server_url": base}
    url = base + "/v1/audio/speech"
    voice = k.get("voice", "af_heart")
    if base not in _KOKORO_CHECKED:
        _KOKORO_CHECKED.add(base)
        print(f"  Kokoro: voice '{voice}' via {base}")
        try:
            vr = requests.get(base + "/v1/audio/voices", timeout=15)
            vr.raise_for_status()
            j = vr.json()
            names = [v if isinstance(v, str) else v.get("id") or v.get("name")
                     for v in (j.get("voices", j) if isinstance(j, dict) else j)]
            missing = [x for x in voice.replace("(", "").replace(")", "").replace("-", "+").split("+")
                       if x and not x.replace(".", "").isdigit() and x.strip() not in names]
            if missing:
                raise RuntimeError(f"The Kokoro server has no voice named {', '.join(missing)}. "
                                   f"Voices it has: {', '.join(sorted(n for n in names if n))}")
        except RuntimeError:
            raise
        except Exception:
            pass                                    # older servers have no voice list – just carry on
    try:
        resp = requests.post(url, json={"model": k.get("model", "kokoro"), "input": text,
                                        "voice": voice,
                                        "speed": float(k.get("speed", 1.0)), "response_format": "wav"},
                             timeout=int(k.get("timeout", 600)))
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Couldn't reach the Kokoro server at {k['server_url']}. Is it running?") from e
    if not resp.ok:
        raise RuntimeError(f"Kokoro server error ({resp.status_code}): {resp.text[:300]}")
    Path(out_path).write_bytes(resp.content)


def kokoro_tts(text, config, out_path):
    k = config.get("kokoro", {})
    if k.get("server_url"):
        _kokoro_server(text, k, out_path)
    else:
        _kokoro_local(text, k, out_path)
    return out_path


def synthesize_narration(text, config, output_dir, base_name="_narration_tmp"):
    """Dispatches to the configured TTS engine (config['tts_engine']:
    'google', 'piper' or 'kokoro') and returns the path to the resulting audio file."""
    engine = config.get("tts_engine", "google")
    output_dir = Path(output_dir)

    if engine == "google":
        out_path = output_dir / f"{base_name}.mp3"
        google_tts_long(text, config, out_path)
    elif engine == "piper":
        out_path = output_dir / f"{base_name}.wav"
        piper_tts(text, config, out_path)
    elif engine == "kokoro":
        out_path = output_dir / f"{base_name}.wav"
        kokoro_tts(text, config, out_path)
    else:
        raise ValueError(f"Unknown tts_engine '{engine}' — use 'google', 'piper' or 'kokoro'.")

    return out_path


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe wrappers
# ---------------------------------------------------------------------------

def run(cmd, timeout=None):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}") from e
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result


def get_duration(path):
    result = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    return float(result.stdout.strip())


def get_video_dimensions(path):
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path),
    ])
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def get_video_fps(path):
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(path),
    ])
    num, _, den = result.stdout.strip().partition("/")
    den = den or "1"
    return float(num) / float(den)


def _write_concat_list(paths, list_path):
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            escaped = str(Path(p).resolve()).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")


def concat_audio(paths, out_path):
    """Concatenate audio files of possibly-mixed formats (e.g. Piper's .wav
    narration alongside .mp3 intro/outro) via filter_complex, which decodes
    each input independently rather than requiring matching codecs."""
    paths = [str(p) for p in paths]
    n = len(paths)
    cmd = ["ffmpeg", "-y"]
    for p in paths:
        cmd += ["-i", p]
    filter_str = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    cmd += ["-filter_complex", filter_str, "-map", "[out]",
            "-c:a", "libmp3lame", "-q:a", "2", str(out_path)]
    run(cmd)
    return out_path


def loudnorm_audio(in_path, out_path):
    run(["ffmpeg", "-y", "-i", str(in_path), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:a", "libmp3lame", "-q:a", "2", str(out_path)])
    return out_path


def pad_audio_to_duration(in_path, target_duration, out_path):
    """Pad `in_path` with trailing silence (or trim) to exactly
    target_duration. Used when a visual (e.g. a scroll) needs to run longer
    than the narration covering it."""
    run(["ffmpeg", "-y", "-i", str(in_path),
         "-af", f"apad=whole_dur={target_duration}",
         "-t", f"{target_duration}",
         "-c:a", "libmp3lame", "-q:a", "2", str(out_path)])
    return out_path


def extract_audio(video_path, out_path):
    """Pull just the audio track out of a video file, as mp3."""
    run(["ffmpeg", "-y", "-i", str(video_path), "-vn",
         "-acodec", "libmp3lame", "-q:a", "2", str(out_path)])
    return out_path


def build_looped_video(middle_path, target_duration, out_path):
    """Ping-pong (forward/reverse) loop `middle_path` until it covers
    target_duration, then trim to exactly that length."""
    clip_dur = get_duration(middle_path)
    if clip_dur <= 0:
        raise RuntimeError("Middle video has zero duration.")

    with tempfile.TemporaryDirectory() as tmp:
        reversed_path = os.path.join(tmp, "reversed.mp4")
        run(["ffmpeg", "-y", "-i", str(middle_path), "-vf", "reverse", "-af", "areverse",
             str(reversed_path)])

        segments = []
        total = 0.0
        forward = True
        while total < target_duration:
            segments.append(middle_path if forward else reversed_path)
            total += clip_dur
            forward = not forward

        list_path = os.path.join(tmp, "looplist.txt")
        _write_concat_list(segments, list_path)

        looped_raw = os.path.join(tmp, "looped_raw.mp4")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c", "copy", looped_raw])

        run(["ffmpeg", "-y", "-i", looped_raw, "-t", f"{target_duration:.3f}",
             "-c", "copy", str(out_path)])

    return out_path


def replace_audio(video_path, audio_path, out_path):
    run(["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-shortest", str(out_path)])
    return out_path


def _resolve_canvas(intro, canvas):
    """Pick a target width/height/fps for normalizing multiple video inputs,
    auto-detected from `intro` unless overridden in `canvas`."""
    canvas = canvas or {}
    target_w = canvas.get("width")
    target_h = canvas.get("height")
    target_fps = canvas.get("fps")
    if not target_w or not target_h:
        target_w, target_h = get_video_dimensions(intro)
    if not target_fps:
        target_fps = get_video_fps(intro)
    return target_w, target_h, target_fps


def _norm_video_filter(idx, label, w, h, fps):
    return (
        f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps}[{label}];"
    )


def _norm_audio_filter(idx, label):
    return f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo[{label}];"


def crossfade_many(paths, out_path, fade_seconds, canvas=None):
    """Chain any number of clips together with crossfades (video and audio).
    xfade/acrossfade need every input to match resolution, frame rate, sample
    rate and channel layout, so each clip is first normalized to a common
    canvas (auto-detected from the first clip unless overridden via
    `canvas`). Every clip must have an audio track and be longer than
    `fade_seconds`."""
    paths = [str(p) for p in paths]
    n = len(paths)
    if n < 2:
        raise ValueError("crossfade_many needs at least two clips.")
    durations = [get_duration(p) for p in paths]
    target_w, target_h, target_fps = _resolve_canvas(paths[0], canvas)

    parts = []
    for i in range(n):
        parts.append(_norm_video_filter(i, f"v{i}", target_w, target_h, target_fps))
        parts.append(_norm_audio_filter(i, f"a{i}"))

    v_label, a_label = "v0", "a0"
    running = durations[0]
    for i in range(1, n):
        out_v, out_a = f"vx{i}", f"ax{i}"
        parts.append(
            f"[{v_label}][v{i}]xfade=transition=fade:duration={fade_seconds}:"
            f"offset={running - fade_seconds}[{out_v}];"
        )
        parts.append(f"[{a_label}][a{i}]acrossfade=d={fade_seconds}[{out_a}];")
        running = running + durations[i] - fade_seconds
        v_label, a_label = out_v, out_a

    filter_complex = "".join(parts).rstrip(";")
    cmd = ["ffmpeg", "-y"]
    for p in paths:
        cmd += ["-i", p]
    cmd += ["-filter_complex", filter_complex,
            "-map", f"[{v_label}]", "-map", f"[{a_label}]", str(out_path)]
    run(cmd)
    return out_path


def crossfade_videos(intro, middle, outro, out_path, fade_seconds, canvas=None):
    """Crossfade intro -> middle -> outro (see crossfade_many)."""
    return crossfade_many([intro, middle, outro], out_path, fade_seconds, canvas)


def concat_videos_plain(intro, middle, outro, out_path, canvas=None):
    """Hard-cut concatenation of intro -> middle -> outro — no crossfade.
    Still normalizes resolution/fps/audio format across inputs first (same
    requirement the concat filter has as xfade/acrossfade)."""
    target_w, target_h, target_fps = _resolve_canvas(intro, canvas)

    filter_complex = (
        _norm_video_filter(0, "v0", target_w, target_h, target_fps) +
        _norm_video_filter(1, "v1", target_w, target_h, target_fps) +
        _norm_video_filter(2, "v2", target_w, target_h, target_fps) +
        _norm_audio_filter(0, "a0") + _norm_audio_filter(1, "a1") + _norm_audio_filter(2, "a2") +
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]"
    )
    run(["ffmpeg", "-y", "-i", str(intro), "-i", str(middle), "-i", str(outro),
         "-filter_complex", filter_complex,
         "-map", "[vout]", "-map", "[aout]", str(out_path)])
    return out_path


def tiktok_export(in_path, out_path, config):
    tk = config["video"]["tiktok"]
    w, h = tk["width"], tk["height"]
    fill_mode = tk.get("fill_mode", "blur_pad")

    if fill_mode == "blur_pad":
        # Blurred, scaled-to-fill background + the untouched source centered on top.
        filter_complex = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=20[bg];"
            f"[0:v]scale={w}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
        )
        run(["ffmpeg", "-y", "-i", str(in_path), "-filter_complex", filter_complex,
             "-map", "[vout]", "-map", "0:a", "-c:a", "copy", str(out_path)])
    elif fill_mode == "crop":
        run(["ffmpeg", "-y", "-i", str(in_path), "-vf",
             f"crop=ih*{w}/{h}:ih,scale={w}:{h}", str(out_path)])
    else:  # letterbox
        run(["ffmpeg", "-y", "-i", str(in_path), "-vf",
             f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black", str(out_path)])

    return out_path


# ---------------------------------------------------------------------------
# "COCku" mode: adds a dimmed overlay + vertically scrolling script text over
# the middle video, with a silent pause before/after the narration.
# ---------------------------------------------------------------------------

def build_padded_audio(narration_path, pad_seconds, out_path):
    """Add `pad_seconds` of silence before and after the narration track."""
    delay_ms = int(pad_seconds * 1000)
    run(["ffmpeg", "-y", "-i", str(narration_path),
         "-af", f"adelay={delay_ms}|{delay_ms}:all=1,apad=pad_dur={pad_seconds}",
         "-c:a", "libmp3lame", "-q:a", "2", str(out_path)])
    return out_path


def _wrap_script_text(text, chars_per_line=45):
    """Wrap script text to a fixed line width so it fits the video frame,
    preserving existing paragraph breaks."""
    wrapped_lines = []
    for para in text.strip().splitlines():
        if not para.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(para, width=chars_per_line) or [""])
    return "\n".join(wrapped_lines)


def _escape_ffmpeg_filter_path(path):
    """Escape a filesystem path for safe use inside an ffmpeg -vf filter
    string (drawtext's fontfile/textfile args), where ':' and '\\' are
    filtergraph syntax characters. Matters most on Windows (drive letters,
    backslash separators)."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def build_cocku_middle(video_path, narration_path, script_text, config, out_path):
    """Build the COCku-mode middle segment: loops the video to
    narration length + 2x pad_seconds, dims it (with a soft fade in/out
    rather than a hard cut) and scrolls the script over it during the
    narration window, with silent pauses before/after."""
    cocku = config["video"]["cocku"]
    pad_seconds = cocku.get("pad_seconds", 1)
    font_file = cocku.get("font_file")
    font_color = cocku.get("font_color", "white")
    font_size = cocku.get("font_size", 48)
    dim_opacity = cocku.get("dim_opacity", 0.55)
    chars_per_line = cocku.get("chars_per_line", 45)
    dim_fade_seconds = cocku.get("dim_fade_seconds", 0.4)

    if not font_file or not Path(font_file).exists():
        raise RuntimeError(
            "Set video.cocku.font_file in config.json to a valid .ttf/.otf "
            "font file path (e.g. \"C:/Windows/Fonts/arial.ttf\")."
        )

    narration_dur = get_duration(narration_path)
    target_duration = narration_dur + 2 * pad_seconds

    # Keep the dim fade from overlapping itself or spilling past the pads.
    fade_dur = max(0.05, min(dim_fade_seconds, pad_seconds, narration_dur / 2))

    with tempfile.TemporaryDirectory() as tmp:
        looped_path = os.path.join(tmp, "looped.mp4")
        build_looped_video(video_path, target_duration, looped_path)
        width, height = get_video_dimensions(looped_path)

        padded_audio_path = os.path.join(tmp, "padded_audio.mp3")
        build_padded_audio(narration_path, pad_seconds, padded_audio_path)

        text_file = os.path.join(tmp, "scroll_text.txt")
        Path(text_file).write_text(_wrap_script_text(script_text, chars_per_line), encoding="utf-8")

        window_start = pad_seconds
        window_end = pad_seconds + narration_dur
        font_file_esc = _escape_ffmpeg_filter_path(font_file)
        text_file_esc = _escape_ffmpeg_filter_path(text_file)

        # A black layer with its own alpha channel, faded in/out via ffmpeg's
        # `fade` filter (alpha=1 mode fades the alpha plane rather than the
        # color), then composited over the base video with `overlay`. This
        # gives a smooth dim in/out instead of drawbox's hard on/off cut.
        filter_complex = (
            f"color=black:s={width}x{height}:d={target_duration},"
            f"format=yuva420p,colorchannelmixer=aa={dim_opacity},"
            f"fade=t=in:st={window_start}:d={fade_dur}:alpha=1,"
            f"fade=t=out:st={window_end - fade_dur}:d={fade_dur}:alpha=1[dim];"
            f"[0:v][dim]overlay=0:0:format=auto[dimmed];"
            f"[dimmed]drawtext=fontfile='{font_file_esc}':textfile='{text_file_esc}':"
            f"fontcolor={font_color}:fontsize={font_size}:text_align=center:"
            f"x=(w-text_w)/2:"
            f"y='h-(h+text_h)*(t-{window_start})/{narration_dur}':"
            f"enable='between(t,{window_start},{window_end})'[vout]"
        )

        run(["ffmpeg", "-y", "-i", looped_path, "-i", padded_audio_path,
             "-filter_complex", filter_complex, "-map", "[vout]", "-map", "1:a",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-c:a", "aac", "-b:a", "192k", str(out_path)])

    return out_path


# ---------------------------------------------------------------------------
# "Aesop" mode: intro -> middle clip (plays once, untouched) -> a still image
# shown while the script is read (first line, a beat, then the rest) -> outro.
# ---------------------------------------------------------------------------

resolve_canvas = _resolve_canvas  # public name for callers outside this module


def has_audio_stream(path):
    result = run(["ffprobe", "-v", "error", "-select_streams", "a",
                  "-show_entries", "stream=index", "-of", "csv=p=0", str(path)])
    return bool(result.stdout.strip())


def ensure_audio_stream(video_path, out_path):
    """Return `video_path` unchanged if it already has an audio track;
    otherwise write a copy to `out_path` with silent audio added (the
    crossfade needs an audio track on every clip) and return that."""
    if has_audio_stream(video_path):
        return video_path
    duration = get_duration(video_path)
    run(["ffmpeg", "-y", "-i", str(video_path),
         "-f", "lavfi", "-t", f"{duration:.3f}",
         "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-shortest", str(out_path)])
    return out_path


def compose_still_frame(image_path, out_png, width, height, fit_mode="blur_pad"):
    """Fit an image onto a width x height canvas and save it as one PNG frame.
    fit_mode: 'blur_pad' (whole image, blurred copy fills the rest — same
    look as the TikTok export), 'pad' (whole image, black bars) or 'crop'
    (fills the frame, trimming the edges)."""
    w, h = width, height
    if fit_mode == "blur_pad":
        fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},gblur=sigma=20[bg];"
              f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]")
        run(["ffmpeg", "-y", "-i", str(image_path), "-filter_complex", fc,
             "-map", "[vout]", "-frames:v", "1", str(out_png)])
    elif fit_mode == "crop":
        run(["ffmpeg", "-y", "-i", str(image_path), "-vf",
             f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1",
             "-frames:v", "1", str(out_png)])
    elif fit_mode == "pad":
        run(["ffmpeg", "-y", "-i", str(image_path), "-vf",
             f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
             "-frames:v", "1", str(out_png)])
    else:
        raise ValueError(f"Unknown image_fit '{fit_mode}' — use 'blur_pad', 'pad' or 'crop'.")
    return out_png


def build_aesop_story_segment(image_paths, narration1_path, rest_paths,
                              canvas_ref, config, out_path, narration_out_path):
    """Build the narrated-image part of an Aesop episode.

    Narration = first line, a pause (`pause_after_first_line_seconds`, only
    if there is more to read), then the rest of the script in one chunk per
    extra image. Image 1 is on screen from the start (with the first line
    and its portion); each later image FADES IN over the previous one
    (`image_fade_seconds`, centered on the moment its portion begins).
    `edge_pad_seconds` of silence is added at both ends so the crossfades
    into/out of the segment never fade the first or last word.

    `image_paths` may be a single path or a list (1-3). `rest_paths` is a
    list of narration chunks, one per image: chunk 1 belongs to image 1
    (after the first line), chunk 2 to image 2, and so on; may be empty.

    Also writes the narration on its own (no edge padding) to
    `narration_out_path` for the companion audio episode."""
    if isinstance(image_paths, (str, os.PathLike)):
        image_paths = [image_paths]
    rest_paths = [p for p in (rest_paths or []) if p is not None]
    if len(image_paths) > max(1, len(rest_paths)):
        raise ValueError("More images than narration portions.")

    aesop = config["video"]["aesop"]
    pause = aesop.get("pause_after_first_line_seconds", 2)
    edge_pad = aesop.get("edge_pad_seconds", 1)
    fit_mode = aesop.get("image_fit", "blur_pad")
    fade = float(aesop.get("image_fade_seconds", 1.0))

    with tempfile.TemporaryDirectory() as tmp:
        pieces = []
        if rest_paths:
            first = os.path.join(tmp, "first_with_pause.mp3")
            pad_audio_to_duration(narration1_path, get_duration(narration1_path) + pause, first)
        else:
            first = narration1_path
        pieces.append(first)
        pieces.extend(rest_paths)

        # when each image's portion begins on the narration timeline
        # (portion 1 = first line + pause + rest chunk 1)
        starts = [0.0] + [get_duration(first) + sum(get_duration(r) for r in rest_paths[:i])
                          for i in range(1, len(image_paths))]

        concat_audio(pieces, narration_out_path)
        story_audio = os.path.join(tmp, "story_audio.mp3")
        build_padded_audio(narration_out_path, edge_pad, story_audio)
        duration = get_duration(story_audio)

        width, height, fps = _resolve_canvas(canvas_ref, config["video"].get("canvas"))
        cmd = ["ffmpeg", "-y"]
        frames = []
        for i, img in enumerate(image_paths):
            frame = os.path.join(tmp, f"frame{i}.png")
            compose_still_frame(img, frame, width, height, fit_mode)
            frames.append(frame)
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", frame]
        cmd += ["-i", story_audio]

        chains = ["[0:v]format=yuv420p[v0]"]
        for i in range(1, len(image_paths)):
            st = max(0.0, edge_pad + starts[i] - fade / 2)
            chains.append(f"[{i}:v]format=yuva420p,fade=t=in:st={st:.3f}:d={fade:.3f}:alpha=1[f{i}]")
            chains.append(f"[v{i-1}][f{i}]overlay=format=auto[v{i}]")
        last = f"v{len(image_paths) - 1}"
        chains.append(f"[{last}]format=yuv420p[vout]")

        cmd += ["-filter_complex", ";".join(chains),
                "-map", "[vout]", "-map", f"{len(image_paths)}:a",
                "-t", f"{duration:.3f}",
                "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "aac", "-b:a", "192k", str(out_path)]
        run(cmd)

    return out_path


# ---------------------------------------------------------------------------
# Optional music bed (assets/middle.mp3), mixed under part of an episode
# ---------------------------------------------------------------------------

MUSIC_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


def find_music_bed(folder, base_name="middle"):
    """Return `{folder}/{base_name}.<audio ext>` (middle.mp3 first) or None.
    Only audio extensions are considered, so middle.mp4 is never mistaken
    for it."""
    folder = Path(folder)
    for ext in MUSIC_EXTS:
        candidate = folder / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    return None


def mix_music_bed(in_path, music_path, start, length, volume, fade_seconds, out_path, has_video=True):
    """Mix a music bed under `in_path` (a video or an audio file): the music
    starts at `start` seconds, runs for `length` seconds (looped if the file
    is shorter, cut if longer), fades in/out over `fade_seconds`, and is
    scaled by `volume` (1.0 = the file's own level, 0.25 = quieter). The
    original audio is left as-is; video is copied untouched."""
    length = max(0.1, float(length))
    fade = max(0.0, min(float(fade_seconds), length / 2))
    delay_ms = int(round(max(0.0, start) * 1000))
    chain = ("aformat=sample_rates=48000:channel_layouts=stereo,"
             f"atrim=0:{length:.3f},asetpts=PTS-STARTPTS")
    if fade > 0:
        chain += f",afade=t=in:st=0:d={fade:.3f},afade=t=out:st={length - fade:.3f}:d={fade:.3f}"
    chain += f",volume={float(volume):.3f},adelay={delay_ms}|{delay_ms}"
    fc = (f"[1:a]{chain}[m];"
          "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[b];"
          "[b][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
    cmd = ["ffmpeg", "-y", "-i", str(in_path), "-stream_loop", "-1", "-i", str(music_path),
           "-filter_complex", fc]
    if has_video:
        cmd += ["-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-map", "[aout]", "-c:a", "libmp3lame", "-q:a", "2"]
    cmd.append(str(out_path))
    run(cmd)
    return out_path
