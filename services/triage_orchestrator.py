"""Triage Orchestrator (Phase 9 M2 + M3): atomic NewsEvent ownership primitives, plus
the full find-work / claim / Triage / create_task() cycle that composes them.

Phase 9 Contract §2.3/§7 (all subsections). See scripts/validate_architecture.py's
triage-orchestrator-isolation rule for the mechanically-enforced dependency boundary:
no LLMGateway, no Capability layer, no provider SDK.

Both primitives (_claim_new_event, _acquire_recovery_ownership) are a single, atomic
conditional UPDATE plus an affected-row-count check - never a SELECT followed by a
separate UPDATE (Contract §7.2's explicit prohibition). They never commit or roll
back themselves - that is run_triage_cycle()'s responsibility, per the exact
transaction discipline documented on it below.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.news_event import EventStatus, NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.session import async_session_factory
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services.cleaning import is_valid_title
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    match_story,
)
from services.story_memory import _RELATED_STORY_ENTITY_FLOOR as _OWN_STORY_ENTITY_FLOOR
from services.story_confidence import compute_confidence_band
from services.story_continuity import (
    classify_continuity,
    evaluate_constrained_enforcement,
    normalize_title_for_exact_match,
)
from services.story_delta_engine import compute_story_delta, gate_delta_by_identity
from services.story_identity_guard import assess_continuity_identity
from services.story_suppression import compute_would_suppress
from services.text_normalization import (
    is_google_news_provenance,
    strip_google_news_title_suffix,
)
from services.triage import decide_triage
from services.workflow_service import _find_active_task, create_task
from workflows.errors import DuplicateActiveTaskError

logger = logging.getLogger(__name__)

__all__ = [
    "_claim_new_event",
    "_select_recovery_candidates",
    "_acquire_recovery_ownership",
    "TriageCycleReport",
    "run_triage_cycle",
]


async def _claim_new_event(session: AsyncSession, event_id: UUID, *, now: datetime) -> bool:
    """Atomically claim one NEW NewsEvent -> PROCESSING (Contract §7.2 step 1).

    A single, atomic conditional UPDATE - `updated_at` is set explicitly to `now`
    (rather than relied upon implicitly via the column's own onupdate=func.now(),
    though the Contract confirms either is compliant) so a claim's exact timestamp
    is deterministic and test-controllable, not dependent on the database server's
    own wall clock.

    Returns True iff this call's own attempt affected the row (won the race - the
    event was still NEW). Returns False iff another instance already claimed it (or
    it was never NEW) - not an error; the caller MUST skip this event silently
    (Contract §18) and MUST NOT proceed to Triage or create_task() for it.

    The caller MUST commit immediately after a True result, before doing anything
    else for this event (Contract §7.5's "claim, already committed in step 1").
    """
    result = await session.execute(
        update(NewsEvent)
        .where(NewsEvent.id == event_id, NewsEvent.status == EventStatus.NEW)
        .values(status=EventStatus.PROCESSING, updated_at=now)
    )
    return result.rowcount == 1  # type: ignore[attr-defined]  # CursorResult at runtime for an UPDATE; Result[Any]'s stub doesn't expose it statically


async def _select_recovery_candidates(
    session: AsyncSession, *, now: datetime, staleness_threshold_seconds: int
) -> list[NewsEvent]:
    """Select PROCESSING NewsEvent rows eligible for stale-claim recovery (Contract
    §7.6's eligibility invariant - all three conditions required, evaluated in this
    exact precedence order):

        status == PROCESSING
        AND no EditorialTask already exists for it (any status - Phase 15 M1;
            was CREATED/RUNNING-only, see _find_active_task()'s own docstring
            for why that let a completed/failed sibling go unnoticed)
        AND (now - updated_at) > staleness_threshold_seconds

    `PROCESSING` + no-existing-task alone is NOT sufficient - a legitimately in-flight
    claim also transiently has no task yet; only once its age exceeds the
    threshold does it become a candidate. The existing-task check takes precedence over
    staleness and is evaluated first per candidate (an event with an existing task is
    never a candidate, regardless of how old `updated_at` is) - _find_active_task()
    is reused unmodified here (not reimplemented as a second, parallel query), exactly
    as the Contract requires; Phase 15 M1 fixed its one shared implementation, not this
    call site.

    Age is computed with strict inequality (`>`, not `>=`) - an event whose age
    exactly equals the threshold is treated as NOT yet stale (Contract §7.6 rule 3,
    the safe, non-recovery direction).
    """
    result = await session.execute(select(NewsEvent).where(NewsEvent.status == EventStatus.PROCESSING))
    threshold = timedelta(seconds=staleness_threshold_seconds)

    candidates: list[NewsEvent] = []
    for event in result.scalars().all():
        age = now - event.updated_at
        if age <= threshold:
            continue
        active_task = await _find_active_task(session, event.id, WorkflowType.NEWS_ANALYSIS)
        if active_task is not None:
            continue
        candidates.append(event)
    return candidates


async def _acquire_recovery_ownership(
    session: AsyncSession, event_id: UUID, observed_updated_at: datetime, *, now: datetime
) -> bool:
    """Atomically acquire recovery ownership of one stale PROCESSING NewsEvent
    (Contract §7.6's CAS mechanism), guarded by the exact `updated_at` value observed
    when the candidate was selected.

    A single, atomic conditional UPDATE: `status = 'PROCESSING' AND updated_at =
    observed_updated_at`, advancing `updated_at` to `now` on success. This guard
    condition is re-evaluated by the database atomically at execution time, so a
    successful acquisition IS the proof that status was still PROCESSING and
    updated_at had not moved since selection - the structural TOCTOU re-check the
    Contract describes, not a separate step.

    Returns True iff this call's own attempt affected the row (won). Returns False
    iff another instance already acquired ownership (or the row otherwise changed) -
    not an error; the caller MUST skip this event silently, exactly as for a lost
    NEW claim, and MUST NOT proceed to Triage or create_task() for it.

    The caller MUST commit immediately after a True result, before doing anything
    else for this event - identical discipline to _claim_new_event().
    """
    result = await session.execute(
        update(NewsEvent)
        .where(
            NewsEvent.id == event_id,
            NewsEvent.status == EventStatus.PROCESSING,
            NewsEvent.updated_at == observed_updated_at,
        )
        .values(updated_at=now)
    )
    return result.rowcount == 1  # type: ignore[attr-defined]  # CursorResult at runtime for an UPDATE; Result[Any]'s stub doesn't expose it statically


@dataclass
class TriageCycleReport:
    """Summary of a single Triage cycle, used for logging - mirrors
    services/collector.py's CollectionReport pattern."""

    events_claimed: int = 0
    events_recovered: int = 0
    tasks_created: int = 0
    claim_races_lost: int = 0
    duplicate_active_task_outcomes: int = 0
    events_rejected_invalid_title: int = 0
    other_failures: int = 0
    # Phase 18.10 M1/M2 (Story Memory, story_memory_mode != "off" only - all zero when "off").
    # `received_events` is a derived property, not a separate counter (see below).
    # `exact_duplicates` is intentionally NOT tracked here - it already exists, unchanged, as
    # services/collector.py::CollectionReport.duplicates_skipped (exact-hash dedup happens at
    # collection time, before an event ever reaches Triage) - cross-module composition, not
    # duplicated. `ignored_events` aliases events_rejected_invalid_title (also unchanged).
    story_new: int = 0
    story_updates: int = 0
    story_supporting_sources: int = 0
    story_semantic_duplicates: int = 0
    story_uncertain_matches: int = 0
    # Phase 20 M8: RELATED_STORY (services/story_memory.py) existed since M5 but was never wired
    # into this report - a real, narrow observability gap found and fixed during M8's own
    # verification pass, not a new feature. story_memory_mode stays "off" in the real .env, so
    # this had zero live effect; it only matters once shadow mode is later enabled.
    story_related: int = 0
    # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1: count of events whose editorial task was
    # ACTUALLY suppressed by the constrained enforcement predicate (0 unless the flag
    # story_continuity_p0_constrained_enforcement_enabled is True and a near-certain
    # DUPLICATE_NO_DELTA passed every gate). Always 0 when story_memory_mode == "off".
    story_tasks_suppressed: int = 0

    @property
    def received_events(self) -> int:
        return self.events_claimed + self.events_recovered


async def _apply_story_memory(
    session: AsyncSession, event: NewsEvent, report: TriageCycleReport
) -> bool:
    """Phase 18.10 M1/M2: match `event` against recent same-category stories
    (services/story_memory.py), persist the result as a NewsEventStoryLink row (never as columns
    on `event` itself - see database/models/news_event.py's own comment on why), and create/
    update the `stories` row as needed. Never raises for a well-formed event (mirrors
    decide_triage()'s own "MUST NOT raise for well-formed input" contract) - any failure here is
    a bug to fix, not a reason to fall back silently, so this deliberately does not have its own
    try/except; a real failure (including "table does not exist" if story_memory_mode is enabled
    before the Phase 18.10 migration has been applied) surfaces via `_run_phase_b()`'s own outer
    `except Exception` handler, exactly like a Triage or create_task() failure would - the event
    is left PROCESSING with no task, automatically eligible for recovery once the migration
    lands, never silently corrupted.

    Owns no commit of its own - all mutations here (the new/updated Story row, the new
    NewsEventStoryLink row) are committed atomically together with create_task()'s own
    EditorialTask insert, in the same transaction `_run_phase_b()` already manages.

    Phase 20 M11.1 (Story Identity Invariant, docs/phase20_m11_1_story_identity_investigation.md):
    a real NewsEvent must not permanently lose the ability to become the root/anchor of its own
    Story merely because its first comparison against older Stories is uncertain or only loosely
    related. `NEW_STORY` always creates its own Story, as before. `RELATED_STORY` now ALSO always
    creates its own Story - it is already, by construction in services/story_memory.py, a
    confident signal that this is a DIFFERENT story (combined score below even the low threshold);
    the only bug was never actually creating that different story. `UNCERTAIN_MATCH` is genuinely
    ambiguous, so it is split by `entity_overlap` (a value services/story_memory.py's
    score_candidate() already computes for every match, not a new signal) against the same
    `_RELATED_STORY_ENTITY_FLOOR` constant RELATED_STORY itself already uses (not a new,
    uncalibrated threshold): real entity signal (>= the floor, e.g. the Moscow pair's 0.4) keeps
    today's attach-without-bumping behavior, since the candidate genuinely might be the same
    story; weak/coincidental overlap (< the floor, e.g. a genuinely new story's root event
    crossing the low bar by chance against something unrelated) creates its own Story instead.
    `STORY_UPDATE`/`SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE` are unchanged - confirmed same-story
    outcomes always attach and bump `event_count`.

    No explicit merge/convergence machinery is added - a later, more decisive event scored
    against a fragmented provisional Story (which participates in candidate retrieval exactly
    like any other Story) can still attach to it normally via the confirmed-outcome path above,
    naturally converging the cluster's future growth without retroactively re-parenting already-
    linked events (out of scope as more than "the smallest fix")."""
    # Phase 23 shadow calibration: Google News RSS titles append a publisher attribution
    # suffix (e.g. " - Vietnam.vn"). That suffix is source provenance, not Story identity.
    # Strip it only when real provenance proves this is a Google News wrapper; title shape
    # alone is intentionally insufficient (same safety rule as Story Delta).
    #
    # Phase V2.22: provenance now also checks the event's own NewsSource feed URL, not only the
    # article's own (possibly already-redirect-resolved) URL - see services/text_normalization.py
    # ::is_google_news_provenance()'s own docstring for the real production evidence (a "Google
    # News RU" NewsSource whose collected articles kept their "- 3DNews"-style suffix uncorrupted
    # because the per-article URL alone no longer pointed at news.google.com).
    source = await session.get(NewsSource, event.source_id)
    is_google_news = is_google_news_provenance(event.url, source.url if source is not None else None)
    story_match_title = strip_google_news_title_suffix(event.title) if is_google_news else event.title
    signature, result = await match_story(
        session, title=story_match_title, category=event.category
    )

    creates_own_story = result.outcome in (NEW_STORY, RELATED_STORY) or (
        result.outcome == UNCERTAIN_MATCH and result.entity_overlap < _OWN_STORY_ENTITY_FLOOR
    ) or (
        # STORY-CONTINUITY-P0: an uncertain match whose only shared identity is an
        # organization/generic token (no distinctive overlap) is not the same story - it gets
        # its own Story, not even a provisional link.
        result.outcome == UNCERTAIN_MATCH and result.company_only_match
        and result.distinctive_overlap == 0.0
    )

    if creates_own_story:
        # Phase V2.22: stores the SAME comparison title `signature` (entities/keywords) was
        # already derived from - previously stored raw `event.title` here while `signature`
        # came from `story_match_title`, so a Google-News-sourced story-creating event ended up
        # with clean entities/keywords but a suffix-corrupted `Story.title`, silently degrading
        # every LATER title_overlap comparison against this Story for its entire lifetime (real
        # production evidence: V2.22 Cluster B). `Story.title` and `Story.entities`/`keywords`
        # must always be derived from the same text.
        story = Story(
            id=uuid4(),
            title=story_match_title,
            category=event.category,
            entities=signature.entities,
            keywords=signature.keywords,
            topic_bucket=signature.topic_bucket,
            first_event_id=event.id,
            event_count=1,
        )
        session.add(story)
        story_id = story.id
    else:
        # STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE, or a strong-entity-overlap
        # UNCERTAIN_MATCH - link the event to the matched story for observability; only the three
        # confirmed-same-story outcomes bump event_count (an uncertain match, even a strong one,
        # is, definitionally, not confident enough to count as a confirmed continuation of that
        # story's own event history).
        assert result.matched_story_id is not None  # guaranteed whenever outcome != NEW_STORY/RELATED_STORY
        story_id = result.matched_story_id
        matched_story = await session.get(Story, result.matched_story_id)
        assert matched_story is not None  # match_story() only returns an id it just queried
        if result.outcome in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE):
            matched_story.event_count += 1

    if result.outcome == NEW_STORY:
        report.story_new += 1
    elif result.outcome == STORY_UPDATE:
        report.story_updates += 1
    elif result.outcome == SUPPORTING_SOURCE:
        report.story_supporting_sources += 1
    elif result.outcome == SEMANTIC_DUPLICATE:
        report.story_semantic_duplicates += 1
    elif result.outcome == UNCERTAIN_MATCH:
        report.story_uncertain_matches += 1
    elif result.outcome == RELATED_STORY:
        report.story_related += 1

    logger.info(
        "phase18_10_story_memory_match",
        extra={
            "event_id": str(event.id),
            "outcome": result.outcome,
            "matched_story_id": str(story_id) if story_id else None,
            "confidence": result.confidence,
            "reason": result.similarity_reason,
        },
    )

    # STORY-CONTINUITY-P0 (2026-09): compute the ONE deterministic continuity decision and its
    # delta evidence, and persist it onto the NewsEventStoryLink row via the canonical creation
    # path below (columns already exist in the production DB - no migration). The delta engine +
    # confidence band + would_suppress diagnostics that were LOGGED-ONLY before this phase now
    # feed classify_continuity() and are persisted. `gate_delta_by_identity()` keeps the same
    # "identity before delta" protection (Phase 20 Checkpoint 6). Everything here is diagnostic:
    # create_task() below still runs unconditionally - P0 never suppresses a send.
    delta_classification: str | None = None
    confidence_band: str | None = None
    would_suppress_flag: bool | None = None
    delta_reason = ""
    identity_assessment = None
    # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1: recomputed deterministically below against
    # the matched Story's own prior events (never inferred from the match score alone - spec §2).
    exact_normalized_title_match = False
    if creates_own_story:
        continuity = classify_continuity(match_result=result, delta_result=None, creates_own_story=True)
    else:
        delta = None
        try:
            delta = await compute_story_delta(
                session, new_title=event.title, story_id=story_id, exclude_event_id=event.id,
            )
            delta = gate_delta_by_identity(
                delta, has_distinctive_shared_entity=result.has_distinctive_shared_entity
            )
            confidence_band = compute_confidence_band(result.confidence)
            would_suppress_flag = compute_would_suppress(
                match_type=result.outcome, confidence_band=confidence_band,
                delta_classification=delta.classification,
            )
            delta_reason = delta.reason
        except Exception:
            logger.warning(
                "story_continuity_delta_failed",
                extra={"event_id": str(event.id), "story_id": str(story_id)},
            )
        # STORY-CONTINUITY-P0.1: the abstract-quality / stable-document-identity firewall. Reads
        # the matched Story's other events' (title, url) - the same bounded, indexed set the
        # delta query above already touches - so a confident same-Story classification cannot
        # rest on unsafe similarity between abstract-like titles (real production evidence:
        # unrelated arXiv papers sharing templated abstract openings). Purely diagnostic here:
        # create_task() below still runs unconditionally.
        prior_doc_rows = (
            await session.execute(
                select(NewsEvent.title, NewsEvent.url)
                .join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
                .where(
                    NewsEventStoryLink.story_id == story_id,
                    NewsEvent.id != event.id,
                )
            )
        ).all()
        identity_assessment = assess_continuity_identity(
            new_title=event.title,
            new_url=event.url,
            new_summary=event.summary,
            prior_documents=[(row.title, row.url) for row in prior_doc_rows],
            match_is_exact_title_identity=(
                result.outcome == SEMANTIC_DUPLICATE and result.confidence >= 1.0 - 1e-9
            ),
        )
        # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1: an independent, deterministic
        # exact-normalized-title equality check against the matched Story's OWN prior events
        # (same bounded rows the identity assessment already read). Whitespace-collapse +
        # casefold only - byte-identical to services/story_memory.py's own exact-title
        # short-circuit. NOT the score-based `match_is_exact_title_identity` above, which a
        # capped-at-1.0 near-verbatim scored match could also satisfy.
        _new_norm_title = normalize_title_for_exact_match(event.title)
        exact_normalized_title_match = any(
            _new_norm_title == normalize_title_for_exact_match(row.title)
            for row in prior_doc_rows
        )
        continuity = classify_continuity(
            match_result=result, delta_result=delta, creates_own_story=False,
            identity_assessment=identity_assessment,
        )
        delta_classification = continuity.delta_class
        # Section 8 - the persisted shadow record must model future enforcement safety: a match
        # the firewall demoted to AMBIGUOUS must never carry would_suppress=True (an upstream
        # polluted Story must not be able to make an event suppression-eligible).
        if continuity.guard_forced_fail_open:
            would_suppress_flag = False

    # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1: the ONE narrow enforcement predicate. Pure;
    # fails open on anything that is not a near-certain, identity-backed, delta-free
    # DUPLICATE_NO_DELTA. `enforcement.suppress` is the only thing that changes runtime behaviour
    # (create_task() is skipped for this event by _run_phase_b()); the NewsEventStoryLink row
    # and its full audit evidence are still written either way.
    enforcement = evaluate_constrained_enforcement(
        enabled=settings.story_continuity_p0_constrained_enforcement_enabled,
        continuity=continuity,
        would_suppress_flag=would_suppress_flag,
        identity_assessment=identity_assessment,
        exact_normalized_title_match=exact_normalized_title_match,
    )

    audit_codes = list(continuity.reason_codes)
    if enforcement.suppress:
        audit_codes = [*audit_codes, "actually_suppressed", f"enforced:{enforcement.evidence['policy_version']}"]

    link = NewsEventStoryLink(
        news_event_id=event.id, story_id=story_id,
        match_type=result.outcome, match_score=result.confidence,
        delta_classification=delta_classification,
        confidence_band=confidence_band,
        would_suppress=would_suppress_flag,
        final_decision=continuity.outcome,
        decision_source="story_continuity_p0",
        decision_confidence=continuity.match_score,
        new_facts=list(continuity.new_signals) or None,
        material_delta=audit_codes or None,
        decision_reason=(
            f"{continuity.outcome} suppression_eligible={continuity.suppression_eligible} "
            f"guard_forced_fail_open={continuity.guard_forced_fail_open} "
            f"title_quality={continuity.title_semantic_quality} "
            f"identity_status={continuity.stable_identity_status} "
            f"actually_suppressed={enforcement.suppress} enforcement={enforcement.reason} "
            f"exact_norm_title_match={exact_normalized_title_match} "
            f"components={continuity.match_components} delta={delta_reason}"[:2000]
        ),
    )
    session.add(link)

    # Observability (Section 17) - concise structured diagnostics, no article bodies, no secrets.
    logger.info(
        "story_continuity_decision",
        extra={
            "event_id": str(event.id),
            "story_id": str(story_id),
            "match_type": result.outcome,
            "continuity_outcome": continuity.outcome,
            "matched_story_id": str(continuity.matched_story_id) if continuity.matched_story_id else None,
            "match_score": continuity.match_score,
            "confidence_band": continuity.confidence_band,
            "distinctive_entity_overlap": result.distinctive_overlap,
            "supporting_entity_overlap": result.supporting_overlap,
            "generic_entity_overlap": result.generic_overlap,
            "company_only_match": result.company_only_match,
            "version_incompatible": result.version_incompatible,
            "delta_class": continuity.delta_class,
            "would_suppress": would_suppress_flag,
            "suppression_eligible": continuity.suppression_eligible,
            "reason_codes": list(continuity.reason_codes),
            # STORY-CONTINUITY-P0.1 firewall diagnostics (Section 12) - bounded scalars only.
            "title_semantic_quality": continuity.title_semantic_quality,
            "stable_identity_status": continuity.stable_identity_status,
            "stable_identity_namespace": (
                identity_assessment.identity_namespace if identity_assessment is not None else None
            ),
            "guard_forced_fail_open": continuity.guard_forced_fail_open,
            # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1 - bounded scalars only.
            "actually_suppressed": enforcement.suppress,
            "enforcement_reason": enforcement.reason,
            "enforcement_policy": enforcement.evidence["policy_version"],
            "exact_normalized_title_match": exact_normalized_title_match,
        },
    )

    if enforcement.suppress:
        report.story_tasks_suppressed += 1
        # A dedicated record for every ACTUAL suppression - full structured evidence so the
        # canary audit can reconstruct exactly why the task was not created (spec §9/§17).
        logger.info(
            "story_continuity_task_suppressed",
            extra={
                "event_id": str(event.id),
                "story_id": str(story_id),
                "continuity_outcome": continuity.outcome,
                "match_score": continuity.match_score,
                "actual_suppression_reason": enforcement.reason,
                **{f"ev_{k}": v for k, v in enforcement.evidence.items()},
            },
        )

    return enforcement.suppress


async def _run_phase_b(session: AsyncSession, event_id: UUID, report: TriageCycleReport) -> None:
    """Phase B - post-claim processing (Contract §7.2 steps 2-3): load the event's
    NewsSource, run deterministic Triage, call the existing, unmodified create_task().

    Runs only after Phase A's commit has already succeeded (see run_triage_cycle()).
    Any exception here triggers `await session.rollback()` before returning -
    **binding invariant**: one event's post-claim failure MUST NOT leave the
    SQLAlchemy session in a failed-transaction state that breaks the processing of
    later events in the same batch. This rollback discards only this event's own
    (uncommitted) Phase B work; it cannot and does not undo Phase A's already-
    committed claim/ownership, which was finalized in its own, separate, prior
    transaction before this function was ever called. The residual state this
    produces on failure - PROCESSING, no active task - is the same, already-approved,
    staleness-gated recovery path this module already implements (§7.5, §7.6),
    not a new mechanism.
    """
    try:
        reference_now = datetime.now(timezone.utc)
        event = await session.get(NewsEvent, event_id)
        assert event is not None  # just claimed/recovered this exact event; it cannot have vanished

        # Phase 15 M1: cheap deterministic gate, before Triage/create_task() ever run - a
        # malformed title (raw HTML fragment, empty, bare URL) must not reach NEWS_ANALYSIS's
        # LLM calls just because it scored low; scoring is not a reliable filter for this
        # (Phase 15 M0: a malformed title scored 78 and was delivered). Defense-in-depth for
        # events collected before services.cleaning's own ingestion-time check existed.
        # Reuses the existing EventStatus.REJECTED lifecycle state - no new status, no new
        # table. decide_triage()'s own closed input contract is untouched: this check runs
        # before it and never becomes one of its inputs.
        if not is_valid_title(event.title):
            event.status = EventStatus.REJECTED
            await session.commit()
            report.events_rejected_invalid_title += 1
            logger.info(
                "phase15_event_rejected_invalid_title",
                extra={"event_id": str(event_id), "source_id": str(event.source_id)},
            )
            return

        # Phase 18.10 M1/M2: Story Memory, immediately after the title gate above - the same
        # "cheap deterministic check before any paid work" seam, since this too is fully
        # deterministic (no LLM call, services/story_memory.py's own module docstring). A no-op
        # when story_memory_mode == "off" (the default) - zero extra queries, byte-identical to
        # pre-18.10 behavior. In "shadow" the match result is persisted for observability only.
        # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1: _apply_story_memory() now RETURNS whether
        # this event's editorial task must be suppressed (True only when the constrained
        # enforcement flag is on AND a near-certain, identity-backed, delta-free DUPLICATE_NO_DELTA
        # passed every gate). Default False - byte-identical to shadow behaviour when the flag is
        # off.
        suppress_editorial_task = False
        if settings.story_memory_mode != "off":
            suppress_editorial_task = await _apply_story_memory(session, event, report)

        source = await session.get(NewsSource, event.source_id)
        reliability_score = source.reliability_score if source is not None else None

        triage_result = decide_triage(
            event.published_at, event.collected_at, reliability_score, reference_now
        )
        logger.info(
            "phase9_triage_decision",
            extra={
                "event_id": str(event_id),
                "source_id": str(event.source_id),
                "reference_now": reference_now.isoformat(),
                **triage_result.explanation,
            },
        )

        if suppress_editorial_task:
            # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1: the ONLY authorized side effect -
            # do not create a new duplicate editorial task for this near-certain DUPLICATE_NO_
            # DELTA. create_task() normally commits this transaction; since we skip it, commit
            # explicitly so the NewsEventStoryLink + Story row (the full audit evidence written
            # in _apply_story_memory) still persist. The NewsEvent, Story membership, history
            # and prior tasks are untouched; no publication behaviour changes.
            await session.commit()
            logger.info(
                "phase9_editorial_task_suppressed_by_story_continuity",
                extra={"event_id": str(event_id), "source_id": str(event.source_id)},
            )
        else:
            command = EditorialTaskCreate(
                event_id=event_id,
                workflow_type=WorkflowType.NEWS_ANALYSIS,
                priority=triage_result.priority,
            )
            await create_task(session, command)
            report.tasks_created += 1

    except DuplicateActiveTaskError:
        # Contract §7.5 point 2: not a failure - another instance already created the
        # active task for this event (a retry, or the narrow "stolen healthy worker"
        # case §7.6 discloses). The event's PROCESSING status is now genuinely
        # accurate; nothing further is required. Rolled back anyway, defensively and
        # uniformly with the branch below, even though no SQL statement actually
        # failed here (create_task()'s own _find_active_task() check is a plain
        # SELECT) - this avoids a fragile special case.
        report.duplicate_active_task_outcomes += 1
        logger.info("phase9_duplicate_active_task", extra={"event_id": str(event_id)})
        await session.rollback()

    except Exception:
        # Any other failure (source/event loading, Triage - which MUST NOT raise for
        # well-formed input, or create_task() itself): the event remains PROCESSING
        # with no active task, MUST be logged, and MUST NOT be treated as processed
        # (Contract §18). It is automatically eligible for recovery on a future pass,
        # once stale.
        report.other_failures += 1
        logger.exception("phase9_triage_phase_b_failed", extra={"event_id": str(event_id)})
        await session.rollback()


async def run_triage_cycle(
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> TriageCycleReport:
    """Run one Triage pass over every eligible NewsEvent (Contract §2.3/§7).

    One shared AsyncSession for the whole batch (mirroring services/collector.py's
    single-session-per-cycle shape), but - unlike collector.py, which commits once per
    *source* (which may hold many items) - this function commits and rolls back once
    per *event*, because each event's ownership claim, not the batch as a whole, is
    the atomic unit of correctness this Contract defines.

    For each eligible event, exactly two phases:

    Phase A - ownership acquisition (commit-or-skip, never partial):
        Normal path: _claim_new_event(); on success, `await session.commit()`
        *immediately* - this is the durable fact Contract §7.5 calls "the claim,
        already committed in step 1." On failure (lost the race), skip silently -
        no exception, no log entry (Contract §18's "not an error" classification) -
        and do NOT proceed to Phase B.
        Recovery path: identical shape, via _acquire_recovery_ownership().
        A losing claimant, either path, MUST NOT run Triage or call create_task() -
        enforced structurally here: Phase B is only ever reached after a successful
        Phase A commit.

    Phase B - post-claim processing: see _run_phase_b()'s own docstring for its
    commit/rollback discipline.

    No distributed transaction, no cross-session coordination, and no change to
    session ownership is introduced anywhere in this discipline - every commit/
    rollback is a plain, single-session operation on the one AsyncSession this
    function owns for the whole batch; create_task()'s own internal commit is
    untouched and unmodified.
    """
    report = TriageCycleReport()
    threshold_seconds = settings.stale_processing_threshold_seconds

    async with session_factory() as session:
        now = datetime.now(timezone.utc)

        new_result = await session.execute(select(NewsEvent).where(NewsEvent.status == EventStatus.NEW))
        new_event_ids = [event.id for event in new_result.scalars().all()]

        recovery_candidates = await _select_recovery_candidates(
            session, now=now, staleness_threshold_seconds=threshold_seconds
        )
        recovery_targets = [(event.id, event.updated_at) for event in recovery_candidates]

        for event_id in new_event_ids:
            claim_now = datetime.now(timezone.utc)
            won = await _claim_new_event(session, event_id, now=claim_now)
            if not won:
                report.claim_races_lost += 1
                continue
            await session.commit()
            report.events_claimed += 1
            await _run_phase_b(session, event_id, report)

        for event_id, observed_updated_at in recovery_targets:
            recovery_now = datetime.now(timezone.utc)
            won = await _acquire_recovery_ownership(session, event_id, observed_updated_at, now=recovery_now)
            if not won:
                report.claim_races_lost += 1
                continue
            await session.commit()
            report.events_recovered += 1
            await _run_phase_b(session, event_id, report)

    logger.info(
        "phase9_triage_cycle_finished",
        extra={
            "events_claimed": report.events_claimed,
            "events_recovered": report.events_recovered,
            "tasks_created": report.tasks_created,
            "claim_races_lost": report.claim_races_lost,
            "duplicate_active_task_outcomes": report.duplicate_active_task_outcomes,
            "events_rejected_invalid_title": report.events_rejected_invalid_title,
            "other_failures": report.other_failures,
            "received_events": report.received_events,
            "story_new": report.story_new,
            "story_updates": report.story_updates,
            "story_supporting_sources": report.story_supporting_sources,
            "story_semantic_duplicates": report.story_semantic_duplicates,
            "story_uncertain_matches": report.story_uncertain_matches,
            "story_related": report.story_related,
            "story_tasks_suppressed": report.story_tasks_suppressed,
        },
    )
    return report
