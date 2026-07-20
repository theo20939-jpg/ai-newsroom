"""Phase 9 M7: Research -> Intelligence integration proof.

**Discovered limitation, load-bearing for this file's test design (must be read before the
tests below)**: while building this proof, empirical testing plus a direct reading of
`workflows/runner.py` (frozen Phase 5) established that `CapabilityExecutor._build_context()`
(frozen Phase 6) can only ever see a prior step's result via `step_results` if that result was
**already present in `EditorialTask.workflow` before the current `WorkflowRunner._execute_steps()`
pass began** - never a result from a step that completed earlier in the *same* pass.
`workflows/runner.py` commits/reassigns `task.workflow` exactly twice (`_execute_steps`'s own
success path, and `_fail()`) - both only *after* its entire step loop finishes, never
mid-loop (confirmed by grep: `task.workflow =` appears at exactly those two sites). Since
`StepExecutor.execute(step)` (the Protocol `CapabilityExecutor` implements) receives only
`step` - never the in-progress `state`/`step_results` WorkflowRunner is accumulating in
memory - `CapabilityExecutor` has no channel to a same-pass, not-yet-persisted prior step's
result. This means a synthetic two-step ("research" then "intelligence") `WorkflowDefinition`
run through **one, uninterrupted `WorkflowRunner.run()` call** does *not* actually propagate
Research's result to Intelligence via `step_results` - contradicting the literal, naive
reading of Contract §9.1's claim for that specific scenario, though the Contract's own §14.1
independently documents the exact mechanism responsible ("`step_results` accumulates only in a
local, in-memory Python list until the loop finishes").

This is a genuine, pre-existing (frozen Phase 5/6) architectural characteristic, not something
any Phase 9 milestone introduced, and Phase 9 has no authority to modify `workflows/runner.py`
or `capabilities/executor.py` to change it (frozen contracts; no redesign authorized). Per the
operating instructions' failure-classification rule ("B: pre-existing baseline -> document and
continue"), this file does not attempt a workaround inside frozen code. Instead it:

1. Proves what *is* true: both Capabilities dispatch correctly, in the right order, through
   the real, unmodified `CapabilityExecutor`/`WorkflowRunner`/`CapabilityRegistry`, and the
   synthetic task reaches `TaskStatus.COMPLETED` (Contract §13's actual allowed proof).
2. Explicitly, directly asserts the discovered non-propagation behavior for the same-pass case,
   so it is regression-locked and visible in the suite, not silently absent.
3. Separately proves the *read side* of the §9.1 mechanism is correctly wired -
   `CapabilityExecutor` genuinely surfaces `step_results` content that is already present in
   `EditorialTask.workflow` before a run begins (the one scenario in which this mechanism can
   fire at all under `WorkflowRunner`'s current, frozen commit discipline) - by seeding that
   state explicitly and labeling the seed as a simulation of a resumed task, not a live,
   same-pass handoff.

See the Phase 9 completion report for this finding's full write-up and its recommendation that
a future phase revisit `WorkflowRunner`'s per-step persistence discipline before relying on
live, same-pass `step_results` chaining for any real multi-step AI pipeline.

**Update (Phase 9.5 M1)**: `WorkflowRunner._execute_steps()` now commits `task.workflow` once per
step whose outcome allows the loop to continue (`SUCCESS`/`SKIPPED`), immediately after
`state.completed_steps.append(step.name)`, not only after the entire pass finishes
(`docs/phase9_5_workflow_hardening_architecture_contract.md` §3-§4). This closes the gap
described above for the same-pass case: `CapabilityExecutor` now observes an earlier step's
result while a later step in the same pass is still executing.
`test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` below has been updated
accordingly - Intelligence's built prompt now genuinely contains Research's facts. The rest of
this module's discussion (the root cause, why `DAILY_DIGEST` was chosen, and the other three
tests below) is unaffected and remains accurate; only that one test's expectation changed. Phase
9.5 changes persistence timing, not workflow semantics - the mechanism this file already proved
correct (§9.1's `step_results` read) is unchanged; only when `task.workflow` becomes durable
within one pass is different.

Synthetic `WorkflowType` choice (resolves docs/phase9_implementation_planning_audit.md MINOR
finding 1): reuses the existing `WorkflowType.DAILY_DIGEST` value, whose own docstring already
states it is never registered in the real `WorkflowRegistry` - so it has no competing real
`WorkflowDefinition` anywhere in the codebase. Mirrors the already-proven pattern
`tests/test_capability_boot_wiring_e2e.py` established: a local `WorkflowRegistry()` instance,
sealed, holding a test-only definition, passed explicitly to `workflow_service.create_task(...,
registry=<local registry>)` - never registered in, and never resolved through, the real global
`workflows.registry.registry` singleton, and no new `WorkflowType` enum member is added
(Contract P10).
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.intelligence_capability import CAPABILITY_NAME as INTELLIGENCE_CAPABILITY_NAME
from capabilities.registry import build_registry
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import NewsEvent
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate, EditorialTaskRead
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import (
    AllowingBudgetGuard,
    EmptyLatencyTracker,
    InMemoryCacheStore,
    PermissiveProviderHealthStore,
)
from tests.fakes.fake_provider_adapter import FakeProviderAdapter
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from workflows.registry import WorkflowRegistry
from workflows.registry import registry as real_workflow_registry
from workflows.runner import WorkflowRunner

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _research_intelligence_definition(steps: list[WorkflowStepDefinition]) -> WorkflowDefinition:
    return WorkflowDefinition(
        name=WorkflowType.DAILY_DIGEST,
        version=1,
        steps=steps,
        max_iterations=3,
        retry_policy=WorkflowRetryPolicy(max_attempts=1, retryable_error_types=["StepExecutionError"]),
        timeout_seconds=60,
        required_input=["event_id"],
        expected_output=["result"],
    )


def _synthetic_research_intelligence_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        _research_intelligence_definition(
            [
                WorkflowStepDefinition(name="research", capability=RESEARCH_CAPABILITY_NAME, max_attempts=1, timeout_seconds=10),
                WorkflowStepDefinition(name="intelligence", capability=INTELLIGENCE_CAPABILITY_NAME, max_attempts=1, timeout_seconds=10),
            ]
        )
    )
    registry.seal()
    return registry


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


async def _created_task(
    session: AsyncSession, event: NewsEvent, workflow_registry: WorkflowRegistry
) -> EditorialTaskRead:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.DAILY_DIGEST, priority=TaskPriority.B)
    return await workflow_service.create_task(session, command, registry=workflow_registry)


def _request_text(request: GenerateRequest) -> str:
    return "\n".join(part.text for message in request.messages for part in message.content if part.text)


# ---------------------------------------------------------------------------
# 1. Both Capabilities dispatch correctly, in order, through the real CapabilityExecutor /
#    WorkflowRunner / CapabilityRegistry, and the synthetic task reaches COMPLETED - Contract
#    §13's actual allowed proof. Also confirms (Phase 9.5 M1) that the same-pass step_results
#    propagation gap the module docstring describes is now closed, via an explicit assertion
#    that Intelligence's own prompt genuinely reflects Research's facts.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_capabilities_dispatch_in_order_and_synthetic_task_completes(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    gateway = FakeLLMGateway(
        generate_responses=[_generate_response(CANONICAL_RESEARCH_OUTPUT), _generate_response(_INTELLIGENCE_OUTPUT)]
    )
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    workflow_registry = _synthetic_research_intelligence_registry()

    task = await _created_task(db_session, real_news_event, workflow_registry)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert [r.step_name for r in result.step_results] == ["research", "intelligence"]
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].result == CANONICAL_RESEARCH_OUTPUT
    assert result.step_results[1].status == "SUCCESS"
    assert result.step_results[1].result == _INTELLIGENCE_OUTPUT
    assert len(gateway.received_requests) == 2

    # Positive fix-confirmation (Phase 9.5 M1): within this single, uninterrupted run() call,
    # Intelligence's own prompt now genuinely contains Research's facts, because
    # EditorialTask.workflow (which CapabilityExecutor reads step_results from) is reassigned
    # and committed once per step - immediately after Research's own step completes, strictly
    # before Intelligence's step begins - not only after the entire loop finishes.
    intelligence_request_text = _request_text(gateway.received_requests[1])
    assert "did not run" not in intelligence_request_text.lower()
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in intelligence_request_text


# ---------------------------------------------------------------------------
# 2. The same dispatch-order/completion proof, through a real RoutingGateway +
#    FakeProviderAdapter - not only through FakeLLMGateway (mirrors
#    tests/test_capability_boot_wiring_e2e.py's own second variant).
# ---------------------------------------------------------------------------


class _SequencedFakeProviderAdapter(FakeProviderAdapter):
    """Test-local extension of the shared FakeProviderAdapter: returns a different, pinned
    `structured_output` per successive `generate()` call (research's call, then
    intelligence's), since both steps route to the same single fake model/provider in this
    test (CapabilityExecutor never sets `preferred_model` - §4.2, no advisory hint to route
    on). A clearly-labeled test-only substitution, not a production code path."""

    def __init__(self, provider_id: str, model_id: str, structured_outputs: list[dict[str, object]]) -> None:
        super().__init__(provider_id, model_id)
        self._structured_outputs = structured_outputs
        self.received_requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.received_requests.append(request)
        index = min(self.call_count, len(self._structured_outputs) - 1)
        self.structured_output = self._structured_outputs[index]
        return await super().generate(request)


def _model() -> ModelDescriptor:
    return ModelDescriptor(
        model_id="fake-model",
        provider_id="fake_provider",
        display_name="fake-model",
        context_window_tokens=128_000,
        supports_structured_output=True,
        pricing_tiers=[
            PricingTier(condition="standard", input_price_per_million=Decimal("1"), output_price_per_million=Decimal("1"))
        ],
    )


def _build_gateway(adapter: FakeProviderAdapter) -> RoutingGateway:
    providers = ProviderRegistry()
    providers.register(ProviderDescriptor(provider_id="fake_provider", display_name="fake_provider"), adapter)
    providers.seal()

    models = ModelRegistry()
    models.register(_model())
    models.seal()

    health_store = PermissiveProviderHealthStore()
    routing_engine = RoutingEngine(
        model_registry=models,
        provider_registry=providers,
        health_store=health_store,  # type: ignore[arg-type]
        latency_tracker=EmptyLatencyTracker(),
        policy_registry=RoutingPolicyRegistry(),
    )
    fallback_policy = FallbackPolicy(
        provider_registry=providers,
        health_store=health_store,  # type: ignore[arg-type]
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
        cost_estimator=CostEstimator(ModelRegistryPricingCatalog(models)),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
    )
    return RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)


@pytest.mark.asyncio
async def test_both_capabilities_dispatch_through_a_real_routing_gateway_and_complete(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    adapter = _SequencedFakeProviderAdapter(
        "fake_provider", "fake-model", [CANONICAL_RESEARCH_OUTPUT, _INTELLIGENCE_OUTPUT]
    )
    gateway = _build_gateway(adapter)
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    workflow_registry = _synthetic_research_intelligence_registry()

    task = await _created_task(db_session, real_news_event, workflow_registry)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].result == CANONICAL_RESEARCH_OUTPUT
    assert result.step_results[1].result == _INTELLIGENCE_OUTPUT
    assert adapter.call_count == 2


# ---------------------------------------------------------------------------
# 3. The read side of the §9.1 mechanism: CapabilityExecutor genuinely surfaces step_results
#    content that is already present in EditorialTask.workflow *before* a run begins -
#    proving the mechanism's wiring is correct given state persisted this way. Since Phase 9.5
#    M1, this is no longer the *only* scenario in which the read side fires (same-pass
#    propagation within one run() call now also works - test 1 above) - this test instead
#    proves the mechanism also works given state a resumed task would have, independent of
#    same-pass persistence. This is a direct simulation of a resumed task, clearly labeled as
#    such, not a claim that WorkflowRunner itself can resume a task from a live run today.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = WorkflowRegistry()
    workflow_registry.register(
        _research_intelligence_definition(
            [WorkflowStepDefinition(name="intelligence", capability=INTELLIGENCE_CAPABILITY_NAME, max_attempts=1, timeout_seconds=10)]
        )
    )
    workflow_registry.seal()

    task = await _created_task(db_session, real_news_event, workflow_registry)

    # Simulate "research already completed and was persisted in a prior run()" - proving the
    # read side works given state a resumed task would have, independent of the same-pass
    # per-step persistence Phase 9.5 M1 added (test 1 above covers that case).
    raw_task = await db_session.get(EditorialTask, task.id)
    assert raw_task is not None
    assert raw_task.workflow is not None
    seeded_workflow = dict(raw_task.workflow)
    seeded_workflow["completed_steps"] = ["research"]
    now = datetime.now(timezone.utc).isoformat()
    seeded_workflow["step_results"] = [
        {
            "step_name": "research",
            "status": "SUCCESS",
            "attempt": 1,
            "started_at": now,
            "finished_at": now,
            "error": None,
            "result": CANONICAL_RESEARCH_OUTPUT,
        }
    ]
    raw_task.workflow = seeded_workflow
    await db_session.commit()

    gateway = FakeLLMGateway(generate_response=_generate_response(_INTELLIGENCE_OUTPUT))
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert len(gateway.received_requests) == 1
    intelligence_request_text = _request_text(gateway.received_requests[0])
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in intelligence_request_text
    assert "did not run" not in intelligence_request_text.lower()


# ---------------------------------------------------------------------------
# 4. Negative/boundary (Contract §13): the real, frozen NEWS_ANALYSIS WorkflowDefinition,
#    run through the real, unmodified WorkflowRunner, still ends FAILED - now at the third
#    step (engagement_analysis/"engagement", unregistered) instead of the first, since
#    research/intelligence are now independently executable. Never used as a completion proof.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_news_analysis_still_fails_at_engagement_analysis_step(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    gateway = FakeLLMGateway(
        generate_responses=[_generate_response(CANONICAL_RESEARCH_OUTPUT), _generate_response(_INTELLIGENCE_OUTPUT)]
    )
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]

    command = EditorialTaskCreate(event_id=real_news_event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command)  # default (real) WorkflowRegistry
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert [r.step_name for r in result.step_results] == ["research", "intelligence", "engagement_analysis"]
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[1].status == "SUCCESS"
    assert result.step_results[2].status == "FAILED"  # "engagement" is not a registered Capability
