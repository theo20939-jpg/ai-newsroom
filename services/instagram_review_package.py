"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 12: `InstagramReviewPackage` - the real handoff
boundary between automated generation and (eventually, human/live) publication. Assembled from
already-computed upstream results only - never re-derives Director reasoning, never re-renders."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.instagram_art_validator import InstagramArtValidationResult
from services.instagram_content_package import InstagramContentPackage
from services.instagram_platform_renderer import InstagramRenderResult


@dataclass(frozen=True)
class InstagramReviewPackage:
    package_id: str
    content_format: str
    caption: str
    caption_is_draft: bool
    cta: str | None
    hashtags: list[str]

    director_reasoning_summary: str
    campaign_context: str
    source_refs: dict[str, str | None]

    media_render_evidence: list[dict[str, Any]]  # one per rendered asset (slide-ordered for carousel)

    art_validation: dict[str, Any]
    risk_warnings: list[str]
    validation_failures: list[str]
    publish_ready: bool

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id, "content_format": self.content_format, "caption": self.caption,
            "caption_is_draft": self.caption_is_draft, "cta": self.cta, "hashtags": list(self.hashtags),
            "director_reasoning_summary": self.director_reasoning_summary, "campaign_context": self.campaign_context,
            "source_refs": self.source_refs, "media_render_evidence": self.media_render_evidence,
            "art_validation": self.art_validation, "risk_warnings": list(self.risk_warnings),
            "validation_failures": list(self.validation_failures), "publish_ready": self.publish_ready,
            "created_at": self.created_at.isoformat(),
        }


def _director_reasoning_summary(package: InstagramContentPackage) -> str:
    ev = package.director_evidence
    parts = [
        f"objective={ev.get('primary_objective')}", f"format={ev.get('recommended_format')}",
        f"confidence={ev.get('confidence')}",
    ]
    if ev.get("hook_family"):
        parts.append(f"hook={ev['hook_family']}")
    if ev.get("format_decision_why"):
        parts.append(f"why={ev['format_decision_why']}")
    if ev.get("evidence"):
        parts.append("evidence=" + "; ".join(ev["evidence"]))
    return " | ".join(parts)


def build_instagram_review_package(
    *, package: InstagramContentPackage, render_results: list[InstagramRenderResult],
    art_result: InstagramArtValidationResult,
) -> InstagramReviewPackage:
    campaign_context = ", ".join(
        filter(None, [package.campaign_name, package.campaign_phase, f"campaign_id={package.campaign_id}" if package.campaign_id else None])
    ) or "no campaign context"

    return InstagramReviewPackage(
        package_id=package.package_id, content_format=package.content_format.value, caption=package.caption,
        caption_is_draft=package.caption_is_draft, cta=package.cta, hashtags=list(package.hashtags),
        director_reasoning_summary=_director_reasoning_summary(package), campaign_context=campaign_context,
        source_refs={
            "opportunity_id": package.opportunity_id, "story_id": package.story_id,
            "trend_id": package.trend_id, "campaign_id": package.campaign_id,
        },
        media_render_evidence=[r.evidence.to_dict() for r in render_results],
        art_validation=art_result.to_dict(),
        risk_warnings=list(art_result.warnings),
        validation_failures=list(art_result.blocking_issues),
        publish_ready=art_result.passed,
    )
