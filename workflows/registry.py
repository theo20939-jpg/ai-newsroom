"""WorkflowRegistry: resolves a WorkflowType to its registered WorkflowDefinition.

Built once, from the definitions declared in workflows.definitions, and never
mutated afterward - there is no dynamic registration at runtime. Every
workflow that exists in the running system was registered at import time.
No database access, no Telegram/AI dependency, no runtime state - mirrors the
immutability of services.adapter_registry.AdapterRegistry, adapted for
workflow definitions instead of source adapters.
"""
import logging

from schemas.workflow import WorkflowDefinition, WorkflowType
from workflows.definitions import content_generation, news_analysis
from workflows.errors import DuplicateWorkflowRegistrationError, UnknownWorkflowTypeError

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """Resolves a WorkflowType to its registered, immutable WorkflowDefinition.

    register() is only ever called while building the registry (see
    build_registry() below) - nothing calls it afterward, so the registry is
    effectively immutable for the lifetime of the process.
    """

    def __init__(self) -> None:
        self._definitions: dict[WorkflowType, WorkflowDefinition] = {}

    def register(self, definition: WorkflowDefinition) -> None:
        """Register one WorkflowDefinition. Raises if its (name, version) is already registered."""
        existing = self._definitions.get(definition.name)
        if existing is not None:
            raise DuplicateWorkflowRegistrationError(
                f"WorkflowType {definition.name.value} is already registered "
                f"(version {existing.version}); cannot register version {definition.version} again."
            )
        self._definitions[definition.name] = definition
        logger.info("Registered workflow %s version %d", definition.name.value, definition.version)

    def resolve(self, workflow_type: WorkflowType) -> WorkflowDefinition:
        """Return the registered WorkflowDefinition for workflow_type, or raise UnknownWorkflowTypeError."""
        definition = self._definitions.get(workflow_type)
        if definition is None:
            raise UnknownWorkflowTypeError(f"No WorkflowDefinition registered for {workflow_type}")
        return definition


def build_registry() -> WorkflowRegistry:
    """Build the Phase 5 WorkflowRegistry from the two registered definitions.

    DAILY_DIGEST is intentionally not registered - see the
    workflows.definitions package docstring.
    """
    registry = WorkflowRegistry()
    registry.register(news_analysis.DEFINITION)
    registry.register(content_generation.DEFINITION)
    return registry


registry = build_registry()
