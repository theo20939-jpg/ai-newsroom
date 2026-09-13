"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S6): typed internal contracts for the shared editorial
production pipeline (Story/Trend -> EditorialBrief -> EvidencePack -> StructuredContent ->
VisualIntent -> MediaResearch -> MediaSelection -> CompositionPlan -> PlatformRender -> QualityGate
-> DeliveryPackage -> Editor/Publication Gate -> Delivery -> Recovery).

Reuse discipline (phase brief S0/S3: "consolidation, not a from-scratch rewrite"): where a real,
tested contract already exists elsewhere in this codebase and already means exactly what this
module needs, it is imported and re-exported here, never duplicated:

- `MediaIntent` (schemas/media_intent.py, CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1) is this
  pipeline's `VisualIntent`/`MediaIntent` (S11) - already platform-neutral, already has
  `primary_entity`/`must_show`/`must_not_imply`/`orientation_preference` etc.
- `ResolvedMediaCandidate` (schemas/media_subject_match.py) is this pipeline's `MediaCandidate`
  (S6/S12) - already carries `MediaProvenance` (S13) and `SubjectMatchValidation` (S12's
  EXACT_SUBJECT/STRONG_CONTEXT/GENERIC_CONTEXT/MISMATCH).
- `MediaSelectionResult` is this pipeline's `MediaSelection` (S6) - already reports
  `exact_subject_media_not_found` truthfully (S16's own literal requirement).
- `DataCandidate`/`QuoteCandidate` (services/presentation_director.py) are reused as the DATA/QUOTE
  evidence-binding primitives `StructuredDataContent`/`StructuredQuoteContent` build on, not
  replaced - the fix this phase makes (S9) is to how a `DataCandidate`'s `label` is constructed
  (never a mangled prose remainder), not to invent a second, competing DATA contract.

Everything below this docstring is genuinely new: `EvidenceClaim`/`EvidencePack` (S7),
`StructuredNewsContent`/`StructuredBreakingContent`/`StructuredDataContent`/
`StructuredQuoteContent` (S8), `CarouselPlan`/`SlidePlan` (S15), `CompositionPlan` (S17),
`QualityGateResult` (S21), `DeliveryPackage` (S6), `RecoveryJob`/`RecoveryResult` (S23).

Dataclass, not Pydantic, for internal-only contracts (matching `services/presentation_director.py`'s
own `PresentationDecision`/`DataCandidate`/`QuoteCandidate` convention for in-process types that
never cross a network/serialization boundary) - Pydantic is used only where the existing, reused
contracts already use it (MediaIntent, ResolvedMediaCandidate, MediaSelectionResult). No new DB
migration is introduced for any of these (phase brief S6: "avoid immediate DB migration merely for
in-process contracts") - `RecoveryJob` documents its own migration path (S23) without applying one.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

# Re-exported, not duplicated - see module docstring.
from schemas.media_intent import (
    DesiredVisualType,
    FreshnessRequirement,
    MediaIntent,
    MediaSubjectType,
    OrientationPreference,
)
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaSelectionResult,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.presentation_director import DataCandidate, QuoteCandidate

__all__ = [
    # Re-exported existing contracts
    "MediaIntent", "MediaSubjectType", "DesiredVisualType", "OrientationPreference",
    "FreshnessRequirement", "ResolvedMediaCandidate", "MediaProvenance", "DiscoveryTier",
    "MediaUsageClassification", "SubjectMatchValidation", "SubjectMatchClassification",
    "MediaSelectionResult", "DataCandidate", "QuoteCandidate",
    # New contracts
    "VisualIntent", "MediaCandidate", "MediaSelection",
    "EvidenceClaim", "EvidencePack",
    "PresentationFormat", "StructuredNewsContent", "StructuredBreakingContent",
    "StructuredDataContent", "StructuredQuoteContent", "StructuredContent",
    "SlidePlan", "CarouselPlan",
    "MediaAssetResolutionMethod", "SelectedMediaAsset", "MediaResolutionFailure",
    "DataCompositionStrategy", "CompositionPlan",
    "QualityCheckName", "QualityCheckResult", "QualityGateVerdict", "QualityGateResult",
    "Platform", "DeliveryOutcome", "DeliveryPackage",
    "RecoveryReasonCode", "RecoveryState", "RecoveryJob", "RecoveryResult",
    "OrchestratorVerdict",
]

# `VisualIntent`/`MediaCandidate`/`MediaSelection` are the phase brief's own names (S6/S11/S12) for
# exactly `MediaIntent`/`ResolvedMediaCandidate`/`MediaSelectionResult` above - aliased, not
# redefined, so call sites may use whichever name reads better without two competing types existing.
VisualIntent = MediaIntent
MediaCandidate = ResolvedMediaCandidate
MediaSelection = MediaSelectionResult


# ---------------------------------------------------------------------------
# S7: EvidencePack - the canonical factual input to content planning. Every meaningful claim a
# StructuredContent field states must trace to one of these, never to a fresh reading of raw prose.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceClaim:
    """One atomic, independently-checkable factual statement. `raw_fact_text` is the exact
    already-verified Research fact string it came from (this codebase's existing `research_facts`
    list, produced by the Research capability - never re-derived from the final generated prose,
    per S7's own explicit "do not parse the final generated Russian prose later to rediscover
    facts" instruction). `derivation` is set only for a computed value (e.g. a unit conversion or
    a percentage delta) and always names the operation and its inputs verbatim - never silently
    blank when a value was actually computed."""

    claim_id: str
    text: str
    source_url: str | None
    raw_fact_text: str
    derivation: str | None = None


@dataclass(frozen=True)
class EvidencePack:
    """The full evidence surface available for one NewsEvent/Story at planning time. `claims` is
    keyed by `claim_id` implicitly (list order is not semantic) - callers needing a specific claim
    look it up by id via `claim_by_id`. Never constructed with fabricated claims: every entry's
    `raw_fact_text` must be traceable to a real `research_facts` string or the NewsEvent/Story row
    itself (S7's own "source URL / NewsEvent-Story evidence / source fact" requirement)."""

    news_event_id: UUID
    story_id: UUID | None
    claims: tuple[EvidenceClaim, ...]
    source_url: str | None
    research_facts: tuple[str, ...]

    def claim_by_id(self, claim_id: str) -> EvidenceClaim | None:
        return next((c for c in self.claims if c.claim_id == claim_id), None)


# ---------------------------------------------------------------------------
# S8: structured content - produced BEFORE rendering, never reconstructed from final prose by a
# renderer. `PresentationFormat` mirrors the existing string constants in
# services/presentation_director.py (PRESENTATION_NEWS/BREAKING/DATA/QUOTE) as a real enum for the
# new pipeline's own internal use - conversion helpers exist rather than a breaking rename of the
# existing constants (S3: consolidation, not a rewrite of code that already works).
# ---------------------------------------------------------------------------


class PresentationFormat(str, enum.Enum):
    NEWS = "NEWS"
    BREAKING = "BREAKING"
    DATA = "DATA"
    QUOTE = "QUOTE"


@dataclass(frozen=True)
class StructuredNewsContent:
    headline: str
    body: str
    ending: str | None
    evidence_claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class StructuredBreakingContent:
    headline: str
    body: str
    urgency_reason: str
    """Why this qualifies as BREAKING (S8: 'appropriate urgency/context fields') - always a real,
    evidence-traceable reason, never a generic "this is breaking" placeholder."""
    context: str | None
    evidence_claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class StructuredDataContent:
    """The S9/S8 fix target. Every field is either directly lifted from one `EvidenceClaim`
    (`source_claim_id` always set) or explicitly derived (`metric_label`/`subject` may be
    deterministically constructed from the title/claim text - never a stripped remainder of the
    original sentence, which was the exact "начинается с юаней" defect class this replaces).
    `metric_value`/`metric_unit` are ALWAYS a clean, complete pair - never independently truncated
    from each other."""

    metric_value: str
    metric_unit: str
    metric_label: str
    subject: str
    context_sentence: str
    comparison: str | None
    delta: str | None
    delta_context: str | None
    series: tuple[float, ...]
    source_claim_id: str
    source_fact: str


@dataclass(frozen=True)
class StructuredQuoteContent:
    quote: str
    speaker: str | None
    """Optional (S8: "role if actually supported") - a real quote with no attributed speaker is
    valid; a renderer must never fabricate one."""
    role: str | None
    context: str | None
    source_claim_id: str


StructuredContent = StructuredNewsContent | StructuredBreakingContent | StructuredDataContent | StructuredQuoteContent


# ---------------------------------------------------------------------------
# S15: Instagram carousel planning - trend thesis -> story arc -> per-slide role/VisualIntent.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlidePlan:
    slide_index: int
    role: str
    """e.g. "hook", "evidence", "comparison", "detail", "cta" - never a bare index; always a real
    editorial role a human can review against the story arc."""
    claim_or_evidence: str
    visual_intent: MediaIntent
    layout_requirement: str


@dataclass(frozen=True)
class CarouselPlan:
    trend_thesis: str
    story_arc: str
    slides: tuple[SlidePlan, ...]


# ---------------------------------------------------------------------------
# S9/S17: composition - DATA's own explicit precedence (real series -> real source image ->
# typographic; never a fabricated graph), and the general CompositionPlan the renderer consumes
# and does ONLY layout/typography/crop/brand treatment/drawing against (S17 - no research, no fact
# extraction, no story selection, no publication decision, no truthfulness policy in the renderer).
# ---------------------------------------------------------------------------


class DataCompositionStrategy(str, enum.Enum):
    DATA_WITH_GRAPH = "data_with_graph"
    DATA_WITH_SOURCE_IMAGE = "data_with_source_image"
    DATA_TYPOGRAPHIC = "data_typographic"


# ---------------------------------------------------------------------------
# RUNTIME-CLOSURE-1 (§5/§6/§7): the ONE authoritative final-media-asset contract. Every stage from
# render onward (render, QA, transport) receives and inspects THIS object - never a candidate/bytes
# captured independently before `MediaResearchService` finished (§3.1's "structurally impossible"
# same-asset invariant). Built exactly once, by `services.editorial_pipeline.media_asset_resolver.
# resolve_selected_media_asset()`, from exactly the `ResolvedMediaCandidate` that
# `MediaSelectionResult.selected` names - never a different candidate.
# ---------------------------------------------------------------------------


class MediaAssetResolutionMethod(str, enum.Enum):
    TELEGRAM_FILE_ID = "telegram_file_id"  # a valid, reusable, already-cached Telegram file_id
    LOCAL_STORAGE_BYTES = "local_storage_bytes"  # freshly-read bytes from this app's own storage
    BOUNDED_DOWNLOAD = "bounded_download"  # a bounded, policy-checked download from the exact
    # selected candidate's own asset_url (Tier 2-5 web-discovered candidates only)
    NONE_TEXT_APPROPRIATE = "none_text_appropriate"  # no candidate was selected AND the format
    # legitimately does not require one (DATA_TYPOGRAPHIC) - never used for a visual-required format


@dataclass(frozen=True)
class SelectedMediaAsset:
    """The one object representing the authoritative final media asset, carried unchanged from
    resolution through render, QA, and transport (§5/§19's "ONE OBJECT" requirement).
    `candidate_id` is always `MediaSelectionResult.selected.candidate_id` when a candidate was
    selected - the identity every downstream stage's own diagnostic/invariant check compares
    against (`services.editorial_pipeline.telegram_integration`'s pre-transport assertion,
    `tests/test_unified_pipeline_same_asset_invariant.py`)."""

    candidate_id: str | None
    resolution_method: MediaAssetResolutionMethod
    source_url: str | None
    origin_url: str | None
    discovery_tier: DiscoveryTier | None
    usage_classification: MediaUsageClassification | None
    subject_match: SubjectMatchClassification | None
    subject_confidence: str | None
    telegram_file_id: str | None = None
    resolved_bytes: bytes | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    sha256: str | None = None

    @property
    def photo_input_ready(self) -> bool:
        """True exactly when this asset carries something a Telegram send call can use directly
        (a cached file_id or real bytes) - `False` for `NONE_TEXT_APPROPRIATE` and for a resolution
        that genuinely failed (see `MediaResolutionOutcome` below, which is returned instead of a
        `SelectedMediaAsset` in that case - this property exists for defensive/diagnostic use, the
        resolver itself never returns a "ready" asset with neither field set)."""
        return self.telegram_file_id is not None or self.resolved_bytes is not None


class MediaResolutionFailure:
    """RUNTIME-CLOSURE-1 (§7/§17): the typed sentinel a `RenderCallable` returns instead of `None`
    when a real candidate WAS selected but its exact bytes/file_id could not be resolved -
    distinguishable from `None` (generic `RENDER_FAILED`: a rendering/branding exception on
    otherwise-resolved bytes) and from a legitimate `(None, html)` text-appropriate composition.
    The orchestrator maps this specific sentinel to `RecoveryReasonCode.MEDIA_RESOLUTION_FAILED`
    (§18: 'never ordinary text delivery' for a visual-required format whose selected asset could
    not actually be resolved)."""

    __slots__ = ("candidate_id", "detail")

    def __init__(self, *, candidate_id: str | None, detail: str) -> None:
        self.candidate_id = candidate_id
        self.detail = detail


@dataclass(frozen=True)
class CompositionPlan:
    presentation_format: PresentationFormat
    data_strategy: DataCompositionStrategy | None
    """Set only when presentation_format is DATA - S9's own explicit precedence decision, made
    HERE (composition), never re-decided inside the renderer."""
    photo_input: object | None
    """Whatever the platform's own renderer input shape is (a cached Telegram file_id string, a
    BufferedInputFile, an Instagram-native asset reference) - intentionally untyped here since this
    contract is platform-neutral (S17); the platform adapter narrows it."""
    media_group_items: tuple[object, ...]
    caption_position: Literal["ABOVE", "BELOW"]
    branding_strength: str


# ---------------------------------------------------------------------------
# S21: the central quality gate. `checks` always lists every check that actually ran (never a
# partial/short-circuited list presented as complete) - S21's own explicit check names.
# ---------------------------------------------------------------------------


class QualityCheckName(str, enum.Enum):
    STRUCTURED_CONTENT_PRESENT = "STRUCTURED_CONTENT_PRESENT"
    """RUNTIME-CLOSURE-1 (§20): renamed from the old `FACT_SUPPORT` - that name claimed an
    independent fact-support/traceability verification this check never actually performed (it
    only ever checked "is `content` not None"). `CLAIM_TRACEABILITY` (below) is the check that
    actually verifies traceability to an `EvidenceClaim`; this one is honestly named for what it
    checks. No new checker was added - semantic honesty, not a second expensive validator (§20's
    own explicit instruction)."""
    CLAIM_TRACEABILITY = "CLAIM_TRACEABILITY"
    LANGUAGE_QUALITY = "LANGUAGE_QUALITY"
    VISUAL_TRUTHFULNESS = "VISUAL_TRUTHFULNESS"
    MEDIA_PROVENANCE = "MEDIA_PROVENANCE"
    FORMAT_REQUIREMENTS = "FORMAT_REQUIREMENTS"
    PLATFORM_BUDGET = "PLATFORM_BUDGET"
    ART_VALIDATION = "ART_VALIDATION"


class QualityGateVerdict(str, enum.Enum):
    READY = "READY"
    HOLD = "HOLD"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class QualityCheckResult:
    name: QualityCheckName
    passed: bool
    reason: str
    """Always set, even when passed=True (a real, specific "why this passed" - S32's own
    observability spirit extended to gate checks, never a bare boolean with no explanation)."""


@dataclass(frozen=True)
class QualityGateResult:
    verdict: QualityGateVerdict
    checks: tuple[QualityCheckResult, ...]

    @property
    def failed_checks(self) -> tuple[QualityCheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)


# ---------------------------------------------------------------------------
# S6/S20/S24: the platform-neutral delivery package + the deliberately dumb transport result.
# ---------------------------------------------------------------------------


class Platform(str, enum.Enum):
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"


class DeliveryOutcome(str, enum.Enum):
    """S24's own exact three states - transport may report these, never decide editorial
    fallbacks on its own."""

    SENT = "SENT"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class DeliveryPackage:
    platform: Platform
    presentation_format: PresentationFormat
    composition_plan: CompositionPlan
    quality_gate_result: QualityGateResult
    caption_or_copy: str
    """Final, already-budget-checked text for the platform - S19: caption budget is solved before
    this package exists, never discovered as a transport-time surprise."""


# ---------------------------------------------------------------------------
# S23: recovery as a first-class workflow. `content_drafts.status = "hold_for_visual"` (this
# session's own prior TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 phase) remains the real,
# currently-deployed persistence mechanism for Telegram - `RecoveryJob` is additive, in-process
# structure around it (S23: "if an in-process compatibility bridge is safer initially: document
# migration path" - done below, no migration applied in this phase).
# ---------------------------------------------------------------------------


class RecoveryReasonCode(str, enum.Enum):
    NO_SUITABLE_MEDIA = "NO_SUITABLE_MEDIA"
    MEDIA_RESEARCH_TIMEOUT = "MEDIA_RESEARCH_TIMEOUT"
    MEDIA_SEND_FAILED = "MEDIA_SEND_FAILED"
    AMBIGUOUS_TRANSPORT_RESULT = "AMBIGUOUS_TRANSPORT_RESULT"
    CAPTION_BUDGET_FAILED = "CAPTION_BUDGET_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"
    MEDIA_RESOLUTION_FAILED = "MEDIA_RESOLUTION_FAILED"
    """RUNTIME-CLOSURE-1 (§7/§17): MediaResearch selected a real candidate (`media_selection.
    selected is not None`), but the exact bytes/file_id that specific candidate needs could not be
    resolved (local storage missing/unreadable AND no valid cached Telegram file_id AND no bounded
    download succeeded) - Founder audit Case A/B. Distinct from the generic `RENDER_FAILED` (a
    rendering/branding exception) so this specific, previously-invisible failure mode is
    observable on its own. Bounded-retryable (a storage/network hiccup may be transient), never a
    silent text-only completion - see `services.editorial_pipeline.media_asset_resolver`."""


class RecoveryState(str, enum.Enum):
    OPEN = "OPEN"
    RETRYING = "RETRYING"
    RECOVERED = "RECOVERED"
    TERMINAL = "TERMINAL"
    """Bounded - S23's own "no infinite retries" requirement: a job reaches TERMINAL after
    `attempt_count >= max_attempts`, never retried again automatically."""


@dataclass(frozen=True)
class RecoveryJob:
    """A future dedicated `recovery_jobs` table would carry exactly these fields (migration path,
    not applied in this phase - see S23):

    ```sql
    CREATE TABLE recovery_jobs (
        id UUID PRIMARY KEY,
        content_draft_id UUID NOT NULL REFERENCES content_drafts(id),
        reason_code VARCHAR NOT NULL,
        failed_stage VARCHAR NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL,
        last_error TEXT,
        next_retry_at TIMESTAMPTZ,
        candidate_diagnostics JSONB,
        state VARCHAR NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    ```

    Until that migration is authored and applied (explicitly NOT in this phase), the in-process
    bridge is: this dataclass is constructed, logged (S32's own `recovery_created` diagnostic
    stage), and its terminal outcome is what actually persists - `content_drafts.status =
    "hold_for_visual"` for Telegram (unchanged, already in production), or the Instagram-shadow
    equivalent (never a real write while `instagram_publication_enabled=False`)."""

    content_draft_id: UUID
    reason_code: RecoveryReasonCode
    failed_stage: str
    attempt_count: int
    max_attempts: int
    last_error: str | None
    candidate_diagnostics: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_terminal(self) -> bool:
        return self.attempt_count >= self.max_attempts

    @property
    def state(self) -> RecoveryState:
        return RecoveryState.TERMINAL if self.is_terminal else RecoveryState.OPEN


@dataclass(frozen=True)
class RecoveryResult:
    job: RecoveryJob
    notice_sent: bool
    """Whether the best-effort editor-visible recovery notice reached its destination - the
    durable guarantee is `job`'s own persisted state, never this (this session's own prior phase's
    own proven invariant: `test_hold_survives_the_notice_send_itself_failing`)."""


# ---------------------------------------------------------------------------
# UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S5): the one explicit orchestrator result the
# Founder review demanded ("worker must not inspect low-level media/content fields and make new
# editorial decisions after receiving this result"). Four, and only four, outcomes:
#
#   READY - `delivery_package` is set; the worker's only remaining job is dumb transport.
#   HOLD  - a real, durable RecoveryJob (services.editorial_pipeline.recovery_service.RecoveryJob,
#           the DB-backed model) has reached a state that needs editor review right now (either
#           TERMINAL_HOLD - bounded retries exhausted - or a reason this phase's own policy never
#           retries automatically at all, e.g. AMBIGUOUS_TRANSPORT_RESULT, which must never be
#           blindly retried/resent). `recovery_job_id` names the durable row a human/future cycle
#           can inspect; never a fabricated id.
#   BLOCK - a quality/safety verdict that content itself must change to pass, never merely retried
#           unchanged (`QUALITY_GATE_FAILED` - the Quality Gate's own verdict is authoritative and
#           final here, never re-decided by the worker).
#   RETRY - a real, durable RecoveryJob exists and is still bounded-retryable (PENDING/RETRYING) -
#           `next_retry_at` says when a future cycle should attempt this draft again; the worker
#           does nothing else with it this cycle (never blindly re-attempts inline).
#
# This verdict is carried directly on the pre-existing `PipelineResult` (S25, still returned
# unchanged in shape by `run_editorial_production_pipeline()` for full backward compatibility with
# the shadow-mode call site and this phase's own pre-existing test suite, both of which never pass
# a durable session) via its new `verdict`/`persisted_recovery_job_id`/`next_retry_at` fields
# (services/editorial_pipeline/orchestrator.py) - deliberately not a second, separate result
# dataclass: this phase's own §9 principle ("do not keep decorative... values with no
# implementation") applies just as much to a competing, never-actually-returned result type as to
# an unused enum member.
# ---------------------------------------------------------------------------


class OrchestratorVerdict(str, enum.Enum):
    READY = "READY"
    HOLD = "HOLD"
    BLOCK = "BLOCK"
    RETRY = "RETRY"
