"""One budgeted execution boundary for production paid image generation.

Callers supply product purpose and stable package/creative identities. Provider adapters remain
low-level request translators; this boundary owns pricing, atomic budget reservation,
idempotency, attempt limits and non-secret Redis audit metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from capabilities.errors import BudgetExceededError
from core.config import settings
from core.redis import get_redis_client
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.image_protocol import (
    ImageGenerationGateway,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from services.budget_guard import RedisBudgetGuard
from services.image_pricing import ImageExecutionProfile, ImagePriceQuote, ImagePricingCatalog

ImageExecutionMode = Literal["off", "dry_run", "live"]


class ImageCostUnaccountedError(RuntimeError):
    retryable = False


class ImageCostBoundExceededError(RuntimeError):
    retryable = False

    def __init__(self, *, actual_cost_usd: Decimal, reserved_cost_usd: Decimal, response: ImageGenerationResponse) -> None:
        super().__init__(
            f"actual image cost ${actual_cost_usd} exceeded provisional reservation ${reserved_cost_usd}"
        )
        self.actual_cost_usd = actual_cost_usd
        self.reserved_cost_usd = reserved_cost_usd
        self.response = response


@dataclass(frozen=True)
class BudgetedImageResult:
    status: Literal["off", "dry_run", "generated", "duplicate", "attempt_limit"]
    quote: ImagePriceQuote | None = None
    response: ImageGenerationResponse | None = None
    accounted_cost_usd: Decimal | None = None
    cost_semantics: str | None = None
    attempt: int = 0


class BudgetedImageExecutor:
    def __init__(
        self,
        *,
        budget_guard: RedisBudgetGuard,
        pricing_catalog: ImagePricingCatalog | None = None,
    ) -> None:
        self._budget_guard = budget_guard
        self._pricing = pricing_catalog or ImagePricingCatalog()

    async def execute(
        self,
        *,
        gateway: ImageGenerationGateway,
        request: ImageGenerationRequest,
        profile: ImageExecutionProfile,
        mode: ImageExecutionMode,
        purpose: str,
        execution_id: str,
        creative_id: str,
        package_id: str | None = None,
        opportunity_id: str | None = None,
        max_attempts: int = 1,
        priority: TaskPriority = TaskPriority.B,
    ) -> BudgetedImageResult:
        if mode == "off":
            return BudgetedImageResult(status="off")

        quote = self._pricing.quote(profile, request)  # unknown pricing fails closed here
        capability_name = f"image_generation:{purpose}"

        if mode == "dry_run":
            # Dry-run proves the same quote can fit the current configured ledger, but never
            # claims an idempotency key and never invokes the paid adapter.
            await self._budget_guard.check(capability_name, priority, quote.worst_case_cost_usd)
            return BudgetedImageResult(
                status="dry_run", quote=quote, accounted_cost_usd=Decimal("0"),
                cost_semantics="dry_run_no_charge",
            )

        reservation = await self._budget_guard.reserve_image_cost(
            capability_name=capability_name,
            priority=priority,
            worst_case=quote.worst_case_cost_usd,
            execution_id=execution_id,
            creative_id=creative_id,
            max_attempts=max_attempts,
        )
        if reservation.status == "budget_exceeded":
            raise BudgetExceededError(f"daily budget exceeded for {capability_name}")
        if reservation.status == "duplicate":
            return BudgetedImageResult(
                status="duplicate", quote=quote, accounted_cost_usd=reservation.reserved_cost,
                cost_semantics="existing_reservation", attempt=reservation.attempt,
            )
        if reservation.status == "attempt_limit":
            return BudgetedImageResult(
                status="attempt_limit", quote=quote, accounted_cost_usd=Decimal("0"),
                cost_semantics="provider_not_called", attempt=reservation.attempt,
            )

        base_audit = {
            "provider": profile.provider,
            "model": profile.model,
            "quality": profile.quality,
            "size": profile.size,
            "operation": profile.operation.value,
            "purpose": purpose,
            "generation_execution_id": execution_id,
            "package_id": package_id or "",
            "opportunity_id": opportunity_id or "",
            "prompt_sha256": str(request.metadata.get("prompt_sha256") or ""),
            "asset_key": str(request.metadata.get("asset_key") or ""),
            "pricing_version": quote.pricing_version,
            "cost_semantics": quote.cost_semantics,
            "expected_cost_usd": str(quote.expected_cost_usd),
        }
        try:
            response = await gateway.generate_image(request)
            if response.provider != profile.provider or response.model_used != profile.model:
                raise RuntimeError(
                    "image provider response does not match reserved pricing profile: "
                    f"{response.provider}/{response.model_used}"
                )
        except Exception as exc:
            await self._budget_guard.complete_image_reservation(
                execution_id=execution_id,
                capability_name=capability_name,
                status="failed",
                accounted_cost=None,
                audit_fields={**base_audit, "error_type": type(exc).__name__},
            )
            raise

        if quote.requires_reported_usage and (
            response.usage.input_tokens is None or response.usage.output_tokens is None
        ):
            # Provisional-cap pricing cannot cost a response without token usage: book the full
            # reservation against the budget and refuse the image so no unaccounted visual ships.
            await self._budget_guard.complete_image_reservation(
                execution_id=execution_id,
                capability_name=capability_name,
                status="success",
                accounted_cost=quote.worst_case_cost_usd,
                audit_fields={
                    **base_audit,
                    "accounted_cost_usd": str(quote.worst_case_cost_usd),
                    "accounted_cost_semantics": "usage_missing_worst_case_booked",
                    "provider_request_id": response.request_id or "",
                    "provider_status_code": str(response.provider_status_code or ""),
                },
            )
            raise ImageCostUnaccountedError("paid image response carried no token usage; cost unaccounted")

        if quote.requires_detailed_input_usage and (
            response.usage.text_input_tokens is None or response.usage.image_input_tokens is None
        ):
            await self._budget_guard.complete_image_reservation(
                execution_id=execution_id,
                capability_name=capability_name,
                status="success",
                accounted_cost=quote.worst_case_cost_usd,
                audit_fields={
                    **base_audit,
                    "accounted_cost_usd": str(quote.worst_case_cost_usd),
                    "accounted_cost_semantics": "usage_breakdown_missing_worst_case_booked",
                    "provider_request_id": response.request_id or "",
                    "provider_status_code": str(response.provider_status_code or ""),
                },
            )
            raise ImageCostUnaccountedError(
                "paid image response carried no text/image input usage breakdown; cost unaccounted"
            )

        accounted_cost = quote.cost_from_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            text_input_tokens=response.usage.text_input_tokens,
            image_input_tokens=response.usage.image_input_tokens,
        )
        if accounted_cost <= 0:
            # A live paid provider must never silently become a zero-cost record.
            accounted_cost = quote.expected_cost_usd
        bound_exceeded = accounted_cost > quote.worst_case_cost_usd
        await self._budget_guard.complete_image_reservation(
            execution_id=execution_id,
            capability_name=capability_name,
            status="cost_bound_exceeded" if bound_exceeded else "success",
            accounted_cost=accounted_cost,
            audit_fields={
                **base_audit,
                "accounted_cost_usd": str(accounted_cost),
                "accounted_cost_semantics": quote.cost_semantics,
                "provider_request_id": response.request_id or "",
                "provider_status_code": str(response.provider_status_code or ""),
                "input_tokens": str(response.usage.input_tokens or 0),
                "text_input_tokens": str(response.usage.text_input_tokens or 0),
                "image_input_tokens": str(response.usage.image_input_tokens or 0),
                "output_tokens": str(response.usage.output_tokens or 0),
                "cost_bound_exceeded": "true" if bound_exceeded else "false",
            },
        )
        if bound_exceeded:
            raise ImageCostBoundExceededError(
                actual_cost_usd=accounted_cost,
                reserved_cost_usd=quote.worst_case_cost_usd,
                response=response,
            )
        return BudgetedImageResult(
            status="generated", quote=quote, response=response,
            accounted_cost_usd=accounted_cost, cost_semantics=quote.cost_semantics,
            attempt=reservation.attempt,
        )


def build_budgeted_image_executor() -> BudgetedImageExecutor:
    redis = get_redis_client()
    return BudgetedImageExecutor(budget_guard=RedisBudgetGuard(redis, settings))


class PaidImageExecutionBlockedError(RuntimeError):
    retryable = False


class BudgetedImageGateway:
    """Protocol-compatible facade used by existing callers without moving policy into adapters."""

    def __init__(
        self,
        *,
        gateway: ImageGenerationGateway,
        executor: BudgetedImageExecutor,
        profile: ImageExecutionProfile,
        mode: ImageExecutionMode,
        purpose: str,
        execution_id: str,
        creative_id: str,
        package_id: str | None = None,
        opportunity_id: str | None = None,
        max_attempts: int = 1,
    ) -> None:
        self._gateway = gateway
        self._executor = executor
        self._profile = profile
        self._mode = mode
        self._purpose = purpose
        self._execution_id = execution_id
        self._creative_id = creative_id
        self._package_id = package_id
        self._opportunity_id = opportunity_id
        self._max_attempts = max_attempts

    @property
    def CAPABILITIES(self):  # noqa: N802 - provider protocol convention
        return self._gateway.CAPABILITIES

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        result = await self._executor.execute(
            gateway=self._gateway,
            request=request,
            profile=self._profile,
            mode=self._mode,
            purpose=self._purpose,
            execution_id=self._execution_id,
            creative_id=self._creative_id,
            package_id=self._package_id,
            opportunity_id=self._opportunity_id,
            max_attempts=self._max_attempts,
        )
        if result.status != "generated" or result.response is None:
            raise PaidImageExecutionBlockedError(f"paid image execution blocked: {result.status}")
        return result.response.model_copy(
            update={"cost_usd": str(result.accounted_cost_usd)}
        )
