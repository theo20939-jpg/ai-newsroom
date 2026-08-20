"""NINJA PULSE RECAP Phase R2.8 - Story Anchor Repair Shadow (SCAFFOLD/DESIGN ONLY, READ ONLY).

DEPRECATED - NOT CANONICAL. Superseded by
`scripts/_recap_r2_8_origin_membership_semantics_shadow.py`, written AFTER R2.7's real production
forensic (this file predates that evidence - see its own module docstring's "R2.7 recap" section
for the two production-proven facts this file's own design never accounted for: (1) `_apply_story_
memory()`'s `match_type` on the NEWLY-created Story's own link is copied unchanged from the
classification against the OLD candidate Story it was scored against, a real semantic-context
question this file's HYPOTHETICAL model never investigates at all; (2) this file's own
`transient_story_with_anchor()` + real `build_event_recap_candidate()` combination can express an
anchor SWAP among EXISTING confirmed members only - it structurally CANNOT express "the origin
event becomes its own extra member," because `build_event_recap_candidate()` always re-derives its
member-event list via a live `load_story_events(session, story.id)` DB query tied to the real,
unchanged link rows, which can never be made to include a non-confirmed link no matter what
`first_event_id` the transient Story copy declares). Retained, unmodified, only as forensic
history of the pre-R2.7-evidence design - not deleted (nothing else in this codebase imports it),
not run this checkpoint either. Use the canonical file above for any future R2.8 production
mounting.

Everything below this point is the ORIGINAL, unmodified pre-R2.7 scaffold text.

NOT a fully-authorized production diagnostic checkpoint yet - prepared per the overnight
autonomous checkpoint's own explicit "prepare, but DO NOT execute, the next logical development
checkpoint... design/tooling only" instruction (Part IX). Do not treat this as equivalent in
review status to scripts/_recap_r2_6_*.py or scripts/_recap_r2_7_*.py - those went through their
own dedicated checkpoints; this file exists so the NEXT checkpoint has working scaffolding ready,
not because anchor repair has been authorized.

Compares, for every Story where the declared `first_event_id` is not among current confirmed
members (the exact same population `scripts/_recap_r2_7_anchor_lifecycle_forensic.py` finds):

    CURRENT   - the real build_event_recap_candidate() result against the Story exactly as it is
                today (always rejected, fail-closed - see services/event_recap.py's own anchor-
                missing branch).
    HYPOTHETICAL - build_event_recap_candidate() against a TRANSIENT, NEVER-PERSISTED, in-memory
                only copy of the same Story with first_event_id swapped to the earliest current
                confirmed member (services/recap_event.py's own R1.5A.2 correction already
                establishes this is NOT a production-safe substitution to apply automatically -
                see that function's own docstring on why blind fallback-to-events[0] was reverted;
                this script uses the same substitution ONLY for a non-persisted, read-only
                comparison, never as a decision).

Never writes: the transient Story copy is a plain, unpersisted `Story(...)` instance (never
`session.add()`-ed, never flushed) - `build_event_recap_candidate()` itself performs zero writes
regardless (module docstring: "requires zero LLM/Gateway calls and zero network access"). Read-only
transaction guard, rollback, statement timeout - identical pattern to every prior R2 diagnostic.

Does NOT modify services/recap_event.py, services/story_memory.py, services/fact_safety.py,
services/event_recap.py, or services/triage_orchestrator.py. Does NOT decide or recommend which
repair option to implement - that decision remains Part IV/Part G of the overnight report's own
job, not this tool's.

Use: `docker compose run --rm --no-deps backend python scripts/_recap_r2_8_anchor_repair_shadow_scaffold.py`
NOT executed by the author of this script - no VPS/production DB access this session.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.event_recap import build_event_recap_candidate  # noqa: E402

OUTPUT_PATH = Path("/tmp/recap_r2_8_anchor_repair_shadow_scaffold.txt")
STATEMENT_TIMEOUT_MS = 30_000


def transient_story_with_anchor(story: Story, hypothetical_anchor_id) -> Story:  # noqa: ANN001
    """Pure, in-memory only - a plain, unpersisted Story object with the SAME id (so
    build_event_recap_candidate()'s own `load_story_events(session, story.id)` call loads the
    real, unchanged confirmed-member set) but `first_event_id` swapped to the hypothetical anchor.
    Never `session.add()`-ed; never flushed; never affects the real, passed-in `story` object at
    all (a NEW instance, not a mutation of `story`)."""
    return Story(
        id=story.id, title=story.title, category=story.category, entities=story.entities,
        keywords=story.keywords, topic_bucket=story.topic_bucket, first_event_id=hypothetical_anchor_id,
        event_count=story.event_count, created_at=story.created_at, updated_at=story.updated_at,
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


async def compare_current_vs_hypothetical(session: AsyncSession, story: Story) -> list[str]:
    """For one anchor-missing Story: real CURRENT result (always rejected today) vs HYPOTHETICAL
    result (transient anchor swap, never persisted). Read only - two build_event_recap_candidate()
    calls, zero writes."""
    lines = [f"Story {story.id}: {story.title!r}"]

    current = await build_event_recap_candidate(session, story, force_shadow=True)
    lines.append(f"  CURRENT: rejected={current.rejected} reasons={current.rejection_reasons}")

    r27 = _load_r27_module()
    from services.recap_event import load_story_events

    confirmed = await load_story_events(session, story.id)
    if not confirmed:
        lines.append("  HYPOTHETICAL: skipped - zero confirmed members, no anchor candidate exists")
        lines.append("")
        return lines

    hypothetical_anchor = r27.earliest_confirmed_member(confirmed)
    transient_story = transient_story_with_anchor(story, hypothetical_anchor.id)
    hypothetical = await build_event_recap_candidate(session, transient_story, force_shadow=True)

    if hypothetical.candidate is None:
        lines.append(f"  HYPOTHETICAL: rejected={hypothetical.rejected} reasons={hypothetical.rejection_reasons}")
    else:
        c = hypothetical.candidate
        lines += [
            f"  HYPOTHETICAL: story_integrity_eligible={c.story_integrity_eligible} "
            f"announcement_count={c.announcement_count} timeline_count={len(c.timeline)} "
            f"verified_facts={len(c.verified_facts)}",
            f"  HYPOTHETICAL RECAP eligibility (force_shadow candidate built): YES "
            f"(readiness_state={c.readiness_state}, still shadow-only, publishable={c.publishable})",
        ]
    lines.append("")
    return lines


def _load_r27_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_recap_r2_7_for_r2_8_scaffold", "scripts/_recap_r2_7_anchor_lifecycle_forensic.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def main() -> None:
    """NOT executed this session - scaffolding only, prepared for a future, separately-authorized
    R2.8 checkpoint. Read-only, zero writes, zero LLM, zero paid calls."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            r27 = _load_r27_module()
            stories_scanned, missing = await r27._scan_anchor_missing_stories(session)

            lines = [
                "NINJA PULSE RECAP Phase R2.8 SCAFFOLD - CURRENT vs HYPOTHETICAL anchor repair (READ ONLY)",
                f"Stories scanned: {stories_scanned}  Anchor-missing found: {len(missing)}",
                "",
            ]
            for story, _confirmed in missing:
                lines += await compare_current_vs_hypothetical(session, story)

            OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote {OUTPUT_PATH} (missing_anchor_total={len(missing)})")
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
