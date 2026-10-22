"""Facebook Page video. Uses Facebook's native scheduling: uploaded up to 24h early,
Facebook publishes it at post_at. Needs a Page access token."""
from datetime import timedelta, datetime, timezone

from ._http import env, check, requests

LEAD_TIME = timedelta(hours=24)
V = "v21.0"


def post(item):
    page = env("FACEBOOK_PAGE_ID")
    token = env("FACEBOOK_PAGE_TOKEN")
    data = {"title": item["title"], "description": item["caption"], "access_token": token}
    ts = int(item["post_at"].timestamp())
    # Facebook only accepts scheduled times at least 10 minutes out.
    if ts - datetime.now(timezone.utc).timestamp() > 15 * 60:
        data.update(published="false", scheduled_publish_time=str(ts))
    with open(item["video_path"], "rb") as f:
        r = check(requests.post(f"https://graph-video.facebook.com/{V}/{page}/videos",
                                data=data, files={"source": f}, timeout=1800))
    return f"https://www.facebook.com/{page}/videos/{r.json()['id']}"
