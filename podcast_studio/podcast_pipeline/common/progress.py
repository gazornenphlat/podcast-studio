"""Remembers which stories of a script are finished, so a run can stop after
any story and the next run picks up where it left off.

Saved in the process folder as progress.json, per script file. Stories are
recognised by their text, so editing one story or adding new ones to the
file doesn't lose track of the ones already done. --start-over forgets it.
"""
import hashlib
import json
import os
from pathlib import Path

FILE = "progress.json"


def story_key(story):
    text = story if isinstance(story, str) else story.get("display", "") + "\0" + story.get("tts", "")
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


class Progress:
    def __init__(self, script_path, start_over=False):
        self.path = Path(FILE).resolve()          # process folder (setup() chdirs there)
        self.key = str(Path(script_path).resolve()).lower()
        try:
            self.all = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.all = {}
        if start_over:
            self.all.pop(self.key, None)
            self.save()
            print("↺ Starting over: progress for this script cleared.")
        self.me = self.all.setdefault(self.key, {"done": [], "rewrites": {}})
        self.me.setdefault("done", []); self.me.setdefault("rewrites", {})

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.all, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def is_done(self, story):
        return story_key(story) in self.me["done"]

    def mark_done(self, story):
        k = story_key(story)
        if k not in self.me["done"]:
            self.me["done"].append(k)
        self.save()

    def pending(self, stories):
        """[(number, story)] still to do, in file order; prints what's skipped."""
        todo = [(i, s) for i, s in enumerate(stories, 1) if not self.is_done(s)]
        skipped = len(stories) - len(todo)
        if skipped and todo:
            print(f"↪ Picking up where you left off: {skipped} of {len(stories)} story(ies) "
                  f"already done, starting at story {todo[0][0]}.")
        if not todo:
            print(f"✓ All {len(stories)} story(ies) in this script are already done. "
                  "Add new stories, or run with --start-over to make them again.")
        return todo

    def flag(self, story, name, value=None):
        """Small per-story markers (e.g. already added to the Word file)."""
        d = self.me.setdefault(name, [])
        k = story_key(story)
        if value is None:
            return k in d
        if value and k not in d:
            d.append(k); self.save()
        return value

    # WITN: cache each rewrite so stopping (or quitting at the image pause)
    # never asks the LLM to rewrite the same story twice.
    def get_rewrite(self, raw):
        return self.me["rewrites"].get(story_key(raw))

    def set_rewrite(self, raw, value):
        self.me["rewrites"][story_key(raw)] = value
        self.save()


def ask_continue(left, next_label=""):
    """After a story: ask whether to go on. Enter/y = yes. No terminal = yes."""
    if left <= 0:
        return True
    nxt = f" — next: {next_label[:60]}" if next_label else ""
    try:
        a = input(f"\nContinue with the next story? ({left} left{nxt}) [Y/n]: ")
    except EOFError:
        return True
    if a.strip().lower() in ("n", "no", "q", "quit", "stop", "exit"):
        print("⏸  Stopped. Run the same command again to pick up with the next story.")
        return False
    return True


def first_line(story):
    text = story if isinstance(story, str) else story.get("display", "")
    return text.strip().split("\n", 1)[0].strip()
