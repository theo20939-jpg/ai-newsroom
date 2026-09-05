"""MEDIA-PROD-1: deterministic, narrow, hand-curated video advertisement detector - never an LLM
call, mirrors services/content_quality_gates.py's own established "deterministic, no ML"
convention and services/meme_opportunity.py::detect_sensitive_categories()'s own word-boundary
regex-lexicon idiom (reused, not reinvented - same `\\b(?:phrase1|phrase2|...)\\b` + IGNORECASE
shape, longest-phrase-first alternation).

Scope decision (real production issue: two advertisement videos passed editorial filtering): only
the TEXT-signal detection the brief's own listed examples describe (buy/sale/discount/promo/
sponsored/купить/скидка/акция/реклама) is implemented this phase. The brief's own "visual signals"
(product showcase, pricing overlays, commercial presentation style) would need real frame-level
analysis - schemas.video_candidate.NativeVideoHint carries no thumbnail/poster/frame of any kind
today, and services/video_discovery.py's own module docstring explicitly disclaims "NO
transcoding, NO ffmpeg dependency" for its bounded, explicitly-authorized discovery sources. Adding
frame extraction now would be new, disproportionate infrastructure for this phase's own "do not
create duplicate pipelines"/"avoid unnecessary AI providers" instructions - documented here as an
explicit, disclosed follow-up, never silently skipped. `VideoContentClassification.LOW_VALUE` is
reserved for that future signal and is never produced by this module today.

`NativeVideoHint` itself carries no title/caption of its own - it is discovery-time-only metadata
(url/platform/declared dimensions, schemas/video_candidate.py). A video's own CONTEXT is the
NewsEvent it was discovered alongside, so `assess_video_text_signals()` scans that event's own
title/content - text `worker/content_cycle.py` already has in scope at its own video-acceptance
point (settings.rich_media_mode == "enforce" block), no new fetch, no new parsing, no new source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# Hand-curated EN+RU lexicon - the brief's own explicit example list, same "fixed list, never a
# general sentiment/quality model" convention services/content_quality_gates.py's own lexicons and
# services/meme_opportunity.py's own _SENSITIVE_PATTERNS already establish.
_ADVERTISEMENT_KEYWORDS: frozenset[str] = frozenset({
    "buy now", "buy", "sale", "on sale", "discount", "promo", "promo code", "sponsored",
    "купить", "скидка", "скидки", "акция", "реклама", "рекламодатель", "промокод",
})


def _compile_keyword_pattern(keywords: frozenset[str]) -> re.Pattern[str]:
    """Byte-for-byte the same idiom services/meme_opportunity.py::_compile_sensitive_patterns()
    already established: longest-phrase-first alternation (so "buy now" matches whole rather than
    just "buy" inside it), `\\b` word boundaries (Unicode-aware by default for a `str` pattern, so
    this works correctly for the Cyrillic keywords too, not just the English ones), case-insensitive."""
    alternation = "|".join(re.escape(keyword) for keyword in sorted(keywords, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


_ADVERTISEMENT_PATTERN = _compile_keyword_pattern(_ADVERTISEMENT_KEYWORDS)


class VideoContentClassification(str, Enum):
    APPROVED = "approved"
    ADVERTISEMENT = "advertisement"
    LOW_VALUE = "low_value"  # reserved - never produced by this module today, see module docstring


@dataclass(frozen=True)
class VideoQualityAssessment:
    classification: VideoContentClassification
    matched_keywords: tuple[str, ...]


def assess_video_text_signals(*, title: str, content: str | None) -> VideoQualityAssessment:
    """Pure, deterministic, zero I/O. Scans `title` + `content` for the advertisement-keyword
    lexicon above and returns every matched keyword (deduped, lowercased) as evidence - never just
    a bare boolean, mirrors detect_sensitive_categories()'s own "evidence, not just a verdict"
    convention, so a caller can log exactly what was matched."""
    haystack = f"{title}\n{content or ''}"
    matches = sorted({match.group(0).lower() for match in _ADVERTISEMENT_PATTERN.finditer(haystack)})
    classification = (
        VideoContentClassification.ADVERTISEMENT if matches else VideoContentClassification.APPROVED
    )
    return VideoQualityAssessment(classification=classification, matched_keywords=tuple(matches))
