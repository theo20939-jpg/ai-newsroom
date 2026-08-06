"""Content Quality Gates (Phase 18.10 M6/M7): deterministic, narrow, hand-curated checks over a
generated draft - never an LLM call, mirroring services/fact_safety.py's/
services/story_memory.py's own established "deterministic, no ML" convention for this codebase.

Each gate is a small, independently-testable pure function returning True (pass) or False (fail).
`evaluate_content_quality_gates()` combines them into one report - the aggregator, not a new
enforcement mechanism; the caller (services/content_draft_service.py) decides what to do with a
failing gate, exactly like services/content_draft_service.py::check_no_hashtags() already does
for its own, narrower check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.quote_verification import verify_quote
from services.text_normalization import fuzzy_phrase_contains, normalize_loose, token_overlap_ratio

# Hand-curated, narrow lexicon - English + Russian, the two languages this corpus actually uses
# (docs/phase18_10_editorial_intelligence_report.md's own disclosed scope). Never a general
# sentiment/quality model - a fixed list, same convention as services/story_memory.py's own topic
# keyword tables.
_GENERIC_FILLER_PHRASES: tuple[str, ...] = (
    "this is an important development",
    "this is a significant development",
    "time will tell",
    "only time will tell",
    "как сообщается",
    "это важное событие",
    "это значимое событие",
    "покажет время",
)

_UNSUPPORTED_SUPERLATIVES: tuple[str, ...] = (
    "the best in the world",
    "unmatched",
    "like nothing before",
    "revolutionary",
    "first of its kind",
    "never been done before",
    "лучший в мире",
    "не имеет аналогов",
    "первый в мире",
    "революционный",
)

_MIN_WHY_IT_MATTERS_CHARS = 20
_HEADLINE_BODY_REPETITION_THRESHOLD = 0.8
_UPDATE_ROOT_REPETITION_THRESHOLD = 0.6
_WHY_IT_MATTERS_VS_WHAT_HAPPENED_REPETITION_THRESHOLD = 0.75


@dataclass(frozen=True)
class QualityGateReport:
    """One boolean field per gate (True = passed). `failed_gates` is a convenience list of the
    gate names that did NOT pass, derived from the same booleans - never a second source of
    truth."""

    # Hashtag presence is deliberately NOT one of this report's gates - it is already a hard,
    # unconditional, separately-enforced check (services.content_draft_service.check_no_hashtags,
    # Phase 18.10 M4), raised as a ValueError before a draft is ever persisted. Including it here
    # too would create two divergent sources of truth for the same check.
    no_headline_body_repetition: bool = True
    no_duplicate_source_headline: bool = True
    no_generic_filler: bool = True
    no_unsupported_competitive_claim: bool = True
    why_it_matters_present: bool = True
    quote_traceable: bool = True
    quote_has_attribution: bool = True
    blockquote_well_formed: bool = True
    update_not_repeating_root: bool = True
    failed_gates: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failed_gates


def check_no_headline_body_repetition(title: str, body: str) -> bool:
    """Fails when the body opens by simply restating the title - editorial value requires the
    body to add something beyond the headline. Checked against only the body's own first
    sentence-ish prefix (up to the first period, or the whole body if short), not the whole body,
    since a long body legitimately mentioning title words later is not repetition."""
    if not title or not body:
        return True
    prefix = body.split(".")[0]
    return token_overlap_ratio(title, prefix) < _HEADLINE_BODY_REPETITION_THRESHOLD


def check_no_duplicate_source_headline(body: str, source_title: str | None) -> bool:
    """Fails when the original source title (typically a different language than the target
    output) appears verbatim inside the generated body - a duplicated, untranslated headline
    leaking through, not a translated, editorially-rewritten one."""
    if not source_title or not body:
        return True
    return not fuzzy_phrase_contains(source_title, body)


def check_no_generic_filler(text: str) -> bool:
    normalized = normalize_loose(text)
    return not any(phrase in normalized for phrase in _GENERIC_FILLER_PHRASES)


def check_no_unsupported_competitive_claim(text: str) -> bool:
    normalized = normalize_loose(text)
    return not any(phrase in normalized for phrase in _UNSUPPORTED_SUPERLATIVES)


def check_why_it_matters_present(why_it_matters: str | None, what_happened: str | None = None) -> bool:
    """Fails when empty/near-empty, or when it's just a restatement of what_happened rather than
    genuine editorial interpretation."""
    if not why_it_matters or len(why_it_matters.strip()) < _MIN_WHY_IT_MATTERS_CHARS:
        return False
    if what_happened and token_overlap_ratio(why_it_matters, what_happened) >= _WHY_IT_MATTERS_VS_WHAT_HAPPENED_REPETITION_THRESHOLD:
        return False
    return True


def check_quote_traceable(quote_text: str | None, source_content: str | None) -> bool:
    """True (pass) whenever there is no quote at all - only a *present* quote can be
    untraceable. Delegates the actual verification to services.quote_verification.verify_quote()
    - never a second, divergent implementation."""
    if not quote_text:
        return True
    return verify_quote(quote_text, source_content)


def check_quote_has_attribution(quote_text: str | None, speaker: str | None) -> bool:
    """True whenever there is no quote at all. A present quote must have a non-empty, non-generic
    speaker - "someone"/"a person"/empty string never counts as real attribution."""
    if not quote_text:
        return True
    if not speaker or not speaker.strip():
        return False
    return normalize_loose(speaker) not in {"someone", "a person", "unknown"}


_BLOCKQUOTE_OPEN_RE = re.compile(r"<blockquote>")
_BLOCKQUOTE_CLOSE_RE = re.compile(r"</blockquote>")


def check_blockquote_well_formed(rendered_html: str) -> bool:
    """Balanced open/close tag counts - a narrow, deterministic structural check, not a full HTML
    parser (matches this codebase's own established "small, explicit, narrow" convention)."""
    return len(_BLOCKQUOTE_OPEN_RE.findall(rendered_html)) == len(_BLOCKQUOTE_CLOSE_RE.findall(rendered_html))


def check_update_not_repeating_root(body: str, is_update: bool, root_body: str | None) -> bool:
    """True whenever this isn't an update at all, or the root body is unknown. For a genuine
    update with a known root, fails when the new body is mostly the same text as the root - an
    update must contain the delta, not a full rewrite of the original post."""
    if not is_update or not root_body:
        return True
    return token_overlap_ratio(body, root_body) < _UPDATE_ROOT_REPETITION_THRESHOLD


def evaluate_content_quality_gates(
    *,
    title: str,
    body: str,
    why_it_matters: str | None = None,
    what_happened: str | None = None,
    source_title: str | None = None,
    quote_text: str | None = None,
    quote_speaker: str | None = None,
    source_content: str | None = None,
    rendered_html: str | None = None,
    is_update: bool = False,
    root_body: str | None = None,
) -> QualityGateReport:
    """Pure. Combines every individual gate above into one report - the caller decides what to
    do with a failing gate (reject, log, route to review); this function only assesses."""
    gates = {
        "no_headline_body_repetition": check_no_headline_body_repetition(title, body),
        "no_duplicate_source_headline": check_no_duplicate_source_headline(body, source_title),
        "no_generic_filler": check_no_generic_filler(f"{body}\n{why_it_matters or ''}"),
        "no_unsupported_competitive_claim": check_no_unsupported_competitive_claim(f"{body}\n{why_it_matters or ''}"),
        "why_it_matters_present": check_why_it_matters_present(why_it_matters, what_happened),
        "quote_traceable": check_quote_traceable(quote_text, source_content),
        "quote_has_attribution": check_quote_has_attribution(quote_text, quote_speaker),
        "update_not_repeating_root": check_update_not_repeating_root(body, is_update, root_body),
    }
    if rendered_html is not None:
        gates["blockquote_well_formed"] = check_blockquote_well_formed(rendered_html)

    failed = [name for name, passed in gates.items() if not passed]
    return QualityGateReport(
        no_headline_body_repetition=gates["no_headline_body_repetition"],
        no_duplicate_source_headline=gates["no_duplicate_source_headline"],
        no_generic_filler=gates["no_generic_filler"],
        no_unsupported_competitive_claim=gates["no_unsupported_competitive_claim"],
        why_it_matters_present=gates["why_it_matters_present"],
        quote_traceable=gates["quote_traceable"],
        quote_has_attribution=gates["quote_has_attribution"],
        blockquote_well_formed=gates.get("blockquote_well_formed", True),
        update_not_repeating_root=gates["update_not_repeating_root"],
        failed_gates=failed,
    )
