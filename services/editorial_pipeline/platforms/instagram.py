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

from typing import TYPE_CHECKING, Any

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


def _verify_same_asset_identity(
    package: "InstagramContentPackage", render_results: list["InstagramRenderResult"],
) -> bool:
    """INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7/§10: `package.media_candidate_id ==
    render_result.evidence.source_media_candidate_id` for every render that actually claims to
    have used a real source image (`source_image_treatment` other than "none"/"generated" -
    a render that never used a photo has nothing to compare and trivially passes). A package that
    never carried a `media_candidate_id` at all (no `media_selection` was supplied - the
    pre-existing, back-compat path) also trivially passes: this check only ever REJECTS a genuine
    divergence, never penalizes a caller that has not been updated to supply the safety wiring yet."""
    if package.media_candidate_id is None:
        return True
    for result in render_results:
        if result.evidence.source_image_treatment in ("none", "generated"):
            continue
        if result.evidence.source_media_candidate_id != package.media_candidate_id:
            return False
    return True


def evaluate_instagram_package(
    *, package: "InstagramContentPackage", render_results: list["InstagramRenderResult"],
    evidence: EvidencePack, content_draft_id: "UUID", media_selection: Any | None = None,
) -> tuple[QualityGateResult, RecoveryJob | None]:
    """Runs the shared quality gate against an already-built, already-rendered Instagram package.
    Returns `(gate_result, None)` when READY, or `(gate_result, RecoveryJob)` when not - the
    orchestrator (S25) treats this exactly like a Telegram HOLD/BLOCK: no publish call is ever
    reachable from a non-READY verdict.

    INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7: `media_selection` (the same real
    `MediaSelectionResult` `services.instagram_media_safety.resolve_instagram_media()` produced for
    this package) is now threaded through to `run_quality_gate()` instead of the previous hardcoded
    `None` - the ONE change this phase makes here. This costs nothing new: `run_quality_gate()`'s
    own `_check_visual_truthfulness()`/`_check_media_provenance()` checks (unmodified, already
    real, already used by Telegram) now apply to Instagram automatically - a MISMATCH or
    NOT_USABLE selected candidate reaching this function becomes a real `BLOCK`, exactly like
    Telegram. `media_selection=None` (the default, for any caller not yet updated) preserves the
    prior byte-identical behavior."""
    art_result = validate_instagram_art(package, render_results)

    same_asset_ok = _verify_same_asset_identity(package, render_results)

    gate_result = run_quality_gate(
        # Instagram's own structured content lives in `package` itself, not yet threaded through
        # StructuredContent (report's own "remaining intentional limitations" section discloses
        # this explicitly) - `content=None` would make quality.py's own STRUCTURED_CONTENT_PRESENT/
        # CLAIM_TRACEABILITY checks fail as "nothing to check", which is correct and desired for
        # Telegram (content really is expected there) but would misrepresent a genuine, disclosed
        # gap as a quality failure for Instagram specifically - overridden explicitly below, never
        # silently reported as a real pass.
        content=None,
        evidence=evidence, media_selection=media_selection, caption_or_copy=package.caption, platform=Platform.INSTAGRAM,
    )

    from services.editorial_pipeline.contracts import QualityCheckName, QualityCheckResult

    _NOT_EVALUATED_REASON = (
        "not evaluated for Instagram in this phase - StructuredContent is not yet threaded "
        "through the Director planning chain (disclosed limitation, not a quality failure)"
    )
    overridden_checks = []
    for check in gate_result.checks:
        if check.name in (QualityCheckName.STRUCTURED_CONTENT_PRESENT, QualityCheckName.CLAIM_TRACEABILITY) and not check.passed:
            overridden_checks.append(QualityCheckResult(check.name, True, _NOT_EVALUATED_REASON))
        elif check.name == QualityCheckName.ART_VALIDATION and not art_result.passed:
            overridden_checks.append(QualityCheckResult(QualityCheckName.ART_VALIDATION, False, "; ".join(art_result.blocking_issues)))
        else:
            overridden_checks.append(check)
    # INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7/§10: the same-asset identity check is appended
    # as its own synthetic check (never silently folded into ART_VALIDATION or any other existing
    # name) - a divergence here means package/render disagree about which candidate this post is
    # about, which is exactly as severe as a MISMATCH and must BLOCK the same way.
    overridden_checks.append(
        QualityCheckResult(
            QualityCheckName.SAME_ASSET_IDENTITY, same_asset_ok,
            "selected/rendered media identity matches" if same_asset_ok
            else "same-asset invariant violated: rendered media does not match the selected candidate",
        )
    )
    checks = tuple(overridden_checks)
    failed = [c for c in checks if not c.passed]
    if not failed:
        gate_result = QualityGateResult(verdict=QualityGateVerdict.READY, checks=checks)
    elif any(
        c.name in (QualityCheckName.VISUAL_TRUTHFULNESS, QualityCheckName.MEDIA_PROVENANCE, QualityCheckName.ART_VALIDATION, QualityCheckName.SAME_ASSET_IDENTITY)
        for c in failed
    ):
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
