"""One-shot, fail-closed contract validation of raw generated KAGE NEWS pixels."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.config import settings
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.llm_gateway.providers.base import build_openai_credential
from integrations.llm_gateway.providers.openai_adapter import build_bounded_openai_adapter
from services.kage_telegram_canary_envelope import (
    VISUAL_COMPLIANCE_INPUT_PRICE_PER_MILLION,
    VISUAL_COMPLIANCE_INPUT_TOKEN_CAP,
    VISUAL_COMPLIANCE_MODEL,
    VISUAL_COMPLIANCE_OUTPUT_PRICE_PER_MILLION,
    VISUAL_COMPLIANCE_OUTPUT_TOKEN_CAP,
    VISUAL_COMPLIANCE_STAGE,
    CanaryPreDispatchSafetyRejection,
    current_telegram_canary_envelope,
    visual_compliance_worst_case,
)

_CHECKS = (
    "readable_text_present",
    "logo_or_wordmark_present",
    "interface_or_webpage_present",
    "document_or_fake_evidence_present",
    "chart_or_data_graphic_present",
    "identifiable_real_person_present",
    "named_person_likeness_risk",
    "unsupported_branded_product_present",
    "obvious_visual_story_mismatch",
)

COMPLIANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{name: {"type": "boolean"} for name in _CHECKS},
        "decision": {"type": "string", "enum": ["COMPLIANT", "REJECT"]},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 9},
    },
    "required": [*_CHECKS, "decision", "reasons"],
    "additionalProperties": False,
}

_SYSTEM = """You are a narrow product-safety validator for a generated editorial image.
Inspect the actual pixels. This is not an aesthetic review. Mark a check true when the forbidden
element is visibly present or reasonably recognizable. Tiny accidental texture that is not readable
is not text. A generic unbranded device is not a branded product. REJECT if any check is true;
otherwise COMPLIANT. Do not infer facts outside the pixels and supplied safe visual concept."""


@dataclass(frozen=True)
class VisualComplianceResult:
    decision: str
    checks: dict[str, bool]
    reasons: tuple[str, ...]
    failure_reason: str | None = None
    model: str = VISUAL_COMPLIANCE_MODEL
    input_tokens: int | None = None
    output_tokens: int | None = None
    actual_cost_usd: Decimal | None = None

    @property
    def compliant(self) -> bool:
        return self.failure_reason is None and self.decision == "COMPLIANT" and not any(self.checks.values())

    def audit(self) -> dict[str, Any]:
        return {
            "decision": self.decision, **self.checks, "reasons": list(self.reasons),
            "failure_reason": self.failure_reason, "model": self.model,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "actual_cost_usd": str(self.actual_cost_usd) if self.actual_cost_usd is not None else None,
        }


def rejected(reason: str) -> VisualComplianceResult:
    return VisualComplianceResult("REJECT", {name: False for name in _CHECKS}, (), reason)


def _parse(output: object, *, input_tokens: int, output_tokens: int, cost: Decimal) -> VisualComplianceResult:
    if not isinstance(output, dict) or set(output) != {*_CHECKS, "decision", "reasons"}:
        return rejected("malformed_result")
    if any(type(output[name]) is not bool for name in _CHECKS):
        return rejected("malformed_result")
    decision, reasons = output["decision"], output["reasons"]
    if decision not in {"COMPLIANT", "REJECT"} or not isinstance(reasons, list) or not all(
        isinstance(item, str) for item in reasons
    ):
        return rejected("malformed_result")
    checks = {name: output[name] for name in _CHECKS}
    if any(checks.values()):
        decision = "REJECT"  # deterministic backstop; never trust a contradictory pass
    elif decision != "COMPLIANT":
        decision = "REJECT"
    return VisualComplianceResult(decision, checks, tuple(reasons), input_tokens=input_tokens,
                                  output_tokens=output_tokens, actual_cost_usd=cost)


async def inspect_generated_visual(
    image_bytes: bytes, *, safe_visual_concept: str, gateway: Any | None = None,
) -> VisualComplianceResult:
    """Inspect once. Any provider, parsing, usage or accounting gap returns REJECT."""
    envelope = current_telegram_canary_envelope()
    if envelope is None:
        return rejected("story_cost_ledger_unavailable")
    try:
        envelope.authorize_visual_dispatch(stage=VISUAL_COMPLIANCE_STAGE,
                                           model_id=VISUAL_COMPLIANCE_MODEL,
                                           reserved_usd=visual_compliance_worst_case())
    except CanaryPreDispatchSafetyRejection as exc:
        return rejected(f"cost_envelope_refused:{exc}")

    adapter = gateway
    if adapter is None:
        if settings.openai_api_key is None:
            envelope.record_visual_result(stage=VISUAL_COMPLIANCE_STAGE, actual_cost_usd=None,
                                          status="FAILED")
            return rejected("openai_api_key_absent")
        adapter = build_bounded_openai_adapter(build_openai_credential(settings), max_retries=0,
                                               timeout_seconds=60)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=_SYSTEM)]),
            Message(role="user", content=[
                ContentPart(type="text", text=f"Safe visual concept:\n{safe_visual_concept}"),
                ContentPart(type="artifact_ref", artifact_ref=data_uri, mime_type="image/jpeg"),
            ]),
        ],
        preferred_model=VISUAL_COMPLIANCE_MODEL,
        preferred_provider="openai",
        max_tokens=VISUAL_COMPLIANCE_OUTPUT_TOKEN_CAP,
        reasoning_effort="none",
        response_mode="json_schema",
        response_schema=COMPLIANCE_SCHEMA,
        modalities=["text", "image"],
        metadata={"capability_name": VISUAL_COMPLIANCE_STAGE},
    )
    try:
        response = await adapter.generate(request)
    except Exception as exc:  # noqa: BLE001 - a single bounded attempt fails closed
        envelope.record_visual_result(stage=VISUAL_COMPLIANCE_STAGE, actual_cost_usd=None,
                                      status="FAILED")
        return rejected(f"provider_error:{type(exc).__name__}")
    usage = response.usage
    input_tokens, output_tokens = usage.input_tokens, usage.output_tokens
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        envelope.record_visual_result(stage=VISUAL_COMPLIANCE_STAGE, actual_cost_usd=None,
                                      status="COST_UNKNOWN")
        return rejected("missing_usage_accounting")
    if input_tokens > VISUAL_COMPLIANCE_INPUT_TOKEN_CAP or output_tokens > VISUAL_COMPLIANCE_OUTPUT_TOKEN_CAP:
        envelope.record_visual_result(stage=VISUAL_COMPLIANCE_STAGE, actual_cost_usd=None,
                                      status="USAGE_EXCEEDED_BOUND")
        return rejected("usage_exceeded_reservation")
    cost = (
        Decimal(input_tokens) * VISUAL_COMPLIANCE_INPUT_PRICE_PER_MILLION
        + Decimal(output_tokens) * VISUAL_COMPLIANCE_OUTPUT_PRICE_PER_MILLION
    ) / Decimal(1_000_000)
    envelope.record_visual_result(stage=VISUAL_COMPLIANCE_STAGE, actual_cost_usd=cost,
                                  status="SUCCEEDED", input_tokens=input_tokens,
                                  output_tokens=output_tokens)
    return _parse(response.structured_output, input_tokens=input_tokens, output_tokens=output_tokens, cost=cost)
