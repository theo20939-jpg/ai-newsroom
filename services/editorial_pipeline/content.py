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
)

# A brand/model token run: a capitalized Latin word immediately followed by a numeral (e.g. "Maxus
# 9", "iPhone 17") - the common shape of a product/model name embedded in Russian-language news
# prose. Deliberately excludes a bare capitalized word with no trailing number (too likely to catch
# an unrelated proper noun) and a bare number with no preceding capitalized word (would catch a
# trailing year on its own, e.g. "2027" in "Maxus 9 2027").
_MODEL_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z]*\s+\d+(?:\.\d+)?\b")

_PRICE_WORDS = ("цена", "цену", "цены", "стоимост")
_STARTING_WORDS = ("начина", "стартует", "стартов")
_RANGE_WORD = "запас хода"
_CHARGE_WORD = "заря"


def _extract_subject_from_title(title: str) -> str | None:
    """Never fabricates a subject when none is findable - returns None, and the caller falls back
    to the fact's own evidence_fact text as both subject and label source (still never a mangled
    stripped remainder - see `build_structured_data_content()`)."""
    matches = _MODEL_NAME_RE.findall(title)
    return matches[-1] if matches else None


def _classify_metric_kind(fact_lower: str) -> str:
    """A small, honest, disclosed classifier (see module docstring) - never invents a kind beyond
    what the fact text itself signals; "Показатель" (generic "metric") is the deliberate, safe
    fallback rather than guessing a more specific one."""
    if any(w in fact_lower for w in _PRICE_WORDS):
        return "Стартовая цена" if any(w in fact_lower for w in _STARTING_WORDS) else "Цена"
    if _RANGE_WORD in fact_lower:
        return "Запас хода"
    if _CHARGE_WORD in fact_lower:
        return "Время зарядки"
    return "Показатель"


def _extract_full_unit_text(fact: str, value: str) -> str | None:
    """The actual fix for the truncation defect: rather than relying on the legacy `_safe_label`'s
    span-stripping (which can leave a preposition stranded next to the unit, or drop the unit's own
    currency word - both confirmed via direct reproduction against the real Maxus 9 article text),
    this independently re-scans the fact for the text immediately following `value`, up to the
    next parenthesis or a real sentence boundary - so "290 тыс. юаней" is captured whole, never as
    a bare "290" with its unit orphaned elsewhere."""
    match = re.search(re.escape(value) + r"\.?\s*([^()]{1,40})", fact)
    if match is None:
        return None
    unit_text = match.group(1)
    # Stop at the first real sentence-ending period (a period followed by a space and an uppercase
    # letter, or end of string) - never at an abbreviation period like "тыс." mid-phrase.
    boundary = re.search(r"\.(?:\s+[А-ЯA-Z]|\s*$)", unit_text)
    if boundary is not None:
        unit_text = unit_text[: boundary.start()]
    return unit_text.strip(" .,")


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

    subject = _extract_subject_from_title(title) or legacy.label
    fact_lower = legacy.evidence_fact.lower()
    metric_label = f"{_classify_metric_kind(fact_lower)} {subject}".strip()

    full_unit = _extract_full_unit_text(legacy.evidence_fact, legacy.value) or legacy.unit

    return StructuredDataContent(
        metric_value=legacy.value,
        metric_unit=full_unit,
        metric_label=metric_label,
        subject=subject,
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
