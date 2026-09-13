"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S9): a real, generic subject/entity extractor for
`MediaIntent` - the fix for the Founder audit finding that production `MediaIntent` construction
was too weak compared with test fixtures.

Deliberately SEPARATE from `services.editorial_pipeline.content._extract_subject_from_title()` -
that function's job is DATA-metric-LABEL construction (S8/S9's own Maxus-class defect fix) and has
its own passing test suite this phase must not regress (S27's own "do not derail into a DATA-design
phase"); this module's job is MEDIA-SUBJECT-IDENTITY extraction for wrong-subject-image prevention,
a related but distinct question with its own, deliberately broader matching rules. Touching the
shared old regex would have risked exactly the kind of DATA regression S27 forbids - a new, purpose-
built extractor avoids that risk entirely while still closing the real gap.

The old, still-untouched `_extract_subject_from_title()` used a single regex requiring a trailing
space-separated digit (`[A-Z][a-zA-Z]*\\s+\\d+`) - it structurally cannot match "iPhone 17" (`iPhone`
itself starts with a lowercase `i`), "GPT-6" (hyphen, not space, before the digit), "Dario Amodei"
(no digit at all), "OpenAI" (no digit), or "foldable iPhone" (no digit). This module fixes exactly
that, deterministically, with no hardcoded brand/company/person name anywhere in this file (S9's own
explicit "must not be hard-coded around Apple/iPhone" requirement) - it recognizes SHAPES (a brand-
style token, optionally versioned; a short proper-noun run), never specific vocabulary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A "brand-style" token: EITHER a plain capitalized Latin word ("Maxus", "Model"), a lowercase-then-
# uppercase mixed-case word ("iPhone", "eBay", "macOS"), or a short all-caps acronym ("GPT", "AI",
# "GPU") - the common shapes a product/company name takes in Latin script embedded in otherwise
# non-Latin (e.g. Russian) news prose. Never a plain lowercase word (too likely to catch ordinary
# vocabulary) and never a single uppercase letter alone (too likely to catch an abbreviation/unit).
_BRAND_TOKEN = r"(?:[A-Z][a-zA-Z]*|[a-z]+[A-Z][a-zA-Z]*|[A-Z]{2,})"

# A version/model-number suffix: a space or hyphen, then a numeral (optionally dotted, optionally
# one trailing letter) - "17", "9", "6", "5.1", "5s". Requires an explicit separator so "iPhone17"
# (no separator, unlikely in real prose) is deliberately NOT matched - avoiding a false-positive
# glued-together match is preferred over catching an unrealistic edge case.
_VERSION_SUFFIX = r"[-\s]\d+(?:\.\d+)*[A-Za-z]?"

_MODEL_WITH_VERSION_RE = re.compile(rf"\b({_BRAND_TOKEN})({_VERSION_SUFFIX})\b")
_BARE_BRAND_TOKEN_RE = re.compile(rf"\b{_BRAND_TOKEN}\b")
# A short run of 2-3 plain, ordinary-capitalized words (never a mixed-case/acronym brand token,
# which the bare-brand pattern above already owns) - the common shape of a person's full name or a
# two-word company/place name in Latin-script news prose ("Dario Amodei", "Apple Park").
_PROPER_NOUN_RUN_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")

# Generic vocabulary that happens to satisfy the brand-token shape but is never a real subject
# identity on its own - bounded, small, purely structural (units/common report-prose openers), NOT
# a brand/company/person denylist (S9's own "no hardcoded brand names" applies in the other
# direction too: this set never excludes a real product name, only generic non-identity tokens).
_GENERIC_NON_SUBJECT_TOKENS = frozenset({"AI", "USD", "EUR", "RUB", "CEO", "CTO", "PR", "IT"})


@dataclass(frozen=True)
class ExtractedMediaSubject:
    """One extracted subject-identity candidate. `versioned_form`/`brand_form` are both set only
    for the model-with-version tier (e.g. `versioned_form="iPhone 17"`, `brand_form="iPhone"`) -
    the two-tier split IS the point: `brand_form` is a CATEGORY signal (any iPhone), `versioned_
    form` is the specific, distinguishing qualifier (this exact iPhone) - matching `services.
    editorial_pipeline.subject_match.classify_subject_match()`'s own required/category-terms model
    exactly, so a caller can feed `model_name=versioned_form, product_name=brand_form` directly."""

    versioned_form: str | None
    brand_form: str | None
    proper_noun_run: str | None

    @property
    def is_informative(self) -> bool:
        """S32's own definition verbatim: "does the intent contain enough truthful subject identity
        to prevent obvious wrong-subject media from winning" - true whenever ANY real identity
        signal was found, regardless of which tier."""
        return bool(self.versioned_form or self.brand_form or self.proper_noun_run)


def extract_media_subject(title: str) -> ExtractedMediaSubject | None:
    """Deterministic, bounded (single regex pass per tier, no backtracking risk beyond what a
    fixed-width alternation already bounds), generic. Returns `None` only when title carries no
    recognizable Latin-script brand-token or proper-noun-run at all (a genuinely subject-less/
    concept-only story, e.g. "AI regulation debate continues") - never fabricates one."""
    versioned_matches = _MODEL_WITH_VERSION_RE.findall(title)
    if versioned_matches:
        brand, suffix = versioned_matches[-1]
        versioned_form = f"{brand}{suffix}".strip()
        return ExtractedMediaSubject(versioned_form=versioned_form, brand_form=brand, proper_noun_run=None)

    proper_noun_matches = _PROPER_NOUN_RUN_RE.findall(title)
    proper_noun_run = max(proper_noun_matches, key=len) if proper_noun_matches else None
    proper_noun_words = frozenset(proper_noun_run.split()) if proper_noun_run else frozenset()

    bare_brand_matches = [
        m for m in _BARE_BRAND_TOKEN_RE.findall(title)
        if m not in _GENERIC_NON_SUBJECT_TOKENS and not m.isupper()  # a bare all-caps acronym alone
        # (no version) is too weak/ambiguous a signal on its own (S9's own conservative-default
        # spirit) - a mixed-case brand word ("iPhone") or a real Titlecase word is still accepted.
        and m not in proper_noun_words  # never re-surface a single word that is merely a FRAGMENT
        # of the fuller proper-noun run already found (e.g. "Amodei" out of "Dario Amodei") as if
        # it were a separate, competing brand/company signal - the fuller run is strictly more
        # informative and must not be silently discarded in favor of one of its own component words.
    ]

    brand_form = bare_brand_matches[-1] if bare_brand_matches else None

    if brand_form is None and proper_noun_run is None:
        return None
    return ExtractedMediaSubject(versioned_form=None, brand_form=brand_form, proper_noun_run=proper_noun_run)
