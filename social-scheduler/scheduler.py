"""Posts whatever in queue.csv is due. Run every few minutes (cron / Task Scheduler).

    python scheduler.py            # post anything due
    python scheduler.py --dry-run  # show what would post, touch nothing
    python scheduler.py --status   # show every queue item's state per platform
    python scheduler.py --done demo-001:rumble   # mark a manual upload as done
    python scheduler.py --platforms              # list supported platform names
    python scheduler.py --login youtube          # sign in to a site now
"""
import argparse
import csv
import json
import os
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "queue.csv")
LOG = os.path.join(HERE, "post_log.json")
MANUAL_TODO = os.path.join(HERE, "manual_uploads.md")
MAX_ATTEMPTS = 3


def load_queue():
    items = []
    with open(QUEUE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("id"):
                continue
            post_at = datetime.fromisoformat(row["post_at"])
            if post_at.tzinfo is None:
                raise ValueError(f"{row['id']}: post_at needs a timezone offset, e.g. -04:00")
            video = row["video_path"]
            items.append({
                "id": row["id"],
                "post_at": post_at,
                "video_path": video if os.path.isabs(video) else os.path.join(HERE, video),
                "title": row.get("title", ""),
                "caption": row.get("caption", ""),
                "tags": [t.strip() for t in row.get("tags", "").split(";") if t.strip()],
                "platforms": [p.strip().lower() for p in row["platforms"].split(";") if p.strip()],
            })
    return items


def load_log():
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_log(log):
    tmp = LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, LOG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--done", metavar="ID:PLATFORM", help="mark a manual upload done")
    ap.add_argument("--platforms", action="store_true")
    ap.add_argument("--login", metavar="PLATFORM", help="sign in to a site now")
    args = ap.parse_args()

    os.chdir(HERE)  # so client_secret.json / tokens are found wherever it's run from
    load_dotenv(os.path.join(HERE, ".env"))
    import platforms

    if args.login:
        mod = platforms.get(args.login)
        if mod is None or not hasattr(mod, "login"):
            print(f"{args.login} doesn't need a sign-in step; its keys go in .env")
        else:
            print(mod.login())
        return

    if args.platforms:
        print("API:    " + ", ".join(platforms.API_PLATFORMS))
        print("Manual: " + ", ".join(platforms.UPLOAD_PAGES))
        print("Aliases: " + ", ".join(f"{a}={b}" for a, b in platforms.ALIASES.items()))
        return

    now = datetime.now(timezone.utc)
    log = load_log()

    if args.done:
        entry = log.get(args.done)
        if not entry:
            print(f"No log entry for {args.done}")
            return
        entry.update(status="posted", result="uploaded manually",
                     updated=now.isoformat())
        save_log(log)
        print(f"Marked {args.done} as posted")
        return

    for item in load_queue():
        for name in item["platforms"]:
            key = f"{item['id']}:{name}"
            entry = log.get(key, {"status": "pending", "attempts": 0})

            if args.status:
                print(f"{key:30} {item['post_at'].isoformat():28} {entry['status']:8} "
                      f"{entry.get('result') or entry.get('error', '')}")
                continue

            if entry["status"] in ("posted", "manual") or entry["attempts"] >= MAX_ATTEMPTS:
                continue
            try:
                mod = platforms.get(name)
            except ImportError as e:
                print(f"[error] {key}: missing package ({e}); run pip install -r requirements.txt")
                continue
            if mod is None:
                print(f"[skip] {key}: unknown platform")
                continue
            if now < item["post_at"] - mod.LEAD_TIME:
                continue
            if not os.path.exists(item["video_path"]):
                print(f"[error] {key}: missing video {item['video_path']}")
                continue

            if args.dry_run:
                print(f"[dry-run] would post {key}")
                continue

            if getattr(mod, "MANUAL", False):
                with open(MANUAL_TODO, "a", encoding="utf-8") as f:
                    f.write(f"- [ ] **{key}** due {item['post_at'].isoformat()}\n"
                            f"  - file: `{item['video_path']}`\n"
                            f"  - title: {item['title']}\n"
                            f"  - caption: {item['caption']}\n"
                            f"  - tags: {', '.join(item['tags'])}\n"
                            f"  - upload at: {mod.url}\n"
                            f"  - when done: `python scheduler.py --done {key}`\n\n")
                entry.update(status="manual", result="waiting for manual upload",
                             updated=now.isoformat())
                log[key] = entry
                save_log(log)
                print(f"[manual] {key}: added to manual_uploads.md")
                continue

            print(f"[posting] {key} ...")
            entry["attempts"] += 1
            try:
                entry["result"] = mod.post(item)
                entry["status"] = "posted"
                entry.pop("error", None)
                print(f"[ok] {key} -> {entry['result']}")
            except Exception as e:  # keep going with other posts
                entry["status"] = "failed"
                entry["error"] = f"{type(e).__name__}: {e}"
                print(f"[fail] {key}: {entry['error']}")
                traceback.print_exc()
            entry["updated"] = datetime.now(timezone.utc).isoformat()
            log[key] = entry
            save_log(log)  # save after each post so a crash never double-posts


if __name__ == "__main__":
    main()
