"""Tests for services.article_metadata (Phase 16 M2, docs/phase16_m2_secure_fetch_and_validation_
report.md §10/§21). Pure HTML parsing - no network, no fixtures beyond inline HTML strings.
"""
from schemas.image_candidate import ImageDiscoveryMethod
from services.article_metadata import extract_article_image_metadata, extract_inline_article_images

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


# ---------------------------------------------------------------------------------------------
# Image Discovery Upgrade: extract_inline_article_images() - the second, independent article-body
# extractor. All scenarios below are the task brief's own required test list, plus a few adjacent
# edge cases (srcset density descriptors, data URI, no-priority-container fallback, picture/source
# vs. fallback img dedup) that follow directly from the same rules.
# ---------------------------------------------------------------------------------------------


def test_1_two_plain_body_images_both_discovered() -> None:
    html = """
    <body>
    <img src="main.jpg" width="800" height="500">
    <img src="second.jpg" width="600" height="400">
    </body>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert len(hints) == 2
    assert {h.discovery_method for h in hints} == {ImageDiscoveryMethod.ARTICLE_INLINE_IMAGE}
    urls = {h.remote_url for h in hints}
    assert urls == {"https://example.com/article/main.jpg", "https://example.com/article/second.jpg"}


def test_2_article_container_image_ranked_above_outside_image() -> None:
    html = """
    <article>
    <img src="article1.jpg" width="1000" height="600">
    </article>
    <img src="outside.jpg" width="1000" height="600">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    urls = [h.remote_url for h in hints]
    assert "https://example.com/article/article1.jpg" in urls
    # A priority container exists in this document, so the stray body-level image outside it is
    # excluded entirely - never merely deprioritized (module docstring's own explicit scoping
    # rule) - "article1 ranks higher" is satisfied unambiguously by "outside.jpg is absent".
    assert "https://example.com/article/outside.jpg" not in urls


def test_2b_no_priority_container_falls_back_to_whole_body() -> None:
    html = '<div class="wrapper"><img src="only.jpg" width="800" height="500"></div>'
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/only.jpg"]


def test_2c_content_class_div_counts_as_priority_container() -> None:
    """"content"/"post"/"entry"/"story" are CSS class/id conventions, not real tag names - matched
    against the element's own class/id attribute, not just <article>/<main>."""
    html = """
    <div class="post-content">
    <img src="inside.jpg" width="800" height="500">
    </div>
    <img src="outside.jpg" width="800" height="500">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    urls = [h.remote_url for h in hints]
    assert urls == ["https://example.com/article/inside.jpg"]


def test_3_icon_ad_and_avatar_images_filtered_leaving_only_the_real_photo() -> None:
    html = """
    <img src="logo.svg" width="800" height="500">
    <img src="favicon.png" width="800" height="500">
    <img src="user-avatar.jpg" width="800" height="500">
    <img src="promo-banner.jpg" width="800" height="500">
    <img src="tracking-pixel.gif" width="800" height="500">
    <img src="real-photo.jpg" width="1200" height="800">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/real-photo.jpg"]


def test_4_srcset_picks_the_highest_declared_width() -> None:
    html = """
    <img srcset="small.jpg 300w, large.jpg 1200w" width="300" height="200">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert len(hints) == 1
    assert hints[0].remote_url == "https://example.com/article/large.jpg"
    assert hints[0].declared_width == 1200


def test_4b_srcset_density_descriptor_picks_highest_x() -> None:
    html = '<img srcset="one.jpg 1x, two.jpg 2x">'
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert hints[0].remote_url == "https://example.com/article/two.jpg"


def test_4c_picture_source_srcset_used_and_fallback_img_not_double_counted() -> None:
    html = """
    <picture>
      <source srcset="from-source.jpg 1200w">
      <img src="fallback.jpg" width="800" height="500">
    </picture>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert len(hints) == 1
    assert hints[0].remote_url == "https://example.com/article/from-source.jpg"


def test_5_raw_candidate_count_is_bounded_even_with_twenty_images() -> None:
    html = "".join(f'<img src="img{i}.jpg" width="800" height="500">' for i in range(20))
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert len(hints) <= 10


def test_5b_final_output_bounded_at_five() -> None:
    html = "".join(f'<img src="img{i}.jpg" width="{1000 - i}" height="600">' for i in range(10))
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert len(hints) <= 5


def test_too_small_known_dimensions_excluded() -> None:
    html = """
    <img src="tiny.jpg" width="100" height="100">
    <img src="short.jpg" width="800" height="150">
    <img src="ok.jpg" width="800" height="500">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/ok.jpg"]


def test_unknown_dimensions_never_excluded_on_size_alone() -> None:
    html = '<img src="unknown-size.jpg">'
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/unknown-size.jpg"]


def test_data_uri_excluded() -> None:
    html = '<img src="data:image/png;base64,iVBORw0KGgo="><img src="real.jpg" width="800" height="500">'
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/real.jpg"]


def test_svg_extension_excluded() -> None:
    html = '<img src="diagram.svg" width="800" height="500"><img src="photo.jpg" width="800" height="500">'
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/photo.jpg"]


def test_larger_image_sorted_first() -> None:
    html = """
    <img src="small.jpg" width="400" height="300">
    <img src="large.jpg" width="1600" height="900">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert hints[0].remote_url == "https://example.com/article/large.jpg"


def test_known_dimensions_ranked_above_unknown_regardless_of_position() -> None:
    html = """
    <img src="unknown.jpg">
    <img src="known.jpg" width="400" height="300">
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert hints[0].remote_url == "https://example.com/article/known.jpg"


def test_no_images_returns_empty_list() -> None:
    html = "<html><body><p>no images here</p></body></html>"
    assert extract_inline_article_images(html, base_url=BASE_URL) == []


def test_empty_html_returns_zero_candidates_for_inline_extractor() -> None:
    assert extract_inline_article_images("", base_url=BASE_URL) == []


def test_malformed_html_does_not_crash_inline_extractor() -> None:
    html = '<article><img src="a.jpg" width="800" height="500"<div><span>unterminated'
    hints = extract_inline_article_images(html, base_url=BASE_URL)  # must not raise
    assert isinstance(hints, list)


def test_relative_inline_url_resolved() -> None:
    html = '<img src="/images/inline.jpg" width="800" height="500">'
    hints = extract_inline_article_images(html, base_url="https://example.com/blog/post-1")
    assert hints[0].remote_url == "https://example.com/images/inline.jpg"


def test_6_metadata_extractor_regression_unaffected_by_inline_extractor() -> None:
    """The existing extract_article_image_metadata() must keep working byte-for-byte unchanged -
    it never sees <img>/<picture> tags at all, only head <meta>/<link> tags."""
    html = """
    <meta property="og:image" content="https://cdn.example.com/a.jpg">
    <body><img src="inline.jpg" width="800" height="500"></body>
    """
    meta_hints = extract_article_image_metadata(html, base_url=BASE_URL)
    assert len(meta_hints) == 1
    assert meta_hints[0].discovery_method == ImageDiscoveryMethod.OPEN_GRAPH_IMAGE
    assert meta_hints[0].remote_url == "https://cdn.example.com/a.jpg"


def test_inline_extractor_never_reads_meta_tags() -> None:
    html = '<meta property="og:image" content="https://cdn.example.com/a.jpg">'
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert hints == []


# ---------------------------------------------------------------------------------------------
# 3DNews secondary/related-subtree false-positive fix. Real production canary case:
# https://3dnews.ru/1146956 - the real article image (github.jpg) is correctly found inline, but
# unrelated "related content" widgets nested in the same priority container were also being
# picked up. Shapes below are the real observed class/id values (see services/article_metadata.py
# ::_SECONDARY_CONTAINER_TOKENS's own docstring for the full forensic trail).
# ---------------------------------------------------------------------------------------------


def test_1_3dnews_forensic_shape_only_returns_the_real_article_image() -> None:
    html = """
    <div class="article-entry">
      <div class="entry-body">
        <div class="js-mediator-article">

          <img src="github.jpg" width="800" height="533">

          <div class="slider-container" id="newsSlider">
            <img class="slider-slide-image" src="wrong1.jpg" width="800" height="600">
          </div>

          <div class="content-block relatedbox rbxglob">
            <img src="wrong2.jpg" width="800" height="600">
          </div>

          <div class="content-block related-slider js-related-slider">
            <img src="wrong3.jpg" width="800" height="600">
          </div>

        </div>
      </div>
    </div>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/github.jpg"]


def test_2_habr_like_normal_article_body_keeps_useful_images() -> None:
    html = """
    <article class="tm-article-body">
      <div class="article-formatted-body">
        <p>Some intro text.</p>
        <img src="diagram1.png" width="900" height="500" alt="Architecture diagram">
        <p>More text.</p>
        <img src="screenshot2.png" width="850" height="480" alt="Screenshot">
      </div>
    </article>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    urls = {h.remote_url for h in hints}
    assert urls == {
        "https://example.com/article/diagram1.png",
        "https://example.com/article/screenshot2.png",
    }


def test_3_generic_slider_without_related_signal_is_not_excluded() -> None:
    """A bare "slider"/gallery wrapper, with no related/recommend/news-slider signal anywhere in
    its own or ancestor class/id, must never be excluded just for containing the word "slider" -
    the task's own explicit "не убить легитимную галерею" requirement."""
    html = """
    <article>
      <div class="article-gallery slider-container">
        <img src="gallery1.jpg" width="900" height="600">
        <img src="gallery2.jpg" width="900" height="600">
      </div>
    </article>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    urls = {h.remote_url for h in hints}
    assert urls == {
        "https://example.com/article/gallery1.jpg",
        "https://example.com/article/gallery2.jpg",
    }


def test_4_secondary_ancestor_wins_over_priority_ancestor() -> None:
    """priority=True AND secondary=True (nested) -> excluded. Mirrors the real 3DNews shape:
    entry-body (priority, via "entry") wraps related-slider (secondary)."""
    html = """
    <div class="entry-body">
      <div class="related-slider">
        <img src="wrong.jpg" width="900" height="600">
      </div>
      <img src="right.jpg" width="900" height="600">
    </div>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/right.jpg"]


def test_5_related_block_without_declared_dimensions_still_excluded() -> None:
    html = """
    <article>
      <div class="read-more-block">
        <img src="wrong.jpg">
      </div>
      <img src="right.jpg" width="900" height="600">
    </article>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/right.jpg"]


def test_recommended_and_recommendation_variants_excluded_via_recommend_substring() -> None:
    html = """
    <article>
      <div class="recommended-articles"><img src="a.jpg" width="900" height="600"></div>
      <div class="recommendation-widget"><img src="b.jpg" width="900" height="600"></div>
      <img src="right.jpg" width="900" height="600">
    </article>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/right.jpg"]


def test_more_news_and_readmore_variants_excluded() -> None:
    html = """
    <article>
      <div class="more-news-block"><img src="a.jpg" width="900" height="600"></div>
      <div class="readmore"><img src="b.jpg" width="900" height="600"></div>
      <img src="right.jpg" width="900" height="600">
    </article>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/right.jpg"]


# ---------------------------------------------------------------------------------------------
# Void-element ancestor-stack leak fix. <img>/<source> are HTML5 void elements - written without
# a self-closing slash (the ordinary, common case), they never get a matching handle_endtag()
# call from html.parser.HTMLParser at all. Before this fix, handle_starttag() pushed EVERY tag
# (including void ones) onto the same ancestor stack used for priority/secondary-container
# tracking; a secondary-flagged <img> then stayed on that stack indefinitely (until some UNRELATED
# ancestor's later closing tag happened to truncate far enough to remove it), incorrectly marking
# every sibling element processed in between as "inside a secondary container" too. Confirmed
# empirically against the live parser before this fix (not assumed).
# ---------------------------------------------------------------------------------------------


def test_secondary_img_does_not_leak_onto_a_following_sibling_img() -> None:
    """The task's own minimal reproducer: a related-thumbnail <img>, written the ordinary
    (non-self-closed) way, must not poison the very next sibling <img> in the same container."""
    html = """
    <div class="article-entry">
      <div class="entry-body">

        <img
          class="related-thumbnail"
          src="wrong.jpg"
          width="800"
          height="600"
        >

        <img
          src="real-after-it.jpg"
          width="800"
          height="600"
        >

      </div>
    </div>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/real-after-it.jpg"]


def test_secondary_source_inside_picture_does_not_leak_onto_a_following_sibling_picture() -> None:
    """<source> is also a void element and is likewise pushed/checked via the same _try_add() path
    - a related-flagged <picture><source> must not poison a following sibling <picture>'s own
    <source>."""
    html = """
    <div class="entry-body">
      <picture class="related-teaser">
        <source srcset="wrong.jpg 800w">
        <img src="wrong-fallback.jpg" width="800" height="600">
      </picture>
      <picture>
        <source srcset="real.jpg 800w">
        <img src="real-fallback.jpg" width="800" height="600">
      </picture>
    </div>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/real.jpg"]


def test_self_closed_xhtml_style_img_is_also_unaffected() -> None:
    """A self-closed <img ... /> reaches handle_startendtag() (base class default: calls
    handle_starttag() then handle_endtag() immediately) - this path never leaked even before the
    fix, and must keep working identically after it."""
    html = """
    <div class="entry-body">
      <img class="related-thumbnail" src="wrong.jpg" width="800" height="600" />
      <img src="real.jpg" width="800" height="600" />
    </div>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    assert [h.remote_url for h in hints] == ["https://example.com/article/real.jpg"]


def test_many_siblings_after_a_secondary_img_all_survive() -> None:
    """Not just the immediate next sibling - the leak (before the fix) would have poisoned every
    sibling up until the enclosing element finally closed, however many there were."""
    html = """
    <div class="entry-body">
      <img class="related-thumbnail" src="wrong.jpg" width="800" height="600">
      <img src="a.jpg" width="800" height="600">
      <img src="b.jpg" width="800" height="600">
      <img src="c.jpg" width="800" height="600">
    </div>
    """
    hints = extract_inline_article_images(html, base_url=BASE_URL)
    urls = {h.remote_url for h in hints}
    assert urls == {
        "https://example.com/article/a.jpg",
        "https://example.com/article/b.jpg",
        "https://example.com/article/c.jpg",
    }
