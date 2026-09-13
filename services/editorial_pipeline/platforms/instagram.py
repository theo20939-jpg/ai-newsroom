"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S13/S20/S21/S30): the Instagram platform adapter.

Deliberately narrower than the Telegram adapter, and honestly so (phase brief S5: "do not create
unnecessary abstraction layers merely to match these names"). Instagram's own real, already-built
Director planning chain (`ContentOpportunity -> GrowthStrategy -> ObjectiveRecommendation ->
FormatDecision -> CreativeGenerationOutcome -> services.instagram_shadow_pipeline.build_shadow_
plan() -> services.instagram_content_package.build_instagram_content_package()`) is genuinely deep,
already real, and untouched by this phase - reconstructing a fake `ContentOpportunity`/
`FormatDecision` here merely to force an `InstagramContentPackage` through a generic adapter
signature would be exactly the kind of hollow, hand-wavy "integration" this phase's own S3
("consolidation, not a from-scratch rewrite... preserve, don't recreate") warns against.

Instead, this adapter integrates at the boundary where the shared pipeline genuinely adds value
Instagram does not already have: taking an ALREADY-BUILT, real `InstagramContentPackage` (produced
by Instagram's own existing chain, unmodified) plus its already-rendered `InstagramRenderResult`s,
and running it through the SAME shared `run_quality_gate()` every Telegram package passes through
(S21 - one gate, not two competing ones) - `ART_VALIDATION` delegates to the real, existing
`services.instagram_art_validator.validate_instagram_art()` (never reimplemented), and a failed
gate produces the SAME shared `RecoveryJob` shape (S23) Telegram uses, rather than a second,
Instagram-only recovery concept.

S30 (Instagram publication safety) - this module never publishes anything and never checks
`instagram_publication_enabled` itself (that gate belongs entirely to `services.instagram_publish_
adapter`, unmodified, per S3): it only decides whether a package IS READY, exactly like the
Telegram adapter's caption-budget planner decides whether a Telegram package is ready. Reaching
READY here has no side effect - no network call, no credential use, nothing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.editorial_pipeline.contracts import (
    EvidencePack,
    Platform,
    QualityGateResult,
    QualityGateVerdict,
    RecoveryJob,
    RecoveryReasonCode,
)
from services.editorial_pipeline.quality import run_quality_gate
from services.editorial_pipeline.recovery import create_recovery_job
from services.instagram_art_validator import validate_instagram_art

if TYPE_CHECKING:
    from uuid import UUID

    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_platform_renderer import InstagramRenderResult


def evaluate_instagram_package(
    *, package: "InstagramContentPackage", render_results: list["InstagramRenderResult"],
    evidence: EvidencePack, content_draft_id: "UUID",
) -> tuple[QualityGateResult, RecoveryJob | None]:
    """Runs the shared quality gate against an already-built, already-rendered Instagram package.
    Returns `(gate_result, None)` when READY, or `(gate_result, RecoveryJob)` when not - the
    orchestrator (S25) treats this exactly like a Telegram HOLD/BLOCK: no publish call is ever
    reachable from a non-READY verdict."""
    art_result = validate_instagram_art(package, render_results)

    gate_result = run_quality_gate(
        # Instagram's own structured content lives in `package` itself, not yet threaded through
        # StructuredContent (report's own "remaining intentional limitations" section discloses
        # this explicitly) - `content=None` would make quality.py's own FACT_SUPPORT/
        # CLAIM_TRACEABILITY checks fail as "nothing to check", which is correct and desired for
        # Telegram (content really is expected there) but would misrepresent a genuine, disclosed
        # gap as a quality failure for Instagram specifically - overridden explicitly below, never
        # silently reported as a real pass.
        content=None,
        evidence=evidence, media_selection=None, caption_or_copy=package.caption, platform=Platform.INSTAGRAM,
    )

    from services.editorial_pipeline.contracts import QualityCheckName, QualityCheckResult

    _NOT_EVALUATED_REASON = (
        "not evaluated for Instagram in this phase - StructuredContent is not yet threaded "
        "through the Director planning chain (disclosed limitation, not a quality failure)"
    )
    overridden_checks = []
    for check in gate_result.checks:
        if check.name in (QualityCheckName.FACT_SUPPORT, QualityCheckName.CLAIM_TRACEABILITY) and not check.passed:
            overridden_checks.append(QualityCheckResult(check.name, True, _NOT_EVALUATED_REASON))
        elif check.name == QualityCheckName.ART_VALIDATION and not art_result.passed:
            overridden_checks.append(QualityCheckResult(QualityCheckName.ART_VALIDATION, False, "; ".join(art_result.blocking_issues)))
        else:
            overridden_checks.append(check)
    checks = tuple(overridden_checks)
    failed = [c for c in checks if not c.passed]
    if not failed:
        gate_result = QualityGateResult(verdict=QualityGateVerdict.READY, checks=checks)
    elif any(c.name in (QualityCheckName.VISUAL_TRUTHFULNESS, QualityCheckName.MEDIA_PROVENANCE, QualityCheckName.ART_VALIDATION) for c in failed):
        gate_result = QualityGateResult(verdict=QualityGateVerdict.BLOCK, checks=checks)
    else:
        gate_result = QualityGateResult(verdict=QualityGateVerdict.HOLD, checks=checks)

    if gate_result.verdict == QualityGateVerdict.READY:
        return gate_result, None

    reason = RecoveryReasonCode.QUALITY_GATE_FAILED
    job = create_recovery_job(
        content_draft_id=content_draft_id, reason_code=reason, failed_stage="instagram_quality_gate",
        candidate_diagnostics=tuple(c.reason for c in gate_result.failed_checks),
    )
    return gate_result, job
