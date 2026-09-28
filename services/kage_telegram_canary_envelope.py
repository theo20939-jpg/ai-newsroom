"""One-run, Telegram-only hard provider-spend envelope.

The limits here apply only while ``telegram_canary_envelope`` is active. Normal
worker calls retain the existing routing, retry, and budget behavior.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterator

from integrations.llm_gateway.errors import ProviderPermanentIncompatibleError, UnknownModelPricingError
from integrations.llm_gateway.models.catalog import GPT_5_6_LUNA, GPT_5_6_TERRA
from integrations.llm_gateway.models.registry import ModelDescriptor
from integrations.llm_gateway.protocol import GenerateRequest

CANARY_HARD_CAP_USD = Decimal("1.00")
CANARY_MODEL_ROUTE = ("gpt-5.6-luna", "gpt-5.6-terra")
CANARY_MAX_DISPATCHES_PER_STAGE = 2
CANARY_WORKFLOW_STEP_ATTEMPTS = 1
CANARY_SAME_MODEL_RETRIES = 0

# Per-request serialized-input ceilings, including prompt, evidence, schema, and message
# framing. Research has a 64 KiB total request ceiling; downstream structured stages get
# 32 KiB for bounded upstream outputs plus their source/draft context; the two compact
# gate requests get 8 KiB. Requests above these deterministic application limits are
# rejected before dispatch, never truncated. UTF-8 byte length upper-bounds text token
# count; an additional 256 tokens reserve protocol framing overhead.
CANARY_STAGE_INPUT_TOKEN_CAPS: dict[str, int] = {
    "director_editorial_gate": 8_192,
    "research": 65_536,
    "intelligence": 32_768,
    "copywriting": 32_768,
    "quality": 32_768,
    "publication_factual_gate": 8_192,
}
CANARY_STAGE_OUTPUT_TOKEN_CAPS: dict[str, int] = {
    "director_editorial_gate": 350,
    "research": 1_400,
    "intelligence": 500,
    "copywriting": 900,
    "quality": 700,
    "publication_factual_gate": 1_655,
}
CANARY_STAGE_ORDER = tuple(CANARY_STAGE_INPUT_TOKEN_CAPS)
CANARY_MAX_PROVIDER_DISPATCHES = len(CANARY_STAGE_ORDER) * CANARY_MAX_DISPATCHES_PER_STAGE
_INPUT_FRAMING_RESERVE_TOKENS = 256


class CanaryPreDispatchSafetyRejection(ProviderPermanentIncompatibleError, UnknownModelPricingError):
    """Deterministic canary guard rejection raised before provider dispatch."""


def validate_request_envelope_contracts() -> dict[str, tuple[int, int]]:
    """Fail before arming if any frozen request can exceed its canary bound."""
    from capabilities.executor import content_generation_output_token_contract
    from services.director_editorial_gate_llm import GATE_MAX_OUTPUT_TOKENS
    from services.kage_publication_worker_gate import GATE_MAX_OUTPUT_TOKENS as PUBLICATION_GATE_MAX

    contracts = content_generation_output_token_contract(kage_11_10=True)
    contracts.update({
        "director_editorial_gate": GATE_MAX_OUTPUT_TOKENS,
        "publication_factual_gate": PUBLICATION_GATE_MAX,
    })
    mismatches = {
        stage: (request_cap, CANARY_STAGE_OUTPUT_TOKEN_CAPS.get(stage, 0))
        for stage, request_cap in contracts.items()
        if request_cap > CANARY_STAGE_OUTPUT_TOKEN_CAPS.get(stage, 0)
    }
    if set(contracts) != set(CANARY_STAGE_OUTPUT_TOKEN_CAPS) or mismatches:
        raise CanaryPreDispatchSafetyRejection(
            f"telegram canary: request/envelope output contract mismatch: {mismatches or 'stage set mismatch'}"
        )
    return {
        stage: (request_cap, CANARY_STAGE_OUTPUT_TOKEN_CAPS[stage])
        for stage, request_cap in contracts.items()
    }


def stage_for_request(request: GenerateRequest) -> str:
    stage = request.metadata.get("capability_name")
    if stage is None:
        execution_id = request.metadata.get("capability_execution_id")
        if isinstance(execution_id, str):
            # call_generate stamps <task UUID>:<capability name>:<attempt>; it does not
            # separately add capability_name to request metadata.
            parts = execution_id.rsplit(":", 2)
            if len(parts) == 3 and parts[2].isdigit():
                stage = parts[1]
    if not isinstance(stage, str) or stage not in CANARY_STAGE_INPUT_TOKEN_CAPS:
        raise CanaryPreDispatchSafetyRejection("telegram canary: unknown provider stage")
    return stage


def serialized_input_token_upper_bound(request: GenerateRequest) -> int:
    """Conservative token upper bound for the exact text/schema material sent to the model."""
    payload: dict[str, object] = {
        "input": [
            {
                "role": message.role,
                "content": [
                    {
                        "type": part.type,
                        "text": part.text,
                        "artifact_ref": part.artifact_ref,
                        "mime_type": part.mime_type,
                    }
                    for part in message.content
                ],
            }
            for message in request.messages
        ],
    }
    if request.response_mode == "json_schema" and request.response_schema is not None:
        payload["schema"] = request.response_schema
    if request.tools:
        payload["tools"] = [tool.model_dump(mode="json") for tool in request.tools]
    serialized_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return serialized_bytes + _INPUT_FRAMING_RESERVE_TOKENS


def _per_dispatch_cost(stage: str, model: ModelDescriptor) -> Decimal:
    output_cap = CANARY_STAGE_OUTPUT_TOKEN_CAPS[stage]
    tier = next((tier for tier in model.pricing_tiers if tier.condition == "standard"), None)
    if tier is None or model.pricing_currency != "USD":
        raise CanaryPreDispatchSafetyRejection(
            f"telegram canary: missing USD standard pricing for {model.model_id}"
        )
    input_tokens = CANARY_STAGE_INPUT_TOKEN_CAPS[stage]
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * tier.input_price_per_million
        + Decimal(output_cap) * tier.output_price_per_million
    ) / million


# The only billable visual call reachable on the KAGE Telegram NEWS path: the legacy router's
# Gemini source-photo recomposition (services/editorial_recomposition.py::maybe_recompose). One
# dispatch at most, on one priced model, reserved at its deterministic worst case. Vision subject
# matching is not a stage here: under this envelope it is rejected before dispatch (unknown stage).
VISUAL_RECOMPOSITION_STAGE = "news_recomposition"
VISUAL_RECOMPOSITION_MODEL = "gemini-3.1-flash-image"
VISUAL_RECOMPOSITION_MAX_DISPATCHES = 1


def visual_recomposition_worst_case() -> Decimal:
    """Worst case of one recomposition dispatch, from the existing image pricing catalog."""
    from integrations.llm_gateway.image_protocol import (
        ImageGenerationOperation, ImageGenerationRequest, ReferenceImage,
    )
    from services.image_pricing import ImageExecutionProfile, ImagePricingCatalog

    profile = ImageExecutionProfile(
        provider="gemini", model=VISUAL_RECOMPOSITION_MODEL, quality="standard", size="1K",
        operation=ImageGenerationOperation.IMAGE_EDIT,
    )
    probe = ImageGenerationRequest(
        prompt="worst-case pricing probe", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=b"\x00", mime_type="image/png"),),
    )
    return ImagePricingCatalog().quote(profile, probe).worst_case_cost_usd * VISUAL_RECOMPOSITION_MAX_DISPATCHES


def maximum_text_canary_cost(models: tuple[ModelDescriptor, ...] = (GPT_5_6_LUNA, GPT_5_6_TERRA)) -> Decimal:
    """All six text stages once; each eligible model at most once per stage."""
    by_id = {model.model_id: model for model in models}
    if set(by_id) != set(CANARY_MODEL_ROUTE):
        raise CanaryPreDispatchSafetyRejection("telegram canary: model route is incomplete or unexpected")
    return sum(
        (_per_dispatch_cost(stage, by_id[model_id]) for stage in CANARY_STAGE_ORDER for model_id in CANARY_MODEL_ROUTE),
        Decimal("0"),
    )


def maximum_canary_cost(models: tuple[ModelDescriptor, ...] = (GPT_5_6_LUNA, GPT_5_6_TERRA)) -> Decimal:
    """Per-story hard maximum: every text stage plus the one bounded visual dispatch."""
    return maximum_text_canary_cost(models) + visual_recomposition_worst_case()


@dataclass
class TelegramCanaryEnvelope:
    """Tracks one ordered pass through the Telegram generation stages."""

    hard_cap_usd: Decimal = CANARY_HARD_CAP_USD
    max_cost_usd: Decimal | None = None
    _active_stage: str | None = None
    _active_index: int = -1
    _used_models: dict[str, set[str]] | None = None
    _spent_reserved: Decimal = Decimal("0")
    dispatch_records: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        self.max_cost_usd = maximum_canary_cost()
        if self.max_cost_usd > self.hard_cap_usd:
            raise CanaryPreDispatchSafetyRejection(
                f"telegram canary: computed maximum ${self.max_cost_usd} exceeds hard cap ${self.hard_cap_usd}"
            )
        self._used_models = {stage: set() for stage in CANARY_STAGE_ORDER}
        self.dispatch_records = []

    def begin_stage(self, request: GenerateRequest) -> str:
        stage = stage_for_request(request)
        index = CANARY_STAGE_ORDER.index(stage)
        if index <= self._active_index:
            raise CanaryPreDispatchSafetyRejection("telegram canary: duplicate or out-of-order stage")
        self._active_stage = stage
        self._active_index = index
        self._validate_request(stage, request)
        return stage

    def end_stage(self, stage: str) -> None:
        if self._active_stage != stage:
            raise CanaryPreDispatchSafetyRejection("telegram canary: stage state mismatch")
        self._active_stage = None

    def allowed_models(self, ranked: list[ModelDescriptor]) -> list[ModelDescriptor]:
        by_id = {model.model_id: model for model in ranked}
        return [by_id[model_id] for model_id in CANARY_MODEL_ROUTE if model_id in by_id]

    def same_model_retries(self) -> int:
        return CANARY_SAME_MODEL_RETRIES

    def workflow_step_attempts(self) -> int:
        return CANARY_WORKFLOW_STEP_ATTEMPTS

    def authorize_dispatch(self, request: GenerateRequest, model: ModelDescriptor) -> None:
        stage = stage_for_request(request)
        self._validate_request(stage, request)
        if self._active_stage != stage or self._used_models is None:
            raise CanaryPreDispatchSafetyRejection("telegram canary: no active stage")
        if model.model_id not in CANARY_MODEL_ROUTE:
            raise CanaryPreDispatchSafetyRejection("telegram canary: model is outside bounded route")
        if model.model_id in self._used_models[stage]:
            raise CanaryPreDispatchSafetyRejection("telegram canary: repeated provider dispatch denied")

        current_cost = _per_dispatch_cost(stage, model)
        pending = self._pending_maximum(stage, model.model_id)
        if self._spent_reserved + current_cost + pending > self.hard_cap_usd:
            raise CanaryPreDispatchSafetyRejection("telegram canary: remaining hard envelope is insufficient")
        self._used_models[stage].add(model.model_id)
        self._spent_reserved += current_cost
        assert self.dispatch_records is not None
        self.dispatch_records.append({
            "stage": stage,
            "model": model.model_id,
            "input_token_upper_bound": serialized_input_token_upper_bound(request),
            "output_token_cap": CANARY_STAGE_OUTPUT_TOKEN_CAPS[stage],
            "reserved_max_cost_usd": str(current_cost),
            "remaining_hard_envelope_usd": str(self.hard_cap_usd - self._spent_reserved),
            "actual_input_tokens": None,
            "actual_output_tokens": None,
            "actual_cost_usd": None,
            "status": "DISPATCH_AUTHORIZED",
        })

    def record_response(self, stage: str, model: ModelDescriptor, usage: object) -> None:
        if not self.dispatch_records:
            raise ProviderPermanentIncompatibleError("telegram canary: provider response without dispatch record")
        record = self.dispatch_records[-1]
        if record["stage"] != stage or record["model"] != model.model_id:
            raise ProviderPermanentIncompatibleError("telegram canary: provider response attribution mismatch")
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ProviderPermanentIncompatibleError("telegram canary: provider token usage unavailable")
        if (
            input_tokens > int(record["input_token_upper_bound"])
            or output_tokens > int(record["output_token_cap"])
        ):
            raise ProviderPermanentIncompatibleError("telegram canary: provider usage exceeded request bounds")
        tier = next((tier for tier in model.pricing_tiers if tier.condition == "standard"), None)
        if tier is None or model.pricing_currency != "USD":
            raise UnknownModelPricingError(
                f"telegram canary: missing USD standard pricing for {model.model_id}"
            )
        actual_cost = (
            Decimal(input_tokens) * tier.input_price_per_million
            + Decimal(output_tokens) * tier.output_price_per_million
        ) / Decimal(1_000_000)
        if actual_cost > Decimal(str(record["reserved_max_cost_usd"])):
            raise ProviderPermanentIncompatibleError("telegram canary: actual usage exceeded request reservation")
        record.update({
            "actual_input_tokens": input_tokens,
            "actual_output_tokens": output_tokens,
            "actual_cost_usd": str(actual_cost),
            "remaining_hard_envelope_usd": str(self.hard_cap_usd - self._spent_reserved),
            "status": "SUCCEEDED",
        })

    def authorize_visual_dispatch(self, *, stage: str, model_id: str, reserved_usd: Decimal) -> None:
        """Reserve the one bounded visual dispatch inside this same per-story ledger, or refuse."""
        if stage != VISUAL_RECOMPOSITION_STAGE or model_id != VISUAL_RECOMPOSITION_MODEL:
            raise CanaryPreDispatchSafetyRejection("telegram canary: visual call is outside the bounded visual stage")
        assert self.dispatch_records is not None
        if sum(1 for r in self.dispatch_records if r["stage"] == stage) >= VISUAL_RECOMPOSITION_MAX_DISPATCHES:
            raise CanaryPreDispatchSafetyRejection("telegram canary: repeated visual dispatch denied")
        if reserved_usd <= 0 or reserved_usd > visual_recomposition_worst_case():
            raise CanaryPreDispatchSafetyRejection("telegram canary: visual reservation is not the priced worst case")
        if self._spent_reserved + reserved_usd > self.hard_cap_usd:
            raise CanaryPreDispatchSafetyRejection("telegram canary: remaining hard envelope is insufficient")
        self._spent_reserved += reserved_usd
        self.dispatch_records.append({
            "stage": stage, "model": model_id, "input_token_upper_bound": None, "output_token_cap": None,
            "reserved_max_cost_usd": str(reserved_usd),
            "remaining_hard_envelope_usd": str(self.hard_cap_usd - self._spent_reserved),
            "actual_input_tokens": None, "actual_output_tokens": None, "actual_cost_usd": None,
            "status": "DISPATCH_AUTHORIZED",
        })

    def record_visual_result(self, *, stage: str, actual_cost_usd: Decimal | None, status: str) -> None:
        """Attach the provider-accounted cost; an unknown cost stays None (fails closed downstream)."""
        record = next((r for r in reversed(self.dispatch_records or []) if r["stage"] == stage), None)
        if record is None:
            raise ProviderPermanentIncompatibleError("telegram canary: visual result without dispatch record")
        record.update({
            "actual_cost_usd": str(actual_cost_usd) if actual_cost_usd is not None else None,
            "status": status if actual_cost_usd is None or actual_cost_usd <= Decimal(str(record["reserved_max_cost_usd"]))
            else "ACTUAL_EXCEEDED_RESERVATION",
        })

    def record_failure(self, stage: str, model: ModelDescriptor, failure_type: str) -> None:
        if not self.dispatch_records:
            return
        record = self.dispatch_records[-1]
        if record["stage"] == stage and record["model"] == model.model_id:
            record.update({"status": "FAILED", "failure_type": failure_type})

    def _validate_request(self, stage: str, request: GenerateRequest) -> None:
        output_cap = CANARY_STAGE_OUTPUT_TOKEN_CAPS.get(stage)
        input_cap = CANARY_STAGE_INPUT_TOKEN_CAPS.get(stage)
        if output_cap is None or input_cap is None:
            raise CanaryPreDispatchSafetyRejection("telegram canary: missing stage bound")
        if request.max_tokens is None or request.max_tokens <= 0 or request.max_tokens > output_cap:
            raise CanaryPreDispatchSafetyRejection("telegram canary: missing or excessive output cap")
        input_upper = serialized_input_token_upper_bound(request)
        if input_upper > input_cap:
            raise CanaryPreDispatchSafetyRejection(
                f"telegram canary: serialized input upper bound {input_upper} exceeds stage cap {input_cap}"
            )

    def _pending_maximum(self, stage: str, model_id: str) -> Decimal:
        """Worst case for remaining eligible dispatches, including later stages."""
        models = {GPT_5_6_LUNA.model_id: GPT_5_6_LUNA, GPT_5_6_TERRA.model_id: GPT_5_6_TERRA}
        current_index = CANARY_STAGE_ORDER.index(stage)
        pending = Decimal("0")
        if model_id == CANARY_MODEL_ROUTE[0]:
            pending += _per_dispatch_cost(stage, models[CANARY_MODEL_ROUTE[1]])
        for later_stage in CANARY_STAGE_ORDER[current_index + 1 :]:
            pending += sum((_per_dispatch_cost(later_stage, models[mid]) for mid in CANARY_MODEL_ROUTE), Decimal("0"))
        # The visual dispatch follows every text stage; text must never consume its reservation.
        return pending + visual_recomposition_worst_case()


_active_envelope: ContextVar[TelegramCanaryEnvelope | None] = ContextVar("telegram_canary_envelope", default=None)


def current_telegram_canary_envelope() -> TelegramCanaryEnvelope | None:
    return _active_envelope.get()


@contextmanager
def telegram_canary_envelope(envelope: TelegramCanaryEnvelope | None = None) -> Iterator[TelegramCanaryEnvelope]:
    selected = envelope or TelegramCanaryEnvelope()
    token: Token[TelegramCanaryEnvelope | None] = _active_envelope.set(selected)
    try:
        yield selected
    finally:
        _active_envelope.reset(token)
