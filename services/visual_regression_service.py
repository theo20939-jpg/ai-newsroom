"""VISUAL-DESIGN-AUTONOMY-1, spec §40-42/§75: VisualRegressionService - runs a CANDIDATE brief
against a bounded set of real, hand-authored stress cases (VisualRegressionCase) before it may ever
be promoted, comparing outcomes against the current baseline (ACTIVE/FROZEN) brief.

CRITICAL (spec §40): this development branch has no historical incident asset library to draw real
past failures from (forensic finding - see this phase's final report) - cases describe honest
STRESS CONDITIONS (busy photo, dark photo, screenshot, DATA number-heavy, etc.), never a fabricated
"real historical example".

CRITICAL (spec §41/§42): the actual Art Director evaluation per case is an INJECTED async callable
(mirrors services/visual_design_loop.py's own `art_director_fn` injection) - this module's own job
is the real, tested comparison/promotion-policy logic, never a production vision call itself."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_regression import VisualRegressionCase, VisualRegressionOutcome, VisualRegressionRun

RegressionArtDirectorFn = Callable[[VisualRegressionCase, UUID], Awaitable[tuple[VisualRegressionOutcome, list[str], float | None]]]

_OUTCOME_SEVERITY = {
    VisualRegressionOutcome.PASS: 0, VisualRegressionOutcome.PASS_WITH_NOTES: 1,
    VisualRegressionOutcome.REWORK: 2, VisualRegressionOutcome.BLOCK: 3,
}


@dataclass(frozen=True)
class RegressionValidationResult:
    candidate_brief_version_id: UUID
    baseline_brief_version_id: UUID | None
    runs: list[VisualRegressionRun] = field(default_factory=list)
    total_cost_known: bool = True
    total_cost: float | None = 0.0

    @property
    def candidate_outcome_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for run in self.runs:
            counts[run.candidate_outcome.value] = counts.get(run.candidate_outcome.value, 0) + 1
        return counts

    @property
    def baseline_outcome_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for run in self.runs:
            if run.baseline_outcome is not None:
                counts[run.baseline_outcome.value] = counts.get(run.baseline_outcome.value, 0) + 1
        return counts


async def active_cases(session: AsyncSession, scope: str) -> list[VisualRegressionCase]:
    stmt = select(VisualRegressionCase).where(VisualRegressionCase.scope == scope, VisualRegressionCase.active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def run_regression_validation(
    session: AsyncSession, *, candidate_brief_version_id: UUID, baseline_brief_version_id: UUID | None,
    cases: list[VisualRegressionCase], art_director_fn: RegressionArtDirectorFn,
) -> RegressionValidationResult:
    runs: list[VisualRegressionRun] = []
    total_cost = 0.0
    cost_known = True

    for case in cases:
        candidate_outcome, candidate_issues, candidate_cost = await art_director_fn(case, candidate_brief_version_id)
        baseline_outcome: VisualRegressionOutcome | None = None
        baseline_cost: float | None = 0.0
        if baseline_brief_version_id is not None:
            baseline_outcome, _baseline_issues, baseline_cost = await art_director_fn(case, baseline_brief_version_id)

        if candidate_cost is None or (baseline_brief_version_id is not None and baseline_cost is None):
            cost_known = False
        else:
            total_cost += (candidate_cost or 0.0) + (baseline_cost or 0.0)

        run = VisualRegressionRun(
            candidate_brief_version_id=candidate_brief_version_id, baseline_brief_version_id=baseline_brief_version_id,
            case_id=case.id, candidate_outcome=candidate_outcome, baseline_outcome=baseline_outcome,
            issue_codes=candidate_issues, cost=candidate_cost,
        )
        session.add(run)
        runs.append(run)

    await session.commit()
    for run in runs:
        await session.refresh(run)

    return RegressionValidationResult(
        candidate_brief_version_id=candidate_brief_version_id, baseline_brief_version_id=baseline_brief_version_id,
        runs=runs, total_cost_known=cost_known, total_cost=(total_cost if cost_known else None),
    )


@dataclass(frozen=True)
class PromotionPolicyResult:
    may_promote: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_promotion_policy(
    result: RegressionValidationResult, *, target_issue_code: str | None = None, max_validation_cost: float | None = None,
) -> PromotionPolicyResult:
    """Spec §42: never promotes merely because it fixed one incident - every listed condition
    must hold. `target_issue_code` (the issue REPEATED_PATTERN evidence identified) must actually
    improve; BLOCK count must not increase; REWORK rate must not materially worsen (never more
    than a fixed absolute tolerance, so a single-case regression set does not flip on noise)."""
    reasons: list[str] = []

    if result.total_cost_known is False:
        return PromotionPolicyResult(may_promote=False, reasons=["validation cost unknown - fail-safe, never promote on an unknown budget"])
    if max_validation_cost is not None and (result.total_cost or 0.0) > max_validation_cost:
        return PromotionPolicyResult(may_promote=False, reasons=[f"validation cost ${result.total_cost:.2f} exceeds limit ${max_validation_cost:.2f}"])

    candidate_blocks = result.candidate_outcome_counts.get("block", 0)
    baseline_blocks = result.baseline_outcome_counts.get("block", 0)
    if candidate_blocks > baseline_blocks:
        reasons.append(f"BLOCK count increased ({baseline_blocks} -> {candidate_blocks})")

    total = len(result.runs) or 1
    candidate_rework_rate = result.candidate_outcome_counts.get("rework", 0) / total
    baseline_rework_rate = result.baseline_outcome_counts.get("rework", 0) / total if result.baseline_outcome_counts else candidate_rework_rate
    if candidate_rework_rate > baseline_rework_rate + 0.10:
        reasons.append(f"REWORK rate worsened materially ({baseline_rework_rate:.0%} -> {candidate_rework_rate:.0%})")

    if target_issue_code is not None:
        target_still_present = any(target_issue_code in (run.issue_codes or []) for run in result.runs if run.candidate_outcome != VisualRegressionOutcome.PASS)
        if target_still_present:
            reasons.append(f"target failure {target_issue_code!r} still reproduces against the candidate")

    return PromotionPolicyResult(may_promote=not reasons, reasons=reasons or ["all promotion conditions satisfied"])
