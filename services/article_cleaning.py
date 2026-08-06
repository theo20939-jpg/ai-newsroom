"""Phase 19 M2: deterministic article cleaning (docs/phase19_m0_audit.md).

Sits between services/article_acquisition.py's raw extraction and services/evidence_package.py's
EvidencePackage assembly: `raw_extracted_text -> clean_extracted_text() -> cleaned_text`, persisted
directly on the same news_event_article_acquisitions row (never reconstructed on a later read).

Every rule is a small, independently-testable, deterministic function operating on the already
line-separated blocks services/article_acquisition.py::extract_raw_text() produces (one block per
HTML text node - this preserves enough structure for block-level heuristics without a second HTML
parse). Conservative by design: a rule that would remove a majority of the article's own blocks is
skipped rather than applied, on the theory that a rule confidently firing on real article
paragraphs is itself evidence the rule mismatched this particular page - never claims perfect
main-content extraction (docs/phase19_m0_audit.md's own disclosed scope).

Reuses services/text_normalization.py for the one rule that needs fuzzy text comparison (repeated
headline) - no new NLP machinery, matching this module's own "deliberately not a general NLP
engine" convention.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.text_normalization import normalize_loose, token_overlap_ratio

CLEANING_VERSION = "1"

# Hand-curated, narrow lexicons - English + Russian, the two languages this corpus actually uses
# (matches services/content_quality_gates.py's own established bilingual-lexicon convention).
# Deliberately separate lists from content_quality_gates.py's - that module screens *generated*
# content quality; this module screens *source* HTML boilerplate. Different purpose, same
# "narrow, reviewable, hand-curated" discipline, not a general classifier either place.
_COOKIE_NOTICE_PHRASES = (
    "we use cookies", "accept cookies", "cookie policy", "manage cookies",
    "мы используем файлы cookie", "согласие на обработку", "использование файлов cookie",
)
_SUBSCRIPTION_PROMPT_PHRASES = (
    "subscribe to our newsletter", "subscribe now", "become a subscriber",
    "подпишитесь на рассылку", "подписаться на новости",
)
_SIGNUP_BLOCK_PHRASES = (
    "sign up for", "enter your email", "create a free account", "log in to continue",
    "войдите, чтобы продолжить", "зарегистрируйтесь",
)
_AD_LABEL_PHRASES = (
    "advertisement", "sponsored content", "promoted content", "advertisement continues",
    "реклама", "на правах рекламы",
)
_RELATED_STORIES_PHRASES = (
    "related articles", "related stories", "you might also like", "more from",
    "похожие статьи", "рекомендуем также",
)
_READ_ALSO_PHRASES = (
    "read also", "read more:", "see also", "читайте также", "смотрите также",
)
_SHARING_CONTROL_PHRASES = (
    "share on facebook", "share on twitter", "share this article", "share this story",
    "поделиться в", "поделиться статьей",
)
_LEGAL_DISCLAIMER_PHRASES = (
    "terms of service", "terms and conditions apply", "privacy policy applies",
    "all rights reserved", "условия использования", "пользовательское соглашение",
)
_NEWSLETTER_PROMO_PHRASES = (
    "get our newsletter", "daily newsletter", "weekly digest delivered",
    "получайте новости на почту", "еженедельная рассылка",
)
_COMMENT_PROMPT_PHRASES = (
    "leave a comment", "join the discussion", "what do you think", "comments (",
    "оставить комментарий", "обсудить в комментариях",
)

_CAPTION_PREFIX_MARKERS = ("photo:", "credit:", "image:", "фото:", "фото —", "credit —")
_BYLINE_PATTERN = re.compile(r"^(by\s+[a-zа-яё]|автор\s*:)", re.IGNORECASE)

# Structural nav/footer heuristic: a run of short, link-menu-like blocks in a row.
_NAV_FOOTER_MAX_BLOCK_CHARS = 40
_NAV_FOOTER_MIN_CONSECUTIVE = 4

# Conservative guard: a rule that would remove this fraction (or more) of all blocks is skipped -
# real articles are never mostly boilerplate; a rule confidently matching that much is itself
# evidence of a false-positive pattern on this particular page, not a genuinely boilerplate-heavy
# article.
_MAX_REMOVABLE_FRACTION_PER_RULE = 0.5

# Correction 2's low-confidence-cleaning downgrade: if less than this fraction of the raw text
# survives cleaning, the acquisition status is not trusted at its original tier (reconcile_status
# below) - a hand-curated, disclosed threshold, not a judgment call.
_LOW_CONFIDENCE_SURVIVAL_RATIO = 0.15


@dataclass(frozen=True)
class CleaningResult:
    cleaned_text: str
    raw_extracted_char_count: int
    cleaned_char_count: int
    removed_block_count: int
    cleaning_reasons: list[str] = field(default_factory=list)
    cleaning_version: str = CLEANING_VERSION


def _split_blocks(raw_text: str) -> list[str]:
    return [block for block in raw_text.split("\n") if block.strip()]


def _matches_any_phrase(block: str, phrases: tuple[str, ...]) -> bool:
    normalized = normalize_loose(block)
    return any(phrase in normalized for phrase in phrases)


def _phrase_rule_indices(blocks: list[str], phrases: tuple[str, ...]) -> set[int]:
    return {i for i, block in enumerate(blocks) if _matches_any_phrase(block, phrases)}


def _navigation_footer_cluster_indices(blocks: list[str]) -> set[int]:
    """A run of >= _NAV_FOOTER_MIN_CONSECUTIVE short blocks in a row - the shape a rendered nav
    menu or footer link list takes once flattened to plain text, distinct from a genuine short
    paragraph (which is not usually adjacent to several other equally short blocks)."""
    indices: set[int] = set()
    run: list[int] = []
    for i, block in enumerate(blocks):
        if len(block) <= _NAV_FOOTER_MAX_BLOCK_CHARS:
            run.append(i)
        else:
            if len(run) >= _NAV_FOOTER_MIN_CONSECUTIVE:
                indices.update(run)
            run = []
    if len(run) >= _NAV_FOOTER_MIN_CONSECUTIVE:
        indices.update(run)
    return indices


def _author_bio_indices(blocks: list[str]) -> set[int]:
    """The block immediately following a clear byline pattern ("By Jane Doe" / "Автор: ...") is
    removed only when short - a genuine article opening is rarely both directly after a byline
    line AND under the short-bio-length cutoff used here."""
    indices: set[int] = set()
    for i, block in enumerate(blocks):
        if _BYLINE_PATTERN.match(block.strip()) and i + 1 < len(blocks):
            candidate = blocks[i + 1]
            if len(candidate) <= 200:
                indices.add(i + 1)
    return indices


def _repeated_headline_indices(blocks: list[str], title: str | None) -> set[int]:
    if not title:
        return set()
    return {i for i, block in enumerate(blocks) if token_overlap_ratio(block, title) >= 0.8}


def _repeated_caption_indices(blocks: list[str]) -> set[int]:
    indices: set[int] = set()
    for i, block in enumerate(blocks):
        stripped = block.strip()
        lowered = stripped.lower()
        if lowered.startswith(_CAPTION_PREFIX_MARKERS):
            indices.add(i)
        elif stripped.startswith("[") and stripped.endswith("]") and len(stripped) <= 200:
            indices.add(i)
    return indices


def clean_extracted_text(raw_text: str, *, title: str | None = None) -> CleaningResult:
    """Pure. Never claims perfect main-content extraction - see module docstring. `title`
    (NewsEvent.title) is optional; the repeated-headline rule is simply skipped without it."""
    raw_char_count = len(raw_text)
    blocks = _split_blocks(raw_text)
    if not blocks:
        return CleaningResult(
            cleaned_text="", raw_extracted_char_count=raw_char_count, cleaned_char_count=0,
            removed_block_count=0, cleaning_reasons=[],
        )

    rule_results: list[tuple[str, set[int]]] = [
        ("navigation_or_footer_cluster", _navigation_footer_cluster_indices(blocks)),
        ("cookie_notice", _phrase_rule_indices(blocks, _COOKIE_NOTICE_PHRASES)),
        ("subscription_prompt", _phrase_rule_indices(blocks, _SUBSCRIPTION_PROMPT_PHRASES)),
        ("signup_block", _phrase_rule_indices(blocks, _SIGNUP_BLOCK_PHRASES)),
        ("advertisement_label", _phrase_rule_indices(blocks, _AD_LABEL_PHRASES)),
        ("related_stories", _phrase_rule_indices(blocks, _RELATED_STORIES_PHRASES)),
        ("read_also", _phrase_rule_indices(blocks, _READ_ALSO_PHRASES)),
        ("sharing_controls", _phrase_rule_indices(blocks, _SHARING_CONTROL_PHRASES)),
        ("author_bio_boilerplate", _author_bio_indices(blocks)),
        ("repeated_headline", _repeated_headline_indices(blocks, title)),
        ("repeated_image_caption", _repeated_caption_indices(blocks)),
        ("legal_disclaimer_unrelated", _phrase_rule_indices(blocks, _LEGAL_DISCLAIMER_PHRASES)),
        ("newsletter_promotion", _phrase_rule_indices(blocks, _NEWSLETTER_PROMO_PHRASES)),
        ("comment_prompt", _phrase_rule_indices(blocks, _COMMENT_PROMPT_PHRASES)),
    ]

    max_removable = max(1, int(len(blocks) * _MAX_REMOVABLE_FRACTION_PER_RULE))
    to_remove: set[int] = set()
    reasons: list[str] = []
    for name, indices in rule_results:
        if not indices:
            continue
        if len(indices) > max_removable:
            reasons.append(f"{name}_skipped_would_remove_majority")
            continue
        to_remove.update(indices)
        reasons.append(name)

    kept_blocks = [block for i, block in enumerate(blocks) if i not in to_remove]
    cleaned_text = "\n\n".join(kept_blocks)

    return CleaningResult(
        cleaned_text=cleaned_text, raw_extracted_char_count=raw_char_count,
        cleaned_char_count=len(cleaned_text), removed_block_count=len(to_remove),
        cleaning_reasons=reasons,
    )


def reconcile_status(acquisition_status: str, cleaning_result: CleaningResult) -> str:
    """Pure. Low cleaning confidence downgrades toward PARTIAL_TEXT rather than letting a
    FULL_TEXT/SUBSTANTIAL_TEXT claim stand on a raw extraction that turned out to be mostly
    boilerplate - the concrete mechanism behind "prefer PARTIAL_TEXT over overclaiming FULL_TEXT
    when confidence is low" (docs/phase19_m0_audit.md)."""
    from database.models.news_event_article_acquisition import (
        ACQUISITION_STATUS_FULL_TEXT,
        ACQUISITION_STATUS_PARTIAL_TEXT,
        ACQUISITION_STATUS_SUBSTANTIAL_TEXT,
    )

    if acquisition_status not in (ACQUISITION_STATUS_FULL_TEXT, ACQUISITION_STATUS_SUBSTANTIAL_TEXT):
        return acquisition_status
    if cleaning_result.raw_extracted_char_count == 0:
        return acquisition_status
    survival_ratio = cleaning_result.cleaned_char_count / cleaning_result.raw_extracted_char_count
    if survival_ratio < _LOW_CONFIDENCE_SURVIVAL_RATIO:
        return ACQUISITION_STATUS_PARTIAL_TEXT
    return acquisition_status
