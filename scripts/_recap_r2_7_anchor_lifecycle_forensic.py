"""NINJA PULSE RECAP Phase R2.7 - Story Anchor Lifecycle Forensic (READ ONLY).

DIAGNOSTIC ONLY. For every Story where the declared `first_event_id` is not among current
CONFIRMED members (`services.recap_event._CONFIRMED_MEMBERSHIP_MATCH_TYPES` -
NEW_STORY/STORY_UPDATE/SUPPORTING_SOURCE/SEMANTIC_DUPLICATE), reports exact forensic detail about
why, plus a pure, non-persisted hypothetical-anchor Story Integrity simulation.

ROOT CAUSE (proven offline this checkpoint - tests/test_recap_r2_7_anchor_lifecycle_forensic.py's
own Part 1, against real, unmodified `services/triage_orchestrator.py`/`services/recap_event.py`):
this is a CREATION-TIME semantic mismatch, never a later "staleness". `services/triage_orchestrator
.py::_apply_story_memory()` (Phase 20 M11.1, Story Identity Invariant) deliberately creates a new
Story with `first_event_id=event.id` for BOTH the `RELATED_STORY` outcome and a weak-entity-overlap
`UNCERTAIN_MATCH` outcome - already proven by the EXISTING, PASSING
`tests/test_story_identity_invariant.py::test_related_story_root_event_gets_its_own_story()`/
`test_uncertain_match_with_weak_entity_overlap_gets_its_own_story()`, which explicitly assert
`own_story.first_event_id == new_event.id` alongside `link.match_type == RELATED_STORY`/
`UNCERTAIN_MATCH` for that SAME event's own link. `services/recap_event.py::
_CONFIRMED_MEMBERSHIP_MATCH_TYPES` (written independently, for a different question - "is this a
confirmed continuation of the Story's own history") excludes both by design. Neither piece of code
is wrong in isolation; `services/event_recap.py::build_event_recap_candidate()` implicitly assumes
the two concepts coincide, which is false for exactly these two creation outcomes. No merge, no
member reclassification, and no link deletion exist anywhere in current production code (confirmed
by exhaustive grep this checkpoint - `NewsEventStoryLink` rows are write-once/immutable in
production: the only non-test constructor call is in `_apply_story_memory()` itself, and no
UPDATE/DELETE of `match_type` or the link table exists in `services/`, `worker/`, or
`capabilities/`) - so this diagnostic does not attempt to trace any such path; it exists to prove,
per-Story, that the declared anchor's own link (which DOES exist) simply never had a confirmed
match_type in the first place.

Does NOT modify `services/recap_event.py`, `services/story_memory.py`, `services/fact_safety.py`,
or `services/triage_orchestrator.py` - Story Integrity thresholds, the `first_event_id` production
write path, and clustering are all untouched and unmodified by this script.

Read-only safety pattern identical to every prior production-facing RECAP script this session: SET
TRANSACTION READ ONLY + SHOW transaction_read_only verification, SET LOCAL statement_timeout, one
transaction, rollback in finally, no writes, no network beyond the DB read, no LLM, no Telegram, no
worker. The hypothetical-anchor simulation (`simulate_hypothetical_anchor_integrity()`) calls the
REAL, frozen, unmodified `evaluate_recap_story_integrity()` - already a pure function over plain
NewsEvent objects - and never persists, flushes, or mutates any ORM object.

Use: `docker compose run --rm --no-deps backend python scripts/_recap_r2_7_anchor_lifecycle_forensic.py`
NOT executed by the author of this script - no VPS/production DB access this session.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
from dataclasses import dataclass  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from database.models.story_link import NewsEventStoryLink  # noqa: E402
from services.recap_event import (  # noqa: E402
    StoryIntegrityResult,
    _CONFIRMED_MEMBERSHIP_MATCH_TYPES,
    evaluate_recap_story_integrity,
    load_story_events,
)
from services.news_editorial_relevance import (  # noqa: E402
    ADJACENT,
    CORE,
    classify_editorial_relevance,
)

OUTPUT_PATH = Path("/tmp/recap_r2_7_anchor_lifecycle_forensic.txt")
STATEMENT_TIMEOUT_MS = 30_000

# Broader than R2.6's INSPECT_LIMIT=60 (this is specifically hunting anchor-missing Stories, not
# building a paid-shadow shortlist) - still bounded, never an unbounded scan.
SCAN_LIMIT = 1000
INSPECT_LIMIT = 300

_NEUTRAL_DEFAULT_RELEVANCE_REASON = "no editorial-relevance keyword evidence - neutral default"

# R2.7 item 22 - small, conservative, diagnostic-only "is this obviously AI/tech" signal, used
# ONLY to quantify how much the anchor-missing bucket actually contains real NINJA PULSE material
# (never production ranking, never wired into services/news_editorial_relevance.py). Calibrated
# against the exact example titles the overnight checkpoint itself listed as known neutral-default
# false negatives - deliberately short, EN/RU paired, never a giant taxonomy.
_OBVIOUS_AI_TECH_MARKERS: tuple[str, ...] = (
    "openai", "anthropic", "claude", "gemini", "alibaba qwen", "qwen", "yandex ai", "grok",
    "ai model", "ии-модель", "ai search", "ии-поиск", "ai video", "ии-видео",
    "ai training", "обучения ии", "ai feature", "ai update", "hugging face",
    "artificial intelligence", "искусственный интеллект", "искусственного интеллекта",
)


def obvious_ai_tech_signal(title: str) -> bool:
    """R2.7 item 22 - forensic-only, never production ranking. False negatives are acceptable
    (this only exists to quantify anchor-failure impact, per the checkpoint's own explicit "do not
    build a giant taxonomy" instruction)."""
    lowered = title.lower()
    return any(marker in lowered for marker in _OBVIOUS_AI_TECH_MARKERS)


def simulate_hypothetical_anchor_integrity(
    hypothetical_anchor: NewsEvent, confirmed_members: list[NewsEvent],
) -> StoryIntegrityResult:
    """R2.7 item 20 - pure, read-only simulation. Calls the REAL, frozen, unmodified
    `evaluate_recap_story_integrity()` directly (never reimplemented, never tuned) with a
    hypothetical anchor substituted in place of the Story's own (non-confirmed) declared
    first_event_id. `confirmed_members` must include `hypothetical_anchor` itself, matching the
    exact calling convention `build_event_recap_candidate()` itself already uses
    (`evaluate_recap_story_integrity(anchor, events)` where `events` includes the anchor - see that
    function's own docstring: it internally computes `others = [e for e in member_events if e.id
    != anchor_event.id]`). Never mutates `hypothetical_anchor`, any member, or persists anything -
    evaluate_recap_story_integrity() is already a pure function over plain NewsEvent objects, so no
    transient/synthetic object construction is needed at all."""
    return evaluate_recap_story_integrity(hypothetical_anchor, confirmed_members)


def earliest_confirmed_member(confirmed_members: list[NewsEvent]) -> NewsEvent:
    """The earliest-by-chronology confirmed member (published_at, falling back to collected_at -
    the same coalesce `load_story_events()` itself already orders by) - the HYPOTHETICAL_ANCHOR
    per R2.7 item 20. Forensic/simulation only, never applied to the real Story."""
    return min(confirmed_members, key=lambda e: e.published_at or e.collected_at)


def most_coherent_confirmed_member(confirmed_members: list[NewsEvent]) -> NewsEvent | None:
    """R2.7 item 21 - MOST_COHERENT_CONFIRMED_MEMBER: the confirmed member whose hypothetical-
    anchor Story Integrity coherence ratio (against the REST of the confirmed members, via the
    same real evaluate_recap_story_integrity()) is highest. Forensic only - never used in
    production logic (spec's own explicit instruction). None only when there are zero confirmed
    members at all."""
    if not confirmed_members:
        return None
    if len(confirmed_members) == 1:
        return confirmed_members[0]
    best_member: NewsEvent | None = None
    best_ratio = -1.0
    for candidate in confirmed_members:
        result = evaluate_recap_story_integrity(candidate, confirmed_members)
        raw_ratio = result.metrics.get("anchor_coherent_ratio", 0.0)
        ratio = raw_ratio if isinstance(raw_ratio, (int, float)) else 0.0
        if ratio > best_ratio:
            best_ratio = ratio
            best_member = candidate
    return best_member


@dataclass(frozen=True)
class RepairCandidate:
    """R2.7 Part V - the pure, diagnostic-only output of `simulate_repair_candidate()`. Never
    applied to any real Story; never persisted."""

    repair_candidate_anchor_id: UUID
    hypothetical_integrity: StoryIntegrityResult
    earliest_and_most_coherent_agree: bool


def simulate_repair_candidate(story: Story, confirmed_members: list[NewsEvent]) -> RepairCandidate:
    """R2.7 Part V (overnight checkpoint item 27) - PURE simulation only. Given a Story with a
    stale/missing confirmed anchor, answers "what would the deterministic repair candidate be" -
    using the ONLY rule proven safe by this checkpoint's own semantics investigation (earliest
    current confirmed member - see the checkpoint's own Part G repair-options discussion for why
    this is a simulation input, not a production decision). Does NOT mutate `story` or any member
    event, does NOT flush/commit, does NOT call it from any worker - a pure function over
    already-loaded data only."""
    anchor = earliest_confirmed_member(confirmed_members)
    integrity = simulate_hypothetical_anchor_integrity(anchor, confirmed_members)
    most_coherent = most_coherent_confirmed_member(confirmed_members)
    agree = most_coherent is not None and most_coherent.id == anchor.id
    return RepairCandidate(
        repair_candidate_anchor_id=anchor.id, hypothetical_integrity=integrity,
        earliest_and_most_coherent_agree=agree,
    )


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - the script refuses to run
    any query in that case."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


def _relevance_bucket(title: str) -> str:
    """CORE / genuine_adjacent / neutral_default / peripheral_or_out_of_scope - mirrors
    scripts/_recap_r2_6_broader_shadow_candidate_selection.py's own bucket logic (not imported,
    since that script is itself a standalone, non-package diagnostic - duplicated per this
    session's own established per-diagnostic-script convention)."""
    decision = classify_editorial_relevance(title)
    if decision.tier == CORE:
        return "CORE"
    if decision.tier == ADJACENT and decision.reason != _NEUTRAL_DEFAULT_RELEVANCE_REASON:
        return "genuine_adjacent"
    if decision.tier == ADJACENT:
        return "neutral_default"
    return "peripheral_or_out_of_scope"


async def _scan_anchor_missing_stories(session: AsyncSession) -> tuple[int, list[tuple[Story, list[NewsEvent]]]]:
    """Bounded scan (SCAN_LIMIT/INSPECT_LIMIT, same discipline as every prior R2 diagnostic) -
    returns (stories_scanned_count, [(story, confirmed_events), ...]) for every inspected Story
    whose declared first_event_id is NOT among its own confirmed members."""
    stmt = select(Story).order_by(Story.updated_at.desc()).limit(SCAN_LIMIT)
    stories = list((await session.execute(stmt)).scalars().all())[:INSPECT_LIMIT]
    missing: list[tuple[Story, list[NewsEvent]]] = []
    for story in stories:
        confirmed = await load_story_events(session, story.id)
        if story.first_event_id not in {e.id for e in confirmed}:
            missing.append((story, confirmed))
    return len(stories), missing


async def _declared_anchor_forensic(session: AsyncSession, story: Story) -> dict:
    """R2.7 items 17-19 - forensic-only detail about the declared (non-confirmed) anchor event
    itself: existence, all of its own current links (never inferring history the schema cannot
    prove - item 18's own explicit PROVEN/LIKELY/UNKNOWN discipline), and whether it currently
    belongs to another Story."""
    declared_id = story.first_event_id
    event_stmt = select(NewsEvent).where(NewsEvent.id == declared_id)
    declared_event = (await session.execute(event_stmt)).scalar_one_or_none()

    all_links_stmt = select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == declared_id)
    all_links = list((await session.execute(all_links_stmt)).scalars().all())

    other_story_links = [link for link in all_links if link.story_id != story.id]

    return {
        "declared_first_event_id": declared_id,
        "exists_in_db": declared_event is not None,
        "event": declared_event,
        "all_current_links": all_links,
        "other_story_links": other_story_links,
    }


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            stories_scanned, missing = await _scan_anchor_missing_stories(session)
            lines = [
                "NINJA PULSE RECAP Phase R2.7 - Story Anchor Lifecycle Forensic (READ ONLY)",
                f"Stories scanned: {stories_scanned} (bounded, most-recently-updated first, cap {INSPECT_LIMIT})",
                f"Anchor-missing Stories found: {len(missing)}",
                "",
            ]

            agg: dict = {
                "declared_anchor_exists_in_db": 0, "declared_anchor_missing_from_db": 0,
                "current_other_story_link_count": 0, "no_current_other_story_link_count": 0,
                "hypothetical_earliest_anchor_PASS": 0, "hypothetical_earliest_anchor_FAIL": 0,
                "obvious_ai_tech_missing_anchor_count": 0,
                "CORE": 0, "genuine_adjacent": 0, "neutral_default": 0, "peripheral_or_out_of_scope": 0,
                "unknown": 0,
            }

            for story, confirmed in missing:
                forensic = await _declared_anchor_forensic(session, story)
                bucket = _relevance_bucket(story.title)
                agg[bucket] = agg.get(bucket, 0) + 1
                ai_tech = obvious_ai_tech_signal(story.title)
                if ai_tech:
                    agg["obvious_ai_tech_missing_anchor_count"] += 1

                lines += [
                    f"Story {story.id}: {story.title!r}",
                    f"  story_created_at={story.created_at} story_updated_at={story.updated_at}",
                    f"  declared_first_event_id={forensic['declared_first_event_id']}",
                    f"  relevance_bucket={bucket} obvious_ai_tech_signal={ai_tech}",
                ]

                if forensic["exists_in_db"]:
                    agg["declared_anchor_exists_in_db"] += 1
                    event = forensic["event"]
                    lines += [
                        f"  declared_event: exists_in_db=True title={event.title!r} "
                        f"source_id={event.source_id} published_at={event.published_at} "
                        f"created_at={event.collected_at} updated_at={event.updated_at}",
                    ]
                else:
                    agg["declared_anchor_missing_from_db"] += 1
                    lines.append("  declared_event: exists_in_db=False (PROVEN absent from news_events)")

                lines.append(f"  ALL current links for declared event ({len(forensic['all_current_links'])}):")
                for link in forensic["all_current_links"]:
                    lines.append(
                        f"    story_id={link.story_id} match_type={link.match_type} "
                        f"confirmed={link.match_type in _CONFIRMED_MEMBERSHIP_MATCH_TYPES} "
                        f"match_score={link.match_score} created_at={link.created_at}"
                    )
                if not forensic["all_current_links"]:
                    lines.append("    (no link rows exist for this event at all - UNKNOWN/PROVEN-absent, see membership-history limitation note)")

                if forensic["other_story_links"]:
                    agg["current_other_story_link_count"] += 1
                    lines.append(f"  OTHER-STORY relationship: PROVEN - belongs to {[str(link.story_id) for link in forensic['other_story_links']]}")
                else:
                    agg["no_current_other_story_link_count"] += 1
                    lines.append("  OTHER-STORY relationship: NO CURRENT OTHER-STORY LINK FOUND (not the same as 'never belonged elsewhere' - UNKNOWN prior history)")

                lines.append(f"  Current confirmed members ({len(confirmed)}):")
                for e in confirmed:
                    lines.append(f"    event_id={e.id} title={e.title!r} published_at={e.published_at}")

                if confirmed:
                    hypothetical_anchor = earliest_confirmed_member(confirmed)
                    hypothetical = simulate_hypothetical_anchor_integrity(hypothetical_anchor, confirmed)
                    if hypothetical.eligible:
                        agg["hypothetical_earliest_anchor_PASS"] += 1
                    else:
                        agg["hypothetical_earliest_anchor_FAIL"] += 1
                    most_coherent = most_coherent_confirmed_member(confirmed)
                    lines += [
                        "  CURRENT: FAIL - first_event_id absent from confirmed members",
                        f"  HYPOTHETICAL_ANCHOR: {hypothetical_anchor.id} ({hypothetical_anchor.title!r})",
                        f"  HYPOTHETICAL Story Integrity: {'PASS' if hypothetical.eligible else 'FAIL'} "
                        f"reasons={hypothetical.reasons}",
                        f"  member_coherence_ratio={hypothetical.metrics.get('anchor_coherent_ratio')}",
                        f"  MOST_COHERENT_CONFIRMED_MEMBER={most_coherent.id if most_coherent else None} "
                        f"(same_as_earliest={most_coherent.id == hypothetical_anchor.id if most_coherent else False})",
                    ]
                else:
                    lines += [
                        "  CURRENT: FAIL - first_event_id absent from confirmed members",
                        "  HYPOTHETICAL_ANCHOR: none available - zero confirmed members at all",
                    ]
                lines.append("")

            lines += [
                "=" * 100, "AGGREGATE METRICS", "=" * 100,
                f"stories_scanned={stories_scanned}",
                f"missing_anchor_total={len(missing)}",
                f"declared_anchor_exists_in_db={agg['declared_anchor_exists_in_db']}",
                f"declared_anchor_missing_from_db={agg['declared_anchor_missing_from_db']}",
                f"current_other_story_link_count={agg['current_other_story_link_count']}",
                f"no_current_other_story_link_count={agg['no_current_other_story_link_count']}",
                f"hypothetical_earliest_anchor_PASS={agg['hypothetical_earliest_anchor_PASS']}",
                f"hypothetical_earliest_anchor_FAIL={agg['hypothetical_earliest_anchor_FAIL']}",
                f"obvious_ai_tech_missing_anchor_count={agg['obvious_ai_tech_missing_anchor_count']}",
                f"CORE={agg['CORE']} genuine_adjacent={agg['genuine_adjacent']} "
                f"neutral_default={agg['neutral_default']} "
                f"peripheral_or_out_of_scope={agg['peripheral_or_out_of_scope']} unknown={agg['unknown']}",
            ]

            OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote {OUTPUT_PATH} (missing_anchor_total={len(missing)})")
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
