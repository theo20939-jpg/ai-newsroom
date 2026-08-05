"""Phase 18.6 - read-only meme opportunity calibration packet generator (docs/
phase18_6_meme_calibration_report.md).

Reads already-persisted `NewsEvent` rows directly (SELECT only - no INSERT/UPDATE/DELETE anywhere
in this file) and runs the existing, unmodified `services.meme_opportunity.
assess_meme_opportunity()` classifier against each one via `services.meme_shadow_analytics.
evaluate_event_shadow()` (Phase 18.5 - reused as-is, not re-implemented). Selects three groups
(Group A: up to 20 `MEDIUM` candidates, sampled for maximum category diversity; Group B: up to 20
random `LOW` examples; Group C: up to 10 random safety-`BLOCKED` examples) via `services.
meme_calibration`'s pure selection functions, then writes:

- `scripts/phase18_6_calibration_dataset.json` - the machine-readable calibration dataset, every
  `human_*` field genuinely blank.
- `docs/phase18_6_human_review_packet.md` - the same dataset rendered as a human-readable packet.

Does not import `capabilities.executor`, `workflows.runner`, `bot`, or any LLM Gateway module -
this script cannot make an LLM call, an image-generation call, or a Telegram send even by
accident (verified by `tests/test_phase18_6_meme_calibration.py`'s own import-boundary check,
mirroring Phase 18.5's own precedent). Never writes to the database.

Usage: `python scripts/phase18_6_generate_calibration_packet.py [--limit N]`
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from schemas.meme_calibration import MemeCalibrationDataset
from schemas.meme_shadow_analytics import MemeOpportunityLabel, MemeShadowRecord
from services.meme_calibration import (
    build_calibration_record,
    build_dataset,
    render_markdown_packet,
    select_diverse_by_category,
    select_random,
)
from services.meme_shadow_analytics import evaluate_event_shadow

_DATASET_PATH = Path(__file__).parent / "phase18_6_calibration_dataset.json"
_PACKET_PATH = Path(__file__).parent.parent / "docs" / "phase18_6_human_review_packet.md"

_GROUP_A_SIZE = 20
_GROUP_B_SIZE = 20
_GROUP_C_SIZE = 10
_SELECTION_SEED = 18.6


async def _collect_shadow_records(
    limit: int | None = None,
) -> tuple[list[MemeShadowRecord], dict[str, NewsEvent]]:
    now = datetime.now(timezone.utc)
    records: list[MemeShadowRecord] = []
    events_by_id: dict[str, NewsEvent] = {}

    async with async_session_factory() as session:
        stmt = (
            select(NewsEvent, NewsSource.name)
            .join(NewsSource, NewsEvent.source_id == NewsSource.id)
            .order_by(NewsEvent.published_at.desc().nulls_last())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        for event, source_name in result.all():
            record = evaluate_event_shadow(
                event.id, event.title, event.content, event.category, event.published_at,
                source_name, now=now,
            )
            if record is not None:
                records.append(record)
                events_by_id[record.event_id] = event

    return records, events_by_id


def _select_groups(records: list[MemeShadowRecord]) -> list[MemeShadowRecord]:
    by_label: dict[MemeOpportunityLabel, list[MemeShadowRecord]] = {label: [] for label in MemeOpportunityLabel}
    for record in records:
        by_label[record.opportunity_label].append(record)

    group_a = select_diverse_by_category(by_label[MemeOpportunityLabel.MEDIUM], _GROUP_A_SIZE, seed=_SELECTION_SEED)
    group_b = select_random(by_label[MemeOpportunityLabel.LOW], _GROUP_B_SIZE, seed=_SELECTION_SEED)
    group_c = select_random(by_label[MemeOpportunityLabel.BLOCKED], _GROUP_C_SIZE, seed=_SELECTION_SEED)
    return [*group_a, *group_b, *group_c]


async def generate(limit: int | None = None) -> MemeCalibrationDataset:
    shadow_records, events_by_id = await _collect_shadow_records(limit=limit)
    selected = _select_groups(shadow_records)

    calibration_records = [
        build_calibration_record(
            shadow_record,
            title=events_by_id[shadow_record.event_id].title,
            content=events_by_id[shadow_record.event_id].content,
            published_at=events_by_id[shadow_record.event_id].published_at,
        )
        for shadow_record in selected
    ]
    return build_dataset(calibration_records)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of NewsEvent rows to scan")
    args = parser.parse_args()

    dataset = await generate(limit=args.limit)
    _DATASET_PATH.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    _PACKET_PATH.write_text(render_markdown_packet(dataset), encoding="utf-8")

    print(
        f"Group A (MEDIUM): {dataset.group_a_count}, Group B (LOW): {dataset.group_b_count}, "
        f"Group C (BLOCKED): {dataset.group_c_count}"
    )
    print(f"Written dataset to {_DATASET_PATH}")
    print(f"Written packet to {_PACKET_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
