"""Phase 19 M2: pure, tier-1 unit tests for services.article_cleaning - no DB, no network."""
from services.article_cleaning import clean_extracted_text, reconcile_status, CleaningResult


def test_removes_cookie_notice() -> None:
    raw = "Real article paragraph one with substantial content about the story.\nWe use cookies to improve your experience.\nReal article paragraph two continues the story."
    result = clean_extracted_text(raw)
    assert "cookies" not in result.cleaned_text.lower()
    assert "paragraph one" in result.cleaned_text
    assert "paragraph two" in result.cleaned_text
    assert "cookie_notice" in result.cleaning_reasons


def test_removes_subscription_prompt() -> None:
    raw = "Real article paragraph about the actual news story here.\nSubscribe to our newsletter for daily updates.\nMore real article content follows this point."
    result = clean_extracted_text(raw)
    assert "subscribe to our newsletter" not in result.cleaned_text.lower()
    assert "subscription_prompt" in result.cleaning_reasons


def test_removes_advertisement_label() -> None:
    raw = "First real paragraph of the article with real content.\nAdvertisement\nSecond real paragraph continuing the article's content."
    result = clean_extracted_text(raw)
    assert "advertisement_label" in result.cleaning_reasons


def test_removes_related_stories_block() -> None:
    raw = "Real paragraph with substantial article content here.\nRelated articles you might enjoy reading next.\nAnother real paragraph with more article content."
    result = clean_extracted_text(raw)
    assert "related_stories" in result.cleaning_reasons


def test_removes_sharing_controls() -> None:
    raw = "Substantial real article paragraph with genuine content.\nShare this article on Facebook and Twitter now.\nAnother substantial real paragraph of content."
    result = clean_extracted_text(raw)
    assert "sharing_controls" in result.cleaning_reasons


def test_removes_comment_prompt() -> None:
    raw = "Genuine article paragraph discussing the real news story.\nLeave a comment below to join the discussion.\nAnother genuine paragraph of real article content."
    result = clean_extracted_text(raw)
    assert "comment_prompt" in result.cleaning_reasons


def test_removes_navigation_footer_cluster() -> None:
    nav_blocks = ["Home", "News", "Sports", "Tech", "About"]
    real_paragraphs = [
        f"This is real article paragraph number {i} with substantial genuine content about the news story being reported here today in detail."
        for i in range(6)
    ]
    raw = "\n".join(nav_blocks) + "\n" + "\n".join(real_paragraphs)
    result = clean_extracted_text(raw)
    assert "navigation_or_footer_cluster" in result.cleaning_reasons
    assert "real article paragraph number 0" in result.cleaned_text
    assert "Home" not in result.cleaned_text


def test_removes_author_bio_after_byline() -> None:
    raw = "By Jane Doe\nJane Doe is a staff writer covering technology.\nThe actual article begins here with real substantive content about the news."
    result = clean_extracted_text(raw)
    assert "author_bio_boilerplate" in result.cleaning_reasons
    assert "actual article begins here" in result.cleaned_text


def test_removes_repeated_headline() -> None:
    title = "Company Announces New Product Launch Today"
    raw = f"{title}\nThe company held a press event to detail the new product's features and pricing."
    result = clean_extracted_text(raw, title=title)
    assert "repeated_headline" in result.cleaning_reasons
    assert "press event" in result.cleaned_text


def test_repeated_headline_skipped_without_title() -> None:
    raw = "Company Announces New Product Launch Today\nThe company held a press event."
    result = clean_extracted_text(raw, title=None)
    assert "repeated_headline" not in result.cleaning_reasons


def test_removes_repeated_image_caption() -> None:
    raw = "The real article paragraph describing the news event in full detail here.\nPhoto: Jane Smith/Agency\nAnother real paragraph of substantive article content follows."
    result = clean_extracted_text(raw)
    assert "repeated_image_caption" in result.cleaning_reasons


def test_removes_legal_disclaimer() -> None:
    raw = "Genuine article paragraph about the real news story reported today.\nAll rights reserved. Terms of service apply to this content.\nAnother genuine paragraph continuing the real article."
    result = clean_extracted_text(raw)
    assert "legal_disclaimer_unrelated" in result.cleaning_reasons


def test_removes_newsletter_promotion() -> None:
    raw = "Real substantive article paragraph discussing the actual news event.\nGet our newsletter delivered to your inbox daily.\nAnother real substantive paragraph of article content."
    result = clean_extracted_text(raw)
    assert "newsletter_promotion" in result.cleaning_reasons


def test_removes_signup_block() -> None:
    raw = "Real article paragraph with genuine substantive content about news.\nSign up for a free account to continue reading.\nAnother real paragraph with genuine substantive content."
    result = clean_extracted_text(raw)
    assert "signup_block" in result.cleaning_reasons


def test_removes_read_also_block() -> None:
    raw = "Real paragraph describing the actual news story in detail.\nRead also: another related story on this topic.\nAnother real paragraph describing more of the story."
    result = clean_extracted_text(raw)
    assert "read_also" in result.cleaning_reasons


def test_never_removes_majority_of_a_genuine_article() -> None:
    """Conservative guard: a rule that would remove most of a real article's blocks is skipped
    rather than applied - a false-positive protection, not just a happy-path claim."""
    paragraphs = [f"This is real paragraph number {i} with genuine substantive news content about the ongoing story." for i in range(10)]
    raw = "\n".join(paragraphs)
    result = clean_extracted_text(raw)
    # None of these paragraphs should trigger any phrase rule, and the nav/footer cluster rule
    # should not fire either (each paragraph exceeds the short-block threshold).
    assert result.cleaned_char_count > result.raw_extracted_char_count * 0.9


def test_conservative_guard_skips_rule_that_would_remove_majority() -> None:
    """When a rule's matches would remove more than half the article's blocks, it is skipped
    entirely (not partially applied) - the concrete conservative-safety mechanism, not just a
    documentation claim."""
    nav_blocks = ["Home", "News", "Sports", "Tech", "About"]
    raw = "\n".join(nav_blocks) + "\nOne short real paragraph."
    result = clean_extracted_text(raw)
    assert "navigation_or_footer_cluster_skipped_would_remove_majority" in result.cleaning_reasons
    assert "Home" in result.cleaned_text  # skipped, not removed


def test_empty_input_produces_empty_result() -> None:
    result = clean_extracted_text("")
    assert result.cleaned_text == ""
    assert result.removed_block_count == 0
    assert result.cleaning_reasons == []


def test_cleaning_version_is_stamped() -> None:
    result = clean_extracted_text("Some real article content that is long enough to survive cleaning intact.")
    assert result.cleaning_version == "1"


def test_reconcile_status_downgrades_low_confidence_full_text() -> None:
    cleaning_result = CleaningResult(
        cleaned_text="short", raw_extracted_char_count=10000, cleaned_char_count=100,
        removed_block_count=50,
    )
    assert reconcile_status("FULL_TEXT", cleaning_result) == "PARTIAL_TEXT"


def test_reconcile_status_keeps_high_confidence_full_text() -> None:
    cleaning_result = CleaningResult(
        cleaned_text="x" * 9000, raw_extracted_char_count=10000, cleaned_char_count=9000,
        removed_block_count=2,
    )
    assert reconcile_status("FULL_TEXT", cleaning_result) == "FULL_TEXT"


def test_reconcile_status_never_touches_non_text_statuses() -> None:
    cleaning_result = CleaningResult(
        cleaned_text="", raw_extracted_char_count=0, cleaned_char_count=0, removed_block_count=0,
    )
    assert reconcile_status("FETCH_FAILED", cleaning_result) == "FETCH_FAILED"
    assert reconcile_status("HEADLINE_ONLY", cleaning_result) == "HEADLINE_ONLY"
