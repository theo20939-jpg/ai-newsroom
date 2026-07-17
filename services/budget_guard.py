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
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Protocol

from redis.asyncio import Redis

from capabilities.errors import BudgetExceededError
from core.config import Settings
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import MissingRedisFailurePolicyError
from services.cost_tracker import global_ledger_key


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
        self._max_daily_ai_cost = settings.max_daily_ai_cost
        self._ledger_namespace = ledger_namespace

    def _namespace(self) -> str:
        return self._ledger_namespace if self._ledger_namespace is not None else _today_namespace()

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        if self._max_daily_ai_cost is None:
            return  # no ceiling configured - always allow

        key = global_ledger_key(self._namespace())
        try:
            raw_spent = await self._redis.get(key)
        except Exception as exc:
            if self._failure_policy == "fail_open":
                return
            raise BudgetExceededError(
                "BudgetGuard ledger unavailable and redis_unavailable_policy=fail_closed"
            ) from exc

        spent_so_far = Decimal(str(raw_spent)) if raw_spent is not None else Decimal("0")
        ceiling = Decimal(str(self._max_daily_ai_cost))
        if spent_so_far + worst_case > ceiling:
            raise BudgetExceededError(
                f"Budget exceeded for capability '{capability_name}' (priority={priority.value}): "
                f"today's spend {spent_so_far} + worst_case {worst_case} > ceiling {ceiling}"
            )
