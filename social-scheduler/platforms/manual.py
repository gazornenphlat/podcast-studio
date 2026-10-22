"""Sites with no public upload API. Instead of posting, the scheduler adds the
item to manual_uploads.md at post time so you can upload it by hand, then run
`python scheduler.py --done <id>:<platform>`."""
from datetime import timedelta

UPLOAD_PAGES = {
    "rumble": "https://rumble.com/upload.php",
    "bitchute": "https://www.bitchute.com/",   # Upload from your channel menu
    "reddit": "https://www.reddit.com/submit",
    "snapchat": "https://my.snapchat.com/",
    "truthsocial": "https://truthsocial.com/",
}


class Manual:
    MANUAL = True
    LEAD_TIME = timedelta(0)

    def __init__(self, name):
        self.name = name
        self.url = UPLOAD_PAGES.get(name, "")
