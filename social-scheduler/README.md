# Social video scheduler

Put videos in `videos/`, add a row to `queue.csv`, and the scheduler posts each
one to its platforms when it's due. Sites with no upload API go on a
manual to-do list instead.

## Supported sites
Use these names in the `platforms` column (`python scheduler.py --platforms` lists them).

| Name | How it posts | What you need |
|---|---|---|
| `youtube` | Uploaded up to 24h early, YouTube releases at post time | Google Cloud OAuth client (Desktop app), YouTube Data API v3 enabled |
| `youtube_shorts` (`shorts`) | Same as YouTube, adds #Shorts | Vertical video, 3 min max |
| `x` (`twitter`) | Posts at post time | Paid X API tier with media upload |
| `tiktok` | Posts at post time | Approved app, Content Posting API; private until TikTok audits the app |
| `facebook` | Uploaded up to 24h early, Facebook releases at post time | Page ID + Page access token (Meta developer app) |
| `instagram` (`reels`) | Posts as a Reel at post time | Business/Creator account linked to a Facebook Page, Meta app |
| `threads` | Posts at post time | Threads API token **and** `MEDIA_BASE_URL`: Threads only fetches video from a public URL |
| `vimeo` | Posts at post time | Token with upload/edit/private scopes; upload quota depends on plan |
| `tumblr` | Posts at post time | OAuth app keys from tumblr.com/oauth/apps |
| `dailymotion` | Posts at post time | API key from Dailymotion Studio |
| `odysee` | Publishes via the LBRY daemon | `lbrynet` running on the same machine, a little LBC for the bid |
| `linkedin` | Posts at post time | App with `w_member_social` (or organization) access |
| `pinterest` | Video Pin at post time | App with `pins:write`, a board ID |
| `bluesky` | Posts at post time | App password; 3 min / 100 MB limit |
| `mastodon` | Posts at post time | Access token from your instance |
| `telegram` | Posts to a channel | Bot token, bot added as channel admin; 50 MB limit |
| `rumble`, `bitchute`, `reddit`, `snapchat`, `truthsocial` | **Manual** | No public upload API; see below |

## Setup
1. `pip install -r requirements.txt`
2. `cp .env.example .env` and fill in only the sites you use.
3. Put a video in `videos/`, add a row to `queue.csv`, then test with
   `python scheduler.py --dry-run`.
4. Sign in to YouTube once: `python scheduler.py --login youtube`. Your browser
   opens a Google sign-in; pick the account that owns the channel. If Google says
   the app isn't verified, click **Advanced > Go to (app name)**, which is normal
   for your own app. You must first add your Google account under **OAuth consent
   screen > Test users** in Google Cloud Console.

## Queue format (`queue.csv`)
| column | example | notes |
|---|---|---|
| id | `demo-001` | unique; used to track what's posted |
| post_at | `2026-10-02T09:00:00-04:00` | must include the timezone offset |
| video_path | `videos/demo.mp4` | relative to this folder, or absolute |
| title | `My video` | used where the site has titles |
| caption | `Check this out!` | description / post text |
| tags | `tutorial;howto` | `;`-separated; become hashtags where relevant |
| platforms | `youtube;x;rumble` | `;`-separated |

Captions are trimmed to each site's limit (X 280, Bluesky 300, Threads/Mastodon 500).

## Running on a schedule
Run every 5 minutes:
- **Mac/Linux:** `crontab -e`, then add
  `*/5 * * * * cd /path/to/social-scheduler && python3 scheduler.py >> scheduler.log 2>&1`
- **Windows:** Task Scheduler, repeat every 5 minutes, `python scheduler.py`
  with "Start in" set to this folder.

The machine must be on at post time (YouTube and Facebook are uploaded up to
24h ahead). For hands-off posting, run it on a small always-on cloud server.

## Manual sites
At post time, a manual site's post is added to `manual_uploads.md` with the
file, title, caption, tags and upload link. After you upload it, run
`python scheduler.py --done demo-001:rumble`.

## Commands
- `python scheduler.py` posts anything due
- `--dry-run` shows what would post
- `--status` shows every post's state with its link or error
- `--done ID:PLATFORM` marks a manual upload done
- `--platforms` lists supported names
- `--login youtube` signs in to YouTube

Every post is recorded in `post_log.json`, so nothing is posted twice.
Failures retry on the next run, up to 3 times.

## Adding a site
Create `platforms/<name>.py` with `LEAD_TIME` (a `timedelta`) and
`post(item) -> str` (return the link), then add `<name>` to `API_PLATFORMS`
in `platforms/__init__.py`. For a manual-only site, add it to
`UPLOAD_PAGES` in `platforms/manual.py`.
