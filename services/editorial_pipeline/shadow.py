"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S25/S26/S27): the single, real, worker-reachable entry
point into the new pipeline, and the dual-run/shadow comparison harness.

`run_shadow_comparison()` is called from EXACTLY ONE place in `worker/content_cycle.py` (S25's own
"must have a clear single entrypoint"), guarded by `settings.unified_editorial_pipeline_enabled`
(default False everywhere - S26) and wrapped in a blanket exception boundary at the call site so a
bug in this brand-new, not-yet-production-proven code can NEVER affect the legacy path's own
already-proven behavior (S39: no production deploy in this phase - this function is never reachable
in any environment where the flag stays False, which is every environment this phase touches).

S27's own explicit constraints, enforced by construction here: this function NEVER sends a Telegram
message, NEVER writes to Instagram, and NEVER mutates any row - it only runs the new orchestrator
(with `unified_editorial_pipeline_shadow_mode` additionally gating whether it even attempts the
comparison logging below) and logs a structured comparison against whatever the legacy path decided
for the SAME event, for later analysis. `run` is the same `RenderCallable` shape the orchestrator
itself takes - the caller (worker/content_cycle.py) passes a small, self-contained closure that
reuses the caller's own already-computed `photo_input`/`html` instead of running the real V8
renderer a second time (S27: never a duplicate real render, not just never a duplicate send).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable
from uuid import UUID

from services.editorial_pipeline.contracts import EvidencePack, Platform, PresentationFormat
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.orchestrator import RenderCallable, run_editorial_production_pipeline

logger = logging.getLogger(__name__)

_FORMAT_BY_LEGACY_STRING = {
    "NEWS": PresentationFormat.NEWS, "BREAKING": PresentationFormat.BREAKING,
    "DATA": PresentationFormat.DATA, "QUOTE": PresentationFormat.QUOTE,
}


async def run_shadow_comparison(
    *, content_draft_id: UUID, news_event_id: UUID, story_id: UUID | None, source_url: str | None,
    title: str, main_body: str | None, research_facts: list[str] | None,
    legacy_presentation_type: str, legacy_had_visual: bool,
    render: RenderCallable,
) -> None:
    """Never raises (the call site does not need its own try/except as a result, though it keeps
    one anyway per defense-in-depth - S4-E). Logs exactly one `shadow_comparison` event comparing
    the new pipeline's own verdict/reason against what the legacy path actually did for the same
    event, never anything else observable from outside this function."""
    try:
        presentation_format = _FORMAT_BY_LEGACY_STRING.get(legacy_presentation_type, PresentationFormat.NEWS)
        evidence: EvidencePack = build_evidence_pack(
            news_event_id=news_event_id, story_id=story_id, source_url=source_url, research_facts=research_facts,
        )
        result = await run_editorial_production_pipeline(
            content_draft_id=content_draft_id, presentation_format=presentation_format, title=title,
            main_body=main_body, evidence=evidence, platform=Platform.TELEGRAM, render=render,
        )
        logger.info(
            "shadow_comparison",
            extra={
                "content_draft_id": str(content_draft_id),
                "legacy_presentation_type": legacy_presentation_type,
                "legacy_had_visual": legacy_had_visual,
                "new_pipeline_ready": result.is_ready,
                "new_pipeline_recovery_reason": result.recovery_job.reason_code.value if result.recovery_job else None,
                "agrees_with_legacy": result.is_ready == legacy_had_visual,
            },
        )
    except Exception as exc:  # noqa: BLE001 - S4-E/S27: a shadow-mode bug must never surface anywhere the legacy path can see it
        logger.warning("shadow_comparison_failed", extra={"content_draft_id": str(content_draft_id), "error": type(exc).__name__})


def build_passthrough_render(photo_input: object | None, html: str) -> Callable[..., Awaitable[tuple[object | None, str]]]:
    """A RenderCallable that does not render anything new - it hands back the legacy path's OWN
    already-computed `photo_input`/`html` verbatim (S27: "no duplicate Telegram sends... no
    production mutation merely to collect shadow output" - extended here to also mean no duplicate
    real rendering work, which this codebase's own renderers are not free to run twice)."""

    async def _render(composition_plan: object, structured_content: object, media_selection: object) -> tuple[object | None, str]:
        return photo_input, html

    return _render
