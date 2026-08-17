"""Unit tests for capabilities.article_generation_capability.ArticleGenerationCapability -
mirrors tests/test_research_capability.py's own FakeLLMGateway + FakePromptRepository convention
exactly (Phase 8 contract §15.1-§15.4). No DB, no network.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from capabilities.article_generation_capability import (
    ARTICLE_GENERATION_CAPABILITY_DEFINITION,
    CAPABILITY_NAME,
    ArticleGenerationCapability,
)
from capabilities.errors import RetryableCapabilityError, ValidationCapabilityError
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    CapabilityUsage,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"}, "lead": {"type": "string"},
        "context": {"type": "array"}, "timeline": {"type": "array"},
        "confirmed_facts": {"type": "array"}, "analysis": {"type": "array"},
        "implications": {"type": "array"}, "background": {"type": "array"},
        "risks": {"type": "array"}, "conclusion": {"type": "string"}, "sources": {"type": "array"},
    },
    "required": [
        "headline", "lead", "context", "timeline", "confirmed_facts", "analysis", "implications",
        "background", "risks", "conclusion", "sources",
    ],
}

_VALID_OUTPUT = {
    "headline": "H", "lead": "L", "context": [], "timeline": [], "confirmed_facts": ["F"],
    "analysis": [], "implications": [], "background": [], "risks": [], "conclusion": "C", "sources": [],
}

_RESEARCH_OUTPUT = {
    "thesis": "T", "confirmed_facts": ["F"], "timeline": [], "source_evidence": [],
    "primary_sources": [], "context_background": [], "implications": [], "competing_views": [],
    "gaps": [], "risky_claims": [], "suggested_article_angles": [], "confidence": 0.8,
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="2", system="You are a fake article writer.",
            rules=["Do not invent facts."], output_schema=_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(
    *, content: str | None = "raw NewsEvent content that must never be read",
    editorial_channel: str | None = None,
) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Anchor event", summary=None, content=content, url=None,
                category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="TELEGRAPH_ARTICLE", workflow_version=1, completed_steps=["generate_article"],
            ),
            telegraph_deep_research_output=_RESEARCH_OUTPUT,
            telegraph_visual_bundle_summary="1 hero image(s) selected.",
            telegraph_editorial_channel=editorial_channel,
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.C, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


@pytest.mark.asyncio
async def test_successful_generation_returns_structured_output() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=200),
        )
    )
    capability = ArticleGenerationCapability(gateway, _prompt_repository())
    result = await capability.execute(_context())
    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT


@pytest.mark.asyncio
async def test_request_never_includes_raw_news_event_content() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=200),
        )
    )
    capability = ArticleGenerationCapability(gateway, _prompt_repository())
    await capability.execute(_context(content="raw NewsEvent content that must never be read"))
    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "raw NewsEvent content that must never be read" not in sent_text
    assert "RESEARCH BUNDLE:" in sent_text
    assert "hero image" in sent_text  # visual summary is present, informational only


@pytest.mark.asyncio
async def test_missing_required_key_raises_validation_error() -> None:
    incomplete = {k: v for k, v in _VALID_OUTPUT.items() if k != "conclusion"}
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=incomplete, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=200),
        )
    )
    capability = ArticleGenerationCapability(gateway, _prompt_repository())
    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


@pytest.mark.asyncio
async def test_truncated_response_raises_retryable_error() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=None, finish_reason="length", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=6000),
        )
    )
    capability = ArticleGenerationCapability(gateway, _prompt_repository())
    with pytest.raises(RetryableCapabilityError):
        await capability.execute(_context())


def test_capability_definition_expected_output_keys_match_schema_required() -> None:
    assert set(ARTICLE_GENERATION_CAPABILITY_DEFINITION.expected_output_keys) == set(_OUTPUT_SCHEMA["required"])


@pytest.mark.asyncio
async def test_editorial_channel_is_threaded_into_the_request_text() -> None:
    """Required test 6 ("prompt selection works"): the same capability/prompt is used for both
    channels - only the CONTEXT text's own "Editorial channel: ..." line changes, never a
    different prompt name/schema."""
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=200),
        )
    )
    capability = ArticleGenerationCapability(gateway, _prompt_repository())
    await capability.execute(_context(editorial_channel="ninja_ai"))
    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "Editorial channel: ninja_ai" in sent_text


@pytest.mark.asyncio
async def test_unspecified_editorial_channel_never_silently_guessed() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=200),
        )
    )
    capability = ArticleGenerationCapability(gateway, _prompt_repository())
    await capability.execute(_context(editorial_channel=None))
    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "Editorial channel: (unspecified)" in sent_text
