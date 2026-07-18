"""FilePromptRepository: the first concrete `PromptRepository` implementation
(Phase 8 contract §7.5/§7.6, Phase 6 contract §8).

Prompt *content* is authored and versioned as static YAML files under
`prompts/<name>/v<N>.yaml`, outside Python (Phase 6 §8's ownership rule) -
never fetched from a network endpoint, never read from a database. Every
file is read exactly once, at construction time, into an immutable
in-memory mapping: `resolve()` itself performs zero I/O, which is what
guarantees side-effect-freedom and "a given (name, version) resolves to the
same RenderedPrompt for the life of the deployment" *by construction*,
matching ModelRegistry's static-catalogue discipline (Phase 7 §3 rule 2)
by analogy - not by embedding content in Python source, which the frozen
Phase 6 contract §8 explicitly places outside Python.

No mutating method exists or will ever be added here (Phase 6 §8: register/
update/publish/rollback belong to a separate, not-yet-built Prompt
Publisher, never to PromptRepository).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]  # no stub package installed repo-wide; see services/source_registry.py

from integrations.prompts.protocol import RenderedPrompt

_VERSION_FILENAME_RE = re.compile(r"^v(\d+)\.yaml$")


class UnknownPromptError(Exception):
    """Raised by FilePromptRepository.resolve() for an unpublished prompt name, or a
    published name with no matching version (§7.6: a clear, typed error, never a wrong
    result)."""


class PromptContentError(Exception):
    """Raised at construction (boot) time if a prompt YAML file's content is malformed, or its
    declared `name`/`version` does not match its own location on disk - a fail-loud
    content-authoring mistake, never silently tolerated (mirrors RegistryConsistencyError's
    boot-time-failure precedent)."""


def _parse_version_number(filename: str) -> int:
    match = _VERSION_FILENAME_RE.match(filename)
    if match is None:
        raise PromptContentError(
            f"Prompt version filename '{filename}' does not match the required 'v<N>.yaml' shape."
        )
    return int(match.group(1))


def _require_str(raw: dict[Any, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise PromptContentError(f"{path}: '{key}' must be a string.")
    return value


def _require_str_list(raw: dict[Any, Any], key: str, path: Path) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PromptContentError(f"{path}: '{key}' must be a list of strings.")
    return value


def _require_dict(raw: dict[Any, Any], key: str, path: Path) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise PromptContentError(f"{path}: '{key}' must be a mapping.")
    return value


def _load_rendered_prompt(path: Path, *, expected_name: str, expected_version: str) -> RenderedPrompt:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PromptContentError(f"{path}: expected a YAML mapping at the top level.")
    rendered = RenderedPrompt(
        name=_require_str(raw, "name", path),
        version=str(raw.get("version")),
        system=_require_str(raw, "system", path),
        rules=_require_str_list(raw, "rules", path),
        output_schema=_require_dict(raw, "output_schema", path),
    )
    if rendered.name != expected_name:
        raise PromptContentError(
            f"{path}: declared name '{rendered.name}' does not match its directory name "
            f"'{expected_name}'."
        )
    if rendered.version != expected_version:
        raise PromptContentError(
            f"{path}: declared version '{rendered.version}' does not match its filename-derived "
            f"version '{expected_version}'."
        )
    return rendered


class FilePromptRepository:
    """Implements `PromptRepository` (integrations.prompts.protocol) over a directory of
    versioned YAML files: `root/<name>/v<N>.yaml`. `root` is caller-supplied - this class
    names no default location itself, keeping it independently constructible in tests and
    swappable at the boot-sequence call site that will inject it (a later milestone)."""

    def __init__(self, root: Path) -> None:
        self._prompts: dict[tuple[str, str], RenderedPrompt] = {}
        self._latest_version: dict[str, str] = {}

        for name_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            name = name_dir.name
            numbered_versions: list[tuple[int, str]] = []
            for version_file in sorted(name_dir.glob("v*.yaml")):
                version_number = _parse_version_number(version_file.name)
                version = str(version_number)
                rendered = _load_rendered_prompt(version_file, expected_name=name, expected_version=version)
                self._prompts[(name, version)] = rendered
                numbered_versions.append((version_number, version))

            if numbered_versions:
                numbered_versions.sort(key=lambda pair: pair[0])
                self._latest_version[name] = numbered_versions[-1][1]

    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        """version=None returns the latest published version. Pure in-memory lookup - no I/O,
        no validation logic (validation belongs to the not-yet-built Prompt Publisher, at
        publish time, per Phase 6 §8)."""
        resolved_version = version if version is not None else self._latest_version.get(name)
        if resolved_version is None:
            raise UnknownPromptError(f"No published prompt named '{name}'.")

        rendered = self._prompts.get((name, resolved_version))
        if rendered is None:
            raise UnknownPromptError(f"No prompt '{name}' version '{resolved_version}'.")
        return rendered
