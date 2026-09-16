"""BudgetGuard (docs/phase6_architecture_contract.md §9; docs/phase7_architecture_contract.md
§15.2, Amendment C §25).

Pre-flight, READ-ONLY budget check - may reject a proposed call before any provider call is
made. Never writes spend data, never calls LLMGateway or a provider. A separate,
non-overlapping concern from CostTracker (services.cost_tracker), which is post-hoc and
write-only - the two are never merged (P5, §9's binding rule, restated unchanged by Amendment C).

Amendment C relocates the call site from Capability to the Routing Gateway (specifically
FallbackPolicy, §5.4) and changes what check() is given: `worst_case: Decimal`, the estimate
CostEstimator (§15.1) produces - not Phase 6's original `BudgetCheckRequest{estimated_usage:
CapabilityUsage}`. No production code called the old signature (Amendment B already deferred
any real BudgetGuard invocation, and capabilities/executor.py confirms CapabilityExecutor never
calls it either) - this is a clean signature replacement, not a change to any exercised call
site. `BudgetCheckRequest` is removed; only the Phase 6 shape-only test
(tests/test_budget_guard_protocol.py) needed updating to match.

API cost optimization (docs/api_cost_optimization_report.md §10): `RedisBudgetGuard` now reads
`settings.llm_budget_mode`/`llm_daily_budget_usd` instead of the never-wired-up
`max_daily_ai_cost` - the same Redis ledger, the same pre-flight call site (unchanged), just a
real, enforceable three-state mode (off/shadow/enforce) instead of an optional ceiling nothing
ever actually populated (the ledger was never written to at all until this same task wired
CostTracker.record() into capabilities/executor.py - see that module's own docstring). "shadow"
computes and logs the exact same allow/deny decision "enforce" would make, but never raises -
the safe default until real spend data validates the accounting.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Protocol

from redis.asyncio import Redis

from capabilities.errors import BudgetExceededError
from core.config import Settings
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import MissingRedisFailurePolicyError
from services.cost_tracker import global_ledger_key

logger = logging.getLogger(__name__)

_IMAGE_RESERVATION_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class ImageBudgetReservation:
    status: Literal["reserved", "duplicate", "attempt_limit", "budget_exceeded"]
    reserved_cost: Decimal
    attempt: int = 0
    prior_status: str | None = None


def image_execution_key(namespace: str, execution_id: str) -> str:
    return f"phase7:image_execution:{namespace}:{execution_id}"


def image_attempt_key(namespace: str, creative_id: str) -> str:
    return f"phase7:image_attempts:{namespace}:{creative_id}"


class BudgetGuard(Protocol):
    """Consulted by the Routing Gateway (FallbackPolicy) before each dispatch attempt it
    intends to make - never by Capability (Amendment C)."""

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        """Raise BudgetExceededError (capabilities.errors) if the proposed call would exceed
        budget. Read-only - MUST NOT write spend data, MUST NOT call LLMGateway or a
        provider."""
        ...


def _today_namespace() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class RedisBudgetGuard:
    """The only implementation of BudgetGuard in this delivery. Reads the same Redis-backed
    daily spend ledger RedisCostTracker writes (never an independent ledger, §9's binding
    rule) - denies if today's recorded spend plus `worst_case` would exceed
    `settings.max_daily_ai_cost`. No ceiling is enforced if that setting is left unset (None),
    matching its existing "reserved, optional" default. `priority` is accepted (matching the
    Protocol shape and included in the denial message) but does not currently scale the
    ceiling per tier - the contract specifies no tier-based allocation formula, so none is
    invented here.

    Requires `settings.redis_unavailable_policy` to be set at construction - raises
    MissingRedisFailurePolicyError otherwise (§28 Q1's binding provisional rule: a ledger
    *read* failure is exactly the case this policy governs, per §18's CostTracker row - unlike
    a ledger *write* failure, which is never call-blocking regardless of policy).

    `ledger_namespace`: None (the production default) computes the real UTC calendar date at
    each call, matching RedisCostTracker's own default so both sides agree on "today" without
    explicit coordination; tests inject a fixed, uuid-based namespace instead for isolation.
    """

    def __init__(
        self,
        redis_client: Redis,
        settings: Settings,
        *,
        ledger_namespace: str | None = None,
    ) -> None:
        if settings.redis_unavailable_policy is None:
            raise MissingRedisFailurePolicyError(
                "BudgetGuard's ledger read requires settings.redis_unavailable_policy to be "
                "explicitly set ('fail_open' or 'fail_closed') before construction (§28 Q1)."
            )
        self._redis = redis_client
        self._failure_policy: Literal["fail_open", "fail_closed"] = settings.redis_unavailable_policy
        self._mode: Literal["off", "shadow", "enforce"] = settings.llm_budget_mode
        self._daily_budget_usd = Decimal(str(settings.llm_daily_budget_usd))
        self._daily_warning_usd = Decimal(str(settings.llm_daily_warning_usd))
        self._ledger_namespace = ledger_namespace

    def _namespace(self) -> str:
        return self._ledger_namespace if self._ledger_namespace is not None else _today_namespace()

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        if self._mode == "off":
            return  # no blocking, no accounting - the explicit escape hatch

        key = global_ledger_key(self._namespace())
        try:
            raw_spent = await self._redis.get(key)
        except Exception as exc:
            if self._failure_policy == "fail_open":
                return
            if self._mode == "enforce":
                raise BudgetExceededError(
                    "BudgetGuard ledger unavailable and redis_unavailable_policy=fail_closed"
                ) from exc
            return  # shadow mode never blocks, even on a ledger read failure

        spent_so_far = Decimal(str(raw_spent)) if raw_spent is not None else Decimal("0")
        projected = spent_so_far + worst_case
        would_exceed = projected > self._daily_budget_usd

        if spent_so_far >= self._daily_warning_usd:
            logger.warning(
                "llm_daily_spend_warning_threshold_crossed",
                extra={
                    "capability": capability_name, "priority": priority.value,
                    "spent_so_far": str(spent_so_far), "warning_threshold": str(self._daily_warning_usd),
                    "daily_budget": str(self._daily_budget_usd), "mode": self._mode,
                },
            )

        if not would_exceed:
            return

        if self._mode == "shadow":
            logger.info(
                "llm_daily_budget_would_be_exceeded_shadow_mode",
                extra={
                    "capability": capability_name, "priority": priority.value,
                    "spent_so_far": str(spent_so_far), "worst_case": str(worst_case),
                    "projected": str(projected), "daily_budget": str(self._daily_budget_usd),
                },
            )
            return

        # enforce
        logger.warning(
            "llm_daily_budget_exceeded_call_denied",
            extra={
                "capability": capability_name, "priority": priority.value,
                "spent_so_far": str(spent_so_far), "worst_case": str(worst_case),
                "projected": str(projected), "daily_budget": str(self._daily_budget_usd),
            },
        )
        raise BudgetExceededError(
            f"Daily LLM budget exceeded for capability '{capability_name}' (priority={priority.value}): "
            f"today's spend {spent_so_far} + worst_case {worst_case} > daily budget {self._daily_budget_usd}"
        )

    async def reserve_image_cost(
        self,
        *,
        capability_name: str,
        priority: TaskPriority,
        worst_case: Decimal,
        execution_id: str,
        creative_id: str,
        max_attempts: int,
    ) -> ImageBudgetReservation:
        """Atomically reserve one paid image call against the existing daily ledger.

        Image LIVE execution is intentionally stricter than the legacy text-call shadow mode:
        a paid image call always enforces ``llm_daily_budget_usd``.  The Lua transaction checks
        existing spend, claims the idempotency key, increments the creative attempt counter and
        reserves spend in one Redis operation, so concurrent workers cannot both pass a stale
        read.  Reserved cost remains charged in the internal ledger after provider dispatch,
        including provider failures, because neither supported API guarantees failed work is
        free.  This is conservative accounting, labelled as a configured estimate by the
        execution boundary.
        """
        if worst_case <= 0:
            raise ValueError("image reservation cost must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        from services.cost_tracker import capability_ledger_key

        namespace = self._namespace()
        global_key = global_ledger_key(namespace)
        capability_key = capability_ledger_key(namespace, capability_name)
        execution_key = image_execution_key(namespace, execution_id)
        attempt_key = image_attempt_key(namespace, creative_id)
        script = """
local prior = redis.call('HGET', KEYS[3], 'status')
if prior then
  local prior_attempt = redis.call('HGET', KEYS[3], 'attempt') or '0'
  return {'duplicate', prior, prior_attempt}
end
local attempts = tonumber(redis.call('GET', KEYS[4]) or '0')
if attempts >= tonumber(ARGV[3]) then
  return {'attempt_limit', '', tostring(attempts)}
end
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
if spent + cost > tonumber(ARGV[2]) then
  return {'budget_exceeded', '', tostring(attempts)}
end
local attempt = redis.call('INCR', KEYS[4])
redis.call('EXPIRE', KEYS[4], ARGV[4])
redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
redis.call('INCRBYFLOAT', KEYS[2], ARGV[1])
redis.call('HSET', KEYS[3], 'status', 'reserved', 'reserved_cost_usd', ARGV[1],
  'cost_semantics', 'configured_worst_case_estimate', 'attempt', tostring(attempt),
  'capability_name', ARGV[5], 'priority', ARGV[6])
redis.call('EXPIRE', KEYS[3], ARGV[4])
return {'reserved', '', tostring(attempt)}
"""
        try:
            raw = await self._redis.eval(
                script,
                4,
                global_key,
                capability_key,
                execution_key,
                attempt_key,
                str(worst_case),
                str(self._daily_budget_usd),
                str(max_attempts),
                str(_IMAGE_RESERVATION_TTL_SECONDS),
                capability_name,
                priority.value,
            )
        except Exception as exc:
            # Paid image execution is always fail-closed.  A missing/unavailable reservation
            # ledger must never degrade to an unbudgeted provider call.
            raise BudgetExceededError("Image budget reservation ledger unavailable") from exc

        status = str(raw[0])
        prior_status = str(raw[1]) or None
        attempt = int(raw[2])
        return ImageBudgetReservation(
            status=status, reserved_cost=worst_case, attempt=attempt, prior_status=prior_status
        )

    async def complete_image_reservation(
        self,
        *,
        execution_id: str,
        capability_name: str,
        status: Literal["success", "failed"],
        accounted_cost: Decimal | None,
        audit_fields: dict[str, str],
    ) -> None:
        """Settle an image reservation and attach non-secret audit metadata.

        Successful calls may replace the conservative worst-case reservation with a smaller
        deterministic usage/configured estimate. Failed dispatched calls retain the reservation
        because provider refund semantics are not guaranteed. Settlement and ledger adjustment
        are atomic, and a repeated settlement is a no-op.
        """
        from services.cost_tracker import capability_ledger_key

        namespace = self._namespace()
        key = image_execution_key(namespace, execution_id)
        global_key = global_ledger_key(namespace)
        capability_key = capability_ledger_key(namespace, capability_name)
        fields = {"status": status, **audit_fields}
        try:
            if not await self._redis.exists(key):
                raise BudgetExceededError("Image reservation disappeared before settlement")
            if status == "success" and accounted_cost is not None:
                script = """
local current = redis.call('HGET', KEYS[3], 'status')
if current ~= 'reserved' then return 0 end
local reserved = tonumber(redis.call('HGET', KEYS[3], 'reserved_cost_usd') or '0')
local actual = tonumber(ARGV[1])
if actual > 0 and actual <= reserved then
  local delta = actual - reserved
  redis.call('INCRBYFLOAT', KEYS[1], tostring(delta))
  redis.call('INCRBYFLOAT', KEYS[2], tostring(delta))
end
redis.call('HSET', KEYS[3], 'status', 'success', 'accounted_cost_usd', ARGV[1])
return 1
"""
                await self._redis.eval(
                    script, 3, global_key, capability_key, key, str(accounted_cost)
                )
            await self._redis.hset(key, mapping=fields)
            await self._redis.expire(key, _IMAGE_RESERVATION_TTL_SECONDS)
        except BudgetExceededError:
            raise
        except Exception as exc:
            raise BudgetExceededError("Image reservation audit settlement failed") from exc
