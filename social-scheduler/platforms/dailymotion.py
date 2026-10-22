"""Dailymotion via its API (API key from your Partner/Studio account)."""
import os
from datetime import timedelta

from ._http import env, check, requests

LEAD_TIME = timedelta(0)
API = "https://api.dailymotion.com"


def post(item):
    tok = check(requests.post(f"{API}/oauth/token", data={
        "grant_type": "password", "scope": "manage_videos",
        "client_id": env("DAILYMOTION_API_KEY"), "client_secret": env("DAILYMOTION_API_SECRET"),
        "username": env("DAILYMOTION_USERNAME"), "password": env("DAILYMOTION_PASSWORD"),
    }, timeout=30)).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    up = check(requests.get(f"{API}/file/upload", headers=h, timeout=30)).json()["upload_url"]
    with open(item["video_path"], "rb") as f:
        url = check(requests.post(up, files={"file": f}, timeout=1800)).json()["url"]

    v = check(requests.post(f"{API}/me/videos", headers=h, data={
        "url": url, "title": item["title"], "description": item["caption"],
        "tags": ",".join(item["tags"]),
        "channel": os.getenv("DAILYMOTION_CHANNEL", "lifestyle"),
        "is_created_for_kids": "false", "published": "true",
    }, timeout=60)).json()
    return f"https://www.dailymotion.com/video/{v['id']}"
