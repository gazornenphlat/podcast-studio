"""LinkedIn video post (Videos API + Posts API). Token needs w_member_social
(or w_organization_social when posting as a company page)."""
import os
import urllib.parse
from datetime import timedelta

from ._http import env, check, poll, requests

LEAD_TIME = timedelta(0)
API = "https://api.linkedin.com/rest"


def post(item):
    owner = env("LINKEDIN_AUTHOR_URN")  # urn:li:person:xxx or urn:li:organization:123
    h = {"Authorization": f"Bearer {env('LINKEDIN_ACCESS_TOKEN')}",
         "LinkedIn-Version": os.getenv("LINKEDIN_VERSION", "202509"),
         "X-Restli-Protocol-Version": "2.0.0"}
    size = os.path.getsize(item["video_path"])

    init = check(requests.post(f"{API}/videos?action=initializeUpload", headers=h, json={
        "initializeUploadRequest": {"owner": owner, "fileSizeBytes": size,
                                    "uploadCaptions": False, "uploadThumbnail": False}},
        timeout=60)).json()["value"]

    etags = []
    with open(item["video_path"], "rb") as f:
        for part in init["uploadInstructions"]:
            f.seek(part["firstByte"])
            chunk = f.read(part["lastByte"] - part["firstByte"] + 1)
            r = check(requests.put(part["uploadUrl"], data=chunk,
                                   headers={"Content-Type": "application/octet-stream"},
                                   timeout=600))
            etags.append(r.headers["ETag"])

    video = init["video"]
    check(requests.post(f"{API}/videos?action=finalizeUpload", headers=h, json={
        "finalizeUploadRequest": {"video": video, "uploadToken": init.get("uploadToken", ""),
                                  "uploadedPartIds": etags}}, timeout=60))
    enc = urllib.parse.quote(video, safe="")
    poll(lambda: check(requests.get(f"{API}/videos/{enc}", headers=h, timeout=30)).json(),
         lambda r: r.get("status") == "AVAILABLE",
         lambda r: r.get("status") == "PROCESSING_FAILED")

    r = check(requests.post(f"{API}/posts", headers=h, json={
        "author": owner, "commentary": item["caption"], "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "content": {"media": {"title": item["title"], "id": video}},
        "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
    }, timeout=60))
    return f"https://www.linkedin.com/feed/update/{r.headers.get('x-restli-id', '')}"
