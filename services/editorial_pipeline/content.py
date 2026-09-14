"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S8/S9): structured content, produced from an
`EvidencePack` BEFORE any rendering happens - never reconstructed from final generated prose by a
renderer (S8's own explicit rule).

This module's `build_structured_data_content()` is the concrete fix for the "Maxus class" defect
(S9): `services.presentation_director._find_data_candidate()` (kept, unmodified, as the legacy
grounding/cross-verification step - it is genuinely good at answering "which number in the copy is
independently confirmed by a Research fact," which is not the defective part) is reused only to
find WHICH claim grounds a DATA card. This module then builds `metric_label`/`subject` as clean,
CONSTRUCTED fields - never a stripped remainder of the original fact sentence, which was the exact
mechanism that produced "Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн
рублей)." (the real, reproduced defect - see tests/test_editorial_pipeline_data_content.py's own
Maxus 9 replay, built from the real, independently-fetched article text, not a fabricated example).

Disclosed, bounded scope (S8's own "legacy extractors may temporarily exist... marked and measured
for later removal" allowance): `_extract_subject_from_title()` and `_classify_metric_kind()` below
are deterministic heuristics, not true NLU or a structured-generation LLM call - a future phase
should replace them with the copywriting capability emitting `metric_value`/`metric_unit`/
`metric_label`/`subject` directly as first-class structured output fields (S8's own stated ideal).
This phase's own scope is the architectural boundary (structured content is decided before
rendering, by one shared module, never by a renderer) and the specific label-corruption defect, not
a full LLM-prompt redesign - see the report's own "remaining intentional limitations" section.
"""
from __future__ import annotations

import re

from services.editorial_pipeline.contracts import (
    EvidenceClaim,
    EvidencePack,
    StructuredDataContent,
    StructuredQuoteContent,
)
from services.presentation_director import (
    DataCandidate,
    QuoteCandidate,
    _find_data_candidate,  # legacy grounding step, reused deliberately - see module docstring
    _is_change_unit,  # the SAME change-vs-magnitude classification the legacy extractor itself
    # already uses (§1 there) - reused, not re-decided, so a percentage/change unit is recognized
    # identically in both places.
)

# A brand/model token run: a capitalized Latin word immediately followed by a numeral (e.g. "Maxus
# 9", "iPhone 17") - the common shape of a product/model name embedded in Russian-language news
# prose. Deliberately excludes a bare capitalized word with no trailing number (too likely to catch
# an unrelated proper noun) and a bare number with no preceding capitalized word (would catch a
# trailing year on its own, e.g. "2027" in "Maxus 9 2027").
_MODEL_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z]*\s+\d+(?:\.\d+)?\b")

# TELEGRAM-DATA-SEMANTIC-OVERFLOW-HOTFIX-1: a bounded, GENERIC (never brand-specific - no company/
# product name is listed anywhere in this module) all-caps acronym shape - "ASML", "NASA", "OPEC" -
# the common shape of an acronym-only organization name in Latin script embedded in Russian prose.
# Mirrors `services.editorial_pipeline.subject_extraction`'s own judgment that a bare all-caps
# token is too weak/ambiguous a signal ALONE - so it is only ever accepted as a DATA subject when
# the SAME acronym is independently grounded in BOTH the title AND the cross-verified research
# fact, the same "grounded in two independent places" discipline `_find_data_candidate()` itself
# already applies to the numeric value (never invents a subject from title alone).
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")
# Structural, not a brand/company denylist (same spirit as subject_extraction.py's own
# `_GENERIC_NON_SUBJECT_TOKENS`) - generic acronyms that are never themselves a real subject
# identity, so a match in both title and fact is never accepted as one.
_GENERIC_ACRONYMS = frozenset({"AI", "EU", "US", "UK", "USD", "EUR", "GPU", "CPU", "CEO", "CTO", "IPO", "API", "OS"})

_PRICE_WORDS = ("цена", "цену", "цены", "стоимост")
_STARTING_WORDS = ("начина", "стартует", "стартов")
_RANGE_WORD = "запас хода"
_CHARGE_WORD = "заря"
# A generic Russian "market" stem (рынок/рынка/рынке/рынку/рынков) - never a specific
# company/product - used only together with an already-grounded change/percentage unit to
# recognize a market-share metric (§6 of the hotfix brief).
_MARKET_WORD_STEM = "рынк"

# TELEGRAM-DATA-SEMANTIC-OVERFLOW-HOTFIX-1: extends `services.presentation_director._CURRENCY_WORD`
# LOCALLY, in this new pipeline's own module - NOT by editing that shared constant directly. Same
# precedent already established by `services.editorial_pipeline.language_qa._EXTENDED_CURRENCY_WORD`
# for the identical "юань was never a recognized currency word" gap: the shared production constant
# must stay byte-for-byte frozen for the still-live legacy V8 renderer path (S18's own
# EXISTING_V8_MEDIA_BACKED_PIXEL_DIFF=0 freeze), so this vocabulary gap is fixed only here.
_EXTENDED_CURRENCY_WORD = r"(?:руб(?:л\w*|\.)?|доллар\w*|usd|eur|евро|₽|\$|юан\w*|yuan|rmb|cny|¥)"
_CURRENCY_TOKEN_RE = re.compile(_EXTENDED_CURRENCY_WORD, re.IGNORECASE)


def _extract_subject_from_title(title: str, fact: str) -> str | None:
    """Never fabricates a subject when none is findable - returns None, and the caller must then
    fall back to a safe, kind-only label (NEVER the whole fact sentence - the exact
    "ПОКАЗАТЕЛЬ ASML КОНТРОЛИРУЕТ ПРИМЕРНО РЫНКА..." defect class this replaces, see
    `build_structured_data_content()`)."""
    matches = _MODEL_NAME_RE.findall(title)
    if matches:
        return matches[-1]
    title_acronyms = {a for a in _ACRONYM_RE.findall(title) if a not in _GENERIC_ACRONYMS}
    if not title_acronyms:
        return None
    for acronym in _ACRONYM_RE.findall(fact):
        if acronym in title_acronyms and acronym not in _GENERIC_ACRONYMS:
            return acronym
    return None


def _classify_metric_kind(fact_lower: str, unit: str) -> str:
    """A small, honest, disclosed classifier (see module docstring) - never invents a kind beyond
    what the fact text itself signals; "Показатель" (generic "metric") is the deliberate, safe
    fallback rather than guessing a more specific one. `unit` is the grounded legacy unit (never
    the display-only full_unit) - only used to recognize a market-share metric (§6): a grounded
    change/percentage signal together with a generic "market" stem, never company-specific."""
    if any(w in fact_lower for w in _PRICE_WORDS):
        return "Стартовая цена" if any(w in fact_lower for w in _STARTING_WORDS) else "Цена"
    if _RANGE_WORD in fact_lower:
        return "Запас хода"
    if _CHARGE_WORD in fact_lower:
        return "Время зарядки"
    if _is_change_unit(unit) and _MARKET_WORD_STEM in fact_lower:
        return "Доля рынка"
    return "Показатель"


def _extract_full_unit_text(fact: str, value: str, legacy_unit: str) -> str:
    """TELEGRAM-DATA-SEMANTIC-OVERFLOW-HOTFIX-1: the real fix for the ASML-class overflow defect
    ("94% рынка литографических сканеров..." becoming the unit). The old version of this function
    scanned up to 40 ARBITRARY characters of trailing prose after `value` - exactly the mechanism
    that produced the overflow. This version never does that:

    `legacy_unit` (`services.presentation_director._find_data_candidate()`'s own grounded,
    cross-verified output) is always the base authority.
      - A percentage/change unit (`%`, "процент*") is already complete on its own and NEVER absorbs
        a following subject noun - returned unchanged, no scan at all.
      - A magnitude unit (тыс/млн/млрд/k) that the legacy extractor already paired with a currency
        word (`_extend_span_with_currency`, e.g. "млн долларов") is already complete - returned
        unchanged.
      - Only a magnitude unit NOT already paired with a currency word may gain ONE bounded,
        semantically-recognized currency token immediately following its own occurrence in `fact`
        (the real, disclosed "юань" gap - see this module's `_EXTENDED_CURRENCY_WORD` docstring) -
        never more than that one token, never arbitrary trailing text."""
    if _is_change_unit(legacy_unit):
        return legacy_unit
    if _CURRENCY_TOKEN_RE.search(legacy_unit):
        return legacy_unit
    match = re.search(re.escape(value) + r"\.?\s*" + re.escape(legacy_unit) + r"\.?", fact, re.IGNORECASE)
    if match is None:
        return legacy_unit
    tail = fact[match.end():]
    currency_match = re.match(rf"\s+({_EXTENDED_CURRENCY_WORD})", tail, re.IGNORECASE)
    if currency_match is None:
        return legacy_unit
    return f"{legacy_unit} {currency_match.group(1).rstrip('.').lower()}"


def build_structured_data_content(
    *, title: str, main_body: str | None, evidence: EvidencePack,
) -> StructuredDataContent | None:
    """Returns None exactly when the legacy grounding step (`_find_data_candidate`) finds nothing
    grounded in both the copy and a real Research fact - never fabricates a DATA card from
    ungrounded numbers. `source_claim_id` always resolves to a real `EvidenceClaim` in `evidence`;
    if the grounded fact string cannot be matched back to one (should not happen - the grounding
    step reads from the same `evidence.research_facts`), this also returns None rather than
    emitting a claim-less structured content object."""
    legacy: DataCandidate | None = _find_data_candidate(title, main_body, list(evidence.research_facts))
    if legacy is None:
        return None
    claim = next((c for c in evidence.claims if c.raw_fact_text.strip() == legacy.evidence_fact.strip()), None)
    if claim is None:
        return None

    fact_lower = legacy.evidence_fact.lower()
    subject = _extract_subject_from_title(title, legacy.evidence_fact)
    kind = _classify_metric_kind(fact_lower, legacy.unit)
    # §5 of the hotfix brief: a subject that cannot be confidently, GENERICALLY determined must
    # NEVER fall back to `legacy.label` (a stripped remainder of the whole fact sentence - the
    # exact "ПОКАЗАТЕЛЬ ASML КОНТРОЛИРУЕТ ПРИМЕРНО РЫНКА..." defect). A safe, kind-only label
    # ("Доля рынка", never a malformed sentence) is strictly preferred.
    metric_label = f"{kind} {subject}" if subject else kind

    full_unit = _extract_full_unit_text(legacy.evidence_fact, legacy.value, legacy.unit)

    return StructuredDataContent(
        metric_value=legacy.value,
        metric_unit=full_unit,
        metric_label=metric_label,
        subject=subject or "",
        context_sentence=legacy.evidence_fact.strip(),
        comparison=None,
        delta=legacy.delta,
        delta_context=None,
        series=legacy.series,
        source_claim_id=claim.claim_id,
        source_fact=claim.raw_fact_text,
    )


def build_structured_quote_content(
    *, quote_candidate: QuoteCandidate, evidence: EvidencePack,
) -> StructuredQuoteContent | None:
    """Thin structuring wrapper around the existing, already-correct `QuoteCandidate` (services/
    presentation_director.py) - QUOTE never had the prose-reconstruction defect DATA had (a quote's
    text/speaker/role are already discrete fields, never regex-sliced from a paragraph), so this
    only adds evidence traceability, never changes quote extraction itself."""
    claim: EvidenceClaim | None = next(
        (c for c in evidence.claims if quote_candidate.text.strip() in c.raw_fact_text or c.raw_fact_text.strip() in quote_candidate.text),
        None,
    )
    if claim is None:
        return None
    return StructuredQuoteContent(
        quote=quote_candidate.text, speaker=quote_candidate.speaker, role=quote_candidate.role,
        context=None, source_claim_id=claim.claim_id,
    )
