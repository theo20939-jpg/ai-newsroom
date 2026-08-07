"""Phase 19 M3: zero-cost, zero-LLM-call deterministic Editorial Plan scaffold, used exclusively
by capabilities/executor.py::_attach_editorial_plan()'s live "shadow" hook.

The real, AI-generated plan (via capabilities/editorial_planning_capability.py +
prompts/editorial_planning/v1.yaml) is only ever produced by the manually-invoked, never-
auto-run scripts/phase19_m3_editorial_plan_comparison.py - shadow mode's own explicit
requirement is "generate OR deterministically build the plan; persist it for review; do not
change Copywriting output," and this module is the deterministic half of that choice, selected
here specifically so the live path never makes a paid call and can never influence Copywriting
even accidentally (there is no code path from this scaffold to any prompt context).

Matches the same 16-field schema prompts/editorial_planning/v1.yaml declares, so a stored row is
directly comparable to a real, AI-generated plan later - but every field here is populated only
from data already computed elsewhere in the pipeline (NewsEvent, Research's own step_results,
Story Memory's match_type, EvidencePackage's known_evidence_gaps) - never inferred, never
guessed. Fields with no deterministic source available stay at an honest, empty placeholder
(never a fabricated value) - `is_deterministic_scaffold: True` on the caller's own persisted row
is what distinguishes this from real editorial judgment.
"""
from __future__ import annotations

from typing import Any

_STORY_MATCH_TYPE_TO_CLASSIFICATION = {
    "new_story": "new_story",
    "story_update": "update",
    "supporting_source": "confirmation",
    "semantic_duplicate": "confirmation",
    "uncertain_match": "analysis",
}


def build_deterministic_plan(
    *,
    title: str,
    research_facts: list[str] | None = None,
    story_match_type: str | None = None,
    known_evidence_gaps: list[str] | None = None,
) -> dict[str, Any]:
    """Pure. Never raises, never fabricates - every field is either a direct copy of already-
    available data or an honest empty placeholder."""
    return {
        "central_fact": title,
        "what_changed": None,
        "what_is_new": title,
        "why_it_matters": "",
        "essential_facts": list(research_facts) if research_facts else [],
        "secondary_facts_omittable": [],
        "necessary_background": None,
        "already_published_summary": None,
        "must_not_repeat": None,
        "story_classification": _STORY_MATCH_TYPE_TO_CLASSIFICATION.get(story_match_type or "", "new_story"),
        "headline_emphasis": title,
        "opening_emphasis": "",
        "what_remains_unknown": None,
        "verified_quote_text": None,
        "media_role_needed": "none",
        "editorial_risks": list(known_evidence_gaps) if known_evidence_gaps else [],
    }
