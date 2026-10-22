"""Odysee (LBRY network). Odysee has no web upload API; this publishes through the
LBRY SDK daemon (lbrynet) running on the same machine, which is what Odysee uses.
Needs a little LBC in the wallet for the publish bid."""
import os
import re
from datetime import timedelta

from ._http import env, check, requests

LEAD_TIME = timedelta(0)


def post(item):
    name = re.sub(r"[^a-z0-9-]+", "-", item["title"].lower()).strip("-")[:60] or item["id"]
    params = {
        "name": name, "bid": os.getenv("ODYSEE_BID", "0.001"),
        "file_path": os.path.abspath(item["video_path"]),
        "title": item["title"], "description": item["caption"], "tags": item["tags"],
        "channel_name": env("ODYSEE_CHANNEL"),  # e.g. @mychannel
        "blocking": True,
    }
    r = check(requests.post(os.getenv("LBRYNET_URL", "http://localhost:5279"),
                            json={"method": "publish", "params": params}, timeout=3600)).json()
    if "error" in r:
        raise RuntimeError(r["error"])
    out = r["result"]["outputs"][0]
    return out.get("permanent_url", "").replace("lbry://", "https://odysee.com/")
