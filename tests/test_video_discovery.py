"""Phase 19 M10: services.video_discovery - pure extraction/classification functions, no
network. Mirrors tests/test_article_metadata.py's own established convention for
services/article_metadata.py.
"""
from __future__ import annotations

from schemas.video_candidate import VideoDiscoveryMethod, VideoPlatform
from services.video_discovery import (
    _sniff_container,
    classify_video_url,
    extract_article_video_metadata,
    extract_rss_native_video,
)

# --- classify_video_url ------------------------------------------------------------------------


def test_youtube_watch_url_classified_as_youtube() -> None:
    assert classify_video_url("https://www.youtube.com/watch?v=abc123") == VideoPlatform.YOUTUBE


def test_youtu_be_short_url_classified_as_youtube() -> None:
    assert classify_video_url("https://youtu.be/abc123") == VideoPlatform.YOUTUBE


def test_youtube_embed_url_classified_as_youtube() -> None:
    assert classify_video_url("https://www.youtube.com/embed/abc123") == VideoPlatform.YOUTUBE


def test_vimeo_url_classified_as_vimeo() -> None:
    assert classify_video_url("https://vimeo.com/123456789") == VideoPlatform.VIMEO


def test_player_vimeo_url_classified_as_vimeo() -> None:
    assert classify_video_url("https://player.vimeo.com/video/123456789") == VideoPlatform.VIMEO


def test_mp4_extension_url_classified_as_direct_hosted() -> None:
    assert classify_video_url("https://cdn.example.com/videos/clip.mp4") == VideoPlatform.DIRECT_HOSTED


def test_webm_extension_url_classified_as_direct_hosted() -> None:
    assert classify_video_url("https://cdn.example.com/clip.webm") == VideoPlatform.DIRECT_HOSTED


def test_unrelated_url_classified_as_unknown() -> None:
    assert classify_video_url("https://example.com/article/some-story") == VideoPlatform.UNKNOWN


def test_malformed_url_classified_as_unknown() -> None:
    assert classify_video_url("not a url at all :::") == VideoPlatform.UNKNOWN


def test_youtube_lookalike_domain_not_misclassified() -> None:
    """A host merely containing "youtube" as a substring (not a real subdomain) must not match -
    same word-boundary-safe discipline as services/image_quality.py's own token patterns."""
    assert classify_video_url("https://notyoutube.com/watch?v=abc") == VideoPlatform.UNKNOWN


# ---------------------------------------------------------------------------
# Video URL Classification Checkpoint (follow-up to the Video Shadow Checkpoint's own real live
# evidence: 14/19 = 74% of "hosted-platform" hints in a ~75-minute shadow sample were channel/
# user/handle/subscribe links, not actual videos, docs/video_shadow_checkpoint.md §8). A YouTube/
# Vimeo hostname match alone is no longer sufficient - the path/query shape must also identify one
# of a small, explicitly bounded set of real video-URL forms.
# ---------------------------------------------------------------------------


# --- YouTube accepted -------------------------------------------------------------------------


def test_youtube_watch_url_with_extra_tracking_params_still_accepted() -> None:
    """Query/fragment normalization - extra tracking params and a fragment must not cause a
    legitimate watch?v=... URL to be rejected."""
    url = "https://m.youtube.com/watch?v=abc123&feature=share&list=PLxyz789#t=30s"
    assert classify_video_url(url) == VideoPlatform.YOUTUBE


def test_youtube_shorts_url_accepted() -> None:
    assert classify_video_url("https://www.youtube.com/shorts/abc123") == VideoPlatform.YOUTUBE


# (standard watch, youtu.be, and embed forms are already covered by the three pre-existing tests
# above - test_youtube_watch_url_classified_as_youtube/test_youtu_be_short_url_classified_as_
# youtube/test_youtube_embed_url_classified_as_youtube - re-verified unaffected by this fix.)


# --- YouTube rejected (the real false-positive shapes observed live) ---------------------------


def test_youtube_channel_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA") == VideoPlatform.UNKNOWN


def test_youtube_user_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/user/techcrunch") == VideoPlatform.UNKNOWN


def test_youtube_handle_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/@mkbhd") == VideoPlatform.UNKNOWN


def test_youtube_c_channel_slug_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/c/9to5google") == VideoPlatform.UNKNOWN


def test_youtube_channel_subscribe_confirmation_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/c/9to5mac?sub_confirmation=1") == VideoPlatform.UNKNOWN


def test_youtube_bare_channel_slug_url_rejected() -> None:
    """A bare "youtube.com/<name>" link (e.g. a footer "Follow us" link) - the exact shape of 10 of
    the 14 real false positives observed in the shadow sample."""
    assert classify_video_url("https://www.youtube.com/9to5mac") == VideoPlatform.UNKNOWN


def test_youtube_feed_subscriptions_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/feed/subscriptions") == VideoPlatform.UNKNOWN


def test_youtube_playlist_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/playlist?list=PLxyz") == VideoPlatform.UNKNOWN


def test_youtube_subscribe_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/subscribe_widget?p=abc") == VideoPlatform.UNKNOWN


def test_youtube_search_results_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/results?search_query=foo") == VideoPlatform.UNKNOWN


def test_youtube_bare_homepage_url_rejected() -> None:
    assert classify_video_url("https://www.youtube.com") == VideoPlatform.UNKNOWN
    assert classify_video_url("https://www.youtube.com/") == VideoPlatform.UNKNOWN


def test_youtube_watch_url_with_no_video_id_rejected() -> None:
    assert classify_video_url("https://www.youtube.com/watch") == VideoPlatform.UNKNOWN
    assert classify_video_url("https://www.youtube.com/watch?v=") == VideoPlatform.UNKNOWN
    assert classify_video_url("https://www.youtube.com/watch?foo=bar") == VideoPlatform.UNKNOWN


# --- Vimeo ---------------------------------------------------------------------------------------


def test_vimeo_video_url_with_privacy_hash_suffix_accepted() -> None:
    assert classify_video_url("https://vimeo.com/123456789/1a2b3c4d5e") == VideoPlatform.VIMEO


def test_vimeo_username_profile_url_rejected() -> None:
    assert classify_video_url("https://vimeo.com/someuser") == VideoPlatform.UNKNOWN


def test_vimeo_channel_url_rejected() -> None:
    assert classify_video_url("https://vimeo.com/channels/staffpicks") == VideoPlatform.UNKNOWN


def test_vimeo_showcase_url_rejected() -> None:
    assert classify_video_url("https://vimeo.com/showcase/12345") == VideoPlatform.UNKNOWN


def test_vimeo_bare_homepage_url_rejected() -> None:
    assert classify_video_url("https://vimeo.com") == VideoPlatform.UNKNOWN


# --- extract_rss_native_video -------------------------------------------------------------------


def test_media_content_video_medium_is_extracted() -> None:
    entry = {"media_content": [{"medium": "video", "url": "https://cdn.example.com/clip.mp4", "width": "1280", "height": "720"}]}
    hints = extract_rss_native_video(entry)
    assert len(hints) == 1
    assert hints[0].discovery_method == VideoDiscoveryMethod.RSS_MEDIA_CONTENT_VIDEO
    assert hints[0].declared_width == 1280


def test_media_content_image_medium_is_not_extracted() -> None:
    entry = {"media_content": [{"medium": "image", "url": "https://cdn.example.com/photo.jpg"}]}
    assert extract_rss_native_video(entry) == []


def test_enclosure_with_video_mime_type_is_extracted() -> None:
    entry = {"enclosures": [{"type": "video/mp4", "href": "https://cdn.example.com/clip.mp4"}]}
    hints = extract_rss_native_video(entry)
    assert len(hints) == 1
    assert hints[0].discovery_method == VideoDiscoveryMethod.RSS_ENCLOSURE_VIDEO


def test_enclosure_with_non_video_mime_type_is_not_extracted() -> None:
    entry = {"enclosures": [{"type": "audio/mpeg", "href": "https://cdn.example.com/clip.mp3"}]}
    assert extract_rss_native_video(entry) == []


def test_empty_entry_produces_no_hints() -> None:
    assert extract_rss_native_video({}) == []


# --- extract_article_video_metadata --------------------------------------------------------------


def test_og_video_secure_url_is_extracted() -> None:
    html = '<html><head><meta property="og:video:secure_url" content="https://cdn.example.com/clip.mp4"></head></html>'
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert any(h.discovery_method == VideoDiscoveryMethod.OPEN_GRAPH_VIDEO_SECURE for h in hints)


def test_video_tag_src_is_extracted() -> None:
    html = '<html><body><video src="clip.mp4"></video></body></html>'
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert len(hints) == 1
    assert hints[0].remote_url == "https://example.com/clip.mp4"
    assert hints[0].discovery_method == VideoDiscoveryMethod.HTML_VIDEO_TAG


def test_video_source_tag_is_extracted() -> None:
    html = '<html><body><video><source src="clip.webm" type="video/webm"></video></body></html>'
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert len(hints) == 1
    assert hints[0].declared_mime_type == "video/webm"


def test_twitter_player_stream_is_extracted() -> None:
    html = '<html><head><meta name="twitter:player:stream" content="https://cdn.example.com/clip.mp4"></head></html>'
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert any(h.discovery_method == VideoDiscoveryMethod.TWITTER_PLAYER_CARD for h in hints)


def test_youtube_link_already_in_article_html_is_extracted() -> None:
    html = '<html><body><a href="https://www.youtube.com/watch?v=abc123">Watch the video</a></body></html>'
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert len(hints) == 1
    assert hints[0].discovery_method == VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE
    assert hints[0].platform == VideoPlatform.YOUTUBE


def test_youtube_iframe_embed_already_in_article_html_is_extracted() -> None:
    html = '<html><body><iframe src="https://www.youtube.com/embed/abc123"></iframe></body></html>'
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert len(hints) == 1
    assert hints[0].platform == VideoPlatform.YOUTUBE


def test_ordinary_article_link_is_not_extracted_as_video() -> None:
    html = '<html><body><a href="https://example.com/related-article">Related</a></body></html>'
    assert extract_article_video_metadata(html, base_url="https://example.com/article") == []


def test_realistic_article_with_one_real_video_and_several_navigation_links_extracts_only_the_video() -> None:
    """Video URL Classification Checkpoint - realistic article shape: a real embedded video link
    alongside several channel/profile/navigation links of the exact kind observed live in the
    video-shadow canary (footer "Follow us" link, subscribe link, author's channel link,
    playlist link). Only the real video may become a NativeVideoHint."""
    html = """
    <html><body>
        <p>Watch our full breakdown: <a href="https://www.youtube.com/watch?v=abc123">here</a>.</p>
        <footer>
            <a href="https://www.youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA">Follow us on YouTube</a>
            <a href="https://www.youtube.com/c/9to5mac?sub_confirmation=1">Subscribe</a>
            <a href="https://www.youtube.com/@mkbhd">Author's channel</a>
            <a href="https://www.youtube.com/playlist?list=PLxyz">Related playlist</a>
        </footer>
    </body></html>
    """
    hints = extract_article_video_metadata(html, base_url="https://example.com/article")
    assert len(hints) == 1
    assert hints[0].remote_url == "https://www.youtube.com/watch?v=abc123"
    assert hints[0].platform == VideoPlatform.YOUTUBE
    assert hints[0].discovery_method == VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE


def test_empty_html_produces_no_hints() -> None:
    assert extract_article_video_metadata("", base_url="https://example.com/article") == []


def test_malformed_html_never_raises() -> None:
    html = "<html><meta property=og:video:secure_url content=<<<broken"
    extract_article_video_metadata(html, base_url="https://example.com/article")  # must not raise


# --- magic-byte sniffing --------------------------------------------------------------------------


def test_mp4_ftyp_signature_detected() -> None:
    data = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
    assert _sniff_container(data) == "mp4"


def test_webm_ebml_signature_detected() -> None:
    data = b"\x1a\x45\xdf\xa3" + b"\x00" * 100
    assert _sniff_container(data) == "webm_mkv"


def test_unrecognized_bytes_return_none() -> None:
    assert _sniff_container(b"not a real video file at all") is None


def test_short_bytes_never_raise() -> None:
    assert _sniff_container(b"") is None
    assert _sniff_container(b"\x00\x00") is None
