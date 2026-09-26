"""VIRAL STORIES EXPAND INTO CAROUSELS (founder product decision, 2026-09-26).

Single stays a valid format - for straightforward product updates, narrow factual announcements, short hard news and stories with one
useful editorial beat. But a story that is strange, funny, provocative, highly discussable or naturally "retellable" no longer defaults
to Single just because it has one core fact: it is retold as a swipeable Carousel of editorial beats.

The decision is deterministic and reads only what Phase A itself already decided (services.instagram_creative_director
.generate_editorial_decision - the frozen, grounded decision prompt is not touched):
  - Phase A chose `single`, and `carousel` is executable for this post;
  - the story carries a viral signal: the feed planner planned it as the TREND product (the internet-native slot), or Phase A read its
    angle as MEME / REACTION / DEBATE.
Everything else stays exactly as Phase A decided: a BREAKING / IMPACT / EXPLAINER / HOW_TO / PRODUCT_USE_CASE / COMPARISON /
EVERGREEN_VALUE single on a NEWS_INSIGHT or AI_HACK post remains a Single."""
from __future__ import annotations

from typing import Any

VIRAL_INTENTS = frozenset({"MEME", "REACTION", "DEBATE"})
VIRAL_PRODUCTS = frozenset({"TREND"})

VIRAL_CAROUSEL_NOTE = (
    "VIRAL STORY - SWIPEABLE RETELLING: this story is a carousel because it is unusual, funny, absurd or highly discussable - not because it "
    "has many facts. Retell it in 4-7 editorial BEATS, never as fact boxes: (1) what happened - the setup; (2) why it is weird / why it caught "
    "attention; (3) what exactly the AI, company or product did; (4) why people care; (5) the consequence, implication or punchline. Copy: "
    "punchy, conversational, internet-aware and easy to repost - short lines, a clear setup and payoff; never slang-heavy, cringe, chaotic or "
    "unclear, and every factual claim still comes ONLY from the evidence (no invented quotes, numbers or details). Visuals: a suitable real "
    "photo where one exists; otherwise a GENERATED editorial image per slide - expressive, ironic, meme-adjacent scenes with clear negative "
    "space for the copy - never fact cells, stacked info boxes, step rectangles or dashboard panels."
)


def _get(decision: Any, name: str) -> Any:
    return decision.get(name) if isinstance(decision, dict) else getattr(decision, name, None)


def viral_signals(decision: Any, *, planned_product: str | None) -> list[str]:
    """Why a story reads as viral / meme-worthy (empty: it does not)."""
    signals = []
    if planned_product in VIRAL_PRODUCTS:
        signals.append(f"planned_product={planned_product}")
    intent = _get(decision, "angle_intent")
    if intent in VIRAL_INTENTS:
        signals.append(f"angle_intent={intent}")
    return signals


def viral_carousel_upgrade(decision: Any, *, planned_product: str | None, executable_formats: list[str]) -> list[str]:
    """The viral signals that turn Phase A's `single` into a Carousel - empty when the Single stays (non-viral, not a single, or carousel
    not executable for this post)."""
    if _get(decision, "recommended_format") != "single" or "carousel" not in executable_formats:
        return []
    return viral_signals(decision, planned_product=planned_product)
