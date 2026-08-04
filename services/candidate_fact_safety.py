"""Candidate Fact Safety second pass (Phase 17 M4): a deterministic audit over one generated
candidate's title/body, reusing Phase 15 M5's own claim extraction rather than duplicating it
(docs/phase17_m4_beginner_friendly_copywriting_report.md).

Zero new LLM call - `services.fact_safety.evaluate_fact_safety()` already does deterministic
numeric/date/entity/quote claim extraction and support classification against the real
`NewsEvent`/Research evidence (Phase 15 M5); this module calls it directly for those claim types
and adds four new, narrow, regex-based detectors M5 never covered: causal-connector sentences,
superlative claims, market-positioning claims, and unhedged forecasts - none of which are
attempted as general NLP/claim-verification, all bucketed as flags for human review, not silent
auto-corrections (module's own explicit "these are flags, not verifications" discipline, disclosed
in `docs/phase17_m4_beginner_friendly_copywriting_report.md` §15's own limitations section).
"""
from __future__ import annotations

import re

from schemas.beginner_friendly import BeginnerFriendlyPlan
from schemas.candidate_fact_safety import (
    AuditSeverity,
    CandidateFactSafetyAudit,
    FactSafetyStatus,
)
from services.fact_safety import FactEvidence, evaluate_fact_safety

_SENTENCE_SPLIT_RE = re.compile(r"[.!?…]+(?:\s|$)")

_CAUSAL_RE = re.compile(
    r"\b(поэтому|это означает|в результате|следовательно|as a result|this means|that's why|"
    # M7.4.2 (docs/phase17_m7_4_2_causal_trigger_expansion_report.md): the connector-word triggers
    # above never covered the single most common Russian causal-VERB construction ("X led to Y"),
    # confirmed as a real false-negative gap in M7 discovery. Added only after M7.4.1's
    # hedge-awareness fix landed and was backtested - shipping this without that guard first would
    # have created large-scale new false positives on hedged sentences using this construction
    # (M7.4 discovery's own explicit sequencing requirement). Grammatical siblings of each
    # requested form are included (all genders/numbers of the same past-tense verb) - narrow,
    # explicit, hand-curated, never a general verb-conjugation rule.
    r"привел[оаи]\s+к|привёл\s+к|приводит\s+к|приводят\s+к|"
    r"вызвал[оаи]?|"
    r"стал[оаи]?\s+причиной|"
    r"caused|led\s+to|resulted\s+in)\b",
    re.IGNORECASE,
)
_SUPERLATIVE_RE = re.compile(
    r"\b(лучш\w*|крупнейш\w*|самый\w*|уникальн\w*|революционн\w*|"
    r"best|largest|leading|unique|unprecedented|revolutionary|groundbreaking|first-ever)\b",
    re.IGNORECASE,
)
_MARKET_CLAIM_RE = re.compile(
    r"\b(лидер рынка|популярн\w*|быстрорастущ\w*|market leader|widely used|growing rapidly|dominant)\b",
    re.IGNORECASE,
)
_FORECAST_RE = re.compile(
    r"\b(будет \w+|станет\w*|will become|is expected to|is set to|ожидается)\b", re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"\b(может|возможно|вероятно|по прогнозам|may|might|could|possibly|likely|потенциально)\b",
    re.IGNORECASE,
)
# M7.4.1 (docs/phase17_m7_4_1_causal_hedge_calibration_report.md): epistemic-limitation phrases
# that mark a sentence as expressing UNCERTAINTY about a claim, not asserting one - broader than
# `_HEDGE_RE` above (which only covers "may/might/possibly"-style probabilistic hedges). This also
# covers explicit "cannot be established"/"no evidence that"/"unclear whether" constructions that
# state the OPPOSITE of an unhedged claim without using any probabilistic hedge word at all. A
# fixed, small, explicit phrase list - never a general hedge classifier (this module's own
# repeated "no general NLP" instruction). Tolerates 0-2 intervening words between a trigger and its
# verb (e.g. "нельзя ОДНОЗНАЧНО утверждать") - a real, disclosed gap in the tighter, adjacency-only
# version this supersedes (docs/phase17_m7_2_quantity_classification_plan.md's own "Fix D",
# docs/phase17_m7_4_causal_calibration_discovery.md), found live on the real `847618cd` production
# case and never fixed until now.
#
# M7.4.2 (docs/phase17_m7_4_2_causal_trigger_expansion_report.md): added "не подтвержда\w*" (the
# ACTIVE verb form, "[данные] не подтверждают" - "[the data] does not confirm") alongside the
# existing "не подтвержден\w*" (PASSIVE participle only, "не подтверждено"/"не подтверждена") - a
# real false positive found via the 281-draft production backtest this milestone's own report
# requires ("Данные не подтверждают, что кампания стала причиной результата"), not assumed safe.
_EPISTEMIC_LIMITATION_RE = re.compile(
    r"\b(нельзя(?:\s+\w+){0,2}\s+(?:утвержда\w*|сказать|сделать\s+вывод|счита\w*\s+установленн\w*)|"
    r"неясно|непонятно|неизвестно|"
    r"нет\s+(?:доказательств|оснований|подтверждени\w*)|"
    r"основани\w*\s+нет|"
    r"не\s+подтвержден\w*|не\s+подтвержда\w*|пока\s+не\s+установлен\w*|нет\s+подтвержден\w*|"
    r"остаётся\s+неподтвержд\w*|остается\s+неподтвержд\w*|"
    r"cannot\s+be\s+considered\s+established|no\s+grounds\s+to\s+consider|"
    r"no\s+evidence\s+(?:that|for)|unclear\s+whether|it\s+is\s+unclear|"
    r"remains\s+unconfirmed|has\s+not\s+been\s+(?:confirmed|established))\b",
    re.IGNORECASE,
)
_DESCRIPTIVE_NOUN_RE = re.compile(
    r"\b(стартап|производитель|компания|разработчик|платформа|издатель|студия|фонд|"
    r"startup|maker|developer|publisher|manufacturer|platform)\w*\b", re.IGNORECASE,
)
_FILLER_PHRASE_RE = re.compile(
    r"\b(это важный шаг\w*|время покажет|эксперты отмечают|рынок продолжает развива\w*|"
    r"time will tell|experts note|important step|watch this space)\b", re.IGNORECASE,
)
_REPETITION_WORD_RE = re.compile(r"\w+")


def detect_filler_phrases(text: str) -> list[str]:
    """Pure, deterministic. A fixed, small, explicit phrase list (M4's own "anti-filler rules")
    - never a general fluency/quality classifier. An unlisted filler phrase simply is not
    caught; this is a narrow, disclosed limitation, not a general filler detector."""
    return [m.group(0) for m in _FILLER_PHRASE_RE.finditer(text)]


def detect_repetition(text: str) -> list[str]:
    """Pure, deterministic. Flags a pair of sentences that share a high fraction of their own
    distinct words (>= 70% overlap, by the shorter sentence's own word count) - a narrow,
    explicit lexical-overlap signal, never a semantic-similarity model. Two sentences can restate
    the same idea in sufficiently different words to escape this check; that is a disclosed
    limitation, not a claim of completeness."""
    sentences = _split_sentences(text)
    flags: list[str] = []
    word_sets = [
        {w.lower() for w in _REPETITION_WORD_RE.findall(s) if len(w) > 3} for s in sentences
    ]
    for i, words_a in enumerate(word_sets):
        if not words_a:
            continue
        for j in range(i + 1, len(word_sets)):
            words_b = word_sets[j]
            if not words_b:
                continue
            overlap = len(words_a & words_b) / max(1, min(len(words_a), len(words_b)))
            if overlap >= 0.7:
                flags.append(f"repetition: {sentences[i][:60]!r} ~ {sentences[j][:60]!r}")
    return flags


def _split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]


def _scan_qualitative_flags(candidate_body: str) -> list[str]:
    """Pure. Returns causal/superlative/market/unhedged-forecast flags, one per matching
    sentence - never a claim about whether the underlying assertion is true or false, only that
    it uses a pattern this audit cannot itself verify and a human should look at."""
    flags: list[str] = []
    for sentence in _split_sentences(candidate_body):
        # M7.4.1: a causal-connector sentence that also expresses epistemic uncertainty
        # ("нельзя утверждать", "неясно", "нет доказательств"...) is a hedge, not an unhedged
        # causal assertion - excluded here, at the raw-detector level, mirroring
        # `_FORECAST_RE`'s own existing "and not _HEDGE_RE.search(sentence)" pattern below, which
        # the causal check never had until now (docs/phase17_m7_4_1_causal_hedge_calibration_
        # report.md). The calibration layer's own `_suppress_hedge_language()` (services/
        # fact_safety_calibration.py) remains as a second, independent safety net for any
        # causal_flags list constructed directly rather than produced by this function.
        if _CAUSAL_RE.search(sentence) and not _EPISTEMIC_LIMITATION_RE.search(sentence):
            flags.append(f"causal_connector: {sentence[:80]}")
        if _SUPERLATIVE_RE.search(sentence):
            flags.append(f"superlative_claim: {sentence[:80]}")
        if _MARKET_CLAIM_RE.search(sentence):
            flags.append(f"market_claim: {sentence[:80]}")
        if _FORECAST_RE.search(sentence) and not _HEDGE_RE.search(sentence):
            flags.append(f"unhedged_forecast: {sentence[:80]}")
    return flags


def _scan_definition_flags(candidate_title: str, candidate_body: str, plan: BeginnerFriendlyPlan | None) -> list[str]:
    """Pure. Flags any term/subject the plan explicitly marked `unexplainable` (no safe evidence
    or glossary entry existed) that nonetheless appears to be explained in the candidate text -
    a direct, deterministic check against this milestone's own "never invent an explanation for
    an unlisted term" rule."""
    if plan is None or not plan.unexplainable_terms:
        return []
    text = f"{candidate_title} {candidate_body}"
    flags: list[str] = []
    for term in plan.unexplainable_terms:
        window_pattern = re.compile(rf"(.{{0,40}}\b{re.escape(term)}\b.{{0,40}})", re.IGNORECASE)
        match = window_pattern.search(text)
        if match and _DESCRIPTIVE_NOUN_RE.search(match.group(1)):
            flags.append(f"unsupported_definition: {term}")
    return flags


def evaluate_candidate_fact_safety(
    candidate_title: str,
    candidate_body: str,
    news_event_title: str,
    news_event_content: str | None,
    research_facts: list[str],
    plan: BeginnerFriendlyPlan | None = None,
) -> CandidateFactSafetyAudit:
    """Pure. No I/O, no LLM call, deterministic: identical inputs always produce an identical
    output."""
    evidence = FactEvidence(
        source_title=news_event_title, source_content=news_event_content, source_url=None,
        research_facts=research_facts,
    )
    fact_safety_result = evaluate_fact_safety(candidate_title, candidate_body, evidence)

    numeric_flags: list[str] = []
    entity_flags: list[str] = []
    for finding in fact_safety_result["findings"]:
        label = f"{finding['support']}:{finding['claim']}"
        # M7.2: metric_quantity (a resolved unit+amount - tokens/parameters/users/requests/calls/
        # operations) is fundamentally numeric, same bucket as money/percentage/date.
        # generic_quantity (an unresolvable magnitude - M7 discovery's own class #1 root cause,
        # now severity-capped at medium instead of forced into "money") is also numeric in kind,
        # just lower-confidence - bucketed here too rather than with entity/quote.
        if finding["type"] in ("money", "percentage", "date", "metric_quantity", "generic_quantity"):
            numeric_flags.append(label)
        else:  # entity, quote
            entity_flags.append(label)

    causal_flags = _scan_qualitative_flags(candidate_body)
    definition_flags = _scan_definition_flags(candidate_title, candidate_body, plan)

    unsupported_claim_flags = [*numeric_flags, *entity_flags, *definition_flags]

    reason_codes = []
    high_severity_unsupported = any(
        f["type"] in ("money", "percentage", "date", "quote", "metric_quantity")
        and f["support"] == "unsupported" and f["severity"] == "high"
        for f in fact_safety_result["findings"]
    )
    any_unsupported = any(f["support"] == "unsupported" for f in fact_safety_result["findings"])
    any_uncertain = any(f["support"] == "uncertain" for f in fact_safety_result["findings"])

    if definition_flags:
        reason_codes.append("unsupported_definition_present")
        status = FactSafetyStatus.FAIL
        severity = AuditSeverity.HIGH
    elif high_severity_unsupported:
        reason_codes.append("high_severity_unsupported_claim")
        status = FactSafetyStatus.FAIL
        severity = AuditSeverity.HIGH
    elif any_unsupported:
        reason_codes.append("unsupported_claim_present")
        status = FactSafetyStatus.REVIEW
        severity = AuditSeverity.MEDIUM
    elif any_uncertain or causal_flags:
        if causal_flags:
            reason_codes.append("qualitative_claim_needs_review")
        if any_uncertain:
            reason_codes.append("uncertain_claim_present")
        status = FactSafetyStatus.REVIEW
        severity = AuditSeverity.LOW
    else:
        status = FactSafetyStatus.PASS
        severity = None

    return CandidateFactSafetyAudit(
        status=status,
        supported_claim_count=fact_safety_result["supported"],
        unsupported_claim_flags=unsupported_claim_flags,
        numeric_flags=numeric_flags,
        entity_flags=entity_flags,
        causal_flags=causal_flags,
        definition_flags=definition_flags,
        severity=severity,
        reason_codes=reason_codes,
    )
