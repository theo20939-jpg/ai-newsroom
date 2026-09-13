"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S25/S26/S27/S35: the shadow-comparison entrypoint.

Confirms: never raises even when the new pipeline itself errors (S4-E/S27 - a shadow-mode bug must
never surface anywhere the legacy path can see it); the passthrough renderer performs no new render
work; and the comparison logs a real, structured event (S32) rather than nothing."""
from uuid import uuid4

import pytest

from services.editorial_pipeline.shadow import build_passthrough_render, run_shadow_comparison

pytestmark = pytest.mark.asyncio


async def test_shadow_comparison_never_raises_even_on_internal_failure(caplog) -> None:
    async def broken_render(composition_plan, structured_content):
        raise RuntimeError("simulated internal pipeline bug")

    with caplog.at_level("WARNING"):
        await run_shadow_comparison(
            content_draft_id=uuid4(), news_event_id=uuid4(), story_id=None, source_url=None,
            title="Some title", main_body="Some body", research_facts=[],
            legacy_presentation_type="NEWS", legacy_had_visual=True, render=broken_render,
        )  # must not raise

    assert any(r.msg == "shadow_comparison_failed" for r in caplog.records)


async def test_shadow_comparison_logs_agreement_when_new_pipeline_matches_legacy(caplog) -> None:
    photo_input = "cached-file-id"
    html = "<b>Заголовок</b>\nТело новости."
    render = build_passthrough_render(photo_input, html)

    with caplog.at_level("INFO"):
        await run_shadow_comparison(
            content_draft_id=uuid4(), news_event_id=uuid4(), story_id=None, source_url=None,
            title="Заголовок", main_body="Тело новости.", research_facts=["real fact"],
            legacy_presentation_type="NEWS", legacy_had_visual=True, render=render,
        )

    comparison = next(r for r in caplog.records if r.msg == "shadow_comparison")
    assert comparison.new_pipeline_ready is True
    assert comparison.agrees_with_legacy is True


async def test_passthrough_render_performs_no_new_rendering() -> None:
    render = build_passthrough_render("photo-x", "html-y")
    result = await render(composition_plan=object(), structured_content=object())
    assert result == ("photo-x", "html-y")
