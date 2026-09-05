"""INSTAGRAM-GROWTH-3, item 1/19: semantic matching tests - real prompt file loads via the real
FilePromptRepository (smoke test only), all logic tests use FakeLLMGateway/FakePromptRepository
(the established §15.1-§15.4 convention - tests/test_capability_testing_convention.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.instagram_semantic_matching import (
    SEMANTIC_MATCH_PROMPT_NAME,
    SEMANTIC_MATCH_PROMPT_VERSION,
    evaluate_semantic_relatedness,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_PROMPT = RenderedPrompt(
    name=SEMANTIC_MATCH_PROMPT_NAME, version=SEMANTIC_MATCH_PROMPT_VERSION,
    system="compare two subjects", rules=["never invent facts"],
    output_schema={
        "type": "object",
        "properties": {
            "is_related": {"type": "boolean"}, "relatedness": {"type": "number"},
            "rationale": {"type": "string"}, "shared_concepts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["is_related", "relatedness", "rationale", "shared_concepts"],
    },
)


def test_real_prompt_file_loads() -> None:
    """Smoke test - the real prompts/instagram_semantic_match/v1.yaml must actually parse."""
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(SEMANTIC_MATCH_PROMPT_NAME, SEMANTIC_MATCH_PROMPT_VERSION)
    assert rendered.name == SEMANTIC_MATCH_PROMPT_NAME
    assert "is_related" in rendered.output_schema["properties"]


@pytest.mark.asyncio
async def test_semantic_match_succeeds_via_structured_response() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={
            "is_related": True, "relatedness": 0.85,
            "rationale": "both concern the same underlying AI coding-assistant capability shift",
            "shared_concepts": ["AI coding assistants"],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=50, output_tokens=20),
    ))
    result = await evaluate_semantic_relatedness(
        gateway, prompt_repository, subject_a="viral 'AI writes my code now' trend",
        subject_b="OpenAI ships a new coding agent",
    )
    assert result.available is True
    assert result.is_related is True
    assert result.relatedness == 0.85
    assert result.call is not None and result.call.status == "SUCCESS"


@pytest.mark.asyncio
async def test_semantic_non_match_reported_honestly() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={
            "is_related": False, "relatedness": 0.05, "rationale": "unrelated topics", "shared_concepts": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=40, output_tokens=15),
    ))
    result = await evaluate_semantic_relatedness(
        gateway, prompt_repository, subject_a="viral dance trend", subject_b="quarterly earnings report",
    )
    assert result.available is True
    assert result.is_related is False
    assert result.relatedness == 0.05


@pytest.mark.asyncio
async def test_gateway_failure_is_reported_as_unavailable_never_raised() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_error=RuntimeError("provider outage"))
    result = await evaluate_semantic_relatedness(
        gateway, prompt_repository, subject_a="a", subject_b="b",
    )
    assert result.available is False
    assert result.unavailable_reason is not None


@pytest.mark.asyncio
async def test_missing_prompt_is_reported_as_unavailable() -> None:
    gateway = FakeLLMGateway()
    empty_repository = FakePromptRepository()
    result = await evaluate_semantic_relatedness(gateway, empty_repository, subject_a="a", subject_b="b")
    assert result.available is False
