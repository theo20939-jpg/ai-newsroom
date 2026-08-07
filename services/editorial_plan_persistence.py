"""Phase 19 M3: the sole place that constructs/persists a ContentDraftEditorialPlan row.

Exists specifically so capabilities/executor.py never imports database.models.
content_draft_editorial_plan directly - tests/test_content_draft_service.py::
test_capabilities_never_import_content_draft() mechanically enforces that nothing under
capabilities/ imports a "content_draft"-named module (Contract §7: Capabilities/their
orchestration layer MUST NOT create, update, or hold any reference to a ContentDraft row).
capabilities/executor.py calls persist_shadow_plan() below instead - the exact same delegation
shape it already uses for services.evidence_package.build_evidence_package().

Always runs the plan through services.editorial_planning_safety.evaluate_plan_safety() before
persisting - the persisted safety_passed/safety_failed_checks columns must reflect a real
evaluation, never an optimistic default, even though the deterministic scaffold never fabricates
by construction (a future real, LLM-backed plan reusing this same persistence path must not
silently inherit an always-True safety_passed value).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_editorial_plan import ContentDraftEditorialPlan
from services.editorial_planning_safety import evaluate_plan_safety


async def persist_shadow_plan(
    session: AsyncSession,
    *,
    event_id: UUID,
    plan: dict,
    evidence_text: str = "",
    quote_candidates: list[str] | None = None,
    selected_editorial_text_hash: str | None = None,
) -> None:
    """Adds one ContentDraftEditorialPlan row to `session` (does not commit - the caller's own
    SAVEPOINT/commit discipline governs that, exactly as every other Phase 19 write does).

    `evidence_text`/`quote_candidates` default to empty when no EvidencePackage was available
    (e.g. article_acquisition_mode == "off") - evaluate_plan_safety()'s own grounding check is
    already defined to pass trivially when there is nothing to ground against, so this degrades
    safely rather than failing every shadow row for an unrelated, independently-gated feature."""
    report = evaluate_plan_safety(plan, evidence_text=evidence_text, quote_candidates=quote_candidates)
    row = ContentDraftEditorialPlan(
        event_id=event_id, plan=plan, is_deterministic_scaffold=True,
        safety_passed=report.passed, safety_failed_checks=report.failed_checks or None,
        selected_editorial_text_hash=selected_editorial_text_hash,
    )
    session.add(row)
