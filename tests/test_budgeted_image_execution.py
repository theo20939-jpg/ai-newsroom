from decimal import Decimal

import pytest

from capabilities.errors import BudgetExceededError
from integrations.llm_gateway.image_protocol import (
    ImageAdapterCapabilities,
    ImageGenerationOperation,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from schemas.capability import CapabilityUsage
from services.budget_guard import ImageBudgetReservation
from services.budgeted_image_execution import BudgetedImageExecutor
from services.image_pricing import ImageExecutionProfile, ImagePricingCatalog, UnknownImagePricingError


class FakeGateway:
    CAPABILITIES = ImageAdapterCapabilities(
        supports_text_to_image=True, supports_image_edit=True,
        max_reference_images=16, supports_aspect_ratio_control=True,
    )

    def __init__(self, *, provider="openai", model="gpt-image-2", error=None):
        self.provider = provider
        self.model = model
        self.error = error
        self.calls = 0

    async def generate_image(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return ImageGenerationResponse(
            image_bytes=b"image", model_used=self.model, provider=self.provider,
            usage=CapabilityUsage(input_tokens=100, output_tokens=3533, units=1, unit_type="image"),
            request_id="req-1",
        )


class FakeGuard:
    def __init__(self, status="reserved"):
        self.status = status
        self.checked = []
        self.reserved = []
        self.completed = []

    async def check(self, capability_name, priority, worst_case):
        self.checked.append((capability_name, worst_case))

    async def reserve_image_cost(self, **kwargs):
        self.reserved.append(kwargs)
        return ImageBudgetReservation(
            status=self.status, reserved_cost=kwargs["worst_case"], attempt=1,
            prior_status="success" if self.status == "duplicate" else None,
        )

    async def complete_image_reservation(self, **kwargs):
        self.completed.append(kwargs)


def _profile(**updates):
    values = dict(
        provider="openai", model="gpt-image-2", quality="medium", size="1024x1024",
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
    )
    values.update(updates)
    return ImageExecutionProfile(**values)


def _request():
    return ImageGenerationRequest(
        prompt="A precise editorial illustration",
        metadata={"prompt_sha256": "abc123", "asset_key": "primary"},
    )


async def _execute(guard, gateway, *, mode="live", profile=None):
    return await BudgetedImageExecutor(budget_guard=guard).execute(
        gateway=gateway, request=_request(), profile=profile or _profile(), mode=mode,
        purpose="instagram", execution_id="package-1:v1", creative_id="package-1",
        package_id="package-1", opportunity_id="opp-1", max_attempts=1,
    )


@pytest.mark.asyncio
async def test_live_paid_request_with_budget_calls_provider_and_records_nonzero_cost():
    guard = FakeGuard()
    gateway = FakeGateway()
    result = await _execute(guard, gateway)
    assert result.status == "generated"
    assert gateway.calls == 1
    assert result.accounted_cost_usd == Decimal("0.0532450")
    assert result.accounted_cost_usd > 0
    assert guard.completed[0]["status"] == "success"
    assert guard.completed[0]["accounted_cost"] == result.accounted_cost_usd
    audit = guard.completed[0]["audit_fields"]
    assert audit["generation_execution_id"] == "package-1:v1"
    assert audit["prompt_sha256"] == "abc123"
    assert audit["asset_key"] == "primary"


@pytest.mark.asyncio
async def test_insufficient_budget_never_calls_provider():
    guard = FakeGuard(status="budget_exceeded")
    gateway = FakeGateway()
    with pytest.raises(BudgetExceededError):
        await _execute(guard, gateway)
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_unknown_model_pricing_fails_closed_before_provider():
    guard = FakeGuard()
    gateway = FakeGateway()
    with pytest.raises(UnknownImagePricingError):
        await _execute(guard, gateway, profile=_profile(model="unknown"))
    assert gateway.calls == 0
    assert not guard.reserved


@pytest.mark.asyncio
async def test_unknown_quality_or_size_fails_closed():
    for changes in ({"quality": "auto"}, {"size": "auto"}):
        guard = FakeGuard()
        gateway = FakeGateway()
        with pytest.raises(UnknownImagePricingError):
            await _execute(guard, gateway, profile=_profile(**changes))
        assert gateway.calls == 0


@pytest.mark.asyncio
async def test_dry_run_prices_and_checks_budget_without_provider_call():
    guard = FakeGuard()
    gateway = FakeGateway()
    result = await _execute(guard, gateway, mode="dry_run")
    assert result.status == "dry_run"
    assert result.quote is not None
    assert guard.checked
    assert not guard.reserved
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_off_mode_neither_prices_nor_calls_provider():
    guard = FakeGuard()
    gateway = FakeGateway()
    result = await _execute(guard, gateway, mode="off", profile=_profile(model="unknown"))
    assert result.status == "off"
    assert gateway.calls == 0
    assert not guard.checked and not guard.reserved


@pytest.mark.asyncio
async def test_failed_dispatched_call_retains_reservation_and_is_audited():
    guard = FakeGuard()
    gateway = FakeGateway(error=RuntimeError("provider failure"))
    with pytest.raises(RuntimeError, match="provider failure"):
        await _execute(guard, gateway)
    assert gateway.calls == 1
    assert guard.completed[0]["status"] == "failed"
    assert guard.completed[0]["accounted_cost"] is None


@pytest.mark.asyncio
async def test_attempt_ceiling_blocks_provider():
    guard = FakeGuard(status="attempt_limit")
    gateway = FakeGateway()
    result = await _execute(guard, gateway)
    assert result.status == "attempt_limit"
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_duplicate_execution_id_does_not_pay_twice():
    guard = FakeGuard(status="duplicate")
    gateway = FakeGateway()
    result = await _execute(guard, gateway)
    assert result.status == "duplicate"
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_gemini_profile_is_representable_and_distinct():
    from integrations.llm_gateway.image_protocol import ReferenceImage

    profile = _profile(
        provider="gemini", model="gemini-3.1-flash-image", quality="standard", size="1K",
        operation=ImageGenerationOperation.IMAGE_EDIT,
    )
    request = ImageGenerationRequest(
        prompt="Preserve the subject", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=b"x", mime_type="image/png"),),
    )
    quote = ImagePricingCatalog().quote(profile, request)
    accounted = quote.cost_from_usage(input_tokens=2500, output_tokens=1300)
    assert quote.expected_cost_usd > Decimal("0.067")
    assert quote.worst_case_cost_usd > quote.expected_cost_usd
    assert accounted > quote.expected_cost_usd
    assert accounted <= quote.worst_case_cost_usd
    assert quote.cost_semantics == "configured_conservative_usage_estimate"


def test_real_paid_profile_can_never_resolve_to_zero_cost():
    quote = ImagePricingCatalog().quote(_profile(), _request())
    assert quote.expected_cost_usd > 0
    assert quote.worst_case_cost_usd >= quote.expected_cost_usd
