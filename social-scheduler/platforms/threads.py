"""Threads. The API only accepts a PUBLIC video URL (no file upload), so host
your videos folder somewhere public and set MEDIA_BASE_URL."""
from datetime import timedelta

from ._http import env, check, poll, public_url, text_with_tags, requests

LEAD_TIME = timedelta(0)
G = "https://graph.threads.net/v1.0"


def post(item):
    uid, token = env("THREADS_USER_ID"), env("THREADS_ACCESS_TOKEN")
    c = check(requests.post(f"{G}/{uid}/threads", data={
        "media_type": "VIDEO", "video_url": public_url(item),
        "text": text_with_tags(item, 500), "access_token": token}, timeout=60)).json()["id"]
    poll(lambda: check(requests.get(f"{G}/{c}", params={
            "fields": "status,error_message", "access_token": token}, timeout=30)).json(),
         lambda r: r.get("status") == "FINISHED",
         lambda r: r.get("status") in ("ERROR", "EXPIRED"))
    tid = check(requests.post(f"{G}/{uid}/threads_publish", data={
        "creation_id": c, "access_token": token}, timeout=60)).json()["id"]
    link = requests.get(f"{G}/{tid}", params={"fields": "permalink",
                                               "access_token": token}, timeout=30).json()
    return link.get("permalink", f"threads post {tid}")
