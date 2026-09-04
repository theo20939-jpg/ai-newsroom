"""R2.10G3-C - shadow LLM eventness judge.

Evaluates whether a bounded LLM shadow reviewer can correctly classify the deterministic "hard
middle" (docs/r2_10_g3_eventness_calibration_report.md §8 - the 11 fixtures no candidate rejector
rule from G3-B safely resolves), plus a frozen control set of already-labelled fixtures.

The LLM here is NOT a production gate. Nothing in this module (or anything it calls) writes to the
database, publishes, sends Telegram, creates an EditorialTask, or changes RECAP readiness / Story
Memory / announcement_count in any way. This is a read-only, single-batch, hard-capped research
diagnostic - identical safety shape to scripts/_recap_r2_shadow_synthesize.py's own established
contract (feature/r2-shadow-preparation), reused below wherever that contract's own machinery
applies unchanged:

  - `ReadOnlyGuardError`/`_verify_read_only()`, `_AttemptCountingLogHandler`, `_SingleAttemptGateway`,
    `_build_single_attempt_gateway()` are DUPLICATED verbatim from that script (not imported) - the
    same per-script-private-helper discipline that script's own docstring establishes: "a future
    change to the other script's own copy can never silently affect this one, and vice versa". This
    IS the single most safety-critical piece of code in this whole module.
  - The read-only DB transaction (feature extraction + evidence-text construction) is opened,
    used, and fully rolled back and closed BEFORE any Gateway import or call - never open while a
    paid network call is in flight, exactly mirroring that script's own ordering.
  - At most ONE physical provider generate() call per Story (`max_same_candidate_retries=0`,
    `max_fallback_attempts=1`, reused from the same script). A single additional prompt-freeze
    sanity call against a synthetic, non-labelled fixture runs once before the real batch (§22 -
    "test only parsing/schema on synthetic neutral fixtures... then run all real evaluation
    fixtures") and is excluded from every real-fixture metric.
  - `EventnessEvaluation`/`DeterministicFeatures`/`evaluate_db_fixture()`/`evaluate_offline_fixture()`
    are imported UNMODIFIED from scripts/_recap_r2_10_g3_eventness_harness.py (G3-A, frozen) -
    reused, not duplicated, since they carry no Gateway dependency and already do exactly the
    read-only feature-extraction this module needs.
  - `CANDIDATE_RULES`/`RULE_COMBINED` are imported UNMODIFIED from
    scripts/_recap_r2_10_g3_eventness_calibrate.py (G3-B, frozen) to report each target fixture's
    already-calibrated deterministic verdict for the conceptual cascade comparison (§28) - never
    reimplemented, never re-tuned here.

BLIND BY DESIGN: the Gateway-facing payload (see `build_evidence_bundle_text()` and
`build_generate_request()`) is constructed ONLY from real, deterministic Story evidence - title,
member-report titles/timestamps/domains, cluster/source aggregates, entities/keywords/topic_bucket,
structural integrity. It NEVER includes `manual_class`, `desired_eventness`, `fixture_id`,
`rationale`, the deterministic rejector's own verdict, or any other hint at the "correct" answer -
enforced directly by construction (these fields are never read inside `build_evidence_bundle_text`)
and independently verified by this module's own test suite.

Run (PAID - one physical LLM call per target fixture, <=30 total, requires a working Redis
connection and real provider credentials via core.config.settings):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_10_g3_eventness_llm_judge.py

NOT run against any production database or production Gateway routing config - developer/local DB
and locally-configured credentials only, per this phase's own explicit safety boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import logging
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
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
from scripts._recap_r2_10_g3_eventness_calibrate import RULE_COMBINED  # noqa: E402
from scripts._recap_r2_10_g3_eventness_harness import (  # noqa: E402
    DeterministicFeatures,
    EventnessEvaluation,
    evaluate_db_fixture,
    evaluate_offline_fixture,
)
from scripts._recap_r2_10_g3_eventness_holdout import HOLDOUT, HoldoutEntry  # noqa: E402
from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST, ManifestEntry  # noqa: E402
from services.recap_event import load_story_events  # noqa: E402

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_OUTPUT_ROOT = Path("/tmp/r2_10_g3_llm_judge_runs")

# Cost/output safety - always applied, never omittable (mirrors _recap_r2_shadow_synthesize.py's
# own MAX_TOKENS/REASONING_EFFORT discipline, values chosen for this module's own, smaller,
# classification-shaped task rather than copied blindly).
MAX_TOKENS = 700
REASONING_EFFORT: Literal["low"] = "low"  # some real judgment is required (§9 - categorical, not a gate)
TEMPERATURE = None  # §21: lowest practical randomness this Gateway exposes for a reasoning model.
# Real finding from this phase's own first live call attempt: the actual routed provider model
# rejects an explicit `temperature` outright once `reasoning_effort` is set ("Unsupported
# parameter: 'temperature' is not supported with this model", HTTP 400) - reasoning-effort models
# do not expose sampling temperature as a separate knob at all. `reasoning_effort="low"` is
# therefore this module's own actual determinism lever (§21's intent honored via the lowest
# practical setting this Gateway/model combination genuinely supports, not via `temperature`).
PREFERRED_MODEL = "gpt-5.6-luna"  # cheapest OPENAI_MODELS tier (integrations/llm_gateway/models/catalog.py) - §19 "one model configuration only for the first experiment"
HARD_CALL_CAP = 30  # §20

PROMPT_NAME = "eventness_judge"
PROMPT_VERSION = "1"

EVENTNESS_OPINIONS = frozenset({"ACCEPT", "REJECT", "UNCERTAIN"})
REASON_CODES = frozenset({
    "COHERENT_SINGLE_EVENT", "EVENT_LIFECYCLE", "TOPIC_COLLECTION", "DIGEST", "PURE_SYNDICATION",
    "NON_EDITORIAL_NOISE", "INSUFFICIENT_EVIDENCE", "FRAGMENTED_BUT_REAL_EVENT", "OTHER",
})
CONFIDENCE_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH"})
_RECOMMENDATION_LANGUAGE_RE = re.compile(r"\b(ready|publish\w*|approve\w*|send|sent)\b", re.IGNORECASE)


# --- target fixture set (§5/§6) - frozen before any LLM call, never redefined after seeing output ---

HARD_MIDDLE_FIXTURE_IDS: tuple[str, ...] = (
    "vlm", "vk_apple_real_3publisher", "marvell_google", "new_york_times_digest",
    "optimizatsiya_koda", "llm_agents_cluster", "robotic_welding_cluster",
    "multimodal_medical_cluster", "object_detection_cluster", "us_futures_wire_noise",
    "holdout_when_predictor_cluster",
)  # verbatim from docs/r2_10_g3_eventness_calibration_report.md §8's own HARD_MIDDLE_STORIES list

POSITIVE_CONTROL_FIXTURE_IDS: tuple[str, ...] = (
    "nvidia_hf_main", "nvidia_mediatek", "south_korea_policy", "ai_challenge_10k",
    "holdout_claude_fable_mythos", "holdout_pentagon_grok",
)

NEGATIVE_CONTROL_FIXTURE_IDS: tuple[str, ...] = (
    "vla", "vk_apple_synthetic_4publisher_false_ready", "ciflow_ci_noise", "utro_digest",
)

# §6 also names VLM and Marvell/Google as mandatory negative/ambiguous controls - both already sit
# in HARD_MIDDLE_FIXTURE_IDS above (they are simultaneously hard-middle targets per §5 AND named
# controls per §6/§15/§18) - disclosed here explicitly rather than silently duplicating the call.
_AUXILIARY_CONTROL_ROLE: dict[str, str] = {
    "vlm": "also satisfies §6/§15 TOPIC CLUSTER SAFETY negative-control mandate (not double-called)",
    "marvell_google": "also satisfies §6/§18 AMBIGUOUS CONTROL mandate (not double-called)",
}


def _holdout_as_manifest_entry(h: HoldoutEntry) -> ManifestEntry:
    """Duplicated from scripts/_recap_r2_10_g3_eventness_calibrate.py's own identically-named,
    identically-behaved private adapter (that function is module-private there - per this
    codebase's own established per-script-private-helper convention, duplicated rather than
    imported across script files, not merely reused via a public re-export)."""
    return ManifestEntry(
        fixture_id=h.fixture_id, kind="db", story_id=h.story_id, title_snapshot=h.title_snapshot,
        manual_class=h.manual_class, desired_eventness=h.desired_eventness, confidence="high",
        source_phase="R2.10G3-B holdout", rationale=h.rationale,
    )


def _lookup_entry(fixture_id: str) -> ManifestEntry:
    for e in MANIFEST:
        if e.fixture_id == fixture_id:
            return e
    for h in HOLDOUT:
        if h.fixture_id == fixture_id:
            return _holdout_as_manifest_entry(h)
    raise KeyError(f"fixture_id {fixture_id!r} not found in MANIFEST or HOLDOUT")


@dataclass(frozen=True)
class TargetFixture:
    entry: ManifestEntry
    group: Literal["HARD_MIDDLE", "POSITIVE_CONTROL", "NEGATIVE_CONTROL"]


def build_target_set() -> tuple[TargetFixture, ...]:
    """Pure, deterministic, frozen before any Gateway call - §5 "must remain immutable throughout
    this phase". Raises if the target set would exceed the §20 hard cap."""
    targets = (
        [TargetFixture(_lookup_entry(fid), "HARD_MIDDLE") for fid in HARD_MIDDLE_FIXTURE_IDS]
        + [TargetFixture(_lookup_entry(fid), "POSITIVE_CONTROL") for fid in POSITIVE_CONTROL_FIXTURE_IDS]
        + [TargetFixture(_lookup_entry(fid), "NEGATIVE_CONTROL") for fid in NEGATIVE_CONTROL_FIXTURE_IDS]
    )
    ids = [t.entry.fixture_id for t in targets]
    assert len(ids) == len(set(ids)), f"duplicate fixture_id in target set: {ids}"
    if len(targets) + 1 > HARD_CALL_CAP:  # +1 for the prompt-freeze sanity call
        raise RuntimeError(
            f"target set of {len(targets)} fixtures (+1 prompt-freeze call) would exceed the "
            f"{HARD_CALL_CAP}-call hard cap (§20) - STOP, do not run."
        )
    return tuple(targets)


def ground_truth_eventness(entry: ManifestEntry) -> str:
    """ACCEPT / REJECT / UNCERTAIN, derived from `desired_eventness` (NOT the literal manual_class
    table §7 describes) - the same resolution G3-B's own measure_rule() docstring already applied,
    for the same reason: `vk_apple_synthetic_4publisher_false_ready`'s manual_class is
    REAL_SINGLE_EVENT (a literal §7 "POSITIVE_EVENT" by class alone) yet the fixture's entire
    purpose (§14/§28) is as the mandatory negative control a safe judge must REJECT. A literal
    manual_class->ACCEPT/REJECT mapping would score a correct REJECT on this exact fixture as the
    single worst possible error (REJECT_ON_MANUAL_POSITIVE) - directly contradicting §14's own
    explicit expected output. `desired_eventness` already resolves this per-fixture (REJECT for
    this one, NEEDS_REVIEW for the real-but-unconfirmed vk_apple_real_3publisher counterpart, kept
    distinct) - reused here for full internal consistency with G3-B, disclosed explicitly rather
    than silently diverging from §7's literal wording."""
    if entry.desired_eventness == "ACCEPT":
        return "ACCEPT"
    if entry.desired_eventness == "REJECT":
        return "REJECT"
    return "UNCERTAIN"  # NEEDS_REVIEW or UNCERTAIN - excluded from binary scoring, same as UNCLEAR


# --- evidence bundle construction (blind by design - see module docstring) -----------------------


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def _event_lines_from_rows(rows: list[tuple[str, str | None, float]]) -> list[str]:
    """`rows`: (title, domain, hours_ago_within_this_fixture_only) - never an absolute timestamp,
    so the evidence text reveals nothing about which `now` reference produced it and reads
    identically regardless of a fixture's real age. Sorted oldest-first; each line's own offset is
    hours before the single most recent report IN THIS FIXTURE."""
    if not rows:
        return []
    latest = min(h for _, _, h in rows)
    ordered = sorted(rows, key=lambda r: r[2], reverse=True)
    return [
        f'  - "{title}" - {domain or "(unknown domain)"}, {h - latest:.2f}h before the most recent report'
        for title, domain, h in ordered
    ]


async def _fetch_db_event_rows(session: AsyncSession, story_id: uuid.UUID) -> list[tuple[str, str | None, float]]:
    events = await load_story_events(session, story_id)
    if not events:
        return []
    timestamps = [e.published_at or e.collected_at for e in events]
    newest = max(timestamps)
    return [
        (e.title, _normalize_domain(e.url), (newest - (e.published_at or e.collected_at)).total_seconds() / 3600)
        for e in events
    ]


def _offline_event_rows(entry: ManifestEntry) -> list[tuple[str, str | None, float]]:
    return [(oe.title, _normalize_domain(oe.url), oe.hours_ago) for oe in entry.offline_events]


def build_evidence_bundle_text(entry: ManifestEntry, event_rows: list[tuple[str, str | None, float]], features: DeterministicFeatures) -> str:
    """The ONLY function that produces the text the Gateway ever sees for a given fixture. Reads
    ONLY `entry.title_snapshot`/`entry.offline_events` (titles/urls/relative hours - never
    `entry.manual_class`, `entry.desired_eventness`, `entry.fixture_id`, `entry.rationale`,
    `entry.confidence`, or `entry.source_phase`) plus the already-deterministic `features`. Covered
    directly by test_manual_label_absent_from_gateway_payload."""
    anchor_title = entry.title_snapshot or (event_rows[0][0] if event_rows else "(no title)")
    lines = [
        f"ANCHOR STORY TITLE: {anchor_title}",
        "",
        f"MEMBER REPORTS ({features.effective_event_count} total, chronological, most recent = 0.00h):",
        *_event_lines_from_rows(event_rows),
        "",
        "AGGREGATE SIGNALS:",
        f"  - announcement_count (deduplicated report clusters): {features.announcement_count}",
        f"  - unique_source_count (distinct publisher domains): {features.unique_source_count}",
        f"  - source_domains: {', '.join(features.source_domains) if features.source_domains else '(none)'}",
        f"  - announcement_cluster_sizes: {features.announcement_cluster_sizes}",
        f"  - single_event_cluster_count: {features.single_event_cluster_count}",
        f"  - multi_source_cluster_count (clusters corroborated by more than one domain): {features.multi_source_cluster_count}",
        f"  - story_span_hours (oldest to newest member report): {features.story_span_hours}",
        f"  - structural_integrity_eligible: {features.integrity_eligible}",
        f"  - structural_integrity_reasons: {features.integrity_reasons if features.integrity_reasons else '(none)'}",
    ]
    if features.match_type_distribution:
        lines.append(f"  - match_type_distribution: {features.match_type_distribution}")
    if features.story_entities:
        lines.append(f"  - extracted_entities: {', '.join(features.story_entities)}")
    if features.story_keywords:
        lines.append(f"  - extracted_keywords: {', '.join(features.story_keywords)}")
    if features.story_topic_bucket:
        lines.append(f"  - topic_bucket: {features.story_topic_bucket}")
    return "\n".join(lines)


_SYNTHETIC_SANITY_EVIDENCE_TEXT = (
    "ANCHOR STORY TITLE: Example Municipal Transit Authority announces new bus route\n\n"
    "MEMBER REPORTS (2 total, chronological, most recent = 0.00h):\n"
    '  - "Example Municipal Transit Authority announces new bus route" - examplenews.test, 0.30h before the most recent report\n'
    '  - "New bus route unveiled by Example Municipal Transit Authority" - examplewire.test, 0.00h before the most recent report\n\n'
    "AGGREGATE SIGNALS:\n"
    "  - announcement_count (deduplicated report clusters): 1\n"
    "  - unique_source_count (distinct publisher domains): 2\n"
    "  - source_domains: examplenews.test, examplewire.test\n"
    "  - announcement_cluster_sizes: [2]\n"
    "  - single_event_cluster_count: 0\n"
    "  - multi_source_cluster_count (clusters corroborated by more than one domain): 1\n"
    "  - story_span_hours (oldest to newest member report): 0.3\n"
    "  - structural_integrity_eligible: True\n"
    "  - structural_integrity_reasons: (none)\n"
)  # §22: a fabricated, never-labelled fixture used ONLY to confirm schema/parsing before freezing.


# --- Gateway safety wrapper - duplicated verbatim from scripts/_recap_r2_shadow_synthesize.py -----
# (module docstring: "a future change to the other script's own copy can never silently affect
# this one, and vice versa" - the same rationale, unchanged here).


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - refuses to run any query."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


class _AttemptCountingLogHandler(logging.Handler):
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
    """Duplicated from scripts/_recap_r2_shadow_synthesize.py's own identically-named class -
    structurally satisfies the LLMGateway Protocol (only generate() is ever called), applies
    `request.model_copy(update={"max_tokens": ..., "reasoning_effort": ...})` before dispatch."""

    def __init__(self, routing_engine: object, fallback_policy: object, *, max_tokens: int, reasoning_effort: str) -> None:
        self._routing_engine = routing_engine
        self._fallback_policy = fallback_policy
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self.last_model_used: str | None = None

    async def generate(self, request: "GenerateRequest") -> "GenerateResponse":
        from integrations.llm_gateway.observability import ObservabilityContext
        from integrations.llm_gateway.routing.criteria import FallbackEligibility, RoutingCriteria

        request = request.model_copy(update={"max_tokens": self._max_tokens, "reasoning_effort": self._reasoning_effort})

        request_id = request.metadata.get("request_id") or str(uuid4())
        trace_id = request.metadata.get("trace_id") or request_id
        capability_execution_id = request.metadata.get("capability_execution_id") or request_id
        observability = ObservabilityContext(trace_id=trace_id, capability_execution_id=capability_execution_id, request_id=request_id)

        capability_name = str(request.metadata.get("capability_name", "unknown"))
        priority_raw = request.metadata.get("priority", TaskPriority.C.value)
        priority = priority_raw if isinstance(priority_raw, TaskPriority) else TaskPriority(priority_raw)
        criteria = RoutingCriteria(
            gateway_method="generate", capability_name=capability_name, priority=priority,
            requires_tools=bool(request.tools), requires_vision="image" in request.modalities,
            requires_structured_output=request.response_mode == "json_schema",
            preferred_model=request.preferred_model, preferred_provider=request.preferred_provider,
            fallback=FallbackEligibility(max_fallback_attempts=1),
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
    """Duplicated from scripts/_recap_r2_shadow_synthesize.py's own identically-named function."""
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
        max_same_candidate_retries=0,
        regional_unavailable_cooldown_seconds=real_fallback_policy._regional_unavailable_cooldown_seconds,  # noqa: SLF001
    )
    return _SingleAttemptGateway(
        routing_engine=real_gateway._routing_engine,  # noqa: SLF001
        fallback_policy=single_attempt_fallback_policy,
        max_tokens=max_tokens, reasoning_effort=reasoning_effort,
    )


def build_generate_request(evidence_text: str, output_schema: dict, system_text: str, rules: list[str]) -> "GenerateRequest":
    from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message

    full_system = system_text + "\n\nRULES:\n" + "\n".join(f"- {r}" for r in rules)
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=full_system)]),
            Message(role="user", content=[ContentPart(type="text", text=f"EVIDENCE BUNDLE:\n{evidence_text}")]),
        ],
        preferred_model=PREFERRED_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        reasoning_effort=REASONING_EFFORT,
        response_mode="json_schema",
        response_schema=output_schema,
        metadata={"capability_name": "eventness_judge_shadow_v1", "priority": TaskPriority.C.value},
    )


# --- output parsing (§8/§33 test E: unknown reason code rejected, never coerced) -------------------


class LLMJudgeOutputError(RuntimeError):
    """Raised when structured_output fails strict schema/vocabulary validation - the result is
    DISCARDED (never coerced, never silently accepted)."""


@dataclass(frozen=True)
class LLMJudgeOpinion:
    eventness_opinion: str
    reason_codes: list[str]
    short_reason: str
    confidence: str
    recommendation_language_detected: bool


def parse_judge_output(structured_output: dict | None) -> LLMJudgeOpinion:
    if structured_output is None:
        raise LLMJudgeOutputError("structured_output is None")
    opinion = structured_output.get("eventness_opinion")
    reason_codes = structured_output.get("reason_codes")
    short_reason = structured_output.get("short_reason")
    confidence = structured_output.get("confidence")
    if opinion not in EVENTNESS_OPINIONS:
        raise LLMJudgeOutputError(f"unknown eventness_opinion: {opinion!r}")
    if not isinstance(reason_codes, list) or not reason_codes:
        raise LLMJudgeOutputError(f"reason_codes must be a non-empty list, got {reason_codes!r}")
    unknown = [c for c in reason_codes if c not in REASON_CODES]
    if unknown:
        raise LLMJudgeOutputError(f"unknown reason_code(s): {unknown}")
    if not isinstance(short_reason, str) or not short_reason:
        raise LLMJudgeOutputError("short_reason must be a non-empty string")
    if confidence not in CONFIDENCE_LEVELS:
        raise LLMJudgeOutputError(f"unknown confidence: {confidence!r}")
    return LLMJudgeOpinion(
        eventness_opinion=opinion, reason_codes=[str(c) for c in reason_codes],
        short_reason=short_reason, confidence=confidence,
        recommendation_language_detected=bool(_RECOMMENDATION_LANGUAGE_RE.search(short_reason)),
    )


# --- per-fixture record + error classification (§24-27) -------------------------------------------

ErrorType = Literal[
    "ACCEPT_ON_MANUAL_NEGATIVE", "REJECT_ON_MANUAL_POSITIVE", "PARSE_ERROR", "SKIPPED_MISSING_STORY",
]


@dataclass(frozen=True)
class JudgeRecord:
    fixture_id: str
    group: str
    also_satisfies: str | None
    manual_class: str
    desired_eventness: str
    ground_truth_eventness: str
    deterministic_rule_result: str | None
    current_readiness_state: str | None
    llm_opinion: str | None
    reason_codes: list[str]
    confidence: str | None
    short_reason: str | None
    recommendation_language_detected: bool
    is_correct: bool | None
    error_type: str | None  # one of ErrorType's values, or None
    overconfident_wrong: bool
    prompt_version: str
    model_used: str | None
    input_tokens: int | None
    output_tokens: int | None
    physical_provider_attempts: int
    parse_error: str | None
    skipped_reason: str | None


def classify_record(ground_truth: str, opinion: LLMJudgeOpinion | None) -> tuple[bool | None, str | None]:
    """Returns (is_correct, error_type). UNCERTAIN ground truth is never scored (mirrors G3-B's own
    exclusion of NEEDS_REVIEW/UNCLEAR from binary scoring - Marvell must not be penalized for a
    correct UNCERTAIN answer, §18). `error_type` is the primary axis (ACCEPT_ON_MANUAL_NEGATIVE /
    REJECT_ON_MANUAL_POSITIVE) - §24's separate OVERCONFIDENT_WRONG metric is an orthogonal flag
    (a wrong answer AND HIGH confidence), computed by the caller via `overconfident_wrong` so it
    never overwrites which specific error occurred."""
    if opinion is None:
        return None, "PARSE_ERROR"
    if ground_truth == "UNCERTAIN":
        return None, None
    if ground_truth == "ACCEPT" and opinion.eventness_opinion == "REJECT":
        return False, "REJECT_ON_MANUAL_POSITIVE"
    if ground_truth == "REJECT" and opinion.eventness_opinion == "ACCEPT":
        return False, "ACCEPT_ON_MANUAL_NEGATIVE"
    if opinion.eventness_opinion == "UNCERTAIN":
        return None, None  # the model itself declined to guess - not scored right/wrong, reported separately
    return True, None


# --- evaluation entry point -------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMJudgeRunResult:
    prompt_version: str
    prompt_hash: str
    model_config_used: str
    records: list[JudgeRecord]
    sanity_check_passed: bool
    physical_calls_total: int


async def _collect_evidence(session: AsyncSession, target: TargetFixture, *, now: datetime) -> tuple[EventnessEvaluation, str]:
    entry = target.entry
    if entry.kind == "db":
        evaluation = await evaluate_db_fixture(session, entry, now=now)
        if evaluation.skipped_reason is not None or evaluation.features is None:
            return evaluation, ""
        rows = await _fetch_db_event_rows(session, uuid.UUID(entry.story_id))  # type: ignore[arg-type]
    else:
        evaluation = evaluate_offline_fixture(entry, now=now)
        rows = _offline_event_rows(entry)
    assert evaluation.features is not None
    text_bundle = build_evidence_bundle_text(entry, rows, evaluation.features)
    return evaluation, text_bundle


async def collect_all_evidence(
    targets: tuple[TargetFixture, ...], *, now: datetime,
) -> dict[str, tuple[EventnessEvaluation, str]]:
    """Phase 1 only - the entire read-only DB pass, fully isolated from the Gateway (no import of
    it occurs anywhere in this function or anything it calls). Extracted from `run_llm_judge()` so
    the DB-safety property (never writes) is independently testable without making any paid
    Gateway call - see test_no_production_readiness_mutation / test_llm_path_cannot_write_db in
    this module's own test suite."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    evidence_by_fixture: dict[str, tuple[EventnessEvaluation, str]] = {}
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            for target in targets:
                evidence_by_fixture[target.entry.fixture_id] = await _collect_evidence(session, target, now=now)
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()
    return evidence_by_fixture


async def run_llm_judge(*, now: datetime | None = None) -> LLMJudgeRunResult:
    from integrations.prompts.file_repository import FilePromptRepository

    resolved_now = now or datetime.now(timezone.utc)
    targets = build_target_set()

    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / PROMPT_NAME / f"v{PROMPT_VERSION}.yaml"
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()

    # --- Phase 1: read-only DB pass, closed BEFORE any Gateway import/call -----------------------
    evidence_by_fixture = await collect_all_evidence(targets, now=resolved_now)

    # --- Phase 2: Gateway only, transaction fully closed above -------------------------------------
    prompt_repository = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
    prompt = prompt_repository.resolve(PROMPT_NAME, PROMPT_VERSION)

    from integrations.llm_gateway.boot import assemble_ai_integration_layer

    layer = assemble_ai_integration_layer(settings, prompt_repository)
    gateway = _build_single_attempt_gateway(layer, max_tokens=MAX_TOKENS, reasoning_effort=REASONING_EFFORT)

    fallback_logger = logging.getLogger("integrations.llm_gateway.fallback.policy")

    async def _call(evidence_text: str) -> tuple[dict | None, str, dict[str, int | None], int]:
        request = build_generate_request(evidence_text, prompt.output_schema, prompt.system, prompt.rules)
        counter = _AttemptCountingLogHandler()
        fallback_logger.addHandler(counter)
        try:
            response = await gateway.generate(request)
        finally:
            fallback_logger.removeHandler(counter)
        physical = 1 + counter.same_candidate_retries + counter.fallback_attempts
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        return response.structured_output, response.model_used, usage, physical

    # Prompt-freeze sanity call (§22) - synthetic, never-labelled fixture, excluded from metrics.
    sanity_output, _sanity_model, _sanity_usage, sanity_physical = await _call(_SYNTHETIC_SANITY_EVIDENCE_TEXT)
    try:
        parse_judge_output(sanity_output)
        sanity_passed = True
    except LLMJudgeOutputError:
        sanity_passed = False

    records: list[JudgeRecord] = []
    total_physical = sanity_physical
    for target in targets:
        entry = target.entry
        evaluation, evidence_text = evidence_by_fixture[entry.fixture_id]
        ground_truth = ground_truth_eventness(entry)
        det_result = None
        if evaluation.features is not None:
            det_result = RULE_COMBINED.fn(evaluation.features)  # type: ignore[arg-type]

        if evaluation.skipped_reason is not None or evaluation.features is None:
            records.append(JudgeRecord(
                fixture_id=entry.fixture_id, group=target.group, also_satisfies=_AUXILIARY_CONTROL_ROLE.get(entry.fixture_id),
                manual_class=entry.manual_class, desired_eventness=entry.desired_eventness, ground_truth_eventness=ground_truth,
                deterministic_rule_result=det_result, current_readiness_state=evaluation.existing_readiness_state,
                llm_opinion=None, reason_codes=[], confidence=None, short_reason=None, recommendation_language_detected=False,
                is_correct=None, error_type="SKIPPED_MISSING_STORY", overconfident_wrong=False,
                prompt_version=PROMPT_VERSION, model_used=None,
                input_tokens=None, output_tokens=None, physical_provider_attempts=0, parse_error=None,
                skipped_reason=evaluation.skipped_reason or "features unavailable",
            ))
            continue

        structured_output, model_used, usage, physical = await _call(evidence_text)
        total_physical += physical
        parse_error: str | None = None
        opinion: LLMJudgeOpinion | None = None
        try:
            opinion = parse_judge_output(structured_output)
        except LLMJudgeOutputError as exc:
            parse_error = str(exc)

        is_correct, error_type = classify_record(ground_truth, opinion)
        if parse_error is not None:
            is_correct, error_type = None, "PARSE_ERROR"
        overconfident_wrong = is_correct is False and opinion is not None and opinion.confidence == "HIGH"

        records.append(JudgeRecord(
            fixture_id=entry.fixture_id, group=target.group, also_satisfies=_AUXILIARY_CONTROL_ROLE.get(entry.fixture_id),
            manual_class=entry.manual_class, desired_eventness=entry.desired_eventness, ground_truth_eventness=ground_truth,
            deterministic_rule_result=det_result, current_readiness_state=evaluation.existing_readiness_state,
            llm_opinion=opinion.eventness_opinion if opinion else None,
            reason_codes=opinion.reason_codes if opinion else [],
            confidence=opinion.confidence if opinion else None,
            short_reason=opinion.short_reason if opinion else None,
            recommendation_language_detected=opinion.recommendation_language_detected if opinion else False,
            is_correct=is_correct, error_type=error_type, overconfident_wrong=overconfident_wrong,
            prompt_version=PROMPT_VERSION, model_used=model_used,
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
            physical_provider_attempts=physical, parse_error=parse_error, skipped_reason=None,
        ))

    return LLMJudgeRunResult(
        prompt_version=PROMPT_VERSION, prompt_hash=prompt_hash, model_config_used=PREFERRED_MODEL,
        records=records, sanity_check_passed=sanity_passed, physical_calls_total=total_physical,
    )


# --- metrics (§24-28) -------------------------------------------------------------------------------


def compute_metrics(records: list[JudgeRecord]) -> dict[str, object]:
    scored = [
        r for r in records
        if r.skipped_reason is None and r.error_type != "PARSE_ERROR" and r.ground_truth_eventness != "UNCERTAIN"
    ]
    ambiguous = [r for r in records if r.skipped_reason is None and r.ground_truth_eventness == "UNCERTAIN"]
    hard_middle = [r for r in scored if r.group == "HARD_MIDDLE"]
    pos_controls = [r for r in scored if r.group == "POSITIVE_CONTROL"]
    neg_controls = [r for r in scored if r.group == "NEGATIVE_CONTROL"]

    def _false_accepts(rows: list[JudgeRecord]) -> list[str]:
        return [r.fixture_id for r in rows if r.error_type == "ACCEPT_ON_MANUAL_NEGATIVE"]

    def _false_rejects(rows: list[JudgeRecord]) -> list[str]:
        return [r.fixture_id for r in rows if r.error_type == "REJECT_ON_MANUAL_POSITIVE"]

    # §26: AMBIGUOUS_CONTROL_OVERCLAIMS - a manually UNCLEAR/UNCERTAIN fixture where the model
    # answered ACCEPT/REJECT instead of UNCERTAIN. §18: a correct UNCERTAIN here is never penalized
    # (excluded from `scored` entirely) but IS counted positively as CORRECT_UNCERTAIN (§24).
    ambiguous_overclaims = [r for r in ambiguous if r.llm_opinion in ("ACCEPT", "REJECT")]
    correct_uncertain = [r for r in ambiguous if r.llm_opinion == "UNCERTAIN"]

    return {
        "total_records": len(records),
        "scored_count": len(scored),
        "skipped_count": sum(1 for r in records if r.skipped_reason is not None),
        "uncertain_ground_truth_excluded_count": len(ambiguous),
        "parse_error_count": sum(1 for r in records if r.error_type == "PARSE_ERROR"),
        "hard_middle_total": len(hard_middle),
        "hard_middle_correct": sum(1 for r in hard_middle if r.is_correct is True),
        "hard_middle_wrong": sum(1 for r in hard_middle if r.is_correct is False),
        "hard_middle_uncertain": sum(1 for r in hard_middle if r.llm_opinion == "UNCERTAIN"),
        "positive_control_false_rejects": _false_rejects(pos_controls),
        "negative_control_false_accepts": _false_accepts(neg_controls),
        "false_accept_ids_overall": _false_accepts(scored),
        "false_reject_ids_overall": _false_rejects(scored),
        "correct_accepts": sum(1 for r in scored if r.is_correct is True and r.ground_truth_eventness == "ACCEPT"),
        "correct_rejects": sum(1 for r in scored if r.is_correct is True and r.ground_truth_eventness == "REJECT"),
        "correct_uncertain_count": len(correct_uncertain),
        "correct_uncertain_ids": [r.fixture_id for r in correct_uncertain],
        "ambiguous_control_overclaim_ids": [r.fixture_id for r in ambiguous_overclaims],
        "overconfident_wrong_ids": [r.fixture_id for r in records if r.overconfident_wrong],
    }


def cascade_simulation(records: list[JudgeRecord]) -> dict[str, object]:
    """§28 - conceptual only, no code change, no production implementation. Deterministic-REJECT
    fixtures are never promoted (§29) - the LLM layer is evaluated only against the HARD_MIDDLE
    remainder that the deterministic layer already PASS_THROUGH'd."""
    negatives = [r for r in records if r.ground_truth_eventness == "REJECT" and r.skipped_reason is None]
    det_filtered = [r for r in negatives if r.deterministic_rule_result == "REJECT"]
    remaining = [r for r in negatives if r.deterministic_rule_result != "REJECT"]
    llm_caught = [r for r in remaining if r.llm_opinion == "REJECT"]
    llm_false_accepts = [r for r in remaining if r.llm_opinion == "ACCEPT"]
    positives = [r for r in records if r.ground_truth_eventness == "ACCEPT" and r.skipped_reason is None]
    llm_false_rejects_on_positives = [r for r in positives if r.llm_opinion == "REJECT"]
    return {
        "deterministic_negatives_filtered": len(det_filtered),
        "deterministic_negatives_filtered_ids": [r.fixture_id for r in det_filtered],
        "hard_middle_sent_to_llm": len(remaining),
        "hard_middle_sent_to_llm_ids": [r.fixture_id for r in remaining],
        "additional_negatives_caught_by_llm": len(llm_caught),
        "additional_negatives_caught_by_llm_ids": [r.fixture_id for r in llm_caught],
        "llm_false_accepts_on_remainder": len(llm_false_accepts),
        "llm_false_accepts_on_remainder_ids": [r.fixture_id for r in llm_false_accepts],
        "llm_false_rejects_on_positives": len(llm_false_rejects_on_positives),
        "llm_false_rejects_on_positives_ids": [r.fixture_id for r in llm_false_rejects_on_positives],
    }


def cost_report(records: list[JudgeRecord]) -> dict[str, object]:
    """§19/§31 - `preferred_model` (PREFERRED_MODEL="gpt-5.6-luna") is advisory only
    (integrations/llm_gateway/routing/engine.py's own explicit "§4.1 rule 1" comment) - the real
    router may dispatch a different model in the same family. A first real run of this module
    confirmed this empirically (every record's own `model_used` came back "gpt-5.6-terra", not
    "gpt-5.6-luna"). Cost MUST therefore be priced per-record from each record's own real
    `model_used`, never from the requested `PREFERRED_MODEL` - pricing every record against the
    requested-but-not-actually-used cheaper tier would silently under-report real spend."""
    from integrations.llm_gateway.models.catalog import OPENAI_MODELS

    pricing_by_model = {
        m.model_id: next((p for p in m.pricing_tiers if p.condition == "standard"), None) for m in OPENAI_MODELS
    }
    input_tokens = sum(r.input_tokens for r in records if r.input_tokens is not None)
    output_tokens = sum(r.output_tokens for r in records if r.output_tokens is not None)
    cost = 0.0
    unpriced: list[str] = []
    for r in records:
        if r.input_tokens is None or r.output_tokens is None:
            continue
        pricing = pricing_by_model.get(r.model_used or "")
        if pricing is None:
            unpriced.append(r.fixture_id)
            continue
        cost += (r.input_tokens / 1_000_000) * float(pricing.input_price_per_million)
        cost += (r.output_tokens / 1_000_000) * float(pricing.output_price_per_million)
    models_used = sorted({r.model_used for r in records if r.model_used})
    return {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
        "models_used": models_used,
        "estimated_cost_usd": round(cost, 4) if not unpriced else "COST_UNKNOWN",
        "unpriced_record_ids": unpriced,
    }


class _JudgeJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=None, help="output directory (default: /tmp/r2_10_g3_llm_judge_runs/<timestamp>/)")
    args = parser.parse_args()

    print("LLM_ENABLED=True")
    print(f"MODEL={PREFERRED_MODEL} REASONING_EFFORT={REASONING_EFFORT!r} MAX_TOKENS={MAX_TOKENS} TEMPERATURE={TEMPERATURE}")
    print(f"HARD_CALL_CAP={HARD_CALL_CAP}")

    result = await run_llm_judge()
    print(f"PROMPT_VERSION={result.prompt_version} PROMPT_HASH={result.prompt_hash[:16]}...")
    print(f"SANITY_CHECK_PASSED={result.sanity_check_passed}")
    print(f"PHYSICAL_CALLS_TOTAL={result.physical_calls_total} (includes 1 prompt-freeze sanity call)")

    metrics = compute_metrics(result.records)
    cascade = cascade_simulation(result.records)
    cost = cost_report(result.records)

    now = datetime.now(timezone.utc)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / now.strftime("%Y%m%dT%H%M%SZ"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "llm_judge_records.json").write_text(
        json.dumps([dataclasses.asdict(r) for r in result.records], cls=_JudgeJSONEncoder, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    (output_dir / "llm_judge_metrics.json").write_text(json.dumps({"metrics": metrics, "cascade": cascade, "cost": cost}, indent=2), encoding="utf-8")

    print(f"HARD_MIDDLE_CORRECT={metrics['hard_middle_correct']}/{metrics['hard_middle_total']} UNCERTAIN={metrics['hard_middle_uncertain']}")
    print(f"NEGATIVE_CONTROL_FALSE_ACCEPTS={metrics['negative_control_false_accepts']}")
    print(f"POSITIVE_CONTROL_FALSE_REJECTS={metrics['positive_control_false_rejects']}")
    print(f"COST: {cost}")
    print(f"Wrote output to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
