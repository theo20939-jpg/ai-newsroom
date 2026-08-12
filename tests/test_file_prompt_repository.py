"""Tests for integrations.prompts.file_repository.FilePromptRepository (Phase 8 M2).

Every test constructs its own repository against a synthetic tmp_path tree of YAML
files - never against the real prompts/ directory - mirroring the established
validate_architecture test pattern (real content is exercised separately, as the
milestone's runtime-evidence step).
"""
import socket
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]  # no stub package installed repo-wide

from integrations.prompts.file_repository import (
    FilePromptRepository,
    PromptContentError,
    UnknownPromptError,
)


def _write_prompt(root: Path, dir_name: str, file_version: int | str, **content_overrides: object) -> None:
    content = {
        "name": dir_name,
        "version": str(file_version),
        "system": f"system prompt for {dir_name} v{file_version}",
        "rules": ["rule one", "rule two"],
        "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
        **content_overrides,
    }
    prompt_dir = root / dir_name
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / f"v{file_version}.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")


def test_resolve_is_deterministic_across_repeated_calls(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "greeting", 1)
    repo = FilePromptRepository(tmp_path)

    first = repo.resolve("greeting", "1")
    second = repo.resolve("greeting", "1")

    assert first == second
    # loaded once at construction into an immutable in-memory mapping - resolve() returns the
    # same frozen object every time, the strongest form of "resolves to the same RenderedPrompt"
    assert first is second


def test_version_none_resolves_to_latest_published_version(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "greeting", 1, system="v1 content")
    _write_prompt(tmp_path, "greeting", 2, system="v2 content")
    repo = FilePromptRepository(tmp_path)

    latest = repo.resolve("greeting")

    assert latest.version == "2"
    assert latest.system == "v2 content"
    # the earlier version remains independently resolvable, unchanged
    assert repo.resolve("greeting", "1").system == "v1 content"


def test_unknown_name_raises_unknown_prompt_error(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "greeting", 1)
    repo = FilePromptRepository(tmp_path)

    with pytest.raises(UnknownPromptError):
        repo.resolve("no_such_prompt")


def test_unknown_version_raises_unknown_prompt_error(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "greeting", 1)
    repo = FilePromptRepository(tmp_path)

    with pytest.raises(UnknownPromptError):
        repo.resolve("greeting", "99")


def test_rendered_prompt_fields_match_source_yaml(tmp_path: Path) -> None:
    _write_prompt(
        tmp_path,
        "greeting",
        1,
        system="hello",
        rules=["a", "b", "c"],
        output_schema={"type": "object"},
    )
    repo = FilePromptRepository(tmp_path)

    rendered = repo.resolve("greeting", "1")

    assert rendered.name == "greeting"
    assert rendered.version == "1"
    assert rendered.system == "hello"
    assert rendered.rules == ["a", "b", "c"]
    assert rendered.output_schema == {"type": "object"}


def test_name_mismatch_between_directory_and_content_fails_at_construction(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "greeting", 1, name="different_name")

    with pytest.raises(PromptContentError):
        FilePromptRepository(tmp_path)


def test_version_mismatch_between_filename_and_content_fails_at_construction(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "greeting", 1, version="2")

    with pytest.raises(PromptContentError):
        FilePromptRepository(tmp_path)


# ---------------------------------------------------------------------------
# Phase 23.1J.1 - dotted minor versions ("v8.1.yaml"), e.g. prompts/copywriting/v8.1.yaml.
# Every plain-integer test above must keep passing unchanged (regression) - these are additive.
# ---------------------------------------------------------------------------


def test_dotted_minor_version_resolves_by_its_exact_string() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_prompt(root, "greeting", "8", system="v8 content")
        _write_prompt(root, "greeting", "8.1", system="v8.1 content")
        repo = FilePromptRepository(root)

        assert repo.resolve("greeting", "8").system == "v8 content"
        assert repo.resolve("greeting", "8.1").system == "v8.1 content"


def test_dotted_minor_version_sorts_after_its_own_major_version_for_latest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_prompt(root, "greeting", "8", system="v8 content")
        _write_prompt(root, "greeting", "8.1", system="v8.1 content")
        repo = FilePromptRepository(root)

        latest = repo.resolve("greeting")
        assert latest.version == "8.1"


def test_dotted_minor_version_does_not_disturb_plain_integer_latest_ordering() -> None:
    """A dotted version like "8.1" must sort between "8" and "9" - never accidentally treated as
    larger than every plain integer version (e.g. via naive string comparison, "8.1" < "10")."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_prompt(root, "greeting", "8", system="v8 content")
        _write_prompt(root, "greeting", "8.1", system="v8.1 content")
        _write_prompt(root, "greeting", "10", system="v10 content")
        repo = FilePromptRepository(root)

        latest = repo.resolve("greeting")
        assert latest.version == "10"


def test_resolve_makes_no_network_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves, rather than merely asserts, §7.6's isolation claim: resolve() still succeeds
    with socket creation blocked entirely."""
    _write_prompt(tmp_path, "greeting", 1)
    repo = FilePromptRepository(tmp_path)

    def _blocked_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("resolve() must not open a network socket")

    monkeypatch.setattr(socket, "socket", _blocked_socket)

    rendered = repo.resolve("greeting", "1")

    assert rendered.name == "greeting"


def test_module_never_imports_database_or_provider_sdk() -> None:
    """Mirrors capabilities.gateway_call's negative-import test - also mechanically enforced
    by scripts/validate_architecture.py's prompt-repository-isolation rule."""
    import integrations.prompts.file_repository as module

    source_path = module.__file__
    assert source_path is not None
    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    for forbidden in ("sqlalchemy", "database.session", "openai", "anthropic", "httpx", "requests"):
        assert forbidden not in content, f"{forbidden} must not be referenced"
