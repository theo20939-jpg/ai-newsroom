"""RoutingPolicyRegistry (docs/phase7_architecture_contract.md §4.5). Sealed-after-boot,
explicit-registration-only, identical discipline to every other registry in this contract (P18).
"""
from integrations.llm_gateway.errors import (
    RoutingPolicyRegistryAlreadySealedError,
    UnknownRoutingObjectiveError,
)
from integrations.llm_gateway.routing.policy import RoutingPolicy


class RoutingPolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, RoutingPolicy] = {}
        self._sealed = False

    def register(self, objective: str, policy: RoutingPolicy) -> None:
        if self._sealed:
            raise RoutingPolicyRegistryAlreadySealedError(
                f"Cannot register objective '{objective}': this RoutingPolicyRegistry is "
                "sealed and accepts no further registrations."
            )
        self._policies[objective] = policy

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, objective: str) -> RoutingPolicy:
        policy = self._policies.get(objective)
        if policy is None:
            raise UnknownRoutingObjectiveError(f"No RoutingPolicy registered for objective '{objective}'")
        return policy
