"""Tests for services.image_relevance (Phase 16 M4, docs/phase16_m4_relevance_ranking_report.md
§19). Pure unit tests - no networking, no database, only Pillow-free synthetic ImageCandidate
objects built directly against the Pydantic contract.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database.models.news_source import SourceType
from schemas.image_candidate import (
    AspectRatioBand,
    DeduplicationInfo,
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    QualitySignals,
    QualityStatus,
    QualityValidation,
    RelevanceStatus,
    ResolutionBand,
    SourceRelationship,
    TechnicalValidation,
    TelegramReference,
)
from services.image_relevance import (
    PROVENANCE_TABLE,
    _candidate_text_tokens,
    _weighted_token_set,
    build_event_context,
    classify_relationship,
    evaluate_eligibility,
    rank_candidates,
    score_candidate,
    textual_overlap_score,
    token_weight,
    tokenize,
)


def _candidate(
    discovery=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE,
    *,
    remote_url: str | None = "https://example.com/img/hero.jpg",
    source_url: str | None = "https://example.com/article/x",
    alt_text: str | None = None,
    caption: str | None = None,
    order: int = 0,
    quality_score: int = 80,
    quality_status: QualityStatus = QualityStatus.ACCEPTED,
    is_representative: bool = True,
    duplicate_of: str | None = None,
    hamming_distance: int | None = None,
    candidate_status: ImageCandidateStatus = ImageCandidateStatus.VALIDATED,
    telegram: TelegramReference | None = None,
    declared_width: int | None = None,
    declared_height: int | None = None,
    width: int = 1200,
    height: int = 630,
    candidate_id: str | None = None,
) -> ImageCandidate:
    technical = None
    quality = None
    if candidate_status == ImageCandidateStatus.VALIDATED:
        technical = TechnicalValidation(
            width=width, height=height, format="JPEG", error_code=None,
            sha256=f"hash-{order}", pixel_count=width * height, byte_size=100_000,
        )
        quality = QualityValidation(
            status=quality_status, quality_score=quality_score,
            signals=QualitySignals(resolution_band=ResolutionBand.GOOD, aspect_ratio_band=AspectRatioBand.EDITORIAL_LANDSCAPE),
            deduplication=DeduplicationInfo(is_representative=is_representative, duplicate_of=duplicate_of, hamming_distance=hamming_distance),
        )
    return ImageCandidate(
        candidate_id=candidate_id or f"cand-{uuid4().hex[:8]}", event_id=uuid4(), source_type=SourceType.RSS,
        discovery_method=discovery, status=candidate_status, remote_url=remote_url, source_url=source_url,
        telegram=telegram, alt_text=alt_text, caption=caption, discovery_order=order,
        discovered_at=datetime.now(timezone.utc), technical_validation=technical, quality_validation=quality,
        declared_width=declared_width, declared_height=declared_height,
    )


_CTX = build_event_context(
    event_title="OpenAI announces GPT-5",
    event_content="OpenAI today announced GPT-5, a major new model release for developers.",
    source_name="TechSite",
    event_url="https://techsite.com/article/gpt-5",
)


# ---------------------------------------------------------------------------
# 1-12: provenance
# ---------------------------------------------------------------------------


def test_1_native_telegram_photo_receives_strong_provenance():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.TELEGRAM_PHOTO] == 100


def test_2_telegram_document_handled_per_policy():
    assert 0 < PROVENANCE_TABLE[ImageDiscoveryMethod.TELEGRAM_DOCUMENT] < PROVENANCE_TABLE[ImageDiscoveryMethod.TELEGRAM_PHOTO]


def test_3_rss_media_content_receives_article_level_provenance():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_MEDIA_CONTENT] >= 80


def test_4_rss_enclosure_handled_per_policy():
    assert 0 < PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_ENCLOSURE] < PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_MEDIA_CONTENT]


def test_5_rss_thumbnail_lower_than_full_article_media():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL] < PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_MEDIA_CONTENT]


def test_6_rss_inline_image_handled_conservatively():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_INLINE_IMAGE] < PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_ENCLOSURE]


def test_7_open_graph_image_receives_source_page_provenance():
    assert 50 < PROVENANCE_TABLE[ImageDiscoveryMethod.OPEN_GRAPH_IMAGE] < PROVENANCE_TABLE[ImageDiscoveryMethod.RSS_MEDIA_CONTENT]


def test_8_jsonld_article_image_handled_correctly():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE] < PROVENANCE_TABLE[ImageDiscoveryMethod.OPEN_GRAPH_IMAGE]


def test_9_twitter_image_handled_correctly():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.TWITTER_IMAGE] < PROVENANCE_TABLE[ImageDiscoveryMethod.OPEN_GRAPH_IMAGE]


def test_10_feed_level_unknown_not_ranked_as_strong_article_media():
    assert PROVENANCE_TABLE[ImageDiscoveryMethod.SOURCE_NATIVE_UNKNOWN] < PROVENANCE_TABLE[ImageDiscoveryMethod.IMAGE_SRC_LINK]


def test_11_unknown_discovery_method_handled_safely():
    candidate = _candidate(ImageDiscoveryMethod.SOURCE_NATIVE_UNKNOWN, source_url=None)
    result = score_candidate(candidate, _CTX)
    assert 0 <= result.relevance_score <= 100


def test_12_provenance_output_is_deterministic():
    candidate = _candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, telegram=TelegramReference(message_id=1, media_kind="photo"))
    a = score_candidate(candidate, _CTX)
    b = score_candidate(candidate, _CTX)
    assert a.components["provenance"] == b.components["provenance"]


# ---------------------------------------------------------------------------
# 13-21: source relationship
# ---------------------------------------------------------------------------


def test_13_same_telegram_message_relationship():
    candidate = _candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, telegram=TelegramReference(message_id=5, media_kind="photo"), source_url=None, remote_url=None)
    assert classify_relationship(candidate, "https://t.me/channel/5") == SourceRelationship.NATIVE_SAME_ITEM


def test_14_same_article_url_relationship():
    candidate = _candidate(source_url="https://techsite.com/article/gpt-5", remote_url="https://techsite.com/article/gpt-5.jpg")
    assert classify_relationship(candidate, "https://techsite.com/article/gpt-5") == SourceRelationship.SAME_ARTICLE


def test_15_same_hostname_relationship():
    candidate = _candidate(source_url="https://techsite.com/a", remote_url="https://techsite.com/img/hero.jpg")
    assert classify_relationship(candidate, "https://techsite.com/a") == SourceRelationship.SAME_ARTICLE


def test_16_related_cdn_hostname_handled_conservatively():
    candidate = _candidate(source_url="https://techsite.com/a", remote_url="https://cdn.imgexample.net/hero.jpg")
    assert classify_relationship(candidate, "https://techsite.com/a") == SourceRelationship.SOURCE_CDN_OR_RELATED


def test_17_third_party_unknown_hostname_does_not_crash_ranking():
    candidate = _candidate(source_url=None, remote_url="https://random-cdn.example/x.jpg")
    ranked = rank_candidates([candidate], event_title="t", event_content="c", event_url=None, source_name=None, top_candidates=5)
    assert ranked[0].relevance_validation is not None
    assert ranked[0].relevance_validation.source_relationship == SourceRelationship.THIRD_PARTY_UNKNOWN


def test_18_conflicting_source_relationship_receives_penalty():
    candidate = _candidate(source_url="https://other-domain.example/article", remote_url="https://other-domain.example/x.jpg")
    result = score_candidate(candidate, _CTX)
    assert result.source_relationship == SourceRelationship.UNRELATED_OR_CONFLICTING
    assert result.penalties.get("conflicting_relationship") is not None
    assert result.penalties["conflicting_relationship"] < 0


def test_19_missing_hostname_receives_explicit_unknown_state():
    candidate = _candidate(source_url="https://techsite.com/a", remote_url=None)
    assert classify_relationship(candidate, "https://techsite.com/a") == SourceRelationship.SAME_ARTICLE


def test_20_redirected_final_article_url_remains_associated():
    # Article fetch may redirect to a different path on the same registrable domain - still
    # correctly associated, not conflicting.
    candidate = _candidate(source_url="https://www.techsite.com/redirected/path", remote_url="https://www.techsite.com/img/hero.jpg")
    assert classify_relationship(candidate, "https://www.techsite.com/article/gpt-5") == SourceRelationship.SAME_ARTICLE


def test_21_no_internet_wide_cdn_assumptions():
    # An entirely fictitious CDN hostname is still classified via the generic domain-comparison
    # rule, not a hardcoded lookup table.
    candidate = _candidate(source_url="https://techsite.com/a", remote_url="https://assets.some-fictitious-cdn-9182.net/x.jpg")
    assert classify_relationship(candidate, "https://techsite.com/a") == SourceRelationship.SOURCE_CDN_OR_RELATED


# ---------------------------------------------------------------------------
# 22-35: text normalization
# ---------------------------------------------------------------------------


def test_22_unicode_normalization():
    assert tokenize("café") == tokenize("café")


def test_23_case_folding():
    assert tokenize("GPT-5 Launch") == tokenize("gpt-5 launch")


def test_24_html_entities():
    assert "at&t" not in tokenize("AT&amp;T announces")
    assert "amp" not in tokenize("Salt &amp; Pepper")


def test_25_url_decoding():
    assert tokenize("gpt%205%20launch") == tokenize("gpt 5 launch")


def test_26_file_extension_removal():
    from services.image_relevance import _filename_tokens

    assert "jpg" not in _filename_tokens("https://example.com/hero-photo.jpg")


def test_27_hyphenated_product_names():
    assert tokenize("GPT-5") == ["gpt", "5"]


def test_28_cyrillic_terms():
    tokens = tokenize("Новая модель ИИ")
    assert "новая" in tokens and "модель" in tokens


def test_29_latin_terms():
    tokens = tokenize("New AI model")
    assert "new" in tokens and "model" in tokens


def test_30_version_numbers():
    assert token_weight("5", original_text="gpt 5") == 1.5


def test_31_acronyms():
    assert token_weight("nasa", original_text="NASA announces mission") == 1.3


def test_32_generic_image_tokens_removed():
    assert token_weight("banner", original_text="banner") == 0.0
    assert token_weight("thumbnail", original_text="thumbnail") == 0.0


def test_33_meaningful_product_tokens_preserved():
    assert token_weight("chatgpt", original_text="chatgpt") > 0.0


def test_34_malformed_filename_does_not_crash():
    from services.image_relevance import _filename_tokens

    assert _filename_tokens("https://example.com/%ZZ%%bad") == [] or isinstance(_filename_tokens("https://example.com/%ZZ%%bad"), list)


def test_35_empty_text_produces_valid_empty_token_set():
    assert tokenize("") == []
    assert tokenize(None) == []


# ---------------------------------------------------------------------------
# 36-46: textual overlap
# ---------------------------------------------------------------------------


def test_36_strong_alt_text_title_overlap():
    candidate = _candidate(alt_text="OpenAI GPT-5 launch photo")
    tokens = _candidate_text_tokens(candidate)
    score, has_evidence = textual_overlap_score(tokens, _CTX)
    assert has_evidence and score > 30


def test_37_strong_filename_title_overlap():
    candidate = _candidate(remote_url="https://example.com/gpt-5-launch.jpg")
    tokens = _candidate_text_tokens(candidate)
    score, has_evidence = textual_overlap_score(tokens, _CTX)
    assert has_evidence and score > 0


def test_38_multi_token_phrase_overlap():
    single = _candidate_text_tokens(_candidate(alt_text="GPT"))
    multi = _candidate_text_tokens(_candidate(alt_text="OpenAI GPT-5 announcement"))
    single_score, _ = textual_overlap_score(single, _CTX)
    multi_score, _ = textual_overlap_score(multi, _CTX)
    assert multi_score >= single_score


def test_39_version_model_number_overlap():
    tokens = _candidate_text_tokens(_candidate(alt_text="GPT-5"))
    score, has_evidence = textual_overlap_score(tokens, _CTX)
    assert has_evidence and score > 0


def test_40_generic_only_overlap_produces_little_score():
    tokens = _candidate_text_tokens(_candidate(alt_text="photo image banner"))
    score, has_evidence = textual_overlap_score(tokens, _CTX)
    assert score == 0 and not has_evidence


def test_41_no_candidate_text_uses_explicit_missing_data_behavior():
    tokens = _candidate_text_tokens(_candidate(alt_text=None, caption=None, remote_url=None))
    score, has_evidence = textual_overlap_score(tokens, _CTX)
    assert score == 0 and not has_evidence


def test_42_rich_unrelated_metadata_does_not_outrank_relevant_native():
    unrelated_rich = _candidate(
        ImageDiscoveryMethod.IMAGE_SRC_LINK, alt_text="a wonderful sunny day at the beach with friends",
        caption="vacation photos from last summer", source_url="https://techsite.com/article/gpt-5",
        remote_url="https://techsite.com/beach.jpg", quality_score=95,
    )
    native_sparse = _candidate(
        ImageDiscoveryMethod.TELEGRAM_PHOTO, telegram=TelegramReference(message_id=1, media_kind="photo"),
        source_url=None, remote_url=None, alt_text=None, quality_score=70,
    )
    ranked = rank_candidates(
        [unrelated_rich, native_sparse], event_title="OpenAI announces GPT-5",
        event_content="OpenAI today announced GPT-5.", event_url="https://techsite.com/article/gpt-5",
        source_name="TechSite", top_candidates=5,
    )
    by_id = {c.candidate_id: c for c in ranked}
    assert by_id[native_sparse.candidate_id].relevance_validation.relevance_score >= by_id[unrelated_rich.candidate_id].relevance_validation.relevance_score


def test_43_title_overlap_outweighs_generic_body_overlap():
    title_match = _candidate_text_tokens(_candidate(alt_text="GPT-5"))
    body_only_ctx = build_event_context(
        event_title="Unrelated headline text", event_content="OpenAI today announced GPT-5 in a blog post.",
        source_name=None, event_url=None,
    )
    title_ctx_score, _ = textual_overlap_score(title_match, _CTX)
    body_ctx_score, _ = textual_overlap_score(title_match, body_only_ctx)
    assert title_ctx_score >= body_ctx_score


def test_44_repeated_tokens_do_not_inflate_score_indefinitely():
    once = _candidate_text_tokens(_candidate(alt_text="GPT-5"))
    repeated = _candidate_text_tokens(_candidate(alt_text="GPT-5 GPT-5 GPT-5 GPT-5 GPT-5"))
    once_score, _ = textual_overlap_score(once, _CTX)
    repeated_score, _ = textual_overlap_score(repeated, _CTX)
    assert once_score == repeated_score


def test_45_cyrillic_latin_unrelated_terms_remain_unrelated():
    ctx = build_event_context(event_title="Новая модель ИИ от компании", event_content="", source_name=None, event_url=None)
    tokens = _candidate_text_tokens(_candidate(alt_text="Completely unrelated english words here"))
    score, has_evidence = textual_overlap_score(tokens, ctx)
    assert score == 0 and not has_evidence


def test_46_no_translation_or_semantic_guessing():
    ctx = build_event_context(event_title="искусственный интеллект", event_content="", source_name=None, event_url=None)
    tokens = _candidate_text_tokens(_candidate(alt_text="artificial intelligence"))
    score, has_evidence = textual_overlap_score(tokens, ctx)
    assert score == 0 and not has_evidence


# ---------------------------------------------------------------------------
# 47-55: quality and penalties
# ---------------------------------------------------------------------------


def test_47_higher_m3_quality_improves_ranking_where_relevance_equal():
    low_q = _candidate(candidate_id="low", quality_score=40, alt_text="GPT-5")
    high_q = _candidate(candidate_id="high", quality_score=95, alt_text="GPT-5")
    low_result = score_candidate(low_q, _CTX)
    high_result = score_candidate(high_q, _CTX)
    assert high_result.relevance_score >= low_result.relevance_score


def test_48_high_quality_unrelated_does_not_beat_strongly_related_native():
    unrelated = _candidate(
        ImageDiscoveryMethod.IMAGE_SRC_LINK, quality_score=100, alt_text=None,
        source_url="https://other.example/x", remote_url="https://other.example/x.jpg",
    )
    native = _candidate(
        ImageDiscoveryMethod.TELEGRAM_PHOTO, telegram=TelegramReference(message_id=1, media_kind="photo"),
        quality_score=60, alt_text="GPT-5 launch", source_url=None, remote_url=None,
    )
    unrelated_result = score_candidate(unrelated, _CTX)
    native_result = score_candidate(native, _CTX)
    assert native_result.relevance_score > unrelated_result.relevance_score


def test_49_possible_logo_does_not_automatically_reject():
    candidate = _candidate(quality_status=QualityStatus.ACCEPTED, alt_text="company logo GPT-5")
    eligible, _ = evaluate_eligibility(candidate)
    assert eligible is True


def test_50_review_candidate_remains_rankable():
    candidate = _candidate(quality_status=QualityStatus.REVIEW, alt_text="GPT-5 launch")
    result = score_candidate(candidate, _CTX)
    assert result.status == RelevanceStatus.RANKED
    assert result.penalties.get("review_status") == -4


def test_51_m3_hard_rejection_remains_ineligible():
    candidate = _candidate(quality_status=QualityStatus.REJECTED_QUALITY)
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is False and "rejected_quality" in reason


def test_52_non_representative_exact_duplicate_remains_ineligible():
    candidate = _candidate(quality_status=QualityStatus.DUPLICATE_EXACT, is_representative=False, duplicate_of="other")
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is False and "duplicate_exact" in reason


def test_53_non_representative_near_duplicate_remains_ineligible():
    candidate = _candidate(quality_status=QualityStatus.DUPLICATE_NEAR, is_representative=False, duplicate_of="other", hamming_distance=3)
    eligible, reason = evaluate_eligibility(candidate)
    assert eligible is False and "duplicate_near" in reason


def test_54_cluster_representative_remains_eligible():
    candidate = _candidate(quality_status=QualityStatus.ACCEPTED, is_representative=True)
    eligible, _ = evaluate_eligibility(candidate)
    assert eligible is True


def test_55_m3_penalties_not_double_counted():
    candidate = _candidate(alt_text="banner logo placeholder", quality_score=50)
    result = score_candidate(candidate, _CTX)
    double_counted_keys = {"possible_logo", "possible_avatar", "possible_banner", "possible_placeholder", "possible_icon", "possible_thumbnail"}
    assert not (set(result.penalties) & double_counted_keys)


# ---------------------------------------------------------------------------
# 56-62: missing data
# ---------------------------------------------------------------------------


def test_56_missing_alt_text_is_not_rewarded():
    with_alt = score_candidate(_candidate(alt_text="something generic here"), _CTX)
    without_alt = score_candidate(_candidate(alt_text=None), _CTX)
    assert without_alt.components["metadata_confidence"] <= with_alt.components["metadata_confidence"]


def test_57_missing_filename_is_not_rewarded():
    with_name = score_candidate(_candidate(remote_url="https://example.com/gpt-5.jpg"), _CTX)
    without_name = score_candidate(_candidate(remote_url=None), _CTX)
    assert without_name.components["metadata_confidence"] <= with_name.components["metadata_confidence"]


def test_58_native_candidate_with_missing_metadata_remains_competitive():
    native_no_meta = _candidate(
        ImageDiscoveryMethod.TELEGRAM_PHOTO, telegram=TelegramReference(message_id=1, media_kind="photo"),
        alt_text=None, source_url=None, remote_url=None, quality_score=80,
    )
    result = score_candidate(native_no_meta, _CTX)
    assert result.relevance_score >= 50


def test_59_unknown_relationship_differs_from_conflicting():
    unknown = _candidate(source_url=None, remote_url="https://example.com/x.jpg")
    conflicting = _candidate(source_url="https://other.example/a", remote_url="https://other.example/x.jpg")
    unknown_result = score_candidate(unknown, _CTX)
    conflicting_result = score_candidate(conflicting, _CTX)
    assert unknown_result.source_relationship != conflicting_result.source_relationship
    assert unknown_result.relevance_score != conflicting_result.relevance_score


def test_60_metadata_confidence_component_is_zero_by_design_but_coverage_still_varies():
    """Phase 23.1N.1: METADATA_CONFIDENCE_MAX was reduced to 0 (its entire budget moved to
    QUALITY_MAX, docs/phase23_1n1_image_ranking_quality_report.md) - the `metadata_confidence`
    relevance-score COMPONENT is now always 0 by design, for every candidate, regardless of how
    rich or poor its metadata is (0 * anything = 0) - this is the direct, intended consequence of
    the rebalancing, not a bug. The underlying signal is not deleted, only removed from the final
    score: `coverage` (test_61) still reports the real alt/caption/filename/dims-match flags
    accurately either way - only their contribution to `relevance_score` itself was zeroed."""
    rich = score_candidate(_candidate(alt_text="GPT-5 launch photo", caption="official image", declared_width=1200, declared_height=630), _CTX)
    poor = score_candidate(_candidate(alt_text=None, caption=None, remote_url=None), _CTX)
    assert rich.components["metadata_confidence"] == 0
    assert poor.components["metadata_confidence"] == 0
    assert rich.coverage["candidate_alt_available"] is True
    assert poor.coverage["candidate_alt_available"] is False


def test_61_coverage_flags_are_accurate():
    candidate = _candidate(alt_text="GPT-5 launch photo", caption=None, remote_url="https://example.com/gpt-5.jpg")
    result = score_candidate(candidate, _CTX)
    assert result.coverage["candidate_alt_available"] is True
    assert result.coverage["candidate_title_available"] is False
    assert result.coverage["filename_available"] is True


def test_62_rich_generic_metadata_does_not_create_false_high_relevance():
    candidate = _candidate(alt_text="image photo picture thumbnail preview banner cover", caption="default media upload")
    result = score_candidate(candidate, _CTX)
    assert result.components["textual_overlap"] == 0


# ---------------------------------------------------------------------------
# 63-76: score and ranking
# ---------------------------------------------------------------------------


def test_63_relevance_score_remains_0_100():
    for kwargs in ({"alt_text": "GPT-5 launch", "quality_score": 100}, {"alt_text": None, "quality_score": 0}):
        result = score_candidate(_candidate(**kwargs), _CTX)
        assert 0 <= result.relevance_score <= 100


def test_64_component_totals_are_deterministic():
    candidate = _candidate(alt_text="GPT-5 launch")
    a = score_candidate(candidate, _CTX)
    b = score_candidate(candidate, _CTX)
    assert a.components == b.components


def test_65_ranking_is_stable_across_repeated_runs():
    candidates = [_candidate(candidate_id=f"c{i}", order=i, alt_text="GPT-5" if i % 2 == 0 else None) for i in range(4)]
    run1 = rank_candidates(candidates, event_title="GPT-5", event_content="c", event_url=None, source_name=None, top_candidates=5)
    run2 = rank_candidates(candidates, event_title="GPT-5", event_content="c", event_url=None, source_name=None, top_candidates=5)
    ranks1 = {c.candidate_id: c.relevance_validation.rank for c in run1}
    ranks2 = {c.candidate_id: c.relevance_validation.rank for c in run2}
    assert ranks1 == ranks2


def test_66_input_ordering_does_not_change_final_ordering():
    candidates = [_candidate(candidate_id=f"c{i}", order=i, alt_text="GPT-5" if i % 2 == 0 else None) for i in range(4)]
    forward = rank_candidates(candidates, event_title="GPT-5", event_content="c", event_url=None, source_name=None, top_candidates=5)
    backward = rank_candidates(list(reversed(candidates)), event_title="GPT-5", event_content="c", event_url=None, source_name=None, top_candidates=5)
    forward_ranks = {c.candidate_id: c.relevance_validation.rank for c in forward}
    backward_ranks = {c.candidate_id: c.relevance_validation.rank for c in backward}
    assert forward_ranks == backward_ranks


def test_67_stable_candidate_id_resolves_final_ties():
    identical_a = _candidate(candidate_id="aaa", order=0, alt_text=None)
    identical_b = _candidate(candidate_id="bbb", order=0, alt_text=None)
    ranked = rank_candidates([identical_b, identical_a], event_title="x", event_content="", event_url=None, source_name=None, top_candidates=5)
    by_id = {c.candidate_id: c.relevance_validation.rank for c in ranked}
    assert by_id["aaa"] < by_id["bbb"]


def test_68_highest_relevance_score_ranks_first():
    strong = _candidate(candidate_id="strong", alt_text="GPT-5 launch photo announcement")
    weak = _candidate(candidate_id="weak", alt_text=None, remote_url=None, quality_score=30)
    ranked = rank_candidates([weak, strong], event_title="OpenAI announces GPT-5", event_content="", event_url=None, source_name=None, top_candidates=5)
    by_id = {c.candidate_id: c for c in ranked}
    assert by_id["strong"].relevance_validation.rank == 1


def test_69_duplicate_cluster_yields_only_one_top_candidate():
    representative = _candidate(candidate_id="rep", quality_status=QualityStatus.ACCEPTED, is_representative=True)
    duplicate = _candidate(candidate_id="dup", quality_status=QualityStatus.DUPLICATE_EXACT, is_representative=False, duplicate_of="rep")
    ranked = rank_candidates([representative, duplicate], event_title="x", event_content="", event_url=None, source_name=None, top_candidates=5)
    top = [c for c in ranked if c.relevance_validation.eligible_for_editorial]
    assert len(top) == 1 and top[0].candidate_id == "rep"


def test_70_review_candidates_remain_flagged():
    candidate = _candidate(quality_status=QualityStatus.REVIEW, alt_text="GPT-5")
    ranked = rank_candidates([candidate], event_title="GPT-5", event_content="", event_url=None, source_name=None, top_candidates=5)
    assert ranked[0].quality_validation.status == QualityStatus.REVIEW
    assert ranked[0].relevance_validation.status == RelevanceStatus.RANKED


def test_71_fewer_than_five_candidates_returns_fewer_than_five():
    candidates = [_candidate(candidate_id=f"c{i}", order=i) for i in range(2)]
    ranked = rank_candidates(candidates, event_title="x", event_content="", event_url=None, source_name=None, top_candidates=5)
    top = [c for c in ranked if c.relevance_validation.eligible_for_editorial]
    assert len(top) == 2


def test_72_zero_candidates_returns_empty_result():
    ranked = rank_candidates([], event_title="x", event_content="", event_url=None, source_name=None, top_candidates=5)
    assert ranked == []


def test_73_configured_top_limit_is_respected():
    candidates = [_candidate(candidate_id=f"c{i}", order=i, alt_text="GPT-5") for i in range(8)]
    ranked = rank_candidates(candidates, event_title="GPT-5", event_content="", event_url=None, source_name=None, top_candidates=2)
    top = [c for c in ranked if c.relevance_validation.eligible_for_editorial]
    assert len(top) == 2


def test_74_unsafe_excessive_top_limit_rejected_by_config_validation():
    from pydantic import ValidationError

    from core.config import Settings

    with pytest.raises(ValidationError):
        Settings(image_intelligence_top_candidates=999)


def test_75_candidate_reasons_are_deterministic():
    candidate = _candidate(alt_text="GPT-5 launch")
    a = score_candidate(candidate, _CTX)
    b = score_candidate(candidate, _CTX)
    assert a.reason == b.reason


def test_76_no_semantic_image_content_claims_in_reasons():
    banned = {"shows", "depicts", "pictured", "displays a", "contains a photo of"}
    for method in ImageDiscoveryMethod:
        candidate = _candidate(method, alt_text="GPT-5 launch", telegram=TelegramReference(message_id=1, media_kind="photo") if "telegram" in method.value else None)
        result = score_candidate(candidate, _CTX)
        lowered = (result.reason or "").lower()
        assert not any(term in lowered for term in banned)


# ---------------------------------------------------------------------------
# Backward-compatibility (M1-M3 deserialization still valid without relevance_validation).
# ---------------------------------------------------------------------------


def test_m3_shaped_candidate_deserializes_without_relevance_validation():
    candidate = _candidate()
    payload = candidate.model_dump(mode="json")
    payload.pop("relevance_validation", None)
    payload["schema_version"] = "m3"
    rebuilt = ImageCandidate.model_validate(payload)
    assert rebuilt.relevance_validation is None


def test_weighted_token_set_handles_none():
    assert _weighted_token_set(None) == {}


# ---------------------------------------------------------------------------
# Phase 23.1N.1 (docs/phase23_1n1_image_ranking_quality_report.md) - the real Anthropic-IPO
# Techmeme-vs-WSJ case (Phase 23.1N's own disclosed, unfixed finding) and the required Part L
# test cases. `_real_techmeme_thumbnail`/`_real_wsj_image` reproduce the ACTUAL persisted
# dimensions/quality_score/discovery_method/source_relationship from the real live canary run
# (scripts/_phase23_1n1_anthropic_full_candidates.txt) - not synthetic approximations.
# ---------------------------------------------------------------------------


def _real_techmeme_thumbnail() -> ImageCandidate:
    """The real winner under the OLD weights: 142x72, quality_score=65 (weak resolution band),
    native_same_item (RSS inline, same event item)."""
    return _candidate(
        ImageDiscoveryMethod.RSS_INLINE_IMAGE, candidate_id="techmeme-thumb",
        remote_url="http://www.techmeme.com/260811/i1.jpg",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
        width=142, height=72, quality_score=65, quality_status=QualityStatus.REVIEW,
        alt_text=None, caption=None,
    )


def _real_wsj_image() -> ImageCandidate:
    """The real loser under the OLD weights despite vastly higher quality: 1280x640,
    quality_score=98 (good resolution band), source_cdn_or_related (hosted on a related asset
    domain, discovered via Open Graph on the same article page)."""
    return _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="wsj-hero",
        remote_url="https://images.wsj.net/im-50714106/social",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
        width=1280, height=640, quality_score=98, quality_status=QualityStatus.REVIEW,
        alt_text=None, caption=None,
    )


_ANTHROPIC_CTX = build_event_context(
    event_title="Anthropic is courting investors for what could be the biggest IPO ever",
    event_content="Sources: Anthropic is courting investors for what could be the biggest IPO ever",
    source_name="Techmeme",
    event_url="https://www.techmeme.com/260811/p1#a260811p1",
)


def test_case_1_real_techmeme_vs_wsj_case_the_higher_quality_direct_image_now_wins():
    """CASE 1 (Part L): tiny aggregator thumbnail vs good direct-source image -> the good
    direct-source image wins. Reproduces the exact real Phase 23.1N finding with real numbers -
    under the OLD QUALITY_MAX=15/METADATA_CONFIDENCE_MAX=10 weights this candidate pair scored
    Techmeme=50, WSJ=47 (Techmeme winning); after the QUALITY_MAX=25/METADATA_CONFIDENCE_MAX=0
    rebalancing, WSJ must win."""
    techmeme = score_candidate(_real_techmeme_thumbnail(), _ANTHROPIC_CTX)
    wsj = score_candidate(_real_wsj_image(), _ANTHROPIC_CTX)
    assert wsj.relevance_score > techmeme.relevance_score, (
        f"WSJ ({wsj.relevance_score}) must outrank the tiny Techmeme thumbnail "
        f"({techmeme.relevance_score}) now that quality carries more weight"
    )


def test_case_2_small_relevant_original_beats_huge_generic_image():
    """CASE 2 (Part L): a small but clearly story-specific original image must still beat a huge
    but generic/unrelated image - quality must never override relevance (Part F guard)."""
    small_relevant = _candidate(
        ImageDiscoveryMethod.RSS_MEDIA_CONTENT, candidate_id="small-relevant",
        width=400, height=300, quality_score=55, alt_text="Anthropic IPO investors",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
    )
    huge_generic = _candidate(
        ImageDiscoveryMethod.IMAGE_SRC_LINK, candidate_id="huge-generic",
        width=4000, height=3000, quality_score=100, alt_text=None,
        source_url="https://unrelated.example/other-page",
        remote_url="https://unrelated.example/generic-server-room.jpg",
    )
    small_result = score_candidate(small_relevant, _ANTHROPIC_CTX)
    huge_result = score_candidate(huge_generic, _ANTHROPIC_CTX)
    assert small_result.relevance_score > huge_result.relevance_score


def test_case_3_equal_relevance_different_quality_better_quality_wins():
    """CASE 3 (Part L): two equally relevant originals, different quality -> the better
    Telegram-display-quality image wins (already partly covered by the pre-existing test_47;
    this uses the real-scale Anthropic quality_score values specifically)."""
    low_quality = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="og-low", width=600, height=300,
        quality_score=65, alt_text="Anthropic IPO",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
    )
    high_quality = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="og-high", width=1280, height=640,
        quality_score=98, alt_text="Anthropic IPO",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
    )
    low_result = score_candidate(low_quality, _ANTHROPIC_CTX)
    high_result = score_candidate(high_quality, _ANTHROPIC_CTX)
    assert high_result.relevance_score > low_result.relevance_score


def test_case_4_gigantic_image_gains_no_runaway_advantage_over_already_good_image():
    """CASE 4 (Part L): a gigantic image must not gain unbounded advantage over an
    already-"comfortably suitable for Telegram" image. Reuses services.image_quality's own
    already-saturating `resolution_band` (GOOD caps at shortest-side>=600, confirmed in
    services/image_quality.py) - both a 1280x640 and an 8000x8000 image land in the GOOD band and
    must receive the identical resolution component, so quality_score itself (which this
    relevance layer reuses unmodified) already provides the diminishing-returns behavior Part E
    asks for - this test proves that saturation survives into the final relevance score too."""
    already_good = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="already-good", width=1280, height=640,
        quality_score=98, alt_text="Anthropic IPO",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
    )
    gigantic = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="gigantic", width=8000, height=4000,
        quality_score=98, alt_text="Anthropic IPO",  # same M3 quality_score - both are GOOD band
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
    )
    good_result = score_candidate(already_good, _ANTHROPIC_CTX)
    gigantic_result = score_candidate(gigantic, _ANTHROPIC_CTX)
    assert good_result.relevance_score == gigantic_result.relevance_score


def test_case_8_article_lead_image_beats_generic_company_logo():
    """CASE 8 (Part L): article lead vs generic company logo -> the article lead wins when both
    are otherwise valid."""
    article_lead = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE, candidate_id="lead", width=1200, height=630,
        quality_score=90, alt_text="Anthropic office announcement",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
    )
    company_logo = _candidate(
        ImageDiscoveryMethod.IMAGE_SRC_LINK, candidate_id="logo", width=512, height=512,
        quality_score=70, alt_text="Anthropic logo",
        source_url="https://www.techmeme.com/260811/p1#a260811p1",
        remote_url="https://www.techmeme.com/logo.png",
    )
    lead_result = score_candidate(article_lead, _ANTHROPIC_CTX)
    logo_result = score_candidate(company_logo, _ANTHROPIC_CTX)
    assert lead_result.relevance_score > logo_result.relevance_score


def test_case_12_candidate_order_reversed_winner_is_identical():
    """CASE 12 (Part L): selection must not depend on discovery/input order - already
    structurally guaranteed by rank_candidates()'s own full-resort design (confirmed by the
    pre-existing test_66), re-proven here specifically for the real Techmeme/WSJ pair post-fix."""
    techmeme = _real_techmeme_thumbnail()
    wsj = _real_wsj_image()
    forward = rank_candidates(
        [techmeme, wsj], event_title="Anthropic IPO",
        event_content="", event_url=_ANTHROPIC_CTX.event_url, source_name="Techmeme", top_candidates=5,
    )
    backward = rank_candidates(
        [wsj, techmeme], event_title="Anthropic IPO", event_content="",
        event_url=_ANTHROPIC_CTX.event_url, source_name="Techmeme", top_candidates=5,
    )
    forward_winner = next(c.candidate_id for c in forward if c.relevance_validation.rank == 1)
    backward_winner = next(c.candidate_id for c in backward if c.relevance_validation.rank == 1)
    assert forward_winner == backward_winner == "wsj-hero"


# ---------------------------------------------------------------------------
# Phase 23.1N.1 continuation (post-reboot recovery, docs/
# session_recovery_after_reboot_phase23_1n1.md) - the 6 required Part L cases left unwritten when
# the session was interrupted (1/2/3/4/8/12 above were already done pre-reboot). QUALITY_MAX=25/
# METADATA_CONFIDENCE_MAX=0 are NOT touched by any test below - these only prove the rebalance
# left everything it must not touch alone.
# ---------------------------------------------------------------------------


def test_case_5_tracking_pixel_and_icon_dimensioned_candidates_remain_hard_rejected():
    """CASE 5 (Part L): tracking/icon hard rejection. A candidate M3 already hard-rejected as
    tracking-pixel/icon-dimensioned (`QualityStatus.REJECTED_QUALITY` - services/image_quality.py's
    own `tracking_pixel_dimensions`/`favicon_dimensions` hard rejection, confirmed live for
    Anthropic's own real 11x12 Techmeme favicon, docs/phase23_1n_story_angle_meme_image_report.md
    §9) must remain permanently ineligible regardless of this phase's weight rebalance -
    `evaluate_eligibility()` gates on M3's `quality.status` BEFORE any relevance/quality scoring
    ever runs, so `QUALITY_MAX`/`METADATA_CONFIDENCE_MAX` structurally cannot rescue it either way
    (already covered in general by the pre-existing test_51; re-proven here end-to-end through
    `rank_candidates()` specifically for this phase, not merely `evaluate_eligibility()` alone)."""
    tracking_or_icon = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="tracking-icon",
        width=11, height=12, quality_score=0, quality_status=QualityStatus.REJECTED_QUALITY,
    )
    eligible, reason = evaluate_eligibility(tracking_or_icon)
    assert eligible is False and "rejected_quality" in reason

    ranked = rank_candidates(
        [tracking_or_icon], event_title="x", event_content="", event_url=None,
        source_name=None, top_candidates=5,
    )
    assert ranked[0].relevance_validation.status == RelevanceStatus.INELIGIBLE
    assert ranked[0].relevance_validation.eligible_for_editorial is False


def test_case_6_mediocre_thumbnail_as_only_relevant_candidate_is_still_selected():
    """CASE 6 (Part L): mediocre thumbnail as the only candidate. Documents the ACTUAL current
    quality-floor semantics rather than inventing a new one: direct reading of
    `evaluate_eligibility()`/`rank_candidates()` shows the only eligibility gate is M3's hard-
    rejection status (tracking/icon/duplicate - Case 5/9) - there is no separate minimum
    relevance_score floor underneath that. A candidate that clears M3's hard-rejection bar remains
    eligible no matter how low its resulting relevance_score is; "no image" only occurs when zero
    candidates clear that bar at all (Case 7 below) or none are discovered (pre-existing
    test_72) - never merely "the only candidate wasn't good enough" on its own."""
    mediocre = _candidate(
        ImageDiscoveryMethod.RSS_INLINE_IMAGE, candidate_id="mediocre-thumb",
        width=200, height=150, quality_score=35, quality_status=QualityStatus.REVIEW,
        alt_text=None, caption=None, source_url=None, remote_url="https://example.com/thumb.jpg",
    )
    ranked = rank_candidates(
        [mediocre], event_title="Some story headline", event_content="", event_url=None,
        source_name=None, top_candidates=5,
    )
    assert ranked[0].relevance_validation.status == RelevanceStatus.RANKED
    assert ranked[0].relevance_validation.eligible_for_editorial is True


def test_case_7_all_candidates_hard_rejected_by_m3_yields_no_image():
    """CASE 7 (Part L): all candidates poor -> no image. When EVERY candidate is hard-rejected by
    M3 (tracking/icon dimensions or a non-representative duplicate - the only real "poor" gate that
    exists in this architecture; Case 6 above proves there is no separate soft floor beneath it),
    `rank_candidates()` marks none of them `eligible_for_editorial` - the real mechanism behind the
    "NO IMAGE > BAD IMAGE" product rule, confirmed on real live data in docs/
    phase23_1h_text_image_canary_report.md §12 (both discovered candidates for that post were
    correctly rejected and it was sent text-only)."""
    tiny_icon = _candidate(
        candidate_id="icon", width=32, height=32, quality_score=5,
        quality_status=QualityStatus.REJECTED_QUALITY,
    )
    duplicate = _candidate(
        candidate_id="dup", quality_status=QualityStatus.DUPLICATE_NEAR,
        is_representative=False, duplicate_of="icon", hamming_distance=2,
    )
    ranked = rank_candidates(
        [tiny_icon, duplicate], event_title="x", event_content="", event_url=None,
        source_name=None, top_candidates=5,
    )
    assert all(c.relevance_validation.eligible_for_editorial is False for c in ranked)
    assert all(c.relevance_validation.status == RelevanceStatus.INELIGIBLE for c in ranked)


def test_case_9_multi_candidate_ranking_still_yields_a_valid_fallback_target():
    """CASE 9 (Part L): duplicate-image guard preserved. The cross-event duplicate-image guard
    itself (`services/image_persistence.py::get_recently_attached_image_source_urls()`, Phase
    23.1N Part J) is NOT modified by this phase (confirmed: file untouched since Phase 23.1N,
    unrelated to relevance weights - it runs a separate DB query keyed on `source_url`) and is
    already covered end-to-end, including its fall-through-to-next-candidate behavior, by
    tests/test_story_angle_and_image_duplicate_guard.py (DB-dependent, unaffected by this phase).
    What THIS ranking layer alone must still guarantee for that guard's caller (`worker/
    content_cycle.py`, which walks the ranked list in order and skips a duplicate) to have
    something to fall back to: a full, correctly-ordered multi-candidate result with each
    candidate's own `source_url` intact, not just a single winner - proven here for a realistic
    mixed native+metadata candidate set under the new weights."""
    native_fallback = _candidate(
        ImageDiscoveryMethod.RSS_MEDIA_CONTENT, candidate_id="native-fallback",
        source_url=None, remote_url="https://cdn.example.com/rss-image.jpg",
        width=800, height=533, quality_score=70, alt_text="Anthropic IPO investors",
    )
    og_winner = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="og-winner",
        source_url="https://www.techmeme.com/a", remote_url="https://images.wsj.net/im-1/social",
        width=1280, height=640, quality_score=98, alt_text="Anthropic IPO",
    )
    ranked = rank_candidates(
        [native_fallback, og_winner], event_title="Anthropic IPO", event_content="",
        event_url="https://www.techmeme.com/a", source_name="Techmeme", top_candidates=5,
    )
    eligible = [c for c in ranked if c.relevance_validation.eligible_for_editorial]
    assert len(eligible) == 2
    assert sorted(c.relevance_validation.rank for c in eligible) == [1, 2]
    assert len({c.candidate_id for c in eligible}) == 2
    ids_to_source = {c.candidate_id: c.source_url for c in eligible}
    assert ids_to_source["native-fallback"] is None
    assert ids_to_source["og-winner"] == "https://www.techmeme.com/a"


_ARMENIA_EVENT_URL = "https://3dnews.ru/1146526"
_ARMENIA_TITLE = "NVIDIA graphics cards from Armenia turned out to contain relabeled Firebird chips"


def test_case_10_armenia_firebird_regression_own_domain_image_still_wins():
    """CASE 10 (Part L): Armenia/Firebird regression. Disclosed honestly, matching Phase 23.1N's
    own §11 disclosure style: no real persisted image_intelligence candidate data exists for this
    event anywhere in this repository - it was never delivered through a real live canary with
    Image Intelligence active (golden-replay only, text-based). This reconstructs a representative
    candidate using the REAL event URL (scripts/_phase23_1i_armenia_events.json, event_id
    36891f69-a5f0-47f8-a336-ddb917f9bdd1) and the exact realistic own-domain-CDN shape confirmed
    for two OTHER real 3dnews.ru candidates persisted this session (`long_march_7a`/`gym_3dnews` in
    scripts/_phase23_1n_image_forensics.json, both `open_graph_secure_image` on `cdn.3dnews.ru`)
    against a generic unrelated alternative - proving the previously-correct class of winner (the
    article's own domain image) is not displaced by the new weights, i.e. relevance still beats
    raw quality here exactly as it did before this phase."""
    own_domain_image = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE, candidate_id="3dnews-own",
        source_url=_ARMENIA_EVENT_URL,
        remote_url="https://cdn.3dnews.ru/assets/external/illustrations/2026/08/09/1146526/firebird.jpg",
        width=800, height=535, quality_score=73, alt_text=None,
    )
    unrelated_generic = _candidate(
        ImageDiscoveryMethod.IMAGE_SRC_LINK, candidate_id="generic-unrelated",
        source_url="https://other.example/unrelated-page", remote_url="https://other.example/stock-photo.jpg",
        width=1600, height=900, quality_score=95, alt_text=None,
    )
    ctx = build_event_context(
        event_title=_ARMENIA_TITLE, event_content=_ARMENIA_TITLE, source_name="3DNews",
        event_url=_ARMENIA_EVENT_URL,
    )
    own_domain_result = score_candidate(own_domain_image, ctx)
    unrelated_result = score_candidate(unrelated_generic, ctx)
    assert own_domain_result.relevance_score > unrelated_result.relevance_score


def test_case_11_phase23_1h_google_news_aggregator_and_broken_candidate_regression():
    """CASE 11 (Part L): Phase 23.1H text-only regression. Reproduces the real live case (docs/
    phase23_1h_text_image_canary_report.md §12, NEWS #2) - a 300x300 generic Google-hosted
    aggregator thumbnail (Phase 16.5's own `_is_generic_aggregator_asset` exclusion) and one
    dimensionless/technically-failed candidate, both correctly rejected on real production data;
    this must remain unchanged under the new weights - both rejections happen at the eligibility
    gate, entirely before `QUALITY_MAX`/`METADATA_CONFIDENCE_MAX` are ever applied."""
    google_aggregator_thumb = _candidate(
        ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, candidate_id="google-agg-thumb",
        source_url="https://news.google.com/rss/articles/xyz",
        remote_url="https://lh3.googleusercontent.com/some-generic-thumb.jpg",
        width=300, height=300, quality_score=60,
    )
    broken = _candidate(candidate_id="broken", candidate_status=ImageCandidateStatus.FETCH_FAILED)
    ranked = rank_candidates(
        [google_aggregator_thumb, broken], event_title="x", event_content="",
        event_url="https://news.google.com/rss/articles/xyz", source_name=None, top_candidates=5,
    )
    assert all(c.relevance_validation.eligible_for_editorial is False for c in ranked)
    reasons = {c.candidate_id: c.relevance_validation.eligibility_reason for c in ranked}
    assert reasons["google-agg-thumb"] == "generic_aggregator_asset"
    assert "not_technically_validated" in reasons["broken"]
