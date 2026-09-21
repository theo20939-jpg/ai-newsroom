"""Phase B.5R: Visual DNA v2 - a sample-by-sample reading of the founder reference board plus a small
library of VISUAL FAMILIES clustered from that evidence. v1 (a flat list of generic rules) is kept,
deprecated, for the record.

Two levels:
  A. global invariants (only what persists across the whole board or is an established brand requirement)
  B. visual families - executable mechanics, never fixed layouts; membership must reference analysed samples.

Evidence (`samples`) is INTERNAL review material. What reaches the Creative Director is the family
library + invariants (`render_visual_dna_v2_context`), and that text is checked to be mechanics only:
no coordinates, hex colours, pixel sizes or literal reference copy. `image_overlay_allowed` is always
False: dark design is a solid designed surface, never a translucent layer over a photograph."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.instagram_visual_dna import DNA_DIR, VisualDnaOriginalityError

SurfaceTone = Literal["dark_solid", "dark_image_field", "light", "mixed"]
MediaKind = Literal["none", "photograph", "illustration", "isolated_object", "screenshot_or_ui", "collage_fragments", "meme_or_reaction"]
VisualLead = Literal["type", "media", "balanced", "interface"]
Scale = Literal["small", "medium", "large", "huge"]
Density = Literal["low", "medium", "high"]
Dominance = Literal["none", "minor", "balanced", "dominant"]
Align = Literal["left", "center", "right", "mixed"]

SCALE_ORDER = ("small", "medium", "large", "huge")
DENSITY_ORDER = ("low", "medium", "high")
DOMINANCE_ORDER = ("none", "minor", "balanced", "dominant")

_TEXT = Field(min_length=1, max_length=600)

# Copy / product names visible on the board: DNA guidance quoting them would be copying, not learning.
_REFERENCE_LITERALS = (
    "gpt-5", "mac studio", "airpods", "iphone 16", "ios 18", "human not found", "watch series", "нового поколения",
    "новости коротко", "когда сказали", "apple event", "nvidia", "chatgpt", "claude", "gemini", "rtx",
)
_FORBIDDEN = (
    (re.compile(r"#[0-9a-fA-F]{3,8}\b"), "hex colour"),
    (re.compile(r"\b\d{2,4}\s?px\b", re.IGNORECASE), "pixel size"),
    (re.compile(r"\b[xy]\s*=\s*\d", re.IGNORECASE), "explicit coordinate"),
    (re.compile(r"\(\s*\d{2,4}\s*,\s*\d{2,4}\s*\)"), "coordinate pair"),
)


class SampleAnalysis(BaseModel):
    """One reference sample (S01..), observable mechanics only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str = Field(pattern=r"^S\d{2}$")
    surface_tone: SurfaceTone
    visual_lead: VisualLead
    headline_scale: Scale
    body_scale: Scale
    text_block_width: Literal["narrow", "medium", "wide"]
    alignment: Align
    type_is_main_visual_object: bool
    media_kind: MediaKind
    media_region_count: int = Field(ge=0, le=12)
    media_dominance: Dominance
    density: Density
    symmetry: Literal["symmetric", "asymmetric"]
    crop_and_media_relation: str = _TEXT
    spatial_composition: str = _TEXT
    graphic_devices: list[str] = Field(max_length=8)
    accent_use: str = _TEXT
    visual_tension: str = _TEXT


class VisualFamily(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    name: str = Field(min_length=1, max_length=80)
    member_samples: list[str] = Field(min_length=1, max_length=20)
    visual_intent: str = _TEXT
    allowed_surfaces: list[SurfaceTone] = Field(min_length=1, max_length=4)
    preferred_visual_weight: VisualLead
    density_min: Density
    density_max: Density
    headline_scale_min: Scale
    headline_scale_max: Scale
    media_regions_min: int = Field(ge=0, le=12)
    media_regions_max: int = Field(ge=0, le=12)
    media_dominance_min: Dominance
    media_dominance_max: Dominance
    allowed_media_behaviors: list[str] = Field(min_length=1, max_length=8)
    spatial_tendencies: list[str] = Field(min_length=1, max_length=8)
    graphic_devices: list[str] = Field(max_length=8)
    negative_space_behavior: str = _TEXT
    accent_behavior: str = _TEXT
    dark_surface_allowed: bool
    image_overlay_allowed: Literal[False] = False
    compatible_content_behaviors: list[str] = Field(min_length=1, max_length=8)
    what_makes_it_distinct: str = _TEXT
    anti_patterns: list[str] = Field(min_length=1, max_length=8)
    when_not_to_use: str = _TEXT

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> "VisualFamily":
        if DENSITY_ORDER.index(self.density_min) > DENSITY_ORDER.index(self.density_max):
            raise ValueError("density_min above density_max")
        if SCALE_ORDER.index(self.headline_scale_min) > SCALE_ORDER.index(self.headline_scale_max):
            raise ValueError("headline_scale_min above headline_scale_max")
        if DOMINANCE_ORDER.index(self.media_dominance_min) > DOMINANCE_ORDER.index(self.media_dominance_max):
            raise ValueError("media_dominance_min above media_dominance_max")
        if self.media_regions_min > self.media_regions_max:
            raise ValueError("media_regions_min above media_regions_max")
        return self


class InstagramVisualDNAV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    reference_path: str
    reference_sha256: str
    analysis_prompt_version: str
    analysis_model: str | None = None
    global_invariants: list[str] = Field(min_length=1, max_length=10)
    samples: list[SampleAnalysis] = Field(min_length=2, max_length=40)
    families: list[VisualFamily] = Field(min_length=1, max_length=10)
    contradictions_kept_distinct: list[str] = Field(default_factory=list, max_length=10)
    must_not_copy: list[str] = Field(min_length=1, max_length=10)
    originality_constraints: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _membership_is_real(self) -> "InstagramVisualDNAV2":
        known = {s.sample_id for s in self.samples}
        if len(known) != len(self.samples):
            raise ValueError("duplicate sample ids")
        for family in self.families:
            unknown = [m for m in family.member_samples if m not in known]
            if unknown:
                raise ValueError(f"family {family.family_id} references unanalysed samples {unknown}")
        if len({f.family_id for f in self.families}) != len(self.families):
            raise ValueError("duplicate family ids")
        return self


def family_mix(dna: InstagramVisualDNAV2) -> dict[str, dict]:
    """Observable sample membership per family (counts, not a score)."""
    total = len(dna.samples)
    return {f.family_id: {"name": f.name, "samples": list(f.member_samples), "count": len(f.member_samples), "of": total} for f in dna.families}


def surface_mix(dna: InstagramVisualDNAV2) -> Counter:
    return Counter(s.surface_tone for s in dna.samples)


def _guidance_texts(dna: InstagramVisualDNAV2) -> list[str]:
    texts = list(dna.global_invariants) + list(dna.contradictions_kept_distinct)
    for f in dna.families:
        texts += [
            f.name, f.visual_intent, f.negative_space_behavior, f.accent_behavior, f.what_makes_it_distinct, f.when_not_to_use,
            *f.allowed_media_behaviors, *f.spatial_tendencies, *f.graphic_devices, *f.compatible_content_behaviors, *f.anti_patterns,
        ]
    return texts


def assert_v2_mechanics_only(dna: InstagramVisualDNAV2) -> None:
    """Guidance (families + invariants) must not quote reference copy; ALL text must be free of
    coordinates, hex colours and pixel sizes. must_not_copy is mandatory."""
    for text in _guidance_texts(dna):
        lowered = text.lower()
        for literal in _REFERENCE_LITERALS:
            if literal in lowered:
                raise VisualDnaOriginalityError(f"DNA v2 guidance quotes reference copy {literal!r}: {text!r}")
    every = _guidance_texts(dna) + [
        t for s in dna.samples for t in (s.crop_and_media_relation, s.spatial_composition, s.accent_use, s.visual_tension, *s.graphic_devices)
    ]
    for text in every:
        for pattern, label in _FORBIDDEN:
            if pattern.search(text):
                raise VisualDnaOriginalityError(f"DNA v2 text contains a {label}: {text!r}")
    if not dna.must_not_copy:
        raise VisualDnaOriginalityError("must_not_copy is mandatory")


def load_visual_dna_v2(*, directory: Path = DNA_DIR) -> InstagramVisualDNAV2 | None:
    path = directory / "v2.json"
    if not path.exists():
        return None
    dna = InstagramVisualDNAV2.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert_v2_mechanics_only(dna)
    return dna


# The stored DNA v2 predates the bounded output vocabulary; the model must see (and emit) the PUBLIC family ids (schemas.instagram_creative.VISUAL_FAMILIES).
PUBLIC_FAMILY_IDS = {"culture_collage": "internet_culture_collage"}


def public_family_id(family_id: str) -> str:
    return PUBLIC_FAMILY_IDS.get(family_id, family_id)


def render_visual_dna_v2_context(dna: InstagramVisualDNAV2) -> str:
    """Structured text for the Creative Director: invariants + the family library. Not a template:
    families are mechanics, geometry is chosen per slide."""
    lines = [
        f"VISUAL DNA v{dna.version} - {len(dna.families)} visual families read sample-by-sample from the founder reference "
        f"({len(dna.samples)} samples). Families are mechanics, never fixed layouts; pick a family per post from the content, "
        "then vary geometry per slide.",
        "GLOBAL INVARIANTS:",
        *(f"- {i}" for i in dna.global_invariants),
    ]
    for f in dna.families:
        lines += [
            f"FAMILY {public_family_id(f.family_id)} - {f.name} ({len(f.member_samples)} of {len(dna.samples)} reference samples)",
            f"  intent: {f.visual_intent}",
            f"  surfaces: {', '.join(f.allowed_surfaces)} | lead: {f.preferred_visual_weight} | density: {f.density_min}-{f.density_max} | "
            f"headline scale: {f.headline_scale_min}-{f.headline_scale_max} | media regions: {f.media_regions_min}-{f.media_regions_max} | "
            f"media dominance: {f.media_dominance_min}-{f.media_dominance_max}",
            f"  media: {'; '.join(f.allowed_media_behaviors)}",
            f"  spatial: {'; '.join(f.spatial_tendencies)}",
            f"  devices: {'; '.join(f.graphic_devices) or 'none'}",
            f"  negative space: {f.negative_space_behavior}",
            f"  accent: {f.accent_behavior}",
            f"  distinct: {f.what_makes_it_distinct}",
            f"  avoid: {'; '.join(f.anti_patterns)} | not for: {f.when_not_to_use}",
        ]
    if dna.contradictions_kept_distinct:
        lines += ["CONTRADICTORY MODES KEPT DISTINCT (never average them):", *(f"- {c}" for c in dna.contradictions_kept_distinct)]
    lines += [
        "RENDERER CONSTRAINTS (override any rule above that conflicts): NO overlays, scrims, dimming, tints or blur - source images are "
        "always shown unaltered. Dark design = a SOLID designed surface with an independent media object; contrast comes from surface, "
        "placement and scale.",
        "MUST NOT COPY:", *(f"- {i}" for i in dna.must_not_copy),
        "ORIGINALITY:", *(f"- {i}" for i in dna.originality_constraints),
    ]
    return "\n".join(lines)


def render_visual_dna_v2_markdown(dna: InstagramVisualDNAV2) -> str:
    mix = family_mix(dna)
    surfaces = surface_mix(dna)
    out = [
        f"# Instagram Visual DNA v{dna.version}", "",
        f"- reference: `{dna.reference_path}` (sha256 `{dna.reference_sha256}`)",
        f"- analysis: prompt `instagram_reference_analysis` v{dna.analysis_prompt_version}; model `{dna.analysis_model}`",
        f"- samples analysed: {len(dna.samples)}; surface mix: " + ", ".join(f"{k} {v}" for k, v in sorted(surfaces.items())),
        "", "## Global invariants", *(f"- {i}" for i in dna.global_invariants), "", "## Family mix (sample membership)",
        *(f"- **{m['name']}** (`{fid}`): {m['count']} of {m['of']} - {', '.join(m['samples'])}" for fid, m in mix.items()), "",
    ]
    for f in dna.families:
        out += [
            f"## {f.name} (`{f.family_id}`)", f"- members: {', '.join(f.member_samples)}", f"- intent: {f.visual_intent}",
            f"- surfaces: {', '.join(f.allowed_surfaces)}; dark surface allowed: {f.dark_surface_allowed}; image overlay allowed: False",
            f"- lead: {f.preferred_visual_weight}; density {f.density_min}-{f.density_max}; headline scale {f.headline_scale_min}-{f.headline_scale_max}",
            f"- media: {f.media_regions_min}-{f.media_regions_max} regions; dominance {f.media_dominance_min}-{f.media_dominance_max}; " + "; ".join(f.allowed_media_behaviors),
            "- spatial: " + "; ".join(f.spatial_tendencies), "- devices: " + ("; ".join(f.graphic_devices) or "none"),
            f"- negative space: {f.negative_space_behavior}", f"- accent: {f.accent_behavior}",
            f"- distinct: {f.what_makes_it_distinct}", "- anti-patterns: " + "; ".join(f.anti_patterns), f"- not for: {f.when_not_to_use}", "",
        ]
    if dna.contradictions_kept_distinct:
        out += ["## Contradictory modes kept distinct", *(f"- {c}" for c in dna.contradictions_kept_distinct), ""]
    out += ["## Must not copy", *(f"- {i}" for i in dna.must_not_copy), "", "## Originality constraints", *(f"- {i}" for i in dna.originality_constraints), "",
            "## Sample evidence (internal review)"]
    for s in dna.samples:
        out.append(
            f"- **{s.sample_id}** surface={s.surface_tone} lead={s.visual_lead} headline={s.headline_scale} density={s.density} "
            f"media={s.media_kind}x{s.media_region_count}/{s.media_dominance} align={s.alignment}; {s.spatial_composition}"
        )
    return "\n".join(out)
