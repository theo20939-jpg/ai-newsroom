"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: services/trend_fingerprint.py - one bounded LLM call
per observation, fail-soft on any Gateway failure. Mirrors tests/test_instagram_semantic_matching.py's
own conventions exactly."""
from __future__ import annotations

from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.trend_fingerprint import (
    TREND_FINGERPRINT_PROMPT_NAME,
    TREND_FINGERPRINT_PROMPT_VERSION,
    TrendFingerprint,
    compute_trend_fingerprint,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"}, "entities": {"type": "array", "items": {"type": "string"}},
        "format": {"type": "string"}, "hook_pattern": {"type": "string"}, "mechanic": {"type": "string"},
        "visual_pattern": {"type": "string"},
    },
    "required": ["topic", "entities", "format", "hook_pattern", "mechanic", "visual_pattern"],
}

_PROMPT = RenderedPrompt(
    name=TREND_FINGERPRINT_PROMPT_NAME, version=TREND_FINGERPRINT_PROMPT_VERSION,
    system="extract a trend fingerprint", rules=["never invent"], output_schema=_SCHEMA,
)


def test_real_prompt_file_loads() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(TREND_FINGERPRINT_PROMPT_NAME, TREND_FINGERPRINT_PROMPT_VERSION)
    assert rendered.name == TREND_FINGERPRINT_PROMPT_NAME
    for field in ("topic", "entities", "format", "hook_pattern", "mechanic", "visual_pattern"):
        assert field in rendered.output_schema["properties"]


@pytest.mark.asyncio
async def test_fingerprint_computed_successfully() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={
            "topic": "new foldable phone launch", "entities": ["iPhone Duo"], "format": "reel",
            "hook_pattern": "surprise reveal", "mechanic": "starter pack", "visual_pattern": "product close-up",
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=50, output_tokens=30),
    ))
    result = await compute_trend_fingerprint(gateway, prompt_repository, raw_topic_text="omg the new foldable is here", source="bluesky")
    assert result.available is True
    assert result.fingerprint is not None
    assert result.fingerprint.topic == "new foldable phone launch"
    assert result.fingerprint.mechanic == "starter pack"


@pytest.mark.asyncio
async def test_gateway_failure_is_fail_soft_never_raises() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_error=RuntimeError("simulated provider outage"))
    result = await compute_trend_fingerprint(gateway, prompt_repository, raw_topic_text="x", source="youtube")
    assert result.available is False
    assert result.fingerprint is None
    assert result.unavailable_reason is not None


@pytest.mark.asyncio
async def test_missing_prompt_is_fail_soft() -> None:
    empty_repository = FakePromptRepository()
    gateway = FakeLLMGateway()
    result = await compute_trend_fingerprint(gateway, empty_repository, raw_topic_text="x", source="youtube")
    assert result.available is False


def test_fingerprint_round_trips_through_dict() -> None:
    fp = TrendFingerprint(topic="t", entities=["a", "b"], format="reel", hook_pattern="h", mechanic="m", visual_pattern="v")
    restored = TrendFingerprint.from_dict(fp.as_dict())
    assert restored == fp


def test_fingerprint_from_dict_never_invents_missing_fields() -> None:
    restored = TrendFingerprint.from_dict({"topic": "only topic given"})
    assert restored.topic == "only topic given"
    assert restored.entities == []
    assert restored.mechanic == ""
