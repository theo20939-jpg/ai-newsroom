"""Transport adapter for the frozen Telegram publication gate.

The factual contract and decision rules live in kage_publication_factual_gate;
this module only calls the gateway and records the result for the worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID, uuid4

from schemas.capability import CapabilityCall
from services.cost_tracker import CostTracker, compute_call_cost
from services.kage_publication_factual_gate import (
    build_gate_input, build_gate_request, publication_decision, validate_gate_output,
)
from services.kage_reaction_safety import reaction_safety_issues
from services.pricing_catalog import PricingCatalog

GATE_MODEL = "gpt-5.6-luna"
GATE_REASONING = "medium"
GATE_MAX_OUTPUT_TOKENS = 1655


@dataclass(frozen=True)
class WorkerGateResult:
    publication_block: bool
    technical_block: bool
    factual_block: bool
    guard_block: bool
    record: dict[str, Any]


async def evaluate_worker_publication_gate(
    *, gateway: Any, prompt_repository: Any, draft: Mapping[str, Any] | None,
    research: Mapping[str, Any] | None, intelligence: Mapping[str, Any] | None,
    source_headline: str, event_id: UUID, draft_id: UUID, task_id: UUID,
    cost_tracker: CostTracker | None = None, pricing_catalog: PricingCatalog | None = None,
    quality_result: Mapping[str, Any] | None = None,
) -> WorkerGateResult:
    """One bounded gate call; every missing/failed/incomplete transport is a block."""
    record: dict[str, Any] = {
        "event_id": str(event_id), "draft_id": str(draft_id), "task_id": str(task_id),
        "model": GATE_MODEL, "reasoning_effort": GATE_REASONING,
        "max_output_tokens": GATE_MAX_OUTPUT_TOKENS,
        "input_tokens": None, "reasoning_tokens": None, "output_tokens": None,
        "finish_reason": None, "structured_output_valid": False,
        "factual_safety": None, "headline_safety": None, "body_safety": None,
        "unsupported_claim_count": None, "local_guard_result": None,
        "final_publication_block": True, "gate_cost_usd": None,
        "technical_error": None,
    }
    stage = "evidence"
    gate_input = None
    guard_issues: list[str] = []
    try:
        if draft is None or research is None or intelligence is None:
            raise ValueError("required draft/evidence output missing")
        gate_input = build_gate_input(
            draft=draft, research=research, intelligence=intelligence,
            source_headline=source_headline,
        )
        guard_issues = reaction_safety_issues(
            draft, research, intelligence, source_headline=source_headline,
        )
        record["local_guard_result"] = "FAIL" if guard_issues else "PASS"
        stage = "request"
        if gateway is None or prompt_repository is None:
            raise ValueError("publication gate gateway or prompt repository missing")
        prompt = prompt_repository.resolve("publication_factual_gate", "1")
        request = build_gate_request(
            gate_input, prompt, model=GATE_MODEL,
            max_tokens=GATE_MAX_OUTPUT_TOKENS, reasoning_effort=GATE_REASONING,
        )
        request = request.model_copy(update={
            "metadata": {**request.metadata, "trace_id": str(task_id),
                         "capability_execution_id": f"{task_id}:publication_factual_gate:1",
                         "request_id": str(uuid4())},
        })
        stage = "provider"
        started = datetime.now(timezone.utc)
        response = await gateway.generate(request)
        finished = datetime.now(timezone.utc)
        stage = "response"
        if response is None:
            raise ValueError("publication gate response missing")
        record["finish_reason"] = response.finish_reason
        record["model"] = response.model_used
        record["input_tokens"] = response.usage.input_tokens
        record["reasoning_tokens"] = response.usage.reasoning_tokens
        record["output_tokens"] = response.usage.output_tokens
        if pricing_catalog is not None:
            stage = "cost_accounting"
            call = CapabilityCall(
                call_id=uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
                model_used=response.model_used, provider="openai",
                prompt_name="publication_factual_gate", prompt_version="1",
                usage=response.usage, started_at=started, finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
            )
            record["gate_cost_usd"] = str(compute_call_cost(call, pricing_catalog))
            if cost_tracker is not None:
                await cost_tracker.record(task_id, "publication_factual_gate", call)
        stage = "validation"
        if response.model_used != GATE_MODEL:
            raise ValueError("publication gate model mismatch")
        if response.finish_reason != "stop":
            raise ValueError("publication gate response incomplete")
        if response.structured_output is None:
            raise ValueError("publication gate structured output missing")
        validate_gate_output(response.structured_output, gate_input)
        record["structured_output_valid"] = True
        record["factual_safety"] = response.structured_output["FACTUAL_SAFETY"]
        record["headline_safety"] = response.structured_output["HEADLINE_SAFETY"]
        record["body_safety"] = response.structured_output["BODY_SAFETY"]
        record["unsupported_claim_count"] = len(response.structured_output["UNSUPPORTED_CLAIMS"])
        decision = publication_decision(
            response.structured_output, gate_input, local_guard_issues=guard_issues,
            quality_9_2_result=quality_result,
        )
        factual_block = "FACTUAL_SAFETY_FAIL" in decision["reasons"]
        guard_block = bool(guard_issues)
        record["final_publication_block"] = decision["PUBLICATION_BLOCK"]
        return WorkerGateResult(decision["PUBLICATION_BLOCK"], False, factual_block, guard_block, record)
    except Exception as exc:
        # No provider/transport/parser/contract exception may authorize delivery.
        record["technical_error"] = f"{stage}:{type(exc).__name__}"
        record["final_publication_block"] = True
        return WorkerGateResult(True, True, False, bool(guard_issues), record)
