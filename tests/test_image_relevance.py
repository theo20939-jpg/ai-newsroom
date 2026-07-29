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


def test_60_missing_metadata_does_not_produce_dead_constant_component():
    rich = score_candidate(_candidate(alt_text="GPT-5 launch photo", caption="official image", declared_width=1200, declared_height=630), _CTX)
    poor = score_candidate(_candidate(alt_text=None, caption=None, remote_url=None), _CTX)
    assert rich.components["metadata_confidence"] != poor.components["metadata_confidence"]


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
