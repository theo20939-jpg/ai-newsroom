"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S22): a bounded Russian editorial-language quality
check, run once, before rendering/package finalization - detection only, plus one narrow,
deterministic mechanical correction (exact duplicated sentences); never an open-ended LLM
self-rewrite loop (S22's own explicit "at most one bounded correction pass" limit).

Real finding from this phase's own Maxus 9 investigation (S9), TWO gaps, not one:

1. `services.presentation_director`'s own `_ORPHANED_LABEL_RE`/`_TRAILING_PREPOSITION_RE` safety
   patterns (module docstring there: "a label... must never leave a bare preposition directly
   touching an orphaned currency/unit noun") list `за|до|на|в|из|от` - but not `с` ("with/from"),
   one of the most common Russian prepositions, and the exact one in the real defect's own
   dangling artifact: "начинается **с** юаней".
2. `services.presentation_director._CURRENCY_WORD` itself only recognizes рубли/доллары/USD/EUR/
   евро/₽/$ - it has never covered юань (yuan), despite this codebase's own real production news
   flow regularly covering Chinese-market products/prices (confirmed directly: `_CURRENCY_WORD`
   would not even have flagged "юаней" as a currency word to protect in the first place, quite
   apart from the missing preposition).

Both gaps are fixed HERE, in this new module's own extended vocabulary - NOT by editing
`services/presentation_director.py`'s shared constants directly. Per this phase's own S18 Telegram
V8 freeze ("EXISTING_V8_MEDIA_BACKED_PIXEL_DIFF = 0"), that module's currently-deployed production
behavior stays byte-for-byte unchanged; this module's own extended checks apply only to the NEW
pipeline's quality gate (S21), which is unreachable in production while `unified_editorial_
pipeline_enabled` stays False (S26). A future phase, once the new pipeline is the production path,
should fold these two vocabulary fixes back into `presentation_director.py` itself and delete the
duplication here.
"""
from __future__ import annotations

import re

from services.presentation_director import _CHANGE_UNIT, _MAGNITUDE_UNIT

# Extends services.presentation_director._CURRENCY_WORD (see module docstring gap 2) - every
# currency that module already covers, plus юань/yuan/RMB/CNY, kept local to this new module.
_EXTENDED_CURRENCY_WORD = r"(?:руб(?:л\w*|\.)?|доллар\w*|usd|eur|евро|₽|\$|юан\w*|yuan|rmb|cny|¥)"
_EXTENDED_PREPOSITIONS = r"за|до|на|в|из|от|с|по|при|под|for|to|of|with"

_ORPHANED_PHRASE_RE = re.compile(
    rf"\b(?:{_EXTENDED_PREPOSITIONS})\s+(?:{_EXTENDED_CURRENCY_WORD}|{_MAGNITUDE_UNIT}|{_CHANGE_UNIT})\b",
    re.IGNORECASE,
)
_TRAILING_PREPOSITION_RE = re.compile(rf"\b(?:{_EXTENDED_PREPOSITIONS})\s*[.,;:!?]?\s*$", re.IGNORECASE)


def _find_duplicated_sentences(text: str) -> str | None:
    """A narrow, exact-match check (never a fuzzy/semantic one - false positives on genuinely
    similar-but-distinct sentences would be worse than missing a near-duplicate) - S22's own
    'duplicated metric sentences' example."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    seen: set[str] = set()
    for sentence in sentences:
        key = sentence.lower()
        if key in seen:
            return sentence
        seen.add(key)
    return None


def check_language_quality(text: str) -> "QualityCheckResult":  # noqa: F821 - imported lazily below to avoid a cycle
    from services.editorial_pipeline.contracts import QualityCheckName, QualityCheckResult

    orphan_match = _ORPHANED_PHRASE_RE.search(text)
    if orphan_match is not None:
        return QualityCheckResult(
            QualityCheckName.LANGUAGE_QUALITY, False,
            f"orphaned preposition + bare unit/currency noun: {orphan_match.group(0)!r}",
        )
    if _TRAILING_PREPOSITION_RE.search(text) is not None:
        return QualityCheckResult(QualityCheckName.LANGUAGE_QUALITY, False, "text trails off on a bare preposition")
    duplicate = _find_duplicated_sentences(text)
    if duplicate is not None:
        return QualityCheckResult(QualityCheckName.LANGUAGE_QUALITY, False, f"duplicated sentence: {duplicate!r}")
    return QualityCheckResult(QualityCheckName.LANGUAGE_QUALITY, True, "no structural artifacts detected")


def correct_duplicated_sentences(text: str) -> str:
    """The one bounded, deterministic mechanical correction this module makes (S22's own "at most
    one bounded correction pass for objective failures") - collapses an exact repeated sentence to
    its first occurrence. Never rewrites wording, never touches anything the detector above did not
    flag as objectively wrong."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    seen: set[str] = set()
    kept: list[str] = []
    for sentence in sentences:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    return " ".join(kept)
