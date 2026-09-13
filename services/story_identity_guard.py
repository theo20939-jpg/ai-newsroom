"""STORY-CONTINUITY-P0.1 (2026-09): abstract-quality + stable-document-identity firewall.

Story Continuity (services/story_continuity.py) must not classify an upstream-matched event as
``DUPLICATE_NO_DELTA`` or ``MATERIAL_UPDATE_CANDIDATE`` when that classification rests primarily
on unsafe similarity between abstract-like / templated titles. A shared Story link is NOT
sufficient evidence of the same document - Story Memory retrieval is deliberately high-recall and
the upstream match may already be wrong.

Production evidence (STORY-CONTINUITY-P0-SHADOW-PRODUCTION-ROLLOUT-1, 2026-09-09): an arXiv
``NewsEvent.title`` holds the paper's full abstract (integrations/sources/arxiv_source.py maps
the Atom ``summary`` into the item text). Unrelated papers share templated opening clauses
("Multimodal Large Language Models (MLLMs)...", "As ...", "Learning ...", "Generating ...") and a
large common vocabulary, so title-dice, the near-verbatim-title rule AND the "distinctive shared
entity" gate all pass for genuinely unrelated documents. Of 8 shadow ``DUPLICATE_NO_DELTA``
decisions, 4 were unrelated arXiv papers; of 7 ``MATERIAL_UPDATE_CANDIDATE``, 6 were. Every false
pair had *different* arXiv identifiers; every true pair scored 1.0 (exact normalized-title
equality) and shared the identifier / the exact text.

This module does not repair the upstream Story assignment (out of scope - a later phase). It
gives Story Continuity an independent, deterministic identity check so the decision fails open
(``AMBIGUOUS``) when identity evidence is weak or contradictory.

Pure, deterministic, no I/O, no LLM, no network call, no embedding. Everything is derived from
already-loaded event/story metadata (title, url, summary). ``O(prior events in the one matched
Story)`` - never scans a historical corpus.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from services.text_normalization import normalize_loose

# --- title semantic quality ----------------------------------------------------------------------
TITLE_LIKE = "TITLE_LIKE"
ABSTRACT_LIKE = "ABSTRACT_LIKE"
TITLE_QUALITY_UNKNOWN = "UNKNOWN"

ALL_TITLE_QUALITIES: tuple[str, ...] = (TITLE_LIKE, ABSTRACT_LIKE, TITLE_QUALITY_UNKNOWN)

# Reasoned starting points from the production shadow sample (docs/
# story_continuity_p0_1_abstract_identity_guard_1_report.md Section E). The false arXiv titles
# were full abstracts: 700-2000 chars, 5-12 sentences, 120-300 words. Real news / vendor / GitHub
# / HN headlines in the same sample were <= ~90 chars and a single clause. These floors sit far
# above the longest realistic headline so a normal news title can never reach ABSTRACT_LIKE.
_ABSTRACT_CHAR_FLOOR = 300
_ABSTRACT_WORD_FLOOR = 40
_MULTI_SENTENCE_WORD_FLOOR = 25
_TITLE_LIKE_CHAR_CEIL = 150
_BORDERLINE_LEAD_IN_WORD_FLOOR = 18

# A *weak* signal, only consulted for titles that already sit in the borderline band (150-300
# chars, one sentence). Deliberately NOT the literal shadow openers ("As", "Learning",
# "Multimodal ...") - those overfit; this is the small closed set of unambiguous academic
# abstract lead-ins that are never how a news headline opens.
_ACADEMIC_LEAD_IN_RE = re.compile(
    r"^\s*(we\s|in this (paper|work|study|article)\b|this (paper|work|study|article)\b|"
    r"recent(ly)?\s+(advances|progress|work|years|developments)\b|prior\s+work\b|"
    r"existing\s+(methods?|approaches?|works?|systems?)\b)",
    re.IGNORECASE,
)

# Sentence terminator followed by whitespace + an opening character, OR end of string. Trailing
# abbreviations ("U.S.", "et al.", "Fig.", "e.g.", "vs.") are stripped first so they do not
# inflate the count for a short headline.
_ABBREV_RE = re.compile(
    r"\b(?:[A-Za-z]\.){2,}|\b(?:et al|e\.g|i\.e|Fig|vs|no|No|Dr|Mr|Mrs|Ms|Inc|Ltd|Corp|Jr|Sr)\.",
)
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s+[\"'(“‘A-Z0-9]|\s*$)")


@dataclass(frozen=True)
class TitleSemanticAssessment:
    """Structured evidence - never a hidden boolean. ``quality`` is one of ALL_TITLE_QUALITIES;
    ``reasons`` are stable machine-readable codes; ``measurements`` are the raw numeric signals
    (for observability / future calibration)."""

    quality: str
    reasons: tuple[str, ...] = ()
    measurements: dict[str, float] = field(default_factory=dict)


def _count_sentences(text: str) -> int:
    stripped = _ABBREV_RE.sub("", text)
    return len(_SENTENCE_END_RE.findall(stripped))


def _resembles_summary(norm_title: str, summary: str | None) -> bool:
    """True when the title *is* (a leading slice of) the article body/abstract rather than a
    written headline. arXiv items set title == summary exactly, which this catches cheaply."""
    if not summary:
        return False
    norm_summary = normalize_loose(summary)
    if not norm_summary or len(norm_summary) < 40:
        return False
    if norm_title == norm_summary:
        return True
    # Title is a genuine prefix of a materially longer body.
    if len(norm_summary) >= len(norm_title) + 60 and norm_summary.startswith(norm_title[:200]):
        return True
    return False


def assess_title_semantic_quality(
    title: str, *, summary: str | None = None
) -> TitleSemanticAssessment:
    """Deterministic, bounded. Decides whether ``title`` reads like a real editorial/document
    title (TITLE_LIKE), like abstract / body prose (ABSTRACT_LIKE), or is genuinely borderline
    (UNKNOWN). No network, no LLM. ``summary`` (the event's own abstract/body, when available)
    only strengthens an ABSTRACT_LIKE finding, never weakens one."""
    norm = " ".join((title or "").split())
    chars = len(norm)
    words = len(norm.split())
    sentences = _count_sentences(norm)
    lead_in = bool(_ACADEMIC_LEAD_IN_RE.match(norm))
    resembles_body = _resembles_summary(normalize_loose(norm), summary)
    measurements: dict[str, float] = {
        "char_count": float(chars),
        "word_count": float(words),
        "sentence_count": float(sentences),
        "academic_lead_in": 1.0 if lead_in else 0.0,
        "resembles_summary": 1.0 if resembles_body else 0.0,
    }

    reasons: list[str] = []
    if resembles_body:
        reasons.append("title_equals_body_prefix")
    if chars >= _ABSTRACT_CHAR_FLOOR:
        reasons.append("char_count_ge_floor")
    if words >= _ABSTRACT_WORD_FLOOR:
        reasons.append("word_count_ge_floor")
    if sentences >= 3:
        reasons.append("three_or_more_sentences")
    if sentences >= 2 and words >= _MULTI_SENTENCE_WORD_FLOOR:
        reasons.append("multi_sentence_prose")
    if reasons:
        return TitleSemanticAssessment(ABSTRACT_LIKE, tuple(reasons), measurements)

    if chars <= _TITLE_LIKE_CHAR_CEIL and sentences <= 1 and not resembles_body:
        return TitleSemanticAssessment(TITLE_LIKE, ("short_single_clause",), measurements)

    if lead_in and words >= _BORDERLINE_LEAD_IN_WORD_FLOOR:
        return TitleSemanticAssessment(
            ABSTRACT_LIKE, ("academic_lead_in_borderline",), measurements
        )
    return TitleSemanticAssessment(TITLE_QUALITY_UNKNOWN, ("borderline_length",), measurements)


# --- stable document identity ------------------------------------------------------------------
ARXIV = "arxiv"
DOI = "doi"

# New-scheme arXiv id (YYMM.NNNNN, 4 or 5 digits), from an abs/pdf URL or a bare "arXiv:" token.
_ARXIV_NEW_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*)(\d{4}\.\d{4,5})(?:v(\d+))?",
    re.IGNORECASE,
)
# Old-scheme arXiv id (archive[.subclass]/YYMMNNN), only ever from an abs/pdf URL.
_ARXIV_OLD_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/([a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v(\d+))?",
    re.IGNORECASE,
)
_DOI_RE = re.compile(
    r"(?:doi\.org/|\bdoi:\s*)(10\.\d{4,9}/[-._;()/:a-z0-9]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentIdentityEvidence:
    """A stable, version-independent document key extracted deterministically from already-known
    metadata. ``identifier`` is the base id with any version suffix removed; ``version`` keeps the
    stripped suffix (arXiv ``v2`` -> ``"2"``) purely as evidence - continuity never treats two
    versions of one arXiv id as different documents."""

    namespace: str  # ARXIV | DOI
    identifier: str
    version: str | None
    source: str  # "url" | "title_text" | "summary_text"


def _clean_doi(raw: str) -> str:
    return raw.rstrip(").,;'\"").casefold()


def extract_document_identity(
    *, url: str | None, title: str | None = None, summary: str | None = None
) -> DocumentIdentityEvidence | None:
    """Deterministic, no network. Prefers the URL (canonical), then a bare ``arXiv:NNNN.NNNNN``
    token in the title, then in the summary. Returns ``None`` when no stable id is present -
    never a guess."""
    if url:
        m = _ARXIV_NEW_RE.search(url)
        if m:
            return DocumentIdentityEvidence(ARXIV, m.group(1).casefold(), m.group(2), "url")
        m = _ARXIV_OLD_RE.search(url)
        if m:
            return DocumentIdentityEvidence(ARXIV, m.group(1).casefold(), m.group(2), "url")
        m = _DOI_RE.search(url)
        if m:
            return DocumentIdentityEvidence(DOI, _clean_doi(m.group(1)), None, "url")
    for text, src in ((title, "title_text"), (summary, "summary_text")):
        if not text:
            continue
        m = _ARXIV_NEW_RE.search(text)
        if m:
            return DocumentIdentityEvidence(ARXIV, m.group(1).casefold(), m.group(2), src)
        m = _DOI_RE.search(text)
        if m:
            return DocumentIdentityEvidence(DOI, _clean_doi(m.group(1)), None, src)
    return None


# --- the continuity identity firewall --------------------------------------------------------
IDENTITY_MATCH = "STABLE_IDENTITY_MATCH"
IDENTITY_CONFLICT = "STABLE_IDENTITY_CONFLICT"
IDENTITY_INSUFFICIENT = "INSUFFICIENT_DOCUMENT_IDENTITY"

GUARD_SAFE = "SAFE"
GUARD_FAIL_OPEN = "FAIL_OPEN"

# Reason codes surfaced to services/story_continuity.py and persisted through the existing
# NewsEventStoryLink.decision_reason / material_delta diagnostic path (no new column).
REASON_STABLE_IDENTITY_MATCH = "stable_document_identity_match"
REASON_STABLE_IDENTITY_CONFLICT = "stable_identity_conflict"
REASON_POLLUTED_STORY = "polluted_multi_document_story"
REASON_ABSTRACT_LIKE_UNSAFE = "abstract_like_title_unsafe_match"
REASON_INSUFFICIENT_IDENTITY = "insufficient_document_identity"
REASON_EXACT_TITLE_IDENTITY = "exact_title_identity_sufficient"
REASON_TITLE_LIKE_OK = "title_like_identity_not_required"

# A matched Story whose OTHER events carry two or more *distinct* stable document identities is a
# multi-document cluster, not one story - Story Membership then proves nothing about document
# identity (production evidence: a 30-distinct-arXiv-id "story", and one polluted with the "As
# online dating..." headline). A confident DUPLICATE / MATERIAL_UPDATE against such a cluster is
# never safe, even when the new event's own id happens to appear among the pile (that only means
# the same mis-clustering already happened). A clean cluster - one paper collected N times, or a
# v1/v2 pair sharing a base id - has exactly ONE distinct identity and is unaffected. Real news
# Stories score 0 here (news URLs carry no stable document id).
_STORY_IDENTITY_POLLUTION_FLOOR = 2


@dataclass(frozen=True)
class ContinuityIdentityAssessment:
    """Structured, deterministic. ``verdict`` is the only field the classifier acts on
    (GUARD_FAIL_OPEN => the confident same-Story branch is skipped); everything else is
    evidence / observability."""

    verdict: str  # GUARD_SAFE | GUARD_FAIL_OPEN
    identity_status: str  # IDENTITY_MATCH | IDENTITY_CONFLICT | IDENTITY_INSUFFICIENT
    identity_namespace: str | None
    title_quality: str
    new_identity: DocumentIdentityEvidence | None
    conflicting_prior_identifiers: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    measurements: dict[str, float] = field(default_factory=dict)


def assess_continuity_identity(
    *,
    new_title: str,
    new_url: str | None,
    new_summary: str | None = None,
    prior_documents: Sequence[tuple[str | None, str | None]],
    match_is_exact_title_identity: bool,
) -> ContinuityIdentityAssessment:
    """Pure. ``prior_documents`` is ``(title, url)`` for every OTHER event already linked to the
    matched Story. ``match_is_exact_title_identity`` is the caller's own signal that Story
    Memory matched on exact normalized-title equality (its 1.0 short-circuit) - genuine identical
    text, safe without an id.

    Semantics (report Section H):
      * matched Story holds >= 2 distinct document ids -> GUARD_FAIL_OPEN  (Case E - polluted)
      * different stable ids, same namespace  -> GUARD_FAIL_OPEN  (Case A - unconditional)
      * same stable id (any version), clean cluster -> GUARD_SAFE / IDENTITY_MATCH  (Case B)
      * no comparable id + exact title text   -> GUARD_SAFE  (genuine duplicate document)
      * no comparable id + ABSTRACT_LIKE title-> GUARD_FAIL_OPEN  (Case C)
      * no comparable id + normal title       -> GUARD_SAFE  (Case D - current behaviour kept)
    """
    title_assessment = assess_title_semantic_quality(new_title, summary=new_summary)
    new_identity = extract_document_identity(url=new_url, title=new_title, summary=new_summary)
    prior_identities = [
        ident
        for (t, u) in prior_documents
        if (ident := extract_document_identity(url=u, title=t)) is not None
    ]
    distinct_prior_keys = {(p.namespace, p.identifier) for p in prior_identities}
    measurements: dict[str, float] = {
        "prior_event_count": float(len(prior_documents)),
        "prior_with_stable_identity": float(len(prior_identities)),
        "distinct_prior_identities": float(len(distinct_prior_keys)),
        **{f"title_{k}": v for k, v in title_assessment.measurements.items()},
    }
    namespace = new_identity.namespace if new_identity is not None else None

    # Case E - the matched Story is a multi-document cluster: Story Membership proves nothing.
    if len(distinct_prior_keys) >= _STORY_IDENTITY_POLLUTION_FLOOR:
        return ContinuityIdentityAssessment(
            verdict=GUARD_FAIL_OPEN,
            identity_status=IDENTITY_CONFLICT,
            identity_namespace=namespace,
            title_quality=title_assessment.quality,
            new_identity=new_identity,
            conflicting_prior_identifiers=tuple(sorted(i for _, i in distinct_prior_keys))[:8],
            reason_codes=(REASON_POLLUTED_STORY, REASON_INSUFFICIENT_IDENTITY),
            measurements=measurements,
        )

    if new_identity is not None:
        same_ns = [p for p in prior_identities if p.namespace == new_identity.namespace]
        if same_ns:
            if any(p.identifier == new_identity.identifier for p in same_ns):
                return ContinuityIdentityAssessment(
                    verdict=GUARD_SAFE,
                    identity_status=IDENTITY_MATCH,
                    identity_namespace=namespace,
                    title_quality=title_assessment.quality,
                    new_identity=new_identity,
                    reason_codes=(REASON_STABLE_IDENTITY_MATCH,),
                    measurements=measurements,
                )
            conflicting = tuple(sorted({p.identifier for p in same_ns}))
            return ContinuityIdentityAssessment(
                verdict=GUARD_FAIL_OPEN,
                identity_status=IDENTITY_CONFLICT,
                identity_namespace=namespace,
                title_quality=title_assessment.quality,
                new_identity=new_identity,
                conflicting_prior_identifiers=conflicting,
                reason_codes=(
                    REASON_STABLE_IDENTITY_CONFLICT,
                    f"{namespace}_identity_mismatch",
                ),
                measurements=measurements,
            )

    # No stable identity comparable on both sides.
    if match_is_exact_title_identity:
        return ContinuityIdentityAssessment(
            verdict=GUARD_SAFE,
            identity_status=IDENTITY_INSUFFICIENT,
            identity_namespace=namespace,
            title_quality=title_assessment.quality,
            new_identity=new_identity,
            reason_codes=(REASON_EXACT_TITLE_IDENTITY,),
            measurements=measurements,
        )
    if title_assessment.quality == ABSTRACT_LIKE:
        return ContinuityIdentityAssessment(
            verdict=GUARD_FAIL_OPEN,
            identity_status=IDENTITY_INSUFFICIENT,
            identity_namespace=namespace,
            title_quality=title_assessment.quality,
            new_identity=new_identity,
            reason_codes=(REASON_ABSTRACT_LIKE_UNSAFE, REASON_INSUFFICIENT_IDENTITY),
            measurements=measurements,
        )
    return ContinuityIdentityAssessment(
        verdict=GUARD_SAFE,
        identity_status=IDENTITY_INSUFFICIENT,
        identity_namespace=namespace,
        title_quality=title_assessment.quality,
        new_identity=new_identity,
        reason_codes=(REASON_TITLE_LIKE_OK,),
        measurements=measurements,
    )


# --- ARXIV-STORY-CLUSTERING-REPAIR-1 (2026-09): upstream candidate-eligibility check ----------
# The P0.1 guard above is DEFENSIVE - it runs after Story Memory has already matched an event
# into a Story and only demotes the *continuity classification*. This helper is used one step
# earlier, by services/story_memory.py::match_story(), to drop a candidate Story from the
# eligible set BEFORE any fuzzy score can attach the event to it. Same primitives
# (extract_document_identity, _STORY_IDENTITY_POLLUTION_FLOOR) so identity semantics stay
# centralized and deterministic; pure, no I/O. Story Memory does NOT import Story Continuity, so
# there is no circular dependency (this module imports only services/text_normalization.py).
CANDIDATE_ELIGIBLE = "ELIGIBLE"
CANDIDATE_INELIGIBLE = "INELIGIBLE"

REASON_CANDIDATE_NO_STABLE_IDENTITY = "new_event_has_no_stable_identity"
REASON_CANDIDATE_NO_COMPARABLE_IDENTITY = "candidate_has_no_comparable_identity"


def candidate_story_identity_verdict(
    *,
    new_url: str | None,
    new_title: str | None,
    candidate_documents: Sequence[tuple[str | None, str | None]],
) -> tuple[str, str]:
    """Whether a candidate Story is still eligible to be matched against `new_event`, on stable
    document identity alone. `candidate_documents` is `(title, url)` for the candidate Story's
    OWN member events.

    Returns ``(CANDIDATE_ELIGIBLE | CANDIDATE_INELIGIBLE, reason_code)``:

    * new event has no extractable stable id                     -> ELIGIBLE (never a conflict)
    * candidate holds >= 2 distinct stable document ids (polluted)-> INELIGIBLE (polluted_multi_document_story)
    * candidate holds no id in the new event's namespace         -> ELIGIBLE (absence is not a conflict, spec sec 6)
    * candidate holds the SAME base id (any version)             -> ELIGIBLE (stable_document_identity_match)
    * candidate holds a DIFFERENT base id in the same namespace  -> INELIGIBLE (<namespace>_identity_mismatch)

    Version suffixes are already stripped by extract_document_identity(), so
    ``2609.06385`` / ``v1`` / ``v2`` are one identity and never a conflict.
    """
    new_identity = extract_document_identity(url=new_url, title=new_title)
    if new_identity is None:
        return CANDIDATE_ELIGIBLE, REASON_CANDIDATE_NO_STABLE_IDENTITY

    prior_identities = [
        ident
        for (title, url) in candidate_documents
        if (ident := extract_document_identity(url=url, title=title)) is not None
    ]
    distinct_keys = {(p.namespace, p.identifier) for p in prior_identities}
    if len(distinct_keys) >= _STORY_IDENTITY_POLLUTION_FLOOR:
        return CANDIDATE_INELIGIBLE, REASON_POLLUTED_STORY

    same_namespace = [p for p in prior_identities if p.namespace == new_identity.namespace]
    if not same_namespace:
        return CANDIDATE_ELIGIBLE, REASON_CANDIDATE_NO_COMPARABLE_IDENTITY
    if any(p.identifier == new_identity.identifier for p in same_namespace):
        return CANDIDATE_ELIGIBLE, REASON_STABLE_IDENTITY_MATCH
    return CANDIDATE_INELIGIBLE, f"{new_identity.namespace}_identity_mismatch"
