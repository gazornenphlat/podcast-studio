# Content Scheduler

A small local app that reminds you (or auto-posts) when each series is due, tracks a content queue per series, gives you ready-to-copy titles and descriptions per site, and emails articles on a schedule.

## Setup

1. Install Python 3.10+ then, in this folder:
   ```
   pip install -r requirements.txt
   ```
2. Copy `secrets.example.yaml` to `secrets.yaml` and fill in only what you use (email app password, API keys).
3. Edit `config.yaml` – sites, series, templates, recipient lists, reminder channels.
4. Start it in the system tray:
   - Windows: double-click **Content Scheduler.pyw** (no command window; errors go to `tray.log`)
   - macOS / Linux: `python3 tray.py`

   Click the tray icon (or choose **Open Content Scheduler**) to open the GUI in your browser.
   A red dot on the icon means reminders are waiting, and new reminders pop up as desktop notifications.
   The menu also has *Run today's check*, *Send test reminder*, *Back up now*, *Open app folder* and *Quit*.
   Running `tray.py` again while it's already running just opens the GUI.

   (`python app.py` still works if you want it without a tray icon, e.g. on a server.)

Config changes are picked up within a minute; no restart needed.

## Day-to-day

- **Series**: **+ New series** / **Edit** next to the series dropdown (or click an empty day on the calendar to start a series on that day). Set the name, day of month, sites, color, description, hashtags and title template. These are saved to `series.yaml`, which replaces the `series:` list in `config.yaml` once it exists. Renaming a series keeps its queue and past posts.

- **Queue**: add upcoming titles to a series. On posting day the reminder names the next one. Click **Mark next as posted** after you publish – it moves to Past Posts, becomes "last uploaded" and bumps the episode number.
- **Post text by site**: each site tab shows the rendered title and description (with that site's hashtags) and Copy buttons. A ⚠ means it's over that site's `max_length`.
- **Content needed by**: worked out from the queue automatically (the first posting date with nothing queued). Set a date yourself to override it; clear the field to go back to automatic.
- **Reminders**: Done / Snooze buttons in the GUI. To get Snooze/Done buttons on your phone (ntfy) and in reminder emails, set `app.host: 0.0.0.0` and `app.public_url` to this computer's address, e.g. `http://192.168.1.50:5050`. (Only do that on a home network you trust – the app has no login.)
- **Articles**: add/edit/delete in the GUI. **Email…** schedules a send; **Preview the email** shows the HTML version.

## Templates

In `config.yaml → templates`, and overridable per series or per site (`site_overrides`):

| Variable | Meaning |
|---|---|
| `{series}` | Series name |
| `{number}` | Episode number (set `start_number`; editable in the GUI) |
| `{title}` | Next queued title |
| `{description}` | Series (or site override) description |
| `{hashtags}` | Series (or site override) hashtags |
| `{site}` `{date}` | Site label, today's date |

## Reliability

- **Missed-reminder catch-up**: if the computer was off, the app replays up to `catchup_days` missed days when it starts (marked "[Missed Oct 05]").
- **Backups**: `data.json` is copied to `backups/` once a day; the newest `backup.keep` copies are kept. "Back up now" in the header forces one. To restore, stop the app and copy a backup over `data.json`.
- **Secrets**: `secrets.yaml` is merged on top of `config.yaml`, so you can share/back up config without passwords.

## Run in the background (starts automatically)

- **Windows**: `powershell -ExecutionPolicy Bypass -File service\install_windows.ps1`
- **macOS**: `bash service/install_mac.sh`
- **Linux**: `bash service/install_linux.sh` (or `--headless` for a no-tray systemd service)

These start the tray version when you log in. Each script prints how to uninstall.
On GNOME, tray icons need the "AppIndicator and KStatusNotifierItem Support" extension.

## Auto-posting

| Site | Auto-post? | Needs |
|---|---|---|
| Website (WordPress) | Yes | Application password in secrets |
| X / Twitter | Yes | Paid API tier keys |
| YouTube | Yes, with a video file | Google OAuth + `next_post.file` |
| Instagram | Yes, with an image | Business/Creator account + public `media_url` |
| TikTok, Rumble, Substack | No | You get a reminder with the upload link |
