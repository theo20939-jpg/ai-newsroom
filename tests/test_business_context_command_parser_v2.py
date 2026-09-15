"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: services/business_context_command_parser.py v2 -
`feature_updates` extraction -> `current_features_add`/`planned_features_add`/
`undecided_facts_add` change-set fields, plus `raw_instruction` provenance passthrough (previously
hardcoded to "")."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.business_context_command_parser import (
    PARSER_PROMPT_NAME,
    PARSER_PROMPT_VERSION,
    BusinessContextExtraction,
    build_change_set,
    parse_business_context_command,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def test_real_v4_prompt_file_loads_and_declares_feature_updates() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)
    assert PARSER_PROMPT_VERSION == "4"
    product_item_schema = rendered.output_schema["properties"]["products_mentioned"]["items"]
    assert "feature_updates" in product_item_schema["properties"]
    feature_update_schema = product_item_schema["properties"]["feature_updates"]["items"]
    # HOTFIX (live production diagnosis): OpenAI's strict response_format="json_schema" mode
    # requires every key in `properties` to also appear in `required` - "note" (truly optional)
    # is expressed via a nullable type union, never via omission from `required`.
    assert set(feature_update_schema["required"]) == {"fact_key", "feature_name", "fact_state", "note"}
    assert feature_update_schema["properties"]["note"]["type"] == ["string", "null"]
    assert feature_update_schema["properties"]["fact_state"]["enum"] == ["confirmed", "planned", "undecided"]


def test_real_v4_prompt_output_schema_has_no_openai_strict_mode_violations() -> None:
    """Structural proof, not a spot-check: every object anywhere in the real output_schema lists
    EVERY one of its own `properties` keys in its own `required` array - the exact OpenAI
    structured-output contract the live production 400 (`invalid_json_schema`, missing 'note')
    proved v1/v2 violated. Recurses into every nested `items`/`properties` object found."""
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)

    def _check(node: dict, path: str) -> list[str]:
        violations: list[str] = []
        if node.get("type") == "object" and "properties" in node:
            required = set(node.get("required", []))
            properties = node["properties"]
            missing = set(properties.keys()) - required
            if missing:
                violations.append(f"{path}: missing {sorted(missing)} from required")
            for key, subschema in properties.items():
                violations.extend(_check(subschema, f"{path}.{key}"))
        if node.get("type") == "array" and "items" in node:
            violations.extend(_check(node["items"], f"{path}[]"))
        return violations

    violations = _check(rendered.output_schema, "output_schema")
    assert violations == [], f"OpenAI strict-mode required-field violations: {violations}"


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=PARSER_PROMPT_NAME, version=PARSER_PROMPT_VERSION, system="parse the business context message",
        rules=["never invent a fact"], output_schema={"type": "object", "properties": {}, "required": []},
    ))
    return repository


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=50, output_tokens=30),
    ))


def _empty_output(**overrides) -> dict:
    base = {
        "products_mentioned": [], "campaign_updates": [], "milestones": [], "directives": [],
        "claims": [], "clarification_needed": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_planned_feature_extraction_produces_planned_features_add() -> None:
    output = _empty_output(products_mentioned=[{
        "slug": "ai", "name": "NINJA AI",
        "feature_updates": [{
            "fact_key": "production_mode.status", "feature_name": "Production Mode", "fact_state": "planned",
        }],
    }])
    extraction = await parse_business_context_command(
        _gateway(output), _prompt_repository(), raw_text="В NINJA AI добавляем Production Mode.",
        context_summary_text="(нет продуктов в системе)", now=datetime.now(timezone.utc),
    )
    change_set = build_change_set(extraction, raw_text="В NINJA AI добавляем Production Mode.")
    version_op = next(op for op in change_set if op["entity_type"] == "product_context_version")
    assert version_op["structured_context"]["planned_features_add"] == ["Production Mode"]
    assert version_op["raw_instruction"] == "В NINJA AI добавляем Production Mode."


@pytest.mark.asyncio
async def test_undecided_fact_extraction_produces_undecided_facts_add() -> None:
    output = _empty_output(products_mentioned=[{
        "slug": "ai", "name": "NINJA AI",
        "feature_updates": [{
            "fact_key": "production_mode.billing", "feature_name": "Production Mode billing",
            "fact_state": "undecided",
        }],
    }])
    extraction = await parse_business_context_command(
        _gateway(output), _prompt_repository(), raw_text="Пока в разработке, экономику ещё не решили.",
        context_summary_text="(нет продуктов в системе)", now=datetime.now(timezone.utc),
    )
    change_set = build_change_set(extraction, raw_text="Пока в разработке, экономику ещё не решили.")
    version_op = next(op for op in change_set if op["entity_type"] == "product_context_version")
    assert version_op["structured_context"]["undecided_facts_add"] == ["production_mode.billing"]


@pytest.mark.asyncio
async def test_confirmed_and_undecided_can_coexist_in_one_message() -> None:
    output = _empty_output(products_mentioned=[{
        "slug": "ai", "name": "NINJA AI",
        "feature_updates": [
            {"fact_key": "web_search.status", "feature_name": "Web Search", "fact_state": "confirmed"},
            {
                "fact_key": "web_search.public_availability", "feature_name": "Web Search availability",
                "fact_state": "undecided",
            },
        ],
    }])
    extraction = await parse_business_context_command(
        _gateway(output), _prompt_repository(), raw_text="x",
        context_summary_text="(нет продуктов в системе)", now=datetime.now(timezone.utc),
    )
    change_set = build_change_set(extraction, raw_text="x")
    version_op = next(op for op in change_set if op["entity_type"] == "product_context_version")
    assert version_op["structured_context"]["current_features_add"] == ["Web Search"]
    assert version_op["structured_context"]["undecided_facts_add"] == ["web_search.public_availability"]


def test_build_change_set_with_no_feature_updates_matches_v1_behavior() -> None:
    """Regression guard: a product mentioned with only current_stage/description (no
    feature_updates at all) behaves exactly as it did before this phase."""
    extraction = BusinessContextExtraction(
        products_mentioned=[{"slug": "vpn", "name": "NINJA VPN", "current_stage": "beta"}],
    )
    change_set = build_change_set(extraction, raw_text="raw text here")
    version_op = next(op for op in change_set if op["entity_type"] == "product_context_version")
    assert version_op["structured_context"] == {"current_stage": "beta"}
    assert version_op["raw_instruction"] == "raw text here"


def test_build_change_set_default_raw_text_is_empty_string_backward_compatible() -> None:
    """The `raw_text` parameter is optional/defaulted - any pre-existing caller that doesn't pass
    it keeps getting the old (empty) behavior, never a TypeError."""
    extraction = BusinessContextExtraction(products_mentioned=[{"slug": "vpn", "name": "NINJA VPN", "description": "d"}])
    change_set = build_change_set(extraction)
    version_op = next(op for op in change_set if op["entity_type"] == "product_context_version")
    assert version_op["raw_instruction"] == ""
