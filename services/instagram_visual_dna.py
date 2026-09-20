"""Phase B.5: versioned Instagram VISUAL DNA - what the founder-approved reference actually means,
as reviewable structured RULES, never as a template.

Built on the EXISTING reference architecture: `services/instagram_reference_deconstruction.py::
ReferenceDeconstruction` (hook mechanics, typography behaviour, visual rhythm, `must_not_copy`,
`originality_constraints`, ...) is embedded verbatim, and this module only adds the visual-language
dimensions a layout planner needs (typography / spatial system / image behaviour / composition
rhythm / accent system / brand invariants / non-invariants).

Lifecycle: the reference image is analysed ONCE (scripts/_instagram_phase_b5_analyze_reference.py,
one controlled vision call) into `docs/references/instagram/visual_dna/vN.json`. Every later
Creative Director call reuses that stored structure via `load_visual_dna()` +
`render_visual_dna_context()` - the raw image is never re-sent per post. Re-analysis happens only
when the reference file's sha256 changes (`dna_is_stale`) or a new reference set is approved.

Originality: DNA rules describe MECHANICS. `assert_mechanics_only()` rejects rules that contain
coordinates, hex colours, pixel sizes or literal reference copy, and `must_not_copy` is mandatory."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.instagram_reference_deconstruction import ReferenceDeconstruction

_REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_BOARD_PATH = _REPO_ROOT / "docs" / "references" / "instagram" / "instagram_visual_reference_board_v1.png"
DNA_DIR = _REPO_ROOT / "docs" / "references" / "instagram" / "visual_dna"

_RULE = Field(min_length=1, max_length=320)

# Literal copy that appears on the reference board - a DNA rule quoting it would be copying, not learning.
_REFERENCE_LITERALS = (
    "gpt-5", "mac studio", "airpods", "iphone 16", "ios 18", "human not found", "watch series",
    "нового поколения", "новости коротко", "when they said",
)
_FORBIDDEN_PATTERNS = (
    (re.compile(r"#[0-9a-fA-F]{3,8}\b"), "hex colour"),
    (re.compile(r"\b\d{2,4}\s?px\b", re.IGNORECASE), "pixel size"),
    (re.compile(r"\b[xy]\s*=\s*\d", re.IGNORECASE), "explicit coordinate"),
    (re.compile(r"\(\s*\d{2,4}\s*,\s*\d{2,4}\s*\)"), "coordinate pair"),
)


class StyleDirection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    mechanics: str = Field(min_length=1, max_length=400)


class InstagramVisualDNA(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    reference_path: str
    reference_sha256: str
    analysis_prompt_version: str
    analysis_model: str | None = None
    typography: list[str] = Field(min_length=1, max_length=8)
    spatial_system: list[str] = Field(min_length=1, max_length=8)
    image_behavior: list[str] = Field(min_length=1, max_length=8)
    composition_rhythm: list[str] = Field(min_length=1, max_length=8)
    accent_system: list[str] = Field(min_length=1, max_length=6)
    brand_invariants: list[str] = Field(min_length=1, max_length=8)
    non_invariants: list[str] = Field(min_length=1, max_length=8)
    style_directions: list[StyleDirection] = Field(default_factory=list, max_length=6)
    must_not_copy: list[str] = Field(min_length=1, max_length=10)
    originality_constraints: list[str] = Field(min_length=1, max_length=8)
    reference_deconstruction: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "typography", "spatial_system", "image_behavior", "composition_rhythm", "accent_system",
        "brand_invariants", "non_invariants", "must_not_copy", "originality_constraints",
    )
    @classmethod
    def _rules_are_bounded(cls, value: list[str]) -> list[str]:
        for rule in value:
            if not rule.strip() or len(rule) > 320:
                raise ValueError("each DNA rule must be a non-empty statement of at most 320 characters")
        return value


class VisualDnaOriginalityError(ValueError):
    """A DNA rule copies the reference (coordinates, colours, pixel sizes or its literal copy)."""


def assert_mechanics_only(dna: InstagramVisualDNA) -> None:
    rules = [
        *dna.typography, *dna.spatial_system, *dna.image_behavior, *dna.composition_rhythm,
        *dna.accent_system, *dna.brand_invariants, *dna.non_invariants,
        *(d.mechanics for d in dna.style_directions),
    ]
    for rule in rules:
        lowered = rule.lower()
        for literal in _REFERENCE_LITERALS:
            if literal in lowered:
                raise VisualDnaOriginalityError(f"DNA rule quotes reference copy {literal!r}: {rule!r}")
        for pattern, label in _FORBIDDEN_PATTERNS:
            if pattern.search(rule):
                raise VisualDnaOriginalityError(f"DNA rule contains a {label}: {rule!r}")
    if not dna.must_not_copy:
        raise VisualDnaOriginalityError("must_not_copy is mandatory")
    if dna.reference_deconstruction:
        # reuse the accepted dataclass's own must_not_copy validation
        _deconstruction_of(dna)


def _deconstruction_of(dna: InstagramVisualDNA) -> ReferenceDeconstruction:
    data = dict(dna.reference_deconstruction)
    data.setdefault("reference_description", f"founder reference board ({dna.reference_sha256[:12]})")
    data.setdefault("must_not_copy", list(dna.must_not_copy))
    data.setdefault("originality_constraints", list(dna.originality_constraints))
    allowed = ReferenceDeconstruction.__dataclass_fields__.keys()
    return ReferenceDeconstruction(**{k: v for k, v in data.items() if k in allowed})


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dna_is_stale(dna: InstagramVisualDNA, reference_path: Path = REFERENCE_BOARD_PATH) -> bool:
    """True when the reference image on disk is no longer the one this DNA was extracted from."""
    return not reference_path.exists() or file_sha256(reference_path) != dna.reference_sha256


def load_visual_dna(version: str | None = None, *, directory: Path = DNA_DIR) -> InstagramVisualDNA | None:
    """The stored, versioned DNA (latest by default). None when no analysis has been stored yet - a
    caller then plans without DNA; it never fabricates one."""
    if not directory.exists():
        return None
    if version is not None:
        path = directory / f"v{version}.json"
    else:
        candidates = sorted(
            (p for p in directory.glob("v*.json") if p.stem[1:].isdigit()), key=lambda p: int(p.stem[1:]),
        )
        if not candidates:
            return None
        path = candidates[-1]
    if not path.exists():
        return None
    dna = InstagramVisualDNA.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert_mechanics_only(dna)
    return dna


def render_visual_dna_context(dna: InstagramVisualDNA) -> str:
    """The exact structured text block handed to the Creative Director (CreativeDirectorInput.
    visual_dna_context). Structured rules only - never a file path."""
    def block(title: str, items: list[str]) -> str:
        return f"{title}:\n" + "\n".join(f"- {item}" for item in items)

    sections = [
        f"VISUAL DNA v{dna.version} (extracted once from the founder reference; learn the MECHANICS, never copy the piece)",
        block("TYPOGRAPHY", dna.typography),
        block("SPATIAL SYSTEM", dna.spatial_system),
        block("IMAGE BEHAVIOR", dna.image_behavior),
        block("COMPOSITION RHYTHM", dna.composition_rhythm),
        block("ACCENT SYSTEM", dna.accent_system),
        block("BRAND INVARIANTS (stay stable)", dna.brand_invariants),
        block("NON-INVARIANTS (should vary with content)", dna.non_invariants),
    ]
    if dna.style_directions:
        sections.append("STYLE DIRECTIONS (mechanics only):\n" + "\n".join(f"- {d.name}: {d.mechanics}" for d in dna.style_directions))
    sections.append(block("MUST NOT COPY", dna.must_not_copy))
    sections.append(block("ORIGINALITY CONSTRAINTS", dna.originality_constraints))
    return "\n".join(sections)


def render_visual_dna_markdown(dna: InstagramVisualDNA) -> str:
    lines = [
        f"# Instagram Visual DNA v{dna.version}",
        "",
        f"- reference: `{dna.reference_path}`",
        f"- reference sha256: `{dna.reference_sha256}`",
        f"- analysis prompt: `instagram_reference_analysis` v{dna.analysis_prompt_version}; model: `{dna.analysis_model}`",
        "",
        "> Rules describe visual MECHANICS extracted from the reference. They are not a template: no coordinates, colours, "
        "pixel sizes or reference copy. Founder review: does this describe what you actually like about the reference?",
        "",
    ]
    for title, items in (
        ("Typography", dna.typography), ("Spatial system", dna.spatial_system), ("Image behavior", dna.image_behavior),
        ("Composition rhythm", dna.composition_rhythm), ("Accent system", dna.accent_system),
        ("Brand invariants", dna.brand_invariants), ("Non-invariants (vary with content)", dna.non_invariants),
    ):
        lines += [f"## {title}", *(f"- {i}" for i in items), ""]
    if dna.style_directions:
        lines += ["## Style directions on the board", *(f"- **{d.name}** - {d.mechanics}" for d in dna.style_directions), ""]
    lines += ["## Must not copy", *(f"- {i}" for i in dna.must_not_copy), "",
              "## Originality constraints", *(f"- {i}" for i in dna.originality_constraints), ""]
    return "\n".join(lines)
