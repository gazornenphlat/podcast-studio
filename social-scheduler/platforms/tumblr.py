"""Tumblr video post (NPF format) with OAuth1 keys from tumblr.com/oauth/apps."""
import json
from datetime import timedelta

from requests_oauthlib import OAuth1

from ._http import env, check, requests

LEAD_TIME = timedelta(0)


def post(item):
    blog = env("TUMBLR_BLOG")  # e.g. myblog.tumblr.com
    auth = OAuth1(env("TUMBLR_CONSUMER_KEY"), env("TUMBLR_CONSUMER_SECRET"),
                  env("TUMBLR_TOKEN"), env("TUMBLR_TOKEN_SECRET"))
    body = {
        "content": [
            {"type": "video", "media": [{"type": "video/mp4", "identifier": "vid"}]},
            {"type": "text", "text": item["caption"]},
        ],
        "tags": ",".join(item["tags"]),
        "state": "published",
    }
    with open(item["video_path"], "rb") as f:
        r = check(requests.post(f"https://api.tumblr.com/v2/blog/{blog}/posts", auth=auth,
                                files={"json": (None, json.dumps(body), "application/json"),
                                       "vid": ("video.mp4", f, "video/mp4")}, timeout=1800))
    pid = r.json()["response"]["id"]
    return f"https://{blog}/post/{pid}"
