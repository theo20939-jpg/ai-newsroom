"""Phase 19 overnight A/B/C validation seam: deterministic serialization of an already-produced
EditorialPlan structured_output (prompts/editorial_planning/v1.yaml's schema, produced either by
the real, LLM-backed EditorialPlanningCapability or services/editorial_planning_deterministic.py's
scaffold) into the bounded text block CopywritingCapability's v6 prompt reads via
BusinessContext.editorial_plan_context.

Pure, deterministic, no LLM call, never fabricates a value not already present in the plan dict.
Bounded so a pathologically long field can never blow out the Copywriting request.
"""
from __future__ import annotations

from typing import Any

_MAX_FIELD_CHARS = 600
_MAX_LIST_ITEMS = 8


def _truncate(text: str, limit: int = _MAX_FIELD_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_list(items: list[Any] | None) -> str:
    if not items:
        return "(none)"
    bounded = [str(item) for item in items[:_MAX_LIST_ITEMS]]
    text = "\n".join(f"  - {_truncate(item, 200)}" for item in bounded)
    if len(items) > _MAX_LIST_ITEMS:
        text += f"\n  - … ({len(items) - _MAX_LIST_ITEMS} more, omitted for length)"
    return text


def serialize_editorial_plan(plan: dict[str, Any]) -> str:
    """Bounded, deterministic EditorialPlan -> text. Every line traces to a real field already in
    `plan` - never inferred, never invented. Missing/None fields render as an honest "(none)"/
    "(unknown)", never silently dropped (an absent field is itself informative to Copywriting -
    e.g. an empty `already_published_summary` on a plan classified "update" is a real signal)."""
    central_fact = _truncate(str(plan.get("central_fact") or "(none)"))
    what_changed = plan.get("what_changed")
    why_it_matters = _truncate(str(plan.get("why_it_matters") or "(none)"))
    story_classification = plan.get("story_classification") or "new_story"
    already_published = plan.get("already_published_summary")
    must_not_repeat = plan.get("must_not_repeat")
    necessary_background = plan.get("necessary_background")
    what_remains_unknown = plan.get("what_remains_unknown")
    media_role = plan.get("media_role_needed") or "none"

    lines = [
        f"central_fact: {central_fact}",
        f"story_classification: {story_classification}",
        f"what_changed: {_truncate(str(what_changed)) if what_changed else '(none - not an update)'}",
        f"why_it_matters: {why_it_matters}",
        "essential_facts:",
        _format_list(plan.get("essential_facts")),
        "secondary_facts_omittable:",
        _format_list(plan.get("secondary_facts_omittable")),
        f"necessary_background: {_truncate(str(necessary_background)) if necessary_background else '(none)'}",
        f"already_published_summary: {_truncate(str(already_published)) if already_published else '(none)'}",
        f"must_not_repeat: {_truncate(str(must_not_repeat)) if must_not_repeat else '(none)'}",
        f"what_remains_unknown: {_truncate(str(what_remains_unknown)) if what_remains_unknown else '(none)'}",
        f"media_role_needed: {media_role}",
        "editorial_risks:",
        _format_list(plan.get("editorial_risks")),
    ]
    return "\n".join(lines)
