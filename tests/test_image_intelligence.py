"""Tests for services.image_intelligence (Phase 16 M1, docs/phase16_m1_native_media_ingestion_
report.md). Pure, offline, no network, no database - fake Telethon-shaped objects and plain
dicts for feedparser-shaped entries, matching tests/test_telegram_source.py's own established
"lightweight fake object, never a real client" pattern.
"""
from dataclasses import dataclass, field
from uuid import uuid4

from database.models.news_source import SourceType
from schemas.image_candidate import ImageCandidateStatus, ImageDiscoveryMethod
from services.image_intelligence import (
    consolidate_candidates,
    extract_rss_native_media,
    extract_telegram_native_media,
    reconstruct_hints_from_content,
)

# ---------------------------------------------------------------------------
# Fake Telethon-shaped objects - class names matter (services.image_intelligence checks
# `type(attribute).__name__` against real Telethon attribute class names).
# ---------------------------------------------------------------------------


@dataclass
class _FakeSize:
    w: int | None = None
    h: int | None = None


@dataclass
class _FakeStrippedSize:
    """Mirrors telethon's PhotoStrippedSize - carries no real w/h."""


@dataclass
class _FakePhoto:
    id: int | None = None
    sizes: list = field(default_factory=list)


@dataclass
class DocumentAttributeFilename:
    file_name: str


@dataclass
class DocumentAttributeImageSize:
    w: int
    h: int


@dataclass
class DocumentAttributeSticker:
    pass


@dataclass
class DocumentAttributeVideo:
    pass


@dataclass
class DocumentAttributeAudio:
    pass


@dataclass
class _FakeDocument:
    id: int | None = None
    mime_type: str | None = None
    attributes: list = field(default_factory=list)


@dataclass
class _FakeMessage:
    id: int
    text: str | None = None
    grouped_id: int | None = None
    photo: object | None = None
    document: object | None = None


# ---------------------------------------------------------------------------
# 1-12: Telegram extraction
# ---------------------------------------------------------------------------


def test_telegram_photo_produces_one_candidate() -> None:
    message = _FakeMessage(id=1, photo=_FakePhoto(id=555, sizes=[_FakeSize(w=1280, h=720)]))
    hints = extract_telegram_native_media(message)
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.TELEGRAM_PHOTO


def test_telegram_photo_size_metadata_is_preserved_where_available() -> None:
    message = _FakeMessage(
        id=2,
        photo=_FakePhoto(id=1, sizes=[_FakeStrippedSize(), _FakeSize(w=90, h=90), _FakeSize(w=1280, h=720)]),
    )
    hints = extract_telegram_native_media(message)
    assert hints[0].declared_width == 1280
    assert hints[0].declared_height == 720  # the largest size wins, the stripped preview is ignored


def test_telegram_image_document_produces_one_candidate() -> None:
    document = _FakeDocument(
        id=99,
        mime_type="image/png",
        attributes=[DocumentAttributeFilename(file_name="chart.png"), DocumentAttributeImageSize(w=640, h=480)],
    )
    message = _FakeMessage(id=3, document=document)
    hints = extract_telegram_native_media(message)
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.TELEGRAM_DOCUMENT
    assert hints[0].declared_mime_type == "image/png"
    assert hints[0].declared_width == 640
    assert hints[0].telegram.file_name == "chart.png"


def test_non_image_document_produces_no_candidate() -> None:
    document = _FakeDocument(id=1, mime_type="application/pdf", attributes=[])
    message = _FakeMessage(id=4, document=document)
    assert extract_telegram_native_media(message) == []


def test_sticker_document_is_never_a_candidate_even_with_image_mime() -> None:
    document = _FakeDocument(id=1, mime_type="image/webp", attributes=[DocumentAttributeSticker()])
    message = _FakeMessage(id=5, document=document)
    assert extract_telegram_native_media(message) == []


def test_video_document_is_never_a_candidate() -> None:
    document = _FakeDocument(id=1, mime_type="image/gif", attributes=[DocumentAttributeVideo()])
    message = _FakeMessage(id=6, document=document)
    assert extract_telegram_native_media(message) == []


def test_media_group_preserves_grouped_id() -> None:
    message = _FakeMessage(id=7, grouped_id=4242, photo=_FakePhoto(id=1, sizes=[_FakeSize(w=100, h=100)]))
    hints = extract_telegram_native_media(message)
    assert hints[0].telegram.grouped_id == 4242


def test_caption_is_preserved_safely() -> None:
    message = _FakeMessage(id=8, text="A caption", photo=_FakePhoto(id=1, sizes=[]))
    hints = extract_telegram_native_media(message)
    assert hints[0].caption == "A caption"


def test_caption_is_bounded_in_length() -> None:
    message = _FakeMessage(id=9, text="x" * 10_000, photo=_FakePhoto(id=1, sizes=[]))
    hints = extract_telegram_native_media(message)
    assert len(hints[0].caption) <= 500


def test_same_message_processed_twice_produces_the_same_candidate_id() -> None:
    event_id = uuid4()
    message = _FakeMessage(id=10, grouped_id=1, photo=_FakePhoto(id=77, sizes=[_FakeSize(w=10, h=10)]))
    hints_a = extract_telegram_native_media(message)
    hints_b = extract_telegram_native_media(message)
    result_a = consolidate_candidates(hints_a, event_id=event_id, source_type=SourceType.TELEGRAM, mode="shadow")
    result_b = consolidate_candidates(hints_b, event_id=event_id, source_type=SourceType.TELEGRAM, mode="shadow")
    assert result_a.candidates[0].candidate_id == result_b.candidates[0].candidate_id


def test_different_messages_do_not_collide() -> None:
    event_id = uuid4()
    message_1 = _FakeMessage(id=11, photo=_FakePhoto(id=1, sizes=[]))
    message_2 = _FakeMessage(id=12, photo=_FakePhoto(id=2, sizes=[]))
    hints = extract_telegram_native_media(message_1) + extract_telegram_native_media(message_2)
    result = consolidate_candidates(hints, event_id=event_id, source_type=SourceType.TELEGRAM, mode="shadow")
    ids = {c.candidate_id for c in result.candidates}
    assert len(ids) == 2


def test_raw_telethon_object_is_not_serialized() -> None:
    """The photo/document object itself never appears in a hint's fields - only plain,
    JSON-serializable scalars and the deliberately narrow TelegramReference."""
    message = _FakeMessage(id=13, photo=_FakePhoto(id=1, sizes=[_FakeSize(w=10, h=10)]))
    hints = extract_telegram_native_media(message)
    dumped = hints[0].model_dump()
    assert "photo" not in dumped
    for value in dumped.values():
        assert not isinstance(value, _FakePhoto)


def test_session_or_auth_data_is_never_persisted_or_logged() -> None:
    """TelegramReference has no access_hash/file_reference field at all - proves it structurally,
    not just "wasn't set this time"."""
    from schemas.image_candidate import TelegramReference

    fields = set(TelegramReference.model_fields.keys())
    assert "access_hash" not in fields
    assert "file_reference" not in fields


def test_missing_optional_media_attributes_do_not_crash_extraction() -> None:
    message = _FakeMessage(id=14, photo=_FakePhoto(id=None, sizes=[]))
    hints = extract_telegram_native_media(message)
    assert len(hints) == 1
    assert hints[0].declared_width is None


def test_message_with_neither_photo_nor_document_produces_no_hints() -> None:
    message = _FakeMessage(id=15)
    assert extract_telegram_native_media(message) == []


def test_extraction_never_raises_even_for_completely_malformed_photo() -> None:
    class _Broken:
        @property
        def sizes(self):
            raise RuntimeError("boom")

    message = _FakeMessage(id=16, photo=_Broken())
    assert extract_telegram_native_media(message) == []  # logged and swallowed, not raised


# ---------------------------------------------------------------------------
# 13-30: RSS extraction
# ---------------------------------------------------------------------------


def test_media_content_image_is_extracted() -> None:
    entry = {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image", "width": "800", "height": "600"}]}
    hints = extract_rss_native_media(entry, article_url="https://example.com/post")
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.RSS_MEDIA_CONTENT
    assert hints[0].declared_width == 800


def test_media_thumbnail_is_extracted() -> None:
    entry = {"media_thumbnail": [{"url": "https://cdn.example.com/thumb.jpg", "width": "150", "height": "150"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL


def test_image_enclosure_is_extracted() -> None:
    entry = {"enclosures": [{"href": "https://cdn.example.com/e.jpg", "type": "image/jpeg"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.RSS_ENCLOSURE


def test_non_image_enclosure_is_rejected() -> None:
    entry = {"enclosures": [{"href": "https://cdn.example.com/audio.mp3", "type": "audio/mpeg"}]}
    assert extract_rss_native_media(entry, article_url=None) == []


def test_inline_img_src_is_extracted() -> None:
    entry = {"summary": '<p>hello <img src="https://cdn.example.com/inline.jpg" alt="desc"/></p>'}
    hints = extract_rss_native_media(entry, article_url=None)
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.RSS_INLINE_IMAGE
    assert hints[0].remote_url == "https://cdn.example.com/inline.jpg"
    assert hints[0].alt_text == "desc"


def test_data_src_lazy_load_attribute_is_preferred_over_placeholder_src() -> None:
    entry = {"summary": '<img src="placeholder.gif" data-src="https://cdn.example.com/real.jpg"/>'}
    hints = extract_rss_native_media(entry, article_url="https://example.com/post")
    assert hints[0].remote_url == "https://cdn.example.com/real.jpg"


def test_data_original_lazy_load_attribute_is_supported() -> None:
    entry = {"summary": '<img data-original="https://cdn.example.com/orig.jpg"/>'}
    hints = extract_rss_native_media(entry, article_url=None)
    assert hints[0].remote_url == "https://cdn.example.com/orig.jpg"


def test_valid_srcset_prefers_largest_declared_width() -> None:
    entry = {"summary": '<img srcset="https://cdn.example.com/small.jpg 480w, https://cdn.example.com/big.jpg 1200w">'}
    hints = extract_rss_native_media(entry, article_url=None)
    assert hints[0].remote_url == "https://cdn.example.com/big.jpg"
    assert hints[0].warnings == []


def test_malformed_srcset_falls_back_to_src_with_a_warning() -> None:
    entry = {"summary": '<img src="https://cdn.example.com/fallback.jpg" srcset="not a valid srcset">'}
    hints = extract_rss_native_media(entry, article_url=None)
    assert hints[0].remote_url == "https://cdn.example.com/fallback.jpg"
    assert "malformed_srcset_ignored" in hints[0].warnings


def test_relative_url_is_resolved_against_article_url() -> None:
    entry = {"summary": '<img src="/images/a.jpg">'}
    hints = extract_rss_native_media(entry, article_url="https://example.com/posts/1")
    assert hints[0].remote_url == "https://example.com/images/a.jpg"


def test_scheme_relative_url_is_resolved() -> None:
    entry = {"summary": '<img src="//cdn.example.com/a.jpg">'}
    hints = extract_rss_native_media(entry, article_url="https://example.com/posts/1")
    assert hints[0].remote_url == "https://cdn.example.com/a.jpg"


def test_data_scheme_url_is_rejected_at_consolidation() -> None:
    entry = {"summary": '<img src="data:image/png;base64,AAAA">'}
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    assert result.candidates[0].status == ImageCandidateStatus.REJECTED_METADATA
    assert any(reason.startswith("unsupported_scheme") for reason in result.candidates[0].rejection_reasons)


def test_javascript_scheme_url_is_rejected_at_consolidation() -> None:
    entry = {"summary": '<img src="javascript:alert(1)">'}
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    assert result.candidates[0].status == ImageCandidateStatus.REJECTED_METADATA


def test_malformed_url_is_rejected_at_consolidation() -> None:
    entry = {"media_content": [{"url": "ht!tp:///broken", "medium": "image"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    assert result.candidates[0].status == ImageCandidateStatus.REJECTED_METADATA


def test_feed_level_logo_is_architecturally_never_read() -> None:
    """extract_rss_native_media's only parameters are one entry + article_url - it has no
    parameter through which a channel-level feed object (where a logo/icon would live) could
    ever be passed in, so a feed logo can never be mistaken for an article image here."""
    import inspect

    from services.image_intelligence import extract_rss_native_media

    parameters = set(inspect.signature(extract_rss_native_media).parameters)
    assert parameters == {"entry", "article_url"}


def test_duplicate_url_from_multiple_rss_fields_consolidates_safely() -> None:
    entry = {
        "media_content": [{"url": "https://cdn.example.com/same.jpg", "medium": "image"}],
        "enclosures": [{"href": "https://cdn.example.com/same.jpg", "type": "image/jpeg"}],
    }
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    assert result.candidates_accepted == 1
    accepted = [c for c in result.candidates if c.status == ImageCandidateStatus.DISCOVERED]
    assert len(accepted) == 1
    assert accepted[0].discovery_method == ImageDiscoveryMethod.RSS_MEDIA_CONTENT  # higher priority wins


def test_two_distinct_urls_remain_separate() -> None:
    entry = {
        "media_content": [
            {"url": "https://cdn.example.com/one.jpg", "medium": "image"},
            {"url": "https://cdn.example.com/two.jpg", "medium": "image"},
        ]
    }
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    assert result.candidates_accepted == 2


def test_malformed_html_does_not_crash_parsing() -> None:
    entry = {"summary": "<img src='unterminated <div><img src=broken"}
    hints = extract_rss_native_media(entry, article_url=None)  # must not raise
    assert isinstance(hints, list)


def test_empty_url_is_rejected() -> None:
    entry = {"media_content": [{"url": "", "medium": "image"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    assert hints == []  # no URL at all - not even a hint is produced


def test_media_content_with_non_image_medium_is_not_a_candidate() -> None:
    entry = {"media_content": [{"url": "https://cdn.example.com/v.mp4", "medium": "video"}]}
    assert extract_rss_native_media(entry, article_url=None) == []


# ---------------------------------------------------------------------------
# 31-35: NEWS_API-category adapters (GitHub/HN/arXiv empty-native behavior)
# ---------------------------------------------------------------------------


def test_no_native_media_source_produces_no_hints_and_is_not_an_error() -> None:
    """Generic proof for GitHub/HN/arXiv: extract_rss_native_media/extract_telegram_native_media
    are simply never called for these adapters - empty native_media_hints (the RawNewsItem
    default) is the correct, non-error M1 behavior. Adapter-specific assertions live in
    tests/test_github_source.py, tests/test_hacker_news_source.py, tests/test_arxiv_source.py."""
    from schemas.raw_news_item import RawNewsItem

    item = RawNewsItem(external_id="x", text="body")
    assert item.native_media_hints == []


# ---------------------------------------------------------------------------
# 49-54: persistence / serialization
# ---------------------------------------------------------------------------


def test_candidate_result_serializes_to_json() -> None:
    entry = {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image", "width": "10", "height": "10"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    payload = result.model_dump(mode="json")
    import json

    json.dumps(payload)  # must not raise


def test_result_deserializes_without_loss() -> None:
    from schemas.image_candidate import ImageIntelligenceResult

    entry = {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    round_tripped = ImageIntelligenceResult.model_validate(result.model_dump(mode="json"))
    assert round_tripped == result


def test_candidate_ids_remain_stable_across_two_consolidation_runs() -> None:
    event_id = uuid4()
    entry = {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    result_a = consolidate_candidates(hints, event_id=event_id, source_type=SourceType.RSS, mode="shadow")
    result_b = consolidate_candidates(hints, event_id=event_id, source_type=SourceType.RSS, mode="shadow")
    assert result_a.candidates[0].candidate_id == result_b.candidates[0].candidate_id


def test_no_secret_or_opaque_object_is_serialized() -> None:
    message = _FakeMessage(id=1, photo=_FakePhoto(id=1, sizes=[_FakeSize(w=10, h=10)]))
    hints = extract_telegram_native_media(message)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.TELEGRAM, mode="shadow")
    dumped_json = result.model_dump_json()
    assert "access_hash" not in dumped_json
    assert "file_reference" not in dumped_json
    assert "_Fake" not in dumped_json


def test_payload_remains_within_a_reasonable_bounded_size() -> None:
    entry = {
        "media_content": [
            {"url": f"https://cdn.example.com/{i}.jpg", "medium": "image"} for i in range(20)
        ]
    }
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="shadow")
    assert len(result.model_dump_json()) < 50_000  # generous bound for a pathological 20-image entry


def test_duplicate_execution_does_not_append_duplicate_candidates() -> None:
    """Re-running consolidate_candidates with the exact same hints for the same event produces an
    equally-sized, not-growing candidate list every time (idempotent, not additive)."""
    event_id = uuid4()
    entry = {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    first = consolidate_candidates(hints, event_id=event_id, source_type=SourceType.RSS, mode="shadow")
    second = consolidate_candidates(hints, event_id=event_id, source_type=SourceType.RSS, mode="shadow")
    assert len(first.candidates) == len(second.candidates) == 1


# ---------------------------------------------------------------------------
# mode="off" and reconstruction helper
# ---------------------------------------------------------------------------


def test_mode_off_returns_empty_result_without_inspecting_hints() -> None:
    entry = {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image"}]}
    hints = extract_rss_native_media(entry, article_url=None)
    result = consolidate_candidates(hints, event_id=uuid4(), source_type=SourceType.RSS, mode="off")
    assert result.candidates == []
    assert result.candidates_discovered == 0
    assert result.mode == "off"


def test_reconstruct_from_persisted_content_recovers_inline_rss_image() -> None:
    content = '<p>Real article <img src="https://cdn.example.com/real.jpg"/></p>'
    hints = reconstruct_hints_from_content(content, "https://example.com/article")
    assert len(hints) == 1
    assert hints[0].remote_url == "https://cdn.example.com/real.jpg"


def test_reconstruct_from_persisted_content_finds_nothing_for_plain_telegram_text() -> None:
    content = "Just a plain Telegram message with no HTML at all."
    hints = reconstruct_hints_from_content(content, "https://t.me/example_channel/123")
    assert hints == []


def test_reconstruct_from_persisted_content_handles_none_content() -> None:
    assert reconstruct_hints_from_content(None, None) == []
