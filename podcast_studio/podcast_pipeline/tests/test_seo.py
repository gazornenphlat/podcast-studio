"""SEO meta description and keyphrases: parsed from the LLM's JSON reply, trimmed to
the length Google shows, and falling back to plain values when the reply is unusable."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import utils  # noqa: E402

STORY = "Dave tried to fix the sink. The sink won. Nobody was surprised. Dave was."


def test_parses_json_reply(monkeypatch):
    reply = 'Sure! {"meta_description": "Dave versus a sink, and the sink wins.", ' \
            '"focus_keyphrase": "funny plumbing story", "keyphrases": ["sink fail", "dave", "  "]}'
    monkeypatch.setattr(utils, "_call_ollama", lambda *a, **k: reply)
    seo = utils.generate_seo(STORY, "The Sink", {"seo": {"max_keyphrases": 5}})
    assert seo == {"meta_description": "Dave versus a sink, and the sink wins.",
                   "focus_keyphrase": "funny plumbing story", "keyphrases": ["sink fail", "dave"],
                   "fallback": False}


def test_long_meta_is_trimmed_on_a_word(monkeypatch):
    long = "word " * 80
    reply = json.dumps({"meta_description": long, "focus_keyphrase": "k", "keyphrases": []})
    monkeypatch.setattr(utils, "_call_ollama", lambda *a, **k: reply)
    meta = utils.generate_seo(STORY, "T", {})["meta_description"]
    assert len(meta) <= utils.SEO_META_MAX + 1 and meta.endswith("…")
    assert not meta[:-1].endswith(" ")


def test_unusable_reply_falls_back(monkeypatch):
    monkeypatch.setattr(utils, "_call_ollama", lambda *a, **k: "I cannot help with that.")
    seo = utils.generate_seo(STORY, "The Sink", {})
    assert seo["fallback"] is True
    assert seo["meta_description"] == "Dave tried to fix the sink."
    assert seo["focus_keyphrase"] == "the sink"


def test_llm_down_falls_back_without_failing(monkeypatch):
    def down(*a, **k):
        raise RuntimeError("Couldn't reach Ollama")
    monkeypatch.setattr(utils, "_call_ollama", down)
    seo = utils.generate_seo(STORY, "The Sink", {})
    assert seo["fallback"] is True
