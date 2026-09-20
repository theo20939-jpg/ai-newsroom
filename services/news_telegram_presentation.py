"""Phase 23.1E/23.1G - Telegram NEWS compact editorial profile (docs/
phase23_1e_telegram_news_compact_profile_report.md, docs/
phase23_1g_editorial_importance_source_quality_report.md).

Root cause this addresses: Phase 23.1C's `services/content_draft_service.py::
_extract_title_and_body()` concatenates ALL of V6's narrative sections into one flat
`ContentDraft.body` blob - the correct, complete representation for persistence and Fact Safety
(which must see every claim), but far too long and repetitive once delivered as a Telegram NEWS
message (confirmed live in Phase 23.1D's own human editorial review, and again at scale in Phase
23.1F). This module is a SEPARATE, destination-specific presentation layer, operating on the
still-STRUCTURED V6 fields (never the already-flattened `ContentDraft.body`) - the core
architectural principle this phase requires:

    V6 structured output -> Fact Safety -> ContentDraft/editorial evidence -> [this module] ->
    compact Telegram NEWS card

V6 itself, `ContentDraftService`, and Fact Safety are all completely untouched by this module -
it is purely an additional, optional presentation step, applied only for `EditorialDestination.
NEWS` (worker/content_cycle.py's own router branch), never for MEME/TELEGRAPH/INSTAGRAM/REELS -
a future Telegraph article can and should still use the full, rich V6 material untouched by any
rule in this file.

Deterministic only - no LLM call. This module can SELECT and TRIM real V6 sentences; it cannot
rewrite or paraphrase them (that would require generation). "Compression" here means: choosing
which already-written sentences a human editor would keep, dropping the rest - never inventing
new wording.

Phase 23.1G: `build_compact_news_body()` now accepts a `treatment` (`services/
editorial_treatment.py`'s own `BRIEF`/`STANDARD`/`MAJOR` - never `SKIP`, which means "do not call
this at all", decided upstream) - the treatment controls both the maximum number of paragraphs
selected and the hedge-family cap (§8/§9 hardening below), never a raw character-count cutoff
(the phase brief's own explicit "do not use blind character cutting" instruction) - length differs
only as a CONSEQUENCE of selecting fewer/more real sections, never by slicing a string.
"""
from __future__ import annotations

import html
import re
from typing import Any

from services.editorial_treatment import BRIEF, MAJOR, STANDARD
from services.quote_budget import fits_within_budget, select_quote_or_omit
from services.text_normalization import normalize_loose, symmetric_token_overlap

# Mirrors services/content_draft_service.py's own _V6_REQUIRED_TEXT_KEYS (Phase 23.1C) -
# duplicated deliberately, not imported: this module must stay usable even if that module's own
# private constant's shape ever changes for ContentDraft-specific reasons unrelated to Telegram
# presentation (this codebase's own established "duplicate small helpers, don't couple modules
# that change for different reasons" convention - see e.g. content_draft_service.py's own
# check_no_hashtags()/_fact_safety_status() docstrings for the same precedent).
_V6_REQUIRED_TEXT_KEYS: tuple[str, ...] = ("opening", "context", "why_it_matters", "what_changed", "conclusion")

# Phase 23.1B/23.1D's own live-observed forced-conclusion filler patterns (§7 of the Phase 23.1E
# brief, verbatim examples) plus their direct semantic variants. Phase 23.1J.1 added its own new
# verbatim "BAD ending" examples ("время покажет" - the reversed word order from "покажет время",
# "станут известны позже", "будет продолжаться", "может стать важным шагом").
_FILLER_CONCLUSION_PATTERNS: tuple[str, ...] = (
    "станет понятнее",
    "станет понятен",
    "предстоит оценить",
    "остается следить",
    "остаётся следить",
    "покажет время",
    "время покажет",
    "появятся позже",
    "появится позже",
    "станут известны позже",
    "станет известно позже",
    "это скорее сигнал",
    "покажет истинный",
    "покажет дальнейшее",
    "развитие покажет",
    "будет зависеть от того, как",
    "будет продолжаться",
    "может стать важным шагом",
)

# Phase 23.1G §9: generic, low-information "this is interesting/important" statements that carry
# no concrete fact - the phase brief's own verbatim examples. Checked against EVERY section (not
# only conclusion), but deliberately narrow (a fixed phrase list, not a generative "is this vague"
# classifier) - per the brief's own explicit "do not blanket-ban useful why it matters; require a
# concrete reason" instruction, this only ever catches sentences that are ALREADY, lexically,
# these specific generic-significance patterns - a why_it_matters sentence that states a concrete
# consequence is never touched by this list.
_GENERIC_LOW_INFORMATION_PATTERNS: tuple[str, ...] = (
    "тема заслуживает внимания",
    "потенциально важное направление",
    "заслуживает внимания на стыке",
    "идея связывает вычислительные методы",
    "представляет интерес для",
)

# Phase 23.1G §8 "Hedge / Uncertainty Hardening V2": Phase 23.1E's own single flat hedge-marker
# list caught only some of the real Phase 23.1F hedging (the live virus/bacteria story still
# expressed caution in nearly every section, using phrasings V1's own narrower list did not
# recognize as the SAME underlying caution). Grouped into named semantic families - not because
# each family needs individually different handling, but so the cap below can be "at most one
# paragraph per family" rather than "at most one hedge-flavored paragraph in the whole post"
# collapsing to the same effective behavior V1 had. Still a fixed, explicit, non-generative phrase
# list (this codebase's own repeated "не создавай universal NLP engine" discipline) - grouped by
# meaning, not guessed at via embeddings/similarity.
_HEDGE_FAMILIES: dict[str, tuple[str, ...]] = {
    "undisclosed": (
        "не раскрыл", "не уточнен", "не уточнил", "не сообщил", "не указан", "не привел",
        "пока не уточнены", "не содержат сведений",
        # Phase 23.1Q: inflected forms a live canary showed this family was missing (e.g.
        # "неизвестны", "не раскрываются", "отсутствует") - the exact stems v8.6's own rewritten
        # UNCERTAINTY rule was written to stop generating in the first place; these are
        # defense-in-depth coverage for this existing collapse-against-main_body mechanism only,
        # never a new stripping subsystem and never a materiality judgment on their own.
        "неизвестн", "не раскрыва", "отсутству",
    ),
    "insufficient_evidence": (
        "данных недостаточно", "недостаточно данных", "недостаточно, чтобы", "остаются открытыми",
        "insufficient",
    ),
    "unconfirmed": (
        "не подтвержд", "неподтвержд", "not confirmed", "unconfirmed",
    ),
    "requires_verification": (
        "требует дополнительной проверки", "требующее дополнительной проверки", "требует проверки",
        "нуждается в проверке", "независимого подтверждения",
    ),
    "ambiguous_reference": (
        "неясно, идет ли речь", "неясно, идёт ли речь", "непонятно, идет ли речь",
    ),
    "signal_not_result": (
        "это только заявление", "это лишь заявление", "это скорее сигнал",
    ),
}

# How many distinct hedge FAMILIES a treatment tier may keep, at most one paragraph representing
# each - phase brief §8: "DEFAULT: 0... ORDINARY MAX: 1... Only MAJOR stories with genuinely
# different material caveats may exceed 1." BRIEF/STANDARD both cap at 1 (the phase brief never
# distinguishes them on this axis); MAJOR allows up to 2 genuinely distinct families, never
# unbounded.
_MAX_HEDGE_FAMILIES_BY_TREATMENT: dict[str, int] = {BRIEF: 1, STANDARD: 1, MAJOR: 2}

# Maximum paragraphs selected per treatment tier (phase brief §3's own target structures) - the
# ONLY mechanism controlling output length; never a character-count truncation.
_MAX_PARAGRAPHS_BY_TREATMENT: dict[str, int] = {BRIEF: 2, STANDARD: 3, MAJOR: 4}

# Phase 23.1I Part E "Importance-Aware Brevity V2": length is a CEILING (an editorial target that
# governs whether to ADD another paragraph), never a target to fill and never a string-slicing
# boundary - no paragraph is ever cut mid-sentence to fit one of these numbers. Reasoned starting
# points from the phase brief's own explicit approximate ranges (BRIEF ~150-350/450 ceiling,
# STANDARD ~250-500/650 ceiling, MAJOR ~350-700/900 ceiling) - ONLY the ceiling (the ~450/650/900
# figures) is enforced deterministically here; the lower "normal" figures describe expected
# real-world outcomes once V7's own "importance does not imply length" prompt rule (prompts/
# copywriting/v7.yaml) makes the underlying V6-shaped text itself more concise, not a second
# mechanism enforced in this module.
_CHAR_CEILING_BY_TREATMENT: dict[str, int] = {BRIEF: 450, STANDARD: 650, MAJOR: 900}

# Phase 23.1I Part E "the two-paragraph default": the first two core paragraphs (what happened +
# why it matters, in `_candidate_paragraphs()`'s own priority order) are always kept when present,
# regardless of the character ceiling above - a real paragraph is never dropped purely for length,
# only ADDING a third/fourth is ever gated by the ceiling.
_DEFAULT_PARAGRAPH_COUNT = 2

# Deliberately narrow and conservative (§5/§6 of the Phase 23.1E brief: "Default: 0 uncertainty
# statements" - the bias must be toward omission). Only strong, unambiguous material signals.
_MATERIAL_UNCERTAINTY_KEYWORDS: tuple[str, ...] = (
    "цена", "цену", "цены", "стоимост", "тариф", "price", "cost", "pricing",
    "сделк", "закры", "deal", "closing",
    "слух", "утечк", "неподтвержд", "не подтвержд", "rumor", "leak", "unverified", "unconfirmed",
    "оспарива", "спорн", "disputed",
)

_ENUMERATION_SPLIT_RE = re.compile(r",\s*(?:а также|и|либо)\s+|;\s*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_REDUNDANCY_THRESHOLD = 0.5
_OPTIONAL_REDUNDANCY_THRESHOLD = 0.3


def _is_v6_shaped(copywriting_output: dict[str, Any]) -> bool:
    return all(isinstance(copywriting_output.get(key), str) for key in _V6_REQUIRED_TEXT_KEYS)


def _is_filler(text: str) -> bool:
    normalized = normalize_loose(text)
    if any(pattern in normalized for pattern in _FILLER_CONCLUSION_PATTERNS):
        return True
    return any(pattern in normalized for pattern in _GENERIC_LOW_INFORMATION_PATTERNS)


def _hedge_family(text: str) -> str | None:
    """Returns the name of the first hedge family `text` matches, or `None` if it isn't
    hedge-flavored at all. A paragraph can only ever belong to one family for this module's own
    bookkeeping purposes (the first match wins) - real hedge sentences overwhelmingly express one
    dominant caution, and this module's job is capping repetition, not exhaustively tagging every
    clause."""
    normalized = normalize_loose(text)
    for family, markers in _HEDGE_FAMILIES.items():
        if any(marker in normalized for marker in markers):
            return family
    return None


def _is_distinct(candidate: str, already_selected: list[str], *, threshold: float = _REDUNDANCY_THRESHOLD) -> bool:
    return all(symmetric_token_overlap(candidate, existing) < threshold for existing in already_selected)


def _first_sentence(text: str) -> str:
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return sentences[0].strip() if sentences and sentences[0].strip() else text.strip()


def _extract_material_caveat(what_remains_unknown: str) -> str | None:
    """Returns a single, trimmed caveat sentence when `what_remains_unknown` is a focused,
    material statement - `None` (omit entirely) when it is either a multi-item enumeration of
    generic unknowns (the common, non-material case) or contains no strong material signal at
    all."""
    text = what_remains_unknown.strip()
    if not text:
        return None
    segments = [s for s in _ENUMERATION_SPLIT_RE.split(text) if s.strip()]
    if len(segments) > 1:
        return None
    normalized = normalize_loose(text)
    if not any(keyword in normalized for keyword in _MATERIAL_UNCERTAINTY_KEYWORDS):
        return None
    return _first_sentence(text)


def _candidate_paragraphs(copywriting_output: dict[str, Any]) -> list[str]:
    """Builds the full, ordered list of candidate paragraphs from V6's structured fields, applying
    the redundancy/filler checks Phase 23.1E already established - but WITHOUT any hedge-budget or
    paragraph-count limiting (that happens once, globally, in `build_compact_news_body()` itself,
    per Phase 23.1G's own "hedge cap must apply across every section, not just the optional ones"
    finding - see that function's own docstring for why V1's per-section budget tracking was not
    strict enough)."""
    paragraphs: list[str] = []

    opening = copywriting_output.get("opening")
    if isinstance(opening, str) and opening.strip() and not _is_filler(opening):
        paragraphs.append(opening.strip())

    why_it_matters = copywriting_output.get("why_it_matters")
    if (
        isinstance(why_it_matters, str) and why_it_matters.strip()
        and not _is_filler(why_it_matters) and _is_distinct(why_it_matters, paragraphs)
    ):
        paragraphs.append(why_it_matters.strip())

    what_changed = copywriting_output.get("what_changed")
    if (
        isinstance(what_changed, str) and what_changed.strip()
        and not _is_filler(what_changed) and _is_distinct(what_changed, paragraphs)
    ):
        paragraphs.append(what_changed.strip())

    context = copywriting_output.get("context")
    if (
        isinstance(context, str) and context.strip() and not _is_filler(context)
        and _is_distinct(context, paragraphs, threshold=_OPTIONAL_REDUNDANCY_THRESHOLD)
    ):
        paragraphs.append(context.strip())

    what_happens_next = copywriting_output.get("what_happens_next")
    if (
        isinstance(what_happens_next, str) and what_happens_next.strip() and not _is_filler(what_happens_next)
        and _is_distinct(what_happens_next, paragraphs, threshold=_OPTIONAL_REDUNDANCY_THRESHOLD)
    ):
        paragraphs.append(what_happens_next.strip())

    conclusion = copywriting_output.get("conclusion")
    if (
        isinstance(conclusion, str) and conclusion.strip() and not _is_filler(conclusion)
        and _is_distinct(conclusion, paragraphs, threshold=_OPTIONAL_REDUNDANCY_THRESHOLD)
    ):
        paragraphs.append(conclusion.strip())

    return paragraphs


def _candidate_caveat(copywriting_output: dict[str, Any], core_paragraphs: list[str]) -> str | None:
    """The material `what_remains_unknown` caveat, kept separate from `_candidate_paragraphs()`'s
    own core list - see `build_compact_news_body()`'s own docstring for why: it must survive the
    paragraph-count truncation whenever it survives the hedge-family cap, never compete for the
    same fixed slots as `why_it_matters`/`context`/etc. purely by construction order."""
    what_remains_unknown = copywriting_output.get("what_remains_unknown")
    if not isinstance(what_remains_unknown, str) or not what_remains_unknown.strip():
        return None
    caveat = _extract_material_caveat(what_remains_unknown)
    if caveat is None or not _is_distinct(caveat, core_paragraphs, threshold=_OPTIONAL_REDUNDANCY_THRESHOLD):
        return None
    return caveat


def _apply_hedge_cap(paragraphs: list[str], *, max_families: int) -> list[str]:
    """Global pass, across EVERY candidate paragraph (opening included) - keeps at most
    `max_families` distinct hedge families, one representative paragraph each (the first, i.e.
    earliest-selected, occurrence of a family survives; later paragraphs in an already-claimed
    family are dropped outright). Non-hedge paragraphs are never touched. This is the Phase 23.1G
    fix for the real, live gap Phase 23.1E's own per-optional-section budget missed: a thin story
    whose `opening`, `why_it_matters`, AND `what_changed` are ALL independently hedge-flavored
    (the real virus/bacteria story, Phase 23.1F) previously kept all three, since V1 only ever
    capped the OPTIONAL sections once a CORE section had already "spent" the budget - core
    sections themselves were never subject to the cap. This function applies the cap uniformly."""
    kept: list[str] = []
    claimed_families: set[str] = set()
    for paragraph in paragraphs:
        family = _hedge_family(paragraph)
        if family is None:
            kept.append(paragraph)
            continue
        if family in claimed_families:
            continue
        if len(claimed_families) >= max_families:
            continue
        claimed_families.add(family)
        kept.append(paragraph)
    return kept


def _select_within_ceiling(candidates: list[str], *, max_paragraphs: int, char_ceiling: int) -> list[str]:
    """Phase 23.1I Part E: the first `_DEFAULT_PARAGRAPH_COUNT` candidates (already ordered by
    `_candidate_paragraphs()`'s own what-happened/why-it-matters priority) are always kept when
    present - never dropped purely for length, only capped by `max_paragraphs` itself. Beyond that
    default, an additional candidate is kept only while both `max_paragraphs` and `char_ceiling`
    still have room - a genuinely distinct third/fourth fact (already guaranteed distinct by
    `_candidate_paragraphs()`'s own redundancy filtering) is welcome only while it still fits the
    editorial length target; once it would push the post over the ceiling, selection stops there -
    never by slicing the paragraph that would have gone over, only by not including it at all."""
    if not candidates:
        return []
    selected = candidates[: min(_DEFAULT_PARAGRAPH_COUNT, len(candidates), max(1, max_paragraphs))]
    running_length = len("\n\n".join(selected))
    for candidate in candidates[len(selected):]:
        if len(selected) >= max_paragraphs:
            break
        candidate_length = running_length + 2 + len(candidate)  # +2 for the "\n\n" join separator
        if candidate_length > char_ceiling:
            break
        selected.append(candidate)
        running_length = candidate_length
    return selected


def build_compact_news_body(copywriting_output: dict[str, Any], *, treatment: str = STANDARD) -> str:
    """The one entry point this module exposes. Pure, deterministic: identical input always
    produces identical output.

    V4 (or any schema without V6's required sections): returns `body` unchanged (or `""` if
    neither `body` nor V6's sections are present) - this module never touches non-V6 drafts.

    V6: builds the full candidate paragraph list (`_candidate_paragraphs()` - opening, why_it_
    matters/what_changed, context, what_happens_next, conclusion, a material unknown-caveat, each
    already filtered for redundancy/filler), then applies two GLOBAL caps, in order:
    1. `_apply_hedge_cap()` - at most `treatment`'s own hedge-family budget (1 for BRIEF/STANDARD,
       2 for MAJOR) survives, across the WHOLE post, not per-section.
    2. A paragraph-count cap (`_MAX_PARAGRAPHS_BY_TREATMENT`) - BRIEF keeps at most 2 paragraphs,
       STANDARD 3, MAJOR 6 - truncating the already-selected LIST of paragraphs (never a string,
       never mid-sentence) from the end, so the highest-priority sections (opening, why_it_
       matters/what_changed) are always kept first. The material `what_remains_unknown` caveat
       (when it survives the hedge-family cap) has its own reserved slot and is never truncated
       away purely because it happens to be last in construction order - a real bug found and
       fixed during this phase's own test-first development (Cases C/H, §16 of the report).

    `treatment` must be one of `services.editorial_treatment.BRIEF/STANDARD/MAJOR` - never `SKIP`
    (a SKIP decision means "do not call this function at all," decided by the caller before any
    Copywriting/presentation work happens). Defaults to `STANDARD` for backward compatibility with
    any caller that does not yet pass a treatment (Phase 23.1E's own original call shape).
    """
    if not _is_v6_shaped(copywriting_output):
        body = copywriting_output.get("body")
        return body if isinstance(body, str) else ""

    max_families = _MAX_HEDGE_FAMILIES_BY_TREATMENT.get(treatment, 1)
    max_paragraphs = _MAX_PARAGRAPHS_BY_TREATMENT.get(treatment, 3)
    char_ceiling = _CHAR_CEILING_BY_TREATMENT.get(treatment, 650)

    core_paragraphs = _candidate_paragraphs(copywriting_output)
    caveat = _candidate_caveat(copywriting_output, core_paragraphs)
    combined: list[str] = list(core_paragraphs)
    if caveat is not None:
        combined.append(caveat)
    combined = _apply_hedge_cap(combined, max_families=max_families)

    paragraphs: list[str]
    if caveat is not None and caveat in combined:
        # The caveat has its own reserved slot (never competes with core paragraphs for the same
        # budget purely by construction order - see this function's own docstring) - the core
        # selector gets one fewer paragraph slot and a character budget reduced by the caveat's
        # own length, so the combined result still respects the treatment's overall ceiling.
        core_candidates = [p for p in combined if p != caveat]
        core_kept = _select_within_ceiling(
            core_candidates, max_paragraphs=max(1, max_paragraphs - 1),
            char_ceiling=max(0, char_ceiling - len(caveat) - 2),
        )
        paragraphs = core_kept + [caveat]
    else:
        paragraphs = _select_within_ceiling(combined, max_paragraphs=max_paragraphs, char_ceiling=char_ceiling)

    if not paragraphs:
        # Safety net, not an expected path: every candidate was filtered (filler/redundant/hedge-
        # capped) - never deliver a completely empty NEWS body. Falls back to `opening` verbatim,
        # unfiltered - V6's own prompt rules already guarantee it is "a strong, concrete hook," so
        # this is a safe, always-available last resort, not a guess.
        opening = copywriting_output.get("opening")
        return opening.strip() if isinstance(opening, str) else ""

    return "\n\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Phase 23.1J: V8 presentation (docs/phase23_1j_copywriting_v8_report.md) - a genuinely smaller
# shape than V6/V7 (title/main_body/ending/expandable_details/quote, not seven/eight sections),
# so this section is deliberately NOT a branch inside build_compact_news_body() above - V8's own
# job is much lighter (mostly a safety-net ceiling check; the V8 prompt itself, prompts/
# copywriting/v8.yaml, is the PRIMARY brevity mechanism, per the phase brief's own explicit "do
# not solve bad copy with truncation" instruction) and produces a genuinely different final
# artifact (a complete, ready-to-send HTML string including a Telegram expandable blockquote and
# a deterministic footer link neither V6 nor V7 ever needed).
# ---------------------------------------------------------------------------

# Phase 23.1J §9: V8's own, tighter soft ceilings - deliberately different numbers from
# _CHAR_CEILING_BY_TREATMENT above (V7's 450/650/900), per the phase brief's own explicit new
# targets. A *soft* ceiling only (never a hard truncation wall) - governs whether the optional
# `ending` paragraph is appended on top of the mandatory `main_body`, never a reason to cut
# `main_body` itself (the one mandatory field always survives whole).
_V8_SOFT_CEILING_BY_TREATMENT: dict[str, int] = {BRIEF: 280, STANDARD: 450, MAJOR: 600}
# MAJOR's own documented "exceptional" allowance (phase brief §9: "up to ~750 characters ONLY
# when removing the additional information would materially reduce the reader's understanding of
# a genuinely major story") - a wider grace margin for MAJOR only, still never a hard wall.
_V8_EXCEPTIONAL_CEILING_BY_TREATMENT: dict[str, int] = {BRIEF: 280, STANDARD: 450, MAJOR: 750}

_NINJA_PULSE_URL = "https://t.me/ninja_pulse"
_NINJA_PULSE_TEXT = "NINJA PULSE. Подписаться 🥷"


def _v8_escape(value: str) -> str:
    """Mirrors bot/formatting.py's own `_escape()` exactly (html.escape, quote=False) - duplicated
    deliberately, not imported, per this module's own established "small, single-purpose helpers
    are duplicated, not cross-coupled" convention (see this file's own opening docstring)."""
    return html.escape(value, quote=False)


def _is_v8_shaped(copywriting_output: dict[str, Any]) -> bool:
    return isinstance(copywriting_output.get("main_body"), str) and bool(copywriting_output["main_body"].strip())


def build_v8_news_body(copywriting_output: dict[str, Any], *, treatment: str = STANDARD) -> str:
    """V8's analogue of `build_compact_news_body()` above, but far simpler: `main_body` (the one
    mandatory field, already written as 1-2 paragraphs by the V8 prompt itself) always survives
    whole and unsplit - this function never breaks it apart or truncates it. `ending` is appended
    only when it passes the same filler/redundancy/hedge-family checks V6/V7 already established,
    AND only while the combined length stays within V8's own, tighter soft ceiling (a safety net,
    not the primary brevity mechanism - see this section's own header comment). Returns `""` when
    `main_body` itself is missing/empty (never expected in practice - V8's schema marks it
    required - but never silently substitutes something else)."""
    main_body = copywriting_output.get("main_body")
    if not isinstance(main_body, str) or not main_body.strip():
        return ""
    main_body = main_body.strip()

    parts = [main_body]
    ending = copywriting_output.get("ending")
    if isinstance(ending, str) and ending.strip():
        ending = ending.strip()
        if not _is_filler(ending) and _is_distinct(ending, parts, threshold=_OPTIONAL_REDUNDANCY_THRESHOLD):
            main_family = _hedge_family(main_body)
            ending_family = _hedge_family(ending)
            # Same hedge family as main_body already expressed -> the SAME caution restated, drop
            # it (phase brief §14/§15: "one uncertainty maximum," "no repetition").
            if ending_family is None or ending_family != main_family:
                exceptional_ceiling = _V8_EXCEPTIONAL_CEILING_BY_TREATMENT.get(treatment, 450)
                candidate_len = len(main_body) + 2 + len(ending)
                if candidate_len <= exceptional_ceiling:
                    parts.append(ending)

    return "\n\n".join(parts)


def build_v8_expandable_details(copywriting_output: dict[str, Any]) -> str | None:
    """The raw (unescaped) `expandable_details` text, filler-filtered - `None` when absent, blank,
    or filler. Kept as plain text (not yet wrapped in a `<blockquote expandable>` tag) so callers
    that only need the persisted/Fact-Safety-checked text (services/content_draft_service.py,
    services/fact_safety.py) and callers that need the rendered Telegram HTML (`render_v8_news_
    card_html()` below) can both use this one function without duplicating the filter logic."""
    expandable = copywriting_output.get("expandable_details")
    if not isinstance(expandable, str) or not expandable.strip():
        return None
    text = expandable.strip()
    if _is_filler(text):
        return None
    return text


def build_ninja_pulse_footer_html() -> str:
    """Phase 23.1J §20-22: the deterministic channel-subscription footer - NEVER generated by the
    LLM (no tokens spent on it, no field for it in prompts/copywriting/v8.yaml's own output
    schema), appended by this presentation layer only, exactly once, per card. The entire visible
    text "NINJA PULSE. Подписаться 🥷" is the clickable anchor - the raw URL is never visible
    (mirrors the existing `[🔗 Источник]` inline-button convention of never showing a raw URL in
    the body, applied here to an in-text anchor instead of a button, since this is meant to read
    as a normal sentence-ending line, not a second button)."""
    return f'<a href="{_NINJA_PULSE_URL}">{_v8_escape(_NINJA_PULSE_TEXT)}</a>'


def render_v8_news_card_html(copywriting_output: dict[str, Any], *, treatment: str = STANDARD) -> str:
    """The complete, ready-to-send Telegram HTML string for a V8 card: HEADLINE (bold) + MAIN BODY
    (+ optional ENDING) + optional EXPANDABLE BLOCKQUOTE + the NINJA PULSE footer - exactly the
    layout phase brief §1/§21 specifies. The `[🔗 Источник]` source button is NOT part of this
    string (it is a separate inline keyboard, attached by the caller - `worker/content_cycle.py` -
    exactly as it already is for every other treatment/version, unchanged this phase).

    Every piece of real editorial text (headline, body, ending, expandable details) is escaped
    here, at the one point where it is embedded into HTML markup - mirrors bot/formatting.py's own
    "escape at render time, never on the stored value" discipline. The footer's own anchor text is
    a fixed, already-known-safe constant (`_NINJA_PULSE_TEXT`), escaped the same way for
    consistency, not because it could ever contain untrusted content.

    Falls back to a title-only render (headline + a body placeholder) when `main_body` is missing/
    unusable - never raises, never sends a completely empty card body."""
    title = copywriting_output.get("title")
    headline = title.strip() if isinstance(title, str) and title.strip() else "(no headline generated)"

    body = build_v8_news_body(copywriting_output, treatment=treatment)
    body_block = _v8_escape(body) if body else "(no body generated)"

    blocks = [f"<b>{_v8_escape(headline)}</b>", body_block]

    expandable_text = build_v8_expandable_details(copywriting_output)
    if expandable_text is not None:
        blocks.append(f"<blockquote expandable>{_v8_escape(expandable_text)}</blockquote>")

    blocks.append(build_ninja_pulse_footer_html())

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Phase 23.1J.1: V8.1 presentation (docs/phase23_1j1_v81_review.md) - human review of V8's own
# golden replay asked for an even simpler format. Telegram NEWS is a fast-scrolling feed, not an
# article: HEADLINE + exactly ONE main-body paragraph + OPTIONAL ending. No expandable-details
# concept for normal NEWS delivery (the V8 expandable-blockquote machinery above is kept
# untouched for a possible future format, simply never invoked here). The NINJA PULSE footer is
# built but NOT included by default - `render_v81_news_card_html()`'s own `include_ninja_pulse_
# footer` parameter defaults to False this phase, per the phase brief's own explicit "disable it
# from normal NEWS delivery unless explicitly enabled" instruction.
# ---------------------------------------------------------------------------

# Copywriting 8.9: the old treatment-specific editorial ceilings no longer suppress a valid,
# distinct ending. Padding remains blocked by the existing filler/redundancy/hedge filters; final
# whole-card safety is governed only by Telegram's actual hard limit below.

_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n+")


def _collapse_to_one_paragraph(text: str) -> str:
    """Defense-in-depth for V8.1's own "MAIN BODY RULE - ABSOLUTE: exactly ONE paragraph, never
    split" prompt instruction - the prompt is the primary mechanism (per this module's own
    established "do not solve bad copy with truncation/reshaping" discipline), this is a safety
    net only, for the rare case the model still emits an internal paragraph break. Collapses any
    run of blank-line(s) into a single space - never drops content, never truncates, only removes
    the break itself."""
    return _PARAGRAPH_BREAK_RE.sub(" ", text.strip())


def _is_v81_shaped(copywriting_output: dict[str, Any]) -> bool:
    return isinstance(copywriting_output.get("main_body"), str) and bool(copywriting_output["main_body"].strip())


def is_v8_family_output(copywriting_output: dict[str, Any]) -> bool:
    """Public shape-detector for `worker/content_cycle.py`'s own router branch (Phase 23.1K -
    docs/phase23_1k_v82_live_canary_report.md §2): True for V8/V8.1/V8.2 output (all three share
    the identical `main_body`-keyed shape - V8.2 is a pure prompt-wording refinement of V8.1, not
    a schema change, confirmed directly). False for V4 (`body`) or V6/V7 (`opening`/`context`/...)
    output, which the caller should keep routing through the existing `build_compact_news_body()`
    + `render_editorial_card()` path, completely unchanged."""
    return _is_v81_shaped(copywriting_output)


def diagnose_v81_ending(
    copywriting_output: dict[str, Any], *, rendered_html: str | None = None,
) -> dict[str, str]:
    """Explain whether the model-produced ending survives deterministic quality filters.

    This diagnostic is intentionally transient: no schema or DB change, and no audience-visible
    labels. Telegram hard-limit handling occurs later, after title/quote/footer composition.
    """
    main_body = copywriting_output.get("main_body")
    ending = copywriting_output.get("ending")
    generated = isinstance(ending, str) and bool(ending.strip())
    result = {
        "ending_generated": "yes" if generated else "no",
        "ending_rendered": "no",
        "ending_drop_reason": "null_from_model" if not generated else "other",
    }
    if not generated:
        return result
    if not isinstance(main_body, str) or not main_body.strip():
        return result

    normalized_body = _collapse_to_one_paragraph(main_body)
    normalized_ending = _collapse_to_one_paragraph(ending)
    if _is_filler(normalized_ending):
        result["ending_drop_reason"] = "filler"
        return result
    if not _is_distinct(normalized_ending, [normalized_body], threshold=_OPTIONAL_REDUNDANCY_THRESHOLD):
        result["ending_drop_reason"] = "redundant"
        return result
    body_family = _hedge_family(normalized_body)
    ending_family = _hedge_family(normalized_ending)
    if ending_family is not None and ending_family == body_family:
        result["ending_drop_reason"] = "duplicate_hedge"
        return result

    result["ending_rendered"] = "yes"
    result["ending_drop_reason"] = "none"
    if rendered_html is not None and _v8_escape(normalized_ending) not in rendered_html:
        result["ending_rendered"] = "no"
        result["ending_drop_reason"] = "telegram_hard_limit"
    return result


def build_v81_news_body(copywriting_output: dict[str, Any], *, treatment: str = STANDARD) -> str:
    """Render V8-family main body plus a distinct, non-filler ending as whole paragraphs.

    `treatment` remains accepted for API compatibility, but its former editorial character ceiling
    no longer silently removes a valid ending. Actual Telegram hard safety is enforced after the
    complete card is composed, without truncating either paragraph.
    """
    del treatment
    main_body = copywriting_output.get("main_body")
    if not isinstance(main_body, str) or not main_body.strip():
        return ""
    main_body = _collapse_to_one_paragraph(main_body)

    parts = [main_body]
    diagnostic = diagnose_v81_ending(copywriting_output)
    if diagnostic["ending_rendered"] == "yes":
        ending = copywriting_output["ending"]
        parts.append(_collapse_to_one_paragraph(ending))

    return "\n\n".join(parts)


_V81_QUOTE_SAFE_LIMIT = 4096  # Telegram's own hard message limit, in UTF-16 code units - mirrors
# bot/formatting.py's own SAFE_LIMIT exactly (duplicated, not imported, per this module's own
# established "small, single-purpose helpers are duplicated, not cross-coupled" convention).


def _v81_telegram_utf16_length(text: str) -> int:
    """Duplicated from bot/formatting.py's own private `_telegram_utf16_length()` intentionally -
    the exact same one-line UTF-16 code-unit formula (Telegram's length limits are measured in
    UTF-16 code units, not Python's `len()`)."""
    return len(text.encode("utf-16-le")) // 2


def _v81_quote_block_html(quote_text: str, quote_speaker: str | None) -> str:
    """The V8.1 analogue of bot/formatting.py's own `_quote_block_text()` - identical shape
    (💬 emoji + a real Telegram-native, non-expandable `<blockquote>` + an em-dash speaker line),
    reused deliberately so quote presentation reads identically regardless of which card format
    delivered it. Not expandable (unlike V8's `expandable_details` block) - a quote should always
    be visible immediately, never collapsed."""
    speaker_suffix = f"\n— {_v8_escape(quote_speaker)}" if quote_speaker else ""
    return f"\U0001F4AC <blockquote>{_v8_escape(quote_text)}</blockquote>{speaker_suffix}"


def render_v81_news_card_html(
    copywriting_output: dict[str, Any], *, treatment: str = STANDARD, include_ninja_pulse_footer: bool = False,
    quote_text: str | None = None, quote_speaker: str | None = None,
) -> str:
    """The complete, ready-to-send Telegram HTML string for a V8.1 card: HEADLINE (bold) + ONE
    main-body paragraph (+ optional ENDING as its own second paragraph) + optional QUOTE block. No
    expandable-blockquote block, ever, for this format. The `[🔗 Источник]` source button is NOT
    part of this string (a separate inline keyboard, attached by the caller, exactly as for every
    other version/treatment, unchanged this phase). `include_ninja_pulse_footer` defaults to
    `False` this phase (docs/phase23_1j1_v81_review.md - "keep implementation isolated, but
    disable it from normal NEWS delivery unless explicitly enabled") - the footer function itself
    (`build_ninja_pulse_footer_html()`) is unchanged and still directly callable/testable.

    Falls back to a title-only render when `main_body` is missing/unusable - never raises, never
    sends a completely empty card body.

    `quote_text`/`quote_speaker` (Phase 23.1Q): the caller's own already-resolved, already-
    verified quote (worker/content_cycle.py resolves this via services/quote_lookup.py's
    get_quote_for_draft() + resolve_display_text(), gated by settings.quote_telegram_rendering_
    mode - this function never looks anything up itself, never trusts an unverified raw quote).
    Rendered with bot/formatting.py's own established `<blockquote>` convention, appended after
    the main body (mirrors that module's own `_render_once()` block order: body, then quote).
    Omitted entirely - never partially rendered - when: no quote was resolved
    (`quote_text` is `None`/empty); the quote materially repeats a sentence already in the body
    (`_is_distinct()`, the same check/threshold already used for `ending`); or including it would
    push the whole card past Telegram's hard message-length ceiling (`fits_within_budget()`/
    `select_quote_or_omit()`, the exact same pure functions bot/formatting.py's own quote budget
    already uses - never a second, divergent length rule)."""
    title = copywriting_output.get("title")
    headline = title.strip() if isinstance(title, str) and title.strip() else "(no headline generated)"

    body = build_v81_news_body(copywriting_output, treatment=treatment)
    body_block = _v8_escape(body) if body else "(no body generated)"

    blocks = [f"<b>{_v8_escape(headline)}</b>", body_block]

    if quote_text and _is_distinct(quote_text, [body] if body else [], threshold=_OPTIONAL_REDUNDANCY_THRESHOLD):
        candidate_block = _v81_quote_block_html(quote_text, quote_speaker)
        non_quote_length = _v81_telegram_utf16_length("\n\n".join(blocks))
        quote_block_length = _v81_telegram_utf16_length("\n\n" + candidate_block)
        fits = fits_within_budget(
            non_quote_blocks_length=non_quote_length, quote_block_length=quote_block_length,
            limit=_V81_QUOTE_SAFE_LIMIT,
        )
        selected_text, _ = select_quote_or_omit(quote_text, quote_speaker, fits=fits)
        if selected_text is not None:
            blocks.append(candidate_block)

    if include_ninja_pulse_footer:
        blocks.append(build_ninja_pulse_footer_html())

    rendered = "\n\n".join(blocks)
    if _v81_telegram_utf16_length(rendered) <= _V81_QUOTE_SAFE_LIMIT:
        return rendered

    # Whole-block fallback only: a valid ending may be suppressed solely by Telegram's actual
    # hard limit, never by an editorial treatment ceiling. Nothing is truncated. If no ending
    # survived the quality filters, preserve the pre-existing base-card behavior and never recurse.
    diagnostic = diagnose_v81_ending(copywriting_output)
    if diagnostic["ending_rendered"] == "yes":
        without_ending = dict(copywriting_output)
        without_ending["ending"] = None
        return render_v81_news_card_html(
            without_ending,
            treatment=treatment,
            include_ninja_pulse_footer=include_ninja_pulse_footer,
            quote_text=quote_text,
            quote_speaker=quote_speaker,
        )
    return rendered


def render_compact_news_card_html(
    title: str, body: str, *, quote_text: str | None = None, quote_speaker: str | None = None,
) -> str:
    """Phase V2.7 §3-5 forensic + fix: the clean, reader-facing card for every copywriting
    schema `render_v81_news_card_html()` above does NOT cover - V4's plain `title`/`body`, or
    V6/V7's `build_compact_news_body()`-already-compacted body. Byte-for-byte the same minimal
    shape Phase 23.1K established for V8 (HEADLINE + body + optional quote - no internal
    "\U0001F4F0 category · date" header row, no raw source-language title, no event metadata):
    `worker/content_cycle.py`'s router-mode branch previously left `html=None` for any non-V8
    shape, which fell through to `bot/formatting.py::render_editorial_card()` - the internal
    `/news` editorial-INBOX-REVIEW template (`services/editorial_inbox_service.py`'s own
    original consumer), never designed or intended as a real reader-facing send. That fallthrough
    was itself an existing, deliberately-commented design choice ("V4/V6/V7 output... keep using
    the exact same render_editorial_card() path as always") - not a defect introduced by any V2.x
    phase - but it violates this project's own "reader-facing output must not contain internal/
    debug/source metadata" contract the moment router-mode delivery is actually used with
    anything other than V8-family copywriting output (as V2.6's real canary was, since production
    `copywriting_prompt_version` is pinned to "4"). This function closes that gap without
    inventing a new editorial style - `title`/`body` are used exactly as already persisted onto
    `ContentDraft.title`/`.body` (`services/content_draft_service.py::_extract_title_and_body()`),
    never re-derived or rewritten. The `[\U0001F517 Источник]`
    source button is NOT part of this string (unchanged - a separate inline keyboard, attached by
    the caller, exactly as for every other card shape)."""
    headline = title.strip() if title.strip() else "(no headline generated)"
    body_block = _v8_escape(body.strip()) if body.strip() else "(no body generated)"

    blocks = [f"<b>{_v8_escape(headline)}</b>", body_block]

    if quote_text and _is_distinct(quote_text, [body] if body else [], threshold=_OPTIONAL_REDUNDANCY_THRESHOLD):
        candidate_block = _v81_quote_block_html(quote_text, quote_speaker)
        non_quote_length = _v81_telegram_utf16_length("\n\n".join(blocks))
        quote_block_length = _v81_telegram_utf16_length("\n\n" + candidate_block)
        fits = fits_within_budget(
            non_quote_blocks_length=non_quote_length, quote_block_length=quote_block_length,
            limit=_V81_QUOTE_SAFE_LIMIT,
        )
        selected_text, _ = select_quote_or_omit(quote_text, quote_speaker, fits=fits)
        if selected_text is not None:
            blocks.append(candidate_block)

    return "\n\n".join(blocks)
