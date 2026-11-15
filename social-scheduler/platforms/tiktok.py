"""TikTok Content Posting API (direct post). Runs at post time.
Until your app passes TikTok's audit, privacy must be SELF_ONLY."""
import math
import os
import time
from datetime import timedelta

import requests

from ._http import env

LEAD_TIME = timedelta(0)
API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024  # 10 MB


def chunk_count(size):
    """How many chunks a file of `size` bytes needs: every chunk but the
    last is exactly CHUNK, so the count is ceil(size / CHUNK)."""
    return 1 if size <= CHUNK else math.ceil(size / CHUNK)


def _headers():
    return {"Authorization": f"Bearer {env('TIKTOK_ACCESS_TOKEN')}",
            "Content-Type": "application/json; charset=UTF-8"}


def post(item):
    path = item["video_path"]
    size = os.path.getsize(path)
    chunk = size if size <= CHUNK else CHUNK
    count = chunk_count(size)

    caption = item["caption"] + "".join(f" #{t}" for t in item["tags"])
    init = requests.post(f"{API}/post/publish/video/init/", headers=_headers(), json={
        "post_info": {
            "title": caption[:2200],
            "privacy_level": os.getenv("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY"),
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": count},
    }, timeout=60)
    init.raise_for_status()
    data = init.json()["data"]

    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            # Last chunk absorbs the remainder.
            length = size - start if i == count - 1 else chunk
            f.seek(start)
            requests.put(data["upload_url"], data=f.read(length), headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {start}-{start + length - 1}/{size}",
            }, timeout=300).raise_for_status()

    # Poll until TikTok finishes processing.
    for _ in range(60):
        st = requests.post(f"{API}/post/publish/status/fetch/", headers=_headers(),
                           json={"publish_id": data["publish_id"]}, timeout=30).json()
        status = st["data"].get("status")
        if status == "PUBLISH_COMPLETE":
            return f"tiktok publish_id {data['publish_id']}"
        if status == "FAILED":
            raise RuntimeError(f"TikTok failed: {st['data'].get('fail_reason')}")
        time.sleep(10)
    raise TimeoutError("TikTok still processing; check the app")
