"""Content Scheduler – local web GUI + background reminder/auto-post loop.
Run:  pip install -r requirements.txt && python app.py   then open http://127.0.0.1:5050
"""
import calendar, glob, html, json, os, shutil, smtplib, threading, time, uuid, datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import yaml, requests
from flask import Flask, jsonify, request, render_template

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
CFG = {}
LOCK = threading.RLock()          # guards every load-modify-save of data.json


def p(*parts): return os.path.join(BASE, *parts)
def new_id(): return uuid.uuid4().hex[:10]

def api_token():
    return os.environ.get("CONTENT_SCHEDULER_API_TOKEN") or CFG.get("app", {}).get("api_token")


# ================= config / secrets =================
def deep_merge(a, b):
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): deep_merge(a[k], v)
        else: a[k] = v
    return a

class _StrictYAML(yaml.SafeLoader):
    """PyYAML keeps the LAST of two equal keys without a word. This refuses instead."""


def _mapping_no_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r} (YAML keeps only the last one silently)", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictYAML.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_no_duplicates)


def load_yaml_file(path):
    """Read a YAML file; a duplicate key is an error that names the file and key."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.load(f, Loader=_StrictYAML) or {}
    except yaml.YAMLError as ex:
        raise ValueError(f"{path}: {ex}") from None


def load_config():
    global CFG
    c = load_yaml_file(p("config.yaml"))
    sp = p(c.get("app", {}).get("secrets_file", "secrets.yaml"))
    if os.path.exists(sp):
        deep_merge(c, load_yaml_file(sp))
    sf = p(c.get("app", {}).get("series_file", "series.yaml"))
    if os.path.exists(sf):                 # series managed in the GUI live here and replace config.yaml's list
        c["series"] = load_yaml_file(sf).get("series", []) or []
    CFG = c
    import voicestudio_batch                # here, not at the top: it is registered after app exists
    voicestudio_batch.configure(c.get("voicestudio"))
    return c

class _LiteralDumper(yaml.SafeDumper): pass
_LiteralDumper.add_representer(str, lambda d, s: d.represent_scalar(
    "tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))

def save_series_file(series):
    sf = p(CFG.get("app", {}).get("series_file", "series.yaml"))
    for s in series:                       # block style needs no trailing spaces on lines
        for k in ("description",):
            if isinstance(s.get(k), str): s[k] = "\n".join(l.rstrip() for l in s[k].strip().splitlines()) + "\n"
    text = ("# Series – managed by the Content Scheduler GUI (New / Edit series).\n"
            "# You can also edit this file by hand; it replaces the series list in config.yaml.\n\n"
            + yaml.dump({"series": series}, Dumper=_LiteralDumper, sort_keys=False, allow_unicode=True, width=1000))
    tmp = sf + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(text)
    os.replace(tmp, sf)


# ================= data / backups =================
def data_path(): return p(CFG["app"].get("data_file", "data.json"))

def load_data():
    d = {}
    if os.path.exists(data_path()):
        with open(data_path(), encoding="utf-8") as f: d = json.load(f)
    for k, v in {"series": {}, "emails": [], "log": [], "fired": {}, "reminders": []}.items():
        d.setdefault(k, v)
    if d.get("articles") is None:      # seed once from config, then the GUI owns them
        d["articles"] = [{"id": new_id(), **{k: a.get(k, "") for k in ("title", "url", "summary", "image_url")}}
                         for a in CFG.get("articles", [])]
    return d

def save_data(d):
    tmp = data_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, indent=2)
    os.replace(tmp, data_path())       # atomic: never leaves a half-written file

def backup(force=False):
    b = CFG.get("backup", {})
    if not b.get("enabled", True) or not os.path.exists(data_path()): return
    folder = p(b.get("folder", "backups")); os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, f"data-{now():%Y-%m-%d}.json")
    if force or not os.path.exists(dst): shutil.copy2(data_path(), dst)
    for old in sorted(glob.glob(os.path.join(folder, "data-*.json")))[:-int(b.get("keep", 30))]:
        os.remove(old)

def now(): return dt.datetime.now(ZoneInfo(CFG["app"]["timezone"]))

def log(d, msg):
    d["log"].insert(0, f"{now():%Y-%m-%d %H:%M} {msg}")
    d["log"] = d["log"][:300]

def sstate(d, name): return d["series"].setdefault(name, {})
def series_cfg(name): return next((s for s in CFG.get("series", []) if s["name"] == name), None)


# ================= schedule math =================
def post_day(ser, y, m):
    return min(int(ser["day_of_month"]), calendar.monthrange(y, m)[1])   # 31st → last day in short months

def posting_dates(ser, start, n):
    out, y, m = [], start.year, start.month
    while len(out) < n:
        day = dt.date(y, m, post_day(ser, y, m))
        if day >= start: out.append(day)
        m += 1
        if m > 12: m, y = 1, y + 1
    return out

def content_needed_by(ser, st, today):
    """Manual date wins; otherwise the posting date right after the queue runs out."""
    if st.get("need_content_by"): return st["need_content_by"], "manual"
    q = len(st.get("queue", []))
    return posting_dates(ser, today, q + 1)[-1].isoformat(), "queue"


# ================= templates =================
class SafeDict(dict):
    def __missing__(self, k): return "{" + k + "}"

def render(tpl, ctx): return (tpl or "").format_map(SafeDict(ctx))

def build_post(ser, st, site, title=None):
    if title is None: title = (st.get("queue") or [""])[0]
    s = CFG["sites"].get(site, {})
    ov = (ser.get("site_overrides") or {}).get(site, {}) or {}
    t = CFG.get("templates", {})
    ctx = {"series": ser["name"], "number": st.get("next_number", ser.get("start_number", 1)),
           "title": title, "date": now().strftime("%Y-%m-%d"), "site": s.get("label", site),
           "hashtags": ov.get("hashtags", ser.get("hashtags", "")) or ""}
    seo = (st.get("media", {}).get(title, {}) or {}).get("seo") or {}
    ctx["meta_description"] = seo.get("meta_description", "")
    ctx["focus_keyphrase"] = seo.get("focus_keyphrase", "")
    ctx["keyphrases"] = ", ".join(seo.get("keyphrases", []))
    ctx["description"] = render(ov.get("description", ser.get("description", "")), ctx).strip()
    full_title = render(ov.get("title_template", ser.get("title_template", t.get("title", "{title}"))), ctx).strip()
    ctx["full_title"] = full_title
    desc = render(ov.get("description_template", ser.get("description_template",
                  t.get("description", "{description}\n\n{meta_description}\n\n{hashtags}"))), ctx)
    desc = "\n\n".join(x.strip() for x in desc.strip().split("\n\n") if x.strip())   # drop empty blocks
    mx = s.get("max_length")
    return {"site": site, "label": s.get("label", site), "title": full_title, "description": desc,
            "length": len(desc), "max_length": mx, "over": bool(mx and len(desc) > mx),
            "upload_url": s.get("upload_url", ""), "auto_post": bool(s.get("auto_post"))}


# ================= notification channels =================
def send_email(to, subject, text, html_body=None):
    e = CFG["email"]
    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text, "plain", "utf-8")); msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, f'{e["from_name"]} <{e["from_address"]}>', ", ".join(to)
    with smtplib.SMTP(e["smtp_host"], e["smtp_port"], timeout=30) as s:
        if e.get("use_tls"): s.starttls()
        if e.get("password"): s.login(e["username"], e["password"])
        s.sendmail(e["from_address"], to, msg.as_string())

def google_service(name, ver):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    g = CFG["google"]
    scopes = {"tasks": "https://www.googleapis.com/auth/tasks",
              "calendar": "https://www.googleapis.com/auth/calendar.events",
              "youtube": "https://www.googleapis.com/auth/youtube.upload"}.get(name)
    scopes = [scopes] if scopes else ["https://www.googleapis.com/auth/tasks",
                                     "https://www.googleapis.com/auth/calendar.events",
                                     "https://www.googleapis.com/auth/youtube.upload"]
    tok = p(g["token_file"])
    creds = Credentials.from_authorized_user_file(tok, scopes) if os.path.exists(tok) else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        else: creds = InstalledAppFlow.from_client_secrets_file(p(g["credentials_file"]), scopes).run_local_server(port=0)
        with open(tok, "w") as f: f.write(creds.to_json())
    return build(name, ver, credentials=creds)

def fmt_minutes(m):
    m = int(m)
    return f"{m // 1440}d" if m % 1440 == 0 else f"{m // 60}h" if m % 60 == 0 else f"{m}m"

def send_channels(title, body, link=None, rid=None, first=True):
    """Send through every enabled channel. Google Tasks/Calendar only on the first send (not snooze repeats)."""
    r = CFG.get("reminders", {})
    pub = (CFG["app"].get("public_url") or "").rstrip("/")
    full = body + (f"\n\nUpload here: {link}" if link else "")
    errors = []
    def attempt(name, fn):
        try: fn()
        except Exception as ex: errors.append(f"{name}: {ex}")

    if r.get("ntfy", {}).get("enabled"):
        n = r["ntfy"]; acts = []
        if link: acts.append({"action": "view", "label": "Open upload page", "url": link})
        if rid and pub:
            m = CFG.get("snooze", {}).get("ntfy_minutes", 120)
            acts.append({"action": "http", "label": f"Snooze {fmt_minutes(m)}", "method": "POST", "clear": True,
                         "url": f"{pub}/api/reminder/{rid}/snooze?minutes={m}"})
            acts.append({"action": "http", "label": "Done", "method": "POST", "clear": True,
                         "url": f"{pub}/api/reminder/{rid}/done"})
        payload = {"topic": n["topic"], "title": title, "message": full, "actions": acts}
        if link: payload["click"] = link
        hdr = {"Authorization": f"Bearer {n['token']}"} if n.get("token") else {}
        attempt("ntfy", lambda: requests.post(n["server"].rstrip("/"), json=payload, headers=hdr, timeout=15).raise_for_status())

    if r.get("pushbullet", {}).get("enabled"):
        pb = {"type": "link", "title": title, "body": body, "url": link} if link else {"type": "note", "title": title, "body": body}
        attempt("pushbullet", lambda: requests.post("https://api.pushbullet.com/v2/pushes", json=pb,
                headers={"Access-Token": r["pushbullet"]["access_token"]}, timeout=15).raise_for_status())

    if r.get("email", {}).get("enabled"):
        extra = ""
        if rid and pub:
            m = CFG.get("snooze", {}).get("ntfy_minutes", 120)
            extra = f"\n\nSnooze {fmt_minutes(m)}: {pub}/api/reminder/{rid}/snooze?minutes={m}\nMark done: {pub}/api/reminder/{rid}/done"
        attempt("email", lambda: send_email(r["email"]["recipients"], title, full + extra))

    if first and r.get("google_tasks", {}).get("enabled"):
        attempt("google_tasks", lambda: google_service("tasks", "v1").tasks().insert(
            tasklist=r["google_tasks"]["tasklist_id"],
            body={"title": title, "notes": full, "due": now().strftime("%Y-%m-%dT00:00:00.000Z")}).execute())

    if first and r.get("google_calendar", {}).get("enabled"):
        c = r["google_calendar"]; start = now().replace(hour=c.get("event_hour", 9), minute=0, second=0, microsecond=0)
        attempt("google_calendar", lambda: google_service("calendar", "v3").events().insert(
            calendarId=c["calendar_id"], body={"summary": title, "description": full,
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + dt.timedelta(minutes=30)).isoformat()}}).execute())
    return errors

def create_reminder(d, kind, title, body, link=None, series=None, site=None):
    rem = {"id": new_id(), "kind": kind, "series": series, "site": site, "title": title, "body": body,
           "link": link, "created": now().isoformat(timespec="minutes"), "status": "open", "snoozed_until": None}
    d["reminders"].append(rem)
    errs = send_channels(title, body, link, rem["id"])
    log(d, f"Reminder: {title}" + (f" (errors: {'; '.join(errs)})" if errs else ""))
    return rem

def resend_snoozed(d):
    changed = False
    for rem in d["reminders"]:
        if rem["status"] == "open" and rem.get("snoozed_until") and dt.datetime.fromisoformat(rem["snoozed_until"]) <= now():
            rem["snoozed_until"] = None
            errs = send_channels("⏰ " + rem["title"], rem["body"], rem.get("link"), rem["id"], first=False)
            log(d, f"Snoozed reminder re-sent: {rem['title']}" + (f" (errors: {'; '.join(errs)})" if errs else ""))
            changed = True
    # keep the list tidy: drop closed reminders older than 60 days
    cutoff = (now() - dt.timedelta(days=60)).isoformat()
    before = len(d["reminders"])
    d["reminders"] = [x for x in d["reminders"] if x["status"] == "open" or x["created"] > cutoff]
    return changed or len(d["reminders"]) != before


# ================= auto-posters =================
def media_file(site_key, m):
    """The file to post on a site: the 9:16 TikTok version for vertical sites, the
    16:9 episode video for everything else. Alt-ending videos are never used."""
    if not m: return None
    vertical = CFG["sites"].get(site_key, {}).get("format") == "vertical"
    return m.get("tiktok") if vertical else m.get("video")

# Sites whose API only sends text or images. A video episode always gets a reminder for these.
VIDEO_REMINDER_ONLY = {"twitter", "instagram"}


def auto_post(site_key, post, st, item=None):
    """Return True if posted. Video/image comes from the queued episode's media (sent by the
    podcast pipeline), falling back to the older st['next_post'] = {file, media_url}."""
    s = CFG["sites"][site_key]
    if not s.get("auto_post"): return False
    extra = dict(st.get("next_post") or {})
    m = (st.get("media") or {}).get(item) if item else None
    if m:
        f = media_file(site_key, m)
        if f and os.path.exists(f): extra["file"] = f
        else: extra.pop("file", None)
    title, text, api = post["title"], post["description"], s.get("api")
    if api in VIDEO_REMINDER_ONLY and m:
        return False                      # X and Instagram APIs can't carry the episode video: reminder only
    if api == "twitter":
        import tweepy
        tweepy.Client(consumer_key=s["api_key"], consumer_secret=s["api_secret"],
                      access_token=s["access_token"], access_token_secret=s["access_secret"]).create_tweet(text=text[:280])
        return True
    if api == "wordpress":
        requests.post(f'{s["base_url"].rstrip("/")}/wp-json/wp/v2/posts', auth=(s["username"], s["app_password"]),
                      json={"title": title, "content": text.replace("\n", "<br>"), "status": s.get("post_status", "draft")},
                      timeout=30).raise_for_status()
        return True
    if api == "youtube" and extra.get("file"):
        from googleapiclient.http import MediaFileUpload
        google_service("youtube", "v3").videos().insert(part="snippet,status",
            body={"snippet": {"title": title[:100], "description": text}, "status": {"privacyStatus": s.get("privacy_status", "private")}},
            media_body=MediaFileUpload(extra["file"], resumable=True)).execute()
        return True
    if api == "instagram" and extra.get("media_url"):
        base = f'https://graph.facebook.com/v21.0/{s["ig_user_id"]}'
        cid = requests.post(f"{base}/media", data={"image_url": extra["media_url"], "caption": text,
                            "access_token": s["access_token"]}, timeout=30).json()["id"]
        requests.post(f"{base}/media_publish", data={"creation_id": cid, "access_token": s["access_token"]}, timeout=30).raise_for_status()
        return True
    return False


# ================= queue / past posts =================
def add_past(st, titles):
    past = st.setdefault("past_posts", []); known = {x.lower() for x in past}; added = []
    for t in titles:
        t = t.strip()
        if t and t.lower() not in known: known.add(t.lower()); past.append(t); added.append(t)
    past.sort(key=str.lower)
    return added

def mark_posted(d, name, title=None):
    ser, st = series_cfg(name), sstate(d, name)
    if ser is None:
        log(d, f"Mark posted skipped: unknown series {name!r}")
        return None
    q = st.setdefault("queue", [])
    if title is None:
        if not q: return None
        title = q.pop(0)
    elif title in q: q.remove(title)
    add_past(st, [title])
    if title not in q: (st.get("media") or {}).pop(title, None)
    st["last_content"], st["last_updated"] = title, now().strftime("%Y-%m-%d")
    st["next_number"] = int(st.get("next_number", ser.get("start_number", 1))) + 1
    for rem in d["reminders"]:                      # close today's "post" reminders for this series
        if rem["status"] == "open" and rem["kind"] == "post" and rem["series"] == name: rem["status"] = "done"
    log(d, f"Marked posted: {name} – {title}")
    return title


# ================= podcast pipeline inbox =================
def queue_dates(ser, st, d=None):
    """Posting date for each queued title, in order."""
    q = st.get("queue") or []
    if not q: return []
    today = now().date()
    start = today + dt.timedelta(days=1) if (d or load_data())["fired"].get("daily") == today.isoformat() else today
    return [x.isoformat() for x in posting_dates(ser, start, len(q))]

def inbox_dir(): return p(CFG["app"].get("inbox_folder", "inbox"))

def ingest_inbox():
    """Queue every finished episode the podcast pipeline dropped in inbox/.
    Each one goes to the end of its series' queue, so it gets the next open
    posting day, with its video file attached for auto-posting/reminders."""
    folder = inbox_dir(); os.makedirs(folder, exist_ok=True)
    notes = sorted(glob.glob(os.path.join(folder, "*.json")))
    if not notes: return []
    scheduled = []
    with LOCK:
        d = load_data(); names = {s["name"]: s for s in CFG.get("series", [])}
        for path in notes:
            dest = "done"
            try:
                with open(path, encoding="utf-8") as f: n = json.load(f)
                ser = names.get(n.get("series")); title = (n.get("title") or "").strip()
                if not ser: raise ValueError(f"no series named '{n.get('series')}'")
                if not title: raise ValueError("episode has no title")
                st = sstate(d, ser["name"]); q = st.setdefault("queue", []); med = st.setdefault("media", {})
                base, k = title, 2
                while title in med or title in q or title.lower() in {x.lower() for x in st.get("past_posts", [])}:
                    title = f"{base} ({k})"; k += 1
                q.append(title)
                med[title] = {k2: n.get(k2) for k2 in ("video", "tiktok", "mp3", "script") if n.get(k2)}
                if isinstance(n.get("seo"), dict): med[title]["seo"] = n["seo"]   # meta description, keyphrases
                med[title]["added"] = now().isoformat(timespec="minutes")
                when = queue_dates(ser, st, d)[-1]
                med[title]["scheduled_for"] = when
                sites = ", ".join(CFG["sites"].get(x, {}).get("label", x) for x in ser["sites"])
                log(d, f"New episode queued: {ser['name']} – {title} → {when} ({sites})")
                errs = send_channels(f"📅 Scheduled: {ser['name']} – {title}",
                                     f"Goes up on {when} ({sites}). Position {len(q)} in the queue.\n"
                                     f"File: {med[title].get('video') or '(none)'}")
                if errs: log(d, f"Schedule notice errors: {'; '.join(errs)}")
                scheduled.append({"series": ser["name"], "title": title, "date": when})
            except Exception as ex:
                dest = "failed"; log(d, f"Inbox: couldn't queue {os.path.basename(path)}: {ex}")
            os.makedirs(os.path.join(folder, dest), exist_ok=True)
            os.replace(path, os.path.join(folder, dest, os.path.basename(path)))
        save_data(d)
    return scheduled


# ================= daily check + catch-up =================
def daily_check(day=None, missed=False):
    with LOCK:
        d = load_data(); day = day or now().date()
        warn = int(CFG["app"].get("upload_warning_days", 3))
        pre = f"[Missed {day:%b %d}] " if missed else ""
        for ser in CFG.get("series", []):
            st = sstate(d, ser["name"])
            if day.day == post_day(ser, day.year, day.month):
                nxt = (st.get("queue") or [None])[0]
                auto_ok, manual_needed = False, False
                for site in ser["sites"]:
                    if site not in CFG["sites"]:
                        log(d, f"Unknown site '{site}' in series {ser['name']}"); continue
                    post = build_post(ser, st, site)
                    try:
                        if auto_post(site, post, st, nxt):
                            auto_ok = True; log(d, f"{pre}Auto-posted {ser['name']} → {post['label']}"); continue
                    except Exception as ex:
                        log(d, f"{pre}Auto-post FAILED {ser['name']} → {post['label']}: {ex}")
                    manual_needed = True
                    m = (st.get("media") or {}).get(nxt) or {}
                    f = media_file(site, m)
                    if m and not f: f = "(no 9:16 version was made for this episode)"
                    create_reminder(d, "post", f"{pre}Post today: {ser['name']} → {post['label']}",
                                    f"Next up: {nxt or '(queue is empty!)'}\nTitle: {post['title']}\n"
                                    + (f"Video file: {f}\n" if f else "") +
                                    f"Last posted: {st.get('last_content') or 'unknown'}",
                                    post["upload_url"], ser["name"], site)
                if auto_ok and not manual_needed and nxt: mark_posted(d, ser["name"])
            empty_check(d, ser, st, day, missed)
            need, _ = content_needed_by(ser, st, day)
            days = (dt.date.fromisoformat(need) - day).days
            if 0 <= days <= warn:
                create_reminder(d, "content", f"{pre}{ser['name']}: new content needed in {days} day(s)",
                                f"Content runs out {need}. Queued: {len(st.get('queue', []))}. "
                                f"Last uploaded: {st.get('last_content') or 'unknown'}", None, ser["name"])
        save_data(d)

def empty_check(d, ser, st, day, missed):
    """Remind if nothing is queued to post in the next `empty_window_days` (default 30).
    Repeats every `empty_repeat_days` (default 7) until something is queued."""
    if missed: return
    a = CFG["app"]; window = int(a.get("empty_window_days", 30)); every = int(a.get("empty_repeat_days", 7))
    q = st.get("queue") or []
    horizon = day + dt.timedelta(days=window)
    if any(x <= horizon for x in posting_dates(ser, day, len(q))) if q else False:
        d["fired"].pop(f"empty:{ser['name']}", None); return
    key = f"empty:{ser['name']}"; last = d["fired"].get(key)
    if last and (day - dt.date.fromisoformat(last)).days < every: return
    d["fired"][key] = day.isoformat()
    nxt = posting_dates(ser, day, 1)[0]
    create_reminder(d, "content", f"{ser['name']}: nothing scheduled in the next {window} days",
                    f"Next posting day is {nxt:%b %d} and the queue has nothing for it. "
                    f"Make an episode (it queues itself) or add a title.", None, ser["name"])

def run_due_checks():
    """Run today's check once after check_time, and replay days missed while the computer was off."""
    n = now(); today = n.date()
    target = today if n.strftime("%H:%M") >= CFG["app"]["check_time"] else today - dt.timedelta(days=1)
    with LOCK:
        d = load_data(); last = d["fired"].get("daily")
        if last is None:
            days = [target] if target == today else []
            if not days: d["fired"]["daily"] = target.isoformat(); save_data(d)   # first run before check_time
        else:
            last = dt.date.fromisoformat(last)
            span = (target - last).days
            cap = int(CFG["app"].get("catchup_days", 7))
            days = [target - dt.timedelta(days=i) for i in range(min(span, cap) - 1, -1, -1)] if span > 0 else []
    for day in days:
        with LOCK:
            d = load_data(); d["fired"]["daily"] = day.isoformat(); save_data(d)
        daily_check(day, missed=(day != today))

def email_check():
    with LOCK:
        d = load_data(); changed = False
        for job in d["emails"]:
            send_at = dt.datetime.fromisoformat(job["send_at"])
            if send_at.tzinfo is None:
                send_at = send_at.replace(tzinfo=ZoneInfo(CFG["app"]["timezone"]))
            if job["status"] == "pending" and send_at <= now():
                try:
                    send_email(job["to"], job["subject"], job["body"], job.get("html"))
                    job["status"] = "sent"; log(d, f"Emailed article '{job['title']}' to {len(job['to'])} recipient(s)")
                except Exception as ex:
                    job["status"] = f"error: {ex}"; log(d, f"Email failed: {ex}")
                changed = True
        if resend_snoozed(d): changed = True
        if changed: save_data(d)

def loop():
    while True:
        try:
            load_config(); backup(); ingest_inbox(); email_check(); run_due_checks()
        except Exception as ex:
            print("loop error:", ex)
        time.sleep(60)


# ================= web: pages & state =================
# ================= Studio (run the pipeline from the browser) =================
from studio import bp as studio_bp
app.register_blueprint(studio_bp)          # /studio
from voicestudio_batch import bp as vs_batch_bp
app.register_blueprint(vs_batch_bp)      # /api/vs/* (VoiceStudio batch queue)


@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/state")
def state():
    load_config()
    with LOCK: d = load_data()
    today = now().date(); out = {}
    for ser in CFG.get("series", []):
        st = sstate(d, ser["name"]); need, src = content_needed_by(ser, st, today)
        out[ser["name"]] = {**st, "color": st.get("color") or ser.get("color") or "#64748b",
                            "default_color": ser.get("color") or "#64748b",
                            "needed_by": need, "needed_by_source": src,
                            "next_number": st.get("next_number", ser.get("start_number", 1)),
                            "next_date": posting_dates(ser, today, 1)[0].isoformat(),
                            "queue_dates": queue_dates(ser, st, d),
                            "media": st.get("media", {}),
                            "posts": [build_post(ser, st, s) for s in ser["sites"] if s in CFG["sites"]]}
    return jsonify({"series": CFG.get("series", []), "sites": CFG["sites"], "state": out,
                    "articles": d["articles"], "recipient_lists": CFG["email"].get("recipient_lists", {}),
                    "emails": sorted(d["emails"], key=lambda e: e["send_at"], reverse=True)[:30],
                    "reminders": [r for r in d["reminders"] if r["status"] == "open"],
                    "snooze_options": CFG.get("snooze", {}).get("options_minutes", [60, 180, 1440]),
                    "log": d["log"][:40]})

def body(): return request.get_json(silent=True) or {}

@app.before_request
def _check_api_token():
    if not request.path.startswith("/api/"): return
    token = api_token()
    if not token: return
    if (request.remote_addr or "") in ("127.0.0.1", "::1", "localhost"): return
    if request.headers.get("X-API-Token") == token: return
    return jsonify(error="unauthorized"), 401


# ================= web: series / queue / past =================
@app.route("/api/series", methods=["POST"])
def update_series():
    b = body()
    with LOCK:
        d = load_data(); st = sstate(d, b["name"])
        if "need_content_by" in b: st["need_content_by"] = b["need_content_by"] or None   # blank = use queue
        if b.get("last_content"):
            st["last_content"], st["last_updated"] = b["last_content"].strip(), now().strftime("%Y-%m-%d")
        added = add_past(st, b.get("titles", "").splitlines() + [b.get("last_content", "")])
        if b.get("next_number"): st["next_number"] = int(b["next_number"])
        log(d, f"Updated {b['name']}" + (f", +{len(added)} past post(s)" if added else ""))
        save_data(d)
    return jsonify(ok=True)

@app.route("/api/series-def", methods=["POST"])
def save_series_def():
    """Create or edit a series. original_name = the series being edited (blank for new)."""
    import re
    b = body(); load_config()
    name = (b.get("name") or "").strip(); orig = (b.get("original_name") or "").strip()
    try: day = int(b.get("day_of_month"))
    except (TypeError, ValueError): day = 0
    sites = [s for s in b.get("sites", []) if s in CFG["sites"]]
    color = (b.get("color") or "").strip()
    if not name: return jsonify(error="Name is required"), 400
    if not 1 <= day <= 31: return jsonify(error="Day of month must be 1–31"), 400
    if not sites: return jsonify(error="Pick at least one site"), 400
    if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color): return jsonify(error="Bad color"), 400
    series = [dict(s) for s in CFG.get("series", [])]
    if any(s["name"] == name for s in series if s["name"] != orig):
        return jsonify(error=f'A series named "{name}" already exists'), 400
    existing = next((s for s in series if s["name"] == orig), None) if orig else None
    entry = existing if existing is not None else {}
    entry.update({"name": name, "sites": sites, "day_of_month": day, "color": color or entry.get("color", "#64748b"),
                  "description": b.get("description") or "", "hashtags": (b.get("hashtags") or "").strip()})
    tt = (b.get("title_template") or "").strip()
    if tt: entry["title_template"] = tt
    else: entry.pop("title_template", None)
    entry.setdefault("start_number", 1)
    if existing is None: series.append(entry)
    with LOCK:
        save_series_file(series)
        d = load_data()
        if orig and orig != name and orig in d["series"]:      # rename: carry queue/past posts over
            d["series"][name] = d["series"].pop(orig)
            for r in d["reminders"]:
                if r.get("series") == orig: r["series"] = name
        if color: d["series"].setdefault(name, {}).pop("color", None)   # dialog color replaces picker override
        log(d, f"{'Edited' if existing is not None else 'Added'} series {name} (day {day}: {', '.join(sites)})")
        save_data(d)
    load_config()
    return jsonify(ok=True, name=name)

@app.route("/api/series-def/delete", methods=["POST"])
def delete_series_def():
    b = body(); load_config()
    series = [dict(s) for s in CFG.get("series", []) if s["name"] != b.get("name")]
    with LOCK:
        save_series_file(series)
        d = load_data()
        for r in d["reminders"]:
            if r.get("series") == b.get("name") and r["status"] == "open": r["status"] = "done"
        log(d, f"Deleted series {b.get('name')} (its queue and past posts are kept in data.json)"); save_data(d)
    load_config()
    return jsonify(ok=True)

@app.route("/api/series/color", methods=["POST"])
def set_series_color():
    import re
    b = body(); color = (b.get("color") or "").strip()
    if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color): return jsonify(error="Bad color"), 400
    with LOCK:
        d = load_data(); st = sstate(d, b["name"])
        if color: st["color"] = color
        else: st.pop("color", None)          # blank = back to config.yaml color
        log(d, f"Color for {b['name']} → {color or 'default'}"); save_data(d)
    return jsonify(ok=True)

@app.route("/api/past-post/delete", methods=["POST"])
def delete_past_post():
    b = body()
    with LOCK:
        d = load_data(); st = sstate(d, b["name"])
        st["past_posts"] = [x for x in st.get("past_posts", []) if x != b["title"]]
        log(d, f"Removed past post '{b['title']}' from {b['name']}"); save_data(d)
    return jsonify(ok=True)

@app.route("/api/queue/<action>", methods=["POST"])
def queue_action(action):
    b = body()
    with LOCK:
        d = load_data(); st = sstate(d, b["name"]); q = st.setdefault("queue", [])
        i = int(b.get("index", 0))
        if action == "add":
            new = [t.strip() for t in b.get("titles", "").splitlines() if t.strip()]
            q.extend(new); log(d, f"Queued {len(new)} item(s) for {b['name']}")
        elif action == "remove" and 0 <= i < len(q):
            t = q.pop(i)
            if t not in q: (st.get("media") or {}).pop(t, None)
        elif action == "move":
            j = i + int(b.get("dir", 0))
            if 0 <= i < len(q) and 0 <= j < len(q): q[i], q[j] = q[j], q[i]
        elif action == "edit" and 0 <= i < len(q) and b.get("title", "").strip():
            old, q[i] = q[i], b["title"].strip()
            med = st.get("media") or {}
            if old in med and old not in q: med[q[i]] = med.pop(old)
        elif action == "posted":
            if not mark_posted(d, b["name"], b.get("title")): return jsonify(error="Queue is empty"), 400
        else: return jsonify(error="bad action"), 400
        save_data(d)
    return jsonify(ok=True)


# ================= web: reminders / snooze =================
@app.route("/api/reminder/<rid>/<action>", methods=["GET", "POST"])
def reminder_action(rid, action):
    with LOCK:
        d = load_data(); rem = next((x for x in d["reminders"] if x["id"] == rid), None)
        if not rem: return jsonify(error="not found"), 404
        if action == "snooze":
            mins = int(request.args.get("minutes") or body().get("minutes") or CFG.get("snooze", {}).get("ntfy_minutes", 120))
            rem["snoozed_until"] = (now() + dt.timedelta(minutes=mins)).isoformat(timespec="minutes")
            log(d, f"Snoozed {fmt_minutes(mins)}: {rem['title']}"); msg = f"Snoozed for {fmt_minutes(mins)}."
        elif action == "done":
            rem["status"] = "done"; log(d, f"Done: {rem['title']}"); msg = "Marked done."
        else: return jsonify(error="bad action"), 400
        save_data(d)
    if request.method == "GET":   # clicked from an email link
        return f"<p style='font:18px system-ui;padding:30px'>{html.escape(msg)}</p>"
    return jsonify(ok=True, message=msg)


# ================= web: articles / email =================
@app.route("/api/articles", methods=["POST"])
def save_article():
    b = body()
    if not b.get("title", "").strip(): return jsonify(error="Title is required"), 400
    with LOCK:
        d = load_data(); fields = {k: (b.get(k) or "").strip() for k in ("title", "url", "summary", "image_url")}
        art = next((a for a in d["articles"] if a["id"] == b.get("id")), None)
        if art: art.update(fields); log(d, f"Edited article '{fields['title']}'")
        else: d["articles"].append({"id": new_id(), **fields}); log(d, f"Added article '{fields['title']}'")
        save_data(d)
    return jsonify(ok=True)

@app.route("/api/articles/<aid>/delete", methods=["POST"])
def delete_article(aid):
    with LOCK:
        d = load_data(); d["articles"] = [a for a in d["articles"] if a["id"] != aid]
        log(d, "Deleted an article"); save_data(d)
    return jsonify(ok=True)

def render_article_email(art):
    e = CFG["email"]
    ctx = {**{k: art.get(k, "") for k in ("title", "url", "summary", "image_url")}, "from_name": e["from_name"]}
    hctx = {k: html.escape(str(v)) for k, v in ctx.items()}
    hctx["image_html"] = (f'<img src="{hctx["image_url"]}" alt="" style="max-width:100%;border-radius:6px;margin:8px 0">'
                          if ctx["image_url"] else "")
    return (render(e.get("article_subject_template", "{title}"), ctx),
            render(e.get("article_body_template", "{summary}\n\n{url}"), ctx),
            render(e.get("article_html_template"), hctx) if e.get("article_html_template") else None)

@app.route("/api/email/preview/<aid>")
def email_preview(aid):
    with LOCK: d = load_data()
    art = next((a for a in d["articles"] if a["id"] == aid), None)
    if not art: return "Not found", 404
    subject, text, h = render_article_email(art)
    return h or f"<pre>{html.escape(text)}</pre>"

@app.route("/api/email", methods=["POST"])
def schedule_email():
    b = body(); e = CFG["email"]
    with LOCK:
        d = load_data()
        art = next((a for a in d["articles"] if a["id"] == b.get("id")), None)
        if not art: return jsonify(error="Article not found"), 404
        to = list(e.get("recipient_lists", {}).get(b.get("list"), [])) + \
             [x.strip() for x in b.get("extra", "").split(",") if x.strip()]
        if not to: return jsonify(error="No recipients"), 400
        subject, text, h = render_article_email(art)
        d["emails"].append({"id": new_id(), "title": art["title"], "to": to, "send_at": b["send_at"],
                            "status": "pending", "subject": subject, "body": text, "html": h})
        log(d, f"Scheduled email '{art['title']}' for {b['send_at'].replace('T', ' ')}"); save_data(d)
    return jsonify(ok=True)

@app.route("/api/email/<eid>/cancel", methods=["POST"])
def cancel_email(eid):
    with LOCK:
        d = load_data()
        for job in d["emails"]:
            if job.get("id") == eid and job["status"] == "pending":
                job["status"] = "cancelled"; log(d, f"Cancelled email '{job['title']}'")
        save_data(d)
    return jsonify(ok=True)


# ================= web: tools =================
@app.route("/api/test-reminder", methods=["POST"])
def test_reminder():
    errs = send_channels("Test reminder", "Content Scheduler is working.")
    with LOCK:
        d = load_data(); log(d, "Test reminder sent" + (f" (errors: {'; '.join(errs)})" if errs else "")); save_data(d)
    return jsonify(errors=errs)

@app.route("/api/inbox/ingest", methods=["POST"])
def inbox_ingest():
    load_config()
    return jsonify(scheduled=ingest_inbox())

@app.route("/api/run-now", methods=["POST"])
def run_now(): daily_check(); return jsonify(ok=True)

@app.route("/api/backup", methods=["POST"])
def backup_now():
    with LOCK: save_data(load_data()); backup(force=True)
    return jsonify(ok=True)


def local_url():
    host, port = CFG["app"]["host"], CFG["app"]["port"]
    return f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"

def start_background():
    """Load config, create data file, start the reminder loop thread."""
    load_config()
    with LOCK:
        if not os.path.exists(data_path()): save_data(load_data())
    threading.Thread(target=loop, daemon=True).start()

def serve_forever():
    host, port = CFG["app"]["host"], CFG["app"]["port"]
    try:
        from waitress import serve
        serve(app, host=host, port=port, _quiet=True)
    except ImportError:
        app.run(host=host, port=port)


if __name__ == "__main__":
    start_background()
    print(f"Content Scheduler running at {local_url()}  (run tray.py for the system-tray version)")
    serve_forever()
