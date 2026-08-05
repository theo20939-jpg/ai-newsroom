"""Meme Opportunity Detection (Phase 18 M1): deterministic, shadow-only classification of
whether a NewsEvent is worth attempting a meme for at all (docs/
phase18_m0_meme_discovery_report.md §6, docs/phase18_m1_meme_opportunity_report.md).

LLM/cost boundary (M1's own explicit requirement - zero new production API cost, matching every
Phase 17 shadow classifier's own discipline): everything here is a deterministic function of
already-available text (`NewsEvent.title`/`.content`/`.category`/`.published_at`), the "research"
step's already-computed facts, and - when present - the "copywriting" step's own already-attached
`image_intelligence` result (Phase 16). No LLM Gateway call, no provider SDK import, no network
call. Source sufficiency is obtained by calling `services.editorial_brief.
classify_source_sufficiency()` directly (a pure function), mirroring `services.channel_relevance`'s
own established reuse of that same classifier - this module does not re-derive source confidence
independently.

Split, mirroring `services/channel_relevance.py`'s/`services/fact_safety.py`'s own established
shape: pure classification/scoring functions (no I/O), plus one thin `apply_meme_opportunity_
shadow()` integration function that is the only piece `capabilities/executor.py` calls.

Known, disclosed limitation (docs/phase18_m0_meme_discovery_report.md §8 risk 4): irony/contrast
detection without an LLM is inherently coarse - a fixed, versioned keyword/pattern lexicon can
recognize *known rhetorical shapes* (hype-vs-substance, hedge-reassurance, relatable-statistic)
but will systematically under-detect novel or subtle irony. This is accepted for M1 (the brief's
own "0 additional LLM calls if possible" requirement) and is the primary reason this module ships
`shadow` mode only - real production volume must validate/calibrate these thresholds before any
future enforce mode, exactly as Phase 17's own M1-M7 calibration milestones did.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from database.models.news_event import EventCategory
from schemas.meme_opportunity import (
    MemeOpportunityAssessment,
    MemeOpportunityDecision,
    MemeOpportunitySignals,
)
from services.editorial_brief import SourceSufficiency, classify_source_sufficiency

POLICY_VERSION = "v1"

# ---------------------------------------------------------------------------
# Sensitivity lexicon - bilingual EN/RU, phrase-based wherever a bare word would over-block a
# benign story (mirrors services/channel_relevance.py's own "no bare company name scores a
# topic" discipline, applied here to "no bare 'child'/'ребёнок' alone blocks a story" - the real
# Phase 17 M0 audit sample includes a wholly benign "free AI clubs open in schools" story that a
# bare-word match would wrongly hard-block). Recall is intentionally favored over precision here
# (the opposite bias from channel_relevance's own "false REJECT worse than false REVIEW" - for
# safety, a false SENSITIVE_BLOCK is far cheaper than a false MEME_READY on a genuinely sensitive
# story, docs/phase18_m0_meme_discovery_report.md §8 risk 2).
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: dict[str, frozenset[str]] = {
    "death_or_tragedy": frozenset({
        # Deliberately no bare "dead" (real false positive found in M1's own gold-set backtest:
        # "The Walking Dead" streaming-rights story - a title/franchise word, not a death report)
        # - only phrases that actually report a death, mirroring services/channel_relevance.py's
        # own "no bare word alone scores a category" discipline.
        "died", "death", "deaths", "killed", "found dead", "pronounced dead", "confirmed dead",
        "left dead", "fatal", "fatality", "fatalities",
        "погиб", "погибли", "погибла", "умер", "умерла", "смерть", "жертв", "гибель",
        "tragedy", "tragic", "трагеди",
    }),
    "disaster": frozenset({
        "disaster", "earthquake", "wildfire", "flood", "flooding", "hurricane", "tsunami",
        "катастроф", "землетрясен", "наводнен", "пожар унёс", "ураган",
    }),
    "war": frozenset({
        "war", "invasion", "airstrike", "air strike", "war crime", "military strike",
        "война", "вторжение", "обстрел", "военное преступление", "боевые действия",
    }),
    "crime_with_victim": frozenset({
        "murder", "murdered", "shooting", "shot by", "shot dead", "stabbed", "kidnap",
        "kidnapped", "assault", "assaulted", "rape", "raped", "victim", "victims",
        "убийство", "убит", "стрельба", "ранен", "похищен", "нападение", "изнасил",
        "жертва",
    }),
    "minors_safety": frozenset({
        "minors' safety", "minor's safety", "minors safety", "child safety", "protect minors",
        "child exploitation", "child abuse", "grooming", "children's safety",
        "защита несовершеннолетних", "безопасность несовершеннолетних", "детской безопасности",
        "растление", "эксплуатация детей",
    }),
    "protected_characteristics": frozenset({
        "hate crime", "hate speech", "racist", "racism", "discriminat", "xenophob",
        "расист", "дискриминац", "ксенофоб", "разжигание ненависти",
    }),
    "serious_illness": frozenset({
        "cancer diagnosis", "terminal illness", "life-threatening illness", "diagnosed with cancer",
        "hospitalized with", "серьёзно болен", "тяжело болен", "онкологическое заболевание",
        "неизлечим", "рак диагностирован",
    }),
    "legal_jeopardy_or_accusation": frozenset({
        "terrorist", "extremist", "terrorists and extremists list", "wanted by police",
        "criminal charges", "accused of", "alleged", "allegedly",
        "террорист", "экстремист", "перечень террористов", "обвинение", "обвинил", "обвиняется",
        "подозревают", "уголовное дело",
    }),
    "harassment_or_stalking": frozenset({
        "stalking", "stalker", "swatting", "doxx", "doxxing", "revenge porn",
        "сталкинг", "преследование", "слежка",
    }),
}


def _compile_sensitive_patterns() -> dict[str, re.Pattern[str]]:
    compiled: dict[str, re.Pattern[str]] = {}
    for category, phrases in _SENSITIVE_PATTERNS.items():
        alternation = "|".join(re.escape(phrase) for phrase in sorted(phrases, key=len, reverse=True))
        compiled[category] = re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)
    return compiled


_SENSITIVE_COMPILED = _compile_sensitive_patterns()

# ---------------------------------------------------------------------------
# Irony/contrast markers - known rhetorical shapes only (module docstring's own disclosed limit).
# ---------------------------------------------------------------------------

_CONTRAST_CONNECTORS = frozenset({
    "however", "despite", "yet still", "even as", "at the same time", "while still",
    "несмотря на", "хотя", "однако", "но всё же", "в то время как", "притом что",
})
_HYPE_MARKERS = frozenset({
    "raised $", "raised €", "привлек", "привлекла", "привлёк", "valuation", "оценке в",
})
_SUBSTANCE_ABSENCE_MARKERS = frozenset({
    "no product", "not yet launched", "hasn't shipped", "has not yet shipped", "not yet shipped",
    "zero products", "pre-revenue", "no products on the market",
    "не выпустил", "ни одного продукта", "ещё не выпустила", "пока не выпустил",
})
_REASSURANCE_MARKERS = frozenset({
    "not destroying jobs", "isn't destroying jobs", "won't take your job", "isn't replacing",
    "не уничтожает рабочие места", "не заменит", "убеждает, что",
})
_IRONY_EXPLICIT_MARKERS = frozenset({
    "irony", "ironically", "paradox", "ирони", "парадокс",
})

# ---------------------------------------------------------------------------
# Audience relatability markers - everyday/workplace/consumer topics with broad reach.
# ---------------------------------------------------------------------------

_RELATABILITY_MARKERS = frozenset({
    "workplace", "colleagues", "коллеги", "рабочие места", "salary", "зарплата",
    "everyday", "daily life", "повседневн", "most people", "большинство", "workers",
    "работников", "employees", "сотрудник",
})
_PERCENT_RE = re.compile(r"\d+([.,]\d+)?\s*%")

# ---------------------------------------------------------------------------
# Visual potential markers - concrete, photographable/screenshot-able content.
# ---------------------------------------------------------------------------

_VISUAL_MARKERS = frozenset({
    "trailer", "screenshot", "photo", "video", "launch event", "unveiled", "showcased",
    "трейлер", "фото", "видео", "показали", "представили", "скриншот",
})

# ---------------------------------------------------------------------------
# Topic-fit prior by EventCategory - directional, from the n=32 real-sample audit
# (docs/phase18_m0_meme_discovery_report.md §6): AI/STARTUPS/TECH funding-hype and
# founder/exec-statement stories skew MEME_READY/POSSIBLE; HARDWARE/UNKNOWN dry technical
# content skews NOT_SUITABLE. A directional prior only, not a hard gate - never appears alone in
# `reason_codes` as a blocking reason.
# ---------------------------------------------------------------------------

_TOPIC_FIT_PRIOR: dict[EventCategory, int] = {
    EventCategory.AI: 75,
    EventCategory.STARTUPS: 70,
    EventCategory.TECH: 60,
    EventCategory.GADGETS: 50,
    EventCategory.SOFTWARE: 45,
    EventCategory.CYBERSECURITY: 40,
    EventCategory.HARDWARE: 35,
    EventCategory.UNKNOWN: 35,
}

# Weighted toward irony/contrast (the single strongest signal in the M0 real-data audit,
# docs/phase18_m0_meme_discovery_report.md §6) and topic fit; freshness is deliberately the
# smallest weight - a fresh-but-dull story should not out-rank a slightly older, genuinely
# ironic one (calibrated against M1's own gold-set backtest, docs/phase18_m1_meme_opportunity_
# report.md).
_COMPOSITE_WEIGHTS = {
    "irony_contrast_score": 0.40,
    "audience_relatability_score": 0.15,
    "visual_potential_score": 0.10,
    "topic_fit_score": 0.25,
    "freshness_score": 0.10,
}

_READY_THRESHOLD = 55
_REVIEW_THRESHOLD = 35
_THIN_SUFFICIENCY = {
    SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY, SourceSufficiency.CONFLICTING,
}


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def detect_sensitive_categories(text: str) -> tuple[list[str], list[str]]:
    """Returns (matched_categories, evidence). Evidence-only match phrases, never the surrounding
    sentence (no raw news content beyond the matched phrase itself is ever logged downstream).

    Public (no leading underscore) and imported directly by `services/meme_safety.py` (Phase 18
    M3) - a safety-relevant lexicon must have exactly one copy, never two independently-
    maintained ones that could silently drift apart between M1 (opportunity detection, scans the
    source NewsEvent) and M3 (safety gate, scans the generated MemeConcept's own text)."""
    categories: list[str] = []
    evidence: list[str] = []
    for category, pattern in _SENSITIVE_COMPILED.items():
        matches = sorted({m.group(0).lower() for m in pattern.finditer(text)})
        if matches:
            categories.append(category)
            evidence.extend(f"{category}:{phrase}" for phrase in matches[:3])
    return categories, evidence


def _score_irony_contrast(text: str) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    if any(marker in text for marker in _CONTRAST_CONNECTORS):
        score += 25
        evidence.append("contrast_connector")
    if any(marker in text for marker in _HYPE_MARKERS) and any(
        marker in text for marker in _SUBSTANCE_ABSENCE_MARKERS
    ):
        score += 60
        evidence.append("hype_without_substance")
    if any(marker in text for marker in _REASSURANCE_MARKERS):
        score += 60
        evidence.append("self_referential_reassurance")
    if any(marker in text for marker in _IRONY_EXPLICIT_MARKERS):
        score += 20
        evidence.append("explicit_irony_marker")
    return min(score, 100), evidence


def _score_audience_relatability(text: str) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    hits = [marker for marker in _RELATABILITY_MARKERS if marker in text]
    if hits:
        score += min(len(hits) * 20, 60)
        evidence.append("relatability_keyword")
    if _PERCENT_RE.search(text) and any(marker in text for marker in _RELATABILITY_MARKERS):
        score += 30
        evidence.append("statistic_about_people")
    return min(score, 100), evidence


def _score_visual_potential(text: str, *, has_image_candidate: bool | None) -> tuple[int, list[str]]:
    score = 20  # floor: every story can in principle get an illustrative meme image
    evidence: list[str] = []
    if has_image_candidate:
        score += 40
        evidence.append("existing_image_candidate_available")
    hits = [marker for marker in _VISUAL_MARKERS if marker in text]
    if hits:
        score += min(len(hits) * 20, 40)
        evidence.append("visual_keyword")
    return min(score, 100), evidence


def _score_topic_fit(category: EventCategory) -> tuple[int, list[str]]:
    score = _TOPIC_FIT_PRIOR.get(category, 40)
    return score, [f"topic_fit_prior:{category.value}"]


def _score_freshness(published_at: datetime | None, *, now: datetime | None = None) -> tuple[int, list[str]]:
    if published_at is None:
        return 30, ["freshness_unknown"]
    reference = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max((reference - published_at).total_seconds() / 3600.0, 0.0)
    if age_hours <= 24:
        return 100, ["fresh_within_24h"]
    if age_hours <= 72:
        return 60, ["fresh_within_72h"]
    return 30, ["stale_beyond_72h"]


def assess_meme_opportunity(
    news_event_title: str,
    news_event_content: str | None,
    news_event_category: EventCategory,
    news_event_published_at: datetime | None,
    research_output: dict[str, Any],
    *,
    has_image_candidate: bool | None = None,
    now: datetime | None = None,
) -> MemeOpportunityAssessment:
    """Pure, deterministic - see module docstring for the full LLM/cost boundary. Sensitivity is
    checked first and short-circuits every other signal (SENSITIVE_BLOCK is never overridden by
    a high composite score, mirroring services.fact_safety's own "hard rejection wins regardless"
    precedence discipline)."""
    research_facts = (
        [f for f in research_output.get("facts", []) if isinstance(f, str)]
        if isinstance(research_output.get("facts"), list) else []
    )
    research_gaps = (
        [g for g in research_output.get("gaps", []) if isinstance(g, str)]
        if isinstance(research_output.get("gaps"), list) else []
    )
    sufficiency_assessment = classify_source_sufficiency(
        news_event_title, news_event_content, research_facts, research_gaps,
    )
    sufficiency = sufficiency_assessment.sufficiency

    text = _normalize(f"{news_event_title} {news_event_content or ''} {' '.join(research_facts)}").lower()

    sensitivity_categories, sensitivity_evidence = detect_sensitive_categories(text)

    irony_score, irony_evidence = _score_irony_contrast(text)
    relatability_score, relatability_evidence = _score_audience_relatability(text)
    visual_score, visual_evidence = _score_visual_potential(text, has_image_candidate=has_image_candidate)
    topic_score, topic_evidence = _score_topic_fit(news_event_category)
    freshness_score, freshness_evidence = _score_freshness(news_event_published_at, now=now)

    composite = round(
        irony_score * _COMPOSITE_WEIGHTS["irony_contrast_score"]
        + relatability_score * _COMPOSITE_WEIGHTS["audience_relatability_score"]
        + visual_score * _COMPOSITE_WEIGHTS["visual_potential_score"]
        + topic_score * _COMPOSITE_WEIGHTS["topic_fit_score"]
        + freshness_score * _COMPOSITE_WEIGHTS["freshness_score"]
    )
    composite = max(0, min(100, composite))

    signals = MemeOpportunitySignals(
        irony_contrast_score=irony_score,
        audience_relatability_score=relatability_score,
        visual_potential_score=visual_score,
        topic_fit_score=topic_score,
        freshness_score=freshness_score,
        composite_score=composite,
    )
    evidence = [
        *sensitivity_evidence, *irony_evidence, *relatability_evidence, *visual_evidence,
        *topic_evidence, *freshness_evidence,
    ]

    if sensitivity_categories:
        return MemeOpportunityAssessment(
            policy_version=POLICY_VERSION,
            decision=MemeOpportunityDecision.SENSITIVE_BLOCK,
            signals=signals,
            sensitivity_categories=sensitivity_categories,
            source_sufficiency=sufficiency.value,
            reason_codes=[f"sensitive_category:{c}" for c in sensitivity_categories],
            evidence=evidence,
        )

    if sufficiency in _THIN_SUFFICIENCY:
        return MemeOpportunityAssessment(
            policy_version=POLICY_VERSION,
            decision=MemeOpportunityDecision.INSUFFICIENT_SOURCE,
            signals=signals,
            sensitivity_categories=[],
            source_sufficiency=sufficiency.value,
            reason_codes=[f"thin_source:{sufficiency.value}"],
            evidence=evidence,
        )

    reason_codes: list[str] = []
    if sufficiency == SourceSufficiency.UNKNOWN:
        reason_codes.append("source_sufficiency_unknown")

    if composite >= _READY_THRESHOLD:
        decision = MemeOpportunityDecision.MEME_READY
    elif composite >= _REVIEW_THRESHOLD:
        decision = MemeOpportunityDecision.REVIEW
        reason_codes.append("composite_below_ready_threshold")
    else:
        decision = MemeOpportunityDecision.NOT_SUITABLE
        reason_codes.append("composite_below_review_threshold")

    return MemeOpportunityAssessment(
        policy_version=POLICY_VERSION,
        decision=decision,
        signals=signals,
        sensitivity_categories=[],
        source_sufficiency=sufficiency.value,
        reason_codes=reason_codes,
        evidence=evidence,
    )


def apply_meme_opportunity_shadow(
    news_event_title: str,
    news_event_content: str | None,
    news_event_category: EventCategory,
    news_event_published_at: datetime | None,
    research_output: dict[str, Any],
    structured_output: dict[str, Any],
    *,
    has_image_candidate: bool | None = None,
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "quality" step, only after
    QualityCapability's own call (and Phase 15/17's own fact-safety/completeness hooks) already
    ran. Returns `structured_output` completely unchanged when `meme_opportunity_mode == "off"`
    (the default, byte-identical rollback path) - mirrors `services.channel_relevance.
    apply_channel_relevance_shadow()`'s own established merge convention exactly: purely
    additive, a single `"meme_opportunity"` key holding the full assessment."""
    if settings.meme_opportunity_mode == "off":
        return structured_output

    assessment = assess_meme_opportunity(
        news_event_title, news_event_content, news_event_category, news_event_published_at,
        research_output, has_image_candidate=has_image_candidate,
    )
    return {**structured_output, "meme_opportunity": assessment.model_dump(mode="json")}
