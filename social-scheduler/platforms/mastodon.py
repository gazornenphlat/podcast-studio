"""Mastodon (any instance). Create an app in Preferences > Development with
write:media and write:statuses scopes."""
import time
from datetime import timedelta

from mastodon import Mastodon

from ._http import env, text_with_tags

LEAD_TIME = timedelta(0)


def post(item):
    m = Mastodon(access_token=env("MASTODON_ACCESS_TOKEN"),
                 api_base_url=env("MASTODON_INSTANCE"))
    media = m.media_post(item["video_path"], mime_type="video/mp4", synchronous=True)
    time.sleep(2)
    s = m.status_post(text_with_tags(item, 500), media_ids=[media["id"]])
    return s["url"]
