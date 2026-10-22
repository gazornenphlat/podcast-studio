"""Bluesky video post (atproto SDK). Use an app password, not your main password.
Bluesky limits: 3 minutes, 100 MB."""
from datetime import timedelta

from atproto import Client

from ._http import env, text_with_tags

LEAD_TIME = timedelta(0)


def post(item):
    c = Client()
    c.login(env("BLUESKY_HANDLE"), env("BLUESKY_APP_PASSWORD"))
    with open(item["video_path"], "rb") as f:
        r = c.send_video(text=text_with_tags(item, 300), video=f.read(),
                         video_alt=item["title"])
    rkey = r.uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{env('BLUESKY_HANDLE')}/post/{rkey}"
