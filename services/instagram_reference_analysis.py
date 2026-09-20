"""INSTAGRAM-GROWTH-3, item 12: AI-assisted Reference Deconstruction. Same one-shot
`call_generate()` pattern as services/instagram_semantic_matching.py/
services/instagram_creative_director.py - no ad-hoc provider. The result is re-validated through
the ACCEPTED `services/instagram_reference_deconstruction.py::ReferenceDeconstruction` dataclass
(must_not_copy required non-empty) before being handed back - a model that omits it is rejected,
never silently defaulted."""
from __future__ import annotations

from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.instagram_reference_deconstruction import ReferenceDeconstruction

REFERENCE_ANALYSIS_PROMPT_NAME = "instagram_reference_analysis"
REFERENCE_ANALYSIS_PROMPT_VERSION = "1"


class ReferenceAnalysisUnavailableError(Exception):
    """Raised on any Gateway failure - no deterministic fallback exists for creative mechanic
    analysis, so failure is explicit, never fabricated placeholder content."""


async def analyze_reference_with_ai(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, reference_description: str,
) -> ReferenceDeconstruction:
    try:
        prompt = prompt_repository.resolve(REFERENCE_ANALYSIS_PROMPT_NAME, REFERENCE_ANALYSIS_PROMPT_VERSION)
    except Exception as exc:
        raise ReferenceAnalysisUnavailableError(f"prompt unavailable: {exc}") from exc

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=f"REFERENCE DESCRIPTION:\n{reference_description}")]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=REFERENCE_ANALYSIS_PROMPT_NAME,
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise ReferenceAnalysisUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise ReferenceAnalysisUnavailableError(str(outcome.error))

    response = outcome.response
    assert response is not None
    output = response.structured_output
    if output is None:
        raise ReferenceAnalysisUnavailableError("no structured output returned")

    try:
        return ReferenceDeconstruction(
            reference_description=reference_description,
            hook_mechanics=output.get("hook_mechanics", ""), pacing=output.get("pacing", ""),
            scene_structure=output.get("scene_structure", ""), narrative_progression=output.get("narrative_progression", ""),
            typography_behavior=output.get("typography_behavior", ""), visual_rhythm=output.get("visual_rhythm", ""),
            editing_rhythm=output.get("editing_rhythm", ""), cta_mechanics=output.get("cta_mechanics", ""),
            interaction_pattern=output.get("interaction_pattern", ""),
            what_appears_effective=list(output.get("what_appears_effective") or []),
            must_not_copy=list(output.get("must_not_copy") or []),
            originality_constraints=list(output.get("originality_constraints") or []),
        )
    except ValueError as exc:
        # Reuses the accepted dataclass's own "must_not_copy cannot be empty" validation - a
        # model that omits it is rejected, never silently defaulted to a made-up constraint.
        raise ReferenceAnalysisUnavailableError(f"AI output failed originality validation: {exc}") from exc


# ---------------------------------------------------------------------------------------------
# Phase B.5: IMAGE-aware reference analysis -> versioned Visual DNA. Reuses the SAME one-shot
# call_generate() pattern, the SAME ReferenceDeconstruction dataclass and the repository's existing
# multimodal mechanism (ContentPart(type="artifact_ref", data URI, image mime) + modalities
# ["text","image"], as already used by capabilities/media_subject_match_capability.py). A filesystem
# path written into prompt text is NOT visual evidence - the image bytes must be attached.
# ---------------------------------------------------------------------------------------------

import base64  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
from pathlib import Path  # noqa: E402

from PIL import Image  # noqa: E402

from integrations.prompts.protocol import RenderedPrompt  # noqa: E402

REFERENCE_IMAGE_ANALYSIS_PROMPT_VERSION = "2"
_MAX_REFERENCE_SIDE = 1568


class ReferenceImageRequired(ValueError):
    """Visual analysis was requested without real, decodable image bytes (a path string alone is
    never treated as evidence)."""


def prepare_reference_image(reference_path: Path | str) -> tuple[bytes, str, str]:
    """(jpeg_bytes, data_uri, sha256_of_the_original_file). Raises ReferenceImageRequired unless the
    path is a real, decodable image file."""
    path = Path(reference_path)
    if not path.is_file():
        raise ReferenceImageRequired(f"reference image file not found: {path} (a path string alone is not visual evidence)")
    original = path.read_bytes()
    try:
        with Image.open(io.BytesIO(original)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(original)) as decoded:
            image = decoded.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ReferenceImageRequired(f"reference file is not a decodable image: {path}") from exc
    if max(image.size) > _MAX_REFERENCE_SIDE:
        scale = _MAX_REFERENCE_SIDE / max(image.size)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=92)
    jpeg = out.getvalue()
    return jpeg, "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"), hashlib.sha256(original).hexdigest()


def build_reference_image_request(prompt: RenderedPrompt, *, data_uri: str) -> GenerateRequest:
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[
                ContentPart(type="text", text="Analyze the attached Instagram visual reference board image and return the structured visual DNA."),
                ContentPart(type="artifact_ref", artifact_ref=data_uri, mime_type="image/jpeg"),
            ]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
        modalities=["text", "image"],
    )


async def analyze_reference_image(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, reference_path: Path | str,
    repo_relative_path: str | None = None,
):
    """ONE controlled vision call -> (ReferenceDeconstruction, InstagramVisualDNA). Run once per
    reference (scripts/_instagram_phase_b5_analyze_reference.py), never per Instagram post."""
    from services.instagram_visual_dna import InstagramVisualDNA, StyleDirection, assert_mechanics_only

    _jpeg, data_uri, digest = prepare_reference_image(reference_path)
    try:
        prompt = prompt_repository.resolve(REFERENCE_ANALYSIS_PROMPT_NAME, REFERENCE_IMAGE_ANALYSIS_PROMPT_VERSION)
    except Exception as exc:
        raise ReferenceAnalysisUnavailableError(f"prompt unavailable: {exc}") from exc
    request = build_reference_image_request(prompt, data_uri=data_uri)
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=REFERENCE_ANALYSIS_PROMPT_NAME,
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )
    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise ReferenceAnalysisUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise ReferenceAnalysisUnavailableError(str(outcome.error))
    assert outcome.response is not None
    output = outcome.response.structured_output
    if output is None:
        raise ReferenceAnalysisUnavailableError("no structured output returned")

    try:
        deconstruction = ReferenceDeconstruction(
            reference_description=f"founder Instagram visual reference board ({digest[:12]})",
            hook_mechanics=output.get("hook_mechanics", ""), pacing=output.get("pacing", ""),
            scene_structure=output.get("scene_structure", ""), narrative_progression=output.get("narrative_progression", ""),
            typography_behavior=output.get("typography_behavior", ""), visual_rhythm=output.get("visual_rhythm", ""),
            editing_rhythm=output.get("editing_rhythm", ""), cta_mechanics=output.get("cta_mechanics", ""),
            interaction_pattern=output.get("interaction_pattern", ""),
            what_appears_effective=list(output.get("what_appears_effective") or []),
            must_not_copy=list(output.get("must_not_copy") or []),
            originality_constraints=list(output.get("originality_constraints") or []),
        )
        dna = InstagramVisualDNA(
            version="1", reference_path=repo_relative_path or str(reference_path), reference_sha256=digest,
            analysis_prompt_version=REFERENCE_IMAGE_ANALYSIS_PROMPT_VERSION,
            analysis_model=getattr(outcome.call, "model_used", None),
            typography=list(output.get("typography") or []), spatial_system=list(output.get("spatial_system") or []),
            image_behavior=list(output.get("image_behavior") or []), composition_rhythm=list(output.get("composition_rhythm") or []),
            accent_system=list(output.get("accent_system") or []), brand_invariants=list(output.get("brand_invariants") or []),
            non_invariants=list(output.get("non_invariants") or []),
            style_directions=[StyleDirection(**d) for d in (output.get("style_directions") or [])],
            must_not_copy=list(output.get("must_not_copy") or []),
            originality_constraints=list(output.get("originality_constraints") or []),
            reference_deconstruction={
                k: v for k, v in output.items()
                if k in ReferenceDeconstruction.__dataclass_fields__ and k not in ("must_not_copy", "originality_constraints")
            },
        )
        assert_mechanics_only(dna)
    except ValueError as exc:
        raise ReferenceAnalysisUnavailableError(f"AI output failed originality/structure validation: {exc}") from exc
    return deconstruction, dna
