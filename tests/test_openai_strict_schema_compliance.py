"""Repository-wide invariant: every registered structured-output Capability's currently-active
prompt `output_schema` is compatible with OpenAI's Structured Outputs strict mode
(`integrations/llm_gateway/providers/openai_adapter.py`'s `_build_payload()` unconditionally
sends `"strict": True` for every `response_mode="json_schema"` request - Capabilities never opt
out of this).

This is the offline protection specified by
docs/openai_structured_outputs_remediation_plan.md (Track A, M3): a real, live OpenAI `400 Bad
Request` (docs/phase10_live_production_validation.md) was caused by a missing
`additionalProperties: false` / array `items` sub-schema, undetected by the automated suite
because `FakeLLMGateway`/`FakeProviderAdapter` never enforce OpenAI's real schema constraints -
this test closes that blind spot with a static, no-network mechanical check, never a live call.

Mirrors Contract §6's existing, narrower convention ("`output_schema.required` must equal
`expected_output_keys`") - same "mechanically verify every prompt file against a fixed rule"
philosophy, extended to OpenAI's stricter recursive rule set.
"""
from pathlib import Path
from typing import Any

import pytest

from capabilities.copywriting_capability import CAPABILITY_NAME as COPYWRITING_CAPABILITY_NAME
from capabilities.copywriting_capability import COPYWRITING_CAPABILITY_DEFINITION
from capabilities.engagement_capability import CAPABILITY_NAME as ENGAGEMENT_CAPABILITY_NAME
from capabilities.engagement_capability import ENGAGEMENT_CAPABILITY_DEFINITION
from capabilities.intelligence_capability import CAPABILITY_NAME as INTELLIGENCE_CAPABILITY_NAME
from capabilities.intelligence_capability import INTELLIGENCE_CAPABILITY_DEFINITION
from capabilities.quality_capability import CAPABILITY_NAME as QUALITY_CAPABILITY_NAME
from capabilities.quality_capability import QUALITY_CAPABILITY_DEFINITION
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from capabilities.research_capability import RESEARCH_CAPABILITY_DEFINITION
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from capabilities.scoring_capability import SCORING_CAPABILITY_DEFINITION
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability_definition import CapabilityDefinition

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

# The exact 5 (capability_name, PROMPT_VERSION, CapabilityDefinition) triples every registered,
# live-default Capability currently resolves - mirrors capabilities/registry.py::build_registry()'s
# own hardcoded registration list (this repository's established "no dynamic discovery"
# convention), independently re-stated here rather than imported, so this test does not silently
# stop checking a Capability if it is ever removed from build_registry() without this file being
# updated too.
_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES: list[tuple[str, str, CapabilityDefinition]] = [
    (SCORING_CAPABILITY_NAME, "2", SCORING_CAPABILITY_DEFINITION),
    (QUALITY_CAPABILITY_NAME, "3", QUALITY_CAPABILITY_DEFINITION),
    (RESEARCH_CAPABILITY_NAME, "2", RESEARCH_CAPABILITY_DEFINITION),
    (INTELLIGENCE_CAPABILITY_NAME, "2", INTELLIGENCE_CAPABILITY_DEFINITION),
    (COPYWRITING_CAPABILITY_NAME, "4", COPYWRITING_CAPABILITY_DEFINITION),
    (ENGAGEMENT_CAPABILITY_NAME, "1", ENGAGEMENT_CAPABILITY_DEFINITION),
]


def _prompt_repository() -> FilePromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _strict_schema_violations(schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Pure, recursive validator - no I/O, no PromptRepository dependency. Returns a list of
    human-readable violation messages (empty means fully OpenAI-strict-mode-compatible).

    Checks, at every object node found (root, and recursively inside any `properties` entry
    whose `type == "object"`, and inside any array `items` schema that is itself an object):
    1. `additionalProperties` is present and is exactly `False`.
    2. Every key in `properties` appears in `required` (OpenAI strict mode's own rule: every
       property must be required - optionality is expressed only via a nullable type union,
       never via omission from `required`).
    3. Every property whose `type == "array"` declares an `items` sub-schema.
    Recurses into any nested object schema (object-typed property, or an array's object-typed
    `items`) - not merely root-level - so a future prompt that introduces nesting is still
    covered without this validator needing to change.
    """
    violations: list[str] = []

    if schema.get("type") != "object":
        return violations

    if schema.get("additionalProperties") is not False:
        violations.append(f"{path}: missing 'additionalProperties: false'")

    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    for key, sub_schema in properties.items():
        if key not in required:
            violations.append(f"{path}.properties.{key}: not present in 'required'")

        sub_type = sub_schema.get("type")
        if sub_type == "array":
            items = sub_schema.get("items")
            if items is None:
                violations.append(f"{path}.properties.{key}: array property has no 'items' sub-schema")
            elif isinstance(items, dict) and items.get("type") == "object":
                violations.extend(_strict_schema_violations(items, path=f"{path}.properties.{key}.items"))
        elif sub_type == "object":
            violations.extend(_strict_schema_violations(sub_schema, path=f"{path}.properties.{key}"))

    return violations


# ---------------------------------------------------------------------------
# RED: the validator itself must be a real check, not a no-op - proven against small, local,
# deliberately-invalid synthetic schemas, independent of any real prompt file.
# ---------------------------------------------------------------------------


def test_validator_detects_missing_additional_properties() -> None:
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
        # no "additionalProperties" key at all
    }

    violations = _strict_schema_violations(schema)

    assert any("additionalProperties" in v for v in violations)


def test_validator_detects_property_missing_from_required() -> None:
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}, "y": {"type": "string"}},
        "required": ["x"],  # "y" is missing
        "additionalProperties": False,
    }

    violations = _strict_schema_violations(schema)

    assert any("y" in v and "required" in v for v in violations)


def test_validator_detects_array_property_missing_items() -> None:
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array"}},  # no "items"
        "required": ["tags"],
        "additionalProperties": False,
    }

    violations = _strict_schema_violations(schema)

    assert any("items" in v for v in violations)


def test_validator_recurses_into_nested_object_properties() -> None:
    """No current prompt has a nested object, but the rule is inherently recursive - proven
    with a synthetic two-level schema so a future prompt that adds nesting is still covered."""
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "type": "object",
                "properties": {"inner": {"type": "string"}},
                "required": ["inner"],
                # missing additionalProperties: false at the NESTED level only
            }
        },
        "required": ["outer"],
        "additionalProperties": False,
    }

    violations = _strict_schema_violations(schema)

    assert any("outer" in v and "additionalProperties" in v for v in violations)


def test_validator_passes_a_fully_compliant_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["x", "tags"],
        "additionalProperties": False,
    }

    assert _strict_schema_violations(schema) == []


# ---------------------------------------------------------------------------
# RED (continued): the exact, real, pre-remediation prompt content - still on disk, immutable,
# per Phase 6 §8 - must be shown to violate the same invariant that a live OpenAI 400 exposed.
# This is empirical evidence against this repository's own real historical content, not only a
# synthetic schema, and requires no destructive git manipulation - the "before" versions were
# never edited in place; they are simply no longer the active default.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("scoring", "1"),
        ("quality", "1"),
        ("quality", "2"),
        ("research", "1"),
        ("intelligence", "1"),
        ("copywriting", "1"),
    ],
)
def test_pre_remediation_prompt_versions_fail_the_invariant(name: str, version: str) -> None:
    """Proves the invariant would have caught the exact defect class that produced the real
    live OpenAI 400 (docs/phase10_live_production_validation.md), had it existed before that
    live-validation attempt. Every one of these six historical versions is still on disk,
    byte-unchanged, and still independently resolvable (Phase 6 §8) - this is not a synthetic
    proxy, it is this repository's own actual pre-remediation content."""
    repository = _prompt_repository()

    rendered = repository.resolve(name, version)
    violations = _strict_schema_violations(rendered.output_schema)

    assert violations, f"expected '{name}' v{version} to violate the strict-schema invariant, but it did not"


# ---------------------------------------------------------------------------
# GREEN: every currently-active, registered, structured-output Capability's resolved prompt is
# now fully compliant.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("capability_name", "prompt_version", "definition"),
    _ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES,
    ids=[c[0] for c in _ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES],
)
def test_active_capability_prompt_is_strict_schema_compliant(
    capability_name: str, prompt_version: str, definition: CapabilityDefinition
) -> None:
    repository = _prompt_repository()

    # Proves the wiring, not just the content - resolve() must not raise UnknownPromptError.
    rendered = repository.resolve(capability_name, prompt_version)

    violations = _strict_schema_violations(rendered.output_schema)
    assert violations == [], f"'{capability_name}' v{prompt_version} violates strict-schema rules: {violations}"

    # expected_output_keys must remain aligned with output_schema.required (Contract §6's
    # existing, narrower rule, re-verified here for every active Capability in one pass).
    assert rendered.output_schema.get("required") == definition.expected_output_keys
