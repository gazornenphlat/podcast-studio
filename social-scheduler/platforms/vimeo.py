"""Vimeo via the official API (tus resumable upload). Token needs 'upload',
'edit' and 'private' scopes (developer.vimeo.com/apps)."""
import os
from datetime import timedelta

from ._http import env, check, requests

LEAD_TIME = timedelta(0)
API = "https://api.vimeo.com"
CHUNK = 64 * 1024 * 1024


def post(item):
    h = {"Authorization": f"bearer {env('VIMEO_ACCESS_TOKEN')}",
         "Accept": "application/vnd.vimeo.*+json;version=3.4"}
    size = os.path.getsize(item["video_path"])
    v = check(requests.post(f"{API}/me/videos", headers=h, json={
        "upload": {"approach": "tus", "size": size},
        "name": item["title"], "description": item["caption"],
        "privacy": {"view": os.getenv("VIMEO_PRIVACY", "anybody")},
    }, timeout=60)).json()

    link, offset = v["upload"]["upload_link"], 0
    with open(item["video_path"], "rb") as f:
        while offset < size:
            f.seek(offset)
            r = check(requests.patch(link, data=f.read(CHUNK), timeout=1800, headers={
                "Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
                "Content-Type": "application/offset+octet-stream"}))
            offset = int(r.headers["Upload-Offset"])

    if item["tags"]:
        requests.put(f"{API}{v['uri']}/tags", headers=h,
                     json=[{"tag": t} for t in item["tags"]], timeout=30)
    return v["link"]
