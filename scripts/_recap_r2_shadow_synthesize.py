"""NINJA PULSE RECAP - R2 Shadow, second canary. Manual, single-Story, controlled EVENT_RECAP
synthesis under a paid LLM Gateway call.

Design record (read before changing anything here): docs/r2_shadow_synthesis_contract.md,
docs/r2_shadow_synthesis_implementation_plan.md. Implements exactly what those two documents scope
- nothing more. `services/event_recap.py` is NOT touched, imported-and-modified, or monkey-patched
anywhere - every cost-safety control is applied entirely inside this script's own Gateway wrapper,
via the `gateway: LLMGateway` parameter `synthesize_event_recap()` already accepts as a caller-
supplied dependency (confirmed workable by direct execution before this file was written - see the
contract's own section 4a).

HUMAN REVIEW PROTOCOL (contract section 3a) - this is the one hard behavioral precondition this
script enforces beyond the sibling scripts' own guarantees: it refuses to run at all unless a prior
R2 Shadow v1 `story_<id>.json` (scripts/_recap_r2_shadow_batch.py's own output) already exists for
the exact Story being requested - proving that Story was already observed, deterministically and
for free, before any money is considered. That prior artifact's own key fields are re-printed to
the terminal before any DB connection opens, so the operator sees them again at the exact moment
before spend. No code here can verify a human actually read them - only that a human ran the prior
observation stage at all. No interactive prompt is added (this codebase's own established "do not
add interactive prompts that break automation" discipline, scripts/_recap_r2_event_shadow.py's own
_cli_safety_warnings()) - running this script at all, with the required flags, already IS the
operator's own deliberate action.

SAFE BY DEFAULT, WITHIN WHAT THIS SCRIPT INHERENTLY DOES:
  - This script has NO --limit argument - structurally single-Story, one invocation, one Story,
    one synthesis call.
  - Never writes to the database (read-only transaction, verified and enforced - `_verify_read_only()`
    below is a direct, deliberate duplication of the sibling scripts' own identically-named,
    identically-behaved private helper).
  - The read-only DB transaction is rolled back and closed BEFORE any Gateway import or call -
    never open while a network call to a paid provider is in flight.
  - Never touches Telegram, never touches a worker, never publishes anything.
  - At most ONE physical provider generate() call per invocation (--single-attempt's own existing
    guarantee, reused - max_same_candidate_retries=0, max_fallback_attempts=1).
  - max_tokens=1000 / reasoning_effort="none" are ALWAYS applied to the outgoing request (this
    script's own Gateway wrapper intercepts and rewrites the request via GenerateRequest's own
    standard, immutable pydantic `.model_copy(update={...})` - never omittable, never left unbounded).
  - max_chars=4000 is a FLAG-ONLY sanity bound on the rendered synthesis preview text - it never
    blocks writing the output artifact, only adds a quality_notes entry (contract section 4b).
    render_event_recap_telegram_preview()'s own pre-existing hard 4096-char limit
    (EventRecapTelegramPreviewTooLongError) remains a SEPARATE, independent, still-hard failure -
    this script's 4000 bound is a tighter, additional sanity check layered on top of it, not a
    replacement.
  - Causal-connective detection (contract section 4c) is FLAG-ONLY METADATA - no rewrite, no
    reject, no block, under any configuration. It never modifies the synthesized text.
  - readiness_state/publishable are carried through, verbatim, from the real, unmodified
    synthesize_event_recap() return value - this script computes neither and cannot change either
    (contract section 7a - already a structural guarantee of the unmodified function itself).

Run (PAID - requires --story-id, an existing prior R2 Shadow v1 artifact via --from-shadow-run, a
working Redis connection, and real provider credentials via core.config.settings):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_shadow_synthesize.py \\
        --story-id <UUID> --from-shadow-run /tmp/r2_shadow_runs/<timestamp>/

NOT EXECUTED by the author of this script - no VPS/production DB access, no paid LLM calls, this
session.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if TYPE_CHECKING:
    from integrations.llm_gateway.protocol import (
        ClassifyRequest, ClassifyResponse, EmbedRequest, EmbedResponse,
        GenerateRequest, GenerateResponse, ModerateRequest, ModerateResponse,
        RerankRequest, RerankResponse,
    )

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.editorial_task import TaskPriority  # noqa: E402
from database.models.story import Story  # noqa: E402
from scripts._recap_r2_10_readiness_candidate_scanner import (  # noqa: E402
    CandidateScanRow, scan_story_readiness,
)
from services.event_recap import (  # noqa: E402
    EventRecapCandidate,
    EventRecapSynthesisError,
    EventRecapTelegramPreviewTooLongError,
    build_event_recap_candidate,
    render_event_recap_bundle_text,
    render_event_recap_telegram_preview,
    synthesize_event_recap,
)

STATEMENT_TIMEOUT_MS = 30_000

# Cost/output safety (contract sections 4a/4b) - always applied, never omittable.
MAX_TOKENS = 1000
REASONING_EFFORT = "none"
MAX_CHARS = 4000

# Small, explicit, hand-curated (contract section 4c/9) - mirrors services/event_recap.py's own
# _INTERNAL_VOCABULARY_TERMS discipline exactly: never a general classifier, subject to revision
# once real shadow-synthesis output exists to check it against.
_CAUSAL_CONNECTIVES: tuple[str, ...] = (
    "because", "as a result", "this led to", "in response to", "due to",
    "потому что", "в результате", "это привело к", "в ответ на", "из-за",
)


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - the script refuses to run
    any query in that case. Mirrors both sibling R2 scripts' own identically-named, identically-
    behaved guard exactly - deliberately duplicated, not imported (see module docstring)."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


class _AttemptCountingLogHandler(logging.Handler):
    """Diagnostic-only observability - counts the exact structured log events
    `integrations.llm_gateway.fallback.policy` itself already emits per attempt. Duplicated
    verbatim from scripts/_recap_r2_event_shadow.py's own identically-named class (module
    docstring's own "deliberately duplicated" discipline)."""

    def __init__(self) -> None:
        super().__init__()
        self.same_candidate_retries = 0
        self.fallback_attempts = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == "retry":
            self.same_candidate_retries += 1
        elif record.getMessage() == "fallback":
            self.fallback_attempts += 1


class _SingleAttemptGateway:
    """Diagnostic-only LLMGateway (structurally satisfies the Protocol - only `generate()` is ever
    called by `capabilities.gateway_call.call_generate()`, the other 5 methods are unsupported
    stubs). Duplicated from scripts/_recap_r2_event_shadow.py's own identically-named class, NOT
    imported across scripts (contract section 4a / implementation plan section 3 - this is the
    single most safety-critical piece of code in this whole stage; keeping it self-contained per
    script means a future change to the other script's own copy can never silently affect this
    one, and vice versa), with ONE addition beyond that class's own contract: `generate()` also
    applies `request.model_copy(update={"max_tokens": ..., "reasoning_effort": ...})` before
    dispatch - the cost-safety mechanism this whole stage exists to guarantee, achieved entirely
    through GenerateRequest's own standard, immutable pydantic `.model_copy()` API (confirmed
    working by direct execution before this file was written), never by modifying
    services/event_recap.py's own request-building code."""

    def __init__(
        self, routing_engine: object, fallback_policy: object, *, max_tokens: int, reasoning_effort: str,
    ) -> None:
        self._routing_engine = routing_engine
        self._fallback_policy = fallback_policy
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        # Cost-visibility only (contract's own "cost visibility required") - the real GenerateResponse
        # this gateway's own last generate() call received, read back by main() after the call
        # returns; never exposed by synthesize_event_recap() itself, so this is the one place this
        # script can observe it without touching services/event_recap.py.
        self.last_model_used: str | None = None

    async def generate(self, request: "GenerateRequest") -> "GenerateResponse":
        from integrations.llm_gateway.observability import ObservabilityContext
        from integrations.llm_gateway.routing.criteria import FallbackEligibility, RoutingCriteria

        # The one deliberate addition beyond the base _SingleAttemptGateway contract - applied
        # before anything else touches `request`, so every downstream read (routing criteria,
        # dispatch) already sees the capped request.
        request = request.model_copy(update={"max_tokens": self._max_tokens, "reasoning_effort": self._reasoning_effort})

        request_id = request.metadata.get("request_id") or str(uuid4())
        trace_id = request.metadata.get("trace_id") or request_id
        capability_execution_id = request.metadata.get("capability_execution_id") or request_id
        observability = ObservabilityContext(
            trace_id=trace_id, capability_execution_id=capability_execution_id, request_id=request_id,
        )

        capability_name = str(request.metadata.get("capability_name", "unknown"))
        priority_raw = request.metadata.get("priority", TaskPriority.B.value)
        priority = priority_raw if isinstance(priority_raw, TaskPriority) else TaskPriority(priority_raw)
        criteria = RoutingCriteria(
            gateway_method="generate", capability_name=capability_name, priority=priority,
            requires_tools=bool(request.tools), requires_vision="image" in request.modalities,
            requires_structured_output=request.response_mode == "json_schema",
            preferred_model=request.preferred_model, preferred_provider=request.preferred_provider,
            fallback=FallbackEligibility(max_fallback_attempts=1),  # the one deliberate override
        )
        ranked_candidates = await self._routing_engine.route(criteria, observability)  # type: ignore[attr-defined]
        response = await self._fallback_policy.dispatch(request, ranked_candidates, criteria, observability)  # type: ignore[attr-defined]
        self.last_model_used = response.model_used
        return response

    async def generate_stream(self, request: "GenerateRequest"):  # type: ignore[no-untyped-def]
        from integrations.llm_gateway.protocol import UnsupportedGatewayCapabilityError

        raise UnsupportedGatewayCapabilityError("_SingleAttemptGateway: generate_stream() is not used by this diagnostic")
        yield  # pragma: no cover - unreachable; keeps this an async generator for typing

    async def embed(self, request: "EmbedRequest") -> "EmbedResponse":
        from integrations.llm_gateway.protocol import UnsupportedGatewayCapabilityError

        raise UnsupportedGatewayCapabilityError("_SingleAttemptGateway: embed() is not used by this diagnostic")

    async def classify(self, request: "ClassifyRequest") -> "ClassifyResponse":
        from integrations.llm_gateway.protocol import UnsupportedGatewayCapabilityError

        raise UnsupportedGatewayCapabilityError("_SingleAttemptGateway: classify() is not used by this diagnostic")

    async def moderate(self, request: "ModerateRequest") -> "ModerateResponse":
        from integrations.llm_gateway.protocol import UnsupportedGatewayCapabilityError

        raise UnsupportedGatewayCapabilityError("_SingleAttemptGateway: moderate() is not used by this diagnostic")

    async def rerank(self, request: "RerankRequest") -> "RerankResponse":
        from integrations.llm_gateway.protocol import UnsupportedGatewayCapabilityError

        raise UnsupportedGatewayCapabilityError("_SingleAttemptGateway: rerank() is not used by this diagnostic")


def _build_single_attempt_gateway(layer: object, *, max_tokens: int, reasoning_effort: str) -> _SingleAttemptGateway:
    """Reuses every real, already-constructed component from the real production boot sequence
    UNCHANGED, exactly like scripts/_recap_r2_event_shadow.py's own identically-named function -
    duplicated, not imported (module docstring)."""
    from integrations.llm_gateway.fallback.policy import FallbackPolicy

    real_gateway = layer.gateway  # type: ignore[attr-defined]
    real_fallback_policy = real_gateway._fallback_policy  # noqa: SLF001
    single_attempt_fallback_policy = FallbackPolicy(
        provider_registry=real_fallback_policy._provider_registry,  # noqa: SLF001
        health_store=real_fallback_policy._health_store,  # noqa: SLF001
        cache_coordinator=real_fallback_policy._cache_coordinator,  # noqa: SLF001
        cost_estimator=real_fallback_policy._cost_estimator,  # noqa: SLF001
        budget_guard=real_fallback_policy._budget_guard,  # noqa: SLF001
        rate_limiter=real_fallback_policy._rate_limiter,  # noqa: SLF001
        max_same_candidate_retries=0,  # the one deliberate override
        regional_unavailable_cooldown_seconds=real_fallback_policy._regional_unavailable_cooldown_seconds,  # noqa: SLF001
    )
    return _SingleAttemptGateway(
        routing_engine=real_gateway._routing_engine,  # noqa: SLF001
        fallback_policy=single_attempt_fallback_policy,
        max_tokens=max_tokens, reasoning_effort=reasoning_effort,
    )


def _detect_unevidenced_causal_claims(
    recap_title: str, recap_summary: str, key_takeaways: list[str], uncertainty_notes: list[str],
    evidence_bundle_text: str,
) -> list[str]:
    """Flag-only metadata (contract section 4c, owner-confirmed scope: "no rewrite, no reject, no
    block") - mirrors services/event_recap.py::_detect_internal_vocabulary_leak()'s own small-
    explicit-term-list, case-insensitive-substring-search shape exactly, scanning the identical
    four synthesized fields. A causal connective is flagged only when it does not itself appear
    anywhere in the evidence bundle text - a conservative, deterministic proxy for "this causal
    framing was not present in the source evidence," never a claim that the specific asserted
    cause was independently verified (reliable claim-level verification is not achievable by
    keyword matching alone - the same precision caution R2.11's own conflict-detection conclusion
    already established for a structurally similar problem)."""
    haystack = " ".join([recap_title, recap_summary, *key_takeaways, *uncertainty_notes]).lower()
    evidence_lower = evidence_bundle_text.lower()
    return sorted(term for term in _CAUSAL_CONNECTIVES if term in haystack and term not in evidence_lower)


def _check_max_chars_note(rendered_preview_text: str) -> str | None:
    """Flag-only (contract section 4b) - never blocks writing the output artifact. A separate,
    tighter, shadow-specific sanity bound layered on top of render_event_recap_telegram_preview()'s
    own pre-existing hard 4096-char EventRecapTelegramPreviewTooLongError, not a replacement for
    it - that exception, if it fires, is handled the same way as EventRecapSynthesisError (main()),
    since it is a genuine, independent, still-hard failure this stage does not soften."""
    if len(rendered_preview_text) > MAX_CHARS:
        return (
            f"synthesis preview text is {len(rendered_preview_text)} chars, exceeds this shadow "
            f"stage's own {MAX_CHARS}-char sanity bound (flag only, never blocks)"
        )
    return None


def _compute_synthesis_quality_notes(
    candidate: EventRecapCandidate, rendered_preview_text: str, evidence_bundle_text: str,
    recap_title: str, recap_summary: str, key_takeaways: list[str], uncertainty_notes: list[str],
) -> list[str]:
    """Shadow-local additions only (contract section 7) - `EventRecapCandidate.quality_flags`
    (fact_verification_*/internal_vocabulary_leak_detected:...) already comes populated, verbatim,
    from the real synthesize_event_recap() return value and is never recomputed or duplicated
    here; this function adds only the R2.11 announcement-count caveat, the max_chars flag, and the
    causal-connective flag - mirrors scripts/_recap_r2_shadow_batch.py::_compute_quality_notes()'s
    own shape, extended with the two checks this stage alone needs."""
    notes: list[str] = []
    if candidate.announcement_count > 1:
        notes.append(
            "announcement_count reflects raw report-level clusters, not confirmed distinct "
            "developments - see docs/r2_11_announcement_identity_findings.md"
        )
    max_chars_note = _check_max_chars_note(rendered_preview_text)
    if max_chars_note:
        notes.append(max_chars_note)
    causal_flags = _detect_unevidenced_causal_claims(
        recap_title, recap_summary, key_takeaways, uncertainty_notes, evidence_bundle_text,
    )
    if causal_flags:
        notes.append(f"unevidenced_causal_connective_detected:{','.join(causal_flags)}")
    return notes


def _compute_synthesis_evaluation_status(
    row: CandidateScanRow, quality_notes: list[str], synthesized_quality_flags: list[str],
) -> str:
    """Shadow-local vocabulary (contract section 7) - deliberately NOT services/fact_safety.py's
    pass/review/block. `fact_verification.status != "pass"` and any internal-vocabulary leak
    already reach here via `synthesized_quality_flags` (EventRecapCandidate.quality_flags,
    unmodified) - both fall through this same NEEDS_REVIEW rule, no separate branch needed."""
    if row.readiness_state == "REJECTED":
        return "REJECTED"
    if row.recommended_for_manual_review or quality_notes or synthesized_quality_flags:
        return "NEEDS_REVIEW"
    return "OBSERVED"


@dataclass(frozen=True)
class ShadowSynthesisMetadata:
    physical_provider_attempts: int
    fallback_attempts: int
    same_candidate_retries: int
    model_used: str | None
    max_tokens_sent: int
    reasoning_effort_sent: str


@dataclass(frozen=True)
class ShadowSynthesisReport:
    """`candidate` is the real, complete, unmodified return value of `synthesize_event_recap()` -
    `readiness_state`/`publishable` on it are read-only, carried-through metadata from the pre-
    synthesis candidate (contract section 7a - already a structural guarantee of the real function,
    never recomputed here); `quality_notes`/`evaluation_status` are the shadow-local additions."""

    story_id: UUID
    title: str
    candidate: EventRecapCandidate
    quality_notes: list[str]
    evaluation_status: str
    synthesis: ShadowSynthesisMetadata


class _ShadowJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _print_human_review_protocol_reprint(prior_report: dict) -> None:
    """Human Review Protocol reinforcement (contract section 3a, item 3) - re-prints the prior R2
    Shadow v1 artifact's own key fields to the operator's terminal before any DB connection opens,
    so the information that should drive the human's decision is surfaced again at the exact
    moment before spend, not merely available somewhere in a file opened minutes or days earlier."""
    evaluation = prior_report.get("evaluation", {})
    candidate = prior_report.get("candidate")
    print(f"Prior R2 Shadow v1 observation for Story {prior_report.get('story_id')}:")
    print(f"  title={prior_report.get('title')!r}")
    print(f"  evaluation_status={evaluation.get('evaluation_status')}")
    if candidate is not None:
        print(f"  readiness_state={candidate.get('readiness_state')}")
        print(f"  announcement_count={candidate.get('announcement_count')}")
    else:
        print("  candidate=None (this Story was REJECTED by the deterministic stage)")
    quality_notes = evaluation.get("quality_notes", [])
    if quality_notes:
        print("  quality_notes:")
        for note in quality_notes:
            print(f"    - {note}")
    else:
        print("  quality_notes: (none)")
    print("Review the above BEFORE proceeding - this stage makes a real, paid LLM call.")


def _write_synthesis_report(
    output_dir: Path, report: ShadowSynthesisReport, rendered_preview_text: str,
) -> tuple[Path, Path]:
    """Extracted for independent testability (mirrors scripts/_recap_r2_shadow_batch.py's own
    `_write_story_report()` precedent). Writes only after a successful synthesis - main() never
    calls this on an `EventRecapSynthesisError`/`EventRecapTelegramPreviewTooLongError` path, so
    "neither artifact written on failure" is enforced by call-site control flow, not by logic
    inside this function."""
    json_path = output_dir / f"story_{report.story_id}_synthesis.json"
    json_path.write_text(json.dumps(dataclasses.asdict(report), cls=_ShadowJSONEncoder, indent=2), encoding="utf-8")
    txt_path = output_dir / f"story_{report.story_id}_synthesis.txt"
    txt_path.write_text(rendered_preview_text, encoding="utf-8")
    return json_path, txt_path


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--story-id", required=True, type=UUID, help="Story.id to synthesize an EVENT_RECAP for.")
    parser.add_argument(
        "--from-shadow-run", required=True, type=Path,
        help="R2 Shadow v1 output directory containing story_<story-id>.json for this exact Story "
             "(Human Review Protocol precondition - see docs/r2_shadow_synthesis_contract.md section 3a).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="output directory for the synthesis artifacts (default: same as --from-shadow-run).",
    )
    args = parser.parse_args()

    prior_artifact_path = args.from_shadow_run / f"story_{args.story_id}.json"
    if not prior_artifact_path.exists():
        print(
            f"No prior R2 Shadow v1 observation found at {prior_artifact_path} - refusing to run. "
            "Run scripts/_recap_r2_shadow_batch.py first and review its output for this Story "
            "before requesting synthesis (Human Review Protocol, docs/r2_shadow_synthesis_contract.md section 3a).",
            file=sys.stderr,
        )
        return 2

    prior_report = json.loads(prior_artifact_path.read_text(encoding="utf-8"))
    _print_human_review_protocol_reprint(prior_report)

    output_dir = args.output_dir or args.from_shadow_run
    output_dir.mkdir(parents=True, exist_ok=True)

    print("LLM_ENABLED=True")
    print("SINGLE_ATTEMPT=True")
    print(f"MAX_PROVIDER_ATTEMPTS=1 MAX_TOKENS={MAX_TOKENS} REASONING_EFFORT={REASONING_EFFORT!r}")

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            now = datetime.now(timezone.utc)

            story = await session.get(Story, args.story_id)
            if story is None:
                print(f"Story {args.story_id} not found.", file=sys.stderr)
                return 1

            row = await scan_story_readiness(session, story, now=now)
            if row.readiness_state == "REJECTED":
                print(
                    f"Story {args.story_id} is currently REJECTED - no candidate can be built: "
                    f"{row.rejection_reasons}",
                    file=sys.stderr,
                )
                return 1

            result = await build_event_recap_candidate(session, story, force_shadow=True, now=now)
            assert result.candidate is not None  # row already proved a candidate builds for this Story
            candidate = result.candidate
            evidence_bundle_text = render_event_recap_bundle_text(candidate)
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()

    # Transaction fully closed above - only now does anything touch the LLM Gateway.
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import RuntimeContext

    prompt_repository = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
    layer = assemble_ai_integration_layer(settings, prompt_repository)
    runtime = RuntimeContext(
        task_id=uuid4(),  # synthetic - no real EditorialTask row backs this shadow run
        event_id=candidate.anchor_event_id,
        capability_name="event_recap_synthesis_shadow_v2",
        priority=TaskPriority.C,
        attempt=1,
        iteration_count=0,
    )
    gateway = _build_single_attempt_gateway(layer, max_tokens=MAX_TOKENS, reasoning_effort=REASONING_EFFORT)

    attempt_counter = _AttemptCountingLogHandler()
    fallback_logger = logging.getLogger("integrations.llm_gateway.fallback.policy")
    fallback_logger.addHandler(attempt_counter)
    try:
        synthesized = await synthesize_event_recap(candidate, gateway, prompt_repository, runtime=runtime)
    except EventRecapSynthesisError as exc:
        print(f"Synthesis failed: {exc}", file=sys.stderr)
        return 1
    finally:
        fallback_logger.removeHandler(attempt_counter)

    physical_provider_attempts = 1 + attempt_counter.same_candidate_retries + attempt_counter.fallback_attempts
    print(
        f"caller_gateway_calls=1 physical_provider_attempts={physical_provider_attempts} "
        f"fallback_attempts={attempt_counter.fallback_attempts} "
        f"same_candidate_retries={attempt_counter.same_candidate_retries}"
    )

    assert synthesized.recap_title is not None and synthesized.recap_summary is not None  # guaranteed on successful return

    try:
        rendered_preview_text = render_event_recap_telegram_preview(synthesized)
    except EventRecapTelegramPreviewTooLongError as exc:
        print(f"Synthesis preview exceeds the hard 4096-char Telegram limit, writing no artifacts: {exc}", file=sys.stderr)
        return 1

    quality_notes = _compute_synthesis_quality_notes(
        candidate, rendered_preview_text, evidence_bundle_text,
        synthesized.recap_title, synthesized.recap_summary, synthesized.key_takeaways, synthesized.uncertainty_notes,
    )
    evaluation_status = _compute_synthesis_evaluation_status(row, quality_notes, synthesized.quality_flags)

    report = ShadowSynthesisReport(
        story_id=story.id, title=story.title, candidate=synthesized,
        quality_notes=quality_notes, evaluation_status=evaluation_status,
        synthesis=ShadowSynthesisMetadata(
            physical_provider_attempts=physical_provider_attempts,
            fallback_attempts=attempt_counter.fallback_attempts,
            same_candidate_retries=attempt_counter.same_candidate_retries,
            model_used=gateway.last_model_used,
            max_tokens_sent=MAX_TOKENS, reasoning_effort_sent=REASONING_EFFORT,
        ),
    )

    json_path, txt_path = _write_synthesis_report(output_dir, report, rendered_preview_text)

    print(f"evaluation_status={evaluation_status} publishable={synthesized.publishable} (always False in R2 - shadow only)")
    print(f"Wrote {json_path}")
    print(f"Wrote {txt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
