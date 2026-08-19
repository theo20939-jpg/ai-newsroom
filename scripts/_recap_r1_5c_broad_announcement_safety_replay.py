"""NINJA PULSE RECAP Phase R1.5C - broad 30-Story production READ-ONLY announcement safety replay.

DIAGNOSTIC ONLY. Does not modify `services/recap_event.py`, `services/story_memory.py`, or
`core/config.py`. Story Integrity is frozen - only Stories that PASS `evaluate_recap_story_
integrity()` (real, unmodified) proceed to announcement comparison; FAIL Stories are reported as
skipped, never clustered.

Compares, for every integrity-PASS Story in a bounded ~30-Story sample:

    OLD announcement behavior - the pre-R1.5B.1 logic: RAW (unsanitized) StorySignature entities,
    and `_announcement_similarity()` WITHOUT the R1.5B.1 conflict-cap guard clause. Reconstructed
    LOCALLY in this script only (`_old_similarity()`/`_old_best_cluster_match_score()`/
    `_old_cluster_announcements()`) - never imported from or written back into services/
    recap_event.py. Everything else (near-exact precedence, distinctive/temporal evidence,
    conflict-fact detection itself, stable-reference-only scope, the 0.75 threshold) is REUSED,
    unchanged, from the real module, since none of those were touched by R1.5B.1 - only signature
    sanitization and the conflict-cap guard were new.

    NEW announcement behavior - the real, current `cluster_announcements()`, called directly and
    unmodified.

Sample selection strategy is copied verbatim from `scripts/_recap_r1_4_production_replay.py`
(SCAN_LIMIT/TARGET_SAMPLE/event-count floors/boilerplate+duplicate-title filtering) - same bounded
~30-Story replay, no backlog processing, no broadening to the whole database.

For every Story where NEW announcement_count < OLD, every genuinely NEW merge (a pair that landed
in the same NEW cluster but different OLD clusters) is classified SAFE_COLLAPSE / SUSPICIOUS_
COLLAPSE / INCONCLUSIVE using only stored titles/entities/numbers/timestamps - see
`_classify_new_merge()`'s own docstring for the exact, disclosed heuristic (never hidden, always
overridable by a human reading the underlying printed numbers). Publisher-suffix removals are
aggregated and independently re-verified (an entity is POSSIBLY_SUBSTANTIVE if it also appears in
the removed entity's own suffix-stripped core title - by construction this should never happen,
which is exactly why it is checked here rather than trusted). Conflict-cap usage is counted and
flagged whenever the cap actually changed the merge/no-merge outcome (pre-cap score would have
cleared 0.75). Readiness is compared OLD vs NEW (same unique-source-count/cooling inputs, only
announcement_count differs) and every READY-state transition is flagged, with any Story that
becomes READY ONLY because of R1.5B.1 marked CRITICAL REVIEW.

Nothing here tunes or edits: publisher sanitization, the conflict cap, the 0.75 threshold,
near-exact rules, the temporal window, stable-reference policy, announcement-similarity weights,
readiness thresholds, or Story Integrity. Report only.

Safety pattern (identical to every prior production-facing diagnostic this session): SET
TRANSACTION READ ONLY + SHOW transaction_read_only verification, SET LOCAL statement_timeout, one
transaction, rollback in finally, no writes/network/LLM/Telegram/workers.

Use: `docker compose run --rm --no-deps backend python scripts/_recap_r1_5c_broad_announcement_safety_replay.py`
NOT executed by the author of this script - no VPS/production DB access this session.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.recap_event import (  # noqa: E402
    _ANNOUNCEMENT_ENTITY_WEIGHT,
    _ANNOUNCEMENT_TITLE_WEIGHT,
    _CONFLICTING_FACTS_SIMILARITY_CAP,
    _DISTINCTIVE_EVIDENCE_SCORE,
    AnnouncementCluster,
    _extract_numeric_tokens,
    _has_conflicting_distinctive_facts,
    _has_distinctive_shared_evidence,
    _has_temporally_corroborated_distinctive_evidence,
    _is_near_exact_title_match,
    _jaccard,
    _publisher_suffix_entities,
    _sanitized_announcement_signature,
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    load_story_events,
)
from services.story_memory import StorySignature, extract_story_signature  # noqa: E402
from services.text_normalization import symmetric_token_overlap  # noqa: E402

OUTPUT_PATH = Path("/tmp/recap_r1_5c_broad_announcement_safety_replay.txt")
STATEMENT_TIMEOUT_MS = 30_000

# Exact bounded sample-selection strategy copied verbatim from scripts/_recap_r1_4_production_replay.py
SCAN_LIMIT = 500
TARGET_SAMPLE = 30
MIN_USABLE_AT_PRIMARY_FLOOR = 5
PRIMARY_EVENT_COUNT_FLOOR = 3
FALLBACK_EVENT_COUNT_FLOOR = 2
_BOILERPLATE_TITLE_MARKERS = ("content cycle test event", "test event", "test source", "test story")

KNOWN_STORY_IDS: dict[UUID, str] = {
    UUID("859ffea0-9b54-41cb-be25-13c061ca75ad"): "Taiwan AI dividend (expected OLD 4 -> NEW 2)",
    UUID("2d803e6c-2378-41d0-87b0-396515681e1b"): "OpenAI / Hugging Face breach (expected unchanged, 5)",
    UUID("60be3f72-28d3-4c5a-af65-f0550923fe94"): "Sverdlovsk dermatologists (expected unchanged, 3)",
    UUID("6b6b8217-db8d-4466-aa28-45ba9068b891"): "AI/VR classrooms (expected 1 -> 1)",
    UUID("24c02f3d-5498-44ee-8ef1-94d2997bd802"): "ADRES (expected 1 -> 1)",
}


class ReadOnlyGuardError(RuntimeError):
    """Raised when SET TRANSACTION READ ONLY could not be verified - no query runs without it."""


def _is_boilerplate_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _BOILERPLATE_TITLE_MARKERS)


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = result.scalar()
    if str(value).strip().lower() != "on":
        raise ReadOnlyGuardError(f"SET TRANSACTION READ ONLY not confirmed - got {value!r}. Refusing to query.")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


async def _scan_candidates(session: AsyncSession, event_count_floor: int) -> dict:
    stmt = select(Story).where(Story.event_count >= event_count_floor).order_by(Story.updated_at.desc()).limit(SCAN_LIMIT)
    scanned = list((await session.execute(stmt)).scalars().all())
    boilerplate_removed, duplicate_removed = 0, 0
    seen_titles: set[str] = set()
    usable: list[Story] = []
    for story in scanned:
        if _is_boilerplate_title(story.title):
            boilerplate_removed += 1
            continue
        if story.title in seen_titles:
            duplicate_removed += 1
            continue
        seen_titles.add(story.title)
        usable.append(story)
    return {
        "event_count_floor": event_count_floor, "scanned": len(scanned),
        "boilerplate_removed": boilerplate_removed, "duplicate_removed": duplicate_removed, "usable": usable,
    }


async def select_sample(session: AsyncSession) -> list[Story]:
    primary = await _scan_candidates(session, PRIMARY_EVENT_COUNT_FLOOR)
    usable = primary["usable"]
    if len(usable) < MIN_USABLE_AT_PRIMARY_FLOOR:
        fallback = await _scan_candidates(session, FALLBACK_EVENT_COUNT_FLOOR)
        seen_ids = {s.id for s in usable}
        usable = usable + [s for s in fallback["usable"] if s.id not in seen_ids]
    return usable[:TARGET_SAMPLE]


# ---------------------------------------------------------------------------
# OLD (pre-R1.5B.1) announcement behavior - reconstructed LOCALLY, diagnostic-only. Reuses every
# real, unchanged primitive (near-exact precedence, distinctive/temporal evidence, conflict-fact
# detection, stable-reference-only scope, the 0.75 threshold); only the conflict-cap guard clause
# and signature sanitization (the two actual R1.5B.1 changes) are reconstructed without their fix.
# ---------------------------------------------------------------------------


def _old_similarity(sig_a: StorySignature, title_a: str, sig_b: StorySignature, title_b: str) -> float:
    """Pre-R1.5B.1 `_announcement_similarity()` - identical formula, WITHOUT the conflict-cap guard
    clause R1.5B.1 added. Reuses the real, unchanged `_jaccard()`/weight constants/
    `symmetric_token_overlap()`."""
    entities_a, entities_b = set(sig_a.entities), set(sig_b.entities)
    title_overlap = symmetric_token_overlap(title_a, title_b)
    if not entities_a or not entities_b:
        return title_overlap
    entity_overlap = _jaccard(entities_a, entities_b)
    return min(1.0, _ANNOUNCEMENT_ENTITY_WEIGHT * entity_overlap + _ANNOUNCEMENT_TITLE_WEIGHT * title_overlap)


def _old_best_cluster_match_score(
    signature: StorySignature, title: str, time: datetime, members: list[tuple[StorySignature, str, datetime]],
) -> float:
    """Mirrors the real `_best_cluster_match_score()`'s exact two-tier structure, but scores via
    `_old_similarity()` instead of the real (R1.5B.1-fixed) `_announcement_similarity()`. Calls the
    real, unchanged `_has_distinctive_shared_evidence()`/
    `_has_temporally_corroborated_distinctive_evidence()`/`_is_near_exact_title_match()` - none of
    those were modified by R1.5B.1; only their signature INPUTS became sanitized when called from
    the real `cluster_announcements()`. Here they receive RAW signatures, exactly matching what they
    received before R1.5B.1 existed."""
    stable_sig, stable_title, stable_time = members[0]
    best = _old_similarity(signature, title, stable_sig, stable_title)
    if _has_distinctive_shared_evidence(signature, title, stable_sig, stable_title):
        best = max(best, _DISTINCTIVE_EVIDENCE_SCORE)
    if _has_temporally_corroborated_distinctive_evidence(
        signature, title, time, stable_sig, stable_title, stable_time,
    ):
        best = max(best, _DISTINCTIVE_EVIDENCE_SCORE)
    for member_sig, member_title, _member_time in members:
        if _is_near_exact_title_match(title, member_title):
            return 1.0
    return best


def _old_cluster_announcements(events: list[NewsEvent]) -> list[AnnouncementCluster]:
    """Mirrors the real `cluster_announcements()`'s exact greedy chronological loop, but builds RAW
    (unsanitized) StorySignatures via `extract_story_signature()` directly - the actual pre-R1.5B.1
    behavior - and scores via `_old_best_cluster_match_score()`."""
    threshold = settings.recap_announcement_cluster_threshold
    clusters: list[dict] = []
    for event in events:
        signature = extract_story_signature(event.title, event.category)
        anchor_time = event.published_at or event.collected_at
        best_idx: int | None = None
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            score = _old_best_cluster_match_score(signature, event.title, anchor_time, cluster["members"])
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx is not None and best_score >= threshold:
            cluster = clusters[best_idx]
            cluster["members"].append((signature, event.title, anchor_time))
            cluster["event_ids"].append(event.id)
        else:
            clusters.append({"members": [(signature, event.title, anchor_time)], "title": event.title, "event_ids": [event.id]})
    return [
        AnnouncementCluster(
            cluster_id=i, event_ids=c["event_ids"], headline=c["title"],
            source_urls=[], source_domains=[], first_seen_at=events[0].published_at or events[0].collected_at,
            last_seen_at=events[-1].published_at or events[-1].collected_at,
        )
        for i, c in enumerate(clusters)
    ]


# ---------------------------------------------------------------------------
# New-merge safety classification (item 6/7) - deterministic, disclosed heuristic over stored
# titles/entities/numbers only. Always shows the underlying raw signals so a human can override.
# ---------------------------------------------------------------------------


def _classify_new_merge(
    sig_a: StorySignature, title_a: str, sig_b: StorySignature, title_b: str,
) -> str:
    """Classifies a pair that merged NEW but did not merge OLD. `sig_a`/`sig_b` are the SANITIZED
    (content-only) signatures - the classifier deliberately reasons about content evidence, not raw
    publisher-contaminated entities.

    SUSPICIOUS_COLLAPSE: both titles carry a number and the numbers differ (a real, proven
    conflicting fact - the same signal `_has_conflicting_distinctive_facts()` itself uses).
    SAFE_COLLAPSE: near-exact title match, OR the same shared number plus at least one shared
    sanitized content entity, OR strong title overlap (>=0.60) plus at least one shared entity.
    SUSPICIOUS_COLLAPSE (weak-evidence case): no shared content entity and no shared number, or the
    merge rests on a single shared entity with weak (<0.50) title overlap.
    INCONCLUSIVE: everything else - titles alone do not clearly establish either direction."""
    numbers_a, numbers_b = _extract_numeric_tokens(title_a), _extract_numeric_tokens(title_b)
    if numbers_a and numbers_b and numbers_a != numbers_b:
        return "SUSPICIOUS_COLLAPSE"
    if _is_near_exact_title_match(title_a, title_b):
        return "SAFE_COLLAPSE"
    title_overlap = symmetric_token_overlap(title_a, title_b)
    shared_entities = set(sig_a.entities) & set(sig_b.entities)
    if numbers_a and numbers_a == numbers_b and shared_entities:
        return "SAFE_COLLAPSE"
    if title_overlap >= 0.60 and shared_entities:
        return "SAFE_COLLAPSE"
    if not shared_entities and not (numbers_a and numbers_a == numbers_b):
        return "INCONCLUSIVE" if title_overlap >= 0.30 else "SUSPICIOUS_COLLAPSE"
    if len(shared_entities) <= 1 and title_overlap < 0.50:
        return "SUSPICIOUS_COLLAPSE"
    return "INCONCLUSIVE"


_SEVERITY_ORDER = {"SAFE_COLLAPSE": 0, "INCONCLUSIVE": 1, "SUSPICIOUS_COLLAPSE": 2}


async def render_story(session: AsyncSession, story: Story, aggregate: dict) -> list[str]:
    events = await load_story_events(session, story.id)
    known_label = KNOWN_STORY_IDS.get(story.id)
    lines = [
        f"Story {story.id}: {story.title!r}" + (f"  [KNOWN CASE: {known_label}]" if known_label else ""),
        f"  declared event_count={story.event_count}  confirmed member count={len(events)}",
    ]

    anchor = next((e for e in events if e.id == story.first_event_id), events[0] if events else None)
    if anchor is None:
        lines.append("  SKIPPED - no confirmed member events loaded")
        lines.append("")
        aggregate["skipped_no_events"] += 1
        return lines

    integrity = evaluate_recap_story_integrity(anchor, events)
    aggregate["integrity"]["PASS" if integrity.eligible else "FAIL"] += 1
    if not integrity.eligible:
        lines.append(f"  Story Integrity Gate: FAIL - {integrity.reasons}")
        lines.append("  SKIPPED - not clustered (Story Integrity frozen this checkpoint)")
        lines.append("")
        return lines
    lines.append("  Story Integrity Gate: PASS")

    title_by_id = {e.id: e.title for e in events}
    raw_sigs = {e.id: extract_story_signature(e.title, e.category) for e in events}
    sanitized_sigs = {e.id: _sanitized_announcement_signature(raw_sigs[e.id], e.title) for e in events}

    old_clusters = _old_cluster_announcements(events)
    new_clusters = cluster_announcements(events)
    old_count, new_count = len(old_clusters), len(new_clusters)
    delta = new_count - old_count

    old_cluster_of: dict[UUID, int] = {eid: c.cluster_id for c in old_clusters for eid in c.event_ids}
    new_cluster_of: dict[UUID, int] = {eid: c.cluster_id for c in new_clusters for eid in c.event_ids}

    lines.append(f"  OLD announcement_count (pre-R1.5B.1, reconstructed)={old_count}")
    lines.append(f"  NEW announcement_count (current production)={new_count}")
    lines.append(f"  delta (NEW - OLD)={delta}")
    lines.append("  OLD clusters:")
    for c in old_clusters:
        lines.append(f"    old_cluster#{c.cluster_id}: {[title_by_id[eid] for eid in c.event_ids]}")
    lines.append("  NEW clusters:")
    for c in new_clusters:
        lines.append(f"    new_cluster#{c.cluster_id}: {[title_by_id[eid] for eid in c.event_ids]}")

    lines.append("  publisher entities removed (NEW, per event):")
    story_removed_any = False
    for e in events:
        removed = _publisher_suffix_entities(e.title)
        if not removed:
            continue
        story_removed_any = True
        aggregate["events_with_removal"] += 1
        aggregate["total_removed_entities"] += len(removed)
        for entity in removed:
            aggregate["removed_by_story"][str(story.id)].append((e.id, entity, e.title))
            # Independent re-verification of the invariant _publisher_suffix_entities() is SUPPOSED
            # to guarantee (suffix-only, never also present in the core) - not trusted blindly.
            core_entities = set(sanitized_sigs[e.id].entities)
            if entity in core_entities:
                aggregate["possibly_substantive_removals"].append((story.id, e.id, entity, e.title))
                lines.append(f"    *** POSSIBLY_SUBSTANTIVE removal: event={e.id} entity={entity!r} title={e.title!r} ***")
        lines.append(f"    event_id={e.id}: removed={sorted(removed)}  title={e.title!r}")
    if story_removed_any:
        aggregate["stories_with_removal"] += 1
    else:
        lines.append("    (none)")

    # Every NEW merge that did not exist OLD - full pairwise audit (item 7) + classification (item 6).
    new_merge_classifications: list[str] = []
    lines.append("  NEW merges not present OLD (full audit):")
    any_new_merge = False
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            a, b = events[i], events[j]
            if new_cluster_of.get(a.id) != new_cluster_of.get(b.id):
                continue  # not in the same NEW cluster
            if old_cluster_of.get(a.id) == old_cluster_of.get(b.id):
                continue  # already merged OLD too - not a NEW merge
            any_new_merge = True
            raw_sig_a, raw_sig_b = raw_sigs[a.id], raw_sigs[b.id]
            san_sig_a, san_sig_b = sanitized_sigs[a.id], sanitized_sigs[b.id]
            old_jaccard = _jaccard(set(raw_sig_a.entities), set(raw_sig_b.entities))
            new_jaccard = _jaccard(set(san_sig_a.entities), set(san_sig_b.entities))
            old_conflict = _has_conflicting_distinctive_facts(raw_sig_a, a.title, raw_sig_b, b.title)
            new_conflict = _has_conflicting_distinctive_facts(san_sig_a, a.title, san_sig_b, b.title)
            title_overlap = symmetric_token_overlap(a.title, b.title)
            numbers_a, numbers_b = _extract_numeric_tokens(a.title), _extract_numeric_tokens(b.title)
            time_a = a.published_at or a.collected_at
            time_b = b.published_at or b.collected_at
            gap_minutes = abs((time_a - time_b).total_seconds()) / 60

            near_exact = _is_near_exact_title_match(a.title, b.title)
            distinctive = _has_distinctive_shared_evidence(san_sig_a, a.title, san_sig_b, b.title)
            temporal = _has_temporally_corroborated_distinctive_evidence(
                san_sig_a, a.title, time_a, san_sig_b, b.title, time_b,
            )
            fuzzy = _old_similarity(san_sig_a, a.title, san_sig_b, b.title)  # entity/title blend only, no cap
            cause_parts = []
            if near_exact:
                cause_parts.append("near_exact")
            if fuzzy >= settings.recap_announcement_cluster_threshold:
                cause_parts.append("fuzzy>=0.75")
            if distinctive:
                cause_parts.append("distinctive_shared_evidence")
            if temporal:
                cause_parts.append("temporal_evidence")
            if old_jaccard < new_jaccard:
                cause_parts.append("publisher_sanitization_entity_jaccard_increase")
            if old_conflict and not new_conflict:
                cause_parts.append("conflict_removed")
            if new_conflict:
                cause_parts.append("conflict_cap_involved")
            cause = ", ".join(cause_parts) if cause_parts else "UNEXPLAINED (investigate)"

            classification = _classify_new_merge(san_sig_a, a.title, san_sig_b, b.title)
            new_merge_classifications.append(classification)
            lines.append(f"    [{classification}] cause=[{cause}]")
            lines.append(f"      A={a.title!r}")
            lines.append(f"      B={b.title!r}")
            lines.append(
                f"      OLD entity_jaccard={old_jaccard:.3f}  NEW entity_jaccard={new_jaccard:.3f}  "
                f"OLD conflict={old_conflict}  NEW conflict={new_conflict}"
            )
            lines.append(
                f"      title_overlap={title_overlap:.3f}  numbers_A={numbers_a}  numbers_B={numbers_b}  "
                f"time_gap_minutes={gap_minutes:.1f}"
            )
            aggregate["new_merge_classification_counts"][classification] += 1
            if new_conflict:
                aggregate["conflict_cap_pairs_total"] += 1
                if fuzzy >= settings.recap_announcement_cluster_threshold:
                    # the pre-cap blend alone would have crossed threshold - cap is doing real work
                    aggregate["conflict_cap_pairs_would_have_crossed"].append(
                        (story.id, a.title, b.title, fuzzy, numbers_a, numbers_b)
                    )
    if not any_new_merge:
        lines.append("    (none)")

    story_classification = None
    if delta < 0:
        aggregate["count_decreases"] += 1
        if new_merge_classifications:
            story_classification = max(new_merge_classifications, key=lambda c: _SEVERITY_ORDER[c])
        else:
            story_classification = "INCONCLUSIVE"  # decrease with no directly-attributable new merge pair found
        aggregate["story_classification_counts"][story_classification] += 1
        lines.append(f"  STORY-LEVEL COLLAPSE CLASSIFICATION: {story_classification} (worst of {new_merge_classifications or ['none found']})")
    elif delta > 0:
        aggregate["count_increases"] += 1
    if delta != 0:
        aggregate["count_changed"] += 1

    # Readiness OLD vs NEW - identical inputs except announcement_count (mirrors R1.4 replay's own
    # research_complete=False isolation methodology).
    unique_sources = count_unique_sources(events)
    last_event_at = max((e.published_at or e.collected_at for e in events), default=story.updated_at)
    readiness_old = evaluate_recap_readiness(
        event_count=len(events), announcement_count=old_count, unique_source_count=unique_sources,
        last_event_at=last_event_at, now=story.updated_at, research_complete=False, unresolved_conflict_count=0,
        story_integrity_eligible=True, story_integrity_reasons=[],
    )
    readiness_new = evaluate_recap_readiness(
        event_count=len(events), announcement_count=new_count, unique_source_count=unique_sources,
        last_event_at=last_event_at, now=story.updated_at, research_complete=False, unresolved_conflict_count=0,
        story_integrity_eligible=True, story_integrity_reasons=[],
    )
    lines.append(f"  readiness OLD: state={readiness_old.state} ready={readiness_old.ready}")
    lines.append(f"  readiness NEW: state={readiness_new.state} ready={readiness_new.ready}")
    if readiness_old.ready != readiness_new.ready:
        transition = f"{readiness_old.ready}->{readiness_new.ready}"
        aggregate["readiness_transitions"][transition] += 1
        lines.append(f"  *** READINESS TRANSITION: {transition} ***")
        if not readiness_old.ready and readiness_new.ready:
            aggregate["new_ready_caused_by_fix"].append(str(story.id))
            lines.append("  *** CRITICAL REVIEW: became READY only because of R1.5B.1 ***")

    lines.append("")
    return lines


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    try:
        await _verify_read_only(conn)
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

        stories = await select_sample(session)
        lines = [
            "NINJA PULSE RECAP Phase R1.5C - broad announcement safety replay (READ ONLY)",
            "Source: production database (connection string never printed)",
            f"Sample size: {len(stories)} Stories (bounded sample strategy copied from R1.4 replay)",
            "",
        ]

        aggregate: dict = {
            "integrity": Counter(),
            "skipped_no_events": 0,
            "count_changed": 0, "count_decreases": 0, "count_increases": 0,
            "new_merge_classification_counts": Counter(),
            "story_classification_counts": Counter(),
            "events_with_removal": 0, "total_removed_entities": 0, "stories_with_removal": 0,
            "removed_by_story": defaultdict(list),
            "possibly_substantive_removals": [],
            "conflict_cap_pairs_total": 0,
            "conflict_cap_pairs_would_have_crossed": [],
            "readiness_transitions": Counter(),
            "new_ready_caused_by_fix": [],
        }

        for story in stories:
            lines += await render_story(session, story, aggregate)

        lines += ["=" * 100, "AGGREGATE", "=" * 100]
        lines.append(f"Sample size: {len(stories)}")
        lines.append(f"Integrity verdicts: {dict(aggregate['integrity'])}  skipped(no events)={aggregate['skipped_no_events']}")
        lines.append(f"Announcement-count changed: {aggregate['count_changed']}  decreases: {aggregate['count_decreases']}  increases: {aggregate['count_increases']}")
        lines.append(f"Story-level collapse classification counts: {dict(aggregate['story_classification_counts'])}")
        lines.append(f"New-merge-pair classification counts: {dict(aggregate['new_merge_classification_counts'])}")
        lines.append(f"Publisher removal: events_with_removal={aggregate['events_with_removal']} total_removed_entities={aggregate['total_removed_entities']} stories_with_removal={aggregate['stories_with_removal']}")
        if aggregate["possibly_substantive_removals"]:
            lines.append(f"*** FLAG: {len(aggregate['possibly_substantive_removals'])} POSSIBLY_SUBSTANTIVE removal(s) found - run flagged ***")
            for story_id, event_id, entity, title in aggregate["possibly_substantive_removals"]:
                lines.append(f"    story={story_id} event={event_id} entity={entity!r} title={title!r}")
        else:
            lines.append("No POSSIBLY_SUBSTANTIVE removals found.")
        lines.append(
            f"Conflict-cap pairs (has_conflicting_distinctive_facts=True on sanitized signatures, "
            f"final similarity capped at {_CONFLICTING_FACTS_SIMILARITY_CAP}): {aggregate['conflict_cap_pairs_total']}"
        )
        if aggregate["conflict_cap_pairs_would_have_crossed"]:
            lines.append(f"Conflict-cap pairs where pre-cap similarity WOULD have crossed threshold ({len(aggregate['conflict_cap_pairs_would_have_crossed'])}):")
            for story_id, title_a, title_b, fuzzy, numbers_a, numbers_b in aggregate["conflict_cap_pairs_would_have_crossed"]:
                lines.append(f"    story={story_id} pre_cap={fuzzy:.3f} numbers_A={numbers_a} numbers_B={numbers_b}")
                lines.append(f"      A={title_a!r}")
                lines.append(f"      B={title_b!r}")
        else:
            lines.append("No conflict-cap pair would otherwise have crossed threshold in this sample.")
        lines.append(f"Readiness transitions: {dict(aggregate['readiness_transitions'])}")
        if aggregate["new_ready_caused_by_fix"]:
            lines.append(f"*** CRITICAL REVIEW: {len(aggregate['new_ready_caused_by_fix'])} Story(ies) became READY only because of R1.5B.1: {aggregate['new_ready_caused_by_fix']} ***")
        else:
            lines.append("No Story became READY only because of R1.5B.1.")

        lines.append("")
        lines.append("Known-case lookup results:")
        found_known_ids = {s.id for s in stories} & set(KNOWN_STORY_IDS)
        for story_id, label in KNOWN_STORY_IDS.items():
            lines.append(f"  {story_id} ({label}): {'present in sample' if story_id in found_known_ids else 'NOT in this sample'}")

        OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH} ({len(stories)} Stories)")
    finally:
        await trans.rollback()
        await conn.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
