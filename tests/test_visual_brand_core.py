"""VISUAL-DESIGN-AUTONOMY-1, spec §66: VisualBrandCore tests - a prompt asking to draw/recreate
the NNJ logo is rejected, a restricted claim in a prompt is rejected, a normal creative prompt with
neither passes clean."""
from __future__ import annotations

from services.visual_brand_core import check_creative_prompt_against_brand_core


def test_prompt_asking_to_draw_logo_is_rejected() -> None:
    result = check_creative_prompt_against_brand_core(
        "A dramatic scene with the NNJ logo rendered prominently in the top corner."
    )
    assert not result.compliant
    assert any("logo" in v.detail.lower() for v in result.violations)


def test_prompt_asking_to_include_watermark_is_rejected() -> None:
    result = check_creative_prompt_against_brand_core("Draw a watermark in the bottom right corner.")
    assert not result.compliant


def test_restricted_claim_in_prompt_is_rejected() -> None:
    result = check_creative_prompt_against_brand_core(
        "A photo showcasing the unreleased Pro model.", restricted_claims=["unreleased Pro model"],
    )
    assert not result.compliant


def test_ordinary_creative_prompt_is_compliant() -> None:
    result = check_creative_prompt_against_brand_core(
        "A wide cinematic shot of a city skyline at dusk, cool blue tones, dramatic rim lighting.",
        restricted_claims=["unreleased Pro model"],
    )
    assert result.compliant
    assert result.violations == []
