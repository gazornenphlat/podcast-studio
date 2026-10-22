"""YouTube: uploads early as private with publishAt; YouTube releases it on time."""
import os
from datetime import timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Upload up to 24h ahead; YouTube handles the actual release time.
LEAD_TIME = timedelta(hours=24)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def login():
    """Sign in now (run once): python scheduler.py --login youtube"""
    _client()
    return "YouTube sign-in saved to " + os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")


def _client():
    token_file = os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets = os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secret.json")
            if not os.path.exists(secrets):
                raise FileNotFoundError(
                    f"{secrets} not found. Download the OAuth client JSON (Desktop app) "
                    "from Google Cloud Console > APIs & Services > Credentials and save "
                    "it in this folder with that name.")
            flow = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES)
            print("Opening your browser to sign in to YouTube. If it doesn't open, "
                  "copy the link below into your browser.")
            creds = flow.run_local_server(port=8080, open_browser=True,
                                          authorization_prompt_message="{url}")
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def post(item):
    publish_at = item["post_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "snippet": {
            "title": item["title"][:100],
            "description": item["caption"],
            "tags": item["tags"],
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(item["video_path"], chunksize=-1, resumable=True)
    req = _client().videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtu.be/{resp['id']}"
