"""Pinterest video Pin (API v5). Token needs pins:write and boards:read."""
from datetime import timedelta

from ._http import env, check, poll, requests

LEAD_TIME = timedelta(0)
API = "https://api.pinterest.com/v5"


def post(item):
    h = {"Authorization": f"Bearer {env('PINTEREST_ACCESS_TOKEN')}"}
    m = check(requests.post(f"{API}/media", headers=h, json={"media_type": "video"},
                            timeout=30)).json()
    with open(item["video_path"], "rb") as f:
        check(requests.post(m["upload_url"], data=m["upload_parameters"],
                            files={"file": f}, timeout=1800))
    poll(lambda: check(requests.get(f"{API}/media/{m['media_id']}", headers=h,
                                    timeout=30)).json(),
         lambda r: r.get("status") == "succeeded", lambda r: r.get("status") == "failed")
    pin = check(requests.post(f"{API}/pins", headers=h, json={
        "board_id": env("PINTEREST_BOARD_ID"),
        "title": item["title"][:100], "description": item["caption"][:500],
        "media_source": {"source_type": "video_id", "media_id": m["media_id"],
                         "cover_image_key_frame_time": 1},
    }, timeout=60)).json()
    return f"https://www.pinterest.com/pin/{pin['id']}/"
