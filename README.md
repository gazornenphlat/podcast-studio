# Podcast Studio

The podcast pipeline and the Content Scheduler, joined up: when a video episode
finishes, it is queued in the scheduler automatically and given the next open
posting day for its series.

```
podcast_studio/
  podcast_pipeline/    makes the episodes (unchanged usage)
  content_scheduler/   schedules / reminds / auto-posts (unchanged usage)
    inbox/             finished episodes land here (created automatically)
```

Keep the two folders side by side like this. The pipeline finds the inbox at
`../../content_scheduler/inbox`, relative to each process folder.

## Studio (web interface)

Start the Content Scheduler as usual, then open **http://127.0.0.1:5050/studio**.
- **Make:** pick a series, write or paste its stories (autosaved to its script file), choose
  TikTok, number of images and voice, then Start. Image prompts appear with a Copy button and
  a drop zone. Drop each image in, press play, and choose Continue or Stop here after each story.
- **Queue:** shows each series' next posting days and its queue.
- **Voices:** VoiceStudio batch queue. Give it a text file (one line = one WAV), an output
  folder and one or more saved VoiceStudio voices, then Start queue. Each run has a progress
  bar. "Stop after this line" pauses the queue; Start picks up where it left off. Lines a
  voice has already made into a folder are skipped. VoiceStudio must be running; its address
  is `voicestudio.url` in `content_scheduler/config.yaml`.

Each episode also gets `<episode>_seo.json` (meta description, focus keyphrase, keyphrases),
written by the local LLM. The meta description is added to post descriptions through
`{meta_description}` in the description template. Turn it off per process with
`"seo": {"enabled": false}` in its config.json.

Check everything with one command: `python podcast_studio/check_all.py`.

Runs are the normal process scripts, so everything works exactly as from the terminal:
resume, scheduling and the Word file. The page has no login. Keep `app.host` at 127.0.0.1
unless you trust everyone on your network, because the page can start runs.

## How it works

1. Run a video process as usual, e.g. `python podcast_pipeline/cocku/cocku.py --script script.txt`.
2. When each episode is done, the pipeline drops a note into `content_scheduler/inbox/`
   with the title and the full paths of the .mp4 (plus the TikTok, .mp3 and script if made).
3. The scheduler adds the episode to the end of that series' queue with the video attached.
   That gives it the next open posting day. Then it sends you a "📅 Scheduled" notification.
   If the scheduler is running, this happens right away and the pipeline prints the date.
   If not, it happens as soon as you start the scheduler.
4. In the GUI, each queued episode shows its posting date, and 🎬 means a video file is attached.
5. On the posting day:
   - YouTube `auto_post: true` → the video is uploaded automatically (as `privacy_status`, default private).
   - `auto_post: false` (the default) → you get the usual reminder, now with the exact file path to upload.

## Which video goes where

Each site in `content_scheduler/config.yaml` has `format: wide` or `format: vertical`.

- **16:9 episode video:** YouTube, Instagram, Facebook, X / Twitter, Rumble, Odysee, Spotify, Substack
- **9:16 TikTok version:** TikTok, YouTube Shorts, Instagram Reels, Facebook Reels
- **Alt-ending videos** are never scheduled.

Scheduled processes always make the 9:16 version, as if `--tiktok` was given.
All four series post to all twelve sites. Untick any in the series' **Edit** dialog.

| Process | Scheduler series |
|---|---|
| cocku | COCKu-YT |
| confuscius | Confuscius-YT |
| witn | WITN-YT |
| aesop | Aesop's Fables-YT |

Change these in each process's `config.json → scheduler`. Set `"enabled": false`
there to stop a process from scheduling. If you rename a series in the scheduler,
update `scheduler.series` too. Notes the scheduler can't match go to
`inbox/failed/` and are listed in the scheduler log. Audio-only episodes are not
scheduled.

Removing or renaming a queued episode in the GUI keeps its video attached
correctly. Marking it posted clears the attachment.
