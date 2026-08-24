"""NINJA PULSE RECAP Phase R2 - manual EVENT_RECAP shadow diagnostic CLI.

The one manual, callable entry point for Phase R2 (spec's own explicit "Manual callable /
diagnostic execution first. ... No scheduler. Do NOT add a worker loop."). Never registered with
any scheduler, worker, or Capability/Workflow registry - a human runs this by hand, against one
Story at a time.

Conceptual flow (spec's own): Story ID -> load confirmed events -> Story Integrity -> announcement
clusters -> readiness -> build evidence bundle -> optional shadow LLM synthesis -> fact
verification -> EventRecapCandidate -> JSON report.

SAFE BY DEFAULT:
  - Without --with-llm: builds the deterministic evidence candidate ONLY. Zero LLM/Gateway calls,
    zero network access, zero cost.
  - Without --force-shadow: a Story that is not READY (per the FROZEN, unmodified
    evaluate_recap_readiness()) is rejected outright - never silently downgraded.
  - Never writes to the database (read-only transaction, verified and enforced - see
    _verify_read_only() below, the same pattern every prior RECAP production script this session
    has used).
  - Never touches Telegram, never touches a worker, never publishes anything - this script has no
    import of bot/*, worker/*, or any delivery path anywhere.

--with-llm is the ONLY way to trigger a real (paid) LLM Gateway call. It requires a working Redis
connection (integrations.llm_gateway.boot.assemble_ai_integration_layer()'s own dependency, for
rate limiting/health/cache/cost tracking - the exact same production boot sequence every real
Capability call already goes through, reused unchanged here) and real provider credentials via
core.config.settings. The LLM call happens strictly AFTER the read-only DB transaction has already
been rolled back and closed - it never runs inside an open DB transaction.

Phase R2.3a --single-attempt (diagnostic safety only, this script ONLY - see module-level
_SingleAttemptGateway/_build_single_attempt_gateway below for the full forensic rationale): the
shared production Gateway's own FallbackPolicy retains its real default resilience
(max_same_candidate_retries=1, max_fallback_attempts=3 - i.e. up to 2 attempts against the
top-ranked candidate, plus fallback to up to 2 further candidate models) for every OTHER caller,
completely unchanged. `--single-attempt` (only meaningful combined with --with-llm) swaps in a
diagnostic-only LLMGateway-shaped object, built from the SAME real, already-constructed
RoutingEngine/ProviderRegistry/ModelRegistry/health_store/cache_coordinator/cost_estimator/
budget_guard/rate_limiter the shared Gateway already uses (nothing new constructed, nothing
duplicated), with exactly one different setting: a fresh FallbackPolicy instance built with
max_same_candidate_retries=0, and RoutingCriteria.fallback.max_fallback_attempts capped at 1 for
this one request - together mathematically guaranteeing at most ONE physical provider generate()
call for this diagnostic invocation, in every case (success or transient failure alike). This
never touches settings, never touches the shared RoutingGateway/FallbackPolicy instance, never
affects any other caller (News Analysis, Content Generation, Research, TELEGRAPH, or any worker).

Run (deterministic only, safe default):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_event_shadow.py --story-id <UUID>

Run (with real shadow LLM synthesis - PAID, requires --with-llm and a working Redis connection):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_event_shadow.py --story-id <UUID> --with-llm --single-attempt

NOT EXECUTED by the author of this script - no VPS/production DB access, and this checkpoint's own
instructions forbid making any paid LLM call.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
from datetime import datetime
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
from services.event_recap import (  # noqa: E402
    EventRecapBuildResult,
    build_event_recap_candidate,
    render_event_recap_bundle_text,
    synthesize_event_recap,
)

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_OUTPUT_DIR = Path("/tmp")


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


class _RecapJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _serialize(result: EventRecapBuildResult) -> dict:
    return {
        "rejected": result.rejected,
        "rejection_reasons": result.rejection_reasons,
        "candidate": dataclasses.asdict(result.candidate) if result.candidate is not None else None,
    }


async def _load_story(session: AsyncSession, story_id: UUID) -> Story | None:
    return await session.get(Story, story_id)


def _render_text_report(result: EventRecapBuildResult, *, with_llm: bool) -> str:
    """Human-readable companion to the JSON output. Presentation only - derives nothing the JSON
    does not already contain, computes nothing new; `original_ready` below is a pure restatement
    of `EventRecapCandidate.readiness_overridden`'s own documented meaning (`readiness_overridden
    = force_shadow and not readiness.ready`, so a built candidate's original `ready` was False
    exactly when `readiness_overridden` is True, and True otherwise - see services/event_recap.py::
    build_event_recap_candidate()'s own docstring)."""
    lines: list[str] = [
        "NINJA PULSE RECAP Phase R2 - EVENT_RECAP shadow diagnostic report",
        f"LLM_ENABLED={with_llm}",
        "",
    ]
    if result.rejected:
        lines.append(f"REJECTED: {result.rejection_reasons}")
        return "\n".join(lines)

    c = result.candidate
    assert c is not None
    original_ready = not c.readiness_overridden

    lines += [
        f"story_id={c.story_id}",
        f"anchor_event_id={c.anchor_event_id}",
        f"story_title={c.story_title!r}",
        f"generated_at={c.generated_at.isoformat()}",
        "",
        f"story_integrity_eligible={c.story_integrity_eligible}",
        f"story_integrity_reasons={c.story_integrity_reasons}",
        "",
        f"readiness_state={c.readiness_state}",
        f"original_ready={original_ready}",
        f"readiness_overridden={c.readiness_overridden}",
        f"publishable={c.publishable}",
        "",
        f"announcement_count={c.announcement_count}",
        # Phase R2.2: deliberately two distinct numbers, never conflated - readiness_source_count
        # is R1's own count_unique_sources() verbatim (what evaluate_recap_readiness() actually
        # saw); evidence_reference_count is a separate, R2-only distinct-evidence-reference count.
        f"readiness_source_count={c.readiness_source_count}",
        f"evidence_reference_count={c.evidence_reference_count}",
        f"source_refs_count={len(c.source_refs)}",
        "",
        "ANNOUNCEMENTS:",
    ]
    for a in c.announcements:
        lines += [
            f"  #{a.cluster_id} stable_event_id={a.stable_event_id}",
            f"    member_event_ids={a.member_event_ids}",
            f"    headline={a.headline!r}",
            f"    first_seen_at={a.first_seen_at.isoformat()}  last_seen_at={a.last_seen_at.isoformat()}",
            f"    meaningful_numbers={a.meaningful_numbers}  content_entities={a.content_entities}",
            f"    evidence_reference_count={a.evidence_reference_count}  source_refs={a.source_refs}",
        ]

    lines.append("")
    lines.append(f"TIMELINE (entries={len(c.timeline)}):")
    for entry in c.timeline:
        lines.append(
            f"  {entry.timestamp.isoformat()} | announcement #{entry.announcement_id} | {entry.label!r} | "
            f"supporting_event_ids={entry.supporting_event_ids} | source_refs={entry.source_refs}"
        )

    lines.append("")
    lines.append("VERIFIED FACTS:")
    if c.verified_facts:
        for fact in c.verified_facts:
            lines.append(
                f"  [{fact.fact_type}] {fact.value} | status={fact.status} | source_count={fact.source_count} | "
                f"source_event_ids={fact.source_event_ids} | conflicting_evidence={fact.conflicting_evidence}"
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"SOURCE_REFS ({len(c.source_refs)}):")
    for ref in c.source_refs:
        lines.append(f"  - {ref}")

    image_count = sum(1 for m in c.media_candidates if m.kind == "image")
    video_count = sum(1 for m in c.media_candidates if m.kind == "video")
    lines.append("")
    lines.append(f"MEDIA CANDIDATES (image={image_count}, video={video_count}):")
    if c.media_candidates:
        for m in c.media_candidates:
            lines.append(f"  [{m.kind}] event_id={m.event_id} rank={m.rank} remote_url={m.remote_url}")
    else:
        lines.append("  (none)")

    if with_llm:
        lines += [
            "",
            f"recap_title={c.recap_title!r}",
            f"recap_summary={c.recap_summary!r}",
            f"key_takeaways={c.key_takeaways}",
            f"uncertainty_notes={c.uncertainty_notes}",
            f"fact_verification={c.fact_verification}",
            f"quality_flags={c.quality_flags}",
        ]

    return "\n".join(lines)


class _AttemptCountingLogHandler(logging.Handler):
    """Diagnostic-only observability (item 7): counts the exact structured log events
    `integrations.llm_gateway.fallback.policy` itself already emits per attempt -
    `logger.info("retry", ...)` for a same-candidate retry, `logger.info("fallback", ...)` for
    moving to a different candidate after a failure - neither reimplemented nor guessed at, both
    read directly from that module's own real, unmodified log call sites. Attached only around
    the single --single-attempt Gateway call, removed immediately after (never a persistent
    global handler, never a new metrics system)."""

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
    """Phase R2.3a diagnostic-only LLMGateway (structurally satisfies the Protocol - only
    `generate()` is ever called by `capabilities.gateway_call.call_generate()`, the other 5
    methods are unsupported stubs, mirroring `RoutingGateway`'s own identical precedent).

    NEVER constructed for, or used by, any other caller in this codebase - built fresh, once,
    only inside `_build_single_attempt_gateway()` below, only when `--with-llm --single-attempt`
    is explicitly passed to THIS script.

    `generate()` deliberately duplicates `RoutingGateway.generate()`'s own real, unmodified
    4-step logic (build observability context -> build routing criteria -> route -> dispatch) -
    confirmed by direct inspection of integrations/llm_gateway/gateway.py that `RoutingCriteria.
    fallback` has NO existing per-request override channel today (only capability_name/priority/
    excluded_providers/objective are read from `request.metadata`; `fallback` is always
    `FallbackEligibility()`'s own default, `max_fallback_attempts=3`) - so this is the smallest
    faithful way to inject exactly one different value (`fallback=FallbackEligibility(
    max_fallback_attempts=1)`) without editing `integrations/llm_gateway/gateway.py` itself,
    which would affect every other caller. The routing engine and the one candidate ultimately
    dispatched to are the REAL, unmodified production components - only the fallback ceiling and
    the same-candidate retry count (via the diagnostic-only FallbackPolicy passed to __init__,
    see `_build_single_attempt_gateway()`) are capped."""

    def __init__(self, routing_engine: object, fallback_policy: object) -> None:
        self._routing_engine = routing_engine
        self._fallback_policy = fallback_policy

    async def generate(self, request: "GenerateRequest") -> "GenerateResponse":
        from integrations.llm_gateway.observability import ObservabilityContext
        from integrations.llm_gateway.routing.criteria import FallbackEligibility, RoutingCriteria

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
        return await self._fallback_policy.dispatch(request, ranked_candidates, criteria, observability)  # type: ignore[attr-defined]

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


def _build_single_attempt_gateway(layer: object) -> _SingleAttemptGateway:
    """Reuses every real, already-constructed component from the real production boot sequence
    (`integrations.llm_gateway.boot.assemble_ai_integration_layer()`) UNCHANGED - the same
    RoutingEngine, ProviderRegistry, ModelRegistry, health_store, cache_coordinator,
    cost_estimator, budget_guard, rate_limiter the shared production Gateway already uses -
    and constructs exactly ONE new `FallbackPolicy`, differing in exactly one constructor
    argument: `max_same_candidate_retries=0` (the shared Gateway's own FallbackPolicy, reached
    via `layer.gateway` here ONLY to read its already-constructed dependencies, is never modified
    and keeps its real default of 1).

    This necessarily reads several leading-underscore attributes off the real, already-
    constructed `RoutingGateway`/`FallbackPolicy` instances (`AIIntegrationLayer` exposes no
    public accessor for these) - read-only, no mutation, no new infrastructure stood up (no
    second Redis-backed health store/cache/rate-limiter, which re-running boot() to get a
    "clean" second FallbackPolicy would require and which this function deliberately avoids, per
    spec R2.3a's own "do not introduce a second LLM architecture"). If a future refactor renames
    any of these attributes, this raises AttributeError immediately (fail loud, never a silent
    fallback to unsafe multi-attempt behavior)."""
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
    )


def _cli_safety_warnings(*, with_llm: bool, single_attempt: bool) -> list[str]:
    """Phase R2.10 Night 2 (Phase 22, CLI UX hardening). Pure - computes warning strings only,
    never blocks execution (this script's own established "SAFE BY DEFAULT" discipline extends to
    never breaking automation with an interactive prompt - a clear stderr warning is the correct,
    non-blocking middle ground). The single dangerous state worth calling out loudly: `--with-llm`
    WITHOUT `--single-attempt` silently falls back to the SHARED production Gateway's own default
    resilience (up to 2 same-candidate retries + fallback to up to 2 further candidates - see
    `_build_single_attempt_gateway()`'s own module docstring) for what is meant to be one
    controlled diagnostic call - an operator who forgets `--single-attempt` could trigger several
    real, paid physical provider attempts instead of the intended one."""
    warnings: list[str] = []
    if with_llm and not single_attempt:
        warnings.append(
            "WARNING: --with-llm without --single-attempt uses the SHARED Gateway's default "
            "resilience (potentially several physical provider attempts, not one controlled "
            "attempt) - pass --single-attempt for a real diagnostic run unless you specifically "
            "intend to exercise ordinary fallback behavior."
        )
    if single_attempt and not with_llm:
        warnings.append(
            "NOTE: --single-attempt has no effect without --with-llm - this run makes zero "
            "LLM/Gateway calls regardless."
        )
    return warnings


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--story-id", required=True, type=UUID, help="Story.id to build an EVENT_RECAP shadow candidate for.")
    parser.add_argument(
        "--force-shadow", action="store_true",
        help="Build a candidate even when readiness is not READY. Always records readiness_overridden=True.",
    )
    parser.add_argument(
        "--with-llm", action="store_true",
        help="Make a REAL (paid) LLM Gateway call for shadow synthesis. Without this flag, only the "
             "deterministic evidence candidate is built - no LLM/Gateway call, zero cost.",
    )
    parser.add_argument(
        "--single-attempt", action="store_true",
        help="Only meaningful combined with --with-llm. Caps this ONE diagnostic Gateway call at "
             "AT MOST ONE physical provider generate() attempt (same-candidate retries=0, "
             "fallback candidates=1) - never affects any other caller's retry/fallback behavior. "
             "Ignored (no effect) without --with-llm.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT_DIR}/recap_r2_event_shadow_<story-id>.json). "
             "A companion human-readable report is written alongside it with a .txt suffix.",
    )
    parser.add_argument(
        "--evidence-output", type=Path, default=None,
        help="Path for a standalone pre-synthesis evidence-bundle dump (default: "
             "<output-stem>_evidence.txt) - the EXACT text a --with-llm run would send to the "
             "model, written as soon as the deterministic candidate is built, BEFORE any Gateway "
             "call - lets the evidence be audited independently of whether --with-llm is used.",
    )
    args = parser.parse_args()

    for warning in _cli_safety_warnings(with_llm=args.with_llm, single_attempt=args.single_attempt):
        print(warning, file=sys.stderr)

    output_path = args.output or DEFAULT_OUTPUT_DIR / f"recap_r2_event_shadow_{args.story_id}.json"
    text_output_path = output_path.with_suffix(".txt")
    evidence_output_path = args.evidence_output or output_path.with_name(f"{output_path.stem}_evidence.txt")
    for existing in (output_path, text_output_path, evidence_output_path):
        if existing.exists():
            print(f"NOTE: {existing} already exists and will be overwritten.", file=sys.stderr)

    # Runtime-visible proof, printed before any DB access, regardless of outcome - unambiguous
    # for both a human reading stdout and an automated check grepping for this exact line.
    print(f"LLM_ENABLED={args.with_llm}")
    if args.with_llm:
        print(f"SINGLE_ATTEMPT={args.single_attempt}")
        print(f"MAX_PROVIDER_ATTEMPTS={1 if args.single_attempt else '(shared production default)'}")

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            story = await _load_story(session, args.story_id)
            if story is None:
                print(f"Story {args.story_id} not found.", file=sys.stderr)
                return 1

            result = await build_event_recap_candidate(session, story, force_shadow=args.force_shadow)
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()

    if result.rejected:
        print(f"REJECTED: {result.rejection_reasons}")
        output_path.write_text(json.dumps(_serialize(result), cls=_RecapJSONEncoder, indent=2), encoding="utf-8")
        text_output_path.write_text(_render_text_report(result, with_llm=args.with_llm), encoding="utf-8")
        print(f"Wrote {output_path}")
        print(f"Wrote {text_output_path}")
        return 0

    candidate = result.candidate
    assert candidate is not None

    # Pre-synthesis evidence audit (written BEFORE any Gateway call, regardless of --with-llm) -
    # the exact text render_event_recap_bundle_text() would embed in the synthesis GenerateRequest.
    evidence_output_path.write_text(render_event_recap_bundle_text(candidate), encoding="utf-8")
    print(f"Wrote {evidence_output_path} (pre-synthesis evidence audit)")

    original_ready = not candidate.readiness_overridden
    print(
        f"Candidate built: story_id={candidate.story_id} announcements={candidate.announcement_count} "
        f"readiness_source_count={candidate.readiness_source_count} "
        f"evidence_reference_count={candidate.evidence_reference_count} "
        f"source_refs_count={len(candidate.source_refs)} readiness_state={candidate.readiness_state} "
        f"original_ready={original_ready} readiness_overridden={candidate.readiness_overridden} "
        f"publishable={candidate.publishable}"
    )

    if args.with_llm:
        # Deferred imports: only touched when --with-llm is actually passed, so the safe default
        # path above never even imports the LLM Gateway boot machinery.
        from integrations.llm_gateway.boot import assemble_ai_integration_layer
        from integrations.prompts.file_repository import FilePromptRepository
        from schemas.capability import RuntimeContext

        prompt_repository = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
        layer = assemble_ai_integration_layer(settings, prompt_repository)
        runtime = RuntimeContext(
            task_id=uuid4(),  # synthetic - no real EditorialTask row backs this shadow run
            event_id=candidate.anchor_event_id,
            capability_name="event_recap_synthesis_shadow",
            priority=TaskPriority.C,
            attempt=1,
            iteration_count=0,
        )

        from integrations.llm_gateway.protocol import LLMGateway

        gateway: LLMGateway = layer.gateway
        if args.single_attempt:
            gateway = _build_single_attempt_gateway(layer)

        attempt_counter = _AttemptCountingLogHandler()
        fallback_logger = logging.getLogger("integrations.llm_gateway.fallback.policy")
        fallback_logger.addHandler(attempt_counter)
        try:
            candidate = await synthesize_event_recap(
                candidate, gateway, prompt_repository, runtime=runtime,
                language=settings.default_content_language,
            )
        finally:
            fallback_logger.removeHandler(attempt_counter)

        result = EventRecapBuildResult(candidate=candidate, rejected=False, rejection_reasons=[])
        # Exact under --single-attempt (fallback_attempts is structurally always 0 there - the
        # capped sequence has only one candidate to begin with, so the "fallback" log event can
        # never fire); a lower-bound approximation otherwise, since a failed-then-retried
        # candidate before an eventual successful fallback isn't separately itemized here.
        physical_provider_attempts = 1 + attempt_counter.same_candidate_retries + attempt_counter.fallback_attempts
        print(
            f"caller_gateway_calls=1 physical_provider_attempts={physical_provider_attempts} "
            f"fallback_attempts={attempt_counter.fallback_attempts} "
            f"same_candidate_retries={attempt_counter.same_candidate_retries}"
        )
        print(
            f"LLM synthesis complete: recap_title={candidate.recap_title!r} "
            f"takeaways={len(candidate.key_takeaways)} fact_verification={candidate.fact_verification.status}"
        )
    else:
        print("No --with-llm flag given - deterministic evidence candidate only, no LLM/Gateway call made.")

    output_path.write_text(json.dumps(_serialize(result), cls=_RecapJSONEncoder, indent=2), encoding="utf-8")
    text_output_path.write_text(_render_text_report(result, with_llm=args.with_llm), encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Wrote {text_output_path}")
    print(f"publishable={candidate.publishable} (always False in R2 - shadow only)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
