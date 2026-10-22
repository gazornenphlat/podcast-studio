"""Platform registry.

To add a site with an upload API: create platforms/<name>.py with LEAD_TIME
(a timedelta) and post(item) -> str, then add "<name>" to API_PLATFORMS.
Sites with no upload API go in manual.UPLOAD_PAGES instead.

Modules load only when used, so a missing package for one site never stops
the others from posting."""
import importlib

from .manual import Manual, UPLOAD_PAGES

API_PLATFORMS = [
    "youtube", "youtube_shorts", "x", "tiktok", "facebook", "instagram", "threads",
    "vimeo", "tumblr", "dailymotion", "odysee", "linkedin", "pinterest", "bluesky",
    "mastodon", "telegram",
]
ALIASES = {"twitter": "x", "shorts": "youtube_shorts", "reels": "instagram",
           "truth": "truthsocial"}


def get(name):
    """Return the platform handler for a queue name, or None if unknown."""
    name = ALIASES.get(name, name)
    if name in UPLOAD_PAGES:
        return Manual(name)
    if name in API_PLATFORMS:
        return importlib.import_module(f".{name}", __name__)
    return None


ALL = sorted(API_PLATFORMS + list(UPLOAD_PAGES))
