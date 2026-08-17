"""Pydantic contracts for the Capability Framework (Phase 6).

Per docs/phase6_architecture_contract.md §3-§4. CapabilityContext is one
immutable object composed of three nested, frozen sub-models - not a
3-parameter split (§3 rationale). CapabilityResult supports zero, one, or
many AI calls via `calls: list[CapabilityCall]` - never a scalar
model_used/prompt_name/prompt_version/usage field (§4 binding rules).

NewsEventSnapshot/WorkflowExecutionStateSnapshot are read-only snapshots
built by capabilities.executor.CapabilityExecutor - never the SQLAlchemy
NewsEvent/EditorialTask rows themselves (§3, no ORM object crosses into a
Capability).
"""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from database.models.editorial_task import TaskPriority


class NewsEventSnapshot(BaseModel):
    """Read-only snapshot of the NewsEvent a Capability is operating on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    title: str
    summary: str | None
    content: str | None
    url: str | None
    category: str
    published_at: datetime | None


class WorkflowExecutionStateSnapshot(BaseModel):
    """Read-only snapshot of prior Workflow progress, for step chaining (P4).

    step_results maps a completed step's name to its result payload - only
    steps that finished SUCCESS with a non-null result are included, since
    those are the only prior outputs a later Capability could meaningfully
    read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_name: str
    workflow_version: int
    completed_steps: list[str]
    step_results: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BusinessContext(BaseModel):
    """Domain data the capability operates on. Read-only snapshots, never ORM objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    news_event: NewsEventSnapshot
    workflow_state: WorkflowExecutionStateSnapshot
    # The desired EDITORIAL OUTPUT language a Capability should write its result in - not the
    # source NewsEvent's own language (docs/content_generation_language_final_implementation_plan.md,
    # Concern 2). Grouped under "editorial config" alongside audience/brand_voice below by original
    # Phase 6 design intent (docs/phase6_architecture_review.md). Source language is a separate,
    # currently-unwired concept (schemas/source_definition.py's SourceDefinition.language) - never
    # conflated with this field. capabilities.executor.CapabilityExecutor._build_context() explicitly
    # injects core.config.settings.default_content_language here in production; this schema-level
    # default only applies to a BusinessContext constructed without doing so (e.g. a test fixture).
    language: str = "en"
    audience: str | None = None
    brand_voice: dict[str, Any] | None = None
    # Phase 19 M1/M2 (services/evidence_package.py): the full, cleaned article text - only ever
    # non-None when article_acquisition_mode == "enforce" AND a usable acquisition exists;
    # capabilities.executor.CapabilityExecutor._build_context() is the sole place this is
    # populated. A narrow, purpose-built read model (not the full EvidencePackage - "no ORM
    # object crosses into a Capability" extends to "no internal-service-shaped object either",
    # matching this schema's own established snapshot convention).
    article_evidence_text: str | None = None
    article_evidence_completeness: str | None = None
    # Phase 19 M13 (capabilities/media_vision_review_capability.py): a data: URI for the one
    # candidate image being reviewed, plus a short text summary of the story it would accompany.
    # Both always None in every live production path - capabilities.executor.CapabilityExecutor.
    # _build_context() never populates either field, structurally preventing any automatic/
    # scheduled call from ever reaching the real vision capability (media_vision_review_mode has
    # no "enforce" value at all - see that capability's own module docstring). Only
    # scripts/phase19_m13_vision_review_manual.py (a manually-invoked, never-auto-run harness,
    # mirrors scripts/phase19_m3_editorial_plan_comparison.py's own established pattern)
    # constructs a CapabilityContext with these populated.
    media_review_image_data_uri: str | None = None
    media_review_story_summary: str | None = None
    # Phase 19 overnight A/B/C validation seam: bounded, deterministic text serializations of an
    # already-persisted EditorialPlan / Story Timeline - never populated in any live production
    # path (capabilities.executor.CapabilityExecutor._build_context() never sets either field;
    # only the manual comparison harness does). CopywritingCapability only ever reads these when
    # prompt.version == "6" (prompts/copywriting/v6.yaml) - both v4 and the existing, frozen v5
    # ignore them completely regardless of whether a caller supplies them, by construction (see
    # capabilities/copywriting_capability.py::_build_request()). None means "no plan"/"no prior
    # coverage found" - never fabricated.
    editorial_plan_context: str | None = None
    prior_coverage_context: str | None = None
    # Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md): a bounded, cleaned excerpt
    # of the already-acquired full article text (services/article_acquisition.py +
    # services/article_cleaning.py, already running for real under article_acquisition_mode=shadow),
    # for Copywriting's own quote-sourcing use ONLY - never a general fact source. Deliberately
    # separate from article_evidence_text above: that field is Research's own enforce-only signal
    # (article_acquisition_mode=="enforce" required) and this phase does not touch it or Research's
    # behavior at all. This field is populated whenever article_acquisition_mode != "off" (shadow
    # included) AND a FULL_TEXT/PARTIAL_TEXT acquisition exists - None otherwise, in which case
    # Copywriting falls back to its own pre-23.1P news_event.content excerpt unchanged.
    quote_source_text: str | None = None
    # TELEGRAPH Checkpoint 3 (services/telegraph_research_context.py): a bounded, deterministic
    # text rendering of an ArticleResearchBundle - present ONLY for the "deep_research" step of a
    # TELEGRAPH_RESEARCH workflow (capabilities/executor.py's own workflow_name check), never for
    # a NEWS_ANALYSIS/CONTENT_GENERATION/MEME_GENERATION "research" step, where this stays None
    # and ResearchCapability's existing news_event-based behavior is completely byte-identical to
    # before this checkpoint. capabilities/research_capability.py's own docstring documents the
    # exact branch this field drives.
    telegraph_research_bundle_text: str | None = None
    # TELEGRAPH Checkpoint 5 (capabilities/article_generation_capability.py): the prior,
    # already-COMPLETED TELEGRAPH_RESEARCH task's own "deep_research" step structured output
    # (prompts/research/v3.yaml's schema) - present ONLY for the "generate_article" step of a
    # TELEGRAPH_ARTICLE workflow (capabilities/executor.py's own workflow_name check). Never a
    # re-run of Research - this is a read of an already-persisted prior result.
    telegraph_deep_research_output: dict[str, Any] | None = None
    # TELEGRAPH Checkpoint 5: a bounded, deterministic text summary of the Visual Research bundle
    # (services/telegraph_visual_research.py) - informational only. ArticleGenerationCapability's
    # own prompt explicitly instructs the model never to describe or embed these images as
    # article text; this field exists so the model at least knows visual coverage exists, not so
    # it writes about the images.
    telegraph_visual_bundle_summary: str | None = None
    # TELEGRAPH editorial channel split (capabilities/article_generation_capability.py): the
    # proposal's own `schemas.editorial.EditorialChannel` value ("ninja_ai"/"ninja_pulse"),
    # classified once at shortlist-creation time (services/editorial_channel_classifier.py) and
    # threaded in read-only by capabilities/executor.py for the "generate_article" step only -
    # never re-classified here, never influences any other step/workflow. A plain `str` (the
    # enum's own `.value`), not the enum type itself, matching every other TELEGRAPH field on
    # this schema's own "no ORM/domain object crosses into a Capability" convention.
    telegraph_editorial_channel: str | None = None


class RuntimeContext(BaseModel):
    """Metadata owned by CapabilityExecutor/WorkflowRunner - never set by the capability itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    event_id: UUID
    capability_name: str
    priority: TaskPriority
    attempt: int = Field(ge=1)
    iteration_count: int = Field(ge=0)


class ExecutionContext(BaseModel):
    """Advisory Gateway-routing hints. LLMGateway makes the final model/provider choice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preferred_model: str | None = None
    preferred_provider: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    # API cost optimization: capability-specific, set centrally by
    # capabilities/executor.py::_build_context() (docs/api_cost_optimization_report.md).
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None


class CapabilityContext(BaseModel):
    """The complete, immutable, read-only input a Capability.execute() call receives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    business: BusinessContext
    runtime: RuntimeContext
    execution: ExecutionContext


class CapabilityUsage(BaseModel):
    """Token or unit cost of one AI interaction. Fields are optional, not
    zero-defaulted, so a non-token-billed call (e.g. a flat-rate search API)
    is representable without a hack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    units: int | None = Field(default=None, ge=0)
    unit_type: str | None = None
    # API cost optimization (docs/api_cost_optimization_report.md §8): populated only when the
    # real provider response reports them (openai_adapter.py's own translation) - never
    # invented. `cached_input_tokens` is a subset of `input_tokens`, not additional to it.
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class CapabilityCall(BaseModel):
    """Everything required to reconstruct one AI interaction that occurred
    while producing a CapabilityResult. One CapabilityCall MUST correspond to
    exactly one LLMGateway method invocation - never a batch of several."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: UUID
    sequence: int = Field(ge=0)
    gateway_method: Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]
    status: Literal["SUCCESS", "FAILED"]

    model_used: str | None
    provider: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None

    usage: CapabilityUsage

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    error: str | None = None


class CapabilityResult(BaseModel):
    """The complete, immutable output of one Capability.execute() call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["SUCCESS", "FAILED"]
    structured_output: dict[str, Any] | None
    confidence: int | None = Field(default=None, ge=0, le=100)

    calls: list[CapabilityCall] = Field(default_factory=list)

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    metadata: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    next_context: dict[str, Any] | None = None
