"""Deterministic, evidence-bound product/brand anchors for Instagram carousels.

The image model never sees or draws these anchors.  A cover anchor is added only when the hook
names a supported company/product and the same identity is corroborated by the Director's stored
story evidence.  Verified raster/vector assets may be added to the closed registry later; until
then the safe fallback is a small deterministic text chip, never a reconstructed logo.
"""
from __future__ import annotations

import re
from hashlib import sha256
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Pattern

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_content_package import InstagramContentPackage
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_visual_profiles import ig_font


@dataclass(frozen=True)
class BrandIdentity:
    key: str
    label: str
    company_pattern: Pattern[str]
    product_pattern: Pattern[str] | None = None
    verified_asset_path: str | None = None
    verified_asset_sha256: str | None = None


@dataclass(frozen=True)
class BrandAnchorDecision:
    status: str
    identity: str | None = None
    label: str | None = None
    asset_kind: str | None = None
    asset_source: str | None = None
    asset_sha256: str | None = None
    reason: str | None = None


class BrandAnchorPlacementError(ValueError):
    pass


_IDENTITIES = (
    BrandIdentity("google_gemini", "GOOGLE · GEMINI", re.compile(r"\bgoogle\b", re.I), re.compile(r"\bgemini(?:\s+\d+(?:\.\d+)*(?:\s+[a-z][\w-]*)?)?\b", re.I)),
    BrandIdentity(
        "openai", "OPENAI", re.compile(r"\bopenai\b", re.I),
        re.compile(r"\b(?:chatgpt|gpt[-\s]?\d+(?:\.\d+)*|sora)\b", re.I),
        "assets/brand/subjects/openai/OAI_OpenAI_Wordmark_White.png",
        "c2a4b58c101ea5b5dbfc23561371da8b5aac9090aa3c2b09f1a9d9cdc6b508c5",
    ),
    BrandIdentity("apple", "APPLE", re.compile(r"\bapple\b", re.I), re.compile(r"\b(?:iphone|ipad|macbook|vision\s+pro)\b", re.I)),
    BrandIdentity("samsung", "SAMSUNG", re.compile(r"\bsamsung\b", re.I), re.compile(r"\bgalaxy(?:\s+[a-z]\d+)?\b", re.I)),
)


def _story_evidence(package: InstagramContentPackage) -> tuple[str, str]:
    evidence = package.director_evidence if isinstance(package.director_evidence, dict) else {}
    decision = evidence.get("editorial_decision") if isinstance(evidence.get("editorial_decision"), dict) else {}
    subject = " ".join(str(decision.get(key) or "") for key in ("topic", "source_summary", "angle"))
    stored = " ".join(str(item) for item in (evidence.get("evidence") or []) if item)
    return subject, stored


def resolve_brand_anchor(package: InstagramContentPackage) -> BrandAnchorDecision:
    """Return one conservative cover-anchor decision; incidental company mentions fail closed."""
    slides = package.media_plan.get("slides") if isinstance(package.media_plan, dict) else None
    if not isinstance(slides, list) or not slides:
        return BrandAnchorDecision(status="NOT_APPLICABLE", reason="not a carousel with a hook slide")
    cover = slides[0] if isinstance(slides[0], dict) else {}
    hook = " ".join(str(cover.get(key) or "") for key in ("text", "body"))
    subject, evidence = _story_evidence(package)
    for identity in _IDENTITIES:
        product_in_hook = bool(identity.product_pattern and identity.product_pattern.search(hook))
        product_supported = bool(identity.product_pattern and identity.product_pattern.search(f"{subject} {evidence}"))
        company_is_subject = bool(
            identity.company_pattern.search(hook)
            and identity.company_pattern.search(subject)
            and identity.company_pattern.search(evidence)
        )
        if not ((product_in_hook and product_supported) or company_is_subject):
            continue
        if identity.verified_asset_path:
            return BrandAnchorDecision(
                status="READY", identity=identity.key, label=identity.label, asset_kind="verified_asset",
                asset_source=identity.verified_asset_path, asset_sha256=identity.verified_asset_sha256,
                reason="hook identity corroborated by stored story evidence",
            )
        return BrandAnchorDecision(
            status="READY", identity=identity.key, label=identity.label, asset_kind="deterministic_text",
            asset_source="renderer_text_fallback", reason="hook identity corroborated; BRAND_ASSET_MISSING",
        )
    return BrandAnchorDecision(status="NOT_APPLICABLE", reason="no supported hook identity corroborated by stored story evidence")


def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int], *, pad: int = 12) -> bool:
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def apply_brand_anchor(layout: LayoutResult, decision: BrandAnchorDecision) -> LayoutResult:
    """Add one secondary verified wordmark or text chip without changing the canonical KAGE mark count."""
    if decision.status != "READY" or not decision.label:
        notes = {**layout.notes, "product_brand_anchor": decision.__dict__}
        return replace(layout, notes=notes)
    canvas = layout.image.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    chip_h = 58
    asset: Image.Image | None = None
    asset_error: str | None = None
    if decision.asset_kind == "verified_asset" and decision.asset_source:
        path = Path(__file__).resolve().parents[1] / decision.asset_source
        try:
            data = path.read_bytes()
            digest = sha256(data).hexdigest()
            if decision.asset_sha256 and digest != decision.asset_sha256:
                raise ValueError("verified asset checksum mismatch")
            asset = Image.open(path).convert("RGBA")
            target_h = 50
            asset = asset.resize((round(asset.width * target_h / asset.height), target_h), Image.Resampling.LANCZOS)
            chip_h = 68
            chip_w = asset.width + 24
        except (OSError, ValueError) as exc:
            asset_error = type(exc).__name__
    if asset is None:
        font = ig_font(34, "semibold")
        text_box = draw.textbbox((0, 0), decision.label, font=font)
        text_width = text_box[2] - text_box[0]
        chip_w = text_width + 64
    margin_x, margin_y = 64, 56
    candidates = (
        (margin_x, margin_y, margin_x + chip_w, margin_y + chip_h),
        (canvas.width - margin_x - chip_w, margin_y, canvas.width - margin_x, margin_y + chip_h),
    )
    occupied = [region.box for region in layout.text_regions]
    chip = next((box for box in candidates if not any(_intersects(box, other) for other in occupied)), None)
    if chip is None:
        failed = BrandAnchorDecision(**{**decision.__dict__, "status": "BRAND_ANCHOR_UNPLACED", "reason": "no collision-free cover safe zone"})
        return replace(layout, notes={**layout.notes, "product_brand_anchor": failed.__dict__})

    radius = 14
    draw.rounded_rectangle(chip, radius=radius, fill=(*tok.INK, 224), outline=(*tok.GREY_STRONG, 150), width=2)
    if asset is not None:
        canvas.alpha_composite(asset, (chip[0] + 12, chip[1] + (chip_h - asset.height) // 2))
    else:
        draw.rounded_rectangle((chip[0], chip[1], chip[0] + 9, chip[3]), radius=4, fill=(*tok.RED, 255))
        text_y = chip[1] + (chip_h - (text_box[3] - text_box[1])) // 2 - text_box[1]
        draw.text((chip[0] + 35, text_y), decision.label, font=font, fill=(*tok.WHITE, 255))
    region = TextRegionSpec(kind="product_brand_anchor", box=chip, clipped=False)
    notes = {
        **layout.notes,
        "product_brand_anchor": {
            **decision.__dict__,
            "status": "DRAWN_ON_COVER",
            "asset_kind": "verified_asset" if asset is not None else "deterministic_text",
            "asset_fallback_reason": None if asset is not None else asset_error,
            "placement": "TOP_LEFT" if chip == candidates[0] else "TOP_RIGHT",
        },
    }
    return replace(layout, image=canvas.convert("RGB"), text_regions=[*layout.text_regions, region], notes=notes)


def reserve_brand_anchor_row(layout_plan: dict | None, decision: BrandAnchorDecision) -> tuple[dict | None, bool]:
    """Reserve a small cover eyebrow row before layout execution.

    Declarative coordinates are normalized. The whole cover text system moves by one deterministic
    delta, preserving its internal spacing; if that would invade the KAGE footer zone, the plan is
    left alone and carousel-level fallback placement handles it.
    """
    if decision.status != "READY" or not isinstance(layout_plan, dict):
        return layout_plan, False
    plan = deepcopy(layout_plan)
    text = [r for r in plan.get("regions") or [] if r.get("kind") == "text"]
    if not text:
        return layout_plan, False
    top = min(float(r.get("y") or 0) for r in text)
    reserved_bottom = 0.14
    if top >= reserved_bottom:
        return plan, True
    delta = reserved_bottom - top
    if max(float(r.get("y") or 0) + float(r.get("h") or 0) + delta for r in text) > 0.91:
        return layout_plan, False
    for region in text:
        region["y"] = round(float(region.get("y") or 0) + delta, 4)
    return plan, True


def mark_fallback_anchor(layout: LayoutResult) -> LayoutResult:
    anchor = dict(layout.notes.get("product_brand_anchor") or {})
    if anchor.get("status") != "DRAWN_ON_COVER":
        return layout
    anchor["status"] = "DRAWN_ON_FALLBACK_SLIDE"
    return replace(layout, notes={**layout.notes, "product_brand_anchor": anchor})


def place_brand_anchor_in_carousel(
    layouts: list[LayoutResult], decision: BrandAnchorDecision,
) -> list[LayoutResult]:
    """Draw exactly one READY anchor: cover first, then the earliest collision-free slide."""
    if not layouts:
        return layouts
    placed = list(layouts)
    if decision.status != "READY":
        placed[0] = apply_brand_anchor(placed[0], decision)
        for layout in placed[1:]:
            layout.notes["product_brand_anchor"] = {
                "status": "NOT_APPLICABLE", "identity": decision.identity, "reason": decision.reason,
            }
        return placed

    placed[0] = apply_brand_anchor(placed[0], decision)
    drawn = placed[0].notes.get("product_brand_anchor", {}).get("status") == "DRAWN_ON_COVER"
    if not drawn:
        for index in range(1, len(placed)):
            candidate = apply_brand_anchor(placed[index], decision)
            if candidate.notes.get("product_brand_anchor", {}).get("status") == "DRAWN_ON_COVER":
                placed[index] = mark_fallback_anchor(candidate)
                drawn = True
                break
    if not drawn:
        raise BrandAnchorPlacementError("READY product brand anchor has no collision-free carousel placement")
    for layout in placed:
        if "product_brand_anchor" not in layout.notes:
            layout.notes["product_brand_anchor"] = {
                "status": "NOT_PRIMARY_SLIDE", "identity": decision.identity,
                "reason": "one primary subject-brand anchor already drawn",
            }
    return placed
