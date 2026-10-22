"""Telegram channel via a bot (make it an admin of the channel).
Bot API upload limit is 50 MB."""
from datetime import timedelta

from ._http import env, check, text_with_tags, requests

LEAD_TIME = timedelta(0)


def post(item):
    chat = env("TELEGRAM_CHAT_ID")  # @channelname or numeric id
    with open(item["video_path"], "rb") as f:
        r = check(requests.post(
            f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendVideo",
            data={"chat_id": chat, "caption": text_with_tags(item, 1024),
                  "supports_streaming": "true"},
            files={"video": f}, timeout=600)).json()["result"]
    return f"https://t.me/{chat.lstrip('@')}/{r['message_id']}" if chat.startswith("@") \
        else f"telegram message {r['message_id']}"
