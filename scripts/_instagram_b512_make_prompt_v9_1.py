"""Phase B.5.1.2: generate prompts/instagram_creative_director_carousel/v9.1.yaml from the (untouched) v9 file. v9.1 is v9 except for the EVIDENCE-REFERENCE
contract: evidence is supplied as handles (E1, E2, ...) and the model cites handles, never re-typed evidence text.

Usage: python scripts/_instagram_b512_make_prompt_v9_1.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V9 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v9.yaml"
V91 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v9.1.yaml"

_SYSTEM_OLD = "every factual claim must be copied (verbatim or near-verbatim) from one of those bullets, and you must list every evidence bullet you actually used in evidence_used."
_SYSTEM_NEW = ("every factual claim must come from one of those evidence items, and you must list the HANDLE (E1, E2, ...) of every evidence item you actually used in "
               "evidence_used.")
_SOURCE_OLD = "Each slide's source_evidence should name which evidence bullet (if any) that slide draws from."
_SOURCE_NEW = "Each slide's source_evidence is either null or ONE supplied evidence handle such as E2 (the handle only, never the text)."
_USED_OLD = "evidence_used must only contain bullets that were actually given to you - never a new one."
_USED_NEW = ("evidence_used must contain ONLY the supplied evidence handles (for example [\"E1\", \"E3\"]) of the items you actually used - never a new handle, never a "
             "[story_N] label, never a paraphrase and never evidence text. Slide copy itself may naturally reword supported facts under the factual rules above.")


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V9.read_text(encoding="utf-8")))
    doc["version"] = "9.1"
    assert _SYSTEM_OLD in doc["system"], "v9 system evidence sentence changed"
    doc["system"] = doc["system"].replace(_SYSTEM_OLD, _SYSTEM_NEW)
    rules = []
    for rule in doc["rules"]:
        rules.append(_SOURCE_NEW if rule == _SOURCE_OLD else _USED_NEW if rule == _USED_OLD else rule)
    assert _SOURCE_NEW in rules and _USED_NEW in rules, "v9 evidence rules changed"
    doc["rules"] = rules
    props = doc["output_schema"]["properties"]
    props["evidence_used"] = {"type": "array", "items": {"type": "string", "maxLength": 12, "description": "an evidence handle such as E1"}}
    return doc


def main() -> None:
    header = (
        "# Phase B.5.1.2: v9.1 = v9 except for the evidence-reference contract. Evidence is supplied as handles (E1, E2, ...); evidence_used and source_evidence cite\n"
        "# HANDLES, never re-typed text. The handles are references only: the caller resolves them back to the exact canonical evidence strings. v9 stays untouched.\n"
    )
    V91.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V91)


if __name__ == "__main__":
    main()
