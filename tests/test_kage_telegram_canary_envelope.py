from decimal import Decimal
from pathlib import Path

import pytest

from integrations.llm_gateway.errors import ProviderPermanentIncompatibleError, UnknownModelPricingError
from integrations.llm_gateway.models.catalog import GPT_5_6_LUNA, GPT_5_6_SOL, GPT_5_6_TERRA
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from services.kage_telegram_canary_envelope import (
    CANARY_HARD_CAP_USD,
    CANARY_MAX_PROVIDER_DISPATCHES,
    CANARY_MODEL_ROUTE,
    CANARY_STAGE_INPUT_TOKEN_CAPS,
    CANARY_STAGE_ORDER,
    CANARY_STAGE_OUTPUT_TOKEN_CAPS,
    TelegramCanaryEnvelope,
    maximum_canary_cost,
    serialized_input_token_upper_bound,
    stage_for_request,
    validate_request_envelope_contracts,
)


def _request(
    stage: str,
    text: str = "representative accepted NEWS input",
    *,
    max_tokens: int | None = -1,
) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text=text)])],
        max_tokens=CANARY_STAGE_OUTPUT_TOKEN_CAPS[stage] if max_tokens == -1 else max_tokens,
        response_mode="json_schema",
        response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        metadata={"capability_name": stage},
    )


def test_computed_envelope_is_deterministic_and_below_hard_cap() -> None:
    assert maximum_canary_cost() == Decimal("0.746389")
    assert maximum_canary_cost() <= CANARY_HARD_CAP_USD
    assert CANARY_MODEL_ROUTE == ("gpt-5.6-luna", "gpt-5.6-terra")
    assert CANARY_MAX_PROVIDER_DISPATCHES == 12


def test_every_reachable_stage_has_finite_input_and_output_caps() -> None:
    assert set(CANARY_STAGE_INPUT_TOKEN_CAPS) == set(CANARY_STAGE_OUTPUT_TOKEN_CAPS) == set(CANARY_STAGE_ORDER)
    assert all(value > 0 for value in CANARY_STAGE_INPUT_TOKEN_CAPS.values())
    assert all(value > 0 for value in CANARY_STAGE_OUTPUT_TOKEN_CAPS.values())


def test_frozen_request_contract_fits_every_canary_stage_before_arming(monkeypatch) -> None:
    contracts = validate_request_envelope_contracts()
    assert set(contracts) == set(CANARY_STAGE_ORDER)
    assert contracts["research"] == (1400, 1400)
    assert contracts["copywriting"] == (900, 900)
    assert contracts["quality"] == (700, 700)

    monkeypatch.setitem(CANARY_STAGE_OUTPUT_TOKEN_CAPS, "research", 1399)
    with pytest.raises(ProviderPermanentIncompatibleError, match="contract mismatch"):
        validate_request_envelope_contracts()


def test_research_1400_is_accepted_and_1401_fails_before_dispatch() -> None:
    envelope = TelegramCanaryEnvelope()
    assert envelope.begin_stage(_request("research", max_tokens=1400)) == "research"
    assert envelope._spent_reserved == Decimal("0")  # noqa: SLF001

    oversized = TelegramCanaryEnvelope()
    with pytest.raises(ProviderPermanentIncompatibleError, match="output cap"):
        oversized.begin_stage(_request("research", max_tokens=1401))
    assert oversized._spent_reserved == Decimal("0")  # noqa: SLF001


@pytest.mark.parametrize(("stage", "accepted", "rejected"), [
    ("research", 1400, 1401),
    ("copywriting", 900, 901),
    ("quality", 700, 701),
])
def test_kage_request_limits_fit_and_values_above_contract_fail_before_dispatch(
    stage: str, accepted: int, rejected: int,
) -> None:
    envelope = TelegramCanaryEnvelope()
    assert envelope.begin_stage(_request(stage, max_tokens=accepted)) == stage

    oversized = TelegramCanaryEnvelope()
    with pytest.raises(ProviderPermanentIncompatibleError, match="output cap"):
        oversized.begin_stage(_request(stage, max_tokens=rejected))
    assert oversized._spent_reserved == Decimal("0")  # noqa: SLF001


def test_current_prompt_assets_and_representative_news_payloads_fit_stage_caps() -> None:
    root = Path(__file__).resolve().parents[1]
    prompt_bytes = {
        "director_editorial_gate": (root / "prompts/director_editorial_gate/v1.yaml").stat().st_size,
        "research": (root / "prompts/research/v5.yaml").stat().st_size,
        "intelligence": (root / "prompts/intelligence/v4.yaml").stat().st_size,
        "copywriting": (root / "prompts/copywriting/v11.10.yaml").stat().st_size,
        "quality": (root / "prompts/quality/v9.2.yaml").stat().st_size,
        "publication_factual_gate": (root / "prompts/publication_factual_gate/v1.yaml").stat().st_size,
    }
    representative_payload_bytes = {
        "director_editorial_gate": 4_096,
        "research": 20_000,  # headline, source article, language and request framing
        "intelligence": 12_000,  # Research facts and request framing
        "copywriting": 18_000,  # evidence facts, bounded 6,000-char excerpt and draft context
        "quality": 20_000,  # story contract, evidence and generated draft
        "publication_factual_gate": 3_800,  # gate contract, facts and final copy
    }
    for stage in CANARY_STAGE_ORDER:
        assert prompt_bytes[stage] + representative_payload_bytes[stage] + 256 < CANARY_STAGE_INPUT_TOKEN_CAPS[stage]


def test_application_input_upper_bound_counts_serialized_schema_and_messages() -> None:
    request = _request("copywriting")
    assert serialized_input_token_upper_bound(request) > len("representative accepted NEWS input")
    envelope = TelegramCanaryEnvelope()
    assert envelope.begin_stage(request) == "copywriting"


def test_publication_gate_stage_is_resolved_from_its_existing_execution_identity() -> None:
    request = _request("research").model_copy(update={
        "metadata": {"capability_execution_id": "task-id:publication_factual_gate:1"},
    })
    assert stage_for_request(request) == "publication_factual_gate"


def test_capability_stage_is_resolved_from_call_generate_execution_identity() -> None:
    request = _request("research").model_copy(update={
        "metadata": {
            "capability_execution_id": "00000000-0000-0000-0000-000000000001:research:1",
        },
    })
    assert stage_for_request(request) == "research"


def test_oversized_request_fails_closed_before_provider_dispatch() -> None:
    envelope = TelegramCanaryEnvelope()
    request = _request("research", "x" * CANARY_STAGE_INPUT_TOKEN_CAPS["research"])
    with pytest.raises(ProviderPermanentIncompatibleError, match="exceeds stage cap"):
        envelope.begin_stage(request)
    assert envelope._spent_reserved == Decimal("0")  # noqa: SLF001


def test_missing_output_cap_fails_closed_before_provider_dispatch() -> None:
    envelope = TelegramCanaryEnvelope()
    request = _request("director_editorial_gate", max_tokens=None)
    with pytest.raises(ProviderPermanentIncompatibleError, match="output cap"):
        envelope.begin_stage(request)
    assert envelope._spent_reserved == Decimal("0")  # noqa: SLF001


def test_unexpected_or_unpriced_route_fails_closed() -> None:
    with pytest.raises(UnknownModelPricingError, match="route is incomplete"):
        maximum_canary_cost((GPT_5_6_LUNA,))
    envelope = TelegramCanaryEnvelope()
    envelope.begin_stage(_request("research"))
    other = GPT_5_6_TERRA.model_copy(update={"model_id": "unregistered-model"})
    with pytest.raises(ProviderPermanentIncompatibleError, match="outside bounded route"):
        envelope.authorize_dispatch(_request("research"), other)

    euro_model = GPT_5_6_LUNA.model_copy(update={"pricing_currency": "EUR"})
    with pytest.raises(UnknownModelPricingError, match="missing USD standard pricing"):
        envelope.authorize_dispatch(_request("research"), euro_model)


def test_stage_dispatch_count_is_two_models_once_each_no_same_model_retry() -> None:
    envelope = TelegramCanaryEnvelope()
    request = _request("research")
    envelope.begin_stage(request)
    envelope.authorize_dispatch(request, GPT_5_6_LUNA)
    with pytest.raises(ProviderPermanentIncompatibleError, match="repeated provider dispatch"):
        envelope.authorize_dispatch(request, GPT_5_6_LUNA)
    envelope.authorize_dispatch(request, GPT_5_6_TERRA)
    with pytest.raises(ProviderPermanentIncompatibleError, match="repeated provider dispatch"):
        envelope.authorize_dispatch(request, GPT_5_6_TERRA)
    assert envelope.same_model_retries() == 0


def test_route_keeps_only_the_two_priced_canary_models_in_fixed_cost_order() -> None:
    envelope = TelegramCanaryEnvelope()
    assert envelope.allowed_models([GPT_5_6_SOL, GPT_5_6_TERRA, GPT_5_6_LUNA]) == [
        GPT_5_6_LUNA,
        GPT_5_6_TERRA,
    ]


def test_maximum_reachable_dispatch_graph_stays_inside_one_envelope() -> None:
    envelope = TelegramCanaryEnvelope()
    for stage in CANARY_STAGE_ORDER:
        request = _request(stage)
        envelope.begin_stage(request)
        for model in (GPT_5_6_LUNA, GPT_5_6_TERRA):
            envelope.authorize_dispatch(request, model)
        envelope.end_stage(stage)
    assert envelope._spent_reserved == Decimal("0.746389")  # noqa: SLF001
    assert envelope._spent_reserved <= envelope.hard_cap_usd


def test_budget_below_computed_maximum_is_rejected_at_envelope_start() -> None:
    with pytest.raises(ProviderPermanentIncompatibleError, match="exceeds hard cap"):
        TelegramCanaryEnvelope(hard_cap_usd=Decimal("0.70"))
