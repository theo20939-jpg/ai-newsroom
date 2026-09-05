"""SOCIAL-INTELLIGENCE-OPS-1, spec §58: /surface parser tests - never invents a chat_id."""
from __future__ import annotations

from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.telegram_surface_command_parser import (
    PARSER_PROMPT_NAME,
    PARSER_PROMPT_VERSION,
    parse_surface_command,
    resolve_chat_id,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_PROMPT = RenderedPrompt(
    name=PARSER_PROMPT_NAME, version=PARSER_PROMPT_VERSION, system="parse the surface", rules=["never invent a chat_id"],
    output_schema={"type": "object", "properties": {}, "required": []},
)


def test_real_prompt_file_loads() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)
    assert "refers_to_current_chat" in rendered.output_schema["properties"]


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=40, output_tokens=20),
    ))


@pytest.mark.asyncio
async def test_current_chat_reference_resolves_via_refers_to_current_chat() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway({
        "role": "internal_editorial", "name": "NINJA NEWSROOM", "refers_to_current_chat": True,
        "active": True, "analytics_enabled": False, "clarification_needed": [],
    })
    extraction = await parse_surface_command(
        gateway, prompt_repository, raw_text="NINJA NEWSROOM — внутренний редакторский чат.", current_chat_name_hint="NINJA NEWSROOM",
    )
    assert extraction.refers_to_current_chat is True
    assert resolve_chat_id(extraction, current_chat_id=-100) == -100


@pytest.mark.asyncio
async def test_different_channel_never_resolves_to_current_chat_id() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway({
        "role": "public_news_channel", "name": "NINJA PULSE", "username": "ninjapulse",
        "refers_to_current_chat": False, "active": True, "analytics_enabled": True, "clarification_needed": [],
    })
    extraction = await parse_surface_command(
        gateway, prompt_repository, raw_text="NINJA PULSE @ninjapulse - публичный канал, включить аналитику.",
        current_chat_name_hint="NINJA NEWSROOM",
    )
    assert extraction.refers_to_current_chat is False
    assert resolve_chat_id(extraction, current_chat_id=-100) is None  # never guessed


@pytest.mark.asyncio
async def test_ambiguous_public_surface_flags_clarification_needed() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway({
        "role": "public_news_channel", "name": "some channel", "refers_to_current_chat": False,
        "active": True, "analytics_enabled": False, "clarification_needed": ["no username or chat identity given"],
    })
    extraction = await parse_surface_command(
        gateway, prompt_repository, raw_text="сделай публичный канал", current_chat_name_hint="NINJA NEWSROOM",
    )
    assert extraction.clarification_needed
