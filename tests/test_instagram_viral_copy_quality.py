"""Founder copy review (2026-09-26): viral copy = NATURAL RUSSIAN + CONCRETE FACT + OPTIONAL DRY PUNCH, never FACT + MANDATORY MEME
LINE. The principle lives in the Director note; the deterministic part a machine can prove without a phrase list - no invented quotes, no
body that adds nothing - is enforced for viral carousels. No provider call."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE, ViralCopyQualityError, assert_viral_copy_quality, invented_quotes

ROOT = Path(__file__).resolve().parent.parent
POLISH = ROOT / "artifacts/instagram_feed_product/viral_copy_polish_20260926/report.json"


def test_the_note_asks_for_the_principle_not_for_punchlines():
    note = VIRAL_CAROUSEL_NOTE
    assert "natural contemporary Russian" in note and "at most ONE dry punch" in note and "a straight factual line is usually stronger" in note
    assert "every body adds a NEW grounded fact" in note and "not 'freedom'" in note and "quotation marks mean a real quote" in note
    assert "физик, специалист по МРТ" in note  # roles and terms translated, never 'физик MRI'
    assert "punchy" not in note and "punchline" not in note  # the wording that produced the forced lines is gone


def test_an_invented_quote_is_caught_and_a_real_quote_or_a_ui_label_is_not():
    evidence = ["Open ChatGPT, go to Plugins", "Он сказал: «мы проверили всё дважды»"]
    assert invented_quotes(["ИИ: «Понял. Взламываю систему»."], evidence) == ["Понял. Взламываю систему"]  # the real Reel hook
    assert invented_quotes(["Зайди в «Plugins»", "Он признал: «мы проверили всё дважды»"], evidence) == []


class _Slide:
    def __init__(self, copy, body):
        self.slide_copy, self.slide_body, self.role = copy, body, "story"
        self.visual_direction = self.media_function = self.layout = None


def test_a_body_that_only_restates_its_headline_blocks_a_viral_carousel():
    slides = [_Slide("Хомяк пробежал 6,06 мили.", "Хомяк пробежал 6,06 мили за пробежку."),
              _Slide("Колесо подключено к Strava.", "Физик из Утрехта собрал для него трекер скорости и дистанции.")]
    with pytest.raises(ViralCopyQualityError, match="body_repeats_headline"):
        assert_viral_copy_quality(slides, ["One recent activity showed 6.06 miles"])


def test_an_invented_quote_blocks_a_viral_carousel_through_the_bounded_retry_path():
    from services.instagram_media_first import MediaFirstContractError

    slides = [_Slide("Агент получил задачу.", "Агент ответил: «Понял, начинаю атаку» и приступил к поиску целей.")]
    with pytest.raises(MediaFirstContractError, match="invented quote"):  # a MediaFirstContractError: the trigger's one correction retry
        assert_viral_copy_quality(slides, ["В мае 2026 года злоумышленник отправил в Telegram одну задачу"])


@pytest.mark.parametrize("story", ["deepseek", "hamster"])
def test_the_polished_copy_passes_the_directors_own_validation_and_the_art_gate(story):
    report = json.loads(POLISH.read_text(encoding="utf-8"))
    assert report["provider_calls"] == 0
    assert report[story]["after_validation"] == "PASS" and report[story]["after_critic_advisory"] == []
    assert report[story]["art_passed"] and report[story]["same_pictures"] == [0, 1, 2, 3, 4]
