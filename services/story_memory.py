"""Story Memory Layer (Phase 18.10 M1/M2, docs/phase18_10_editorial_intelligence_report.md).

Recognizes when a new NewsEvent is likely describing the same developing real-world story as one
already seen, so the system can link it as an update (or flag it as a near-duplicate rehash from
a different source) instead of treating every source's coverage of the same event as an
unrelated new item.

Deliberately deterministic and narrow - no embeddings, no vector store, no new LLM capability
(this codebase has neither pgvector nor any embedding column anywhere, and this phase does not
add one). Reuses services/text_normalization.py, which is explicitly documented as "the shared
layer for entity/phrase matching" and "deliberately NOT a general NLP engine" - a fixed, small,
explicit set of narrow rules, exactly the convention this module follows too (mirrors
services/fact_safety.py's and services/image_deduplication.py's own hand-curated, threshold-based
style, never a statistical/ML model).

Split into a pure calculator (`extract_story_signature`, `score_candidate` - no I/O, fully
unit-testable) and one thin async orchestration function (`match_story`, the only piece
services/triage_orchestrator.py calls) - mirrors services/editorial_scoring.py's own established
split exactly.

Shadow-mode only in this phase: `match_story()`'s result is persisted (by the caller) for
observability, but never suppresses any downstream processing - see
services/triage_orchestrator.py's own `story_memory_mode` gating for the enforcement boundary,
which does not exist yet in this delivery.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import EventCategory
from database.models.story import Story
from services.editorial_content_type import classify_content_type, is_content_type_mismatch
from services.fact_safety import ClaimType, extract_claims
from services.text_normalization import normalize_for_entity_match, normalize_loose, symmetric_token_overlap

# Phase V2.22A: mirrors services/story_delta_engine.py's own _MATERIAL_CLAIM_TYPES verbatim (never
# imported directly - story_delta_engine.py already imports FROM this module, so the reverse
# import would be circular). Kept as a literal duplicate of the same 4 claim types, not
# independently chosen - see that module's own comment for why "entity"/"quote" are deliberately
# excluded (a new entity or a quote is often just a different source's own phrasing, never a
# material development on its own).
_MATERIAL_CLAIM_TYPES: tuple[ClaimType, ...] = ("date", "money", "percentage", "metric_quantity")

# --- outcomes -----------------------------------------------------------------------------

NEW_STORY = "new_story"
STORY_UPDATE = "story_update"
# Phase 18.10 M7 (novelty scoring): a confident match whose title is substantially similar to an
# existing story - most often another outlet corroborating the same core event without adding
# new substance - distinct from SEMANTIC_DUPLICATE (near-identical/rehash title) and from
# STORY_UPDATE (materially different title, a real new development). Sits between the two on the
# title-overlap spectrum, not a separate scoring dimension.
SUPPORTING_SOURCE = "supporting_source"
SEMANTIC_DUPLICATE = "semantic_duplicate"
UNCERTAIN_MATCH = "uncertain_match"
# Phase 20 M5: same entity family (company/product/person), genuinely different editorial event -
# e.g. "GTA VI preorders" vs "GTA VI Netflix marketing campaign" (Take-Two, both about GTA VI, not
# the same story). Never merges - a non-blocking, informational pointer only
# (NewsEventStoryLink.matched_story_id still points at the related, NOT the same, Story). Exists
# specifically to protect this precision case once M3's category/topic hard gates (which
# accidentally protected it before) are relaxed for recall - see docs/phase20_story_memory_
# calibration_dataset.md's own "gta_negative_control" case for the evidence this responds to.
RELATED_STORY = "related_story"


def is_story_update_match(match_type: str | None) -> bool:
    """The single source of truth for "does this NewsEventStoryLink.match_type represent an
    update to an existing story" (as opposed to a fresh, standalone story) - reused by both
    services/content_draft_service.py (at draft-creation time, to populate ContentDraftStoryLink.
    is_story_update) and services/story_duplicate_guard.py (at pre-generation time, docs/
    post_acceptance_followup_checkpoint.md §B's cost short-circuit) so the two can never silently
    diverge. Every outcome except NEW_STORY and UNCERTAIN_MATCH counts as an update - mirrors the
    exact inline check content_draft_service.py used before this extraction (`match_type not in
    (NEW_STORY, UNCERTAIN_MATCH)`), byte-for-byte, not a new policy."""
    return match_type not in (None, NEW_STORY, UNCERTAIN_MATCH)


# --- topic buckets --------------------------------------------------------------------------
# Deliberately few and broad (not one bucket per news-type) - the false-positive-protection goal
# is separating clearly-unrelated categories of news about the same entity (a product launch vs.
# a regulatory-commentary story about the same company), not finely taxonomizing every possible
# angle. "product" in particular is intentionally broad enough to keep a launch and its own
# follow-up benchmark/feature coverage in the same bucket (docs/phase18_10_editorial_intelligence_
# report.md's own worked example) - splitting those into separate buckets would defeat the
# feature's own purpose.
TOPIC_PRODUCT = "product"
TOPIC_FINANCIAL = "financial"
TOPIC_CORPORATE = "corporate"
TOPIC_LEGAL_REGULATORY = "legal_regulatory"
TOPIC_SECURITY_INCIDENT = "security_incident"
TOPIC_OTHER = "other"

# Checked narrowest/most-specific first, since a title could plausibly contain generic
# product-ish words alongside a more specific signal (e.g. "regulator opens probe into new AI
# chip" should classify as legal_regulatory, not product, even though "chip" would match product
# too) - first match wins, in this fixed priority order.
_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        TOPIC_SECURITY_INCIDENT,
        (
            "breach", "hack", "hacked", "vulnerability", "exploit", "leaked", "leak", "malware",
            "cyberattack", "взлом", "утечка", "уязвимость", "кибератака", "вредонос",
        ),
    ),
    (
        TOPIC_LEGAL_REGULATORY,
        (
            "lawsuit", "sue", "sues", "sued", "regulation", "regulator", "antitrust", "ban",
            "banned", "fine", "fined", "investigation", "court", "probe", "compliance", "law",
            "суд", "иск", "регулятор", "закон", "штраф", "расследование", "запрет", "запретил",
        ),
    ),
    (
        TOPIC_FINANCIAL,
        (
            "earnings", "revenue", "profit", "loss", "funding", "raised", "raises", "valuation",
            "ipo", "quarterly", "financial results", "выручка", "прибыль", "убыток",
            "инвестиции", "раунд", "оценка", "финансовые результаты",
        ),
    ),
    (
        TOPIC_CORPORATE,
        (
            "ceo", "executive", "hires", "hired", "resigns", "resigned", "appoints", "appointed",
            "merger", "acquisition", "acquires", "partnership", "board", "leadership",
            "гендиректор", "директор", "назначил", "партнёрство", "партнерство", "слияние",
            "поглощение", "совет директоров",
        ),
    ),
    (
        TOPIC_PRODUCT,
        (
            "launch", "launches", "launched", "release", "releases", "released", "unveil",
            "unveils", "unveiled", "introduce", "introduces", "introduced", "announce",
            "announces", "announced", "update", "updated", "upgrade", "feature", "benchmark",
            "benchmarks", "version", "model", "релиз", "выпустил", "представил", "анонсировал",
            "бенчмарк", "версия", "обновление", "запустил",
        ),
    ),
)

# Phase 20 Checkpoint 6: grammatical determiners/demonstratives - never named entities - excluded
# from _extract_entities() below. Fixed, closed, linguistically-principled set (English/Russian
# only, matching this module's existing bilingual scope) - not derived from or specific to any
# calibration case's own company/product/person names.
_GENERIC_DETERMINER_ENTITIES = frozenset({
    "this", "that", "these", "those", "it", "if", "a", "an", "the",
    "это", "этот", "эта", "эти",
})

# Entity Normalization Calibration (docs/research_reuse_entity_normalization_checkpoint.md §B/C,
# the VK "Отчёт VK" vs "VK" duplicate-story miss): a second, small, explicitly calibration-
# EVIDENCE-BACKED set - unlike _GENERIC_DETERMINER_ENTITIES above (fixed, closed, deliberately NOT
# calibration-derived), these five tokens ARE calibration-derived, confirmed against the real,
# full working database (1,280 real Story rows): two Russian prepositions ("в"/"от" - a closed
# grammatical class, structurally incapable of being part of a real proper name) plus three
# institutional/document common nouns, in the exact POST-CASE-STRIPPED form this module's own
# normalize_for_entity_match()/strip_ru_case_suffix() pipeline actually produces before this check
# ever runs ("компани"/"правительств", not the dictionary forms "компания"/"правительство"; "отчёт"
# has no case suffix to strip in this instance, so it is unchanged). Real calibration evidence: 26
# real entity pairs corrected across the corpus (including the exact real VK pair this set was
# built to fix), 0 false positives against real negative controls checked (standalone "ai": 149
# corpus occurrences, never touched; every real company-prefixed product name checked - "google
# pixel", "apple watch", "amazon bedrock", "github copilot" among others - untouched, since Google/
# Apple/Amazon/GitHub are proper nouns, never members of this generic-noun set).
#
# Deliberately kept SEPARATE from _GENERIC_DETERMINER_ENTITIES, never merged into it - that set's
# own docstring's "never hardcoded from any calibration case" claim stays true only if this stays
# its own set. Never broaden this set without the same per-word, real-corpus-evidence discipline
# each of these five members individually received - this is not a general stopword list.
_CALIBRATED_GENERIC_PREFIX_ENTITIES = frozenset({
    "в", "от", "отчёт", "компани", "правительств",
})

# Phase R2.10G1: a second closed, linguistically-principled (NOT calibration-derived) grammatical
# class, mirroring _GENERIC_DETERMINER_ENTITIES above exactly - common pronouns/prepositions/
# conjunctions, capitalized only because they open a sentence, never because they denote anything.
# Kept as its own set rather than merged into _GENERIC_DETERMINER_ENTITIES (whose own docstring
# specifically says "determiners/demonstratives") - each of this module's exclusion sets stays a
# truthful, narrow account of its own linguistic category, even though _extract_entities() below
# treats all of them identically at the exclusion check itself.
_GENERIC_FUNCTION_WORD_ENTITIES = frozenset({
    "we", "to", "for", "when",
})

# Phase R2.10G1 (real forensic finding, RECAP R2.10F: 8 of a 21-Story hand-reviewed sample were
# incoherent groupings of editorially unrelated events, held together by a single spurious shared
# "entity" that was really just a generic word capitalized for being sentence-initial - the same
# failure class Checkpoint 6 already fixed for pure determiners, e.g. two unrelated arXiv abstracts
# both opening "Accurate ..."/"Recent ..." scoring entity_overlap=1.0 from that one shared token,
# real member titles spanning dialogue systems, radiotherapy segmentation, and agricultural cold-
# hardiness forecasting). Confirmed via a real full-corpus scan (every Story with exactly one
# extracted entity, `select entities, event_count from stories where json_array_length(entities) =
# 1 order by event_count desc`): each member below was the SOLE entity of a real Story that had
# accumulated real, editorially-unrelated confirmed-member events (11-22 events each) purely on
# this token's own strength.
#
# Two evidence-backed sub-categories, each member individually confirmed against real title data
# (mirrors _CALIBRATED_GENERIC_PREFIX_ENTITIES's own per-word discipline - this is NOT a general
# stopword list):
#   - English ML-abstract-convention openers, describing the paper's own claimed rigor/scope, never
#     its actual subject: "accurate", "recent", "many", "large", "deep", "modern", "synthetic",
#     "autonomous", "multimodal", "robotic", "understanding".
#   - Russian digest/wire-template markers, in the exact post-normalize_for_entity_match() form
#     (lowercased; "новости" case-suffix-stripped to "новост", matching this module's own
#     normalize_for_entity_match()/strip_ru_case_suffix() pipeline - see that module's own
#     docstring): "утро" ("morning" - a recurring "Утро среды:"/"Утро четверга:" daily-digest
#     template merged 4 different days' digests into one Story), "новост" ("news" - a recurring
#     "Новости к этому часу" digest template merged two DIFFERENT digest sources plus one genuinely
#     unrelated item into one Story), "день" ("day").
#
# Deliberately excludes other generic-looking single words the same corpus scan surfaced (e.g.
# "machine"/"learning"/"language"/"video"/"robot"/"object"/"artificial") where a bare single-word
# form remains plausibly a real, informative entity on its own - not included without the same
# per-word confidence the members below already have; a future phase may add any of them
# individually with its own real-corpus evidence, exactly as this phase did for these.
_CALIBRATED_GENERIC_DESCRIPTOR_ENTITIES = frozenset({
    "accurate", "recent", "many", "large", "deep", "modern", "synthetic", "autonomous",
    "multimodal", "robotic", "understanding",
    "утро", "новост", "день",
})

# STORY-CONTINUITY-P0 (2026-09, real production evidence META-AI-DUPLICATE forensics): broad
# domain/format vocabulary that a headline routinely capitalizes ("AI", "Model", "Agent",
# "Update") or opens a sentence with ("Will consumers trust it?" -> "will"), which then acts as a
# spurious Story anchor or inflates entity_jaccard between two unrelated same-company items. Real
# confirmed failures this set responds to, individually:
#   - Story "Will you have spent more of your life with computers..." accumulated 7 editorially
#     unrelated articles (gaming / solar / self-flying planes / AI-for-coders / a Meta Muse agent
#     item) whose SOLE shared entity was the sentence-initial modal "will".
#   - Story "Meta's new AI transcription model ..." (entities ["meta","ai"]) absorbed two
#     Sept-8 Meta personal-agent items purely on the generic {meta, ai} overlap.
# Two evidence-backed sub-categories (NOT a general stopword list - each member is a real
# forensic finding or its direct linguistic class):
#   - domain/product-category vocabulary, never an identity on its own: "ai", "ml", "llm",
#     "model", "models", "agent", "agents", "app", "apps", "tool", "tools", "platform", "api",
#     "technology", "tech", "software", "chatbot", "assistant", "feature", "features", "service",
#     "startup", "company", "news", "launch", "update", "release", "version".
#   - sentence-initial modal/opener verbs, capitalized only for position: "will", "can", "could",
#     "should", "would", "does", "do", "is", "are", "here", "why", "how", "what", "meet".
#   - Russian equivalents in post-normalize_for_entity_match() form: "ии", "модель", "модел",
#     "приложение", "приложени", "технологи", "сервис", "компани" (already covered), "новост"
#     (already covered), "запуск", "агент", "инструмент".
_GENERIC_DOMAIN_ENTITIES = frozenset({
    "ai", "ml", "llm", "model", "models", "agent", "agents", "app", "apps", "tool", "tools",
    "platform", "api", "technology", "tech", "software", "chatbot", "assistant", "feature",
    "features", "service", "startup", "company", "news", "launch", "update", "release",
    "version", "product", "system",
    # sentence-initial modal / opener words - capitalized for position, never an identity
    # (real forensic finding: the Story "Will you have spent more of your life with computers..."
    # accumulated 7 unrelated articles anchored solely on "will").
    "will", "can", "could", "should", "would", "does", "do", "is", "are", "was", "were",
    "here", "why", "how", "what", "who", "when", "meet",
    "ии", "модель", "модел", "приложение", "приложени", "технологи", "технология", "сервис",
    "запуск", "агент", "инструмент", "продукт", "система",
})

# Union of every set _extract_entities() drops outright and classify_entity() calls "generic".
_ALL_GENERIC_ENTITY_SETS: tuple[frozenset[str], ...] = (
    _GENERIC_DETERMINER_ENTITIES,
    _CALIBRATED_GENERIC_PREFIX_ENTITIES,
    _GENERIC_FUNCTION_WORD_ENTITIES,
    _CALIBRATED_GENERIC_DESCRIPTOR_ENTITIES,
    _GENERIC_DOMAIN_ENTITIES,
)

# STORY-CONTINUITY-P0: globally-recurring organizations / platforms whose bare name appears
# across many editorially-unrelated stories in any candidate pool ("a mega-corp, a head of
# state" - the exact class services/story_memory.py::_distinctive_shared_entities()'s own
# docstring already names as NOT story-identifying on its own). A single bare token in this set
# classifies as SUPPORTING, never DISTINCTIVE - so "Meta launches X" and "Meta sues Y" cannot
# reach a confident same-Story match on the shared "meta" alone. NOT a calibration list of one
# incident's names: it is the standard set of always-present tech subjects. A specific
# product / project / model name (e.g. "muse", "llama", "gemini", "copilot") is deliberately
# NOT here - those DO identify a story and stay DISTINCTIVE.
_SUPPORTING_ORG_ENTITIES = frozenset({
    "meta", "facebook", "instagram", "whatsapp", "threads",
    "google", "alphabet", "youtube", "android", "chrome", "waymo",
    "apple", "microsoft", "windows", "xbox", "linkedin", "github",
    "amazon", "aws", "twitch",
    "openai", "anthropic", "nvidia", "amd", "intel", "qualcomm", "arm", "tsmc",
    "samsung", "sony", "tesla", "spacex", "netflix", "spotify", "uber", "adobe",
    "ibm", "oracle", "salesforce", "snap", "snapchat", "pinterest", "reddit",
    "tiktok", "bytedance", "baidu", "alibaba", "tencent", "huawei", "xiaomi",
    "x", "twitter", "yandex", "vk", "telegram", "discord",
    "eu", "ftc", "doj", "sec",
    "мета", "гугл", "эпл", "майкрософт", "яндекс",
})


def _is_generic_token(token: str) -> bool:
    if any(token in s for s in _ALL_GENERIC_ENTITY_SETS):
        return True
    # a hyphenated compound of only-generic parts is itself generic: "ИИ-модель" ->
    # "ии-модель" -> ["ии", "модель"] (both generic); "AI-agent". "muse-spark" is NOT.
    if "-" in token:
        parts = [p for p in token.split("-") if p]
        return len(parts) > 1 and all(
            any(p in s for s in _ALL_GENERIC_ENTITY_SETS) for p in parts
        )
    return False


# A cleaned entity run longer than this many tokens is almost never a real named identity - it
# is a Title-Case headline fragment the capitalized-run regex swept up whole ("Meta Targets Mass
# Market Automation With New Muse AI Agent"). Dropped rather than kept as a spurious entity.
_MAX_ENTITY_RUN_TOKENS = 5


# STORY-CONTINUITY-P0 entity-evidence tiers (docs continuity contract §4/§6). Deterministic, no
# registry, no LLM:
#   DISTINCTIVE - a named product / model / version / feature: a multi-word run that is not
#     entirely generic vocabulary, OR any run carrying a digit (a version/model number). Carries
#     the most evidentiary weight; an incompatible distinctive identity is negative evidence.
#   SUPPORTING - a bare proper-noun token (organization / person / platform): a single non-
#     generic word. Real identity, but organization overlap ALONE must never establish "same
#     Story" (a Meta launch and a Meta lawsuit share "meta" and nothing else).
#   GENERIC   - domain/format vocabulary (see the sets above): ~zero matching weight.
ENTITY_DISTINCTIVE = "distinctive"
ENTITY_SUPPORTING = "supporting"
ENTITY_GENERIC = "generic"


def classify_entity(entity: str) -> str:
    """Pure. `entity` is already normalize_for_entity_match()-normalized (lowercased, RU-case-
    stripped), as produced by _extract_entities()."""
    tokens = [t for t in entity.split(" ") if t]
    if not tokens:
        return ENTITY_GENERIC
    if all(_is_generic_token(t) for t in tokens):
        return ENTITY_GENERIC
    if len(tokens) == 1 and tokens[0] in _SUPPORTING_ORG_ENTITIES:
        return ENTITY_SUPPORTING
    if any(ch.isdigit() for ch in entity) or len(tokens) >= 2:
        return ENTITY_DISTINCTIVE
    # a single bare non-generic, non-mega-org token: a specific project / product / model /
    # surname / place name - identifying, so DISTINCTIVE (the SUPPORTING_SOURCE / STORY_UPDATE
    # path still additionally requires _distinctive_shared_entities()'s df-rarity gate, so a
    # coincidental common word cannot ride this alone into a confident merge).
    return ENTITY_DISTINCTIVE


def _classified_entities(entities: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {
        ENTITY_DISTINCTIVE: set(), ENTITY_SUPPORTING: set(), ENTITY_GENERIC: set()
    }
    for e in entities:
        out[classify_entity(e)].add(e)
    return out


@dataclass(frozen=True)
class EntityEvidence:
    """Component entity-overlap evidence between a new event and a candidate Story - all pure
    Jaccard over the classified entity sets, plus one derived `effective` score the matcher uses
    in place of a flat entity_jaccard. Persisted/logged for diagnostics; never chain-of-thought."""
    distinctive_overlap: float
    supporting_overlap: float
    generic_overlap: float
    effective: float
    shared_distinctive: tuple[str, ...]
    company_only: bool  # the ONLY shared identity evidence is supporting/generic (no distinctive)
    version_incompatible: bool  # both sides name a product in the same family but a DIFFERENT one


# Weights for the effective entity score. Distinctive overlap dominates; supporting overlap
# contributes a capped, secondary amount; generic overlap contributes nothing. Reasoned, not
# fit to the Meta fixture - the intent is qualitative (generic tokens can't carry a match),
# not a tuned magic number. The 0.65 confident-match threshold in match_story() is UNCHANGED.
_DISTINCTIVE_OVERLAP_WEIGHT = 1.0
_SUPPORTING_OVERLAP_WEIGHT = 0.35
_SUPPORTING_ONLY_EFFECTIVE_CAP = 0.45  # supporting+generic overlap alone can't exceed this
_VERSION_INCOMPATIBLE_PENALTY = 0.30   # subtracted from combined in score_candidate()


def _tokens(entity: str) -> set[str]:
    return {t for t in entity.split(" ") if t}


# An explicit release/version token in a headline: "v0.32.3", "1.3", "17", "2026.1", "r2".
_VERSION_TOKEN_RE = re.compile(r"\bv?\d+(?:\.\d+)+\b|\bv\d+\b|\br\d+\b", re.IGNORECASE)


def _release_version_tokens(text: str) -> set[str]:
    from services.text_normalization import normalize_loose

    return {m.group(0).lstrip("vVрR").casefold() for m in _VERSION_TOKEN_RE.finditer(normalize_loose(text))}


def titles_differ_by_release_version(a: str, b: str) -> bool:
    """Pure. True when BOTH titles carry an explicit release/version token and the two sets are
    disjoint - a near-identical headline about "v0.32.2" vs "v0.32.3" (or "Muse Spark 1.2" vs
    "1.3") is a NEW RELEASE, not a duplicate. False if either side has no version token (so an
    ordinary same-story pair is completely unaffected)."""
    va, vb = _release_version_tokens(a), _release_version_tokens(b)
    return bool(va) and bool(vb) and not (va & vb)


def _version_incompatible(new_distinctive: set[str], cand_distinctive: set[str]) -> bool:
    """True when both sides carry a distinctive product/model identity that share a family token
    (e.g. "muse") but name a DIFFERENT specific product ("muse voice transcribe" vs "muse spark
    1.3") - a strong signal these are separate launches, not one Story. Not triggered when one
    distinctive entity's tokens are a subset of the other's (same product, more/less version
    detail: "muse spark" vs "muse spark 1.3")."""
    if not new_distinctive or not cand_distinctive:
        return False
    if new_distinctive & cand_distinctive:
        return False  # an exact distinctive match -> same product
    for a in new_distinctive:
        ta = _tokens(a)
        for b in cand_distinctive:
            tb = _tokens(b)
            if not (ta & tb):
                continue  # unrelated distinctive entities - no family relationship asserted
            if ta <= tb or tb <= ta:
                return False  # prefix/superset -> same product at different version granularity
    # every shared-family distinctive pair names a different product
    return any(_tokens(a) & _tokens(b) for a in new_distinctive for b in cand_distinctive)


def compute_entity_evidence(new_entities: list[str], candidate_entities: list[str]) -> EntityEvidence:
    """Pure. The component-tiered replacement for a flat entity Jaccard - see EntityEvidence."""
    new_c = _classified_entities(new_entities)
    cand_c = _classified_entities(candidate_entities)
    d = _jaccard(new_c[ENTITY_DISTINCTIVE], cand_c[ENTITY_DISTINCTIVE])
    s = _jaccard(new_c[ENTITY_SUPPORTING], cand_c[ENTITY_SUPPORTING])
    g = _jaccard(new_c[ENTITY_GENERIC], cand_c[ENTITY_GENERIC])
    shared_distinctive = tuple(sorted(new_c[ENTITY_DISTINCTIVE] & cand_c[ENTITY_DISTINCTIVE]))
    if d > 0.0:
        effective = min(1.0, _DISTINCTIVE_OVERLAP_WEIGHT * d + _SUPPORTING_OVERLAP_WEIGHT * s)
        company_only = False
    else:
        effective = min(_SUPPORTING_ONLY_EFFECTIVE_CAP, _SUPPORTING_OVERLAP_WEIGHT * s)
        company_only = (s > 0.0 or g > 0.0)
    return EntityEvidence(
        distinctive_overlap=d, supporting_overlap=s, generic_overlap=g, effective=effective,
        shared_distinctive=shared_distinctive, company_only=company_only,
        version_incompatible=_version_incompatible(
            new_c[ENTITY_DISTINCTIVE], cand_c[ENTITY_DISTINCTIVE]
        ),
    )

# Capitalized-run entity heuristic: one or more consecutive words each starting with an
# uppercase Latin/Cyrillic letter, allowing internal digits/hyphens/dots (so "GPT-4", "GPT-5.6",
# "iPhone"-style would still need the leading capital - a documented, narrow heuristic, not a
# real NER model). Deliberately a new, narrow regex here rather than reusing
# services/fact_safety.py's own quote-extraction regexes - different purpose, same
# intentional-narrow-duplication convention this codebase already uses between
# capabilities/copywriting_capability.py's and capabilities/intelligence_capability.py's own
# duplicated _floor_validate.
# STORY-CONTINUITY-P0: a digit-led token (a version / model / generation number) is captured as
# a CONTINUATION of a capitalized run, though never its start - so "iPhone 17" -> "phone 17",
# "Muse Spark 1.3" -> "muse spark 1.3", "Google Pixel 11" -> "google pixel 11". This lets the
# matcher tell two releases of one product line apart ("iPhone 17" vs "iPhone 16") instead of
# collapsing both to the bare noun "phone".
_ENTITY_RUN_RE = re.compile(r"[A-ZА-ЯЁ][\w\-.]*(?:\s+(?:[A-ZА-ЯЁ][\w\-.]*|\d[\w.\-]*))*")
_MIN_ENTITY_LEN = 2

# Significant title keyword extraction - length-filtered, matches text_normalization's own
# min_token_len=3 convention for token_overlap_ratio.
_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
_MIN_KEYWORD_LEN = 3

# Bounded candidate window (mirrors services/editorial_scoring.py::fetch_engagement_baseline()'s
# own "bounded window, scored in Python" pattern exactly) - recent stories, never the full table.
# Phase 20 M3: no longer same-category-only (see _fetch_candidate_stories's own docstring for why
# - the Phase 19 overnight validation's "kitesurf" case proved a hard category gate excludes real
# same-story matches). Lookback is now settings.story_match_lookback_days (tunable without a code
# deploy); the candidate cap is raised (50 -> 150) to compensate for no longer being
# category-narrowed, still cheap at real `stories` table volumes.
#
# Phase 20 M11.2 finding: this cap, applied directly at the SQL level (ORDER BY updated_at DESC
# LIMIT 150), was measured (M11 historical replay, 3,774 real events) to saturate 94.2% of the
# time at real production volume (750-1200 events/day) - a purely-recency-ordered top-150 window
# routinely excludes the genuinely correct candidate once more than 150 *other* stories have been
# touched more recently, which is common within a single busy hour. This constant now names the
# FINAL cap on how many candidates reach the (more expensive) full score_candidate() scoring stage
# - see _RETRIEVAL_FETCH_SAFETY_CAP / _PRESELECTION_RELEVANCE_LIMIT / _PRESELECTION_RECENCY_LIMIT
# below for the new, wider two-stage retrieval that decides WHICH candidates fill this budget.
STORY_MATCH_CANDIDATE_LIMIT = 150

# Stage 1 (SQL): a much wider time-windowed fetch, safety-capped only to guard against a
# pathological table size, not to shape retrieval quality (that is Stage 2's job). Reasoned from
# the M11 replay's own real data: ~2,441 new stories over 4 real days (~610/day) implies roughly
# 8,500 stories in a 14-day lookback window at today's production volume - this cap is set well
# above that so it does not bind in practice; revisit only if a future replay shows it does.
# Requires database/migrations/versions/3f37cf34109d_add_stories_updated_at_index.py (stories.
# updated_at previously had no index at all) to stay cheap as the table grows past this width.
_RETRIEVAL_FETCH_SAFETY_CAP = 10_000

# Stage 2 (Python, pure, cheap - see _preselect_candidates()): two unioned tiers feeding the
# STORY_MATCH_CANDIDATE_LIMIT-capped set that actually reaches full scoring. "Relevance" reuses
# entity/keyword SETS the module already extracts for every Story (StorySignature.entities/
# keywords - no new extraction, no embeddings) - a candidate sharing zero entities and zero
# keywords with the new event is deprioritized without being scored via the (slightly pricier)
# symmetric title-token-overlap computation. "Recency" is unioned in unconditionally, preserving
# today's behavior for genuinely fresh, low-keyword-overlap corroboration.
_PRESELECTION_RELEVANCE_LIMIT = 150
_PRESELECTION_RECENCY_LIMIT = 50

# Reasoned, not fit to historical outcome data (Phase 20 M11's historical replay is what should
# refine these - see docs/phase20_story_memory_calibration_dataset.md - not a guess made before
# any real data exists). Unchanged from the original values: the scoring *inputs* changed (M3/M4),
# not these bands - re-deriving them without real replay data would be a second guess stacked on
# the first.
_LOW_THRESHOLD = 0.35
_HIGH_THRESHOLD = 0.65
# Within the confident-match zone (combined >= _HIGH_THRESHOLD), title_overlap alone decides the
# 3-way split between SEMANTIC_DUPLICATE / SUPPORTING_SOURCE / STORY_UPDATE - a near-identical
# title is a rehash, a substantially-similar-but-not-identical title is another source
# corroborating the same event, and a materially different title (while still clearing the
# entity-driven combined-score floor) signals real new information. Reasoned, not fit to
# historical data (none exists yet - same disclosed-limitation convention as
# services/editorial_scoring.py's own weight comments).
_DUPLICATE_TITLE_OVERLAP_THRESHOLD = 0.75
_SUPPORTING_SOURCE_TITLE_OVERLAP_THRESHOLD = 0.55

_ENTITY_WEIGHT = 0.6
_TITLE_WEIGHT = 0.4

# Phase 20 M3/M5: category/topic_bucket are no longer hard gates (see module docstring for the
# "kitesurf" case that proved they were excluding real matches) - now small additive scoring
# bonuses, applied only when they agree, on top of the entity/title combined score. Deliberately
# small relative to the 0.6/0.4 entity/title weights - the Kitesurf case's real entity+title
# overlap alone (independently hand-verified against this module's own regex/Dice logic:
# entity_jaccard=0.75, title_dice≈0.57 -> combined≈0.68, already clears _HIGH_THRESHOLD) does not
# require these bonuses to work; they exist to modestly reinforce agreement, not to carry a match
# on their own. Combined score is capped at 1.0 after bonuses.
_CATEGORY_BONUS = 0.05
_TOPIC_BONUS = 0.05

# Phase 20 M5: RELATED_STORY band - protects the "same entity family, different editorial event"
# case (the "gta_negative_control" calibration case; also the synthetic entity-overlap-trap
# cases) once the category/topic hard gates that accidentally protected it are relaxed. A
# candidate whose entity_overlap alone clears this floor, but whose combined score stays below
# _LOW_THRESHOLD (i.e. title/topic/category evidence does NOT support a real same-story match),
# is tagged RELATED_STORY instead of a plain, uninformative NEW_STORY - never merged, never
# auto-suppressed (see services/story_memory.py's own MatchResult docstring). Reasoned starting
# point, not fit to data yet - explicitly called out as needing M11 replay calibration.
_RELATED_STORY_ENTITY_FLOOR = 0.2

# Phase V2.22 (Story Memory match-quality fix, real production evidence): a raw entity-Jaccard
# overlap alone systematically undercounts real identity evidence when the SAME real-world
# organization/person is captured at different specificity by different headlines (real case:
# "Warner Chappell" vs. bare "Warner" - two different normalized strings for the same real
# entity, purely because one outlet's headline dropped "Chappell"). Rather than attempting fuzzy
# substring/prefix entity matching (rejected - exactly the "broad fuzzy merging" risk this phase's
# own instructions warn against: "Warner Bros" and "Warner Music" would also share a "Warner"
# prefix despite being different real companies), this reuses the ALREADY-EXISTING, already-
# calibrated `_distinctive_shared_entities()` document-frequency check (Phase 20 Checkpoint 6) as
# an evidence-strength BONUS on the combined score - a shared entity already had to prove itself
# either multi-word or genuinely rare in the current candidate pool to count here, so this cannot
# fire on a single common/generic shared word alone (confirmed via the V2.22 negative control:
# "same lawsuit defendant, different plaintiff/case" shares only one distinctive entity and one
# bonus unit keeps its combined score below _LOW_THRESHOLD, unchanged from before this fix).
# Real evidence: Sony Music/Warner Chappell vs. Anthropic lawsuit, two outlets - combined=0.46
# with 2 distinctive shared entities ("sony music", "anthropic") never reached _HIGH_THRESHOLD
# under entity/title weighting alone.
_DISTINCTIVE_ENTITY_MATCH_BONUS = 0.10
_DISTINCTIVE_ENTITY_MATCH_BONUS_MAX_ENTITIES = 2

# Phase V2.22A (pool-size sensitivity, found during this phase's own negative-control testing):
# `_distinctive_shared_entities()`'s document-frequency check is a PERCENTAGE of the candidate
# pool (`_DISTINCTIVE_ENTITY_DF_FRACTION`) - at a very small pool, `max(1, round(pool_size *
# 0.05))` floors at 1, so a shared entity's df of 1 (the only way it CAN score in a pool this
# small) trivially clears the bar regardless of whether that entity is actually rare or a generic,
# ubiquitous brand/topic word. This is not fixable by re-deriving the fraction - it is an
# information-theoretic floor: distinctiveness cannot be measured from a sample of ~1. Confirmed
# directly: a synthetic "Apple unveils iPhone 17..." vs. "Apple releases iOS 19.2... for iPhone
# 16" negative control (two genuinely different real events) incorrectly reached STORY_UPDATE at
# a small pool size, purely because "apple"/"phone" had nothing to be diluted against - the same
# entities correctly fail distinctiveness once compared against a realistic-scale pool (confirmed
# separately). Rather than hardcoding "apple"/"phone" into the existing, calibration-EVIDENCE-
# ONLY `_CALIBRATED_GENERIC_IDENTITY_ENTITIES` set (this is a synthetic test case, not a real,
# evidenced calibration finding - hardcoding it there would violate that set's own documented
# discipline), the BONUS specifically requires a minimum, realistic-scale candidate pool before it
# is ever applied - conservative fail-closed (no bonus, not "wrong bonus") below this size,
# matching this whole module's own "false suppression/merge is worse than a duplicate" philosophy.
# Scoped to the bonus ONLY - the pre-existing, already-validated SUPPORTING_SOURCE/STORY_UPDATE
# distinctive-entity gate itself (which does not aggregate a NEW combined-score effect, only
# decides between two already-confident outcomes) is completely unaffected. Reasoned, not fit to
# data (no real pool-size distribution has been measured yet): 20 is the smallest pool size at
# which the underlying percentage first has room to mean anything other than "the trivial floor of
# 1" for more than one shared entity's worth of headroom.
_DISTINCTIVE_ENTITY_BONUS_MIN_POOL_SIZE = 20

# Phase V2.22: a title_overlap this high (near-syndicated/verbatim wording) is, on its own,
# strong same-story evidence independent of how many named entities happen to be extractable -
# real case: "Memory prices climb 500% in 12 months, up to 10x the lowest ever tracked prices"
# (Hacker News) vs. the same sentence plus a trailing product/price clause (Tom's Hardware) -
# title_overlap=0.83 but only ONE weak, generic entity ("memory") is extractable from either
# title, so the 0.6/0.4 entity/title-weighted combined score (0.63) never reached
# _HIGH_THRESHOLD despite the titles being almost verbatim. Set strictly above the ALREADY-
# DOCUMENTED real false-positive case this module's own history recorded (Phase 20 Checkpoint 4:
# two different Fields-of-Mistria guide headlines scored title_overlap=0.75 despite naming a
# genuinely different subject) - 0.80 keeps real margin above that known-bad case while admitting
# the real Memory-prices case (0.83).
_NEAR_VERBATIM_TITLE_OVERLAP_THRESHOLD = 0.80


@dataclass(frozen=True)
class StorySignature:
    entities: list[str]
    keywords: list[str]
    topic_bucket: str


@dataclass(frozen=True)
class MatchResult:
    outcome: str  # NEW_STORY | STORY_UPDATE | SUPPORTING_SOURCE | SEMANTIC_DUPLICATE | UNCERTAIN_MATCH | RELATED_STORY
    matched_story_id: UUID | None
    confidence: float
    similarity_reason: str
    # Phase 20 M11.1: the raw entity_overlap component score_candidate() already computes
    # internally for every outcome - exposed explicitly so callers (services/triage_orchestrator.
    # py's Story Identity dispatch) can distinguish a genuinely substantial entity signal from a
    # coincidental one, instead of parsing similarity_reason's free text. 0.0 for NEW_STORY when
    # there were no candidates at all (nothing to compute overlap against).
    entity_overlap: float = 0.0
    # Phase 20 Checkpoint 6: whether the winning candidate shares at least one *distinctive*
    # entity with the new event (see _distinctive_shared_entities()'s own docstring) - exposed so
    # callers combining this match with Delta Engine output can apply the "identity before delta"
    # rule (a weak/generic entity match must not let a coincidental new number/date/keyword be
    # treated as a confirmed MATERIAL_UPDATE to this specific Story). False whenever no candidate
    # was scored at all (NEW_STORY with an empty pool).
    has_distinctive_shared_entity: bool = False
    # STORY-CONTINUITY-P0: per-tier entity-overlap evidence for the winning candidate, surfaced
    # for the continuity classifier, the delta-persistence path and structured observability
    # (never chain-of-thought). All 0.0 / empty for NEW_STORY with no candidates.
    distinctive_overlap: float = 0.0
    supporting_overlap: float = 0.0
    generic_overlap: float = 0.0
    shared_distinctive_entities: tuple[str, ...] = ()
    company_only_match: bool = False
    version_incompatible: bool = False


def _strip_leading_determiner(normalized_entity: str) -> str:
    """NEWS Output Stability Fix (CD Projekt/Project Sirius duplicate-story miss, docs/
    news_output_stability_forensic_report.md §10): a captured multi-word entity run whose FIRST
    word is a generic determiner/article (e.g. "The Witcher", captured whole because "The"
    happened to be capitalized in this particular headline's own phrasing) must normalize
    identically to the same entity captured without the leading article elsewhere in a different
    headline about the same story (e.g. bare "Witcher"). Confirmed root cause of a real missed
    match: "Witcher multiplayer spin-off Project Sirius hit by fresh layoffs" extracts entity
    "witcher" (bare - "Witcher" is not preceded by a capitalized word in that headline), while "CD
    Projekt cuts more than 20% of The Witcher spinoff development team..." extracts "the witcher"
    (the leading "The" happened to be capitalized) - two different strings for the same real-world
    entity, silently zeroing entity_overlap between two real headlines about the identical layoffs
    story. Strips only ONE leading determiner, never recursively - the realistic English/Russian
    headline pattern this class of bug actually occurs in. Reuses `_GENERIC_DETERMINER_ENTITIES`
    verbatim (the same fixed, closed set Checkpoint 6 already established) - no new lexicon.

    Entity Normalization Calibration addition (docs/research_reuse_entity_normalization_
    checkpoint.md Sections B/C, the real VK "Отчёт VK" vs "VK" duplicate-story miss): also strips
    a single leading token from `_CALIBRATED_GENERIC_PREFIX_ENTITIES` - the identical mechanism,
    applied to a second, explicitly calibration-derived set kept separate from
    `_GENERIC_DETERMINER_ENTITIES` itself (see that set's own docstring for why).

    Phase R2.10G1 addition: also strips a single leading token from `_GENERIC_FUNCTION_WORD_
    ENTITIES`/`_CALIBRATED_GENERIC_DESCRIPTOR_ENTITIES` - the identical mechanism again, for the
    identical reason: "Recent Nvidia announcement..." must normalize to bare "nvidia", the same
    entity a differently-phrased headline about the same real event would extract on its own."""
    words = normalized_entity.split(" ")
    if len(words) > 1 and (
        words[0] in _GENERIC_DETERMINER_ENTITIES
        or words[0] in _CALIBRATED_GENERIC_PREFIX_ENTITIES
        or words[0] in _GENERIC_FUNCTION_WORD_ENTITIES
        or words[0] in _CALIBRATED_GENERIC_DESCRIPTOR_ENTITIES
        or words[0] in _GENERIC_DOMAIN_ENTITIES  # STORY-CONTINUITY-P0: "New Muse ..." -> "muse ..."
    ):
        return " ".join(words[1:])
    return normalized_entity


def _extract_entities(title: str) -> list[str]:
    """Normalized, de-duplicated, order-preserving.

    Phase 20 Checkpoint 6 fix: a small, fixed set of grammatical determiners/demonstratives
    (never named entities, never hardcoded from any calibration case) is excluded - these are
    capitalized only because they happen to start a sentence ("This paper...", "The state of...",
    "Это..."), not because they denote anything. Confirmed root cause of a real false-match class
    (two entirely unrelated arXiv abstracts, both conventionally opening "This paper/research
    ...", scored `entity_overlap=1.0` from a single shared "this" - the entire "entity" set on
    both sides was this one spurious token). A bare first-word capital was previously not
    specially excluded at all - documented at the time as "a documented, accepted imprecision";
    Checkpoint 6's real replay evidence shows it is not merely imprecise but actively
    identity-forming when it is the *only* extracted entity, so it is now excluded outright.

    NEWS Output Stability Fix: `_strip_leading_determiner()` handles the adjacent case - a
    determiner GLUED to a following real entity (rather than standing alone) - see that function's
    own docstring for the real evidence.

    Phase R2.10G1 fix: the same exclusion, extended to `_GENERIC_FUNCTION_WORD_ENTITIES` (a second
    closed grammatical class - pronouns/prepositions/conjunctions) and
    `_CALIBRATED_GENERIC_DESCRIPTOR_ENTITIES` (calibration-evidence-backed generic descriptors) -
    see both sets' own docstrings for the real corpus evidence behind each. Same architecture,
    same call site, same "excluded outright when a spurious sentence-initial capital is the *only*
    extracted entity" rationale Checkpoint 6 already established - no new mechanism."""
    seen: dict[str, None] = {}
    for match in _ENTITY_RUN_RE.finditer(title):
        candidate = match.group(0).strip()
        if len(candidate) < _MIN_ENTITY_LEN:
            continue
        normalized = normalize_for_entity_match(candidate)
        if (
            normalized in _GENERIC_DETERMINER_ENTITIES
            or normalized in _CALIBRATED_GENERIC_PREFIX_ENTITIES
            or normalized in _GENERIC_FUNCTION_WORD_ENTITIES
            or normalized in _CALIBRATED_GENERIC_DESCRIPTOR_ENTITIES
        ):
            continue
        normalized = _strip_leading_determiner(normalized)
        # STORY-CONTINUITY-P0: a captured run can still carry generic domain/format vocabulary
        # INSIDE it ("new AI transcription model" -> the run "AI" alone, or "New Muse AI Agent"
        # -> "muse ai agent"). Drop the generic tokens from within the run so what survives is
        # only the identifying words; drop the run entirely if nothing identifying survives or if
        # it is a Title-Case headline fragment (too many surviving tokens to be a real name).
        run_tokens = [t for t in normalized.split(" ") if t and not _is_generic_token(t)]
        if not run_tokens or len(run_tokens) > _MAX_ENTITY_RUN_TOKENS:
            continue
        normalized = " ".join(run_tokens)
        if normalized and normalized not in seen:
            seen[normalized] = None
    return list(seen.keys())


def _extract_keywords(title: str) -> list[str]:
    from services.text_normalization import normalize_loose

    seen: dict[str, None] = {}
    for token in _WORD_RE.findall(normalize_loose(title)):
        if len(token) >= _MIN_KEYWORD_LEN and token not in seen:
            seen[token] = None
    return list(seen.keys())


def _classify_topic(title: str) -> str:
    """Phase 20 M4 fix: uses `services.text_normalization.fuzzy_phrase_contains()` - already-
    established, whole-word-boundary, Russian-case-suffix-aware phrase containment - instead of
    the original raw `keyword in normalized` substring check, which false-positive-matched "иск"
    (a legal_regulatory keyword meaning "lawsuit") inside "искусственному" ("artificial", as in
    "artificial intelligence") - a real bug independently found via the Phase 19 overnight
    validation's `moscow_student_pair` case (docs/phase20_story_memory_calibration_dataset.md). A
    naive `\\bkeyword\\b` regex fix was tried first and rejected: it also broke legitimate
    Russian morphological variants the original substring behavior accidentally handled (e.g. the
    keyword "представил" no longer matching "представила", a real gender-agreement inflection) -
    `fuzzy_phrase_contains()`'s existing case-suffix stripping handles both correctly, since "иск"
    (3 chars) is too short to be stripped further while "искусственному" strips down to a
    different, non-matching stem."""
    from services.text_normalization import fuzzy_phrase_contains

    for bucket, keywords in _TOPIC_KEYWORDS:
        if any(fuzzy_phrase_contains(kw, title) for kw in keywords):
            return bucket
    return TOPIC_OTHER


def extract_story_signature(title: str, category: EventCategory) -> StorySignature:
    """Pure. Deterministic: identical input always produces an identical signature.
    `category` is accepted for interface symmetry with `match_story()` (both take the same two
    facts about an event) even though the signature itself does not currently vary by category -
    Phase 20 M3: category is a soft scoring bonus in `score_candidate()`, never a hard retrieval
    filter (see this module's own docstring for why the original hard gate was removed)."""
    del category  # not used in the signature itself - see docstring
    # STORY-CONTINUITY-P0: one shared identity-normalization pass (Google News suffix + Russian
    # legal-designation disclaimer + leading wire-format label) so publisher/format boilerplate
    # never becomes a Story entity or inflates keyword overlap. A no-op for titles without any of
    # that boilerplate. See services/text_normalization.py::normalize_story_identity_title().
    from services.text_normalization import normalize_story_identity_title

    identity_title = normalize_story_identity_title(title)
    return StorySignature(
        entities=_extract_entities(identity_title),
        keywords=_extract_keywords(identity_title),
        topic_bucket=_classify_topic(identity_title),
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _score_components(
    title: str, signature: StorySignature, category: EventCategory, candidate_title: str, candidate: Story
) -> tuple[float, float, float, EntityEvidence]:
    """Pure. STORY-CONTINUITY-P0 component-tiered scoring - returns
    (combined_score, effective_entity_overlap, title_overlap, entity_evidence).

    Changes from the pre-P0 flat scorer, all in the FEATURES, never the 0.65 confident threshold:
      - the entity component is `EntityEvidence.effective` (distinctive overlap dominates,
        supporting overlap is capped-secondary, generic overlap contributes nothing) instead of a
        flat Jaccard over undifferentiated entities. See compute_entity_evidence().
      - COMPANY-ONLY GUARD: when the only shared identity evidence is an organization/generic
        token (no distinctive overlap), `combined` is capped just below the confident threshold
        so it can never become a confident SEMANTIC_DUPLICATE / SUPPORTING_SOURCE / STORY_UPDATE
        - it can still be RELATED_STORY / UNCERTAIN_MATCH (attach for observability, never merge).
      - VERSION-INCOMPATIBLE PENALTY: when both sides name a DIFFERENT product in the same family
        ("Muse Voice Transcribe" vs "Muse Spark 1.3"), a fixed penalty pushes `combined` down so
        two adjacent-but-distinct launches stay separate Stories.
      - title_overlap is measured on identity-normalized titles (publisher/legal/format
        boilerplate stripped) so a shared disclaimer or wire label can't inflate it.
    """
    from services.text_normalization import normalize_story_identity_title

    ev = compute_entity_evidence(list(signature.entities), list(candidate.entities or []))
    title_overlap = symmetric_token_overlap(
        normalize_story_identity_title(title), normalize_story_identity_title(candidate_title)
    )
    bonus = 0.0
    if candidate.category == category:
        bonus += _CATEGORY_BONUS
    if candidate.topic_bucket == signature.topic_bucket:
        bonus += _TOPIC_BONUS
    combined = min(1.0, _ENTITY_WEIGHT * ev.effective + _TITLE_WEIGHT * title_overlap + bonus)
    if ev.version_incompatible:
        combined = max(0.0, combined - _VERSION_INCOMPATIBLE_PENALTY)
    # COMPANY-ONLY GUARD: shared organization/generic tokens with NO distinctive overlap can't
    # carry a confident same-Story match - UNLESS the wording is itself substantially similar
    # (a near-rewording is independent same-story evidence, the V2.22 "Memory prices" / VK
    # "Отчёт VK" rationale). So the cap is skipped once title_overlap clears the supporting-
    # source similarity bar.
    if (
        ev.company_only
        and ev.distinctive_overlap == 0.0
        and title_overlap < _SUPPORTING_SOURCE_TITLE_OVERLAP_THRESHOLD
    ):
        combined = min(combined, _HIGH_THRESHOLD - 0.001)
    return combined, ev.effective, title_overlap, ev


def score_candidate(
    title: str, signature: StorySignature, category: EventCategory, candidate_title: str, candidate: Story
) -> tuple[float, float, float]:
    """Pure. Returns (combined_score, effective_entity_overlap, title_overlap) - the pre-P0
    3-tuple shape kept verbatim for existing callers/tests. STORY-CONTINUITY-P0 enriched the
    feature model behind it; see _score_components() for the full evidence including the
    per-tier EntityEvidence."""
    combined, entity_overlap, title_overlap, _ = _score_components(
        title, signature, category, candidate_title, candidate
    )
    return combined, entity_overlap, title_overlap


async def _fetch_candidate_stories(session: AsyncSession, *, now: datetime) -> list[Story]:
    """Phase 20 M3: no longer filtered by category - `services/story_memory.py`'s own module
    docstring / the Phase 19 overnight validation's "kitesurf" case proved a same-category-only
    SQL WHERE clause silently excludes real same-story candidates in a different NewsEvent
    category. Still bounded (time window + a wide safety cap, indexed - see
    _RETRIEVAL_FETCH_SAFETY_CAP's own comment) - a wide, not unbounded, scan. Category is
    reintroduced as a soft scoring bonus in `score_candidate()` instead.

    Phase 20 M11.2: this is now Stage 1 of a two-stage retrieval - callers must apply
    `_preselect_candidates()` before scoring; this function alone no longer represents "the
    candidates that will be scored," only "everything worth considering," ordered by recency
    (still a reasonable, cheap ORDER BY given the new index) so `_preselect_candidates()`'s own
    recency tier can simply take a prefix without re-sorting."""
    cutoff = now - timedelta(days=settings.story_match_lookback_days)
    stmt = (
        select(Story)
        .where(Story.updated_at >= cutoff)
        .order_by(Story.updated_at.desc())
        .limit(_RETRIEVAL_FETCH_SAFETY_CAP)
    )
    return list((await session.execute(stmt)).scalars().all())


def _preselect_candidates(signature: StorySignature, candidates: list[Story]) -> list[Story]:
    """Pure, deterministic, cheap - Stage 2 of retrieval (Phase 20 M11.2). `candidates` is assumed
    already ordered by `updated_at DESC` (as `_fetch_candidate_stories()` returns it).

    Two unioned tiers, feeding the `STORY_MATCH_CANDIDATE_LIMIT`-capped set that reaches full
    `score_candidate()` scoring:
    - up to `_PRESELECTION_RELEVANCE_LIMIT` candidates with the highest (entity_overlap_count,
      keyword_overlap_count) set-intersection count against the new event's own signature -
      "distinctive entity/product/project/company tokens" and "normalized headline token overlap"
      per the M11.2 design brief, computed via plain Python set intersection (no embeddings, no
      new extraction - reuses StorySignature.entities/keywords, already computed for every Story).
      Candidates with zero overlap on both are excluded from this tier entirely (recency is their
      only path back in, via the second tier).
    - up to `_PRESELECTION_RECENCY_LIMIT` most-recently-updated candidates, unconditionally -
      preserves today's behavior for a genuinely fresh corroborating source whose title happens to
      share few distinctive tokens with the new event (e.g. very short headlines).

    The union is capped at `STORY_MATCH_CANDIDATE_LIMIT` overall (relevance tier first, since it is
    the higher-precision signal) purely to bound the downstream full-scoring compute cost - not to
    reintroduce the old recall problem, since the two tiers are chosen deliberately rather than by
    a single blind recency cutoff."""
    new_entities = set(signature.entities)
    new_keywords = set(signature.keywords)

    def _relevance(story: Story) -> tuple[int, int]:
        story_entities = set(story.entities or [])
        story_keywords = set(story.keywords or [])
        return len(new_entities & story_entities), len(new_keywords & story_keywords)

    by_relevance = sorted(candidates, key=_relevance, reverse=True)
    by_relevance = [c for c in by_relevance if _relevance(c) != (0, 0)][:_PRESELECTION_RELEVANCE_LIMIT]
    by_recency = candidates[:_PRESELECTION_RECENCY_LIMIT]

    seen_ids: set[UUID] = set()
    merged: list[Story] = []
    for story in by_relevance + by_recency:
        if story.id not in seen_ids:
            seen_ids.add(story.id)
            merged.append(story)
    return merged[:STORY_MATCH_CANDIDATE_LIMIT]


# Phase 20 Checkpoint 6: an entity shared with at least this large a fraction of the current
# candidate pool is treated as "generic for this pool" (a constantly-recurring subject - a
# mega-corp, a head of state - rather than something that specifically identifies this one
# story). Reasoned starting point (5% of the pool), not fit to data - the M11 replay's own
# calibration convention applies here too: revisit only if a future replay's evidence justifies a
# different value, never guessed twice.
_DISTINCTIVE_ENTITY_DF_FRACTION = 0.05

# Phase 23 shadow calibration: broad AI-topic tokens can be useful for retrieval/scoring,
# but they are not specific enough to serve as the final identity evidence required for
# STORY_UPDATE or SUPPORTING_SOURCE. Keep this deliberately narrow and apply it only inside
# _distinctive_shared_entities(); extraction, preselection, base scoring and duplicate matching
# remain unchanged.
_CALIBRATED_GENERIC_IDENTITY_ENTITIES = frozenset({
    "ai",
    "we",
    "\u043a\u0430\u043a",
    "\u0438\u0438",
    "\u0438\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d",
})


def _entity_document_frequencies(candidates: list[Story]) -> dict[str, int]:
    """Pure. Classic, deterministic document-frequency count (not an embedding, not an ML model)
    - for each entity string, how many Stories in the current candidate pool contain it. Used only
    to distinguish a genuinely distinctive shared entity from a generic, constantly-recurring one;
    never used to alter retrieval or the base combined score itself."""
    df: dict[str, int] = {}
    for story in candidates:
        for entity in set(story.entities or []):
            df[entity] = df.get(entity, 0) + 1
    return df


def _distinctive_shared_entities(
    new_entities: list[str], candidate_entities: list[str], entity_df: dict[str, int], pool_size: int,
) -> list[str]:
    """Pure. A shared entity counts as distinctive if it is a multi-word phrase (inherently more
    specific than a single common word - e.g. "app store", "windows pcs" - no document-frequency
    check needed) or its document frequency within the current candidate pool is low (appears in
    only a small fraction of the Stories under consideration, not a subject - a company, a head of
    state - that recurs across many unrelated stories in this same pool). Checkpoint 6 root-cause
    evidence (docs/phase20_checkpoint6_human_calibration_report.md): confirmed false-match cases
    shared only a single generic word ("путин" alone, "apple" alone, "день" alone); confirmed
    genuine-update cases always shared either a multi-word entity ("app store", "windows pcs") or
    a company name that, in the real replay corpus, was specific to that one story pair."""
    shared = set(new_entities) & set(candidate_entities)
    if not shared or pool_size <= 0:
        return []
    threshold = max(1, round(pool_size * _DISTINCTIVE_ENTITY_DF_FRACTION))
    return sorted(
        e
        for e in shared
        if e not in _CALIBRATED_GENERIC_IDENTITY_ENTITIES
        and (" " in e or entity_df.get(e, 0) <= threshold)
    )


async def match_story(
    session: AsyncSession, *, title: str, category: EventCategory, now: datetime | None = None
) -> tuple[StorySignature, MatchResult]:
    """The only orchestration entry point services/triage_orchestrator.py calls. Does one bounded,
    indexed query (see `_fetch_candidate_stories`) - never an unbounded table scan. Category is no
    longer a hard retrieval filter (Phase 20 M3) - candidate retrieval is deliberately
    high-recall; relationship classification (this function's own threshold bands) stays
    precision-preserving.

    Returns both the extracted signature (the caller persists it onto the new Story if this
    becomes a new_story) and the match result. Never creates or mutates a Story row itself - that
    is the caller's responsibility (keeps this module read-only/pure-adjacent, mirroring
    services/editorial_scoring.py's own apply_editorial_scoring_v2() not owning persistence
    either)."""
    reference_now = now if now is not None else datetime.now(timezone.utc)
    signature = extract_story_signature(title, category)
    # Phase 20.7: Editorial Content Type - computed here, before Story Identity is evaluated
    # below, per the "identity before delta" ordering this module already establishes (a
    # relationship classification must never be more confident than the evidence for it - a
    # content-type mismatch is exactly the same class of evidence gap as a missing distinctive
    # entity, see _distinctive_shared_entities()'s own docstring for the parallel).
    new_content_type = classify_content_type(title)
    fetched = await _fetch_candidate_stories(session, now=reference_now)
    candidates = _preselect_candidates(signature, fetched)
    entity_df = _entity_document_frequencies(candidates)

    if not candidates:
        return signature, MatchResult(
            NEW_STORY, None, 1.0, "no candidate stories in the lookback window", entity_overlap=0.0,
        )

    # Shadow calibration: an exactly identical normalized title is sufficient evidence for a
    # semantic duplicate even when entity extraction yields no entities (for example GitHub
    # release titles). Keep this deliberately narrower than the 0.75 near-identical-title rule:
    # different versions or otherwise non-identical titles continue through normal scoring.
    normalized_title = " ".join(title.split()).casefold()
    for candidate in candidates:
        if normalized_title == " ".join(candidate.title.split()).casefold():
            return signature, MatchResult(
                SEMANTIC_DUPLICATE,
                candidate.id,
                1.0,
                "exact normalized title match - same event regardless of entity extraction",
                entity_overlap=0.0,
                has_distinctive_shared_entity=True,
            )

    best: tuple[float, float, float, EntityEvidence, Story] | None = None
    for candidate in candidates:
        combined, entity_overlap, title_overlap, ev = _score_components(
            title, signature, category, candidate.title, candidate
        )
        if best is None or combined > best[0]:
            best = (combined, entity_overlap, title_overlap, ev, candidate)

    assert best is not None  # candidates is non-empty, so the loop ran at least once
    combined, entity_overlap, title_overlap, best_ev, candidate = best

    # STORY-CONTINUITY-P0: inject the winning candidate's per-tier entity evidence into every
    # MatchResult this branch returns, without editing each return site individually.
    def _mk(outcome: str, story_id: UUID | None, conf: float, reason: str, **kw: object) -> MatchResult:
        kw.setdefault("entity_overlap", entity_overlap)
        return MatchResult(
            outcome, story_id, conf, reason,
            distinctive_overlap=best_ev.distinctive_overlap,
            supporting_overlap=best_ev.supporting_overlap,
            generic_overlap=best_ev.generic_overlap,
            shared_distinctive_entities=best_ev.shared_distinctive,
            company_only_match=best_ev.company_only,
            version_incompatible=best_ev.version_incompatible,
            **kw,  # type: ignore[arg-type]
        )

    # Phase V2.22: distinctive-shared-entity bonus, applied to the winning candidate's own
    # combined score before any threshold check - see _DISTINCTIVE_ENTITY_MATCH_BONUS's own
    # comment for the real evidence and the false-positive guard this relies on (a shared entity
    # must already have proven itself multi-word or genuinely rare in this pool via the existing,
    # unmodified `_distinctive_shared_entities()` check - never a single common word alone).
    # Computed once here and reused below (the same evidence used later for the SUPPORTING_
    # SOURCE/STORY_UPDATE gate) rather than recomputed twice.
    distinctive_at_best = _distinctive_shared_entities(signature.entities, candidate.entities or [], entity_df, len(candidates))
    # Phase V2.22A: the bonus itself additionally requires a realistic-scale pool (see
    # _DISTINCTIVE_ENTITY_BONUS_MIN_POOL_SIZE's own comment) - `distinctive_at_best` is still
    # computed unconditionally above and reused below for the pre-existing, unaffected SUPPORTING_
    # SOURCE/STORY_UPDATE gate.
    if distinctive_at_best and len(candidates) >= _DISTINCTIVE_ENTITY_BONUS_MIN_POOL_SIZE:
        bonus_units = min(len(distinctive_at_best), _DISTINCTIVE_ENTITY_MATCH_BONUS_MAX_ENTITIES)
        combined = min(1.0, combined + bonus_units * _DISTINCTIVE_ENTITY_MATCH_BONUS)

    if combined < _LOW_THRESHOLD:
        if entity_overlap >= _RELATED_STORY_ENTITY_FLOOR:
            reason = (
                f"real entity overlap (entity_overlap={entity_overlap:.2f}) but combined score "
                f"{combined:.2f} below low threshold {_LOW_THRESHOLD:.2f} (title_overlap="
                f"{title_overlap:.2f}) - same entity family, not confidently the same story"
            )
            return signature, _mk(RELATED_STORY, candidate.id, entity_overlap, reason)
        reason = (
            f"best candidate score {combined:.2f} below low threshold "
            f"{_LOW_THRESHOLD:.2f} (entity_overlap={entity_overlap:.2f}, title_overlap={title_overlap:.2f})"
        )
        return signature, _mk(NEW_STORY, None, 1.0 - combined, reason)

    # Phase V2.22: a near-verbatim title alone (see _NEAR_VERBATIM_TITLE_OVERLAP_THRESHOLD's own
    # comment) is independently sufficient to enter the confident-match branch, even when the
    # entity-driven combined score alone would not clear _HIGH_THRESHOLD - real case: a headline
    # with almost no extractable named entities but near-syndicated wording (V2.22 "Memory prices"
    # cluster). Never lowers _HIGH_THRESHOLD itself; only adds a second, independent way in.
    if combined >= _HIGH_THRESHOLD or title_overlap >= _NEAR_VERBATIM_TITLE_OVERLAP_THRESHOLD:
        # STORY-CONTINUITY-P0 (Section 9): a near-identical headline that names a DIFFERENT
        # explicit release/version is a new release, not a duplicate ("...bedrock-sdk: v0.32.2"
        # vs "v0.32.3"; "Muse Spark 1.2" vs "1.3"). Do not call it SEMANTIC_DUPLICATE - fall
        # through to the distinctive-entity / claim logic below, which classifies it as a real
        # development or, absent a distinctive shared entity, an UNCERTAIN_MATCH.
        version_release_split = titles_differ_by_release_version(title, candidate.title)
        if title_overlap >= _DUPLICATE_TITLE_OVERLAP_THRESHOLD and not version_release_split:
            reason = (
                f"near-identical title (title_overlap={title_overlap:.2f}) - same event, "
                f"likely a different source's coverage (entity_overlap={entity_overlap:.2f}, "
                f"candidate topic_bucket={candidate.topic_bucket}, category={candidate.category})"
            )
            return signature, _mk(
                SEMANTIC_DUPLICATE, candidate.id, combined, reason,
                has_distinctive_shared_entity=True,  # near-identical wording is sufficient alone
            )

        # Phase 20 Checkpoint 6: SUPPORTING_SOURCE and STORY_UPDATE both assert a CONFIRMED
        # same-story relationship (bump event_count, eligible for suppression/update treatment) -
        # unlike SEMANTIC_DUPLICATE, their title overlap alone is not strong enough to trust
        # without also requiring a genuinely distinctive shared entity (see
        # _distinctive_shared_entities()'s own docstring for the real evidence this responds to -
        # confirmed false matches shared only a single generic word; confirmed genuine matches
        # always shared something more specific). Absent that, the match downgrades to
        # UNCERTAIN_MATCH rather than being confidently (and wrongly) treated as the same story.
        distinctive = distinctive_at_best  # Phase V2.22: already computed above, reused verbatim
        # Phase 20.7: same entity/product does not mean same editorial Story - a review and a
        # guide about the same game are different editorial objects even with a perfect entity
        # match. Gated the same way as the distinctive-entity check (both must clear before a
        # confident same-story outcome is allowed) - NEWS (no specific marker on either side) is
        # never itself a mismatch (services/editorial_content_type.py::is_content_type_mismatch()'s
        # own docstring explains why: most genuine same-story updates carry no special marker).
        candidate_content_type = classify_content_type(candidate.title)
        content_type_ok = not is_content_type_mismatch(new_content_type, candidate_content_type)
        if distinctive and content_type_ok:
            if title_overlap >= _SUPPORTING_SOURCE_TITLE_OVERLAP_THRESHOLD:
                reason = (
                    f"confident match, substantially similar but not identical title "
                    f"(title_overlap={title_overlap:.2f}) - likely a corroborating source, not new "
                    f"substance (entity_overlap={entity_overlap:.2f}, distinctive_shared_entities="
                    f"{distinctive}, content_type={new_content_type}/{candidate_content_type}, "
                    f"candidate topic_bucket={candidate.topic_bucket}, category={candidate.category})"
                )
                return signature, _mk(
                    SUPPORTING_SOURCE, candidate.id, combined, reason,
                    has_distinctive_shared_entity=True,
                )
            # Phase V2.22A (real production evidence, Cluster A: Sony Music/Warner Chappell vs.
            # Anthropic lawsuit, Techmeme vs. TechCrunch): "materially different title" (title_
            # overlap below the supporting-source bar) is only a PROXY for "new information" - two
            # outlets can word the exact same event very differently with zero actual new facts.
            # Confirmed directly: neither real headline here contains any date/money/percentage/
            # metric_quantity claim (services/fact_safety.py::extract_claims(), the SAME extractor
            # services/story_delta_engine.py::classify_delta() already uses - never a second,
            # competing check). STORY_UPDATE is reserved for a REAL new material claim the
            # candidate's own title does not already carry; absent one, this downgrades to
            # SUPPORTING_SOURCE (a confirmed same-story corroborating report, not a fresh
            # development) regardless of how differently the two are worded.
            new_claims = extract_claims(title)
            candidate_claims = extract_claims(candidate.title)
            new_material_claims = [c for t in _MATERIAL_CLAIM_TYPES for c in new_claims.get(t, [])]
            candidate_material_pool = {
                normalize_loose(c) for t in _MATERIAL_CLAIM_TYPES for c in candidate_claims.get(t, [])
            }
            has_genuine_new_claim = any(
                normalize_loose(c) not in candidate_material_pool for c in new_material_claims
            )
            if not has_genuine_new_claim:
                reason = (
                    f"confident match, differently-worded title (entity_overlap={entity_overlap:.2f}, "
                    f"title_overlap={title_overlap:.2f}, distinctive_shared_entities={distinctive}) but "
                    f"no material date/money/percentage/quantity claim in the new title beyond what the "
                    f"candidate's own title already carries - a corroborating report, not new substance "
                    f"(candidate topic_bucket={candidate.topic_bucket}, category={candidate.category})"
                )
                return signature, _mk(
                    SUPPORTING_SOURCE, candidate.id, combined, reason,
                    has_distinctive_shared_entity=True,
                )
            reason = (
                f"confident match, materially different title (entity_overlap={entity_overlap:.2f}, "
                f"title_overlap={title_overlap:.2f}, distinctive_shared_entities={distinctive}, "
                f"content_type={new_content_type}/{candidate_content_type}, new_material_claims="
                f"{new_material_claims}, candidate topic_bucket={candidate.topic_bucket}, "
                f"category={candidate.category})"
            )
            return signature, _mk(
                STORY_UPDATE, candidate.id, combined, reason,
                has_distinctive_shared_entity=True,
            )

        if not content_type_ok:
            reason = (
                f"score cleared the confident threshold ({combined:.2f}) but the new event's "
                f"editorial content type ({new_content_type}) differs from the matched candidate's "
                f"({candidate_content_type}) - same entity/product does not mean same editorial "
                f"Story (e.g. a review vs. a guide about the same game) - downgraded "
                f"(entity_overlap={entity_overlap:.2f}, title_overlap={title_overlap:.2f})"
            )
        else:
            reason = (
                f"score cleared the confident threshold ({combined:.2f}) but no distinctive shared "
                f"entity survived (only generic/common shared entities, or none) and title_overlap "
                f"({title_overlap:.2f}) is below the near-identical-title threshold - downgraded to "
                f"avoid a confident same-story claim resting on a coincidental generic-entity match "
                f"(entity_overlap={entity_overlap:.2f})"
            )
        return signature, _mk(
            UNCERTAIN_MATCH, candidate.id, combined, reason,
            has_distinctive_shared_entity=bool(distinctive),
        )

    reason = (
        f"borderline score {combined:.2f} between thresholds [{_LOW_THRESHOLD:.2f}, "
        f"{_HIGH_THRESHOLD:.2f}) - not confidently new or matched "
        f"(entity_overlap={entity_overlap:.2f}, title_overlap={title_overlap:.2f})"
    )
    return signature, _mk(
        UNCERTAIN_MATCH, candidate.id, combined, reason,
        has_distinctive_shared_entity=bool(distinctive_at_best),
    )
