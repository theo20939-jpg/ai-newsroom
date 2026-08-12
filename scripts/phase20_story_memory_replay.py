"""Phase 20 M11: historical replay + calibration for Story Memory V2.

Replays several real, consecutive days of *actual* historical `NewsEvent` rows (title/category/
published_at/collected_at only - read-only `SELECT` against the real database, never mutating it)
chronologically through the V2 matcher (services/story_memory.py) + Delta Engine (services/
story_delta_engine.py) + confidence bands (services/story_confidence.py) + suppression proposal
layer (services/story_suppression.py), persisting results into a disposable, throwaway Postgres
container (never the real database). Mirrors the exact disposable-DB technique independently
proven safe in docs/phase19_activation_review.md §3 (`docker run postgres:16` on an isolated
port, `alembic upgrade head`, verify, destroy) - zero paid LLM calls (the matcher/delta engine are
fully deterministic), zero Telegram, zero production mutation.

Launch with:
    python -m scripts.phase20_story_memory_replay
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings as real_settings
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from services.story_confidence import compute_confidence_band
from services.story_delta_engine import compute_story_delta, gate_delta_by_identity
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_MATCH_CANDIDATE_LIMIT,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    _fetch_candidate_stories,
    _preselect_candidates,
    match_story,
    score_candidate,
)
from services.story_memory import _RELATED_STORY_ENTITY_FLOOR as _OWN_STORY_ENTITY_FLOOR
from services.story_suppression import compute_would_suppress

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "phase20_calibration_cases.json"
OUTPUT_JSON = REPO_ROOT / "artifacts" / "phase20_m11_replay_results.json"

# Several real, consecutive days (not another 15-minute burst) - includes 2026-08-07, the exact
# date of every real calibration case (kitesurf/ai_olympiad_cluster/moscow_student_pair/
# gta_negative_control), so those cases are replayed under REALISTIC candidate volume/noise
# rather than the isolated single-candidate unit tests in tests/test_story_memory_v2.py.
REPLAY_START = datetime(2026, 8, 4, tzinfo=timezone.utc)
REPLAY_END = datetime(2026, 8, 8, tzinfo=timezone.utc)  # exclusive

DISPOSABLE_CONTAINER_NAME = "phase20_m11_replay_pg"
DISPOSABLE_PORT = 55433
DISPOSABLE_PASSWORD = "phase20_replay"
DISPOSABLE_DB = "phase20_replay"

_SAME_STORY_OUTCOMES = (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE, UNCERTAIN_MATCH)
_EVENT_COUNT_BUMP_OUTCOMES = (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE)
_MAX_SUPPRESSION_EXAMPLES = 25


# --- disposable Postgres lifecycle (mirrors docs/phase19_activation_review.md §3) -----------


def _start_disposable_postgres() -> None:
    subprocess.run(["docker", "rm", "-f", DISPOSABLE_CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", DISPOSABLE_CONTAINER_NAME,
            "-e", f"POSTGRES_PASSWORD={DISPOSABLE_PASSWORD}", "-e", f"POSTGRES_DB={DISPOSABLE_DB}",
            "-p", f"{DISPOSABLE_PORT}:5432", "postgres:16",
        ],
        check=True, capture_output=True,
    )


def _wait_for_postgres_ready(timeout_s: int = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", DISPOSABLE_CONTAINER_NAME, "pg_isready", "-U", "postgres"],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("disposable postgres container did not become ready in time")


def _run_alembic_upgrade_head() -> None:
    env = {
        **os.environ,
        "POSTGRES_HOST": "localhost", "POSTGRES_PORT": str(DISPOSABLE_PORT),
        "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": DISPOSABLE_PASSWORD, "POSTGRES_DB": DISPOSABLE_DB,
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        env=env, capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade head against the disposable DB failed:\n{result.stdout}\n{result.stderr}")


def _stop_disposable_postgres() -> None:
    subprocess.run(["docker", "rm", "-f", DISPOSABLE_CONTAINER_NAME], capture_output=True)


# --- real, read-only historical fetch ---------------------------------------------------------


async def _fetch_real_historical_events() -> list[tuple[NewsEvent, str, object]]:
    """Read-only against the REAL database (real_settings.database_url, unchanged) - a plain
    `SELECT`, never a write. Returns (event, source_name, source_type) tuples ordered
    chronologically."""
    engine = create_async_engine(real_settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(NewsEvent, NewsSource.name, NewsSource.type)
                .join(NewsSource, NewsEvent.source_id == NewsSource.id)
                .where(NewsEvent.published_at >= REPLAY_START, NewsEvent.published_at < REPLAY_END)
                .order_by(NewsEvent.published_at.asc())
            )
        ).all()
    await engine.dispose()
    return list(rows)


# --- replay loop against the disposable DB ------------------------------------------------------


def _load_known_case_event_ids() -> dict[UUID, str]:
    """event_id -> case_id, for every real_case event in the calibration fixture - used to
    instrument candidate-pool visibility specifically for the events we have ground truth for."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    mapping: dict[UUID, str] = {}
    for case in data["real_cases"]:
        for event_spec in case["events"]:
            mapping[UUID(event_spec["event_id"])] = case["case_id"]
    return mapping


async def _run_replay(rows: list[tuple[NewsEvent, str, object]]) -> dict:
    disposable_url = (
        f"postgresql+asyncpg://postgres:{DISPOSABLE_PASSWORD}@localhost:{DISPOSABLE_PORT}/{DISPOSABLE_DB}"
    )
    engine = create_async_engine(disposable_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    outcome_counts: Counter[str] = Counter()
    delta_counts: Counter[str] = Counter()
    band_counts: Counter[str] = Counter()
    would_suppress_true = 0
    would_suppress_examples: list[dict] = []
    # Phase 20 M12: bounded control samples for the human-review packet - "obvious non-suppress"
    # and "MATERIAL_UPDATE, must remain publishable" cases, captured alongside the suppression
    # candidates rather than in a separate pass.
    non_suppress_control_examples: list[dict] = []
    material_update_control_examples: list[dict] = []
    _MAX_CONTROL_EXAMPLES = 15

    # --- candidate-pool capacity instrumentation (measurement only, no behavior change) --------
    stage1_pool_sizes: list[int] = []
    stage2_pool_sizes: list[int] = []
    stage2_saturated_count = 0
    fragmented_story_count = 0  # M11.1's own-story creations for RELATED_STORY / weak UNCERTAIN_MATCH
    known_case_event_ids = _load_known_case_event_ids()
    # case_id -> {event_id: (story_id, first_event_id)} - first_event_id lets later diagnostics
    # detect an IDENTITY_MISS (the "prior" story recorded is not genuinely rooted at that event).
    case_event_story_ids: dict[str, dict[str, tuple[str, str]]] = {}
    case_pool_diagnostics: list[dict] = []

    async with session_factory() as session:
        seen_sources: dict[UUID, tuple[str, object]] = {}
        for event, source_name, source_type in rows:
            seen_sources.setdefault(event.source_id, (source_name, source_type))
        for source_id, (name, source_type) in seen_sources.items():
            session.add(NewsSource(id=source_id, name=name, type=source_type, active=True))
        await session.flush()

        for index, (event, source_name, _source_type) in enumerate(rows):
            reference_now = event.published_at or event.collected_at
            new_event = NewsEvent(
                id=event.id, source_id=event.source_id, title=event.title, category=event.category,
                hash=f"phase20-m11-replay-{event.id}", published_at=event.published_at,
                collected_at=event.collected_at or event.published_at,
            )
            session.add(new_event)
            await session.flush()

            # Instrumentation (Phase 20 M11.2): reproduce BOTH retrieval stages exactly as
            # match_story() is about to run them internally, purely to measure pool sizes / cap
            # saturation / true-candidate presence at each stage - never used to alter the
            # outcome (match_story() below runs its own, independent copy of this same logic).
            stage1_candidates = await _fetch_candidate_stories(session, now=reference_now)
            stage1_pool_sizes.append(len(stage1_candidates))
            stage1_ids_seen = {c.id for c in stage1_candidates}

            case_id = known_case_event_ids.get(event.id)
            prior_case_story_ids: dict[str, tuple[str, str]] = case_event_story_ids.get(case_id, {}) if case_id else {}

            signature, result = await match_story(session, title=event.title, category=event.category, now=reference_now)
            outcome_counts[result.outcome] += 1

            stage2_candidates = _preselect_candidates(signature, stage1_candidates)
            stage2_pool_sizes.append(len(stage2_candidates))
            stage2_saturated = len(stage2_candidates) >= STORY_MATCH_CANDIDATE_LIMIT
            if stage2_saturated:
                stage2_saturated_count += 1
            stage2_ids_seen = {c.id for c in stage2_candidates}

            if case_id and prior_case_story_ids:
                # Phase 20 CP4.1/CP4.2 - full ranked scoring of the entire Stage 2 set, so every
                # candidate's rank (not just presence/absence) and every score component is known,
                # for both the true sibling and whatever the matcher actually chose. Cheap: Stage 2
                # is capped at STORY_MATCH_CANDIDATE_LIMIT (150), so this is at most 150 pure-Python
                # score_candidate() calls per diagnosed event.
                ranked: list[tuple[UUID, float, float, float]] = []  # (story_id, combined, entity_overlap, title_overlap)
                for candidate in stage2_candidates:
                    combined, entity_overlap, title_overlap = score_candidate(
                        event.title, signature, event.category, candidate.title, candidate,
                    )
                    ranked.append((candidate.id, combined, entity_overlap, title_overlap))
                ranked.sort(key=lambda r: r[1], reverse=True)
                rank_by_id = {story_id: i + 1 for i, (story_id, *_rest) in enumerate(ranked)}
                score_by_id = {story_id: (combined, eo, to) for story_id, combined, eo, to in ranked}

                winning_id = result.matched_story_id
                winning_detail = await _story_full_detail(session, winning_id) if winning_id else None
                is_confident_same_story_outcome = result.outcome in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE)

                for prior_event_id, (prior_story_id, prior_story_first_event_id) in prior_case_story_ids.items():
                    prior_story_uuid = UUID(prior_story_id)
                    matched_prior_sibling = (
                        str(result.matched_story_id) == prior_story_id if result.matched_story_id else False
                    )
                    identity_ok = prior_story_first_event_id == prior_event_id
                    in_stage1 = prior_story_uuid in stage1_ids_seen
                    in_stage2 = prior_story_uuid in stage2_ids_seen

                    if matched_prior_sibling:
                        miss_class = None
                    elif not identity_ok:
                        miss_class = "IDENTITY_MISS"
                    elif not in_stage1 or not in_stage2:
                        miss_class = "RETRIEVAL_MISS"
                    elif is_confident_same_story_outcome and not matched_prior_sibling:
                        # The true sibling was present and scored, but the matcher confidently
                        # (STORY_UPDATE/SUPPORTING_SOURCE/SEMANTIC_DUPLICATE) chose a DIFFERENT
                        # story instead - a confident wrong answer, not a mere miss.
                        miss_class = "RELATIONSHIP_CLASSIFIER_FALSE_POSITIVE"
                    else:
                        miss_class = "SCORING_MISS"

                    entry = {
                        "case_id": case_id, "event_id": str(event.id), "prior_event_id": prior_event_id,
                        "prior_story_id": prior_story_id, "prior_story_identity_ok": identity_ok,
                        "total_lookback_stories": len(stage1_candidates),
                        "stage1_pool_size": len(stage1_candidates), "stage2_pool_size": len(stage2_candidates),
                        "stage2_saturated": stage2_saturated,
                        "prior_story_present_in_stage1": in_stage1, "prior_story_present_in_stage2": in_stage2,
                        "prior_story_preselection_rank": rank_by_id.get(prior_story_uuid) if in_stage2 else None,
                        "actual_outcome": result.outcome,
                        "actual_matched_story_id": str(result.matched_story_id) if result.matched_story_id else None,
                        "actual_matched_prior_sibling": matched_prior_sibling,
                        "miss_classification": miss_class,
                        "winning_story_detail": winning_detail,
                        "winning_story_rank": rank_by_id.get(winning_id) if winning_id else None,
                    }
                    if in_stage2:
                        combined, entity_overlap, title_overlap = score_by_id[prior_story_uuid]
                        entry["true_candidate_combined_score_if_scored"] = combined
                        entry["true_candidate_entity_overlap_component"] = entity_overlap
                        entry["true_candidate_title_overlap_component"] = title_overlap
                        entry["true_candidate_entity_weighted_contribution"] = 0.6 * entity_overlap
                        entry["true_candidate_title_weighted_contribution"] = 0.4 * title_overlap
                        entry["true_candidate_detail"] = await _story_full_detail(session, prior_story_uuid)
                        if winning_id and winning_id != prior_story_uuid:
                            entry["score_gap_winning_minus_true"] = (
                                score_by_id.get(winning_id, (result.confidence,))[0] - combined
                            )
                    entry["winning_candidate_score"] = result.confidence
                    case_pool_diagnostics.append(entry)

            # Phase 20 M11.1 (Story Identity Invariant) - mirrors services/triage_orchestrator.py::
            # _apply_story_memory()'s own dispatch exactly (this script cannot call that function
            # directly, since it needs its own instrumentation hooks around match_story(), so the
            # dispatch logic is deliberately kept in lockstep with it - see that function's own
            # docstring for the full rationale).
            creates_own_story = result.outcome in (NEW_STORY, RELATED_STORY) or (
                result.outcome == UNCERTAIN_MATCH and result.entity_overlap < _OWN_STORY_ENTITY_FLOOR
            )
            if creates_own_story:
                story = Story(
                    title=event.title, category=event.category, entities=signature.entities,
                    keywords=signature.keywords, topic_bucket=signature.topic_bucket,
                    first_event_id=event.id, event_count=1,
                    created_at=reference_now, updated_at=reference_now,
                )
                session.add(story)
                await session.flush()
                story_id = story.id
                story_first_event_id = event.id
                if result.outcome != NEW_STORY:
                    fragmented_story_count += 1
            else:
                story_id = result.matched_story_id
                matched_story = await session.get(Story, story_id)
                story_first_event_id = matched_story.first_event_id
                if result.outcome in _EVENT_COUNT_BUMP_OUTCOMES:
                    matched_story.event_count += 1
                    matched_story.updated_at = reference_now  # simulated historical "now", not real wall-clock
                    await session.flush()

            if case_id:
                case_event_story_ids.setdefault(case_id, {})[str(event.id)] = (str(story_id), str(story_first_event_id))

            delta_classification: str | None = None
            confidence_band: str | None = None
            would_suppress: bool | None = None
            if result.outcome in _SAME_STORY_OUTCOMES:
                confidence_band = compute_confidence_band(result.confidence)
                band_counts[confidence_band] += 1
                delta = await compute_story_delta(
                    session, new_title=event.title, story_id=story_id, exclude_event_id=event.id,
                )
                # Phase 20 Checkpoint 6 (identity before delta): gate MATERIAL_UPDATE on whether
                # the winning candidate shared a genuinely distinctive entity with the new event -
                # mirrors the exact real fix in services/story_delta_engine.py::
                # gate_delta_by_identity(), applied here since this script is the only current
                # caller of compute_story_delta() (no production wiring exists yet).
                delta = gate_delta_by_identity(delta, has_distinctive_shared_entity=result.has_distinctive_shared_entity)
                delta_classification = delta.classification
                delta_counts[delta_classification] += 1
                would_suppress = compute_would_suppress(
                    match_type=result.outcome, confidence_band=confidence_band, delta_classification=delta_classification,
                )
                if would_suppress:
                    would_suppress_true += 1
                    # Phase 20 M12 (suppression human-review packet): capture ALL suppression
                    # candidates, not a chronological-first sample, with the SAME full Story
                    # detail (_story_full_detail - every linked event's title/source, not just the
                    # root) used for the M13 identity-convergence diagnostics, so the reviewer
                    # packet can show "previous linked event titles" per the M12 spec.
                    story_detail = await _story_full_detail(session, story_id)
                    would_suppress_examples.append({
                        "event_id": str(event.id), "title": event.title, "source": source_name,
                        "category": event.category.value if hasattr(event.category, "value") else str(event.category),
                        "published_at": event.published_at.isoformat() if event.published_at else None,
                        "story_id": str(story_id),
                        "root_title": story_detail["root_title"] if story_detail else None,
                        "root_source": story_detail["root_source"] if story_detail else None,
                        "root_category": story_detail["category"] if story_detail else None,
                        "linked_events": story_detail["linked_events"] if story_detail else [],
                        "match_type": result.outcome, "delta_classification": delta_classification,
                        "delta_reason": delta.reason, "delta_new_keywords": delta.new_keywords,
                        "delta_new_material_claims": delta.new_material_claims,
                        "confidence_band": confidence_band, "match_score": result.confidence,
                        # The exact policy rule that fired - services/story_suppression.py's own
                        # compute_would_suppress() docstring, restated per-case for the reviewer.
                        "suppression_reason": (
                            f"{result.outcome} + confidence_band={confidence_band} + "
                            f"delta={delta_classification} (no material delta) -> would_suppress"
                        ),
                    })
                else:
                    control_entry = {
                        "event_id": str(event.id), "title": event.title, "source": source_name,
                        "category": event.category.value if hasattr(event.category, "value") else str(event.category),
                        "published_at": event.published_at.isoformat() if event.published_at else None,
                        "story_id": str(story_id), "match_type": result.outcome,
                        "delta_classification": delta_classification, "delta_reason": delta.reason,
                        "confidence_band": confidence_band, "match_score": result.confidence,
                    }
                    if delta_classification == "material_update" and len(material_update_control_examples) < _MAX_CONTROL_EXAMPLES:
                        story_detail = await _story_full_detail(session, story_id)
                        control_entry["root_title"] = story_detail["root_title"] if story_detail else None
                        material_update_control_examples.append(control_entry)
                    elif len(non_suppress_control_examples) < _MAX_CONTROL_EXAMPLES:
                        story_detail = await _story_full_detail(session, story_id)
                        control_entry["root_title"] = story_detail["root_title"] if story_detail else None
                        non_suppress_control_examples.append(control_entry)

            await session.execute(
                text(
                    "INSERT INTO news_event_story_links "
                    "(news_event_id, story_id, match_type, match_score, delta_classification, "
                    "confidence_band, would_suppress) "
                    "VALUES (:eid, :sid, :mt, :ms, :dc, :cb, :ws)"
                ),
                {
                    "eid": str(event.id), "sid": str(story_id), "mt": result.outcome, "ms": result.confidence,
                    "dc": delta_classification, "cb": confidence_band, "ws": would_suppress,
                },
            )

            if (index + 1) % 250 == 0:
                await session.commit()
                print(f"  ... {index + 1}/{len(rows)} events replayed", file=sys.stderr)

        await session.commit()

        # --- known real-case spot check under realistic candidate volume ------------------------
        case_results = await _check_known_cases(session)
        human_reviewed_results = await _check_human_reviewed_cases(session)

    await engine.dispose()

    miss_counts: Counter[str] = Counter(
        e["miss_classification"] for e in case_pool_diagnostics if e["miss_classification"] is not None
    )
    converged_count = sum(1 for e in case_pool_diagnostics if e["miss_classification"] is None)

    return {
        "total_events_replayed": len(rows),
        "replay_window": {"start": REPLAY_START.isoformat(), "end": REPLAY_END.isoformat()},
        "outcome_counts": dict(outcome_counts),
        "delta_classification_counts": dict(delta_counts),
        "confidence_band_counts": dict(band_counts),
        "would_suppress_true_count": would_suppress_true,
        "would_suppress_examples": would_suppress_examples,
        "non_suppress_control_examples": non_suppress_control_examples,
        "material_update_control_examples": material_update_control_examples,
        "known_case_results": case_results,
        "fragmented_story_count": fragmented_story_count,
        "candidate_pool_stats": {
            "story_match_candidate_limit": STORY_MATCH_CANDIDATE_LIMIT,
            "total_candidate_fetches": len(stage1_pool_sizes),
            "stage1_min_pool_size": min(stage1_pool_sizes) if stage1_pool_sizes else None,
            "stage1_max_pool_size": max(stage1_pool_sizes) if stage1_pool_sizes else None,
            "stage1_mean_pool_size": sum(stage1_pool_sizes) / len(stage1_pool_sizes) if stage1_pool_sizes else None,
            "stage2_saturated_count": stage2_saturated_count,
            "stage2_saturated_rate": stage2_saturated_count / len(stage2_pool_sizes) if stage2_pool_sizes else None,
            "stage2_min_pool_size": min(stage2_pool_sizes) if stage2_pool_sizes else None,
            "stage2_max_pool_size": max(stage2_pool_sizes) if stage2_pool_sizes else None,
            "stage2_mean_pool_size": sum(stage2_pool_sizes) / len(stage2_pool_sizes) if stage2_pool_sizes else None,
        },
        "known_case_pool_diagnostics": case_pool_diagnostics,
        "known_case_miss_classification_counts": dict(miss_counts),
        "known_case_converged_count": converged_count,
        "human_reviewed_case_results": human_reviewed_results,
    }


async def _story_full_detail(session: AsyncSession, story_id: UUID) -> dict | None:
    """Phase 20 CP4.1: full diagnostic dump of a Story - id, title, entities, keywords, topic,
    category, root event/source, and every event currently linked to it. Used only for the known
    real cases' own diagnostics (bounded, cheap) - never called on the full unlabeled corpus."""
    story_row = (
        await session.execute(
            text(
                "SELECT st.title, st.entities, st.keywords, st.topic_bucket, st.category, "
                "st.event_count, st.first_event_id, ne.title AS root_title, s.name AS root_source "
                "FROM stories st JOIN news_events ne ON ne.id = st.first_event_id "
                "JOIN sources s ON s.id = ne.source_id WHERE st.id = :sid"
            ),
            {"sid": str(story_id)},
        )
    ).mappings().first()
    if story_row is None:
        return None
    linked = (
        await session.execute(
            text(
                "SELECT nel.news_event_id, ne.title, s.name AS source, nel.match_type, nel.match_score "
                "FROM news_event_story_links nel "
                "JOIN news_events ne ON ne.id = nel.news_event_id "
                "JOIN sources s ON s.id = ne.source_id WHERE nel.story_id = :sid"
            ),
            {"sid": str(story_id)},
        )
    ).mappings().all()
    return {
        "story_id": str(story_id), "title": story_row["title"], "entities": story_row["entities"],
        "keywords": story_row["keywords"], "topic_bucket": story_row["topic_bucket"],
        "category": story_row["category"], "event_count": story_row["event_count"],
        "root_event_id": str(story_row["first_event_id"]), "root_title": story_row["root_title"],
        "root_source": story_row["root_source"],
        "linked_events": [
            {
                "event_id": str(row["news_event_id"]), "title": row["title"], "source": row["source"],
                "match_type": row["match_type"], "match_score": row["match_score"],
            }
            for row in linked
        ],
    }


async def _check_known_cases(session: AsyncSession) -> list[dict]:
    """Query the disposable DB's own persisted NewsEventStoryLink rows for the 4 real calibration
    cases' exact event IDs - proves they behave as expected/documented when replayed inside a
    realistic multi-thousand-event candidate pool, not just the isolated single-candidate unit
    tests in tests/test_story_memory_v2.py."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    results = []
    for case in data["real_cases"]:
        case_result = {"case_id": case["case_id"], "events": []}
        for event_spec in case["events"]:
            event_id = UUID(event_spec["event_id"])
            row = (
                await session.execute(
                    text(
                        "SELECT match_type, match_score, delta_classification, confidence_band, "
                        "would_suppress, story_id FROM news_event_story_links WHERE news_event_id = :eid"
                    ),
                    {"eid": str(event_id)},
                )
            ).mappings().first()
            case_result["events"].append({
                "event_id": str(event_id), "title": event_spec["title"],
                "found_in_replay_window": row is not None,
                "match_type": row["match_type"] if row else None,
                "match_score": row["match_score"] if row else None,
                "delta_classification": row["delta_classification"] if row else None,
                "confidence_band": row["confidence_band"] if row else None,
                "would_suppress": row["would_suppress"] if row else None,
                "story_id": str(row["story_id"]) if row else None,
            })
        story_ids = {e["story_id"] for e in case_result["events"] if e["story_id"] is not None}
        case_result["all_events_landed_under_same_story_id"] = len(story_ids) == 1 and len(case_result["events"]) > 1
        results.append(case_result)
    return results


_HUMAN_REVIEWED_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "phase20_human_reviewed_cases.json"
_SAME_STORY_MATCH_TYPES = {STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE}


async def _check_human_reviewed_cases(session: AsyncSession) -> dict:
    """Phase 20 Checkpoint 6: query the disposable DB's own persisted NewsEventStoryLink rows for
    every case in tests/fixtures/phase20_human_reviewed_cases.json - the real, measured (not
    synthetic-pool) outcome for each confirmed false-match/genuine-update/investigation case,
    under full real-corpus candidate volume and real corpus-wide entity document frequency."""
    if not _HUMAN_REVIEWED_FIXTURE_PATH.exists():
        return {}
    data = json.loads(_HUMAN_REVIEWED_FIXTURE_PATH.read_text(encoding="utf-8"))
    results: dict[str, list[dict]] = {}
    for section in ("false_match_cases", "genuine_update_cases", "special_investigation_cases", "representative_correct_suppress_cases"):
        section_results = []
        for case in data.get(section, []):
            event_id = UUID(case["event_id"])
            row = (
                await session.execute(
                    text(
                        "SELECT match_type, match_score, delta_classification, confidence_band, "
                        "would_suppress, story_id FROM news_event_story_links WHERE news_event_id = :eid"
                    ),
                    {"eid": str(event_id)},
                )
            ).mappings().first()
            outcome = {
                "case_id": case["case_id"], "human_verdict": case["human_verdict"],
                "found_in_replay_window": row is not None,
                "match_type": row["match_type"] if row else None,
                "match_score": row["match_score"] if row else None,
                "delta_classification": row["delta_classification"] if row else None,
                "confidence_band": row["confidence_band"] if row else None,
                "would_suppress": row["would_suppress"] if row else None,
            }
            if row:
                outcome["is_confident_same_story"] = row["match_type"] in _SAME_STORY_MATCH_TYPES
            section_results.append(outcome)
        results[section] = section_results
    return results


async def main() -> None:
    print("Phase 20 M11: fetching real historical events (read-only) ...", file=sys.stderr)
    rows = await _fetch_real_historical_events()
    print(f"Fetched {len(rows)} real events between {REPLAY_START.date()} and {REPLAY_END.date()} (exclusive).", file=sys.stderr)
    if not rows:
        raise RuntimeError("no real historical events found in the replay window - aborting")

    print("Starting disposable Postgres container ...", file=sys.stderr)
    _start_disposable_postgres()
    try:
        _wait_for_postgres_ready()
        print("Applying migrations (alembic upgrade head) to the disposable DB only ...", file=sys.stderr)
        _run_alembic_upgrade_head()
        print("Replaying events chronologically through the V2 matcher ...", file=sys.stderr)
        results = await _run_replay(rows)
    finally:
        print("Destroying disposable Postgres container ...", file=sys.stderr)
        _stop_disposable_postgres()

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Results written to {OUTPUT_JSON}", file=sys.stderr)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
