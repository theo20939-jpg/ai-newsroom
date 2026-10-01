"""A carousel of generated pictures has a deliberate visual rhythm - not one full-bleed + bottom-text template repeated."""
from __future__ import annotations

import pytest

from schemas.instagram_creative import InstagramSlideLayout
from services.instagram_generated_fallback import FRAMED, HERO, SPLIT_TOP, TEXT_FIRST, hero_layout, rhythm_mode
from services.instagram_layout_validation import compose_slide_text, validate_layout
from services.instagram_layout_signature import layout_signature

SHORT = ("Claude — это не одна модель", "Haiku — самая маленькая. Opus — самая большая.")
LONG = ("Сначала обновили Opus. Теперь — Sonnet", "x" * 140)


def _modes(total: int, copies=None) -> list[str]:
    copies = copies or [SHORT] * total
    return [rhythm_mode(i, total, headline=copies[i][0], body=copies[i][1],
                        previous_headline=copies[i - 1][0] if i else "", previous_body=copies[i - 1][1] if i else "") for i in range(total)]


def test_hook_is_the_full_bleed_hero_and_the_next_slide_is_not() -> None:
    modes = _modes(5)
    assert modes[0] == HERO and modes[1] != HERO


@pytest.mark.parametrize("total", [4, 5, 6])
def test_normal_carousel_uses_at_least_three_distinct_modes_and_no_adjacent_repeat(total: int) -> None:
    modes = _modes(total)
    assert len(set(modes)) >= 3
    assert all(a != b for a, b in zip(modes, modes[1:]))


def test_long_copy_never_gets_a_hero() -> None:
    modes = _modes(5, [SHORT, SHORT, SHORT, LONG, SHORT])
    assert modes[3] != HERO


def test_every_mode_layout_is_valid_and_geometrically_distinct() -> None:
    signatures = set()
    for mode in (HERO, FRAMED, TEXT_FIRST, SPLIT_TOP):
        layout = InstagramSlideLayout.model_validate(hero_layout({}, "generated", mode=mode))
        validated = validate_layout(layout, slide_copy=compose_slide_text(*SHORT), resolvable_subjects={"generated"})
        assert validated.accepted, (mode, validated.rejection_codes)
        signatures.add(layout_signature(layout.model_dump()))
    assert len(signatures) >= 3


def test_default_mode_keeps_the_existing_hero_geometry() -> None:
    base = hero_layout({}, "generated")
    media = [r for r in base["regions"] if r["kind"] == "media"][0]
    assert (media["x"], media["y"], media["w"], media["h"]) == (0.0, 0.0, 1.0, 1.0)
