"""Autonomous Product Quality Loop, iteration 2: generate prompts/instagram_creative_director_carousel/v10.5.yaml from the (untouched)
v10.4 file. One hook-rule edit, wording only, no schema change. Real iteration-1 evidence: the NEWS_INSIGHT hook came back as
'Самая умная — не для каждой задачи', a near-paraphrase of the rule's own 'forgettable' example - the model anchored on it. The rule
now says its example lines are never to be reused or paraphrased, and names what a hook must carry instead: the reader's concrete
stake (money, time, effort, a habit, a risk, status) or one specific surprising fact/number from the evidence.

Usage: python scripts/_instagram_b8_make_prompt_v10_5.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V104 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.4.yaml"
V105 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.5.yaml"

_ANCHOR = "until the line has a real stake, not just a qualified observation."
_ADDITION = (
    " The example lines quoted in these rules only show a direction: NEVER reuse, translate or paraphrase them (a hook of the shape "
    "'X - не для каждой задачи' or 'X - не всегда Y' is that same forgettable line). The hook must carry at least one of: the reader's "
    "concrete stake (their money, time, effort, habit, risk or status), or one specific surprising fact, number or name from the evidence "
    "stated so the contrast is visible in the line itself."
)


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V104.read_text(encoding="utf-8")))
    doc["version"] = "10.5"
    rules = list(doc["rules"])
    hits = [i for i, r in enumerate(rules) if r.startswith("HOOK CONTRACT (slide 1).") and _ANCHOR in r]
    assert len(hits) == 1, f"v10.4 hook rule wording changed ({len(hits)} matches)"
    rules[hits[0]] = rules[hits[0]].replace(_ANCHOR, _ANCHOR + _ADDITION, 1)
    doc["rules"] = rules
    return doc


def main() -> None:
    header = (
        "# Autonomous Product Quality Loop, iteration 2: v10.5 = v10.4 + the hook rule forbids reusing/paraphrasing its own example lines and\n"
        "# requires a concrete reader stake or one specific surprising fact in the hook. No schema change. v10.4 stays published and untouched.\n"
    )
    V105.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V105)


if __name__ == "__main__":
    main()
