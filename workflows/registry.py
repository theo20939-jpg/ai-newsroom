"""WorkflowRegistry: resolves a WorkflowType to its registered WorkflowDefinition.

Built once, from the definitions declared in workflows.definitions, then
sealed - after seal() is called, register() raises RegistryAlreadySealedError
instead of silently accepting more definitions. Immutability is therefore
enforced, not just conventional: nothing can register a workflow at runtime
even if it tried to. No database access, no Telegram/AI dependency, no
runtime state - mirrors the immutability of
services.adapter_registry.AdapterRegistry, adapted for workflow definitions
instead of source adapters.
"""
import logging

from schemas.workflow import WorkflowDefinition, WorkflowType
from workflows.definitions import (
    content_generation,
    meme_generation,
    news_analysis,
    telegraph_article,
    telegraph_research,
)
from workflows.errors import (
    DuplicateWorkflowRegistrationError,
    RegistryAlreadySealedError,
    UnknownWorkflowTypeError,
)

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """Resolves a WorkflowType to its registered, immutable WorkflowDefinition.

    Mutable (via register()) only until seal() is called - see build_registry()
    below, which seals the registry before handing it back. Every workflow
    that exists in the running system was registered before that point.
    """

    def __init__(self) -> None:
        self._definitions: dict[WorkflowType, WorkflowDefinition] = {}
        self._sealed = False

    def register(self, definition: WorkflowDefinition) -> None:
        """Register one WorkflowDefinition.

        Raises RegistryAlreadySealedError if the registry has been sealed, or
        DuplicateWorkflowRegistrationError if its (name, version) is already
        registered.
        """
        if self._sealed:
            raise RegistryAlreadySealedError(
                f"Cannot register {definition.name.value} version {definition.version}: "
                "this WorkflowRegistry is sealed and accepts no further definitions."
            )
        existing = self._definitions.get(definition.name)
        if existing is not None:
            raise DuplicateWorkflowRegistrationError(
                f"WorkflowType {definition.name.value} is already registered "
                f"(version {existing.version}); cannot register version {definition.version} again."
            )
        self._definitions[definition.name] = definition
        logger.info("Registered workflow %s version %d", definition.name.value, definition.version)

    def seal(self) -> None:
        """Permanently stop accepting further register() calls."""
        self._sealed = True

    def resolve(self, workflow_type: WorkflowType) -> WorkflowDefinition:
        """Return the registered WorkflowDefinition for workflow_type, or raise UnknownWorkflowTypeError.

        Read-only regardless of seal state - resolve() works identically
        before and after sealing.
        """
        definition = self._definitions.get(workflow_type)
        if definition is None:
            raise UnknownWorkflowTypeError(f"No WorkflowDefinition registered for {workflow_type}")
        return definition


def build_registry() -> WorkflowRegistry:
    """Build and seal the WorkflowRegistry from the registered definitions.

    DAILY_DIGEST is intentionally not registered - see the
    workflows.definitions package docstring. MEME_GENERATION is registered as of Phase 18 M4
    (docs/phase18_m4_meme_copywriting_report.md) - see workflows/definitions/meme_generation.py's
    own docstring for why registering it is safe (no automatic caller creates a task for it yet).
    TELEGRAPH_RESEARCH is registered as of TELEGRAPH Checkpoint 3 - safe for the identical
    reason: only services/telegraph_research_processor.py::process_approved_telegraph_proposal()
    creates a task for it, and nothing calls that function automatically (no scheduler/worker
    path exists yet).
    """
    registry = WorkflowRegistry()
    registry.register(news_analysis.DEFINITION)
    registry.register(content_generation.DEFINITION)
    registry.register(meme_generation.DEFINITION)
    registry.register(telegraph_research.DEFINITION)
    # TELEGRAPH Checkpoint 5: registered like TELEGRAPH_RESEARCH - safe for the identical reason
    # (only services/telegraph_article_processor.py::generate_article_for_researched_proposal()
    # creates a task for it, and nothing calls that automatically).
    registry.register(telegraph_article.DEFINITION)
    registry.seal()
    return registry


registry = build_registry()
