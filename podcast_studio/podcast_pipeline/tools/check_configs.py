"""Find duplicate keys in every config file, before they silently override each other.

    python podcast_pipeline/tools/check_configs.py [folder]

Checks config.json files under podcast_pipeline/ and config.yaml / secrets*.yaml /
series.yaml under content_scheduler/. Exits 1 if anything is wrong.
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]


def _json_dupes(path):
    problems = []

    def hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                problems.append(f"duplicate key {key!r}")
            seen.add(key)
        return dict(pairs)

    try:
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except ValueError as ex:
        problems.append(f"invalid JSON: {ex}")
    return problems


def _yaml_node_dupes(node, trail, problems):
    if isinstance(node, yaml.MappingNode):
        seen = set()
        for k, v in node.value:
            name = getattr(k, "value", str(k))
            if name in seen:
                problems.append(f"duplicate key {name!r} under {trail or '<top level>'}")
            seen.add(name)
            _yaml_node_dupes(v, f"{trail}.{name}" if trail else str(name), problems)
    elif isinstance(node, yaml.SequenceNode):
        for i, v in enumerate(node.value):
            _yaml_node_dupes(v, f"{trail}[{i}]", problems)


def _yaml_dupes(path):
    problems = []
    try:
        root = yaml.compose(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as ex:
        return [f"invalid YAML: {ex}"]
    if root is not None:
        _yaml_node_dupes(root, "", problems)
    return problems


def main():
    files = sorted(ROOT.glob("podcast_pipeline/**/config.json"))
    files += [p for p in ROOT.glob("content_scheduler/*.yaml") if p.name in
              ("config.yaml", "secrets.yaml", "series.yaml")]
    bad = 0
    for f in files:
        probs = _json_dupes(f) if f.suffix == ".json" else _yaml_dupes(f)
        if probs:
            bad += 1
            for pr in probs:
                print(f"PROBLEM  {f.relative_to(ROOT)}: {pr}")
    print(f"checked {len(files)} file(s); {bad} with problems" if files else "no config files found")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
