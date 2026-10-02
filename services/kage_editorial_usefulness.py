"""Deterministic KAGE editorial-usefulness guard: block a safe but empty headline restatement.

Runs after the publication factual gate passed and before delivery. It never calls a model and
never judges factual safety. Headline and body are mapped onto the already-selected Research
fact cards (the same cards the story contract, writer, Quality and factual gate use). A text
"communicates" a card when it carries enough of that card's distinctive substance, after
morphology normalization and small synonym groups, so a paraphrase ("на паузе" / "приостановила")
maps to the same fact. When the story contract has 2+ core facts, the body must communicate at
least one supported fact the headline does not already carry. One-core-fact stories always pass.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from services.kage_evidence_first import _GAP_OR_META, content_stems, minimum_story_contract, select_evidence_cards
from services.news_current_delta import evaluate_current_delta

GUARD_VERSION = "2"

# Small, generic paraphrase groups (not story-specific): each maps to one canonical token.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("пауз", "приос", "остан", "замор", "прекр", "halt", "pause", "suspe"),
    ("прави", "госор", "госуч", "госст", "госсл", "госве", "ведом", "feder", "gover"),
    ("запре", "блоки", "бан", "огран"),
    ("выпус", "запус", "предс", "анонс", "релиз", "launc", "relea"),
    ("купи", "покуп", "приоб", "погло", "acqui"),
    ("уволи", "уволь", "отстр", "сокра"),
)
_CANON = {stem: group[0] for group in _SYNONYM_GROUPS for stem in group}


def _canon(stems: set[str]) -> set[str]:
    return {_CANON.get(stem, stem) for stem in stems}


def _distinctive(cards: list[dict[str, Any]]) -> dict[int, set[str]]:
    """Each card's own substance: canonical stems no other selected card carries."""
    stems = {card["id"]: _canon(content_stems(card["fact"])) for card in cards}
    result = {}
    for card_id, own in stems.items():
        others = set().union(*(s for other, s in stems.items() if other != card_id))
        result[card_id] = own - others
    return result


def communicated_fact_ids(text: str, cards: list[dict[str, Any]]) -> list[int]:
    """Card ids whose distinctive substance the text carries (>= 2 stems and >= 30% of it)."""
    words = _canon(content_stems(text))
    found = []
    for card_id, distinct in _distinctive(cards).items():
        if not distinct:
            continue
        matched = len(words & distinct)
        if matched >= min(2, len(distinct)) and matched >= math.ceil(0.3 * len(distinct)):
            found.append(card_id)
    return sorted(found)


def evaluate_editorial_usefulness(
    *, title: str, body: str, research: Mapping[str, Any], intelligence: Mapping[str, Any],
    source_headline: str = "", now: datetime | None = None,
) -> dict[str, Any]:
    try:
        story = minimum_story_contract(research, intelligence, source_headline=source_headline)
        cards, _, _ = select_evidence_cards(research, intelligence, source_headline=source_headline)
    except ValueError:
        # No buildable story contract (e.g. no Research facts). The publication factual gate builds
        # the same contract and owns that failure; this guard has nothing to compare against.
        return {"guard_version": GUARD_VERSION, "core_fact_ids": [], "applicable": False, "passed": True,
                "reason": "no_story_contract", "headline_fact_ids": [], "body_fact_ids": [], "new_body_fact_ids": []}
    core_ids = [item["id"] for item in story["core_facts"]]
    substantive = [card for card in cards if not _GAP_OR_META.search(card["fact"])]
    current_delta = evaluate_current_delta(
        title=title,
        content=body,
        old_event_context=" ".join(
            [source_headline, *(str(item.get("fact") or "") for item in story["core_facts"])]
        ),
        now=now,
        require_headline_delta=True,
        require_body_delta=True,
    )
    result: dict[str, Any] = {
        "guard_version": GUARD_VERSION, "core_fact_ids": core_ids,
        "applicable": len(core_ids) >= 2, "passed": True, "reason": None,
        "headline_fact_ids": [], "body_fact_ids": [], "new_body_fact_ids": [],
        "current_delta_classification": current_delta.classification,
        "underlying_old_event": current_delta.underlying_old_event,
        "weak_disclosure": current_delta.weak_disclosure,
        "material_current_delta": current_delta.material_current_delta,
        "headline_foregrounds_delta": current_delta.headline_foregrounds_delta,
        "body_explains_delta": current_delta.body_explains_delta,
    }
    if not current_delta.eligible:
        result.update(applicable=True, passed=False, reason=current_delta.reason)
        return result
    if not result["applicable"]:
        result["reason"] = "fewer_than_two_core_facts"
        return result
    headline_ids = communicated_fact_ids(title, substantive)
    body_ids = communicated_fact_ids(body, substantive)
    new_ids = [card_id for card_id in body_ids if card_id not in headline_ids]
    result.update(headline_fact_ids=headline_ids, body_fact_ids=body_ids, new_body_fact_ids=new_ids)
    if not new_ids:
        result.update(passed=False, reason="body_adds_no_supported_fact_beyond_headline")
    return result
