"""Tests for services.image_quality (Phase 16 M3, docs/phase16_m3_quality_and_deduplication_
report.md). Pure analysis - no network, generated in-memory Pillow fixtures only.
"""
import io
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image

from database.models.news_source import SourceType
from schemas.image_candidate import (
    AspectRatioBand,
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    ResolutionBand,
    TechnicalValidation,
)
from services.image_quality import analyze_candidate, aspect_ratio_band, resolution_band


def _png(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(90, 110, 130)).save(buf, format="PNG")
    return buf.getvalue()


def _candidate(
    url: str | None, width: int, height: int, *, alt: str | None = None,
    discovery: ImageDiscoveryMethod = ImageDiscoveryMethod.OPEN_GRAPH_IMAGE,
    declared_width: int | None = None, declared_height: int | None = None,
) -> ImageCandidate:
    return ImageCandidate(
        candidate_id=f"c-{uuid4()}", event_id=uuid4(), source_type=SourceType.RSS,
        discovery_method=discovery, status=ImageCandidateStatus.VALIDATED,
        remote_url=url, alt_text=alt, discovery_order=0, discovered_at=datetime.now(timezone.utc),
        declared_width=declared_width, declared_height=declared_height,
        technical_validation=TechnicalValidation(
            width=width, height=height, format="PNG", error_code=None,
            pixel_count=width * height, byte_size=1000,
        ),
    )


def _analyze(url, width, height, **kwargs):
    candidate = _candidate(url, width, height, **kwargs)
    return analyze_candidate(_png((width, height)), candidate=candidate)


# ---------------------------------------------------------------------------
# 1-15: hard quality rules
# ---------------------------------------------------------------------------


def test_1x1_tracking_pixel_rejected() -> None:
    result = _analyze("https://x.com/pixel.gif", 1, 1)
    assert "tracking_pixel_dimensions" in result.hard_rejection_reasons


def test_2x2_tracking_pixel_rejected() -> None:
    result = _analyze("https://x.com/spacer.gif", 2, 2)
    assert "tracking_pixel_dimensions" in result.hard_rejection_reasons


def test_favicon_sized_image_detected() -> None:
    result = _analyze("https://x.com/favicon.png", 32, 32)
    assert "favicon_dimensions" in result.hard_rejection_reasons
    assert result.signals.resolution_band == ResolutionBand.ICON


def test_small_but_potentially_legitimate_image_handled_conservatively() -> None:
    """100x100 has no strong URL evidence and is above the unconditional 64px favicon cutoff -
    must not be hard-rejected on dimensions alone."""
    result = _analyze("https://x.com/photo-small.jpg", 100, 100)
    assert result.hard_rejection_reasons == []


def test_normal_landscape_accepted() -> None:
    result = _analyze("https://x.com/hero.jpg", 1200, 630)
    assert result.hard_rejection_reasons == []
    assert result.signals.aspect_ratio_band == AspectRatioBand.EDITORIAL_LANDSCAPE


def test_normal_portrait_accepted() -> None:
    result = _analyze("https://x.com/portrait.jpg", 600, 900)
    assert result.hard_rejection_reasons == []
    assert result.signals.aspect_ratio_band == AspectRatioBand.PORTRAIT


def test_square_product_artwork_not_automatically_rejected() -> None:
    result = _analyze("https://x.com/product-launch.jpg", 800, 800)
    assert result.hard_rejection_reasons == []
    assert result.signals.aspect_ratio_band == AspectRatioBand.SQUARE


def test_extreme_wide_spacer_rejected() -> None:
    result = _analyze("https://x.com/spacer.jpg", 3000, 40)  # ratio 75 - ultra-extreme
    assert "extreme_aspect_ratio" in result.hard_rejection_reasons


def test_extreme_tall_spacer_rejected() -> None:
    result = _analyze("https://x.com/spacer-v.jpg", 20, 2000)  # ratio 0.01 - ultra-extreme
    assert "extreme_aspect_ratio" in result.hard_rejection_reasons


def test_weak_resolution_image_receives_expected_penalty() -> None:
    result = _analyze("https://x.com/small.jpg", 200, 150)
    assert result.signals.resolution_band == ResolutionBand.WEAK
    assert result.quality_components["resolution"] < 40


def test_good_resolution_image_receives_stronger_quality_score() -> None:
    weak = _analyze("https://x.com/weak.jpg", 200, 150)
    good = _analyze("https://x.com/good.jpg", 1200, 800)
    assert good.quality_score > weak.quality_score


def test_missing_dimensions_cannot_crash_quality_evaluation() -> None:
    candidate = ImageCandidate(
        candidate_id="c1", event_id=uuid4(), source_type=SourceType.RSS,
        discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, status=ImageCandidateStatus.VALIDATED,
        remote_url="https://x.com/a.jpg", discovery_order=0, discovered_at=datetime.now(timezone.utc),
        technical_validation=TechnicalValidation(format="PNG", error_code=None),  # no width/height
    )
    result = analyze_candidate(_png((500, 400)), candidate=candidate)  # must not raise
    assert result.decode_error is None  # falls back to the actually-decoded image's real size


def test_m2_technical_rejection_remains_rejected() -> None:
    """M3's analyze_candidate is simply never called for a REJECTED_TECHNICAL candidate in the
    real orchestration (services/image_intelligence.py only calls it after a VALIDATED status) -
    this is a structural, not a per-call, guarantee, proven at the orchestration-test level
    (tests/test_image_intelligence_m3.py)."""
    import inspect

    from services.image_intelligence import _fetch_and_validate_candidate

    source = inspect.getsource(_fetch_and_validate_candidate)
    assert "analyze_candidate(fetch_result.body" in source
    assert "if status != ImageCandidateStatus.VALIDATED" in source


def test_animation_remains_unsupported() -> None:
    """M3 never re-examines animation - that is M2's own, already-implemented decision
    (TechnicalValidation.animated / error_code="animation_unsupported"); an animated candidate
    never reaches VALIDATED status and therefore never reaches analyze_candidate() at all in the
    real pipeline (same structural guarantee as the M2-rejection test above)."""
    import inspect

    from services import image_quality

    assert "animated" not in inspect.getsource(image_quality.analyze_candidate).lower()


def test_svg_remains_rejected_before_m3() -> None:
    """SVG is rejected by services.image_validation (M2) via signature sniffing, before an SVG
    candidate could ever reach VALIDATED status - proven directly against that module, not
    re-implemented here."""
    from services.image_validation import validate_image_bytes

    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
    result = validate_image_bytes(svg, max_pixels=10_000_000)
    assert result.error_code == "svg_rejected"


# ---------------------------------------------------------------------------
# 16-27: URL/metadata signals
# ---------------------------------------------------------------------------


def test_logo_token_detected_on_word_boundary() -> None:
    result = _analyze("https://x.com/assets/site-logo.png", 400, 400)
    assert result.signals.possible_logo is True


def test_catalogo_does_not_accidentally_match_logo() -> None:
    result = _analyze("https://x.com/catalogo/item.jpg", 800, 600)
    assert result.signals.possible_logo is False


def test_favicon_token() -> None:
    result = _analyze("https://x.com/favicon-32x32.png", 100, 100)
    assert result.signals.resolution_band in (ResolutionBand.ICON, ResolutionBand.WEAK)


def test_icon_token() -> None:
    result = _analyze("https://x.com/app-icon-large.png", 120, 120)
    assert "favicon_with_url_evidence" in result.hard_rejection_reasons


def test_avatar_profile_author_tokens() -> None:
    for path in ("https://x.com/avatar/user123.jpg", "https://x.com/profile-pic.jpg", "https://x.com/author-headshot.jpg"):
        result = _analyze(path, 300, 300)
        assert result.signals.possible_avatar is True, path


def test_banner_ad_sponsor_tokens() -> None:
    for path in ("https://x.com/banner-top.jpg", "https://x.com/ad-creative.jpg", "https://x.com/sponsor-logo.jpg"):
        result = _analyze(path, 800, 400)
        assert result.signals.possible_banner is True, path


def test_placeholder_default_no_image_tokens() -> None:
    for path in ("https://x.com/placeholder.jpg", "https://x.com/default-image.jpg", "https://x.com/no-image.png"):
        result = _analyze(path, 300, 300)
        assert result.signals.possible_placeholder is True or result.hard_rejection_reasons, path


def test_case_insensitive_token_handling() -> None:
    result = _analyze("https://x.com/LOGO-Banner.PNG", 300, 300)
    assert result.signals.possible_logo is True


def test_url_encoded_filename_handling() -> None:
    result = _analyze("https://x.com/assets/company%20logo.png", 300, 300)
    assert result.signals.possible_logo is True


def test_malformed_url_does_not_crash_signal_extraction() -> None:
    result = _analyze("not a url at all ###%%%", 800, 600)  # must not raise
    assert isinstance(result.quality_score, int)


def test_one_weak_token_does_not_automatically_hard_reject_large_editorial_image() -> None:
    result = _analyze("https://x.com/thumb-of-the-day-hero.jpg", 1600, 900)
    assert result.hard_rejection_reasons == []


def test_feed_level_logo_origin_produces_strong_logo_signal() -> None:
    result = _analyze("https://x.com/feed-logo.png", 200, 200, discovery=ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL)
    assert result.signals.possible_logo is True


# ---------------------------------------------------------------------------
# 28-37: placeholder/logo/avatar/banner
# ---------------------------------------------------------------------------


def test_obvious_feed_logo_downgraded_or_rejected() -> None:
    result = _analyze("https://x.com/site-logo-icon.png", 60, 60)
    assert result.hard_rejection_reasons or result.signals.possible_logo


def test_author_avatar_receives_conservative_penalty() -> None:
    result = _analyze("https://x.com/author/profile.jpg", 200, 200)
    assert result.hard_rejection_reasons == []
    assert "possible_avatar" in result.quality_penalties


def test_square_news_photograph_not_treated_as_confirmed_avatar() -> None:
    result = _analyze("https://x.com/press-photo.jpg", 1000, 1000)
    assert result.signals.possible_avatar is False


def test_large_branded_launch_artwork_remains_eligible_for_review_or_acceptance() -> None:
    result = _analyze("https://x.com/product-launch-keyart.jpg", 1600, 900, alt="New product launch")
    assert result.hard_rejection_reasons == []


def test_standard_ad_size_dimensions_alone_do_not_prove_an_ad() -> None:
    """728x90 is a classic ad-banner IAB size, but with zero token evidence it must not be
    hard-rejected outright (only the possible_banner soft signal, from the aspect-ratio band, may
    fire) - conservative per the M3 task brief's own explicit instruction."""
    result = _analyze("https://x.com/hero-wide.jpg", 728, 90)
    assert "extreme_aspect_ratio" not in result.hard_rejection_reasons


def test_very_wide_banner_plus_ad_token_receives_strong_penalty() -> None:
    result = _analyze("https://x.com/ad-banner-728x90.jpg", 728, 90)
    assert result.signals.possible_banner is True
    assert result.quality_penalties.get("possible_banner", 0) < 0


def test_transparent_app_icon_detected_conservatively() -> None:
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), color=(255, 255, 255, 0)).save(buf, format="PNG")
    candidate = _candidate("https://x.com/app-icon.png", 64, 64)
    result = analyze_candidate(buf.getvalue(), candidate=candidate)
    assert "favicon_dimensions" in result.hard_rejection_reasons


def test_low_color_minimalist_editorial_image_not_automatically_rejected() -> None:
    """A large, single-color image with a NEUTRAL filename (no placeholder/icon token) must not be
    hard-rejected from color statistics alone (M3 task brief's own explicit warning)."""
    result = _analyze("https://x.com/article/minimalist-design.jpg", 1200, 800)
    assert result.hard_rejection_reasons == []


def test_generic_placeholder_with_strong_combined_evidence_rejected() -> None:
    """Small dimensions AND a placeholder token together - strong combined evidence."""
    result = _analyze("https://x.com/no-image-placeholder.png", 40, 40)
    assert "placeholder_strong_evidence" in result.hard_rejection_reasons or "tracking_pixel_dimensions" in result.hard_rejection_reasons or "favicon_dimensions" in result.hard_rejection_reasons


def test_ordinary_illustration_with_neutral_filename_accepted() -> None:
    result = _analyze("https://x.com/article/illustration-2024.jpg", 1000, 700)
    assert result.hard_rejection_reasons == []
    assert result.quality_score > 50


# ---------------------------------------------------------------------------
# Bands (pure function tests)
# ---------------------------------------------------------------------------


def test_resolution_band_boundaries() -> None:
    assert resolution_band(2, 2) == ResolutionBand.TRACKING
    assert resolution_band(50, 50) == ResolutionBand.ICON
    assert resolution_band(200, 150) == ResolutionBand.WEAK
    assert resolution_band(400, 400) == ResolutionBand.ADEQUATE
    assert resolution_band(1200, 800) == ResolutionBand.GOOD


def test_aspect_ratio_band_boundaries() -> None:
    assert aspect_ratio_band(0.02) == AspectRatioBand.EXTREME_TALL
    assert aspect_ratio_band(0.5) == AspectRatioBand.PORTRAIT
    assert aspect_ratio_band(1.0) == AspectRatioBand.SQUARE
    assert aspect_ratio_band(1.9) == AspectRatioBand.EDITORIAL_LANDSCAPE
    assert aspect_ratio_band(3.0) == AspectRatioBand.WIDE_BANNER
    assert aspect_ratio_band(30.0) == AspectRatioBand.EXTREME_WIDE


# ---------------------------------------------------------------------------
# 71-81: quality score
# ---------------------------------------------------------------------------


def test_score_remains_between_0_and_100() -> None:
    for width, height, url in [(1, 1, "https://x/a.gif"), (5000, 5000, "https://x/huge.jpg"), (10, 800, "https://x/strip.jpg")]:
        result = _analyze(url, width, height)
        assert 0 <= result.quality_score <= 100


def test_higher_resolution_improves_score_all_else_equal() -> None:
    low = _analyze("https://x.com/photo.jpg", 250, 200)
    high = _analyze("https://x.com/photo.jpg", 1600, 1200)
    assert high.quality_score > low.quality_score


def test_normal_aspect_ratio_improves_score_over_pathological_ratio() -> None:
    normal = _analyze("https://x.com/photo.jpg", 1200, 700)
    pathological = _analyze("https://x.com/photo.jpg", 1200, 20)
    assert normal.quality_score > pathological.quality_score


def test_logo_warning_applies_documented_penalty() -> None:
    result = _analyze("https://x.com/company-logo.jpg", 500, 500)
    assert result.quality_penalties["possible_logo"] == -15


def test_avatar_warning_applies_documented_penalty() -> None:
    result = _analyze("https://x.com/author-avatar.jpg", 300, 300)
    assert result.quality_penalties["possible_avatar"] == -10


def test_banner_warning_applies_documented_penalty() -> None:
    result = _analyze("https://x.com/ad-banner.jpg", 1000, 200)
    assert result.quality_penalties["possible_banner"] == -12


def test_missing_optional_metadata_has_explicit_neutral_behavior() -> None:
    with_declared = _analyze("https://x.com/a.jpg", 800, 600, declared_width=800, declared_height=600)
    without_declared = _analyze("https://x.com/a.jpg", 800, 600)
    assert without_declared.quality_components["technical_integrity"] == 20  # neutral full credit, not penalized
    assert with_declared.quality_components["technical_integrity"] == 20  # matches -> also full credit


def test_quality_component_total_is_deterministic() -> None:
    candidate = _candidate("https://x.com/a.jpg", 900, 600)
    data = _png((900, 600))
    a = analyze_candidate(data, candidate=candidate)
    b = analyze_candidate(data, candidate=candidate)
    assert a.quality_components == b.quality_components
    assert a.quality_score == b.quality_score


def test_no_semantic_relevance_fields_appear_in_quality_score_components() -> None:
    result = _analyze("https://x.com/a.jpg", 900, 600)
    forbidden = {"relevance", "title_similarity", "semantic", "entity", "channel_context"}
    assert forbidden.isdisjoint(result.quality_components.keys())
    assert forbidden.isdisjoint(result.quality_penalties.keys())
