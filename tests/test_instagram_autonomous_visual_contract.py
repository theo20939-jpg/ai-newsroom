from PIL import Image

import pytest

from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative
from services.instagram_brand_anchor import (
    BrandAnchorDecision,
    BrandAnchorPlacementError,
    place_brand_anchor_in_carousel,
    reserve_brand_anchor_row,
)
from services.instagram_creative_media import (
    InstagramCreativeMediaResult,
    InstagramMediaExecutionAsset,
    InstagramMediaMode,
    media_first_carousel_hold_reason,
)
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec


def _creative(sources: list[str]) -> InstagramCarouselCreative:
    return InstagramCarouselCreative(
        objective="reach",
        slides=[
            InstagramCarouselSlideCreative(
                role="hook" if i == 0 else ("takeaway" if i == len(sources) - 1 else "context"),
                slide_copy=f"Slide {i + 1}", visual_direction="one concrete visual scene",
                media_source=source,
            )
            for i, source in enumerate(sources)
        ],
    )


def _asset(index: int, mode: InstagramMediaMode, *, pixels: bool = True, persisted: bool = True):
    return InstagramMediaExecutionAsset(
        asset_key=str(index), media_mode=mode,
        status="generated_media" if pixels else mode.value.lower(),
        image=Image.new("RGB", (32, 32), (index * 20, 40, 80)) if pixels else None,
        asset_ref=f"generated:slide-{index}.png" if pixels and persisted else None,
        generated_asset_ref=f"generated:slide-{index}.png" if pixels and persisted else None,
        asset_identity=f"identity-{index}" if pixels and persisted else None,
    )


def _result(assets) -> InstagramCreativeMediaResult:
    return InstagramCreativeMediaResult(
        status="media_plan_ready", image=None, media_ref=None, media_strategy="generated_media", assets=tuple(assets),
    )


def test_five_visual_assets_and_one_intentional_graphic_rhythm_slide_are_legal():
    creative = _creative(["generated"] * 5 + ["graphic"])
    assets = [_asset(i, InstagramMediaMode.GENERATED) for i in range(5)] + [
        _asset(5, InstagramMediaMode.GRAPHIC, pixels=False)
    ]
    assert media_first_carousel_hold_reason(creative, _result(assets)) is None


def test_multiple_assetless_graphic_slides_hold_before_delivery():
    creative = _creative(["generated"] * 4 + ["graphic", "graphic"])
    assets = [_asset(i, InstagramMediaMode.GENERATED) for i in range(4)] + [
        _asset(4, InstagramMediaMode.GRAPHIC, pixels=False),
        _asset(5, InstagramMediaMode.GRAPHIC, pixels=False),
    ]
    assert media_first_carousel_hold_reason(creative, _result(assets)) == "too_many_nonvisual_slides:5,6"


def test_required_generated_media_failure_is_never_reclassified_as_the_rhythm_slide():
    creative = _creative(["generated"] * 6)
    assets = [_asset(i, InstagramMediaMode.GENERATED) for i in range(5)] + [
        _asset(5, InstagramMediaMode.GENERATED, pixels=False)
    ]
    assert media_first_carousel_hold_reason(creative, _result(assets)) == "slide_6_required_media_missing:generated"


def test_pixels_without_persisted_ref_or_identity_hold_before_delivery():
    creative = _creative(["generated"] * 6)
    assets = [_asset(i, InstagramMediaMode.GENERATED) for i in range(6)]
    assets[2] = _asset(2, InstagramMediaMode.GENERATED, persisted=False)
    assert media_first_carousel_hold_reason(creative, _result(assets)) == "slide_3_visual_not_persisted"


def _layout(*boxes: tuple[int, int, int, int]) -> LayoutResult:
    return LayoutResult(
        image=Image.new("RGB", (1080, 1350), "#111111"),
        text_regions=[TextRegionSpec(kind="headline", box=box, clipped=False) for box in boxes],
        visible_brand_mark_count=1, source_image_treatment="none", layout_variant="test",
        text_clipped=False, notes={},
    )


def _ready() -> BrandAnchorDecision:
    return BrandAnchorDecision(
        status="READY", identity="google_gemini", label="GOOGLE · GEMINI",
        asset_kind="deterministic_text", asset_source="renderer_text_fallback",
    )


def test_brand_row_reservation_moves_the_cover_text_system_as_one_block():
    plan = {"regions": [
        {"kind": "text", "y": 0.04, "h": 0.18},
        {"kind": "text", "y": 0.42, "h": 0.20},
        {"kind": "media", "y": 0.0, "h": 1.0},
    ]}
    reserved, changed = reserve_brand_anchor_row(plan, _ready())
    assert changed and [r["y"] for r in reserved["regions"][:2]] == [0.14, 0.52]
    assert reserved["regions"][2]["y"] == 0.0


def test_both_cover_top_zones_occupied_falls_back_to_the_earliest_later_slide():
    cover = _layout((40, 35, 520, 150), (560, 35, 1040, 150))
    later = _layout((64, 300, 900, 700))
    placed = place_brand_anchor_in_carousel([cover, later], _ready())
    assert placed[0].notes["product_brand_anchor"]["status"] == "BRAND_ANCHOR_UNPLACED"
    assert placed[1].notes["product_brand_anchor"]["status"] == "DRAWN_ON_FALLBACK_SLIDE"
    assert sum(any(r.kind == "product_brand_anchor" for r in layout.text_regions) for layout in placed) == 1
    assert all(layout.visible_brand_mark_count == 1 for layout in placed)


def test_ready_brand_never_silently_disappears_when_every_slide_is_occupied():
    occupied = _layout((40, 35, 520, 150), (560, 35, 1040, 150))
    with pytest.raises(BrandAnchorPlacementError):
        place_brand_anchor_in_carousel([occupied, occupied], _ready())
