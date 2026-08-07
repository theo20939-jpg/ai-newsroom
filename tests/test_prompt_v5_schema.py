"""Phase 19 M4: pure schema-shape tests for prompts/copywriting/v5.yaml - no DB, no network, no
LLM. Mirrors tests/test_openai_strict_schema_compliance.py's own Contract §6 check
(required == properties keys), scoped to this one file.
"""
from pathlib import Path

from integrations.prompts.file_repository import FilePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_EXPECTED_FIELDS = {
    "title", "opening", "context", "why_it_matters", "what_changed", "what_happens_next",
    "conclusion", "what_remains_unknown", "quote",
}


def _resolve_v5():
    repository = FilePromptRepository(_PROMPTS_ROOT)
    return repository.resolve("copywriting", "5")


def test_v5_resolves_without_error() -> None:
    prompt = _resolve_v5()
    assert prompt.version == "5"
    assert prompt.name == "copywriting"


def test_v5_schema_has_exactly_the_required_fields() -> None:
    prompt = _resolve_v5()
    assert set(prompt.output_schema["properties"].keys()) == _EXPECTED_FIELDS
    assert set(prompt.output_schema["required"]) == _EXPECTED_FIELDS


def test_v5_schema_is_additional_properties_false() -> None:
    prompt = _resolve_v5()
    assert prompt.output_schema["additionalProperties"] is False


def test_v5_nullable_fields_use_union_type() -> None:
    prompt = _resolve_v5()
    properties = prompt.output_schema["properties"]
    assert properties["what_happens_next"]["type"] == ["string", "null"]
    assert properties["what_remains_unknown"]["type"] == ["string", "null"]
    assert properties["quote"]["type"] == ["object", "null"]


def test_v5_non_nullable_fields_are_plain_string() -> None:
    prompt = _resolve_v5()
    properties = prompt.output_schema["properties"]
    for field in ("title", "opening", "context", "why_it_matters", "what_changed", "conclusion"):
        assert properties[field]["type"] == "string"


def test_v5_quote_object_matches_v4_nested_shape() -> None:
    """The quote sub-schema must stay identical to v4's own shape - never a divergent, second
    quote representation."""
    prompt = _resolve_v5()
    quote_schema = prompt.output_schema["properties"]["quote"]
    assert quote_schema["additionalProperties"] is False
    assert set(quote_schema["properties"].keys()) == {"text", "translated_text", "speaker"}
    assert set(quote_schema["required"]) == {"text", "translated_text", "speaker"}


def test_v4_still_resolves_unmodified_alongside_v5() -> None:
    """Prompt immutability: v4 must remain fully resolvable, unchanged, after v5 is added."""
    repository = FilePromptRepository(_PROMPTS_ROOT)
    v4 = repository.resolve("copywriting", "4")
    assert v4.version == "4"
    assert "body" in v4.output_schema["properties"]
    assert "opening" not in v4.output_schema["properties"]
