"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 15: an Instagram-specific VisualSpec/evidence
description. Deliberately NOT a `database/models/design_spec_version.py::DesignSpecVersion` row
and NOT a `schemas/declarative_visual_parameters.py::DeclarativeVisualParameters` instance - that
schema/registry pair is Telegram's own production VisualSpec architecture (`design_spec_registry.py`
only ever creates `telegram_*` scopes); this phase does NOT activate anything in production
(section 15's own explicit instruction) and does not extend that production schema.

This is a plain, local, non-persisted dataclass that truthfully describes what
`services/instagram_platform_renderer.py` actually does - `platform` is always `"instagram"`, the
canvas geometry comes from `services/instagram_visual_profiles.py` (Instagram's OWN aspect ratios,
never a borrowed Telegram assumption), and `matches_evidence()` only asserts things the renderer can
actually prove (no fake hard constraint like an exact text-region count, which is content-length
dependent)."""
from __future__ import annotations

from dataclasses import dataclass

from services.instagram_render_evidence import InstagramRenderEvidence
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

PLATFORM = "instagram"


@dataclass(frozen=True)
class InstagramVisualSpec:
    platform: str
    content_format: str
    profile: str
    canvas_width: int
    canvas_height: int
    aspect: float
    required_brand_marks: int  # exactly this many, never more, never fewer
    headline_clip_allowed: bool  # a spec-level policy: this renderer's own contract never allows it

    def matches_evidence(self, evidence: InstagramRenderEvidence) -> list[str]:
        """Returns a list of violated constraints (empty = PASS). Every check here is something the
        renderer's own evidence can truthfully answer - no aspirational field the current renderer
        cannot measure."""
        violations: list[str] = []
        if self.platform != PLATFORM:
            violations.append(f"spec platform {self.platform!r} is not 'instagram'")
        if evidence.content_format != self.content_format:
            violations.append(f"content_format mismatch: spec={self.content_format!r} evidence={evidence.content_format!r}")
        if evidence.profile != self.profile:
            violations.append(f"profile mismatch: spec={self.profile!r} evidence={evidence.profile!r}")
        if (evidence.canvas_width, evidence.canvas_height) != (self.canvas_width, self.canvas_height):
            violations.append(
                f"canvas mismatch: spec={self.canvas_width}x{self.canvas_height} evidence={evidence.canvas_width}x{evidence.canvas_height}"
            )
        if evidence.visible_brand_mark_count != self.required_brand_marks:
            violations.append(f"brand_mark_count mismatch: spec requires {self.required_brand_marks}, evidence={evidence.visible_brand_mark_count}")
        if not self.headline_clip_allowed:
            headline_clipped = any(t.clipped for t in evidence.text_regions if t.kind == "headline")
            if headline_clipped:
                violations.append("headline_clip_allowed=false but evidence reports a clipped headline")
        return violations


_FORMAT_PROFILE = {
    "single": InstagramRenderProfile.PORTRAIT_FEED,
    "carousel": InstagramRenderProfile.CAROUSEL_SLIDE,
    "reel": InstagramRenderProfile.REEL_COVER,
}


def default_instagram_visual_spec(content_format: str) -> InstagramVisualSpec:
    """The ONE local candidate spec per format, derived directly from
    `services/instagram_visual_profiles.py` - never a hand-typed duplicate of those numbers."""
    profile = _FORMAT_PROFILE[content_format]
    spec = profile_spec(profile)
    return InstagramVisualSpec(
        platform=PLATFORM, content_format=content_format, profile=profile.value,
        canvas_width=spec.width, canvas_height=spec.height, aspect=spec.aspect,
        required_brand_marks=1, headline_clip_allowed=False,
    )
