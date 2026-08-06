"""ContentDraftService: the only component authorized to create a ContentDraft row (Phase 10,
docs/phase10_production_content_pipeline_architecture_contract.md §7/§7.1).

Class-based, constructor-injected with the same AsyncSession the caller already used for
WorkflowRunner.run() - mirrors services/budget_guard.py's RedisBudgetGuard constructor-injection
shape (§7.1's own precedent), not the plain-function style of services/workflow_service.py.

Called by the caller (Milestone 4's CLI script) only after WorkflowRunner.run() has returned a
COMPLETED WorkflowRunResult - never before, never for a FAILED result (§7.1, §9). This module
does not itself branch on `result.status`: a FAILED run has no "copywriting" step_results entry
to find (the chain never reaches that step, or copywriting itself failed), so calling this on a
FAILED result fails loudly via _copywriting_output()'s own lookup, rather than silently
persisting wrong or partial data.
"""
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_quote import ContentDraftQuote
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.news_event import NewsEvent
from database.models.story_link import NewsEventStoryLink
from schemas.content_draft import ContentDraftRead
from schemas.workflow import WorkflowRunResult
from services.content_quality_gates import evaluate_content_quality_gates
from services.evidence_package import build_evidence_package
from services.quote_verification import verify_quote
from services.story_memory import NEW_STORY, UNCERTAIN_MATCH

logger = logging.getLogger(__name__)

# Phase 18.10 M4: hashtags are a mandatory, unconditional removal (not a rollout) - modern
# Telegram media channels don't use hashtag blocks. This is a small, deterministic regression
# guard, not a calibrated gate, so it deliberately has no off/shadow/enforce mode: there is no
# meaningful "off" state for "never contains a hashtag," and nothing here needs calibration.
_HASHTAG_PATTERN = re.compile(r"#\w+")


def check_no_hashtags(title: str | None, body: str | None) -> bool:
    """Pure. True when neither `title` nor `body` contains a hashtag-shaped token. The primary
    prevention is upstream (the copywriting prompt no longer asks for hashtags, and this service
    never persists the legacy `hashtags` field on new drafts) - this is defense-in-depth against
    a hashtag slipping into the free-text title/body themselves."""
    return not _HASHTAG_PATTERN.search(title or "") and not _HASHTAG_PATTERN.search(body or "")


def _copywriting_output(result: WorkflowRunResult) -> dict[str, Any]:
    """Locate the "copywriting" entry in `result.step_results` (a list, per
    schemas/workflow.py's WorkflowStepResult shape) and return its `.result` dict.

    Raises ValueError if absent - a real, reachable case only when this is called on a result
    that never reached a successful "copywriting" step (misuse of the calling convention above),
    never silently substituted with empty/None values (Contract §7.1: no reformatting, no
    silent discarding of required structured content)."""
    for step_result in result.step_results:
        if step_result.step_name == "copywriting" and step_result.status == "SUCCESS":
            if step_result.result is None:
                raise ValueError(
                    f"WorkflowRunResult for task {result.task_id} has a SUCCESS 'copywriting' "
                    "step with no result payload."
                )
            return step_result.result
    raise ValueError(
        f"WorkflowRunResult for task {result.task_id} has no successful 'copywriting' step "
        "result - create_from_result() MUST only be called on a COMPLETED result."
    )


def _fact_safety_status(result: WorkflowRunResult) -> str | None:
    """Phase 15 M5: locate the "quality" step's `fact_safety.status` ("pass"/"review"/"block"),
    if present - `None` when fact safety never ran (`fact_safety_mode == "off"`, or a historical
    task predating M5) or the "quality" step itself is absent, mirroring `_copywriting_output()`'s
    own lookup shape but never raising: whether fact safety produced a result is optional
    metadata for this function's own status-setting decision below, not a requirement for
    ContentDraft persistence to succeed at all (that contract remains "copywriting" alone,
    unchanged from Phase 10)."""
    for step_result in result.step_results:
        if step_result.step_name == "quality" and step_result.status == "SUCCESS" and step_result.result:
            fact_safety = step_result.result.get("fact_safety")
            if isinstance(fact_safety, dict):
                status = fact_safety.get("status")
                if isinstance(status, str):
                    return status
    return None


def _draft_status_for(fact_safety_status: str | None) -> str:
    """Phase 15 M5.8 enforcement design: outside `fact_safety_mode == "enforce"`, this always
    returns "draft" - byte-identical to pre-M5 behavior (shadow mode must never change delivery
    or persistence, per M5.6). Only in "enforce" mode does a "review"/"block" fact-safety verdict
    change the persisted `ContentDraft.status` - free-text column (`database/models/
    content_draft.py`'s own documented "not a constrained enum" design), so this needs no
    migration. This is visibility, not deletion: the draft row, its full text, and the
    fact-safety findings in `EditorialTask.workflow` all remain fully queryable - only
    `worker/content_cycle.py`'s own delivery decision (a separate change) actually withholds the
    live Telegram send."""
    if settings.fact_safety_mode != "enforce" or fact_safety_status is None:
        return "draft"
    if fact_safety_status == "block":
        return "draft_blocked_fact_safety"
    if fact_safety_status == "review":
        return "draft_review_fact_safety"
    return "draft"


def _to_read_schema(draft: ContentDraft) -> ContentDraftRead:
    """Build ContentDraftRead from an ORM row - mirrors services/workflow_service.py's
    _to_read_schema() shape exactly."""
    return ContentDraftRead(
        id=draft.id,
        task_id=draft.task_id,
        type=draft.type,
        title=draft.title,
        body=draft.body,
        # ContentDraft.hashtags is typed Mapped[dict | None] (pre-existing ORM imprecision -
        # database/models/content_draft.py's own JSON column stores whatever's assigned; this
        # Capability's output schema (Contract §5) guarantees a list at runtime, never a dict).
        hashtags=draft.hashtags,  # type: ignore[arg-type]
        version=draft.version,
        status=draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


class ContentDraftService:
    """Constructed with the same AsyncSession the caller already used for
    WorkflowRunner.run() - never opens a new session or connection (Contract §7.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_result(
        self, task_id: UUID, result: WorkflowRunResult, *, event_id: UUID | None = None
    ) -> ContentDraftRead:
        """Create exactly one ContentDraft row from `result`'s "copywriting" step output.

        Owns its own, single, deterministic commit - a separate transaction from
        WorkflowRunner.run()'s own already-closed final commit. Raises uncaught on failure
        (Contract §7.1: MUST NOT swallow). Phase 10 writes exactly one status ("draft"), one
        version (1), one type (ContentType.POST) - no migration, no schema change. Phase 15 M5:
        `status` varies from "draft" only when `fact_safety_mode == "enforce"` AND the "quality"
        step's fact-safety verdict is "review"/"block" - see `_draft_status_for()`'s own
        docstring. In every other case (mode "off"/"shadow", or a "pass" verdict) this is
        byte-identical to the pre-M5 behavior.

        `event_id` (Phase 18.10 M3, optional, additive): when provided AND the source NewsEvent
        has a NewsEventStoryLink (story_memory_mode was enabled at Triage time), also creates a
        ContentDraftStoryLink row in the same transaction - the input worker/content_cycle.py's
        reply-target determination (services/story_telegram_delivery.py) needs. `event_id=None`
        (every pre-18.10 caller) is byte-identical to before: no lookup, no new row, ever.
        """
        copywriting_output = _copywriting_output(result)
        title = copywriting_output["title"]
        body = copywriting_output["body"]
        # v4-only fields (Phase 18.10 M5/M6) - .get(), not [...], since a historical result
        # produced by a frozen earlier prompt version (v1/v2/v3) never has these keys at all;
        # None/absent degrades gracefully rather than raising.
        why_it_matters = copywriting_output.get("why_it_matters")
        what_happened = copywriting_output.get("what_happened")
        quote = copywriting_output.get("quote")

        # Phase 18.10 M4 quality check: a draft containing a hashtag is never persisted -
        # raises loudly (this module's own established "MUST NOT swallow" convention), never
        # silently stripped, since a hashtag reaching this point means the upstream prompt/
        # generation contract was violated and needs investigation, not silent correction.
        if not check_no_hashtags(title, body):
            raise ValueError(
                f"QUALITY CHECK FAILED: WorkflowRunResult for task {result.task_id} produced a "
                "title/body containing a hashtag - hashtags are no longer permitted in generated "
                "content (Phase 18.10 M4)."
            )

        news_event = await self._session.get(NewsEvent, event_id) if event_id is not None else None

        # Phase 19 M1/M2 (services/evidence_package.py): source_content is only ever upgraded to
        # the full, cleaned article when article_acquisition_mode == "enforce" - byte-identical
        # to news_event.content (the original source) in every other case, including when
        # article_acquisition_mode == "shadow" (persists evidence for observability, changes
        # nothing here). SAVEPOINT-isolated (begin_nested): "enforce" set before the Phase 19 M1
        # migration has been applied must degrade to news_event.content, never crash draft
        # creation - mirrors capabilities/executor.py's identical guard.
        source_content = news_event.content if news_event is not None else None
        if news_event is not None and settings.article_acquisition_mode == "enforce":
            try:
                async with self._session.begin_nested():
                    evidence = await build_evidence_package(self._session, news_event)
                source_content = evidence.selected_editorial_text
            except Exception:
                logger.warning(
                    "article_evidence_package_unavailable_falling_back",
                    extra={"task_id": str(result.task_id), "event_id": str(event_id)},
                )

        # Phase 18.10 M5: verify any claimed quote against the source before it can ever be
        # persisted or rendered - fail closed (drop, never fabricate), per
        # services/quote_verification.py's own contract. A dropped quote never blocks the draft
        # itself; only the quote is discarded.
        verified_quote: dict[str, Any] | None = None
        if isinstance(quote, dict):
            quote_text = quote.get("text")
            if isinstance(quote_text, str) and verify_quote(quote_text, source_content):
                verified_quote = quote
            else:
                logger.warning(
                    "quote_failed_verification_dropped",
                    extra={"task_id": str(result.task_id), "quote_text": quote_text},
                )

        # Phase 18.10 M6/M7: deterministic quality gates - computed and logged for visibility,
        # never blocking persistence (these are heuristic editorial-quality signals, not the
        # hard, zero-false-positive hashtag requirement above) - matches
        # services/fact_safety.py's own "assess and record, don't silently reject" philosophy.
        quality_report = evaluate_content_quality_gates(
            title=title,
            body=body,
            why_it_matters=why_it_matters if isinstance(why_it_matters, str) else None,
            what_happened=what_happened if isinstance(what_happened, str) else None,
            source_title=news_event.title if news_event else None,
            quote_text=verified_quote.get("text") if verified_quote else None,
            quote_speaker=verified_quote.get("speaker") if verified_quote else None,
            source_content=source_content,
        )
        if not quality_report.passed:
            logger.warning(
                "content_quality_gate_failures",
                extra={"task_id": str(result.task_id), "failed_gates": quality_report.failed_gates},
            )

        draft = ContentDraft(
            id=uuid4(),
            task_id=task_id,
            type=ContentType.POST,
            title=title,
            body=body,
            # Phase 18.10 M4: hashtags are no longer populated on new drafts - modern Telegram
            # media channels don't use hashtag blocks. The column itself stays (nullable, no
            # migration) for backward compatibility with historical rows that still have them.
            hashtags=None,
            version=1,
            status=_draft_status_for(_fact_safety_status(result)),
        )
        self._session.add(draft)

        # Gated on story_memory_mode, not merely on event_id being provided (every real caller
        # always provides a real event_id) - mirrors services/editorial_scoring.py's own
        # apply_editorial_scoring_v2() identical fix: editorial_scoring_version == "v2"/normal
        # draft creation with story_memory_mode == "off" (the default) is a valid, already-
        # working combination that must never depend on this phase's migration being applied.
        if event_id is not None and settings.story_memory_mode != "off":
            story_link = await self._session.get(NewsEventStoryLink, event_id)
            if story_link is not None:
                self._session.add(
                    ContentDraftStoryLink(
                        content_draft_id=draft.id,
                        story_id=story_link.story_id,
                        # uncertain_match is deliberately never treated as a confirmed update
                        # (services/story_memory.py's own conservative design) - only a
                        # confident match type marks this draft for reply-context delivery.
                        is_story_update=story_link.match_type not in (NEW_STORY, UNCERTAIN_MATCH),
                        source_event_id=event_id,
                    )
                )

        await self._session.commit()
        await self._session.refresh(draft)

        # Phase 18.10 M5: the quote insert is deliberately a SEPARATE, later commit, not part of
        # the transaction above - unlike ContentDraftStoryLink (gated behind story_memory_mode,
        # an explicit opt-in), a verified quote can occur on the very first v4-prompted
        # generation with no separate settings flag to gate it behind. Isolating it here means a
        # quote-table failure (e.g. this phase's migration not yet applied) can never take down
        # the ContentDraft row that was just safely committed above - it only means this one
        # draft's quote goes unpersisted (logged, not silently lost from view - the verified
        # quote_text/speaker were already logged nowhere else, so this log line is the record).
        if verified_quote is not None:
            try:
                self._session.add(
                    ContentDraftQuote(
                        content_draft_id=draft.id,
                        quote_text=verified_quote["text"],
                        translated_text=verified_quote.get("translated_text"),
                        speaker=verified_quote.get("speaker") or "",
                        source_url=news_event.url if news_event else None,
                        source_published_at=news_event.published_at if news_event else None,
                    )
                )
                await self._session.commit()
            except Exception:
                await self._session.rollback()
                logger.exception(
                    "content_draft_quote_persistence_failed",
                    extra={
                        "draft_id": str(draft.id), "quote_text": verified_quote.get("text"),
                        "quote_speaker": verified_quote.get("speaker"),
                    },
                )

        return _to_read_schema(draft)
