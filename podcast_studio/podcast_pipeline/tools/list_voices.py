#!/usr/bin/env python3
"""
List available Google Cloud TTS voices, straight from the API (so it's
always current — voice lineups change over time).

Usage:
    python list_voices.py                    # all en-US voices
    python list_voices.py --language en-GB    # a different language/locale
    python list_voices.py --language "" # every voice, every language (long)
"""

import argparse
import json
import os

import requests

import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "common"))
from utils import load_config


def main():
    parser = argparse.ArgumentParser(description="List available Google Cloud TTS voices.")
    parser.add_argument("--language", default="en-US", help="BCP-47 language code, e.g. en-US, en-GB, es-ES. Empty string = all languages.")
    parser.add_argument("--config", default=str(__import__("pathlib").Path(__file__).resolve().parent.parent / "audio" / "config.json"), help="Path to a process config.json (default: audio/config.json)")
    args = parser.parse_args()

    config = load_config(args.config)
    g = config["google_tts"]
    api_key = g.get("api_key") or os.environ.get(g.get("api_key_env", "GOOGLE_TTS_API_KEY"))
    if not api_key:
        raise SystemExit("Set google_tts.api_key in config.json or the GOOGLE_TTS_API_KEY env var first.")

    url = "https://texttospeech.googleapis.com/v1/voices"
    params = {"key": api_key}
    if args.language:
        params["languageCode"] = args.language

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    voices = resp.json().get("voices", [])

    if not voices:
        print(f"No voices found for language '{args.language}'.")
        return

    # Group by tier (encoded in the voice name, e.g. en-US-Neural2-F)
    def tier_of(name):
        parts = name.split("-")
        return parts[2] if len(parts) >= 3 else "Other"

    voices.sort(key=lambda v: (tier_of(v["name"]), v["name"]))

    current_tier = None
    for v in voices:
        tier = tier_of(v["name"])
        if tier != current_tier:
            print(f"\n--- {tier} ---")
            current_tier = tier
        gender = v.get("ssmlGender", "?").title()
        rate = v.get("naturalSampleRateHertz", "?")
        print(f"  {v['name']:<28} {gender:<10} {rate} Hz")

    print(f"\n{len(voices)} voice(s) found for '{args.language or 'all languages'}'.")
    print("Set google_tts.voice_name in config.json to any name above.")


if __name__ == "__main__":
    main()
