"""Autonomous Product Quality Loop, iteration 3: generate prompts/instagram_creative_director_carousel/v10.6.yaml from the (untouched)
v10.5 file. One archetype-rule clarification, wording only, no schema change. Real iteration-2 evidence: the NEWS_RECAP opener reused
story_1's exact image with the same full-bleed crop, so slides 1 and 2 of the carousel were near-identical. 'Its own visual' now says
what it means.

Usage: python scripts/_instagram_b8_make_prompt_v10_6.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V105 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.5.yaml"
V106 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.6.yaml"

_OLD = "news_recap: a short opening with its own visual,"
_NEW = ("news_recap: a short opening with its own visual (a GENERATED image that synthesises the week, or a clearly different crop and scale "
        "of one story's image - never the same picture framed the same way as the story slide that follows),")


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V105.read_text(encoding="utf-8")))
    doc["version"] = "10.6"
    rules = list(doc["rules"])
    hits = [i for i, r in enumerate(rules) if _OLD in r]
    assert len(hits) == 1, f"v10.5 archetype rule wording changed ({len(hits)} matches)"
    rules[hits[0]] = rules[hits[0]].replace(_OLD, _NEW, 1)
    doc["rules"] = rules
    return doc


def main() -> None:
    header = (
        "# Autonomous Product Quality Loop, iteration 3: v10.6 = v10.5 + the NEWS_RECAP opener is its own visual, never the next story\n"
        "# slide's picture framed the same way. No schema change. v10.5 stays published and untouched.\n"
    )
    V106.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V106)


if __name__ == "__main__":
    main()
