"""YouTube Shorts: same upload as YouTube. Video must be vertical and <= 3 min;
#Shorts is added to the title to help classification."""
from . import youtube

LEAD_TIME = youtube.LEAD_TIME
login = youtube.login


def post(item):
    item = dict(item)
    if "#shorts" not in item["title"].lower():
        item["title"] = (item["title"][:92] + " #Shorts")
    return youtube.post(item).replace("youtu.be/", "youtube.com/shorts/")
