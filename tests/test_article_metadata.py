"""Tests for services.article_metadata (Phase 16 M2, docs/phase16_m2_secure_fetch_and_validation_
report.md §10/§21). Pure HTML parsing - no network, no fixtures beyond inline HTML strings.
"""
from schemas.image_candidate import ImageDiscoveryMethod
from services.article_metadata import extract_article_image_metadata

BASE_URL = "https://example.com/article/1"


def _method(hints, index=0):
    return hints[index].discovery_method


def test_og_image() -> None:
    html = '<meta property="og:image" content="https://cdn.example.com/a.jpg">'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert len(hints) == 1
    assert hints[0].discovery_method == ImageDiscoveryMethod.OPEN_GRAPH_IMAGE
    assert hints[0].remote_url == "https://cdn.example.com/a.jpg"


def test_og_image_url_variant() -> None:
    html = '<meta property="og:image:url" content="https://cdn.example.com/b.jpg">'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].discovery_method == ImageDiscoveryMethod.OPEN_GRAPH_IMAGE
    assert hints[0].remote_url == "https://cdn.example.com/b.jpg"


def test_og_image_secure_url() -> None:
    html = '<meta property="og:image:secure_url" content="https://cdn.example.com/c.jpg">'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].discovery_method == ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE


def test_og_image_dimensions_and_alt_text() -> None:
    html = """
    <meta property="og:image" content="https://cdn.example.com/a.jpg">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:image:alt" content="A description">
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].declared_width == 1200
    assert hints[0].declared_height == 630
    assert hints[0].alt_text == "A description"


def test_twitter_image() -> None:
    html = '<meta name="twitter:image" content="https://cdn.example.com/tw.jpg">'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].discovery_method == ImageDiscoveryMethod.TWITTER_IMAGE


def test_twitter_image_src_variant() -> None:
    html = '<meta name="twitter:image:src" content="https://cdn.example.com/tw2.jpg">'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].discovery_method == ImageDiscoveryMethod.TWITTER_IMAGE


def test_link_rel_image_src() -> None:
    html = '<link rel="image_src" href="https://cdn.example.com/link.jpg">'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].discovery_method == ImageDiscoveryMethod.IMAGE_SRC_LINK


def test_jsonld_article_image_string() -> None:
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Article","image":"https://cdn.example.com/j1.jpg"}
    </script>
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].discovery_method == ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE
    assert hints[0].remote_url == "https://cdn.example.com/j1.jpg"


def test_jsonld_newsarticle_imageobject() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"NewsArticle","image":{"@type":"ImageObject","url":"https://cdn.example.com/j2.jpg"}}
    </script>
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].remote_url == "https://cdn.example.com/j2.jpg"


def test_jsonld_imageobject_content_url() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"NewsArticle","image":{"@type":"ImageObject","contentUrl":"https://cdn.example.com/j3.jpg"}}
    </script>
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].remote_url == "https://cdn.example.com/j3.jpg"


def test_jsonld_image_array() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"Article","image":["https://cdn.example.com/j4.jpg","https://cdn.example.com/j5.jpg"]}
    </script>
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    urls = {h.remote_url for h in hints}
    assert urls == {"https://cdn.example.com/j4.jpg", "https://cdn.example.com/j5.jpg"}


def test_multiple_jsonld_blocks() -> None:
    html = """
    <script type="application/ld+json">{"@type":"Article","image":"https://cdn.example.com/a.jpg"}</script>
    <script type="application/ld+json">{"@type":"Article","image":"https://cdn.example.com/b.jpg"}</script>
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    urls = {h.remote_url for h in hints}
    assert urls == {"https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"}


def test_jsonld_at_graph_wrapping() -> None:
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"WebPage"},
      {"@type":"NewsArticle","image":"https://cdn.example.com/graph.jpg"}
    ]}
    </script>
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints[0].remote_url == "https://cdn.example.com/graph.jpg"


def test_malformed_jsonld_does_not_crash() -> None:
    html = '<script type="application/ld+json">not valid json {{{</script>'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)  # must not raise
    assert hints == []


def test_relative_image_url_resolved() -> None:
    html = '<meta property="og:image" content="/images/a.jpg">'
    hints = extract_article_image_metadata(html, base_url="https://example.com/blog/post-1")
    assert hints[0].remote_url == "https://example.com/images/a.jpg"


def test_scheme_relative_image_url_resolved() -> None:
    html = '<meta property="og:image" content="//cdn.example.com/a.jpg">'
    hints = extract_article_image_metadata(html, base_url="https://example.com/blog/post-1")
    assert hints[0].remote_url == "https://cdn.example.com/a.jpg"


def test_duplicate_url_across_og_and_twitter_appears_as_separate_hints() -> None:
    """Extraction preserves every discovered hint - consolidation (services/image_intelligence.py)
    is what deduplicates identical URLs, keeping the higher-priority discovery method."""
    html = """
    <meta property="og:image" content="https://cdn.example.com/same.jpg">
    <meta name="twitter:image" content="https://cdn.example.com/same.jpg">
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert len(hints) == 2
    assert {h.discovery_method for h in hints} == {ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, ImageDiscoveryMethod.TWITTER_IMAGE}


def test_distinct_image_urls_remain_distinct() -> None:
    html = """
    <meta property="og:image" content="https://cdn.example.com/one.jpg">
    <meta name="twitter:image" content="https://cdn.example.com/two.jpg">
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert {h.remote_url for h in hints} == {"https://cdn.example.com/one.jpg", "https://cdn.example.com/two.jpg"}


def test_priority_order_is_secure_og_then_og_then_jsonld_then_twitter_then_image_src() -> None:
    html = """
    <link rel="image_src" href="https://cdn.example.com/5.jpg">
    <meta name="twitter:image" content="https://cdn.example.com/4.jpg">
    <script type="application/ld+json">{"@type":"Article","image":"https://cdn.example.com/3.jpg"}</script>
    <meta property="og:image" content="https://cdn.example.com/2.jpg">
    <meta property="og:image:secure_url" content="https://cdn.example.com/1.jpg">
    """
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    ordered_urls = [h.remote_url for h in hints]
    assert ordered_urls == [
        "https://cdn.example.com/1.jpg",
        "https://cdn.example.com/2.jpg",
        "https://cdn.example.com/3.jpg",
        "https://cdn.example.com/4.jpg",
        "https://cdn.example.com/5.jpg",
    ]


def test_no_image_metadata_returns_zero_candidates_without_failure() -> None:
    html = "<html><head><title>No images here</title></head><body>text</body></html>"
    hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert hints == []


def test_malformed_html_does_not_crash() -> None:
    html = '<meta property="og:image" content="https://cdn.example.com/a.jpg"<div><span>unterminated'
    hints = extract_article_image_metadata(html, base_url=BASE_URL)  # must not raise
    assert isinstance(hints, list)


def test_empty_html_returns_zero_candidates() -> None:
    assert extract_article_image_metadata("", base_url=BASE_URL) == []


def test_feed_level_object_is_never_read() -> None:
    """extract_article_image_metadata's only parameters are html + base_url - it has no path to
    receive a separate "feed" or "site" object, unlike a hypothetical crawler that might conflate
    a site-wide logo with an article image."""
    import inspect

    parameters = set(inspect.signature(extract_article_image_metadata).parameters)
    assert parameters == {"html", "base_url"}
