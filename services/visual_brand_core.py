"""VISUAL-DESIGN-AUTONOMY-1, spec §4: VisualBrandCore - the SMALL, immutable set of non-negotiable
visual invariants. Deliberately excludes subjective creative taste (spec §4's own "do not put
subjective creative taste into Brand Core" instruction, and "do not hardcode 'always red'/'subject
always right' unless current repository reality proves such a rule is genuinely mandatory" - a
forensic pass over services/nnj_master_news_overlay.py/services/brand_renderer.py found no such
hardcoded rule; the real repository invariant is compositional (subject-collision-aware overlay
placement), not a fixed palette or layout).

CRITICAL (spec §5): the canonical NNJ mark is never an image asset re-drawn by a generative model -
it is DETERMINISTIC PYTHON CODE (services/nnj_master_news_overlay.py::_build_upper_mark_image()/
_build_lower_signature_image(), a programmatically drawn pulse-line + wordmark, never a loaded PNG
the image model could be asked to "recreate"). This module's job is to make sure no creative prompt
ever asks the image-generation model to draw/recreate/interpret that mark, never to police pixels
after the fact (the deterministic renderer already owns that - services/brand_renderer.py/
services/nnj_master_news_overlay.py remain the final authority, spec §5's own "generated visual is
scene only; deterministic renderer owns final technical branding" split)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Spec §4's own required minimum invariant list - textual, fed verbatim into
# VisualDirectorContext (services/visual_director_context.py) so the LLM creative-direction call
# sees them as non-negotiable constraints, never as creative suggestions.
BRAND_CORE_RULES: tuple[str, ...] = (
    "Canonical NNJ branding (mark/wordmark/overlay) is applied by the deterministic production "
    "renderer AFTER generation - never ask the image model to draw, redraw, recreate, or "
    "interpret the NNJ logo/mark/wordmark.",
    "Never invent a replacement or stylized variant of NNJ branding - if brand presence in the "
    "scene itself is desired, describe clean negative space for the renderer's own overlay "
    "instead.",
    "Never alter supplied factual information: story facts, product/model names, and numbers "
    "must render exactly as supplied, never invented or approximated.",
    "Never depict or reference a restricted or embargoed product claim.",
    "Respect the renderer's safe-zone geometry - do not place the story's most important visual "
    "subject where the deterministic overlay is expected to be composited.",
    "The output must be technically suitable for the target platform and legible on a mobile "
    "screen at typical viewing size.",
)

_LOGO_REDRAW_PATTERN = re.compile(
    r"\b(ninja\s*pulse|nnj)\b.{0,40}\b(logo|wordmark|mark|watermark|brand(ing)?)\b"
    r"|\b(logo|wordmark|mark|watermark)\b.{0,40}\b(draw|render|generate|recreate|redraw|include)\b"
    r"|\b(draw|render|generate|recreate|redraw|include)\w*\b.{0,40}\b(logo|wordmark|watermark)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BrandCoreViolation:
    rule: str
    detail: str


def check_prompt_never_asks_to_draw_logo(prompt_text: str) -> BrandCoreViolation | None:
    """The one PROMPT-LEVEL check Brand Core can make deterministically before any generation
    call - catches a creative prompt that would ask the image model to draw/recreate NNJ
    branding itself. Post-generation pixel compliance remains the deterministic renderer's own
    job (it never lets a generated scene stand in for its own overlay output), not this
    function's."""
    match = _LOGO_REDRAW_PATTERN.search(prompt_text)
    if match is None:
        return None
    return BrandCoreViolation(
        rule=BRAND_CORE_RULES[0],
        detail=f"prompt text asks to draw/recreate branding near: {match.group(0)!r}",
    )


def check_prompt_never_names_restricted_claim(prompt_text: str, restricted_claims: list[str]) -> BrandCoreViolation | None:
    """Restricted/embargoed claim text must never appear in a generative prompt - mirrors
    services/instagram_creative_director.py's own post-generation claim re-check philosophy,
    applied here at the prompt-construction boundary instead."""
    lowered = prompt_text.lower()
    for claim in restricted_claims:
        if claim and claim.lower() in lowered:
            return BrandCoreViolation(rule=BRAND_CORE_RULES[3], detail=f"restricted claim present in prompt: {claim!r}")
    return None


@dataclass(frozen=True)
class BrandCoreCheckResult:
    violations: list[BrandCoreViolation] = field(default_factory=list)

    @property
    def compliant(self) -> bool:
        return not self.violations


def check_creative_prompt_against_brand_core(
    prompt_text: str, *, restricted_claims: list[str] | None = None,
) -> BrandCoreCheckResult:
    """The one function a caller should run against every freshly generated creative prompt
    before it is ever used to call an image model - deterministic, free, no Gateway call."""
    violations: list[BrandCoreViolation] = []
    logo_violation = check_prompt_never_asks_to_draw_logo(prompt_text)
    if logo_violation is not None:
        violations.append(logo_violation)
    claim_violation = check_prompt_never_names_restricted_claim(prompt_text, restricted_claims or [])
    if claim_violation is not None:
        violations.append(claim_violation)
    return BrandCoreCheckResult(violations=violations)


# VISUAL-DESIGN-AUTONOMY-1A §10: a candidate PERSISTENT BRIEF is a second, distinct attack surface
# from a per-post prompt - it could try to WEAKEN a Brand Core rule for every future post rather
# than merely violate it once. This pattern catches language that tries to override/remove/relax a
# safety rule, never a creative-taste choice (spec §4's own "no subjective taste in Brand Core"
# boundary is unaffected - this only ever flags an attempt to touch the immutable rules themselves).
_WEAKENING_VERBS = (
    r"ignor(?:e|ing)|overrid(?:e|ing)|disregard|bypass|relax(?:ed)?|waive[d]?|"
    r"no\s+longer\s+(?:need(?:s|ed)?|require[sd]?|applies|applicable)|"
    r"(?:is|are|be)\s+no\s+longer\s+required|not?\s+required\s+anymore|"
    r"remove[sd]?\s+the\s+requirement|no\s+restriction(?:s)?\s+on|"
    r"may\s+now\s+be\s+(?:altered|changed|approximated|shown|adjusted|redrawn)|"
    r"(?:can|may)\s+now\s+(?:be\s+)?(?:ignored|skipped|omitted)"
)
_SAFETY_SUBJECTS = r"brand\s*core|logo|wordmark|watermark|fact(?:ual|s)?|numbers?|claims?|restrict(?:ed|ions?)?|embargo(?:es)?"
_SAFETY_WEAKENING_PATTERN = re.compile(
    rf"\b(?:{_WEAKENING_VERBS})\b.{{0,60}}\b(?:{_SAFETY_SUBJECTS})\b"
    rf"|\b(?:{_SAFETY_SUBJECTS})\b.{{0,60}}\b(?:{_WEAKENING_VERBS})\b",
    re.IGNORECASE,
)


def check_brief_text_weakens_safety(brief_text: str) -> BrandCoreViolation | None:
    match = _SAFETY_WEAKENING_PATTERN.search(brief_text)
    if match is None:
        return None
    return BrandCoreViolation(
        rule="Brand Core is immutable - a candidate brief may never weaken, override, or remove a Brand Core rule.",
        detail=f"brief text appears to weaken a safety rule near: {match.group(0)!r}",
    )


def check_brief_text_against_brand_core(brief_text: str) -> BrandCoreCheckResult:
    """VISUAL-DESIGN-AUTONOMY-1A §10: the one function a caller must run against every freshly
    generated CANDIDATE brief before it is ever persisted, let alone promoted - deterministic, free,
    no Gateway call. Checks the persistent-brief-specific attack surface (attempting to weaken a
    safety rule for every future post) on top of the same logo-redraw check a per-post prompt
    already gets."""
    violations: list[BrandCoreViolation] = []
    logo_violation = check_prompt_never_asks_to_draw_logo(brief_text)
    if logo_violation is not None:
        violations.append(logo_violation)
    weakening_violation = check_brief_text_weakens_safety(brief_text)
    if weakening_violation is not None:
        violations.append(weakening_violation)
    return BrandCoreCheckResult(violations=violations)
