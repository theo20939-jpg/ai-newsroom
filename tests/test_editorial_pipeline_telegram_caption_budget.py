"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S19/S28-D/S35: the caption-too-long replay.

Required outcome (S28-D): "never finished text-only merely due to caption limit." This directly
supersedes the previous phase's own preserved, disclosed Phase 23.1H/23.1Q tradeoff for the NEW
pipeline specifically (S18's V8 freeze keeps the OLD, currently-deployed path's behavior
unchanged - see platforms/telegram.py's own module docstring).
"""
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from services.editorial_pipeline.contracts import RecoveryReasonCode
from services.editorial_pipeline.platforms.telegram import plan_telegram_caption_budget
from services.news_telegram_presentation import build_ninja_pulse_footer_html


def _long_html(body_units: int, *, with_footer: bool) -> str:
    body = "<b>Заголовок</b>\n" + ("А" * body_units)
    if with_footer:
        body = body + "\n" + build_ninja_pulse_footer_html()
    return body


def test_a_caption_that_fits_is_sent_as_is_no_visual_dropped() -> None:
    html = _long_html(200, with_footer=True)
    plan = plan_telegram_caption_budget(html, has_visual=True)
    assert plan.fits is True
    assert plan.caption == html
    assert plan.footer_dropped is False


def test_dropping_only_the_non_factual_footer_can_recover_the_budget() -> None:
    # Sized so the full text (with footer) exceeds the limit, but the body alone (footer removed)
    # fits - proving the footer, not factual content, is what gets trimmed first.
    footer_len = len(build_ninja_pulse_footer_html())
    body_units = CAPTION_SAFE_LIMIT - 20  # comfortably fits alone
    html = _long_html(body_units, with_footer=True)
    assert len(html.encode("utf-16-le")) // 2 > CAPTION_SAFE_LIMIT  # confirm the fixture is actually over budget

    plan = plan_telegram_caption_budget(html, has_visual=True)

    assert plan.fits is True
    assert plan.footer_dropped is True
    assert plan.caption is not None
    assert "NINJA PULSE" not in plan.caption
    assert "А" * body_units in plan.caption  # every character of factual body copy survives whole


def test_even_the_footer_stripped_caption_still_too_long_holds_never_drops_the_visual_as_text() -> None:
    html = _long_html(CAPTION_SAFE_LIMIT + 500, with_footer=True)  # body alone already over budget
    plan = plan_telegram_caption_budget(html, has_visual=True)

    assert plan.fits is False
    assert plan.caption is None
    assert plan.recovery_reason == RecoveryReasonCode.CAPTION_BUDGET_FAILED
    # Critically: this is a HOLD signal, not a text-only send - the orchestrator (S25) must route
    # this to recovery, never to send_to_editorial_destination() with the full text and no photo.


def test_text_only_paths_are_not_subject_to_the_photo_caption_limit_at_all() -> None:
    """S4-C's own carve-out (system/operator/explicit text-only) - has_visual=False means this
    function is not even the right budget check (plain messages get Telegram's much larger 4096-
    unit limit) - it must never HOLD a genuinely text-only message."""
    html = _long_html(2000, with_footer=False)
    plan = plan_telegram_caption_budget(html, has_visual=False)
    assert plan.fits is True
    assert plan.recovery_reason is None
