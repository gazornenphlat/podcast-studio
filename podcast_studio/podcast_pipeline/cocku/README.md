# COCku

`python cocku/cocku.py --script script.txt [--tiktok] [--outro2 file]`

Middle video loops under the narration, is dimmed (with a fade), and the
script scrolls centered over it, with a pause before and after. Crossfaded
with intro/outro.

Output (`cocku/output/`): `COCKU-001_Title.mp4`, `.mp3`, `_intro.*`, `_middle.mp4`
(processed), `_image_prompt.txt`, optional `_tiktok.mp4`.

**Alternate ending:** if `assets/outro-2.*` exists (or `--outro2`), each episode
also gets `_alt-ending.mp4`, `_alt-ending.mp3` and (with `--tiktok`) `_alt-ending_tiktok.mp4`.

Look and feel: `video.cocku` in `cocku/config.json` (`font_file`, `font_color`,
`font_size`, `dim_opacity`, `dim_fade_seconds`, `pad_seconds`, `chars_per_line`).
Set `font_file` to a font that exists on your machine.
