"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §43: /launch parser tests - never invents a field the message
did not address."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.social_launch_command_parser import (
    PARSER_PROMPT_NAME,
    PARSER_PROMPT_VERSION,
    extraction_to_structure,
    parse_launch_command,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_PROMPT = RenderedPrompt(
    name=PARSER_PROMPT_NAME, version=PARSER_PROMPT_VERSION, system="parse the launch instruction",
    rules=["never invent a field"], output_schema={"type": "object", "properties": {}, "required": []},
)


def test_real_prompt_file_loads() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)
    assert "target_identity" in rendered.output_schema["properties"]
    assert "historical_content_policy" in rendered.output_schema["properties"]


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=40, output_tokens=20),
    ))


def _base_output(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "target_identity": "NINJA PULSE", "current_identity": None, "launch_state": None,
        "planned_launch_at": None, "launch_date_status": None, "baseline_policy": None,
        "historical_content_policy": None, "summary": "", "clarification_needed": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_telegram_transition_instruction_parses_current_and_target_identity() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway(_base_output(
        current_identity="NINJA VPN", historical_content_policy="legacy_context_only",
        summary="Rebranding NINJA VPN to NINJA PULSE; old VPN posts are legacy context only.",
    ))
    extraction = await parse_launch_command(
        gateway, prompt_repository, raw_text="Текущий канал - NINJA VPN, переходим в NINJA PULSE.",
        platform="telegram", previous_structure=None,
    )
    assert extraction.current_identity == "NINJA VPN"
    assert extraction.historical_content_policy == "legacy_context_only"


@pytest.mark.asyncio
async def test_instagram_empty_account_instruction_parses_cleanly() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway(_base_output(summary="Empty account, cold start."))
    extraction = await parse_launch_command(
        gateway, prompt_repository, raw_text="Аккаунт Instagram пустой, начинаем с нуля.",
        platform="instagram", previous_structure=None,
    )
    assert extraction.target_identity == "NINJA PULSE"
    assert extraction.current_identity is None


def test_extraction_to_structure_omits_unset_fields_never_fabricates_them() -> None:
    from services.social_launch_command_parser import SocialLaunchExtraction

    extraction = SocialLaunchExtraction(target_identity="NINJA PULSE", summary="only target set")
    structure = extraction_to_structure(extraction)
    assert structure == {"target_identity": "NINJA PULSE", "summary": "only target set"}
    assert "launch_state" not in structure
    assert "planned_launch_at" not in structure
