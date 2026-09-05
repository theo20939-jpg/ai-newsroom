"""Phase 18 M5 - Meme Image Generation tests (docs/phase18_m5_meme_image_generation_report.md).

No network, no live provider call anywhere in this file - MockImageAdapter is deterministic and
local. `LocalImageStorage` writes to a temporary directory (pytest's own `tmp_path` fixture), not
`settings.image_storage_root` - fully isolated, no shared state between test runs.
"""
from __future__ import annotations

import pytest
from PIL import Image

from integrations.llm_gateway.image_protocol import ImageGenerationRequest, ImageGenerationResponse
from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import CapabilityUsage
from schemas.meme_concept import MemeConcept, MemeFormat
from schemas.meme_image import MemeImageStatus
from services.meme_image_generation import build_image_prompt, generate_meme_image

_CONCEPT = MemeConcept(
    # MEME-PROD-2: punchline was a bare "pl" placeholder - too short to be a meaningful "must not
    # appear in the prompt" check, and coincidentally a substring of ordinary English words (e.g.
    # "nameplate") that legitimately appear in the prompt's own instructional text once that text
    # was extended (services/meme_image_generation.py::build_image_prompt()) - a realistic short
    # phrase removes that false-collision risk while keeping the same intent.
    premise="p", setup="s", punchline="Jobs are still safe, technically.", humor_mechanism="irony",
    visual_scene="A CEO on stage pointing at a slide reading 'Jobs are safe'.",
    visual_punchline="A robot quietly wheels his own desk out the door behind him mid-speech.",
    visual_style="reaction photo",
    characters_objects=["CEO", "presentation slide"], text_overlay_intent="intent",
    source_fact_links=["fact"], forbidden_interpretations=[], meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
)


class _FailingGateway:
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        raise RuntimeError("provider unavailable")


class _FailThenSucceedGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        return await MockImageAdapter().generate_image(request)


class _BadBytesGateway:
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            image_bytes=b"not a real image",
            model_used="fake", provider="fake", usage=CapabilityUsage(units=1, unit_type="image"),
        )


# ---------------------------------------------------------------------------
# build_image_prompt
# ---------------------------------------------------------------------------


def test_build_image_prompt_includes_visual_scene_and_objects() -> None:
    prompt = build_image_prompt(_CONCEPT)
    assert _CONCEPT.visual_scene in prompt
    assert "CEO" in prompt
    assert "presentation slide" in prompt


def test_build_image_prompt_excludes_punchline_and_instructs_no_text() -> None:
    """M0's own recommendation: image has no baked-in text - M6 overlays it deterministically."""
    prompt = build_image_prompt(_CONCEPT)
    assert _CONCEPT.punchline not in prompt
    assert "no text" in prompt.lower()


# ---------------------------------------------------------------------------
# MockImageAdapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_adapter_is_deterministic_for_the_same_prompt() -> None:
    adapter = MockImageAdapter()
    first = await adapter.generate_image(ImageGenerationRequest(prompt="A CEO on stage."))
    second = await adapter.generate_image(ImageGenerationRequest(prompt="A CEO on stage."))
    assert first.image_bytes == second.image_bytes


@pytest.mark.asyncio
async def test_mock_adapter_differs_for_different_prompts() -> None:
    adapter = MockImageAdapter()
    a = await adapter.generate_image(ImageGenerationRequest(prompt="A CEO on stage."))
    b = await adapter.generate_image(ImageGenerationRequest(prompt="A dog wearing sunglasses."))
    assert a.image_bytes != b.image_bytes


@pytest.mark.asyncio
async def test_mock_adapter_produces_a_valid_1024_square_png() -> None:
    import io

    adapter = MockImageAdapter()
    response = await adapter.generate_image(ImageGenerationRequest(prompt="test"))
    with Image.open(io.BytesIO(response.image_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (1024, 1024)


@pytest.mark.asyncio
async def test_mock_adapter_reports_zero_cost_usage() -> None:
    adapter = MockImageAdapter()
    response = await adapter.generate_image(ImageGenerationRequest(prompt="test"))
    assert response.usage.units == 1
    assert response.usage.unit_type == "image"


# ---------------------------------------------------------------------------
# generate_meme_image - mode gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_makes_zero_calls(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    class _NeverCalledGateway:
        async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
            raise AssertionError("must never be called when mode=='off'")

    result = await generate_meme_image(
        _CONCEPT, gateway=_NeverCalledGateway(), storage=storage, mode="off",
    )
    assert result.status == MemeImageStatus.OFF
    assert result.storage_key is None


@pytest.mark.asyncio
async def test_mode_dry_run_generates_and_stores(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    result = await generate_meme_image(
        _CONCEPT, gateway=MockImageAdapter(), storage=storage, mode="dry_run",
    )

    assert result.status == MemeImageStatus.GENERATED
    assert result.storage_key is not None
    assert storage.exists(result.storage_key)
    assert result.cost_usd == "0"
    assert result.width == 1024
    assert result.height == 1024
    assert result.attempt_count == 1


@pytest.mark.asyncio
async def test_generation_failure_after_bounded_attempts_returns_failed(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    result = await generate_meme_image(
        _CONCEPT, gateway=_FailingGateway(), storage=storage, mode="dry_run",
    )

    assert result.status == MemeImageStatus.FAILED
    assert result.error_code is not None
    assert result.attempt_count == 2  # _MAX_GENERATION_ATTEMPTS, bounded not unlimited


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    gateway = _FailThenSucceedGateway()

    result = await generate_meme_image(_CONCEPT, gateway=gateway, storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.GENERATED
    assert result.attempt_count == 2
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_malformed_image_bytes_from_gateway_are_handled_not_raised(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    result = await generate_meme_image(_CONCEPT, gateway=_BadBytesGateway(), storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.FAILED
    assert result.error_code is not None


@pytest.mark.asyncio
async def test_regenerating_the_same_concept_is_idempotent_in_storage(tmp_path) -> None:
    """Same prompt -> same bytes -> same content-addressed key -> storing twice is a safe no-op
    (LocalImageStorage's own idempotent-upsert precedent), never a duplicate file or an error."""
    storage = LocalImageStorage(tmp_path)

    first = await generate_meme_image(_CONCEPT, gateway=MockImageAdapter(), storage=storage, mode="dry_run")
    second = await generate_meme_image(_CONCEPT, gateway=MockImageAdapter(), storage=storage, mode="dry_run")

    assert first.storage_key == second.storage_key
    assert first.sha256 == second.sha256


# ---------------------------------------------------------------------------
# MEME-PROD-2 §10: retry classification - a `retryable=False` exception must stop the bounded
# loop immediately (exactly 1 attempt), never spend a second paid call retrying an identical
# request that cannot plausibly succeed differently.
# ---------------------------------------------------------------------------


class _NonRetryableFailingGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        self.calls += 1
        error = RuntimeError("authentication failed")
        error.retryable = False  # type: ignore[attr-defined]
        raise error


class _RetryableThenNeverCalledGateway:
    """Proves the loop only ever makes ONE call when the first fails non-retryably - a second call
    would mean the classification was ignored."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        self.calls += 1
        raise AssertionError("must never be called a second time after a non-retryable failure")


@pytest.mark.asyncio
async def test_non_retryable_failure_stops_after_exactly_one_attempt(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    gateway = _NonRetryableFailingGateway()

    result = await generate_meme_image(_CONCEPT, gateway=gateway, storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.FAILED
    assert result.attempt_count == 1  # never reached the bounded max of 2
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_gateway_without_retryable_attribute_keeps_the_prior_always_retry_behavior(tmp_path) -> None:
    """Backward compatibility: an exception with no `retryable` attribute at all (every gateway
    that existed before MEME-PROD-2, e.g. MockImageAdapter/GeminiImageAdapter's own errors) must
    still be retried exactly as before - `getattr(exc, "retryable", True)` defaults to True."""
    storage = LocalImageStorage(tmp_path)
    gateway = _FailingGateway()  # RuntimeError with no .retryable attribute at all

    result = await generate_meme_image(_CONCEPT, gateway=gateway, storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.FAILED
    assert result.attempt_count == 2  # unchanged - still tries the full bounded max


@pytest.mark.asyncio
async def test_first_successful_generation_never_causes_a_second_provider_call(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    gateway = MockImageAdapter()

    class _CountingGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
            self.calls += 1
            return await gateway.generate_image(request)

    counting = _CountingGateway()
    result = await generate_meme_image(_CONCEPT, gateway=counting, storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.GENERATED
    assert counting.calls == 1  # success on attempt 1 - the loop returns immediately, never a 2nd call


# ---------------------------------------------------------------------------
# MEME-PROD-2 §9: image prompt contract - the image model must never be asked to render meme
# typography, and a visual_scene implying readable text must be resolved to "render it blank/
# unlabeled," never left as a bare contradiction.
# ---------------------------------------------------------------------------


def test_prompt_never_injects_meme_top_or_bottom_text() -> None:
    """build_image_prompt() has no top_text/bottom_text parameter at all - MemeCopy (produced by
    a LATER, separate copywriting step) is structurally impossible to reach this function."""
    import inspect

    from services.meme_image_generation import build_image_prompt as _build

    params = inspect.signature(_build).parameters
    assert "top_text" not in params
    assert "bottom_text" not in params
    assert "copy" not in params


def test_prompt_resolves_contradictory_readable_label_scene_without_banning_the_object() -> None:
    """The exact production defect: _CONCEPT.visual_scene describes 'a slide reading "Jobs are
    safe"' - a literal readable-text scene. The prompt must still describe the slide (never delete
    the concept's own visual content) but must resolve the contradiction by instructing the model
    to render it blank/unlabeled, never both "reading X" and "no text" as a bare contradiction."""
    prompt = build_image_prompt(_CONCEPT)
    assert "slide" in prompt  # the object itself is preserved
    assert "no text" in prompt.lower()
    assert "blank" in prompt.lower() or "unlabeled" in prompt.lower()  # the resolution rule


def test_prompt_never_asks_for_readable_text_while_also_prohibiting_it_incoherently() -> None:
    """A softer structural proxy for "not a bare contradiction": the no-text instruction must
    itself acknowledge label-like objects rather than silently ignoring what visual_scene says."""
    prompt = build_image_prompt(_CONCEPT)
    assert "nameplate" in prompt.lower() or "label" in prompt.lower() or "sign" in prompt.lower()


def test_real_public_figure_names_pass_through_the_prompt_unmodified() -> None:
    """§6/§13: no blanket fictionalization or name replacement anywhere in this code - a concept
    naming a real adult public figure must reach the image prompt byte-for-byte unchanged."""
    concept = MemeConcept(
        premise="p", setup="s", punchline="A bold claim, again.", humor_mechanism="irony",
        visual_scene="Tim Cook standing confidently in front of a large Apple logo on a stage.",
        visual_punchline="A single tumbleweed rolls past the Apple logo as products are quietly carried out.",
        visual_style="documentary-style photo",
        characters_objects=["Tim Cook", "Apple logo", "stage"], text_overlay_intent="intent",
        source_fact_links=["fact"], forbidden_interpretations=[], meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
    )
    prompt = build_image_prompt(concept)
    assert "Tim Cook" in prompt
    assert "Apple logo" in prompt


# ---------------------------------------------------------------------------
# MEME-PROD-3: pseudo-text/fake-UI hardening, composition. MEME-PROD-4: visual_punchline/style.
# ---------------------------------------------------------------------------


def test_prompt_no_longer_permits_illegible_or_abstract_marks() -> None:
    """The exact wording MEME-PROD-2 shipped ("illegible/abstract marks only" as an acceptable
    rendering) is very likely why gpt-image-2 produced scribble-text/squares - it was explicit
    permission to draw mark-like texture. That permission must be gone."""
    prompt = build_image_prompt(_CONCEPT)
    assert "illegible/abstract marks only" not in prompt
    assert "abstract symbols" in prompt.lower()  # named only as something to AVOID, not permit
    assert "not even" in prompt.lower() or "never" in prompt.lower()


def test_prompt_names_ui_specific_objects_not_just_signage() -> None:
    """MEME-PROD-2's object list (nameplate/sign/screen/slide/product label) never named UI
    elements at all, even though v2's own encouraged meme_format list includes UI-parody formats
    (fake screenshot/chat, notification/UI parody, gaming HUD/UI parody)."""
    prompt = build_image_prompt(_CONCEPT).lower()
    for keyword in ("button", "icon", "hud overlay", "chat bubble", "notification badge"):
        assert keyword in prompt


def test_prompt_forbids_fake_interface_chrome_with_legible_labels() -> None:
    prompt = build_image_prompt(_CONCEPT).lower()
    assert "fake interface chrome" in prompt


def test_prompt_keeps_calm_top_bottom_bands_but_drops_centered_hero_framing() -> None:
    """MEME-PROD-4: the render-safety requirement (calm top/bottom bands for legible captions,
    meme_render.py's own genuine need) is kept, but the earlier "centered hero subject" cinematic
    framing is deliberately dropped per the brief's own §9 instruction - composition should serve
    the joke, not a hero shot."""
    prompt = build_image_prompt(_CONCEPT).lower()
    assert "centered" not in prompt
    assert "calm" in prompt and "top" in prompt and "bottom" in prompt


def test_prompt_explicitly_frames_this_as_a_meme_not_an_illustration() -> None:
    prompt = build_image_prompt(_CONCEPT).lower()
    assert "meme" in prompt
    assert "editorial illustration" in prompt
    assert "advertisement" in prompt


def test_prompt_includes_visual_punchline_and_visual_style_not_humor_mechanism() -> None:
    """MEME-PROD-4: the image model now receives the SPECIFIC visual joke (visual_punchline) and
    a visual tone (visual_style) instead of the abstract humor_mechanism label - distinct from
    punchline (still never included, per test_build_image_prompt_excludes_punchline_and_
    instructs_no_text above)."""
    prompt = build_image_prompt(_CONCEPT)
    assert _CONCEPT.visual_punchline in prompt
    assert _CONCEPT.visual_style in prompt
    assert _CONCEPT.punchline not in prompt


def test_prompt_adds_panel_composition_instruction_for_multi_panel_concepts() -> None:
    concept = MemeConcept(
        premise="p", setup="s", punchline="pl", humor_mechanism="irony",
        visual_scene="A cat.", visual_punchline="The same cat, increasingly unhinged, across four beats.",
        visual_style="cartoon", characters_objects=["cat"], text_overlay_intent="intent",
        source_fact_links=["fact"], forbidden_interpretations=[], meme_format="four_panel_escalation",
        panel_count=4, panel_beats=["making a plan", "obsessively waiting", "discovering it's sold out", "selling a kidney"],
    )
    prompt = build_image_prompt(concept).lower()
    assert "2x2" in prompt or "four" in prompt
    assert "same recurring character" in prompt or "same" in prompt
    assert "making a plan" in prompt
    assert "selling a kidney" in prompt


def test_prompt_has_no_panel_instruction_for_single_panel_concepts() -> None:
    prompt = build_image_prompt(_CONCEPT).lower()
    assert "2x2" not in prompt
    assert "panel 1" not in prompt
