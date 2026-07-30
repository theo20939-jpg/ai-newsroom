"""Phase 16 M4: deterministic relevance ranking (docs/phase16_m4_relevance_ranking_report.md).
Pure, metadata-only logic - no networking (M2 already fetched everything; this module never issues
a request), no persistence, no visual/semantic image understanding. Answers only "how confidently is
this technically-valid, editorially-usable candidate tied to THIS story," using lexical overlap,
discovery provenance, and source/article relationship signals already present on the candidate and
the NewsEvent - never image content itself.

Deliberately separate from `services.image_quality` (M3: "is this image usable") and `services.
image_deduplication` (M3: "is this a duplicate") - M4 only ranks candidates that already survived
both. M3's own `quality_score` is reused as one bounded relevance component (§12), never
recomputed or re-penalized signal-by-signal (double-counting audit, §14).
"""
import html
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from schemas.image_candidate import (
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    QualityStatus,
    RelevanceStatus,
    RelevanceValidation,
    SourceRelationship,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score-component budgets (docs §15 - centralized, no dead component, sum to 100).
# ---------------------------------------------------------------------------

PROVENANCE_MAX = 30
RELATIONSHIP_MAX = 20
TEXTUAL_OVERLAP_MAX = 25
QUALITY_MAX = 15
METADATA_CONFIDENCE_MAX = 10

# Relevance-specific penalties only (docs §14's double-counting audit) - M3's own possible_logo/
# possible_avatar/possible_banner/possible_placeholder/possible_icon/possible_thumbnail penalties
# already reduced quality_score, which already reduces the `quality` component above; none of those
# signals are re-penalized here.
PENALTY_REVIEW_STATUS = -4
PENALTY_WEAK_TEXT_EVIDENCE = -2
PENALTY_CONFLICTING_RELATIONSHIP = -5
PENALTY_THIRD_PARTY_UNKNOWN = -2

_INSUFFICIENT_EVIDENCE_PROVENANCE_FLOOR = 50

# ---------------------------------------------------------------------------
# Provenance hierarchy (docs §6) - "how confidently is this image tied to the original
# publication," never "does it visually show the news subject." Media attached directly to the
# original source item (Telegram photo/document, RSS entry-level media) outranks generic webpage
# metadata (OG/JSON-LD/Twitter), which in turn outranks weak fallback signals (image_src, unknown).
# ---------------------------------------------------------------------------

PROVENANCE_TABLE: dict[ImageDiscoveryMethod, int] = {
    ImageDiscoveryMethod.TELEGRAM_PHOTO: 100,
    ImageDiscoveryMethod.TELEGRAM_DOCUMENT: 95,
    ImageDiscoveryMethod.RSS_MEDIA_CONTENT: 90,
    ImageDiscoveryMethod.RSS_ENCLOSURE: 80,
    ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE: 70,
    ImageDiscoveryMethod.OPEN_GRAPH_IMAGE: 68,
    ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE: 65,
    ImageDiscoveryMethod.TWITTER_IMAGE: 60,
    ImageDiscoveryMethod.TELEGRAM_THUMBNAIL: 55,
    ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL: 50,
    ImageDiscoveryMethod.RSS_INLINE_IMAGE: 45,
    ImageDiscoveryMethod.IMAGE_SRC_LINK: 40,
    ImageDiscoveryMethod.SOURCE_NATIVE_UNKNOWN: 20,
}

_NATIVE_DISCOVERY_METHODS = frozenset(
    {
        ImageDiscoveryMethod.TELEGRAM_PHOTO,
        ImageDiscoveryMethod.TELEGRAM_DOCUMENT,
        ImageDiscoveryMethod.TELEGRAM_THUMBNAIL,
        ImageDiscoveryMethod.RSS_MEDIA_CONTENT,
        ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL,
        ImageDiscoveryMethod.RSS_ENCLOSURE,
        ImageDiscoveryMethod.RSS_INLINE_IMAGE,
    }
)

_RELATIONSHIP_CONFIDENCE: dict[SourceRelationship, int] = {
    SourceRelationship.NATIVE_SAME_ITEM: 100,
    SourceRelationship.SAME_ARTICLE: 90,
    SourceRelationship.SAME_DOMAIN: 80,
    SourceRelationship.SOURCE_CDN_OR_RELATED: 60,
    SourceRelationship.THIRD_PARTY_UNKNOWN: 40,
    SourceRelationship.UNRELATED_OR_CONFLICTING: 10,
}

# ---------------------------------------------------------------------------
# Text normalization (docs §8) - Unicode-safe, no stemming/lemmatization, no translation, no
# fuzzy matching, no entity aliasing.
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_IMAGE_EXTENSIONS = re.compile(r"\.(jpe?g|png|gif|webp|svg|avif|bmp|ico|tiff?)$", re.IGNORECASE)
_SIZE_SUFFIX = re.compile(
    r"([-_@](?:\d{2,4}x\d{2,4}|\d+w|\d+px|2x|3x|scaled|thumb|thumbnail))+$", re.IGNORECASE
)

_ENGLISH_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for", "with", "is",
        "are", "was", "were", "this", "that", "these", "those", "it", "its", "as", "by", "from",
        "has", "have", "had", "be", "been", "will", "would", "can", "could", "not", "no",
    }
)
_RUSSIAN_STOPWORDS = frozenset(
    {
        "и", "в", "на", "с", "по", "для", "от", "из", "что", "это", "как", "к", "у", "не", "о",
        "за", "до", "при", "же", "но", "а", "или", "то", "его", "ее", "их", "тот", "эта",
    }
)
# Generic image-metadata vocabulary (docs §9) - present on countless unrelated images, must never
# itself count as evidence of story relevance.
_GENERIC_IMAGE_TOKENS = frozenset(
    {
        "image", "photo", "picture", "thumbnail", "thumb", "preview", "hero", "banner", "cover",
        "og", "social", "news", "article", "upload", "media", "default", "img", "pic",
    }
)
_STOPWORDS = _ENGLISH_STOPWORDS | _RUSSIAN_STOPWORDS | _GENERIC_IMAGE_TOKENS

# Weak/generic informative-content words (docs §11) - down-weighted, never excluded outright (a
# real headline can legitimately be built almost entirely of these for a very generic story).
_WEAK_TOKENS = frozenset(
    {
        "technology", "company", "new", "release", "update", "launch", "announce", "announces",
        "announced", "today", "official", "world", "market", "best", "top", "review", "guide",
        "latest", "big", "major", "report", "reports",
    }
)

_CONTENT_TOKEN_LIMIT = 60


def _strip_filename_noise(basename: str) -> str:
    """Remove a trailing image extension and a trailing dimension/scale suffix (e.g.
    "-1200x630", "@2x", "-scaled") before tokenizing - these are layout artifacts, never
    editorial evidence (docs §8)."""
    stripped = _IMAGE_EXTENSIONS.sub("", basename)
    stripped = _SIZE_SUFFIX.sub("", stripped)
    return stripped


def tokenize(text: str | None) -> list[str]:
    """Unicode-NFKC-normalize, HTML-entity-decode, URL-decode, casefold, then split on any
    non-alphanumeric boundary (works uniformly for Latin and Cyrillic). No stemming, no
    lemmatization, no translation - a purely mechanical, deterministic split (docs §8)."""
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text)
    normalized = html.unescape(normalized)
    try:
        normalized = unquote(normalized)
    except Exception:
        pass
    normalized = normalized.casefold()
    return _TOKEN_PATTERN.findall(normalized)


def _has_digit(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


def _is_acronym_in_original(token: str, original_text: str) -> bool:
    """Detects a 2-6 letter all-uppercase run in the ORIGINAL (pre-casefold) text matching this
    (already-casefolded) token - acronyms/model codes are informative tokens (docs §11)."""
    if not (2 <= len(token) <= 6):
        return False
    return bool(re.search(rf"\b{re.escape(token.upper())}\b", original_text))


def token_weight(token: str, *, original_text: str) -> float:
    """Bounded lexical importance heuristic (docs §11) - no named-entity recognition, no identity
    inference. Digits/short-acronym tokens (versions, model numbers) score highest; weak/generic
    words are down-weighted, not deleted; single-character non-digit tokens are treated as noise."""
    if token in _STOPWORDS:
        return 0.0
    if len(token) == 1 and not token.isdigit():
        return 0.2
    if _has_digit(token):
        return 1.5
    if _is_acronym_in_original(token, original_text):
        return 1.3
    if token in _WEAK_TOKENS:
        return 0.4
    return 1.0


def _weighted_token_set(text: str | None) -> dict[str, float]:
    tokens = tokenize(text)
    return {t: token_weight(t, original_text=text or "") for t in tokens}


def _filename_tokens(url: str | None) -> list[str]:
    if not url:
        return []
    try:
        path = urlsplit(url).path
    except ValueError:
        return []
    basename = path.rsplit("/", 1)[-1]
    if not basename:
        return []
    cleaned = _strip_filename_noise(basename)
    return tokenize(cleaned)


def _has_meaningful_tokens(weighted: dict[str, float]) -> bool:
    return any(weight > 0 for weight in weighted.values())


# ---------------------------------------------------------------------------
# Hostname helpers (docs §7) - naive last-two-label "registrable domain" heuristic, documented
# limitation (no public-suffix-list handling for multi-part TLDs like co.uk); conservative by
# construction since it only ever widens a match, never narrows eligibility.
# ---------------------------------------------------------------------------


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _registrable_domain(host: str | None) -> str | None:
    if not host:
        return None
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def classify_relationship(candidate: ImageCandidate, event_url: str | None) -> SourceRelationship:
    """Docs §7. Native (Telegram/RSS-entry-level) candidates have no separate "article page" to
    compare against - they came from the very same source item as the event itself, the strongest
    possible relationship. Metadata-discovered candidates (OG/JSON-LD/Twitter/image_src) are
    compared against the article page M2 actually fetched (`candidate.source_url`)."""
    if candidate.telegram is not None or candidate.discovery_method in _NATIVE_DISCOVERY_METHODS:
        return SourceRelationship.NATIVE_SAME_ITEM

    if not candidate.source_url or not event_url:
        return SourceRelationship.THIRD_PARTY_UNKNOWN

    source_host = _hostname(candidate.source_url)
    event_host = _hostname(event_url)
    if not source_host or not event_host:
        return SourceRelationship.THIRD_PARTY_UNKNOWN

    if _registrable_domain(source_host) != _registrable_domain(event_host):
        # The page M2 actually fetched is not (even loosely) the event's own article - defensive;
        # should not normally occur given M2 only ever fetches `article_url == event.url`, but a
        # redirect to a genuinely different site is conflicting evidence, not merely "unknown".
        return SourceRelationship.UNRELATED_OR_CONFLICTING

    image_host = _hostname(candidate.remote_url)
    if not image_host:
        return SourceRelationship.SAME_ARTICLE

    if image_host == source_host:
        return SourceRelationship.SAME_ARTICLE
    if _registrable_domain(image_host) == _registrable_domain(source_host):
        return SourceRelationship.SAME_DOMAIN
    # Discovered by parsing the correct article page, just hosted on an external asset domain/CDN -
    # uncertainty, not rejection (docs §7's explicit "a third-party CDN should normally receive
    # uncertainty, not automatic rejection").
    return SourceRelationship.SOURCE_CDN_OR_RELATED


# ---------------------------------------------------------------------------
# Eligibility (docs §4).
# ---------------------------------------------------------------------------

_INELIGIBLE_QUALITY_STATUSES = frozenset(
    {QualityStatus.REJECTED_QUALITY, QualityStatus.DUPLICATE_EXACT, QualityStatus.DUPLICATE_NEAR}
)

# Phase 16.5 (docs/phase16_5_image_calibration_report.md) - M7's own real 100-event validation
# found 29% of sampled events selected the exact same Google-hosted generic app icon as their
# top-ranked "editorial" image. Root cause: a Google News RSS item's own article URL is a
# news.google.com redirect/interstitial page, not the publisher's real article - that page's own
# og:image is Google News' own generic branding, always served from one of Google's own generic
# asset CDNs, never the publisher's own domain.
#
# Deliberately keys on BOTH signals together, never either alone (the brief's own explicit "ARTICLE
# SOURCE vs IMAGE SOURCE" rule): a Google-News-sourced article whose *image* is hosted on the real
# publisher's own domain must remain fully eligible (a Google News article can have a valid
# publisher image); a normal, non-Google-News article that happens to embed a legitimate image
# hosted on a Google-owned CDN (e.g. a Blogger/Google-Photos-hosted picture) must also remain
# untouched - only the specific combination (Google-News-sourced article AND a Google-owned image
# host) is excluded, since that combination is what M7 actually observed to be Google's own generic
# branding, never a real per-article photo.
_AGGREGATOR_ARTICLE_REGISTRABLE_DOMAIN = "google.com"
_GENERIC_ASSET_IMAGE_REGISTRABLE_DOMAINS = frozenset({"google.com", "googleusercontent.com", "gstatic.com"})


def _is_generic_aggregator_asset(candidate: ImageCandidate) -> bool:
    """True only when the article page this candidate was discovered on is itself a Google News
    aggregator page (`source_url`'s registrable domain is `google.com` - covers both the current
    `news.google.com` subdomain and the legacy `google.com/news` path form) AND the candidate's own
    image is hosted on one of Google's own generic asset domains - never based on the article
    domain alone. Native (Telegram/RSS-entry-level) candidates have no `source_url` at all and are
    structurally exempt (matches `classify_relationship`'s own "native candidates have no separate
    article page" precedent)."""
    if _registrable_domain(_hostname(candidate.source_url)) != _AGGREGATOR_ARTICLE_REGISTRABLE_DOMAIN:
        return False
    image_host = _hostname(candidate.remote_url)
    if not image_host:
        return False
    return _registrable_domain(image_host) in _GENERIC_ASSET_IMAGE_REGISTRABLE_DOMAINS


def evaluate_eligibility(candidate: ImageCandidate) -> tuple[bool, str]:
    """Docs §4. Only M3 `accepted`/`review` cluster representatives are potentially eligible -
    everything else (M2 technical failure, M3 hard rejection, non-representative duplicate, or
    Phase 16.5's own generic-aggregator-asset exclusion) is ineligible but remains fully visible in
    the structured result with its reason (never silently dropped)."""
    if candidate.status != ImageCandidateStatus.VALIDATED:
        return False, f"not_technically_validated:{candidate.status.value}"
    quality = candidate.quality_validation
    if quality is None:
        return False, "not_quality_analyzed"
    if quality.status in _INELIGIBLE_QUALITY_STATUSES:
        return False, f"m3_status:{quality.status.value}"
    if _is_generic_aggregator_asset(candidate):
        return False, "generic_aggregator_asset"
    return True, "eligible"


# ---------------------------------------------------------------------------
# Textual overlap (docs §9/§10).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _EventContext:
    title_tokens: dict[str, float]
    content_tokens: dict[str, float]
    source_tokens: dict[str, float]
    event_url: str | None


def build_event_context(
    *, event_title: str | None, event_content: str | None, source_name: str | None, event_url: str | None
) -> _EventContext:
    content_snippet = None
    if event_content:
        content_snippet = " ".join(event_content.split()[:_CONTENT_TOKEN_LIMIT])
    return _EventContext(
        title_tokens=_weighted_token_set(event_title),
        content_tokens=_weighted_token_set(content_snippet),
        source_tokens=_weighted_token_set(source_name),
        event_url=event_url,
    )


def _candidate_text_tokens(candidate: ImageCandidate) -> dict[str, float]:
    """Union of alt text, caption, and filename-derived tokens - each already individually
    weighted against its own original text for acronym detection."""
    merged: dict[str, float] = {}
    for text in (candidate.alt_text, candidate.caption):
        merged.update(_weighted_token_set(text))
    filename = _filename_tokens(candidate.remote_url)
    filename_text = " ".join(filename)
    for token in filename:
        weight = token_weight(token, original_text=filename_text)
        merged[token] = max(merged.get(token, 0.0), weight)
    return merged


def _overlap_raw(candidate_tokens: dict[str, float], target_tokens: dict[str, float]) -> float:
    """Set-based (unique-token) overlap - a repeated token contributes exactly once, so no signal
    can be inflated by repetition (docs §10)."""
    matched = set(candidate_tokens) & set(target_tokens)
    return sum(min(candidate_tokens[t], target_tokens[t]) for t in matched)


_TITLE_WEIGHT = 3.0
_SOURCE_WEIGHT = 2.0
_CONTENT_WEIGHT = 1.0
# Calibrated so a single strong (weight~1.5) title token match alone already produces a
# meaningfully non-zero score, while requiring several matches (or one title + supporting
# content/source matches) to approach the component ceiling - see docs §21 for the backtest
# distribution this was checked against.
_OVERLAP_NORMALIZER = 9.0


def textual_overlap_score(
    candidate_tokens: dict[str, float], ctx: _EventContext
) -> tuple[int, bool]:
    """Returns (0-100 raw overlap score, has_any_evidence). Title overlap outweighs generic body
    overlap (docs §10); missing candidate text yields an explicit 0, never a bonus."""
    if not candidate_tokens:
        return 0, False
    raw = (
        _overlap_raw(candidate_tokens, ctx.title_tokens) * _TITLE_WEIGHT
        + _overlap_raw(candidate_tokens, ctx.source_tokens) * _SOURCE_WEIGHT
        + _overlap_raw(candidate_tokens, ctx.content_tokens) * _CONTENT_WEIGHT
    )
    score = max(0, min(100, round(raw / _OVERLAP_NORMALIZER * 100)))
    return score, raw > 0


# ---------------------------------------------------------------------------
# Metadata confidence (docs §11) - coverage-based, neutral baseline so missing metadata is neither
# rewarded nor catastrophically punished.
# ---------------------------------------------------------------------------

_METADATA_BASELINE = 40


def _metadata_confidence(
    candidate: ImageCandidate, *, alt_meaningful: bool, filename_usable: bool
) -> tuple[int, dict[str, bool]]:
    score = _METADATA_BASELINE
    caption_meaningful = bool(candidate.caption and _has_meaningful_tokens(_weighted_token_set(candidate.caption)))
    dims_match = False
    technical = candidate.technical_validation
    if technical and technical.width and technical.height and candidate.declared_width and candidate.declared_height:
        dims_match = (
            abs(technical.width - candidate.declared_width) <= max(2, round(candidate.declared_width * 0.05))
            and abs(technical.height - candidate.declared_height) <= max(2, round(candidate.declared_height * 0.05))
        )
    if alt_meaningful:
        score += 15
    if caption_meaningful:
        score += 15
    if filename_usable:
        score += 15
    if dims_match:
        score += 15
    coverage = {
        "candidate_alt_available": alt_meaningful,
        "candidate_title_available": caption_meaningful,
        "filename_available": filename_usable,
        "article_domain_match": dims_match,
    }
    return max(0, min(100, score)), coverage


# ---------------------------------------------------------------------------
# Reason generation (docs §16) - deterministic, template-based, never a visual-content claim.
# ---------------------------------------------------------------------------


def _build_reason(
    *,
    discovery_method: ImageDiscoveryMethod,
    relationship: SourceRelationship,
    has_text_evidence: bool,
    quality_score: int,
) -> str:
    provenance_phrase = {
        ImageDiscoveryMethod.TELEGRAM_PHOTO: "native Telegram photo",
        ImageDiscoveryMethod.TELEGRAM_DOCUMENT: "native Telegram image document",
        ImageDiscoveryMethod.TELEGRAM_THUMBNAIL: "native Telegram thumbnail",
        ImageDiscoveryMethod.RSS_MEDIA_CONTENT: "RSS entry media image",
        ImageDiscoveryMethod.RSS_ENCLOSURE: "RSS enclosure image",
        ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL: "RSS entry thumbnail",
        ImageDiscoveryMethod.RSS_INLINE_IMAGE: "RSS inline content image",
        ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE: "original article Open Graph image",
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE: "original article Open Graph image",
        ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE: "original article structured-data image",
        ImageDiscoveryMethod.TWITTER_IMAGE: "original article Twitter Card image",
        ImageDiscoveryMethod.IMAGE_SRC_LINK: "generic in-page image link",
        ImageDiscoveryMethod.SOURCE_NATIVE_UNKNOWN: "unknown-provenance native media",
    }.get(discovery_method, "candidate image")

    relationship_phrase = {
        SourceRelationship.NATIVE_SAME_ITEM: None,
        SourceRelationship.SAME_ARTICLE: "from the article page",
        SourceRelationship.SAME_DOMAIN: "from the article's own domain",
        SourceRelationship.SOURCE_CDN_OR_RELATED: "hosted on a related asset domain",
        SourceRelationship.THIRD_PARTY_UNKNOWN: "with an unverified source relationship",
        SourceRelationship.UNRELATED_OR_CONFLICTING: "with a conflicting source relationship",
    }[relationship]

    text_phrase = "strong metadata overlap" if has_text_evidence else "weak textual evidence"
    quality_phrase = "high technical quality" if quality_score >= 80 else None

    parts = [provenance_phrase]
    if relationship_phrase:
        parts.append(relationship_phrase)
    parts.append(f"with {text_phrase}")
    if quality_phrase:
        parts.append(f"and {quality_phrase}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Per-candidate scoring.
# ---------------------------------------------------------------------------


def score_candidate(candidate: ImageCandidate, ctx: _EventContext) -> RelevanceValidation:
    """Scores one already-eligible candidate. Caller (`rank_candidates`) is responsible for
    eligibility filtering, ranking, and top-N selection - this function only computes one
    candidate's own components/penalties/score in isolation, so results are independent of
    processing order (docs §15's determinism requirement)."""
    start = time.monotonic()
    quality = candidate.quality_validation
    assert quality is not None  # guaranteed by eligibility filtering upstream

    relationship = classify_relationship(candidate, ctx.event_url)
    provenance_confidence = PROVENANCE_TABLE.get(candidate.discovery_method, 20)
    relationship_confidence = _RELATIONSHIP_CONFIDENCE[relationship]

    candidate_tokens = _candidate_text_tokens(candidate)
    overlap_raw, has_text_evidence = textual_overlap_score(candidate_tokens, ctx)

    alt_meaningful = bool(candidate.alt_text and _has_meaningful_tokens(_weighted_token_set(candidate.alt_text)))
    filename_tokens = _filename_tokens(candidate.remote_url)
    filename_usable = any(
        token_weight(t, original_text=" ".join(filename_tokens)) > 0 for t in filename_tokens
    )
    metadata_raw, coverage = _metadata_confidence(candidate, alt_meaningful=alt_meaningful, filename_usable=filename_usable)

    components = {
        "provenance": round(provenance_confidence / 100 * PROVENANCE_MAX),
        "source_relationship": round(relationship_confidence / 100 * RELATIONSHIP_MAX),
        "textual_overlap": round(overlap_raw / 100 * TEXTUAL_OVERLAP_MAX),
        "quality": round(quality.quality_score / 100 * QUALITY_MAX),
        "metadata_confidence": round(metadata_raw / 100 * METADATA_CONFIDENCE_MAX),
    }

    penalties: dict[str, int] = {}
    if quality.status == QualityStatus.REVIEW:
        penalties["review_status"] = PENALTY_REVIEW_STATUS
    no_text_at_all = not (alt_meaningful or filename_usable or (candidate.caption and _has_meaningful_tokens(_weighted_token_set(candidate.caption))))
    if no_text_at_all:
        penalties["weak_text_evidence"] = PENALTY_WEAK_TEXT_EVIDENCE
    if relationship == SourceRelationship.UNRELATED_OR_CONFLICTING:
        penalties["conflicting_relationship"] = PENALTY_CONFLICTING_RELATIONSHIP
    elif relationship == SourceRelationship.THIRD_PARTY_UNKNOWN:
        penalties["third_party_unknown_provenance"] = PENALTY_THIRD_PARTY_UNKNOWN

    raw_score = sum(components.values()) + sum(penalties.values())
    relevance_score = max(0, min(100, raw_score))

    status = RelevanceStatus.RANKED
    if (
        not has_text_evidence
        and relationship in (SourceRelationship.THIRD_PARTY_UNKNOWN, SourceRelationship.UNRELATED_OR_CONFLICTING)
        and provenance_confidence < _INSUFFICIENT_EVIDENCE_PROVENANCE_FLOOR
    ):
        status = RelevanceStatus.INSUFFICIENT_EVIDENCE

    reason = _build_reason(
        discovery_method=candidate.discovery_method, relationship=relationship,
        has_text_evidence=has_text_evidence, quality_score=quality.quality_score,
    )

    return RelevanceValidation(
        status=status, eligibility_reason="eligible", relevance_score=relevance_score,
        source_relationship=relationship, components=components, penalties=penalties,
        coverage=coverage, reason=reason, duration_ms=int((time.monotonic() - start) * 1000),
    )


# ---------------------------------------------------------------------------
# Ranking (docs §16/§17).
# ---------------------------------------------------------------------------


def _rank_sort_key(candidate: ImageCandidate) -> tuple:
    relevance = candidate.relevance_validation
    assert relevance is not None
    quality = candidate.quality_validation
    quality_score = quality.quality_score if quality else 0
    provenance_component = relevance.components.get("provenance", 0)
    overlap_component = relevance.components.get("textual_overlap", 0)
    return (
        -relevance.relevance_score,
        -provenance_component,
        -overlap_component,
        -quality_score,
        candidate.discovery_order,
        candidate.candidate_id,
    )


def rank_candidates(
    candidates: list[ImageCandidate],
    *,
    event_title: str | None,
    event_content: str | None,
    event_url: str | None,
    source_name: str | None,
    top_candidates: int,
) -> list[ImageCandidate]:
    """The sole entry point. Returns every input candidate, each with `relevance_validation` set
    (ineligible ones get `status=ineligible` and no score) - nothing is silently dropped from the
    structured result. Deterministic and idempotent: two calls with the same input (regardless of
    list order) produce the same ranking, because ranking is computed from a full re-sort with a
    stable final tie-breaker (`candidate_id`), not from insertion order."""
    ctx = build_event_context(
        event_title=event_title, event_content=event_content, source_name=source_name, event_url=event_url
    )

    scored: list[ImageCandidate] = []
    for candidate in candidates:
        eligible, reason = evaluate_eligibility(candidate)
        if not eligible:
            scored.append(candidate.model_copy(update={
                "relevance_validation": RelevanceValidation(status=RelevanceStatus.INELIGIBLE, eligibility_reason=reason),
                "schema_version": "m4",
            }))
            continue
        try:
            relevance = score_candidate(candidate, ctx)
        except Exception:
            logger.warning("relevance_scoring_candidate_failed", extra={"candidate_id": candidate.candidate_id})
            scored.append(candidate.model_copy(update={
                "relevance_validation": RelevanceValidation(
                    status=RelevanceStatus.INSUFFICIENT_EVIDENCE, eligibility_reason="scoring_error"
                ),
                "schema_version": "m4",
            }))
            continue
        scored.append(candidate.model_copy(update={"relevance_validation": relevance, "schema_version": "m4"}))

    rankable = [c for c in scored if c.relevance_validation and c.relevance_validation.status == RelevanceStatus.RANKED]
    rankable.sort(key=_rank_sort_key)

    top_ids = {c.candidate_id for c in rankable[:top_candidates]}
    rank_by_id = {c.candidate_id: index + 1 for index, c in enumerate(rankable)}
    final: list[ImageCandidate] = []
    for candidate in scored:
        existing = candidate.relevance_validation
        if existing is None or existing.status != RelevanceStatus.RANKED:
            final.append(candidate)
            continue
        rank = rank_by_id[candidate.candidate_id]
        final.append(candidate.model_copy(update={
            "relevance_validation": existing.model_copy(update={
                "rank": rank, "eligible_for_editorial": candidate.candidate_id in top_ids,
            })
        }))
    return final
