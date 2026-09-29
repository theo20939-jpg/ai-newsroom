"""Focused offline proofs for the one-shot KAGE controlled-delivery entrypoint."""
from pathlib import Path

import pytest
from sqlalchemy import select

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.story_link import NewsEventStoryLink
from scripts import _kage_telegram_controlled_delivery as controlled
from tests.test_content_worker_cycle import factory, test_source  # noqa: F401


def test_runner_is_bound_to_one_event_and_never_invokes_natural_selection() -> None:
    source = Path(controlled.__file__).read_text(encoding="utf-8")
    assert str(controlled.EVENT_ID) == "db748bb0-b41b-4a21-9679-7bd3262a749c"
    assert "event_ids_override=[EVENT_ID]" in source
    assert "_select_eligible_events" not in source
    assert "send_to_editorial_destination" not in source
    assert "bot.send_photo(" not in source


def test_visual_loader_accepts_only_the_frozen_founder_reviewed_artifact() -> None:
    visual = controlled._load_visual()
    assert (visual.width, visual.height) == controlled.EXPECTED_VISUAL_SIZE
    assert visual.sha256 == controlled.EXPECTED_VISUAL_SHA256
    assert visual.compliance_decision == "COMPLIANT"


@pytest.mark.asyncio
async def test_saved_fixture_seed_is_exact_idempotent_and_reuses_upstream_evidence(factory) -> None:
    fixture = controlled._load_fixture()
    first = await controlled.seed_saved_story(factory, fixture)
    second = await controlled.seed_saved_story(factory, fixture)
    assert first == second
    assert first["event_id"] == str(controlled.EVENT_ID)

    async with factory() as session:
        event = await session.get(NewsEvent, controlled.EVENT_ID)
        link = await session.get(NewsEventStoryLink, controlled.EVENT_ID)
        analysis = await session.scalar(
            select(EditorialTask).where(
                EditorialTask.event_id == controlled.EVENT_ID,
                EditorialTask.workflow["workflow_name"].as_string() == "NEWS_ANALYSIS",
            )
        )
    assert event is not None and event.title == fixture["source_headline"]
    assert link is not None and str(link.story_id) == first["story_id"]
    assert analysis is not None and analysis.status == TaskStatus.COMPLETED
    results = {item["step_name"]: item["result"] for item in analysis.workflow["step_results"]}
    assert results == {"research": fixture["research"], "intelligence": fixture["intelligence"]}
