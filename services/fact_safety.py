"""Fact Safety (Phase 15 M5): a deterministic guard against unsupported high-risk factual claims
surviving into a delivered ContentDraft.

Root cause this addresses (docs/phase15_m5_fact_safety_report.md §2, Phase 14.5's own live
incident): from Copywriting onward, the pipeline sees only Research's *paraphrased*, wholly
unprovenanced facts (`prompts/research/v2.yaml`'s own schema is `{facts: list[str], confidence,
gaps}` - no citation, no URL, nothing) - never the original `NewsEvent.title`/`.content` directly
(`capabilities/copywriting_capability.py`'s own docstring: "never content"). A concrete detail
invented or amplified during Research/Copywriting has nothing further downstream capable of
catching it: `QualityCapability` is a second LLM opinion, not a deterministic check, and its
`passed`/`issues` result is not even read by anything that gates delivery today
(`services/content_draft_service.py` builds `ContentDraft` from Copywriting's output
unconditionally, whenever the workflow completes).

Zero new LLM/provider calls, zero new DB queries: `capabilities/executor.py`'s existing
`CapabilityContext` already carries the raw `NewsEventSnapshot` (title/content/url) *and* every
prior step's completed `step_results` (including "research" and "copywriting") at the "quality"
step - the exact same seam Phase 15 M4 already proved out for `apply_editorial_scoring_v2()`
(`step.capability == "scoring"`). This module never touches a database session or the LLM
Gateway - see `test_fact_safety_module_imports_no_llm_gateway_or_capability`.

Split, mirroring `services/editorial_scoring.py`'s own established shape: pure, fully
unit-testable claim extraction/normalization/classification (no I/O), plus one thin
`apply_fact_safety()` integration function that is the only piece `capabilities/executor.py`
calls.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from core.config import settings

FACT_SAFETY_VERSION = "v1"

ClaimType = Literal["money", "percentage", "date", "entity", "quote"]
SupportLevel = Literal["supported", "uncertain", "unsupported"]
Severity = Literal["low", "medium", "high"]
DraftStatus = Literal["pass", "review", "block"]

# High-risk claim types (M5.2) always receive HIGH severity when unsupported - a concrete,
# precisely fabricatable detail (an exact number, an exact date, a verbatim quote). Entity
# severity is decided per-finding (centrality-dependent, see _entity_severity) rather than a
# fixed table value - a secondary/background company name is a materially different risk than
# the story's own named subject (M5.5's own explicit HIGH vs. MEDIUM entity examples).
_UNSUPPORTED_SEVERITY: dict[ClaimType, Severity] = {
    "money": "high", "percentage": "high", "date": "high", "quote": "high", "entity": "medium",
}
# UNCERTAIN findings are always one tier below their UNSUPPORTED equivalent - a real gap worth
# surfacing for editorial review, never treated as equally alarming as a confirmed contradiction.
_UNCERTAIN_SEVERITY: dict[ClaimType, Severity] = {
    "money": "medium", "percentage": "medium", "date": "medium", "quote": "medium", "entity": "low",
}


@dataclass(frozen=True)
class FactEvidence:
    """The centralized evidence packet (M5.1). Built entirely from data already present on
    `CapabilityContext` - no new external call, no new DB query.

    `source_content` is `None` when the underlying NewsEvent has no body text (a real, common
    case - see `database/models/news_event.py`'s own nullable `content` column) - this is a
    distinct, tracked state from "content present but simply doesn't mention the claim" (M5.4's
    UNCERTAIN-vs-UNSUPPORTED distinction, `_evidence_coverage`).

    `research_facts` is the real, current, always-unprovenanced Research output shape
    (`list[str]`) - matches `prompts/research/v2.yaml`'s actual schema. `research_facts_provenanced`
    is an extensibility hook for a *future* Research capability version that does attach real
    provenance (a fact paired with the source URL/quote it was drawn from) - production code
    never populates this today (no such Research output exists yet), but the classifier already
    knows how to treat a provenanced match as equal-strength to original source evidence
    (M5.4/M5.1: "do not treat an AI-generated Research statement as equally authoritative to
    original source text unless it retains provenance") - kept here, tested directly, rather than
    silently unsupported until Research itself changes.
    """

    source_title: str
    source_content: str | None
    source_url: str | None
    research_facts: list[str] = field(default_factory=list)
    research_facts_provenanced: tuple[tuple[str, str], ...] = ()
    intelligence_summary: str | None = None


@dataclass(frozen=True)
class ClaimFinding:
    claim: str
    claim_type: ClaimType
    support: SupportLevel
    severity: Severity | None  # None only for a "supported" claim - not a "finding" needing review
    evidence: list[str]


# ---------------------------------------------------------------------------
# M5.3 - normalization
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Safe Unicode normalization (NFKC - compatibility fold, e.g. full-width/half-width digits,
    ligatures) + casefold + collapsed whitespace. Used as the base step before every
    type-specific normalizer, and directly for plain substring/quote comparison."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


_MONEY_MAGNITUDE: dict[str, float] = {
    "trillion": 1e12, "трлн": 1e12,
    "b": 1e9, "bn": 1e9, "billion": 1e9, "млрд": 1e9,
    "m": 1e6, "mn": 1e6, "million": 1e6, "млн": 1e6,
    "k": 1e3, "thousand": 1e3, "тыс": 1e3,
}
# M5.3 calibration: added Yuan/CNY/RMB - the pipeline covers Chinese-market news routinely (the
# live Trip.com/$770M fine draft, docs/phase15_m5_fact_safety_report.md M5.2 §9) and previously
# had zero currency-word coverage beyond USD/EUR/GBP/RUB, so any Yuan-denominated claim could
# never resolve to a currency and was guaranteed to be a false-positive UNSUPPORTED finding even
# when it exactly matched the source. No conversion rate is introduced - matching still requires
# the same currency code and the same exact numeric amount (_money_matches).
_CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "долларов": "USD", "доллара": "USD", "доллар": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "евро": "EUR",
    "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
    "₽": "RUB", "rub": "RUB", "ruble": "RUB", "rubles": "RUB", "рублей": "RUB", "рубля": "RUB", "рубль": "RUB",
    "cny": "CNY", "rmb": "CNY", "yuan": "CNY", "yuans": "CNY", "renminbi": "CNY",
    "юаней": "CNY", "юаня": "CNY", "юань": "CNY",
}

# Shared "number" fragment (M5.3): either proper thousands-grouping (each group after the first
# is exactly 3 digits - "1,700,000" / "1.700.000") or a plain number with at most one decimal
# separator ("1.7" / "1,7"). Deliberately excludes any digit run with irregular grouping (e.g.
# "24.07.2026", a date) - this is what previously let a date get misparsed as a money amount.
_MONEY_NUMBER = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
# Single-letter shorthand (B/M/K) must sit directly against the number, no space - "$1.7B" is a
# real, required format (M5.3); "5 b..." (any word starting with "b") must not be treated as a
# magnitude - a trailing \b word-boundary on every alternative prevents matching only a prefix of
# an unrelated longer word (e.g. "bears" -> "b").
# M7.1 calibration: added trillion/трлн - discovered as a coverage gap during Phase 17 M7 (docs/
# phase17_m7_fact_safety_calibration_discovery.md §1b): a trillion-scale claim (e.g. "2.8 trillion
# parameters") was previously invisible to extract_claims() entirely, since neither the English nor
# Russian word was in this magnitude table - a fabricated trillion-scale figure would pass Fact
# Safety unchecked. Scoped narrowly to exactly these two words, per M7.1's own explicit scope (no
# single-letter "T" shorthand added - not requested, and "t"/"tn" collide far more with ordinary
# words than "b"/"m"/"k" already do).
_MONEY_MAGNITUDE_WORD = r"(?:trillion|billion|bn|million|mn|thousand|трлн|млрд|млн|тыс)\b"
_MONEY_MAGNITUDE_LETTER = r"[bmk]\b"
_MONEY_CURRENCY_WORD = (
    r"(?:dollars?|euros?|pounds?|rubles?|yuans?|renminbi|"
    r"долларов|доллара|доллар|евро|рублей|рубля|рубль|юаней|юаня|юань|"
    r"usd|eur|gbp|rub|cny|rmb)\b"
)

_MONEY_PATTERN = re.compile(
    rf"(?P<currency>\$|€|£|₽)?\s*"
    rf"(?P<number>{_MONEY_NUMBER})"
    rf"(?:\s*(?P<magnitude>{_MONEY_MAGNITUDE_WORD})|(?P<magnitude_letter>{_MONEY_MAGNITUDE_LETTER}))?\.?\s*"
    rf"(?P<currency_word>{_MONEY_CURRENCY_WORD})?",
    re.IGNORECASE,
)


def _parse_money_number(raw: str) -> float | None:
    """Handles both `1.7` (decimal point) and `1,7` (decimal comma, RU convention) as well as
    thousands-grouped forms (`1,700,000` / `1.700.000`) - disambiguated by counting fractional
    digits: a single separator followed by exactly 1-2 digits at the end is treated as a decimal
    point; anything with multiple separators or >2 trailing digits is treated as thousands
    grouping and the separators are simply stripped."""
    raw = raw.strip()
    if not raw:
        return None
    separators = [c for c in raw if c in ",."]
    if len(separators) <= 1:
        last_sep_index = max(raw.rfind(","), raw.rfind("."))
        if last_sep_index != -1 and len(raw) - last_sep_index - 1 <= 2:
            # At most one separator total (established above) - this reconstruction can never
            # produce a second ".", so a direct float() parse is always safe here.
            candidate = raw[:last_sep_index] + "." + raw[last_sep_index + 1 :]
            try:
                return float(candidate)
            except ValueError:
                return None
    cleaned = raw.replace(",", "").replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_money(raw_text: str) -> tuple[str, float] | None:
    """Returns (currency_code, amount_in_base_units) - e.g. "$1.7 billion", "$1,7 млрд", and
    "$1.7B" all normalize to `("USD", 1_700_000_000.0)`."""
    match = _MONEY_PATTERN.fullmatch(raw_text.strip())
    if match is None:
        return None
    number = _parse_money_number(match.group("number"))
    if number is None:
        return None
    magnitude_key = (match.group("magnitude") or match.group("magnitude_letter") or "").lower()
    amount = number * _MONEY_MAGNITUDE.get(magnitude_key, 1.0)
    currency_key = (match.group("currency") or match.group("currency_word") or "").lower()
    currency = _CURRENCY_SYMBOLS.get(currency_key)
    if currency is None:
        return None
    return currency, amount


def _money_matches(a: tuple[str, float], b: tuple[str, float]) -> bool:
    """Same currency, amount equal within a small relative tolerance (floating-point-safe
    equality for magnitudes computed via multiplication, e.g. 1.7 * 1e9)."""
    if a[0] != b[0]:
        return False
    if a[1] == 0 and b[1] == 0:
        return True
    return abs(a[1] - b[1]) <= max(abs(a[1]), abs(b[1])) * 1e-6


_PERCENTAGE_PATTERN = re.compile(
    rf"(?P<number>{_MONEY_NUMBER})\s*(?:%|percent|процент(?:а|ов)?)", re.IGNORECASE
)


def _normalize_percentage(raw_text: str) -> float | None:
    match = _PERCENTAGE_PATTERN.fullmatch(raw_text.strip())
    if match is None:
        return None
    return _parse_money_number(match.group("number"))


def _percentage_matches(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6


@dataclass(frozen=True)
class _DateParts:
    year: int
    month: int | None
    day: int | None


_MONTH_NAMES: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "января": 1, "январь": 1, "февраля": 2, "февраль": 2, "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4, "мая": 5, "май": 5, "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7, "августа": 8, "август": 8, "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10, "ноября": 11, "ноябрь": 11, "декабря": 12, "декабрь": 12,
}

_DATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"),  # ISO: 2026-07-24
    re.compile(r"(?P<d>\d{1,2})[./](?P<m>\d{1,2})[./](?P<y>\d{4})"),  # 24.07.2026 / 24/07/2026
    re.compile(
        r"(?P<mname>[A-Za-zА-Яа-яЁё]+)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})"
    ),  # "July 24, 2026" / "24 июля 2026" (month-first form)
    re.compile(r"(?P<d>\d{1,2})\s+(?P<mname>[A-Za-zА-Яа-яЁё]+)\s+(?P<y>\d{4})"),  # "24 июля 2026"
    re.compile(r"\b(?P<y>(?:19|20)\d{2})\b"),  # bare year, lowest-precision fallback
]


def _normalize_date(raw_text: str) -> _DateParts | None:
    text = raw_text.strip()
    for pattern in _DATE_PATTERNS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        groups = match.groupdict()
        year = int(groups["y"])
        month: int | None = None
        day: int | None = None
        if "mname" in groups and groups.get("mname"):
            month = _MONTH_NAMES.get(groups["mname"].lower())
            if month is None:
                continue  # not a recognized month word - not actually a date match
        elif "m" in groups and groups.get("m"):
            month = int(groups["m"])
        if "d" in groups and groups.get("d"):
            day = int(groups["d"])
        if month is not None and not (1 <= month <= 12):
            continue
        if day is not None and not (1 <= day <= 31):
            continue
        return _DateParts(year=year, month=month, day=day)
    return None


def _date_matches(a: _DateParts, b: _DateParts) -> bool:
    """Partial specificity is compatible, not contradictory: a source that only says "2026"
    does not conflict with a draft claim of "July 2026" - but a draft claim of "August 2026"
    when the source specifically says "July 2026" is a genuine mismatch. Matching requires the
    year to agree and, for any field both sides actually specify, that field to also agree."""
    if a.year != b.year:
        return False
    if a.month is not None and b.month is not None and a.month != b.month:
        return False
    if a.day is not None and b.day is not None and a.day != b.day:
        return False
    return True


_ENTITY_SUFFIX_PATTERN = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|gmbh|plc)\.?\s*$", re.IGNORECASE)
# Russian legal-entity markers are written BEFORE the name ("ООО Ромашка" = "Romashka LLC"), the
# reverse convention from English suffixes - a distinct pattern, anchored at the start.
_ENTITY_PREFIX_PATTERN = re.compile(r"^(ооо|зао|пао|оао)\b\.?\s*", re.IGNORECASE)
# M5.3 calibration: a narrow, explicit set of generic Russian descriptive nouns commonly
# hyphen-attached to a proper noun ("CRISPR-система" = "the CRISPR system") - the live sample's
# own CRISPR/CRISPR-система false positive. Deliberately a small, fixed word list (not a
# morphological/suffix-stripping algorithm) - conservative by instruction: it only ever strips
# one of these exact words, never guesses at an unlisted suffix.
_ENTITY_DESCRIPTIVE_SUFFIX_PATTERN = re.compile(
    r"-(?:система|технология|платформа|модель|метод|алгоритм|инструмент)\b", re.IGNORECASE
)

# M5.3 calibration: explicit, hand-curated equivalence groups for same-real-world-entity aliases
# that never string-match - a same-language abbreviation ("ИИ" / "искусственный интеллект") or a
# cross-language name ("КНР" / "China") - both observed as live false positives (docs/
# phase15_m5_fact_safety_report.md M5.2 §9). Deliberately a short, explicit, hand-reviewed list,
# never general acronym-guessing or transliteration inference (M5.3 instruction) - an alias not
# listed here simply stays unmatched, which only ever costs a false positive, never risks a false
# negative by inventing an equivalence that isn't actually certain.
_ENTITY_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"ии", "искусственный интеллект", "ai", "artificial intelligence"}),
    frozenset({"кнр", "китай", "china", "people's republic of china", "peoples republic of china"}),
)
_ENTITY_ALIAS_CANONICAL: dict[str, str] = {
    alias: min(group) for group in _ENTITY_ALIAS_GROUPS for alias in group
}
_ENTITY_ALIAS_CANONICAL_VALUES: frozenset[str] = frozenset(_ENTITY_ALIAS_CANONICAL.values())
# English possessive - "China's" and "China" name the same entity. Narrow (only a trailing
# 's/'s), not a general grammar normalizer.
_POSSESSIVE_SUFFIX_PATTERN = re.compile(r"[’']s$", re.IGNORECASE)


def _normalize_entity(raw_text: str) -> str:
    text = _normalize_text(raw_text)
    text = _ENTITY_PREFIX_PATTERN.sub("", text)
    text = _ENTITY_SUFFIX_PATTERN.sub("", text).strip()
    text = _ENTITY_DESCRIPTIVE_SUFFIX_PATTERN.sub("", text).strip()
    text = _POSSESSIVE_SUFFIX_PATTERN.sub("", text).strip()
    text = text.strip(" .,’'\"")
    return _ENTITY_ALIAS_CANONICAL.get(text, text)


# ---------------------------------------------------------------------------
# M5.2 - claim extraction
# ---------------------------------------------------------------------------

_MONEY_EXTRACT_PATTERN = re.compile(
    # Currency-symbol-anchored: "$1.7 billion", "$1,7 млрд", "$2 billion", "$1.7B", "$50".
    rf"(?:\$|€|£|₽)\s*(?:{_MONEY_NUMBER})(?:\s*{_MONEY_MAGNITUDE_WORD}|{_MONEY_MAGNITUDE_LETTER})?\.?"
    # Magnitude-word-anchored, no currency symbol required: "1.7 billion dollars", "1,7 млрд долларов".
    rf"|(?:{_MONEY_NUMBER})\s*{_MONEY_MAGNITUDE_WORD}\.?\s*(?:{_MONEY_CURRENCY_WORD})?"
    # Currency-word-anchored, no symbol and no magnitude word: "50 dollars", "50 долларов".
    rf"|(?:{_MONEY_NUMBER})\s*{_MONEY_CURRENCY_WORD}",
    re.IGNORECASE,
)
_PERCENTAGE_EXTRACT_PATTERN = re.compile(
    rf"(?:{_MONEY_NUMBER})\s*(?:%|percent|процент(?:а|ов)?)", re.IGNORECASE
)
_DATE_EXTRACT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|(?:[A-Za-z]+|[А-Яа-яЁё]+)\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:[A-Za-z]+|[А-Яа-яЁё]+)\s+\d{4}"
    r"|\b(?:19|20)\d{2}\b"  # bare year fallback - only reached when no fuller date matched here first
)
# Capitalized-token run heuristic (M5.2's "do not build a general NLP parser" instruction) - 1-4
# consecutive Title-Case (or ALLCAPS, e.g. "OpenAI", "NASA") words, optionally trailed by a legal
# suffix - but see _extract_entities()'s own filtering below: a *lone* ordinary Title-Case word
# (just a capitalized first letter - the single biggest false-positive source, since it fires on
# every sentence-initial word in both English and Russian) is discarded unless it carries a
# stronger independent signal (all-caps acronym, internal capital, or an attached legal suffix).
_ENTITY_RUN_PATTERN = re.compile(
    # [^\S\n]+ (whitespace-but-not-newline), not \s+ - a multi-word run must never span a
    # newline, so an incidental capitalized word ending one line (e.g. a title) can never
    # accidentally concatenate with a capitalized word starting the next (e.g. the following
    # body text) into one false "entity".
    r"\b(?:[A-ZА-ЯЁ][\w'-]*|[A-ZА-ЯЁ]{2,})(?:[^\S\n]+(?:[A-ZА-ЯЁ][\w'-]*|[A-ZА-ЯЁ]{2,})){0,3}"
    r"(?:[^\S\n]+(?:Inc|LLC|Ltd|Corp|Corporation|Co|GmbH|plc|ООО|ЗАО|ПАО)\.?)?"
)
_INTERNAL_CAPITAL_PATTERN = re.compile(r"^.+[A-ZА-ЯЁ]")  # a capital letter anywhere after index 0
_LEGAL_SUFFIX_PATTERN = re.compile(r"(?:Inc|LLC|Ltd|Corp|Corporation|Co|GmbH|plc|ООО|ЗАО|ПАО)\.?$")
# M5.3 calibration: a multi-word common-noun alias phrase ("искусственный интеллект") never
# satisfies _ENTITY_RUN_PATTERN's capitalized-run heuristic outside a sentence-initial position,
# because only its first word is ever capitalized in ordinary Russian/English prose - unlike a
# real proper-noun phrase ("Trip.com Group"), where every word is capitalized. Rather than
# loosening the general capitalized-run heuristic (which would reopen the exact lone-Title-Case-
# word false-positive class it exists to close), this is a separate, literal, case-insensitive
# search for the small set of explicit multi-word alias phrases only - never a general noun-phrase
# parser.
_ENTITY_ALIAS_MULTIWORD_PATTERN = re.compile(
    "|".join(re.escape(alias) for alias in sorted(_ENTITY_ALIAS_CANONICAL, key=len, reverse=True) if " " in alias),
    re.IGNORECASE,
)
_QUOTE_EXTRACT_PATTERN = re.compile(r'"([^"\n]{3,200})"|«([^»\n]{3,200})»|“([^”\n]{3,200})”')
# A quoted SINGLE word is, in both Russian and English news-writing convention, almost always a
# brand/proper-noun styling choice («Медикейд», «Палантир», "the app") - never an attributed
# statement. Requiring at least one internal space (2+ words) before something counts as a
# "quote" claim excludes this entire, very common false-positive class without discarding real
# short quotes ("we are thrilled" still qualifies).
_MULTI_WORD_PATTERN = re.compile(r"\S+\s+\S+")


def _is_strong_single_token_entity(token: str) -> bool:
    """A lone capitalized word is kept only when it carries a signal stronger than "starts a
    sentence": ALL-CAPS shorthand (NASA, AI), an internal capital past the first letter
    (OpenAI, iPhone), an attached legal suffix (handled separately, before this is called), or an
    explicit, hand-curated alias match (M5.3 - "China"/"China's", "Китай", never a generically
    guessed acronym)."""
    if token.isupper() and len(token) >= 2:
        return True
    if _INTERNAL_CAPITAL_PATTERN.match(token[1:]):
        return True
    return _normalize_entity(token) in _ENTITY_ALIAS_CANONICAL_VALUES


def _extract_entities(text: str) -> list[str]:
    candidates = []
    for match in _ENTITY_RUN_PATTERN.finditer(text):
        value = match.group(0).strip()
        if len(value) < 2 or not any(character.isalpha() for character in value):
            continue
        has_suffix = bool(_LEGAL_SUFFIX_PATTERN.search(value))
        core = _LEGAL_SUFFIX_PATTERN.sub("", value).strip()
        token_count = len(core.split())
        if token_count >= 2:
            candidates.append(value)  # multi-word run - a real proper-noun-phrase signal
        elif has_suffix:
            candidates.append(value)  # "Acme Inc" even if "Acme" alone would not qualify
        elif _is_strong_single_token_entity(core):
            candidates.append(value)
        # else: a lone ordinary Title-Case word - discarded, most common false-positive source
    if _ENTITY_ALIAS_MULTIWORD_PATTERN.pattern:
        candidates.extend(m.group(0) for m in _ENTITY_ALIAS_MULTIWORD_PATTERN.finditer(text))
    return candidates


def extract_claims(text: str) -> dict[ClaimType, list[str]]:
    """Deterministic. Returns raw (un-normalized) claim substrings grouped by type - purely
    regex-based (M5.2: "do not build a general natural-language parser... do not add a new NLP
    service"), using only the stdlib `re` module already used throughout this codebase."""
    return {
        "money": [m.group(0).strip() for m in _MONEY_EXTRACT_PATTERN.finditer(text) if m.group(0).strip()],
        "percentage": [m.group(0).strip() for m in _PERCENTAGE_EXTRACT_PATTERN.finditer(text)],
        "date": [m.group(0).strip() for m in _DATE_EXTRACT_PATTERN.finditer(text)],
        "entity": _extract_entities(text),
        "quote": [
            quoted
            for m in _QUOTE_EXTRACT_PATTERN.finditer(text)
            if _MULTI_WORD_PATTERN.search(quoted := next(g for g in m.groups() if g is not None).strip())
        ],
    }


# ---------------------------------------------------------------------------
# M5.4 - support classification
# ---------------------------------------------------------------------------


def _claim_matches_any(claim_type: ClaimType, claim: str, evidence_claims: list[str]) -> bool:
    if claim_type == "money":
        normalized_money = _normalize_money(claim)
        if normalized_money is None:
            return False
        return any(
            (parsed := _normalize_money(candidate)) is not None and _money_matches(normalized_money, parsed)
            for candidate in evidence_claims
        )
    if claim_type == "percentage":
        normalized_percentage = _normalize_percentage(claim)
        if normalized_percentage is None:
            return False
        return any(
            (parsed_pct := _normalize_percentage(candidate)) is not None
            and _percentage_matches(normalized_percentage, parsed_pct)
            for candidate in evidence_claims
        )
    if claim_type == "date":
        normalized_date = _normalize_date(claim)
        if normalized_date is None:
            return False
        return any(
            (parsed_date := _normalize_date(candidate)) is not None and _date_matches(normalized_date, parsed_date)
            for candidate in evidence_claims
        )
    if claim_type == "entity":
        normalized_entity = _normalize_entity(claim)
        if not normalized_entity:
            return False
        return any(normalized_entity == _normalize_entity(candidate) for candidate in evidence_claims)
    # quote: exact-normalized-text containment (never fuzzy - M5.3's own "no broad fuzzy
    # matching that can turn unrelated claims into matches" rule applies most strictly here).
    normalized_quote = _normalize_text(claim)
    return any(normalized_quote in _normalize_text(candidate) for candidate in evidence_claims)


def _entity_severity(entity: str, draft_title: str, support: SupportLevel) -> Severity:
    if support == "uncertain":
        return _UNCERTAIN_SEVERITY["entity"]
    # M5.3 regression guard: centrality is a literal-substring check against the draft's own
    # title text, which always contains the entity's ORIGINAL wording (e.g. "ИИ"), never its
    # cross-language alias canonical form (e.g. "ai") - using the full `_normalize_entity()`
    # pipeline here (which now also resolves aliases) would make a Cyrillic entity's Latin
    # canonical form fail to substring-match a Cyrillic title even when the literal word is
    # right there. `_normalize_text()` alone (casefold + NFKC, no alias/suffix mapping) is the
    # correct comparison for this specific "does the title literally say this" check.
    is_central = _normalize_text(entity) in _normalize_text(draft_title)
    return "high" if is_central else _UNSUPPORTED_SEVERITY["entity"]


def _classify_claim(
    claim_type: ClaimType,
    claim: str,
    *,
    draft_title: str,
    source_claims: list[str],
    provenanced_claims: list[str],
    unprovenanced_research_claims: list[str],
    evidence_complete: bool,
) -> ClaimFinding:
    if _claim_matches_any(claim_type, claim, source_claims):
        return ClaimFinding(claim=claim, claim_type=claim_type, support="supported", severity=None, evidence=source_claims)
    if _claim_matches_any(claim_type, claim, provenanced_claims):
        return ClaimFinding(claim=claim, claim_type=claim_type, support="supported", severity=None, evidence=provenanced_claims)

    if _claim_matches_any(claim_type, claim, unprovenanced_research_claims):
        # M5.1/M5.4: an unprovenanced Research paraphrase is never treated as full support on its
        # own - it downgrades an otherwise-UNSUPPORTED claim to UNCERTAIN, never to SUPPORTED.
        severity = _entity_severity(claim, draft_title, "uncertain") if claim_type == "entity" else _UNCERTAIN_SEVERITY[claim_type]
        return ClaimFinding(claim=claim, claim_type=claim_type, support="uncertain", severity=severity, evidence=unprovenanced_research_claims)

    if not evidence_complete:
        # M5.3 test 14 / M5.4: missing/incomplete source evidence must never manufacture a
        # confident UNSUPPORTED verdict - the fuller article might have said this.
        return ClaimFinding(claim=claim, claim_type=claim_type, support="uncertain", severity=(
            _entity_severity(claim, draft_title, "uncertain") if claim_type == "entity" else _UNCERTAIN_SEVERITY[claim_type]
        ), evidence=[])

    severity = _entity_severity(claim, draft_title, "unsupported") if claim_type == "entity" else _UNSUPPORTED_SEVERITY[claim_type]
    return ClaimFinding(claim=claim, claim_type=claim_type, support="unsupported", severity=severity, evidence=[])


# ---------------------------------------------------------------------------
# Top-level evaluation
# ---------------------------------------------------------------------------


def _draft_status(findings: list[ClaimFinding]) -> tuple[DraftStatus, Severity | None]:
    problem_findings = [f for f in findings if f.support != "supported"]
    if not problem_findings:
        return "pass", None
    severities = [f.severity for f in problem_findings if f.severity is not None]
    if "high" in severities and any(f.support == "unsupported" and f.severity == "high" for f in problem_findings):
        return "block", "high"
    highest: Severity = "high" if "high" in severities else ("medium" if "medium" in severities else "low")
    return "review", highest


def evaluate_fact_safety(draft_title: str, draft_body: str, evidence: FactEvidence) -> dict[str, Any]:
    """Pure. No I/O, no LLM call, deterministic: identical inputs always produce an identical
    output dict. This is the M5.7 result contract's own producer."""
    draft_text = f"{draft_title}\n{draft_body}"
    draft_claims = extract_claims(draft_text)

    source_text = evidence.source_title + ("\n" + evidence.source_content if evidence.source_content else "")
    source_claims = extract_claims(source_text)
    research_text = "\n".join(evidence.research_facts)
    research_claims = extract_claims(research_text)
    provenanced_text = "\n".join(fact for fact, _url in evidence.research_facts_provenanced)
    provenanced_claims = extract_claims(provenanced_text)

    evidence_complete = evidence.source_content is not None and evidence.source_content.strip() != ""

    findings: list[ClaimFinding] = []
    for claim_type, claims in draft_claims.items():
        for claim in claims:
            findings.append(
                _classify_claim(
                    claim_type, claim, draft_title=draft_title,
                    source_claims=source_claims.get(claim_type, []),
                    provenanced_claims=provenanced_claims.get(claim_type, []),
                    unprovenanced_research_claims=research_claims.get(claim_type, []),
                    evidence_complete=evidence_complete,
                )
            )

    status, highest_risk = _draft_status(findings)
    supported = sum(1 for f in findings if f.support == "supported")
    uncertain = sum(1 for f in findings if f.support == "uncertain")
    unsupported = sum(1 for f in findings if f.support == "unsupported")

    return {
        "version": FACT_SAFETY_VERSION,
        "status": status,
        "mode": settings.fact_safety_mode,
        "claims_checked": len(findings),
        "supported": supported,
        "uncertain": uncertain,
        "unsupported": unsupported,
        "highest_risk": highest_risk,
        "findings": [
            {
                "claim": f.claim, "type": f.claim_type, "support": f.support,
                "severity": f.severity, "evidence": f.evidence,
            }
            for f in findings if f.support != "supported"
        ],
    }


def apply_fact_safety(
    news_event_title: str,
    news_event_content: str | None,
    news_event_url: str | None,
    research_output: dict[str, Any],
    copywriting_output: dict[str, Any],
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "quality" step, only after
    QualityCapability's own LLM call already succeeded. Returns `structured_output` completely
    unchanged when `fact_safety_mode == "off"` (M5.6's zero-processing rollback path).

    `copywriting_output` - NOT `structured_output` - is where the actual draft `title`/`body`
    live: `QualityCapability`'s own real output schema is `{"passed": bool, "issues": list}`
    only (confirmed by `capabilities/quality_capability.py`'s own `QUALITY_CAPABILITY_DEFINITION.
    expected_output_keys`) - it never carries the draft text itself. `copywriting_output` is
    `context.business.workflow_state.step_results["copywriting"]`, already present on the
    context with zero extra DB query, exactly like `research_output`. (A real bug during initial
    M5 development: `apply_fact_safety` originally read `title`/`body` from `structured_output`
    - i.e. Quality's own output - which is always `{}` for those two keys in production, so the
    function always silently no-opped via the guard below; only local test doubles that
    incorrectly included `title`/`body` on their *fake* Quality output masked this. Fixed in
    Phase 15 M5.2, alongside the regression test that would have caught it.)

    On "shadow"/"enforce", the original `structured_output` (`passed`/`issues`, preserved
    verbatim) is merged with a `"fact_safety"` key - purely additive, matching
    `services/editorial_scoring.py::apply_editorial_scoring_v2()`'s own established merge
    convention. Reading `structured_output["fact_safety"]["status"]` to actually change delivery
    behavior only ever happens in `enforce` mode, and only in `worker/content_cycle.py` /
    `services/content_draft_service.py` - this function itself never blocks anything.
    """
    if settings.fact_safety_mode == "off":
        return structured_output

    title = copywriting_output.get("title")
    body = copywriting_output.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        # Defensive only, mirrors apply_editorial_scoring_v2()'s identical guard: Copywriting's
        # own floor-validation already guarantees these are strings in practice - this only
        # fires if Copywriting's own step never ran or produced no result, which the workflow's
        # own step ordering (copywriting before quality) makes structurally unreachable for a
        # successfully-running "quality" step.
        return structured_output

    evidence = FactEvidence(
        source_title=news_event_title,
        source_content=news_event_content,
        source_url=news_event_url,
        research_facts=list(research_output.get("facts", [])) if isinstance(research_output.get("facts"), list) else [],
    )
    fact_safety_result = evaluate_fact_safety(title, body, evidence)

    return {**structured_output, "fact_safety": fact_safety_result}
