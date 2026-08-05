"""Meme Intelligence Calibration Update (Phase 18.7): additive v2 calibration layer over the
existing, unmodified M1/M3 classifiers, encoding the Phase 18.6 human-calibration-packet's own
system-level findings (docs/phase18_6_meme_calibration_report.md §6, docs/
phase18_7_calibration_results.md).

Both `services.meme_opportunity.assess_meme_opportunity()` and `services.meme_opportunity.
detect_sensitive_categories()` (the latter reused by `services.meme_safety` for the concept-text
scan) are imported and called exactly as-is - never modified, never re-implemented. This module
only computes a *delta* on top of their output: a bounded score adjustment for M1 (never a block,
never an override of `SENSITIVE_BLOCK`/`INSUFFICIENT_SOURCE`), and a per-phrase context-exception
filter for M3/M1's shared sensitivity scan (never a blanket category suppression, always cancelled
by an override marker). Zero LLM calls, zero network calls, zero new external dependencies - pure
text-in, structured-out functions, exactly like every classifier this project has shipped since
Phase 15.

Not wired into `CapabilityExecutor`, `WorkflowRunner`, or any live call site in this phase - see
`core.config.Settings.meme_opportunity_calibration_version`/`meme_safety_calibration_version`'s
own docstring. Exercised only by `tests/test_phase18_7_meme_calibration_rules.py` and
`scripts/phase18_7_calibration_replay.py`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from database.models.news_event import EventCategory
from schemas.meme_calibration_rules import MemeOpportunityAssessmentV2, SafetyContextExceptionResultV2
from schemas.meme_opportunity import MemeOpportunityDecision
from services.meme_opportunity import (
    _READY_THRESHOLD as _V1_READY_THRESHOLD,  # single source of truth - never redefined here
)
from services.meme_opportunity import (
    _REVIEW_THRESHOLD as _V1_REVIEW_THRESHOLD,
)
from services.meme_opportunity import (
    assess_meme_opportunity,
    detect_sensitive_categories,
)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


# ---------------------------------------------------------------------------
# Finding 1 - M1: research-paper/academic-abstract false positives (Phase 18.5 M4 §6, Phase 18.6
# MEDIUM sample: 16/20 real MEDIUM records were arXiv abstracts, 18/20 carried `contrast_connector`
# evidence - academic hedge-then-contrast phrasing structurally resembles the irony/contrast
# pattern M1 looks for, but is not irony). A penalty, never a block - the brief's own explicit
# "Do NOT block. Only reduce opportunity probability" requirement.
# ---------------------------------------------------------------------------

_ARXIV_SOURCE_MARKERS = frozenset({"arxiv"})
_ABSTRACT_STYLE_MARKERS = frozenset({
    "we propose", "we show that", "we demonstrate", "in this paper", "we present",
    "we introduce", "our approach", "our method",
})
_METHODOLOGY_MARKERS = frozenset({
    "methodology", "experiment", "dataset", "benchmark", "evaluation metric", "ablation study",
})
_BENCHMARK_TERMINOLOGY_MARKERS = frozenset({
    "state-of-the-art", "sota", "outperforms", "baseline", "outperform the baseline",
})
_SCIENTIFIC_FRAMING_MARKERS = frozenset({
    "theorem", "proof", " eq. ", "equation", "hypothesis", "empirical results",
})

_ARXIV_SOURCE_PENALTY = 22
_RESEARCH_MARKER_PENALTY = 4
_MAX_RESEARCH_PENALTY = 30


def _score_research_paper_penalty(text: str, source_name: str | None) -> tuple[int, list[str]]:
    """Returns a *positive* penalty magnitude (the caller subtracts it) plus evidence. Deliberately
    conservative: an arXiv source alone is enough to cross the brief's own worked example (a
    36-40 MEDIUM score dropping below the 35 REVIEW threshold into LOW); additional research-style
    language nudges non-arXiv-tagged academic writing down too, but less aggressively, so a
    genuinely ironic story that happens to use the word "however" is not wrongly penalized."""
    penalty = 0
    evidence: list[str] = []

    source_lower = (source_name or "").lower()
    if any(marker in source_lower for marker in _ARXIV_SOURCE_MARKERS):
        penalty += _ARXIV_SOURCE_PENALTY
        evidence.append("research_paper:arxiv_source")

    marker_groups = {
        "abstract_style": _ABSTRACT_STYLE_MARKERS,
        "methodology": _METHODOLOGY_MARKERS,
        "benchmark_terminology": _BENCHMARK_TERMINOLOGY_MARKERS,
        "scientific_framing": _SCIENTIFIC_FRAMING_MARKERS,
    }
    for label, markers in marker_groups.items():
        if any(marker in text for marker in markers):
            penalty += _RESEARCH_MARKER_PENALTY
            evidence.append(f"research_paper:{label}")

    return min(penalty, _MAX_RESEARCH_PENALTY), evidence


# ---------------------------------------------------------------------------
# Finding 2 - M1: missing positive signals (human emotion, company drama, gaming controversy,
# recognizable brand + conflict). Every component is capped individually; the brand+conflict bonus
# only fires when a drama/gaming-controversy signal (or v1's own irony evidence) is also present -
# the brief's own explicit "Only when combined with conflict/irony/failure. Do NOT make every
# brand mention a meme" requirement.
# ---------------------------------------------------------------------------

_HUMAN_EMOTION_MARKERS = frozenset({
    "frustrated", "frustration", "furious", "stunned", "shocked", "disappointed", "disappointment",
    "let down", "thrilled", "excited", "excitement",
    "разочарован", "возмущены", "ошеломлены", "в восторге", "в ярости",
})
_COMMUNITY_REACTION_MARKERS = frozenset({
    "backlash", "outcry", "went viral", "trending", "flooded with", "public outrage",
    "критику", "волна возмущения", "хайп",
})
_COMPANY_DRAMA_MARKERS = frozenset({
    "launch failed", "botched launch", "public criticism", "widely criticized", "under fire",
    "faces backlash", "provokes criticism", "public backlash", "unexpected decision",
    "скандал", "критикуют", "неожиданное решение",
})
_GAMING_CONTROVERSY_MARKERS = frozenset({
    "delayed again", "delayed", "player backlash", "fans furious", "review bombed",
    "review bombing", "price increase criticized", "pricing complaints", "back in my day",
    "used to be better", "pay to win", "microtransaction backlash", "controversial update",
    "patch backlash", "nostalgic comparison",
})
_RECOGNIZABLE_BRANDS = frozenset({
    "apple", "google", "openai", "microsoft", "nvidia", "tesla", "sony", "nintendo", "steam",
    "playstation", "xbox",
})

_EMOTION_BONUS = 5
_MAX_EMOTION_BONUS = 15
_DRAMA_BONUS = 15
_GAMING_BONUS = 15
_BRAND_CONFLICT_BONUS = 10
_MAX_TOTAL_POSITIVE_DELTA = 25


def _score_human_emotion(text: str) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    if any(marker in text for marker in _HUMAN_EMOTION_MARKERS):
        score += _EMOTION_BONUS
        evidence.append("positive_signal:human_emotion")
    if any(marker in text for marker in _COMMUNITY_REACTION_MARKERS):
        score += _EMOTION_BONUS
        evidence.append("positive_signal:community_reaction")
    return min(score, _MAX_EMOTION_BONUS), evidence


def _score_company_drama(text: str) -> tuple[int, list[str]]:
    if any(marker in text for marker in _COMPANY_DRAMA_MARKERS):
        return _DRAMA_BONUS, ["positive_signal:company_drama"]
    return 0, []


def _score_gaming_controversy(text: str) -> tuple[int, list[str]]:
    if any(marker in text for marker in _GAMING_CONTROVERSY_MARKERS):
        return _GAMING_BONUS, ["positive_signal:gaming_controversy"]
    return 0, []


def _score_brand_conflict(text: str, *, has_conflict_signal: bool) -> tuple[int, list[str]]:
    if not has_conflict_signal:
        return 0, []
    matched_brands = [brand for brand in _RECOGNIZABLE_BRANDS if brand in text]
    if not matched_brands:
        return 0, []
    return _BRAND_CONFLICT_BONUS, [f"positive_signal:brand_conflict:{matched_brands[0]}"]


def compute_calibration_delta(text: str, source_name: str | None) -> tuple[int, list[str]]:
    """Pure: the single function that turns v1's already-computed composite score into a v2
    `calibration_score_delta`. Penalty is subtracted first (Finding 1), then bonuses are summed
    and capped (Finding 2); the final delta is clamped to `[-30, +25]` so calibration remains an
    incremental adjustment, never a wholesale rescoring."""
    penalty, penalty_evidence = _score_research_paper_penalty(text, source_name)
    emotion_bonus, emotion_evidence = _score_human_emotion(text)
    drama_bonus, drama_evidence = _score_company_drama(text)
    gaming_bonus, gaming_evidence = _score_gaming_controversy(text)
    conflict_present = bool(drama_evidence) or bool(gaming_evidence)
    brand_bonus, brand_evidence = _score_brand_conflict(text, has_conflict_signal=conflict_present)

    positive_total = min(emotion_bonus + drama_bonus + gaming_bonus + brand_bonus, _MAX_TOTAL_POSITIVE_DELTA)
    delta = positive_total - penalty

    evidence = [*penalty_evidence, *emotion_evidence, *drama_evidence, *gaming_evidence, *brand_evidence]
    return delta, evidence


def assess_meme_opportunity_v2(
    news_event_title: str,
    news_event_content: str | None,
    news_event_category: EventCategory,
    news_event_published_at: datetime | None,
    research_output: dict[str, Any],
    *,
    source_name: str | None = None,
    has_image_candidate: bool | None = None,
    now: datetime | None = None,
) -> MemeOpportunityAssessmentV2:
    """Calls the unmodified v1 `assess_meme_opportunity()` first, then applies the calibration
    delta on top of its composite score. `SENSITIVE_BLOCK` and `INSUFFICIENT_SOURCE` pass through
    completely unchanged - calibration only ever adjusts the MEME_READY/REVIEW/NOT_SUITABLE
    boundary, mirroring v1's own precedence discipline exactly."""
    base = assess_meme_opportunity(
        news_event_title, news_event_content, news_event_category, news_event_published_at,
        research_output, has_image_candidate=has_image_candidate, now=now,
    )
    base_score = base.signals.composite_score

    if base.decision in (MemeOpportunityDecision.SENSITIVE_BLOCK, MemeOpportunityDecision.INSUFFICIENT_SOURCE):
        return MemeOpportunityAssessmentV2(
            base_decision=base.decision, base_composite_score=base_score, decision=base.decision,
            adjusted_composite_score=base_score, calibration_score_delta=0, calibration_evidence=[],
        )

    text = _normalize(f"{news_event_title} {news_event_content or ''}").lower()
    delta, evidence = compute_calibration_delta(text, source_name)
    adjusted = max(0, min(100, base_score + delta))

    if adjusted >= _V1_READY_THRESHOLD:
        decision = MemeOpportunityDecision.MEME_READY
    elif adjusted >= _V1_REVIEW_THRESHOLD:
        decision = MemeOpportunityDecision.REVIEW
    else:
        decision = MemeOpportunityDecision.NOT_SUITABLE

    return MemeOpportunityAssessmentV2(
        base_decision=base.decision, base_composite_score=base_score, decision=decision,
        adjusted_composite_score=adjusted, calibration_score_delta=delta, calibration_evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Finding 3 - M3/M1 shared sensitivity scan: keyword-only false positives on game/franchise titles
# ("war") and technical/creative usage ("died"/"killed"/"shooting"). Finding 4 - stay conservative:
# every exception has its own `override_markers` set; if any override marker is also present in
# the text, the exception is cancelled and the original v1 block is preserved.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ContextException:
    phrase: str
    category: str
    safe_context_markers: frozenset[str]
    override_markers: frozenset[str]


_CONTEXT_EXCEPTIONS: tuple[_ContextException, ...] = (
    _ContextException(
        phrase="war", category="war",
        safe_context_markers=frozenset({
            "god of war", "gears of war", "total war", "war thunder",
            "game", "gaming", "trailer", "dlc", "multiplayer", "beta", "patch", "xbox",
            "playstation", "steam", "nintendo", "gpu driver", "graphics driver",
            "видеоигр", "мультиплеер", "трейлер", "драйвер",
        }),
        override_markers=frozenset({
            "invasion", "airstrike", "air strike", "war crime", "military strike",
            "вторжение", "обстрел", "военное преступление", "боевые действия",
        }),
    ),
    _ContextException(
        phrase="died", category="death_or_tragedy",
        safe_context_markers=frozenset({
            "process", "server", "service", "connection", "session", "container", "instance",
            "application", "app", "system", "thread", "job", "script", "database", "pod",
            "процесс", "сервер", "система", "приложени",
        }),
        override_markers=frozenset({
            "hospital", "funeral", "family", "police", "больниц", "похорон", "семь",
        }),
    ),
    _ContextException(
        phrase="killed", category="death_or_tragedy",
        safe_context_markers=frozenset({
            "process", "app", "background", "download", "connection", "session", "task", "job",
            "фоновое приложение", "процесс",
        }),
        override_markers=frozenset({
            "gunman", "shooter", "victim", "police", "hospital", "стрелял", "жертва",
        }),
    ),
    _ContextException(
        phrase="shooting", category="crime_with_victim",
        safe_context_markers=frozenset({
            "trajectory", "camera", "photo", "video", "range", "star", "hoop", "hoops", "goal",
            "траектор", "фото", "видео", "камер",
        }),
        override_markers=frozenset({
            "gunman", "shooter", "victim", "police", "wounded", "injured", "dead",
            "стрелял", "жертва", "ранен",
        }),
    ),
)


def _is_exempted(phrase: str, category: str, text: str) -> bool:
    for exc in _CONTEXT_EXCEPTIONS:
        if exc.phrase != phrase or exc.category != category:
            continue
        if any(marker in text for marker in exc.override_markers):
            return False
        return any(marker in text for marker in exc.safe_context_markers)
    return False


def detect_sensitive_categories_v2(text: str) -> SafetyContextExceptionResultV2:
    """Calls the unmodified v1 `detect_sensitive_categories()` first, then removes exactly the
    phrase matches a context exception covers (never a blanket per-category suppression - if any
    other, non-exempted phrase in the same category still matches, the category stays). Every
    suppressed match is recorded in `suppressed_evidence`, never silently dropped."""
    base_categories, base_evidence = detect_sensitive_categories(text)

    kept_evidence: list[str] = []
    suppressed_evidence: list[str] = []
    for item in base_evidence:
        category, _, phrase = item.partition(":")
        if _is_exempted(phrase, category, text):
            suppressed_evidence.append(item)
        else:
            kept_evidence.append(item)

    kept_categories = sorted({
        category for category in base_categories
        if any(evidence.startswith(f"{category}:") for evidence in kept_evidence)
    })

    return SafetyContextExceptionResultV2(
        base_categories=list(base_categories), categories=kept_categories, evidence=kept_evidence,
        suppressed_evidence=suppressed_evidence,
    )
