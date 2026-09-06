"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §13-18: REAL Art Director
pixel inspection - moves beyond services/telegram_art_director.py's own structural-metadata-only
`evaluate_art_direction_shadow()` to an actual vision-model call over the real rendered bytes.

Architecture note (mirrors services/business_context_command_parser.py's own identical, already-
established precedent exactly): this repo's only path to the LLM Gateway is the full Capability +
CapabilityExecutor + WorkflowRunner + EditorialTask machinery, which is workflow/Story-bound. A
shadow Art Director evaluation has no EditorialTask of its own (spec §111: no publication-path
side effect), so forcing one into existence merely to satisfy the Capability contract would be a
disproportionate architecture graft. This module instead calls
`capabilities/gateway_call.py::call_generate()` directly - the SAME shared Gateway plumbing every
real Capability already uses (routing, `ContentPart(type="artifact_ref")` image translation,
`modalities=["text","image"]` vision-aware routing, response_mode="json_schema") - with a synthetic
`RuntimeContext`, exactly as capabilities/media_vision_review_capability.py's own real, already-
wired image-request construction already proves works end to end. This is reuse of the existing
vision architecture, never an ad-hoc external vision provider (spec §13's own explicit instruction).

SHADOW ONLY (spec §21: telegram_art_director_shadow_enabled defaults False) - `evaluate_art_
direction_vision()` itself never writes to any table; callers decide persistence (see
services/telegram_visual_failure_persistence.py for the real §19 write path)."""
from __future__ import annotations

import base64
import logging
from typing import Any
from uuid import uuid4

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.telegram_art_director import (
    ArtDirectorDecision,
    ArtDirectorIssueCode,
    ArtDirectorResult,
    PixelInputContract,
    evaluate_art_direction_shadow,
    renderer_reports_duplicate_branding,
    renderer_reports_safe_degradation,
)

logger = logging.getLogger(__name__)

VISION_PROMPT_NAME = "telegram_art_director_vision"
VISION_PROMPT_VERSION = "1"

_MIME_BY_FORMAT = {"JPEG": "image/jpeg", "JPG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ArtDirectorVisionError(Exception):
    """Wraps a `CapabilityError` from the underlying Gateway call - never raised past a caller
    that must fail soft (spec §27: "vision failure fails soft to HUMAN_REVIEW/safe outcome")."""


def _to_data_uri(rendered_bytes: bytes, *, image_format: str = "JPEG") -> str:
    mime = _MIME_BY_FORMAT.get(image_format.upper(), "image/jpeg")
    encoded = base64.b64encode(rendered_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _build_task_text(
    pixel_input: PixelInputContract, *, expected_facts: dict[str, Any] | None,
) -> str:
    safe_degradation = renderer_reports_safe_degradation(pixel_input.renderer_decision_metadata)
    duplicate_marks = renderer_reports_duplicate_branding(pixel_input.renderer_decision_metadata)
    lines = [
        f"presentation_type: {pixel_input.presentation_type}",
        f"renderer_version: {pixel_input.renderer_version or 'unknown'}",
        f"caption: {pixel_input.caption}",
        f"renderer_decision_metadata: {pixel_input.renderer_decision_metadata}",
        f"safe_no_overlay_degradation: {safe_degradation}",
        f"renderer_placed_duplicate_marks: {duplicate_marks}",
        f"media_source_metadata: {pixel_input.media_source_metadata}",
        f"expected_facts: {expected_facts or {}}",
    ]
    return "\n".join(lines)


def _parse_issue_code(raw: str) -> ArtDirectorIssueCode:
    try:
        return ArtDirectorIssueCode(raw)
    except ValueError:
        return ArtDirectorIssueCode.UNKNOWN_VISUAL_FAILURE


def _parse_decision(raw: str) -> ArtDirectorDecision:
    try:
        return ArtDirectorDecision(raw)
    except ValueError:
        return ArtDirectorDecision.PASS_WITH_NOTES


def _safe_fallback_result(reason: str) -> ArtDirectorResult:
    """Spec §27's own explicit "fails soft to HUMAN_REVIEW/safe outcome" - never a silent PASS
    (that would claim a verification that never happened) and never BLOCK/REWORK (that would act
    on a judgment that was never actually made)."""
    return ArtDirectorResult(
        decision=ArtDirectorDecision.PASS_WITH_NOTES, severity="none",
        issue_codes=[ArtDirectorIssueCode.UNKNOWN_VISUAL_FAILURE], action="HUMAN_REVIEW",
        instructions=reason, confidence=0.0,
    )


async def evaluate_art_direction_vision(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, pixel_input: PixelInputContract,
    expected_facts: dict[str, Any] | None = None, image_format: str = "JPEG",
) -> ArtDirectorResult:
    """Real vision inspection. Falls back to the deterministic structural checks (empty bytes,
    renderer-side duplicate branding) before ever spending a paid vision call - VISUAL-SINGLE-
    BRAND-MARK-1 §23's own "prevent structurally before image mutation, never burn image-
    generation budget for a renderer bug" instruction. Never fabricates a quality judgment when
    there is nothing to look at, and never asks a vision model to confirm what pipeline metadata
    already proves."""
    structural = evaluate_art_direction_shadow(pixel_input)
    if not pixel_input.rendered_bytes:
        return structural
    if renderer_reports_duplicate_branding(pixel_input.renderer_decision_metadata):
        return structural

    from capabilities.gateway_call import call_generate  # local import: avoids a capabilities<->services import cycle at module load time

    prompt = prompt_repository.resolve(VISION_PROMPT_NAME, VISION_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    task_text = _build_task_text(pixel_input, expected_facts=expected_facts)
    data_uri = _to_data_uri(pixel_input.rendered_bytes, image_format=image_format)

    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[
                ContentPart(type="text", text=task_text),
                ContentPart(type="artifact_ref", artifact_ref=data_uri, mime_type=_MIME_BY_FORMAT.get(image_format.upper(), "image/jpeg")),
            ]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
        modalities=["text", "image"],
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name="telegram_art_director_vision",
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=1)
    except Exception:
        logger.warning("telegram_art_director_vision call raised unexpectedly", exc_info=True)
        return _safe_fallback_result("Vision call raised an unexpected exception - human review recommended.")

    if outcome.error is not None:
        logger.info("telegram_art_director_vision failed: %s", outcome.error)
        return _safe_fallback_result(f"Vision call failed ({outcome.error}) - human review recommended.")

    output = (outcome.response.structured_output if outcome.response is not None else None) or {}
    if not output:
        return _safe_fallback_result("Vision call returned no structured output - human review recommended.")

    issues_raw = output.get("issues", [])
    issue_codes = [_parse_issue_code(issue.get("code", "")) for issue in issues_raw if isinstance(issue, dict)]

    return ArtDirectorResult(
        decision=_parse_decision(output.get("decision", "")),
        severity=output.get("severity", "none"),
        issue_codes=issue_codes,
        action=(issues_raw[0].get("recommended_action", "") if issues_raw and isinstance(issues_raw[0], dict) else ""),
        instructions="; ".join(
            issue.get("description", "") for issue in issues_raw if isinstance(issue, dict)
        ),
        confidence=float(output.get("overall_confidence", 0.0)),
    )
