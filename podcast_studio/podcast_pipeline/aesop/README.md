# Aesop

`python aesop/aesop.py --script script.txt [--tiktok] [--images 1-3] [--music-volume 0.3]` (needs an interactive terminal)

1. **Prepare:** for each story a title and up to **three** Aesop's-Fables-storybook
   image prompts are generated - one per part of the story (split at sentence
   boundaries, balanced by length). Short stories get fewer (never more than one per
   sentence). Prompts for the later scenes ask for the same characters and setting so the
   set matches. All prompts are printed and saved in `_image_prompt.txt`, with the exact
   `.jpg` names to use.
2. **Pause:** create the images and save them in `aesop/output/` as
   `<episode>_1.jpg`, `_2.jpg`, `_3.jpg` (a single-image story is just `<episode>.jpg`).
   Enter continues, `q` quits, and it re-prompts while any are missing. If some are
   missing but there are exactly as many other `.jpg` files with that episode's number,
   they are renamed in filename order. One pause covers every story in the file.
3. **Build**, all crossfaded: intro -> middle video (once, normal speed, no script) ->
   your images while the script is read -> outro.
   - Image 1 is on screen from the start: the first line, the pause, then the first part.
   - Image 2 (and 3) **fade in** over the previous image as the narration reaches that
     part of the story; the fade is centered on the moment that part begins.

Output (`aesop/output/`): `AESOP-001_Title.mp4`, `.mp3`, `_story.mp4` (images +
narration segment), `_image_prompt.txt`, optional `_tiktok.mp4`.

Config (`aesop/config.json`):
- `process.image_style` / `image_tone` - prompt wording.
- `video.aesop.max_images` (3; or `--images N` per run), `image_fade_seconds` (1.0),
  `pause_after_first_line_seconds` (2), `edge_pad_seconds` (1),
  `image_fit` (`blur_pad` | `pad` | `crop`).

## Music bed (optional)
Drop `middle.mp3` into `assets/` (next to `intro/middle/outro`; `.wav/.m4a/.aac/.ogg/.flac`
also work). It plays **under the middle video and the story segment only** - not the
intro or outro - fading in and out, looped if it is shorter than that stretch and cut if
longer. The middle video's own audio and the narration are untouched. The companion
`.mp3` gets the music under the narration too.
- Volume: `video.music.volume` in `config.json` (default `0.25`; `1.0` = the file's own
  level), or per run with `--music-volume 0.4`.
- Fade: `video.music.fade_seconds` (default `1.0`).
- No `middle.mp3` = no music, nothing else changes.
