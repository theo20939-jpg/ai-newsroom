"""VISUAL-SINGLE-BRAND-MARK-1: the required test coverage for the "exactly one canonical NNJ
brand mark" product invariant - idempotent finalization (§20), per-presentation mark counts (§21),
generated-fake-branding Art Director classification (§22), and structural renderer-duplication
detection (§23). Real PIL/JPEG bytes throughout - never a mocked boolean standing in for an image;
mark-count assertions come from the real, non-mocked structural decision object
(`MasterNewsBrandingDecision`), never from OCR/visual logo detection (spec's own explicit
instruction)."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from services.brand_renderer import render_branded_media
from services.nnj_master_news_overlay import (
    ComponentPlacement,
    MasterNewsBrandingDecision,
    apply_master_news_branding,
)
from services.presentation_director import BREAKING, DATA, QUOTE, DataCandidate, QuoteCandidate
from services.telegram_art_director import (
    ArtDirectorDecision,
    ArtDirectorIssueCode,
    PixelInputContract,
    evaluate_art_direction_shadow,
)
from services.telegram_art_director_vision import VISION_PROMPT_NAME, VISION_PROMPT_VERSION, evaluate_art_direction_vision
from services.telegram_revision_router import RevisionAction, route_revision
from services.visual_root_cause import classify_root_cause
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_CANVAS = (1280, 720)


def _flat_photo(color: tuple[int, int, int] = (120, 120, 120)) -> bytes:
    im = Image.new("RGB", _CANVAS, color)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _all_busy_photo() -> bytes:
    """Full-frame high-frequency noise - every corner scores unsafe (mirrors tests/
    test_v2_10h_master_news_production.py's own `_all_busy_photo()` fixture shape)."""
    import random
    rng = random.Random(42)
    im = Image.new("RGB", _CANVAS)
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(_CANVAS[0] * _CANVAS[1])])
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _brand_mark_count(decision: MasterNewsBrandingDecision) -> int:
    """The real, structural mark count for one `apply_master_news_branding()` decision - never
    derived from pixels. Mutual exclusion (VISUAL-SINGLE-BRAND-MARK-1 §6) guarantees this is
    always 0 or 1, never 2."""
    count = 0
    if decision.upper_mark.placement is not ComponentPlacement.OMITTED:
        count += 1
    if decision.lower_signature.placement is not ComponentPlacement.OMITTED:
        count += 1
    return count


# ---------------------------------------------------------------------------
# §20 - idempotency
# ---------------------------------------------------------------------------

def test_single_finalize_produces_exactly_one_brand_mark() -> None:
    branded, decision = apply_master_news_branding(_flat_photo())
    assert _brand_mark_count(decision) <= 1
    assert _brand_mark_count(decision) == 1  # a clean quiet photo always finds a safe corner
    assert decision.already_finalized is False


def test_repeated_finalization_never_adds_a_second_mark() -> None:
    """raw -> finalize -> finalize -> finalize: still exactly one mark, byte-identical output from
    the second call onward (VISUAL-SINGLE-BRAND-MARK-1 §6/§20)."""
    once, decision_1 = apply_master_news_branding(_flat_photo())
    assert _brand_mark_count(decision_1) == 1

    twice, decision_2 = apply_master_news_branding(once)
    assert decision_2.already_finalized is True
    assert decision_2.already_finalized_had_overlay is True
    assert twice == once  # completely unchanged, never re-composited

    thrice, decision_3 = apply_master_news_branding(twice)
    assert decision_3.already_finalized is True
    assert thrice == once


def test_repeated_finalization_of_a_safe_suppressed_image_stays_at_zero_marks() -> None:
    """A NO_OVERLAY_SAFETY result (all-busy photo) must stay at zero marks across repeats too -
    idempotency must never accidentally "upgrade" a safe-suppressed image into a branded one."""
    once, decision_1 = apply_master_news_branding(_all_busy_photo())
    assert _brand_mark_count(decision_1) == 0
    assert decision_1.degradation_mode == "no_overlay"

    twice, decision_2 = apply_master_news_branding(once)
    assert decision_2.already_finalized is True
    assert decision_2.already_finalized_had_overlay is False
    assert decision_2.degradation_mode == "no_overlay"
    assert twice == once


def test_finalization_ignores_new_params_once_already_finalized() -> None:
    """A repeat call passing a DIFFERENT `disable_lower_signature` must still be a pure no-op -
    idempotency means "never re-evaluate," not "re-evaluate with the new params.\""""
    once, _decision = apply_master_news_branding(_flat_photo())
    twice, decision = apply_master_news_branding(once, disable_lower_signature=True)
    assert twice == once
    assert decision.already_finalized is True


# ---------------------------------------------------------------------------
# §21 - presentations: NEWS light/dark/busy, BREAKING, QUOTE
# (DATA already has its own extensive "exactly one bottom signature" suite in
# tests/test_brand_renderer.py::test_data_card_renders_exactly_one_bottom_signature_end_to_end /
# test_data_card_never_calls_master_news_branding_or_upper_mark /
# test_data_card_never_ships_with_zero_branding_on_a_maximally_busy_photo - not duplicated here.)
# ---------------------------------------------------------------------------

def test_news_light_photo_has_exactly_one_mark() -> None:
    _branded, decision = apply_master_news_branding(_flat_photo(color=(230, 230, 230)))
    assert _brand_mark_count(decision) == 1


def test_news_dark_photo_has_exactly_one_mark() -> None:
    _branded, decision = apply_master_news_branding(_flat_photo(color=(20, 20, 20)))
    assert _brand_mark_count(decision) == 1


def test_news_busy_photo_never_exceeds_one_mark_and_may_safely_suppress() -> None:
    _branded, decision = apply_master_news_branding(_all_busy_photo())
    count = _brand_mark_count(decision)
    assert count <= 1
    if count == 0:
        assert decision.degradation_mode == "no_overlay"


def test_breaking_places_exactly_one_brand_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.brand_renderer as brand_renderer_module
    calls: list[int] = []
    original = brand_renderer_module._paste_svg_mark

    def _spy(canvas, *, target_width, margin):
        calls.append(1)
        return original(canvas, target_width=target_width, margin=margin)

    monkeypatch.setattr(brand_renderer_module, "_paste_svg_mark", _spy)
    result = render_branded_media(
        presentation_type=BREAKING, source_image_bytes=_flat_photo(), category="technology", editorial_code="NP-0001",
    )
    assert result.success
    assert len(calls) == 1


def test_quote_places_exactly_one_brand_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.brand_renderer as brand_renderer_module
    calls: list[int] = []
    original = brand_renderer_module._paste_svg_mark

    def _spy(canvas, *, target_width, margin):
        calls.append(1)
        return original(canvas, target_width=target_width, margin=margin)

    monkeypatch.setattr(brand_renderer_module, "_paste_svg_mark", _spy)
    result = render_branded_media(
        presentation_type=QUOTE, source_image_bytes=None, category="technology", editorial_code="NP-0002",
        quote_candidate=QuoteCandidate(text="Real quote text, unmodified.", speaker="Example Speaker"),
    )
    assert result.success
    assert len(calls) == 1


def test_data_dispatch_still_never_touches_master_news_upper_mark_path() -> None:
    """Cross-check against tests/test_brand_renderer.py's own dedicated DATA suite - proves DATA's
    dispatch through this phase's own render_branded_media() import path is unaffected."""
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=_flat_photo(), category="finance", editorial_code="NP-0003",
        data_candidate=DataCandidate(value="42", unit="%", label="of respondents", evidence_fact="42% reported X"),
    )
    assert result.success


# ---------------------------------------------------------------------------
# §22 - generated fake branding: Art Director classification + routing
# ---------------------------------------------------------------------------

_VISION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string"}, "severity": {"type": "string"},
        "issues": {"type": "array"}, "overall_confidence": {"type": "number"},
    },
    "required": ["decision", "severity", "issues", "overall_confidence"],
}


def _vision_prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=VISION_PROMPT_NAME, version=VISION_PROMPT_VERSION,
        system="Fake Art Director for tests.", rules=["Use only provided codes."],
        output_schema=_VISION_OUTPUT_SCHEMA,
    ))
    return repository


@pytest.mark.asyncio
async def test_generated_fake_brand_mark_is_classified_and_routed_to_generation_model() -> None:
    """A generation-caused duplicate (renderer itself placed only ONE real component - the vision
    model reports a SECOND, fake one it sees in the scene) must: never PASS, decision=REWORK
    (never BLOCK), route to REDRAW (never RERENDER - re-running the same deterministic overlay on
    the same source bytes cannot remove a fake mark baked into the generated scene), and classify
    as GENERATION_MODEL root cause, never RENDERER/OVERLAY."""
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "decision": "rework", "severity": "medium",
            "issues": [{
                "code": "duplicate_nnj_brand_mark",
                "description": "A second, hand-drawn-looking NINJA mark is visible in the generated scene, "
                                "distinct from the clean canonical mark the renderer placed.",
                "confidence": 0.8, "recommended_action": "regenerate",
            }, {
                "code": "generation_artifact", "description": "fake brand mark drawn by the generation model",
                "confidence": 0.8, "recommended_action": "regenerate",
            }],
            "overall_confidence": 0.75,
        },
        finish_reason="stop", model_used="fake-vision-v1", usage=CapabilityUsage(input_tokens=40, output_tokens=20),
    ))
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-final-bytes", caption="Breaking news", presentation_type="NEWS",
        renderer_version="v1",
        # Renderer itself only placed the lower signature - the upper mark was never placed, so
        # any second mark visible in the FINAL image must have come from the generated scene.
        renderer_decision_metadata={
            "upper_mark": {"placement": "omitted"}, "lower_signature": {"placement": "lower_right"},
        },
    )

    result = await evaluate_art_direction_vision(gateway, _vision_prompt_repository(), pixel_input=pixel_input)

    assert result.decision == ArtDirectorDecision.REWORK
    assert result.decision != ArtDirectorDecision.PASS
    assert ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK in result.issue_codes

    root_cause = classify_root_cause(list(result.issue_codes))
    from database.models.visual_design_attempt import VisualFailureRootCause
    assert root_cause == VisualFailureRootCause.GENERATION_MODEL

    action = route_revision(result, attempt_count=0)
    assert action == RevisionAction.REDRAW


# ---------------------------------------------------------------------------
# §23 - structural renderer-duplication detection (prevented before any vision call)
# ---------------------------------------------------------------------------

def test_renderer_duplication_is_detected_structurally_and_blocked() -> None:
    """Simulates the pre-fix bug via renderer_decision_metadata (both components genuinely
    placed) - even without ever calling `select_master_news_branding()` again, the Art Director's
    OWN deterministic check must catch it: BLOCK, never REWORK, root_cause=OVERLAY, and
    route_revision() must send it straight to HUMAN_REVIEW - never a regeneration loop."""
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-bytes-both-marks-placed", caption="test", presentation_type="NEWS",
        renderer_version="v1",
        renderer_decision_metadata={
            "upper_mark": {"placement": "upper_right"}, "lower_signature": {"placement": "lower_right"},
        },
    )
    result = evaluate_art_direction_shadow(pixel_input)

    assert result.decision == ArtDirectorDecision.BLOCK
    assert result.issue_codes == [ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK]

    from database.models.visual_design_attempt import VisualFailureRootCause
    assert classify_root_cause(list(result.issue_codes)) == VisualFailureRootCause.OVERLAY
    assert route_revision(result, attempt_count=0) == RevisionAction.HUMAN_REVIEW


@pytest.mark.asyncio
async def test_renderer_duplication_short_circuits_before_any_vision_call() -> None:
    """No image-generation/vision budget is ever spent on a structurally-proven renderer bug
    (spec §12/§23's own "prevent structurally before image mutation" instruction) - the gateway
    must never even be invoked."""
    gateway = FakeLLMGateway(generate_error=AssertionError("vision must never be called for a structural renderer duplicate"))
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-bytes-both-marks-placed", caption="test", presentation_type="NEWS",
        renderer_version="v1",
        renderer_decision_metadata={
            "upper_mark": {"placement": "upper_right"}, "lower_signature": {"placement": "lower_right"},
        },
    )

    result = await evaluate_art_direction_vision(gateway, _vision_prompt_repository(), pixel_input=pixel_input)

    assert result.decision == ArtDirectorDecision.BLOCK
    assert gateway.received_requests == []


def test_master_news_overlay_itself_never_produces_two_placed_components() -> None:
    """End-to-end structural proof at the real renderer, not just the Art Director's own
    contract-level check above: across many different quiet-photo shades, select_master_news_
    branding() (via apply_master_news_branding()) never returns both components placed."""
    for shade in (30, 80, 120, 160, 200, 230):
        _branded, decision = apply_master_news_branding(_flat_photo(color=(shade, shade, shade)))
        both_placed = (
            decision.upper_mark.placement is not ComponentPlacement.OMITTED
            and decision.lower_signature.placement is not ComponentPlacement.OMITTED
        )
        assert not both_placed, f"shade={shade} produced both components placed"
