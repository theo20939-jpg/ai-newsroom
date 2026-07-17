"""Boot-sequence assembly and validation helpers
(docs/phase7_architecture_contract.md §19, §3 rule 7, §6 rule 4).

Built up across several milestones:
  - M4: validate_registry_consistency() only.
  - M16 (this checkpoint): validate_retry_ceiling().
  - M19: assemble_ai_integration_layer(), the fixed boot sequence.
"""
from integrations.llm_gateway.errors import RegistryConsistencyError, RetryCeilingExceededError
from integrations.llm_gateway.models.registry import ModelRegistry
from integrations.llm_gateway.providers.base import ProviderRegistry

DEFAULT_RETRY_MULTIPLICATION_CEILING = 30


def validate_registry_consistency(providers: ProviderRegistry, models: ModelRegistry) -> None:
    """After both ProviderRegistry and ModelRegistry seal, confirm every
    ModelDescriptor.provider_id resolves in ProviderRegistry (§3 rule 7).

    Raises RegistryConsistencyError on the first mismatch found - the process MUST fail to
    start when this is raised.
    """
    for model in models.all_models():
        if not providers.is_enabled(model.provider_id):
            raise RegistryConsistencyError(
                f"ModelDescriptor '{model.model_id}' names provider_id='{model.provider_id}', "
                "which is not registered in ProviderRegistry."
            )


def validate_retry_ceiling(
    workflow_retry_max_attempts: int,
    max_fallback_attempts: int,
    max_same_candidate_retries: int,
    *,
    ceiling: int = DEFAULT_RETRY_MULTIPLICATION_CEILING,
    capability_name: str | None = None,
) -> None:
    """§6 rule 4: pure arithmetic, no runtime cost. Computes
    WorkflowRetryPolicy.max_attempts x max_fallback_attempts x (1 + max_same_candidate_retries)
    for one Capability's effective configuration and raises RetryCeilingExceededError - not
    merely logs a warning - if the product exceeds `ceiling` (recommended default: 30).

    Called once per registered Capability at boot (at CapabilityRegistry seal time, or an
    equivalent boot-sequence validation, §19) - `capability_name` is included in the error
    message when the caller has one, to make a boot-time failure immediately actionable.
    """
    total_attempts = workflow_retry_max_attempts * max_fallback_attempts * (1 + max_same_candidate_retries)
    if total_attempts > ceiling:
        subject = f"capability '{capability_name}'" if capability_name else "this configuration"
        raise RetryCeilingExceededError(
            f"Retry-multiplication ceiling exceeded for {subject}: "
            f"{workflow_retry_max_attempts} (workflow) x {max_fallback_attempts} (fallback) x "
            f"{1 + max_same_candidate_retries} (1 + same-candidate retries) = {total_attempts} "
            f"> ceiling {ceiling}."
        )
