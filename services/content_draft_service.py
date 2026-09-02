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
from services.content_quality_gates import check_quote_is_self_contained, evaluate_content_quality_gates
from services.evidence_package import build_evidence_package
from services.quote_verification import verify_quote
from services.story_memory import STORY_UPDATE
from services.story_telegram_delivery import get_root_delivery

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


# Phase I.1 (Approved EVENT_RECAP -> Final Post Authoring Core): a small, explicit, backward-
# compatible extension - a genuinely distinct step name ("final_post_authoring", never the literal
# "copywriting" - that would misrepresent this draft's real provenance for no benefit), with its
# own narrow `{title, body}` schema (prompts/final_post_authoring/v1.yaml's own output_schema -
# already exactly the two fields ContentDraft.title/.body need, no V6/V8-style multi-section
# reduction required). `_copywriting_output()`/`_extract_title_and_body()` above are completely
# unmodified by this addition.
def _final_post_authoring_output(result: WorkflowRunResult) -> dict[str, Any]:
    """Locate the "final_post_authoring" entry in `result.step_results` and return its `.result`
    dict. Raises ValueError if absent - mirrors `_copywriting_output()`'s own identical "MUST NOT
    swallow" philosophy."""
    for step_result in result.step_results:
        if step_result.step_name == "final_post_authoring" and step_result.status == "SUCCESS":
            if step_result.result is None:
                raise ValueError(
                    f"WorkflowRunResult for task {result.task_id} has a SUCCESS "
                    "'final_post_authoring' step with no result payload."
                )
            return step_result.result
    raise ValueError(
        f"WorkflowRunResult for task {result.task_id} has no successful 'final_post_authoring' "
        "step result - create_from_final_post_authoring_result() MUST only be called on a "
        "COMPLETED result."
    )


# Phase 23.1C: Copywriting schema versions this module knows how to reduce to the single
# (title, body) shape ContentDraft.title/.body has always expected - mirrors services/
# fact_safety.py::_extract_draft_text()'s own identical pattern (Phase 21), the smallest safe
# adapter for the same underlying problem: Fact Safety validates a draft's semantic content
# regardless of presentation schema, and this service persists it regardless of presentation
# schema - neither needed to be taught a second, separate notion of "what counts as a draft"
# beyond this one small extraction seam. V6 (`prompts/copywriting/v6.yaml`, verified directly
# against the real prompt file) has no `body` key at all - its long-form structure is `opening/
# context/why_it_matters/what_changed/what_happens_next/conclusion/what_remains_unknown/quote`.
# Natural prompt-declaration order (prompts/copywriting/v6.yaml's own field order) - the two
# optional fields are interleaved in their real narrative position (what_happens_next between
# what_changed and conclusion; what_remains_unknown after conclusion), not grouped separately, so
# the concatenated body reads in the same order a human editor encounters the sections.
_V6_REQUIRED_TEXT_KEYS = frozenset({"opening", "context", "why_it_matters", "what_changed", "conclusion"})
_V6_TEXT_KEYS_IN_ORDER: tuple[str, ...] = (
    "opening", "context", "why_it_matters", "what_changed", "what_happens_next", "conclusion",
    "what_remains_unknown",
)

# Phase 23.1J: V8 (`prompts/copywriting/v8.yaml`) - a deliberately smaller shape than V6/V7's
# seven/eight narrative sections. `main_body` is the only required text field beyond `title`;
# `ending`/`expandable_details` are optional, included here (for persistence/Fact-Safety
# completeness) only when actually populated - the Telegram presentation layer (services/
# news_telegram_presentation.py) is what decides whether `expandable_details` is visually hidden
# behind an expandable blockquote, never this persistence layer, which must see every claim
# regardless of how it will eventually be displayed.
_V8_REQUIRED_TEXT_KEYS = frozenset({"main_body"})
_V8_TEXT_KEYS_IN_ORDER: tuple[str, ...] = ("main_body", "ending", "expandable_details")


def _extract_title_and_body(copywriting_output: dict[str, Any]) -> tuple[str, str]:
    """Reduces any *known* Copywriting output schema to `(title, body)` - the exact shape this
    module has always persisted onto `ContentDraft.title`/`.body`. Raises `ValueError` (this
    module's own established "MUST NOT swallow" convention - see `_copywriting_output()`'s
    identical philosophy immediately below) for a schema this function does not recognize -
    never a silent skip, never an uninformative raw `KeyError`.

    V4 (and any future schema that still carries a plain `body` field): `body` used as-is,
    byte-identical to this module's pre-Phase-23.1C behavior for every existing V4 case.

    V6: every one of its required non-null narrative sections (`opening`, `context`,
    `why_it_matters`, `what_changed`, `conclusion`) must be present as a string, or this is not
    recognized as V6 either; the two genuinely optional sections (`what_happens_next`,
    `what_remains_unknown`) are included only when actually populated (V6's own prompt sets them
    to `null`, not `""`, when there is nothing genuine to say - Phase 23.1B's own live sample
    draft had `what_happens_next=None`, confirming this is the common, not the edge, case).
    Concatenated in the prompt's own declared section order, joined with blank lines so claim/
    quality-gate text processing downstream never fuses two sections' words together - preserves
    ordering exactly as the phase brief requires."""
    title = copywriting_output.get("title")
    if not isinstance(title, str):
        raise ValueError(
            f"copywriting_output has no valid 'title' string (got keys "
            f"{sorted(copywriting_output.keys())}) - cannot create a ContentDraft."
        )

    body = copywriting_output.get("body")
    if isinstance(body, str):
        return title, body

    if all(isinstance(copywriting_output.get(key), str) for key in _V6_REQUIRED_TEXT_KEYS):
        sections = [
            copywriting_output[key] for key in _V6_TEXT_KEYS_IN_ORDER
            if isinstance(copywriting_output.get(key), str)
        ]
        return title, "\n\n".join(sections)

    if all(isinstance(copywriting_output.get(key), str) for key in _V8_REQUIRED_TEXT_KEYS):
        sections = [
            copywriting_output[key] for key in _V8_TEXT_KEYS_IN_ORDER
            if isinstance(copywriting_output.get(key), str)
        ]
        return title, "\n\n".join(sections)

    raise ValueError(
        f"copywriting_output matches no known Copywriting schema (has keys "
        f"{sorted(copywriting_output.keys())}) - expected V4's 'body' field or V6's "
        f"opening/context/why_it_matters/what_changed/conclusion fields. Cannot create a "
        f"ContentDraft without an explicit, recognized schema."
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
        title, body = _extract_title_and_body(copywriting_output)
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
        # NEWS Output Stability Fix (Case D): reuses this exact same fail-closed mechanism -
        # check_quote_is_self_contained() is a second, independent required condition, never a
        # separate enforcement path. "No quote is better than a contextless/meaningless quote" -
        # the real BBC/Discord case ("thoughtfully reviewing") was verbatim AND correctly
        # attributed, so verify_quote() alone was never going to catch it.
        verified_quote: dict[str, Any] | None = None
        if isinstance(quote, dict):
            quote_text = quote.get("text")
            if (
                isinstance(quote_text, str) and verify_quote(quote_text, source_content)
                and check_quote_is_self_contained(quote_text)
            ):
                verified_quote = quote
            else:
                logger.warning(
                    "quote_failed_verification_dropped",
                    extra={"task_id": str(result.task_id), "quote_text": quote_text},
                )

        # NEWS Output Stability Fix (Case C): the story_link lookup (previously only performed
        # AFTER quality-gate evaluation, purely to drive Telegram reply-routing) happens here,
        # before evaluate_content_quality_gates(), so check_update_not_repeating_root() can
        # receive is_update/root_body once a trustworthy source for them exists. `is_update` is
        # computed once here and reused below for ContentDraftStoryLink.is_story_update - a single
        # source of truth, never two divergent computations of the same fact.
        #
        # PHASE STORY-MEMORY-V2-2 Phase 1 (2026-09-02): is_story_update_match() is retired as live
        # decision truth here - the approved forensic finding (PHASE STORY-MEMORY-PROD-FORENSIC-1)
        # confirmed its match_type-based collapse incorrectly treated RELATED_STORY (explicitly a
        # DIFFERENT editorial event per services/story_memory.py's own docstring - "never merges")
        # and SUPPORTING_SOURCE as confirmed updates. STORY_UPDATE and SEMANTIC_DUPLICATE were NOT
        # part of that finding and are deliberately left unchanged here - this phase's own explicit
        # instruction is "the minimum narrow legacy-safe value only where necessary", not a
        # blanket False that would also silently change behavior for the two match_types that were
        # never shown to be wrong. No Story Memory V2 final_decision exists yet to replace this
        # with properly (that lands in a later, separately-authorized phase) - this inline check is
        # an explicit, transitional narrowing of the old 4-type collapse to the 2 types it was
        # never proven wrong for, not a new helper hiding the same collapse under another name.
        # root_body fetching (get_root_delivery()) is pre-existing "Case C" logic, unrelated to
        # is_story_update_match()'s retirement - preserved unchanged here, gated on the now-
        # correctly-narrowed is_update above. Structural Fix 1 (worker/content_cycle.py) means
        # story_telegram_deliveries can now genuinely be populated regardless of
        # telegram_story_reply_mode, so this already-existing, non-blocking quality gate can now
        # observe real root text where it never could before - an explicitly intended consequence
        # of Structural Fix 1 (it unblocks this exact mechanism), not a new suppression path or an
        # editorial-output change: check_update_not_repeating_root() only ever logs, never blocks
        # persistence or delivery.
        #
        # PHASE STORY-MEMORY-V2-2 Phase 1 safety fix (2026-09-02, PHASE STORY-MEMORY-V2-2 Concern
        # 2): narrowed further, from (STORY_UPDATE, SEMANTIC_DUPLICATE) to STORY_UPDATE alone. The
        # approved Story Memory V2 design (PHASE STORY-MEMORY-V2-1) defines NEW_STORY/SEMANTIC_
        # DUPLICATE/STORY_UPDATE/UNCERTAIN as four DISTINCT final outcomes - collapsing SEMANTIC_
        # DUPLICATE into is_story_update=True is exactly the kind of semantic collapse that design
        # explicitly rejects, merely because no V2 final_decision layer exists yet to represent
        # SEMANTIC_DUPLICATE properly. is_story_update is used for Telegram reply-threading (a
        # genuine boolean is required there) and this quality gate; a semantic duplicate is not a
        # reply-worthy "update" in either sense. SEMANTIC_DUPLICATE gets is_update=False (fail open)
        # here, same as RELATED_STORY/SUPPORTING_SOURCE/UNCERTAIN_MATCH/NEW_STORY/None - only
        # STORY_UPDATE, Story Memory's own existing definition of "a materially different title, a
        # real new development", still sets is_update=True this phase.
        story_link: NewsEventStoryLink | None = None
        is_update = False
        root_body: str | None = None
        if event_id is not None and settings.story_memory_mode != "off":
            story_link = await self._session.get(NewsEventStoryLink, event_id)
            if story_link is not None:
                is_update = story_link.match_type == STORY_UPDATE
                if is_update:
                    root_delivery = await get_root_delivery(self._session, story_link.story_id)
                    if root_delivery is not None:
                        root_draft = await self._session.get(ContentDraft, root_delivery.content_draft_id)
                        root_body = root_draft.body if root_draft is not None else None

        # Phase 18.10 M6/M7: deterministic quality gates - computed and logged for visibility,
        # never blocking persistence (these are heuristic editorial-quality signals, not the
        # hard, zero-false-positive hashtag requirement above) - matches
        # services/fact_safety.py's own "assess and record, don't silently reject" philosophy.
        # This non-blocking policy is preserved unchanged for update_not_repeating_root too - this
        # fix wires the gate's real inputs, it does not change what happens when it fails.
        quality_report = evaluate_content_quality_gates(
            title=title,
            body=body,
            why_it_matters=why_it_matters if isinstance(why_it_matters, str) else None,
            what_happened=what_happened if isinstance(what_happened, str) else None,
            source_title=news_event.title if news_event else None,
            quote_text=verified_quote.get("text") if verified_quote else None,
            quote_speaker=verified_quote.get("speaker") if verified_quote else None,
            source_content=source_content,
            is_update=is_update,
            root_body=root_body,
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

        # `story_link`/`is_update` already resolved above (needed earlier for the quality-gate
        # call) - reused here rather than looked up a second time. Gating remains identical:
        # gated on story_memory_mode, not merely on event_id being provided (every real caller
        # always provides a real event_id) - mirrors services/editorial_scoring.py's own
        # apply_editorial_scoring_v2() identical fix: editorial_scoring_version == "v2"/normal
        # draft creation with story_memory_mode == "off" (the default) is a valid, already-
        # working combination that must never depend on this phase's migration being applied.
        if story_link is not None:
            self._session.add(
                ContentDraftStoryLink(
                    content_draft_id=draft.id,
                    story_id=story_link.story_id,
                    is_story_update=is_update,
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

    async def create_from_final_post_authoring_result(
        self, task_id: UUID, result: WorkflowRunResult,
    ) -> ContentDraftRead:
        """Create exactly one ContentDraft row from `result`'s "final_post_authoring" step output
        (Phase I.1). Deliberately NOT `create_from_result()` extended in place: that method's own
        quote-verification/story-link/quality-gate machinery is real NEWS-copywriting behavior
        (article evidence, story-update root-repetition checks, hashtag-era quote objects) that
        does not apply here - the authoring source is an already-approved internal recap, not raw
        source text, and Phase I.1's own explicit scope is "ContentDraft.title = authored title,
        .body = authored body; status = existing safe draft/non-published state" (no quote/story-
        link/quality-gate concerns are part of that contract). A small, explicit, separate method
        is safer than teaching `create_from_result()` a second, divergent notion of what a "draft"
        is assembled from.

        Owns its own, single, deterministic commit, exactly like `create_from_result()`. Always
        writes `status="draft"` - the same safe, non-published default `create_from_result()`
        itself always uses outside `fact_safety_mode == "enforce"` (services/final_post_processor.py
        already gates ContentDraft creation on a non-"block" fact-safety verdict before ever
        calling this method, so there is no separate enforce-mode status split to reproduce here).
        Never sends this draft to Telegram - Phase I.1's own explicit "no publication" scope."""
        authoring_output = _final_post_authoring_output(result)
        title = authoring_output.get("title")
        body = authoring_output.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError(
                f"final_post_authoring_output for task {result.task_id} has a malformed "
                f"title/body (got keys {sorted(authoring_output.keys())}) - cannot create a "
                "ContentDraft."
            )

        if not check_no_hashtags(title, body):
            raise ValueError(
                f"QUALITY CHECK FAILED: WorkflowRunResult for task {result.task_id} produced a "
                "final post title/body containing a hashtag - hashtags are not permitted in "
                "generated content."
            )

        draft = ContentDraft(
            id=uuid4(),
            task_id=task_id,
            type=ContentType.POST,
            title=title,
            body=body,
            hashtags=None,
            version=1,
            status="draft",
        )
        self._session.add(draft)
        await self._session.commit()
        await self._session.refresh(draft)
        return _to_read_schema(draft)
