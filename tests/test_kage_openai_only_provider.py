"""KAGE OpenAI-only provider migration: every KAGE visual call is OpenAI (gpt-image-2.5-sunburst edit
for a source photo, gpt-image-2.5-flare text-to-image when there is none), is reserved in the
per-story envelope before dispatch and costed from reported usage after it, and no runtime path can
reach Gemini. The OpenAI SDK client is faked at its lowest seam, so the real adapter, budget
executor, pricing catalog and envelope all run; nothing touches the network."""
from __future__ import annotations

import ast
import base64
import io
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from pydantic import SecretStr

from core.config import Settings, settings
from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest, ReferenceImage
from integrations.llm_gateway.providers import openai_image_adapter
from scripts import _kage_telegram_bounded_natural_batch as batch
from scripts import _kage_telegram_atomic_natural_canary as canary
from services import budgeted_image_execution
from services import editorial_recomposition
from services import kage_visual_fallback as vf
from services.budget_guard import ImageBudgetReservation
from services.budgeted_image_execution import BudgetedImageExecutor
from services.image_pricing import ImageExecutionProfile, ImagePricingCatalog, UnknownImagePricingError
from services.kage_telegram_canary_envelope import (
    VISUAL_COMPLIANCE_STAGE,
    VISUAL_GENERATION_STAGE,
    VISUAL_RECOMPOSITION_STAGE,
    TelegramCanaryEnvelope,
    maximum_canary_cost,
    telegram_canary_envelope,
    visual_recomposition_worst_case,
)

REPO = Path(__file__).resolve().parents[1]
FLARE, SUNBURST = "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"


def _jpeg(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (30, 50, 80))
    # Keep the four corners calm so the production pixel-branding risk gate does not correctly
    # classify this synthetic fixture as a watermark/logo-heavy source photo. The textured center
    # still makes it non-blank for generated-image validation.
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = width // 4, height // 4, width * 3 // 4, height * 3 // 4
    draw.rectangle((left, top, right, bottom), fill=(80, 120, 170))
    for y in range(top, bottom, max(1, height // 40)):
        draw.line((left, y, right, y), fill=((y * 3) % 255, (y * 5) % 255, 140), width=2)
    out = io.BytesIO()
    image.save(out, format="JPEG")
    return out.getvalue()


def _source(width: int, height: int) -> bytes:
    """A flat landscape source photo: recomposition-eligible (no corner branding-pixel risk)."""
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(out, format="JPEG")
    return out.getvalue()


class FakeImagesAPI:
    """Stands in for `AsyncOpenAI().images.with_raw_response` - records every call's kwargs."""

    def __init__(self, image: bytes, usage: tuple[int, int, int] | None):
        self.image, self.usage, self.calls = image, usage, []

    def _raw(self):
        usage = None if self.usage is None else SimpleNamespace(
            input_tokens=self.usage[0] + self.usage[1],
            input_tokens_details=SimpleNamespace(text_tokens=self.usage[0], image_tokens=self.usage[1]),
            output_tokens=self.usage[2],
        )
        parsed = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(self.image).decode())], usage=usage)
        return SimpleNamespace(headers={"x-request-id": "req_fake"}, status_code=200, parse=lambda: parsed)

    async def generate(self, **kwargs):
        self.calls.append(("generate", kwargs))
        return self._raw()

    async def edit(self, **kwargs):
        self.calls.append(("edit", kwargs))
        return self._raw()


class FakeGuard:
    def __init__(self):
        self.reserved, self.completed = [], []

    async def check(self, capability_name, priority, worst_case):
        return None

    async def reserve_image_cost(self, **kwargs):
        self.reserved.append(kwargs)
        return ImageBudgetReservation(status="reserved", reserved_cost=kwargs["worst_case"], attempt=1, prior_status=None)

    async def complete_image_reservation(self, **kwargs):
        self.completed.append(kwargs)


@pytest.fixture
def openai_world(monkeypatch):
    """A KAGE runtime with an OpenAI key, NO Gemini key, a fake OpenAI client, a fake budget guard,
    and a Gemini adapter that explodes if anything ever reaches it."""
    world = SimpleNamespace(guard=FakeGuard(), api=None, clients=[])

    def make_api(image: bytes, usage: tuple[int, int, int] | None = (1_200, 0, 6_000)):
        world.api = FakeImagesAPI(image, usage)
        return world.api

    world.make_api = make_api

    def fake_client(**kwargs):
        world.clients.append(kwargs)
        assert world.api is not None
        return SimpleNamespace(images=SimpleNamespace(with_raw_response=world.api))

    monkeypatch.setattr(openai_image_adapter, "AsyncOpenAI", fake_client)
    monkeypatch.setattr(budgeted_image_execution, "build_budgeted_image_executor",
                        lambda: BudgetedImageExecutor(budget_guard=world.guard))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test-not-real"))
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")

    from integrations.llm_gateway.providers import gemini_image_adapter

    async def no_gemini(*_a, **_k):
        raise AssertionError("a KAGE runtime path reached the Gemini adapter")

    monkeypatch.setattr(gemini_image_adapter.GeminiImageAdapter, "generate_image", no_gemini)
    return world


# --- pricing: official GPT Image 2.5 token rates, PROVISIONAL per-call caps --------------------------------

def _quote(model, operation, refs=0, quality="high", size="1536x1024"):
    request = ImageGenerationRequest(
        prompt="p", operation=operation,
        reference_images=tuple(ReferenceImage(data=_jpeg(800, 450), mime_type="image/jpeg") for _ in range(refs)),
    )
    return ImagePricingCatalog().quote(
        ImageExecutionProfile(provider="openai", model=model, quality=quality, size=size, operation=operation), request)


def test_gpt_image_2_5_worst_cases_are_official_rates_times_provisional_caps():
    gen = _quote(FLARE, ImageGenerationOperation.TEXT_TO_IMAGE)
    edit = _quote(SUNBURST, ImageGenerationOperation.IMAGE_EDIT, refs=1)
    assert gen.worst_case_cost_usd == Decimal("0.440")  # 16,000 text x $5/M + 12,000 out x $30/M
    assert edit.worst_case_cost_usd == Decimal("0.488")  # + 6,000 reference-image tokens x $8/M
    assert gen.requires_reported_usage and edit.requires_reported_usage
    assert gen.cost_semantics == edit.cost_semantics == "official_token_rates_provisional_per_call_caps"
    # Source edit is still larger than generation plus its separately priced compliance call.
    assert visual_recomposition_worst_case() == max(gen.worst_case_cost_usd, edit.worst_case_cost_usd)
    assert maximum_canary_cost() == Decimal("0.746389") + Decimal("0.488") == Decimal("1.234389")
    assert canary.MAX_COST == batch.PER_STORY_MAX_USD == Decimal("1.234389")
    assert batch.BATCH_HARD_CAP_USD == Decimal("6.18") >= 5 * batch.PER_STORY_MAX_USD


@pytest.mark.parametrize("model, operation, refs, quality", [
    (FLARE, ImageGenerationOperation.TEXT_TO_IMAGE, 0, "medium"),       # unpriced quality
    (SUNBURST, ImageGenerationOperation.IMAGE_EDIT, 2, "high"),         # more references than priced
    (FLARE, ImageGenerationOperation.TEXT_TO_IMAGE, 1, "high"),         # generation with a reference
], ids=["unpriced_quality", "edit_two_references", "generation_with_reference"])
def test_unpriced_gpt_image_2_5_shapes_fail_before_any_call(model, operation, refs, quality):
    # an edit with no reference is already refused by the request schema (a ValueError) - either way
    # nothing unpriced can reach a provider
    with pytest.raises((UnknownImagePricingError, ValueError)):
        _quote(model, operation, refs=refs, quality=quality)


def test_edit_without_reference_fails_at_request_contract_before_pricing():
    with pytest.raises(ValueError, match="requires at least one reference_images entry"):
        ImageGenerationRequest(prompt="p", operation=ImageGenerationOperation.IMAGE_EDIT)


# --- Tier 2: no source photo -> ONE OpenAI flare generation ------------------------------------------------

@pytest.mark.asyncio
async def test_generation_is_one_openai_flare_call_reserved_then_costed_from_usage(openai_world):
    api = openai_world.make_api(_jpeg(1536, 1024), usage=(1_200, 0, 6_000))
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        image, reason = await vf.generate_editorial_image("a verified editorial brief")
    assert reason == "ok" and image == api.image
    assert [c[0] for c in api.calls] == ["generate"]
    kwargs = api.calls[0][1]
    assert (kwargs["model"], kwargs["size"], kwargs["quality"], kwargs["n"]) == (FLARE, "1536x1024", "high", 1)
    assert (kwargs["output_format"], kwargs["output_compression"]) == ("jpeg", 90)
    assert openai_world.clients == [{"api_key": "sk-test-not-real", "max_retries": 0, "timeout": 120}]
    # reserved in the shared image budget at the worst case, completed at the usage-derived actual
    assert openai_world.guard.reserved[0]["worst_case"] == Decimal("0.440")
    actual = Decimal("0.186")  # 1,200 text x $5/M + 6,000 image output x $30/M
    assert openai_world.guard.completed[0]["accounted_cost"] == actual
    record = envelope.dispatch_records[-1]
    assert record["stage"] == VISUAL_GENERATION_STAGE and record["model"] == FLARE
    assert Decimal(record["reserved_max_cost_usd"]) == Decimal("0.440")
    assert Decimal(record["actual_cost_usd"]) == actual
    assert (record["actual_input_tokens"], record["actual_output_tokens"]) == (1_200, 6_000)
    assert (record["actual_text_input_tokens"], record["actual_image_input_tokens"]) == (1_200, 0)
    assert (record["provider_request_id"], record["provider_status_code"]) == ("req_fake", 200)
    assert record["status"] == "SUCCEEDED"
    cost, _, gap = batch._story_cost({"provider_dispatches": envelope.dispatch_records})
    assert cost == actual and gap is False


@pytest.mark.asyncio
async def test_generation_above_its_provisional_reservation_is_flagged_for_the_batch_stop(openai_world):
    openai_world.make_api(_jpeg(1536, 1024), usage=(1_000, 0, 20_000))  # 0.605 > 0.440 reserved
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        image, reason = await vf.generate_editorial_image("brief")
    assert image is None and reason.startswith("generation_error:ImageCostBoundExceededError")
    assert openai_world.guard.completed[0]["status"] == "cost_bound_exceeded"
    assert openai_world.guard.completed[0]["accounted_cost"] == Decimal("0.605")
    assert envelope.dispatch_records[-1]["status"] == "ACTUAL_EXCEEDED_RESERVATION"


@pytest.mark.asyncio
async def test_generation_without_reported_usage_is_refused_and_fails_closed(openai_world):
    openai_world.make_api(_jpeg(1536, 1024), usage=None)
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        image, reason = await vf.generate_editorial_image("brief")
    assert image is None and reason.startswith("generation_error:ImageCostUnaccountedError")
    # the paid call is booked at its full reservation, never silently at an "expected" cost
    assert openai_world.guard.completed[0]["accounted_cost"] == Decimal("0.440")
    assert envelope.dispatch_records[-1]["actual_cost_usd"] is None
    assert batch._story_cost({"provider_dispatches": envelope.dispatch_records})[2] is True  # batch stops


# --- Tier 1: a source photo -> ONE OpenAI sunburst edit -----------------------------------------------------

@pytest.mark.asyncio
async def test_source_photo_edit_is_one_openai_sunburst_call_on_a_bounded_reference(openai_world):
    api = openai_world.make_api(_jpeg(1536, 1024), usage=(500, 2_500, 6_200))
    source = _source(2400, 1350)  # eligible landscape, larger than the 1536 px reference bound
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        result = await editorial_recomposition.maybe_recompose(source_image_bytes=source)
    assert result.used_recomposed_image is True and result.image_bytes == api.image
    assert (result.provider, result.model) == ("openai", SUNBURST)
    assert [c[0] for c in api.calls] == ["edit"]
    kwargs = api.calls[0][1]
    assert (kwargs["model"], kwargs["size"], kwargs["quality"], kwargs["input_fidelity"]) == (
        SUNBURST, "1536x1024", "high", "high")
    assert (kwargs["output_format"], kwargs["output_compression"]) == ("jpeg", 90)
    [(_name, reference, mime)] = kwargs["image"]
    with Image.open(io.BytesIO(reference)) as ref:
        assert max(ref.size) <= 1536 and mime == "image/jpeg"
    assert openai_world.guard.reserved[0]["worst_case"] == Decimal("0.488")
    actual = Decimal("0.2085")  # 500 text x $5/M + 2,500 image x $8/M + 6,200 output x $30/M
    record = envelope.dispatch_records[-1]
    assert record["stage"] == VISUAL_RECOMPOSITION_STAGE and record["model"] == SUNBURST
    assert Decimal(record["actual_cost_usd"]) == actual and record["status"] == "SUCCEEDED"
    assert (record["actual_input_tokens"], record["actual_output_tokens"]) == (3_000, 6_200)
    assert (record["actual_text_input_tokens"], record["actual_image_input_tokens"]) == (500, 2_500)


@pytest.mark.asyncio
async def test_source_edit_without_usage_keeps_the_original_photo_and_fails_closed(openai_world):
    openai_world.make_api(_jpeg(1536, 1024), usage=None)
    source = _source(1600, 900)
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        result = await editorial_recomposition.maybe_recompose(source_image_bytes=source)
    assert result.used_recomposed_image is False and result.image_bytes == source
    assert envelope.dispatch_records[-1]["actual_cost_usd"] is None
    assert batch._story_cost({"provider_dispatches": envelope.dispatch_records})[2] is True


@pytest.mark.asyncio
async def test_one_story_never_pays_for_both_an_edit_and_a_generation(openai_world):
    openai_world.make_api(_jpeg(1536, 1024))
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        await editorial_recomposition.maybe_recompose(source_image_bytes=_source(1600, 900))
        image, reason = await vf.generate_editorial_image("brief")
    assert image is None and reason.startswith("cost_envelope_refused")
    assert len(openai_world.api.calls) == 1


# --- no Gemini: key absent, no import, no call -------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_openai_key_means_no_call_and_a_gemini_key_is_never_a_substitute(openai_world, monkeypatch):
    openai_world.make_api(_jpeg(1536, 1024))
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("gemini-key-must-be-ignored"))
    image, reason = await vf.generate_editorial_image("brief")
    result = await editorial_recomposition.maybe_recompose(source_image_bytes=_source(1600, 900))
    assert (image, reason) == (None, "openai_api_key_absent")
    assert result.used_recomposed_image is False and result.fallback_reason == "openai_api_key_absent"
    assert openai_world.api.calls == [] and openai_world.clients == []


_RUNTIME_PACKAGES = ("services", "worker", "bot", "capabilities", "integrations", "core", "database", "schemas")
_DORMANT = {Path("integrations/llm_gateway/providers/gemini_image_adapter.py")}


def test_no_runtime_module_imports_the_gemini_adapter_or_a_google_sdk():
    offenders = []
    for package in _RUNTIME_PACKAGES:
        for path in (REPO / package).rglob("*.py"):
            rel = path.relative_to(REPO)
            if rel in _DORMANT:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [a.name for a in node.names]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if any("gemini" in n.lower() or n.startswith(("google.genai", "google.generativeai")) for n in names):
                    offenders.append(str(rel))
    assert offenders == []


def test_kage_starts_and_builds_its_env_without_any_gemini_key(monkeypatch):
    from scripts.kage_build_worker_env import build_worker_env, load_flags
    from worker import content_main

    host = "OPENAI_API_KEY=sk-test-not-real\nTELEGRAM_BOT_TOKEN=1:x\nPOSTGRES_PASSWORD=p\n"
    lines = build_worker_env(host, load_flags())
    keys = {line.split("=", 1)[0] for line in lines}
    assert "OPENAI_API_KEY" in keys
    assert not {k for k in keys if "GEMINI" in k or "GOOGLE" in k}
    assert not any("gemini" in line.lower() for line in lines)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.gemini_api_key is None
    for key, value in (("editorial_delivery_mode", "router"), ("unified_editorial_pipeline_enabled", False),
                       ("copywriting_prompt_version", "11.10"), ("gemini_api_key", None)):
        monkeypatch.setattr(settings, key, value)
    assert content_main._configure_telegram_copywriting_default() == "11.10"


def test_visual_provider_constants_are_openai_only():
    from services.kage_telegram_canary_envelope import VISUAL_STAGE_MODELS

    assert VISUAL_STAGE_MODELS == {
        VISUAL_RECOMPOSITION_STAGE: SUNBURST,
        VISUAL_GENERATION_STAGE: FLARE,
        VISUAL_COMPLIANCE_STAGE: "gpt-5.6-luna",
    }
    assert (vf.GENERATION_MODEL, vf.GENERATION_QUALITY, vf.GENERATION_SIZE) == (FLARE, "high", "1536x1024")
    assert (editorial_recomposition.RECOMPOSITION_PROVIDER, editorial_recomposition.RECOMPOSITION_MODEL) == (
        "openai", SUNBURST)
    for module in (vf, editorial_recomposition):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "gemini_api_key" not in source and "GeminiImageAdapter" not in source
