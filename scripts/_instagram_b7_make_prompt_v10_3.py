"""Product Quality Pass (Phase B.7): generate prompts/instagram_creative_director_carousel/v10.3.yaml from the (untouched) v10.2 file.

v10.3 = v10.2 (media-first contract, structured flow_steps, hook_emotion/hook_mechanic, evidence handles, Visual DNA v2) plus,
wording-only, no schema/field change:
  - a generated slide MUST cite an evidence handle in source_evidence (mirrors the new code-level requirement in
    services.instagram_media_first / services.instagram_creative_director - grounding is now structural, not a keyword guess);
  - the shared creative_execution_plan rule is strengthened so every slide's generated visual stays inside ONE visual world;
  - the hook rule is pushed further from safe editorial phrasing toward personal stake / sharp contradiction, with the
    founder's own worked example.

Usage: python scripts/_instagram_b7_make_prompt_v10_3.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V102 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.2.yaml"
V103 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.3.yaml"

_SOURCE_EVIDENCE_OLD = "Each slide's source_evidence is either null or ONE supplied evidence handle such as E2 (the handle only, never the text)."
_SOURCE_EVIDENCE_NEW = (
    "Each slide's source_evidence is ONE supplied evidence handle such as E2 (the handle only, never the text). A GENERATED slide MUST set "
    "source_evidence: the generated image is grounded in exactly that one evidence item, never guessed from word choice. A source or graphic "
    "slide may leave it null."
)
_PLAN_OLD = "Create one shared creative_execution_plan for the coherent series. Slides may vary crop, hierarchy, density and emphasis without becoming unrelated designs."
_PLAN_NEW = (
    "Create ONE shared creative_execution_plan for the coherent series: one central visual idea (main_idea), one visual motif or treatment "
    "(visual_treatment), one emotional tone, one media strategy. Every slide is part of that same visual world - a generated slide's "
    "generation_brief and story_anchor must visibly connect back to main_idea/visual_treatment (the same materials, palette logic or staging "
    "idea recurring with variation), not a fresh unrelated scene per slide. Slides may vary crop, hierarchy, density, emphasis and which "
    "specific object/moment they show without becoming unrelated designs - controlled variation on one idea, not a rotation of templates."
)
_HOOK_PREFIX = "HOOK CONTRACT (slide 1)."
_HOOK_INSERT_AFTER = "Prefer personal stake, a sharp contradiction, a specific surprise, an unexpected consequence, relatable pain or genuine absurdity over abstract editorial phrasing."
_HOOK_ADDITION = (
    " A hook that is merely factually safe is not enough: 'Самая умная модель - не всегда лучший выбор' is true and forgettable - push further "
    "toward what it actually means for the reader ('Ты платишь за мощность, которая тебе не нужна', or a sharper contradiction/consequence the "
    "evidence supports) until the line has a real stake, not just a qualified observation."
)


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V102.read_text(encoding="utf-8")))
    doc["version"] = "10.3"
    rules = list(doc["rules"])
    replaced = 0
    for i, rule in enumerate(rules):
        if rule == _SOURCE_EVIDENCE_OLD:
            rules[i], replaced = _SOURCE_EVIDENCE_NEW, replaced + 1
        elif rule == _PLAN_OLD:
            rules[i], replaced = _PLAN_NEW, replaced + 1
        elif rule.startswith(_HOOK_PREFIX):
            assert _HOOK_INSERT_AFTER in rule, "v10.2 hook rule wording changed"
            rules[i] = rule.replace(_HOOK_INSERT_AFTER, _HOOK_INSERT_AFTER + _HOOK_ADDITION, 1)
            replaced += 1
    assert replaced == 3, f"v10.2 source_evidence/plan/hook rules changed ({replaced} of 3 found)"
    doc["rules"] = rules
    return doc


def main() -> None:
    header = (
        "# Product Quality Pass (Phase B.7): v10.3 = v10.2 + (1) a generated slide MUST cite an evidence handle in source_evidence (structural\n"
        "# grounding, replaces the removed keyword-based VAGUE_DIRECTION_PHRASES guard), (2) the shared creative_execution_plan is strengthened\n"
        "# into one coherent visual world every slide stays inside, (3) the hook rule pushes past safe-but-forgettable phrasing toward real\n"
        "# stake. No schema change. v10.2 stays published and untouched.\n"
    )
    V103.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V103)


if __name__ == "__main__":
    main()
