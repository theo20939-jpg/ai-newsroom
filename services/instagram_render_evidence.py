"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 9: `InstagramRenderEvidence` - the truthful,
renderer-produced record of what `services/instagram_platform_renderer.py` actually did for one
rendered asset. Deliberately a STANDALONE dataclass, not a reuse of
`services/render_evidence.py::RenderEvidence` - that type's vocabulary (`logo_zone` as one of four
Telegram corner names, `placement_zone`, `scrim_treatment`) encodes Telegram-renderer assumptions
this phase's own instruction (section 13) says not to force onto Instagram. Every field here is
something the Instagram renderer can truthfully measure about its OWN output, nothing borrowed."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RENDER_VERSION = "instagram-render-v1"


@dataclass(frozen=True)
class TextRegion:
    """One measured text block's bounding box, in canvas pixels."""

    kind: str  # "headline" | "caption_overlay" | "cta"
    box: tuple[int, int, int, int]  # (x0, y0, x1, y1)
    clipped: bool


@dataclass(frozen=True)
class InstagramRenderEvidence:
    render_version: str
    content_format: str
    profile: str
    canvas_width: int
    canvas_height: int
    visible_brand_mark_count: int
    text_regions: list[TextRegion] = field(default_factory=list)
    text_clipped: bool = False
    source_image_treatment: str = "none"  # "none" | "preserve" | "crop" | "generated"
    slide_index: int | None = None
    slide_count: int | None = None
    caption_linkage: str = ""  # the package_id this render was produced for
    content_identity: str = ""  # a stable hash of the package's own content (never of pixels)
    # INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7/§10: the SAME `media_candidate_id` the package
    # that requested this render carried - the renderer's own honest declaration of which selected
    # candidate its `source_image_treatment` pixels actually came from. `None` for a render that
    # used no real source image (`source_image_treatment="none"`/"generated") - never fabricated
    # for a render that genuinely did not consume a real, unified-verified candidate.
    source_media_candidate_id: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "render_version": self.render_version,
            "content_format": self.content_format,
            "profile": self.profile,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "visible_brand_mark_count": self.visible_brand_mark_count,
            "text_regions": [
                {"kind": t.kind, "box": list(t.box), "clipped": t.clipped} for t in self.text_regions
            ],
            "text_clipped": self.text_clipped,
            "source_image_treatment": self.source_image_treatment,
            "slide_index": self.slide_index,
            "slide_count": self.slide_count,
            "caption_linkage": self.caption_linkage,
            "content_identity": self.content_identity,
            "source_media_candidate_id": self.source_media_candidate_id,
            "notes": self.notes,
        }
