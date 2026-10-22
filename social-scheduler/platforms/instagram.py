"""Instagram Reels via the Instagram Graph API (Business/Creator account linked
to a Facebook Page). Uses resumable upload, so no public video URL is needed."""
import os
from datetime import timedelta

from ._http import env, check, poll, text_with_tags, requests

LEAD_TIME = timedelta(0)
V = "v21.0"
G = f"https://graph.facebook.com/{V}"


def post(item):
    uid, token = env("INSTAGRAM_USER_ID"), env("INSTAGRAM_ACCESS_TOKEN")
    c = check(requests.post(f"{G}/{uid}/media", data={
        "media_type": "REELS", "upload_type": "resumable",
        "caption": text_with_tags(item, 2200), "share_to_feed": "true",
        "access_token": token}, timeout=60)).json()["id"]

    size = os.path.getsize(item["video_path"])
    with open(item["video_path"], "rb") as f:
        check(requests.post(f"https://rupload.facebook.com/ig-api-upload/{V}/{c}",
                            headers={"Authorization": f"OAuth {token}",
                                     "offset": "0", "file_size": str(size)},
                            data=f, timeout=1800))

    status = lambda: check(requests.get(f"{G}/{c}", params={
        "fields": "status_code", "access_token": token}, timeout=30)).json()
    poll(status, lambda r: r.get("status_code") == "FINISHED",
         lambda r: r.get("status_code") in ("ERROR", "EXPIRED"))

    mid = check(requests.post(f"{G}/{uid}/media_publish", data={
        "creation_id": c, "access_token": token}, timeout=60)).json()["id"]
    link = requests.get(f"{G}/{mid}", params={"fields": "permalink",
                                               "access_token": token}, timeout=30).json()
    return link.get("permalink", f"instagram media {mid}")
