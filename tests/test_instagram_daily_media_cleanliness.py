"""SINGLE / REEL media cleanliness (2026-09-26 launch blocker): a source image that EXISTS is not one that must be USED.
Reproduced from the real live failures - the Habr share card (Single art-gate block `single_source_image_not_rendered`) and the vc.ru
share card (Reel cover with the source headline clipped mid-word, passed by the gate). No provider, no network, no DB: the vision step is
the real decision code answering from a fixture (scripts/_instagram_daily_media_acceptance.py)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def acceptance(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("daily_media")
    subprocess.run([sys.executable, str(ROOT / "scripts/_instagram_daily_media_acceptance.py"), str(out)],
                   check=True, capture_output=True, cwd=ROOT)
    return json.loads((out / "acceptance.json").read_text(encoding="utf-8"))


def test_the_live_single_failure_is_reproduced_by_the_legacy_package(acceptance):
    assert "single_source_image_not_rendered" in acceptance["1_single_live_failure_reproduced"]["blocking"]


def test_the_habr_share_card_is_unsuitable_and_the_director_is_told_so(acceptance):
    selection = acceptance["2_habr_classified"]
    assert selection["suitable"] is False and selection["selected"] is None
    assert "media_strategy 'typographic'" in acceptance["2_director_media_note"]


def test_a_designed_single_renders_without_the_card_and_passes_the_gate(acceptance):
    single = acceptance["3_single_designed_without_card"]
    assert single["plan_demoted"] and single["treatment"] == "none" and single["designed_typographic"] and single["focal"] == "figure"
    assert acceptance["4_single_gate"] == {"passed": True, "blocking": []}


def test_the_vcru_share_card_cannot_become_the_reel_hero(acceptance):
    assert acceptance["5_reel_live_cover_reproduced"]["treatment"] == "cover_cropped"  # the live defect
    assert acceptance["6_vcru_classified"]["suitable"] is False
    assert acceptance["6_share_card_cannot_be_the_hero"] == {"treatment": "none", "layout_variant": "reel_graphic"}
    assert acceptance["7_reel_fallback_cover"]["designed_typographic"] and acceptance["7_reel_fallback_cover"]["gate"]["passed"]


def test_the_raw_clipped_share_card_cover_fails_once_the_decision_is_known(acceptance):
    blocking = acceptance["10_clipped_embedded_text_still_fails"]["blocking"]
    assert any(b.startswith("unsuitable_source_media_rendered") for b in blocking)


def test_suitable_photography_stays_eligible_and_wins_over_an_earlier_unsuitable_card(acceptance):
    eligible = acceptance["8_suitable_photo_eligible"]
    assert eligible["alone"]["selected"] == "source"
    assert eligible["after_an_unsuitable_card"]["selected"] == "source_2"
    assert acceptance["8_suitable_photo_single"]["treatment"] != "none" and acceptance["8_suitable_photo_single"]["gate"]["passed"]


def test_suitable_selected_media_missing_from_the_render_still_fails(acceptance):
    missing = acceptance["9_selected_media_missing"]
    assert "single_source_image_not_rendered" in missing["single"]["blocking"]
    assert not missing["reel"]["passed"]  # now blocking for a Reel too, once the image was approved


def test_a_plain_text_dump_still_fails(acceptance):
    assert any(b.startswith("typographic_render_not_designed") for b in acceptance["plain_text_dump_still_fails"]["gate"]["blocking"])


def test_the_split_panel_is_the_canonical_kage_violet(acceptance):
    assert acceptance["11_split_panel"]["violet"]


def test_no_provider_call(acceptance):
    assert acceptance["provider_calls"] == 0


def test_a_plan_without_source_media_is_left_alone():
    from types import SimpleNamespace

    from services.instagram_automatic_trigger import _demote_source_plan

    creative = SimpleNamespace(creative_execution_plan=SimpleNamespace(media_strategy="typographic"))
    assert _demote_source_plan(creative) == (creative, False)
