"""Lines the pipeline prints that the Studio reads back.

The pipeline prints these and the Studio (content_scheduler/studio.py) parses them.
Both sides use the constants below, so a wording change is made once, here.
podcast_pipeline/tests/test_markers.py fails if a literal copy turns up elsewhere.
"""
import re

STORY_HEADER = "=== Story"                # "=== Story 2/5 ==="
PROMPT_IMAGES = "press Enter to continue (or q to quit)"
PROMPT_CONTINUE = "Continue with the next story?"
IMAGE_NEEDED = "🎨 IMAGE NEEDED — "      # "🎨 IMAGE NEEDED — story 1/2: Title — image 1 of 3"
SAVE_AS = "Save your image as:"
STILL_MISSING = "Still missing:"
CREATE_PROMPT = "Create the image"
DONE = "✅ Done:"
SCHEDULED = "📅 Scheduled:"

IMAGE_NEEDED_RE = re.compile(
    re.escape(IMAGE_NEEDED) + r"story \d+/\d+: (.*?)(?: — image (\d+) of (\d+))?$")
NEXT_LABEL_RE = re.compile(r"next: (.*?)\) \[Y/n\]")
