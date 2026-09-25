"""2026-09-25 final pre-render contract: (A) Phase A quotes ground as ONE contiguous, boundary-aligned span of one exact evidence item
after SAFE normalization only (Unicode, quotation marks, apostrophes, whitespace) - never fuzzy, never semantic; (B) a supported primitive
used on many slides is a design-repetition DIAGNOSTIC, not a hard pre-render failure - only an empty / impossible / mechanically
duplicated plan is rejected. No provider, no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import services.instagram_creative_director as cd
from schemas.instagram_creative import InstagramCarouselCreative
from services.instagram_media_first import MediaFirstContractError, assert_media_first, visual_repetition_report
from tests.test_instagram_downstream_blockers import _carousel, _flow, _poll
from tests.test_instagram_phase_b5_visual_dna_declarative import _r
from tests.test_instagram_phase_b6_media_first import _media, _slide_dict, _text

RUN = Path(__file__).resolve().parent.parent / "artifacts/instagram_feed_product/e2e_week_2026-08-05_11/micro_canary_run"
SENTENCE = ("Drawing on more than 70 tools across Adobe’s creative and productivity suites, the Adobe plugin in ChatGPT supports "
            "a wide range of workflows.")
GLUED = "RELATED HEADING about something else “" + SENTENCE + "” Adobe said in the release."


def _grounds(quote: str, item: str) -> bool:
    try:
        cd.assert_evidence_grounded([quote], [item])
        return True
    except cd.UngroundedEvidenceError:
        return False


# --- A. source-span grounding ------------------------------------------------------------------------------------------------------

def test_1_a_sentence_inside_a_larger_item_behind_a_glued_heading_grounds():
    assert _grounds(SENTENCE, GLUED)
    assert _grounds(SENTENCE, "RELATED HEADING. " + SENTENCE)


def test_2_typographic_quotes_apostrophes_and_whitespace_normalize():
    item = "Adobe’s plugin is “available today” in ChatGPT. Free accounts   have\nusage limits."
    assert _grounds('Adobe\'s plugin is "available today" in ChatGPT.', item)
    assert _grounds("Free accounts have usage limits.", item)
    assert _grounds("- " + item, item)  # the whole item (with our own prompt bullet) is still exact
    assert _grounds("Adobe’s plugin is available today in ChatGPT.", item)  # reported-speech marks are punctuation, not content


@pytest.mark.parametrize("quote", [
    SENTENCE.replace("70", "80"),                                            # 3. a number changed
    SENTENCE.replace("more than 70", "70"),                                  # 4. a material qualifier removed (mid-span)
    "70 tools across Adobe’s creative and productivity suites, the Adobe plugin in ChatGPT supports a wide range of workflows.",  # 4. qualifier cut off the front
    "Drawing on more than 70 tools across Adobe’s creative and productivity suites",  # a clause cut before its end
    "Adobe's ChatGPT plugin gives access to over 70 creative tools.",        # 5. paraphrase
    "Drawing on more than 70 tools across Adobe’s creative and productivity suites, Adobe said in the release.",  # 6. two non-contiguous spans
    SENTENCE.lower(),                                                         # case is content, never normalized
])
def test_3_to_6_material_changes_paraphrases_and_joined_spans_fail(quote):
    assert not _grounds(quote, GLUED)


def test_two_items_cannot_be_joined_into_one_quote():
    with pytest.raises(cd.UngroundedEvidenceError):
        cd.assert_evidence_grounded(["First fact. Second fact."], ["First fact.", "Second fact."])


def test_the_director_handle_resolver_stays_exact():
    with pytest.raises(cd.UngroundedEvidenceError):
        cd.resolve_evidence_references([SENTENCE], [GLUED])


def test_adobe_saved_phase_a_output_now_grounds():
    post = RUN / "2026-08-06_1_ai_hack"
    decision = json.loads((post / "calls/01_phase_a.json").read_text(encoding="utf-8"))["response"]["structured_output"]
    package = json.loads((post / "evidence_package.json").read_text(encoding="utf-8"))
    allowed = [package["premise"], *(i["text"] for k in ("steps", "facts", "limitations") for i in package[k])]
    cd.assert_evidence_grounded(decision["evidence_used"], allowed)  # raised UngroundedEvidenceError in the paid micro-canary
    quote = next(q for q in decision["evidence_used"] if q.startswith("Drawing on more than 70"))
    assert quote not in allowed  # it grounds as a span, not by whole-item equality
    with pytest.raises(cd.UngroundedEvidenceError):
        cd.assert_evidence_grounded([quote.replace("70", "7")], allowed)


# --- B. repetition is a diagnostic ---------------------------------------------------------------------------------------------------

def _saved_recap_plans() -> list[list]:
    plans = []
    for name in ("04_director.json", "05_director.json"):
        out = json.loads((RUN / "weekly_recap/calls" / name).read_text(encoding="utf-8"))["response"]["structured_output"]
        plans.append(list(InstagramCarouselCreative.model_validate(out).slides))
    return plans


def test_both_saved_recap_plans_are_executable_and_carry_a_repetition_warning():
    verdicts = json.loads((RUN / "weekly_recap/vision_verdicts.json").read_text(encoding="utf-8"))  # the media the Director was offered
    available = {v["subject_key"] for v in verdicts}
    unsuitable = {v["subject_key"] for v in verdicts if not v["suitable"]}
    for slides in _saved_recap_plans():
        assert_media_first(slides, available_subjects=available, unsuitable_subjects=unsuitable, generated_media_available=False)
        report = visual_repetition_report(slides)
        assert report["design_repetition_warning"] and report["degenerate_composition"] is None


def test_a_common_valid_primitive_no_longer_fails_by_percentage():
    same = [_flow("hook", "Как это работает")] + [_flow("step", f"Шаг {i}", steps=(f"A{i}", f"B{i}", "C")) for i in range(1, 6)] + [
        _poll("takeaway", "Итог: A | B")]
    slides = _carousel(same)
    assert_media_first(slides, available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)
    report = visual_repetition_report(slides)
    assert report["primitive_distribution"]["flow_diagram"] == 6 and report["warnings"][0] == "flow_diagram carries 6 of 7 slides"


def test_a_mechanically_duplicated_composition_is_still_rejected():
    slides = _carousel([_flow("hook", "Одно и то же")] + [_flow("step", f"Шаг {i}") for i in range(1, 5)] + [_flow("takeaway", "Итог")])
    with pytest.raises(MediaFirstContractError, match="identical composition"):
        assert_media_first(slides, available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)


def test_empty_ui_frame_impossible_media_and_decorative_graphics_still_hard_fail():
    empty = [_flow("hook", "Как подключить"), _slide_dict("step", "Шаг 2", "graphic", [
        _r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="ui_frame", tone="accent"), _text(y=0.56)]), _poll("takeaway", "A | B")]
    with pytest.raises(MediaFirstContractError, match="empty window frame"):
        assert_media_first(_carousel(empty), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)
    generated = [_slide_dict("hook", "Сгенерировано", "generated", [_media("generated", 0.0, 0.0, 1.0, 0.6), _text(y=0.64)]),
                 _flow("step", "Шаг 1"), _poll("takeaway", "A | B")]
    with pytest.raises(MediaFirstContractError, match="image generation is off"):
        assert_media_first(_carousel(generated), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)
    stray = [_slide_dict("hook", "Фото", "source", [_media("not_listed", 0.0, 0.0, 1.0, 0.6), _text(y=0.64)], subject="not_listed"),
             _flow("step", "Шаг 1"), _poll("takeaway", "A | B")]
    with pytest.raises(MediaFirstContractError):
        assert_media_first(_carousel(stray), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)
    rule_only = [_slide_dict("hook", "Только линия", "graphic", [_r("accent", 0.08, 0.12, 0.84, 0.02, accent_type="rule_h", tone="accent"),
                                                                _text(y=0.56)]), _flow("step", "Шаг 1"), _poll("takeaway", "A | B")]
    with pytest.raises(MediaFirstContractError, match="substantive graphic"):
        assert_media_first(_carousel(rule_only), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)


def test_the_60_percent_constant_is_gone_and_the_art_gate_is_untouched():
    import services.instagram_media_first as mf
    from services import instagram_art_validator

    assert not hasattr(mf, "GENERIC_PRIMITIVE_MAX_SHARE")
    assert "slide_without_meaningful_visual" in Path(instagram_art_validator.__file__).read_text(encoding="utf-8")
