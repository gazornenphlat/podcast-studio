"""Rewrite step for WITN: script-in.txt -> Ollama rewrite -> script.txt,
plus a .txt per story and one .docx for the whole batch.

script-in.txt: stories separated by a blank line (same as script.txt).
script.txt (written here, used by the rest of the process):

    Title of story one
    Rewritten story one...

    Title of story two
    Rewritten story two...

The title is the first line (no blank line after it), so it is read aloud
first, then the pause, then the story.
"""
import re
import textwrap
from pathlib import Path

from utils import _call_ollama, generate_title, parse_script_file

DEFAULT_INSTRUCTIONS = (
    "Rewrite the following story in your own words as a lively script to be read "
    "aloud. Keep every fact, name and number. Keep it about the same length."
)

_PREAMBLE = re.compile(r"^(here('s| is| are)|sure|okay|ok|certainly|rewritten)\b.{0,80}:\s*$", re.I)


def _clean(text):
    """Strip chatty preamble/quotes and blank lines (a blank line would split the story)."""
    lines = [l.strip() for l in text.strip().splitlines()]
    while lines and (not lines[0] or _PREAMBLE.match(lines[0])):
        lines.pop(0)
    out = "\n".join(l for l in lines if l)
    return out.strip().strip('"').strip()


def _clean_title(title):
    title = title.strip().strip('"').strip("'").strip("*").strip()
    return re.sub(r"^title:\s*", "", title, flags=re.I)


def rewrite_story(text, config):
    rw = config.get("rewrite", {})
    prompt = textwrap.dedent(f"""\
        {rw.get("instructions", DEFAULT_INSTRUCTIONS)}

        Return ONLY the rewritten story as plain text — no title, no headings,
        no preamble, no notes, no markdown.

        STORY:
        {text}
    """)
    return _clean(_call_ollama(prompt, config, max_tokens=int(rw.get("max_tokens", 1500))))


def rewrite_script(script_in, script_out, config):
    """Rewrite every story in `script_in` and write `script_out`.
    Returns a list of {"title", "story"} in order."""
    stories = parse_script_file(script_in, "\0no-marker\0")
    if not stories:
        raise SystemExit(f"No stories found in {script_in}")
    print(f"Found {len(stories)} story(ies) in {script_in} — rewriting with Ollama...")
    out = []
    for i, s in enumerate(stories, 1):
        print(f"\n→ Rewriting story {i}/{len(stories)}...")
        story = rewrite_story(s["display"], config)
        if not story:
            raise SystemExit(f"Ollama returned nothing for story {i}.")
        print("→ Generating title...")
        title = _clean_title(generate_title(story, config))
        print(f"  Title: {title}")
        out.append({"title": title, "story": story})
    Path(script_out).write_text(
        "\n\n".join(f"{x['title']}\n{x['story']}" for x in out) + "\n", encoding="utf-8")
    print(f"\n📝 Rewritten script saved: {script_out}")
    return out


def rewrite_one(raw_text, config):
    """Rewrite one story and title it -> {"title", "story"}."""
    print("→ Rewriting the story...")
    story = rewrite_story(raw_text, config)
    if not story:
        raise SystemExit("The language model returned nothing for this story.")
    print("→ Generating title...")
    title = _clean_title(generate_title(story, config))
    print(f"  Title: {title}")
    return {"title": title, "story": story}


def write_script(script_out, entries):
    """script.txt: title on the first line, story under it, blank line between stories."""
    Path(script_out).write_text(
        "\n\n".join(f"{x['title']}\n{x['story']}" for x in entries) + "\n", encoding="utf-8")


def _prompts_only(im):
    return im["prompt"].strip()


def export_story_files(stories, prepared, config, output_dir):
    """One <episode>.txt per story (title, story), and every story appended to one
    running Word file (<PREFIX>_Stories.docx, or process.stories_docx):
    title, blank line, story, blank line, "Image Prompt", blank line, prompts."""
    from docx import Document

    output_dir = Path(output_dir)
    name = config.get("process", {}).get("stories_docx") or f"{config['naming']['prefix']}_Stories.docx"
    path = output_dir / name
    existing = path.exists()
    doc = Document(str(path)) if existing else Document()
    for i, (story, prep) in enumerate(zip(stories, prepared)):
        title, _, body = story["display"].strip().partition("\n")
        title, body = title.strip(), body.strip()

        txt = output_dir / f"{prep['stem']}.txt"
        txt.write_text(f"{title}\n{body}\n", encoding="utf-8")
        print(f"📝 Story text saved: {txt}")

        if i or existing:
            doc.add_page_break()
        doc.add_heading(title, level=1)
        doc.add_paragraph()
        for para in body.splitlines():
            doc.add_paragraph(para)
        doc.add_paragraph()
        doc.add_heading("Image Prompt", level=2)
        doc.add_paragraph()
        n = len(prep["images"])
        for j, im in enumerate(prep["images"]):
            if j:
                doc.add_paragraph()
            if n > 1:
                doc.add_paragraph().add_run(f"Image {im['n']} of {n} — save as {im['path'].name}").bold = True
            for line in _prompts_only(im).splitlines():
                if line.strip():
                    doc.add_paragraph(line.strip())

    try:
        doc.save(path)
    except PermissionError:
        raise SystemExit(f"Can't write {path} — close it in Word and run again.")
    print(f"📄 {'Added to' if existing else 'Created'} Word document: {path} "
          f"({len(prepared)} stor{'y' if len(prepared) == 1 else 'ies'})")
    return path
