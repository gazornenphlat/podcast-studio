"""Hand a finished video episode to the Content Scheduler.

When a process finishes an episode it calls hand_off(). That writes a small
JSON note into the scheduler's inbox folder; the scheduler picks it up
(within a minute, or immediately if it's running), puts the episode in the
right series' queue with its video file attached, and gives it the next open
posting day.

Configure it per process in config.json:

    "scheduler": {
      "enabled": true,
      "series": "COCKu-YT",                         # series name in the scheduler
      "inbox": "../../content_scheduler/inbox",     # relative to this process folder
      "url": "http://127.0.0.1:5050"                # optional: ask a running scheduler to pick it up now
    }
"""
import datetime as dt
import json
import os
import uuid
from pathlib import Path

import requests


def _abs(p):
    return str(Path(p).resolve()) if p else None


def hand_off(config, title, video, tiktok=None, mp3=None, script=None, extra=None):
    sch = config.get("scheduler") or {}
    if not sch.get("enabled"):
        return None
    series = sch.get("series")
    if not series:
        print("⚠️  scheduler.enabled is on but scheduler.series is empty — not scheduled.")
        return None

    inbox = Path(sch.get("inbox", "../../content_scheduler/inbox")).resolve()
    try:
        inbox.mkdir(parents=True, exist_ok=True)
    except OSError as ex:
        print(f"⚠️  Couldn't reach the scheduler inbox {inbox}: {ex} — not scheduled.")
        return None

    note = {
        "series": series,
        "title": title.strip(),
        "video": _abs(video),
        "tiktok": _abs(tiktok),
        "mp3": _abs(mp3),
        "script": _abs(script),
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        **(extra or {}),
    }
    name = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.json"
    tmp = inbox / (name + ".tmp")
    tmp.write_text(json.dumps(note, indent=2), encoding="utf-8")
    os.replace(tmp, inbox / name)          # scheduler never sees a half-written note

    url = (sch.get("url") or "").rstrip("/")
    if url:
        headers = {}
        if sch.get("token"):
            headers["X-API-Token"] = sch["token"]
        try:
            r = requests.post(f"{url}/api/inbox/ingest", timeout=10, headers=headers)
            for item in (r.json().get("scheduled") or []):
                if item.get("title") == note["title"] and item.get("series") == series:
                    print(f"📅 Scheduled: {series} – {note['title']} → {item['date']}")
                    return item
        except Exception:
            pass                            # not running: it will pick the note up when it starts
    print(f"📅 Sent to the Content Scheduler ({series}). It gets the next open posting day "
          "as soon as the scheduler sees it.")
    return note
