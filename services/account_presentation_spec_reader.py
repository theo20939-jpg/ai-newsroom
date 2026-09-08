"""DIRECTOR-CONTROL-PLANE-1A §24: reads design/account_presentation_spec.md's own real
Field/Value/Source table rows - never re-derives or fabricates these values in code, the markdown
file (a human-edited document) stays the single source of truth. Read-only, no mutation, no write
path exists anywhere in this module.

Exposes `NEEDS_FOUNDER_INPUT`/`REFERENCE_MISSING` fields honestly (spec §24's own explicit
requirement) rather than silently treating them as "not applicable" - both /accounts and /design
(spec §25) and the Visual Director's own context (spec §14) share this single reader."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_PATH = _REPO_ROOT / "design/account_presentation_spec.md"

_SECTION_RE = re.compile(r"^## (.+)$")
_ROW_RE = re.compile(r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|")
_SKIP_FIELD_NAMES = frozenset({"Field"})


@dataclass(frozen=True)
class PresentationSpecField:
    name: str
    value: str
    needs_founder_input: bool


@dataclass(frozen=True)
class AccountPresentationSpec:
    platform: str
    fields: list[PresentationSpecField] = field(default_factory=list)

    @property
    def needs_founder_input_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.needs_founder_input]


def read_account_presentation_spec(platform: str) -> AccountPresentationSpec | None:
    """`platform` matches (case-insensitively) against the "## <Platform> - ..." heading in the
    markdown file - e.g. "telegram" matches "## Telegram - NINJA PULSE". Returns None when the file
    is missing or no matching section is found - never a fabricated spec."""
    if not _SPEC_PATH.is_file():
        return None
    fields: list[PresentationSpecField] = []
    in_target_section = False
    for line in _SPEC_PATH.read_text(encoding="utf-8").splitlines():
        section_match = _SECTION_RE.match(line)
        if section_match:
            if in_target_section:
                break  # left the target section - nothing more to read
            in_target_section = platform.lower() in section_match.group(1).lower()
            continue
        if not in_target_section:
            continue
        row_match = _ROW_RE.match(line)
        if row_match is None:
            continue
        name = row_match.group("field").strip()
        value = row_match.group("value").strip()
        if name in _SKIP_FIELD_NAMES or set(name) <= {"-"}:
            continue
        fields.append(PresentationSpecField(
            name=name, value=value,
            needs_founder_input="NEEDS_FOUNDER_INPUT" in value or "REFERENCE_MISSING" in value,
        ))
    if not fields:
        return None
    return AccountPresentationSpec(platform=platform, fields=fields)


def summarize_for_creative(spec: AccountPresentationSpec | None) -> str:
    """Plain compact summary string for VisualDirectorContext/StrategyDirector consumption -
    mirrors services/design_spec_registry.py::describe_spec_for_creative()'s own "None -> honest
    empty string" contract."""
    if spec is None or not spec.fields:
        return ""
    return "; ".join(f"{f.name}={f.value}" for f in spec.fields)
