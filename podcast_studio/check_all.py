"""One command for every check: python check_all.py  (run from this folder).

1. Duplicate keys and bad structure in every config file.
2. Pipeline tests.
3. Content Scheduler tests.
Exits with a non-zero code on the first failure. Needs pytest and ffmpeg on PATH for the video test."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    ("configs", [sys.executable, str(HERE / "podcast_pipeline" / "tools" / "check_configs.py")], HERE),
    ("pipeline tests", [sys.executable, "-m", "pytest", "tests", "-q"], HERE / "podcast_pipeline"),
    ("scheduler tests", [sys.executable, "-m", "pytest", "tests", "-q"], HERE / "content_scheduler"),
]


def main():
    for name, cmd, cwd in STEPS:
        print(f"== {name}", flush=True)
        result = subprocess.run(cmd, cwd=cwd)
        if result.returncode != 0:
            print(f"FAILED: {name}. See the output above.")
            return result.returncode
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
