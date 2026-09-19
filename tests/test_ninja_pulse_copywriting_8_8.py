from pathlib import Path

import yaml

from integrations.prompts.file_repository import FilePromptRepository


def test_copywriting_8_8_is_a_narrow_schema_compatible_prompt_update() -> None:
    root = Path("prompts")
    prompt_87 = FilePromptRepository(root).resolve("copywriting", "8.7")
    prompt_88 = FilePromptRepository(root).resolve("copywriting", "8.8")

    assert prompt_88.version == "8.8"
    assert prompt_88.output_schema == prompt_87.output_schema
    assert "ending_strategy" not in prompt_88.output_schema.get("properties", {})

    raw = Path("prompts/copywriting/v8.8.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    rules = "\n".join(parsed["rules"])
    assert "OPTIONAL HUMAN ENDING (V8.8)" in rules
    assert "actively prefer ONE short human final sentence" in rules
    assert "Absence from the supplied context is not evidence" in rules
    assert "FINAL-SENTENCE FACT SCOPE (V8.8)" in rules
    assert "ABSENCE IS NOT EVIDENCE (V8.8)" in rules
    assert "FINAL SENTENCE MUST BE NEW (V8.8)" in rules
    assert "Что думаете?" in rules


def test_copywriting_8_8_keeps_editorial_context_seam() -> None:
    source = Path("capabilities/copywriting_capability.py").read_text(encoding="utf-8")
    assert '"8.7", "8.8"' in source
