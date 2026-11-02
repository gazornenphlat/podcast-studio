"""The Studio reads the pipeline's printed lines back. These tests keep the two in step."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                       # podcast_studio/
sys.path.insert(0, str(HERE.parent / "common"))

import markers as M  # noqa: E402


def test_image_needed_line_round_trips():
    single = f"{M.IMAGE_NEEDED}story 1/2: My Title"
    multi = f"{M.IMAGE_NEEDED}story 2/2: My Title — image 3 of 3"
    m = M.IMAGE_NEEDED_RE.match(single)
    assert m and m.group(1) == "My Title" and m.group(2) is None
    m = M.IMAGE_NEEDED_RE.match(multi)
    assert m and m.group(1) == "My Title" and (m.group(2), m.group(3)) == ("3", "3")


def test_next_label_parses_continue_prompt():
    line = f"{M.PROMPT_CONTINUE} (2 left — next: Chapter Two) [Y/n]: "
    assert M.NEXT_LABEL_RE.search(line).group(1) == "Chapter Two"


def test_marker_strings_only_live_in_markers_module():
    """Any literal copy of a marker in the pipeline or the Studio would drift on its own.
    They must be imported from common/markers.py instead."""
    literals = [M.IMAGE_NEEDED.strip(), M.SAVE_AS, M.STILL_MISSING, M.PROMPT_CONTINUE,
                M.PROMPT_IMAGES, M.DONE, M.SCHEDULED, M.STORY_HEADER, M.CREATE_PROMPT]
    files = [p for p in (ROOT / "podcast_pipeline").rglob("*.py")
             if "tests" not in p.parts and p.name != "markers.py"]
    files.append(ROOT / "content_scheduler" / "studio.py")
    offenders = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for lit in literals:
            if lit in text:
                offenders.append(f"{f.relative_to(ROOT)}: {lit!r}")
    assert not offenders, "copy marker text from common/markers.py instead:\n" + "\n".join(offenders)
