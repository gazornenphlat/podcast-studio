"""Small helpers shared by platform modules."""
import os
import time

import requests


def env(name, default=None):
    v = os.getenv(name, default)
    if v in (None, ""):
        raise RuntimeError(f"Missing setting {name} in .env")
    return v


def check(resp):
    if not resp.ok:
        raise RuntimeError(f"{resp.request.method} {resp.url.split('?')[0]} -> "
                           f"{resp.status_code}: {resp.text[:500]}")
    return resp


def poll(fn, done, failed=lambda r: False, tries=90, wait=10):
    """Call fn() until done(result); raise if failed(result) or timeout."""
    for _ in range(tries):
        r = fn()
        if done(r):
            return r
        if failed(r):
            raise RuntimeError(f"Processing failed: {r}")
        time.sleep(wait)
    raise TimeoutError("Platform still processing the video")


def public_url(item):
    """For platforms that fetch the video from a URL (Threads)."""
    base = env("MEDIA_BASE_URL").rstrip("/")
    return f"{base}/{os.path.basename(item['video_path'])}"


def text_with_tags(item, limit=None):
    text = item["caption"]
    tags = " ".join(f"#{t}" for t in item["tags"])
    if tags and (limit is None or len(text) + len(tags) + 1 <= limit):
        text = f"{text} {tags}".strip()
    return text[:limit] if limit else text


requests = requests
