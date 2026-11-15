"""X: no API scheduling, so this runs at post time. Needs a paid API tier."""
from datetime import timedelta

import tweepy

from ._http import env

LEAD_TIME = timedelta(0)


def post(item):
    key, secret = env("X_API_KEY"), env("X_API_SECRET")
    tok, tok_secret = env("X_ACCESS_TOKEN"), env("X_ACCESS_SECRET")

    # Media upload uses the v1.1 endpoint (chunked for video).
    api = tweepy.API(tweepy.OAuth1UserHandler(key, secret, tok, tok_secret))
    media = api.media_upload(item["video_path"], media_category="tweet_video", chunked=True)

    text = item["caption"]
    hashtags = " ".join(f"#{t}" for t in item["tags"])
    if hashtags and len(text) + len(hashtags) + 1 <= 280:
        text = f"{text} {hashtags}"

    client = tweepy.Client(consumer_key=key, consumer_secret=secret,
                           access_token=tok, access_token_secret=tok_secret)
    resp = client.create_tweet(text=text[:280], media_ids=[media.media_id])
    return f"https://x.com/i/status/{resp.data['id']}"
