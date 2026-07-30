"""Phase 16.5 - image provenance calibration for aggregator sources (docs/
phase16_5_image_calibration_report.md). M7's own real 100-event validation found 29/100 events
selected the exact same Google-hosted generic app icon as their top-ranked "editorial" image -
every one of those events' article URL was a `news.google.com` redirect/interstitial page, and the
"image" was always Google News' own generic branding served from a Google-owned asset CDN, never
the publisher's real photo.

Pure unit tests - no networking, no database, mirrors tests/test_image_relevance.py's own
established `_candidate()`-factory convention exactly (imported, not duplicated).
"""
from database.models.news_source import SourceType
from schemas.image_candidate import ImageDiscoveryMethod, QualityStatus, RelevanceStatus, TelegramReference
from services.image_relevance import _is_generic_aggregator_asset, evaluate_eligibility, rank_candidates
from tests.test_image_relevance import _candidate

_GOOGLE_NEWS_ARTICLE_URL = "https://news.google.com/rss/articles/CBMisomethingfakebutshaped"
_GOOGLE_GENERIC_ICON_URL = (
    "https://lh3.googleusercontent.com/J6_coFbogxhRI9iM864NL_liGXvsQp2AupsKei7z0cNNfDvGUmWUy20nuUhkREQyrpY4bEeIBuc=s0-w300"
)
_REAL_PUBLISHER_IMAGE_URL = "https://cdn.theverge.com/uploads/chorus/2026/07/hero.jpg"


# ---------------------------------------------------------------------------
# Required case 1: Google News generic icon -> rejected (ineligible), never ranked.
# ---------------------------------------------------------------------------


def test_google_news_generic_icon_is_ineligible():
    candidate = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url=_GOOGLE_GENERIC_ICON_URL,
        quality_status=QualityStatus.ACCEPTED,
    )
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is False
    assert reason == "generic_aggregator_asset"


def test_google_news_generic_icon_never_becomes_the_ranked_top_candidate():
    candidate = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url=_GOOGLE_GENERIC_ICON_URL,
        quality_status=QualityStatus.ACCEPTED, candidate_id="generic-icon",
    )
    ranked = rank_candidates(
        [candidate], event_title="Some real headline", event_content=None,
        event_url=_GOOGLE_NEWS_ARTICLE_URL, source_name="Some Source", top_candidates=5,
    )
    assert len(ranked) == 1
    relevance = ranked[0].relevance_validation
    assert relevance is not None
    assert relevance.status == RelevanceStatus.INELIGIBLE
    assert relevance.eligible_for_editorial is False


# ---------------------------------------------------------------------------
# Required case 2: Google News article with a real publisher image -> allowed, ranked normally.
# ---------------------------------------------------------------------------


def test_google_news_article_with_real_publisher_image_remains_eligible():
    candidate = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url=_REAL_PUBLISHER_IMAGE_URL,
        quality_status=QualityStatus.ACCEPTED,
    )
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is True
    assert reason == "eligible"


def test_google_news_article_with_real_publisher_image_can_be_top_ranked():
    """The IMPORTANT RULE, exercised end to end: a Google-News-sourced article whose actual image
    is the publisher's own must still be preserved as a legitimate, rankable candidate - the fix
    must never blanket-reject every candidate for a Google-News-sourced event."""
    generic = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url=_GOOGLE_GENERIC_ICON_URL,
        quality_status=QualityStatus.ACCEPTED, candidate_id="generic-icon", order=0,
    )
    real = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url=_REAL_PUBLISHER_IMAGE_URL,
        quality_status=QualityStatus.ACCEPTED, alt_text="Real headline photo", candidate_id="real-image", order=1,
    )
    ranked = rank_candidates(
        [generic, real], event_title="Real headline photo story", event_content=None,
        event_url=_GOOGLE_NEWS_ARTICLE_URL, source_name="Some Source", top_candidates=5,
    )
    by_id = {c.candidate_id: c for c in ranked}
    assert by_id["generic-icon"].relevance_validation.status == RelevanceStatus.INELIGIBLE
    assert by_id["real-image"].relevance_validation.status == RelevanceStatus.RANKED
    assert by_id["real-image"].relevance_validation.eligible_for_editorial is True


# ---------------------------------------------------------------------------
# Required case 3: normal RSS source (non-Google-News article) -> unchanged.
# ---------------------------------------------------------------------------


def test_normal_rss_source_is_unaffected():
    candidate = _candidate(
        source_url="https://example.com/article/x", remote_url="https://example.com/img/hero.jpg",
        quality_status=QualityStatus.ACCEPTED,
    )
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is True
    assert reason == "eligible"


def test_normal_rss_source_embedding_a_google_hosted_image_is_unaffected():
    """A non-Google-News article that happens to embed a legitimate Google-CDN-hosted image (e.g.
    a Blogger/Google-Photos-hosted picture) must not be rejected - only the specific combination of
    a Google-News-sourced *article* AND a Google-hosted *image* is excluded, never the image host
    alone (the brief's own explicit ARTICLE SOURCE vs IMAGE SOURCE rule)."""
    candidate = _candidate(
        source_url="https://example.com/article/x", remote_url=_GOOGLE_GENERIC_ICON_URL,
        quality_status=QualityStatus.ACCEPTED,
    )
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is True
    assert reason == "eligible"


# ---------------------------------------------------------------------------
# Required case 4: Telegram source -> unchanged (no source_url, structurally exempt).
# ---------------------------------------------------------------------------


def test_telegram_native_source_is_unaffected():
    candidate = _candidate(
        discovery=ImageDiscoveryMethod.TELEGRAM_PHOTO,
        source_url=None, remote_url=None,
        telegram=TelegramReference(message_id=1, media_kind="photo", media_id=42),
        quality_status=QualityStatus.ACCEPTED,
    )
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is True
    assert reason == "eligible"


# ---------------------------------------------------------------------------
# Required case 5: NEWS_API source -> unchanged.
# ---------------------------------------------------------------------------


def test_news_api_source_is_unaffected():
    candidate = _candidate(
        source_url="https://news-api-publisher.example.com/article/x",
        remote_url="https://news-api-publisher.example.com/img/hero.jpg",
        quality_status=QualityStatus.ACCEPTED,
    )
    candidate = candidate.model_copy(update={"source_type": SourceType.NEWS_API})
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is True
    assert reason == "eligible"


# ---------------------------------------------------------------------------
# Boundary / false-positive-resistance checks on the detector itself.
# ---------------------------------------------------------------------------


def test_detector_matches_legacy_google_com_news_path_form():
    candidate = _candidate(
        source_url="https://www.google.com/news?story=abc", remote_url=_GOOGLE_GENERIC_ICON_URL,
        quality_status=QualityStatus.ACCEPTED,
    )
    assert _is_generic_aggregator_asset(candidate) is True


def test_detector_matches_gstatic_image_host():
    candidate = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url="https://www.gstatic.com/news/img/icon.png",
        quality_status=QualityStatus.ACCEPTED,
    )
    assert _is_generic_aggregator_asset(candidate) is True


def test_detector_never_matches_a_lookalike_domain():
    """A domain that merely contains "google" as a substring (never a real Google-owned domain)
    must never be treated as the aggregator - registrable-domain comparison only, never a substring
    check (docs' own established precedent, services.image_relevance.classify_relationship)."""
    candidate = _candidate(
        source_url="https://news.notgoogle.com/rss/articles/x", remote_url="https://cdn.notgoogle.com/icon.png",
        quality_status=QualityStatus.ACCEPTED,
    )
    assert _is_generic_aggregator_asset(candidate) is False


def test_detector_requires_both_article_and_image_signal():
    """Google-News-sourced article, but no remote_url at all (e.g. still-`None` for a not-yet-
    resolved candidate) - never a false positive on missing data."""
    candidate = _candidate(
        source_url=_GOOGLE_NEWS_ARTICLE_URL, remote_url=None, quality_status=QualityStatus.ACCEPTED,
    )
    assert _is_generic_aggregator_asset(candidate) is False


def test_detector_ignores_missing_source_url():
    candidate = _candidate(source_url=None, remote_url=_GOOGLE_GENERIC_ICON_URL, quality_status=QualityStatus.ACCEPTED)
    assert _is_generic_aggregator_asset(candidate) is False
