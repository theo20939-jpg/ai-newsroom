"""Editorial judgment reset (prompt v10.8): the frozen v10.7 PAID validation outputs are the regression dataset.

Every known failure of those four real Creative Director outputs must be caught before acceptance; the founder reference copy for the same
four stories must pass with zero blocking findings (the false-positive check). Zero provider calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageDraw

import services.instagram_creative_director as cd
from services.instagram_carousel_layouts import render_carousel_slide
from services.instagram_declarative_layout import _wrap
from services.instagram_editorial_critic import EditorialQualityError, critique, salience
from services.instagram_media_first import MediaFirstContractError
from services.instagram_typography import wrap_units
from services.instagram_visual_profiles import InstagramRenderProfile, ig_font, profile_spec

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "instagram_v107_validation"
ARCHETYPES = ("ai_hack", "news_insight", "news_recap", "trend_generative")

# every failure found in the founder review of the real paid run that the deterministic critic is expected to catch
EXPECTED = {
    "ai_hack": {"hook_is_a_label_chain", "usable_instruction_paraphrased", "instruction_actor_changed", "card_adds_no_new_information",
                "phrase_repeated_in_card", "russian_bureaucratic_phrase"},
    "news_insight": {"hook_too_long_for_display", "label_headline", "no_practical_takeaway", "list_repeated_from_earlier_card", "russian_vague_noun"},
    "news_recap": {"hook_misses_strongest_fact", "strongest_fact_dropped", "body_repeats_headline", "body_restates_headline_claim",
                   "completed_fact_turned_into_plan", "claim_stronger_than_evidence", "launch_after_discussion", "russian_calque_adopted",
                   "russian_participle_chain", "russian_temporal_where", "russian_empty_filler", "russian_wrong_preposition_week"},
    "trend_generative": {"russian_tautology", "label_headline", "russian_pronoun_without_referent", "russian_empty_filler",
                         "list_repeated_from_earlier_card"},
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _reference_slides(data: dict) -> list[dict]:
    return [{**s, "layout": {"regions": [{"flow_steps": s["flow_steps"]}]} if s.get("flow_steps") else None} for s in data["reference"]["slides"]]


@pytest.mark.parametrize("name", ARCHETYPES)
def test_every_known_paid_failure_is_caught(name):
    data = _load(name)
    findings = critique(data["paid_output"]["slides"], list(data["evidence_handles"].values()), archetype=name,
                        caption=data["paid_output"].get("final_caption") or "")
    codes = {f.code for f in findings}
    assert EXPECTED[name] <= codes, EXPECTED[name] - codes
    # since the v10.9 judgment reset the critic only GATES what is false, loses core value or cannot be displayed; taste is advisory
    gating = {f.code for f in findings if f.severity == "blocking"}
    assert gating == GATING_EXPECTED[name], gating


GATING_EXPECTED = {
    "ai_hack": {"usable_instruction_paraphrased"},
    "news_insight": {"hook_too_long_for_display"},
    "news_recap": {"strongest_fact_dropped", "completed_fact_turned_into_plan", "claim_stronger_than_evidence", "launch_after_discussion"},
    "trend_generative": set(),  # its defects are Russian/taste - reported as advisory, never a gate
}


@pytest.mark.parametrize("name", ARCHETYPES)
def test_the_founder_reference_passes_with_no_blocking_finding(name):
    data = _load(name)
    findings = critique(_reference_slides(data), list(data["evidence_handles"].values()), archetype=name, caption=data["reference"]["final_caption"])
    assert [f.render() for f in findings if f.severity == "blocking"] == []


def test_the_strongest_fact_is_the_extreme_ratio_not_the_plain_launch():
    evidence = list(_load("news_recap")["evidence_handles"].values())
    ranked = sorted(evidence, key=salience, reverse=True)
    assert "1%" in ranked[0] and salience(ranked[0]) > salience("[story_1] OpenAI запустила GPT-6 Sol и Luna.")


def test_the_apollo_type_tense_drift_is_caught_and_the_correct_tense_is_not():
    evidence = ["[story_3] Apollo обучена примерно на 600 миллионах исторических греческих слов."]
    wrong = [{"slide_copy": "Apollo", "slide_body": "x"}, {"slide_copy": "ИИ для древнегреческого", "slide_body": "Apollo планируют обучить на 600 млн слов."}]
    right = [{"slide_copy": "Apollo", "slide_body": "x"}, {"slide_copy": "ИИ для древнегреческого", "slide_body": "Apollo уже обучили на 600 млн слов."}]
    assert "completed_fact_turned_into_plan" in {f.code for f in critique(wrong, evidence)}
    assert "completed_fact_turned_into_plan" not in {f.code for f in critique(right, evidence)}


def test_v10_8_acceptance_rejects_a_real_paid_output_before_it_can_ship():
    data = _load("ai_hack")
    director_input = cd.CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s",
                                              allowed_evidence=list(data["evidence_handles"].values()), locale="ru", media_first=True)
    with pytest.raises(EditorialQualityError, match="usable_instruction_paraphrased"):
        cd._validate_carousel_output(data["paid_output"], None, director_input=director_input, archetype="ai_hack")
    assert issubclass(EditorialQualityError, MediaFirstContractError)  # the one contract retry receives the exact findings


def test_the_recap_contract_overflow_is_blocked_and_the_bound_is_now_stated():
    data = _load("news_recap")
    director_input = cd.CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", is_recap_bundle=True,
                                              allowed_evidence=list(data["evidence_handles"].values()), locale="ru", media_first=True,
                                              available_media_subjects=("story_3",))
    with pytest.raises(MediaFirstContractError, match="exceed the per-post bound 6"):
        cd._validate_carousel_output(data["paid_output"], None, director_input=director_input, archetype="news_recap")
    prompt = yaml.safe_load((ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.8.yaml").read_text(encoding="utf-8"))
    assert any("at most 6 slides with media_source 'generated'" in rule for rule in prompt["rules"])


def test_v10_8_is_active_and_is_exactly_what_its_generator_builds():
    import scripts._instagram_make_prompt_v10_8 as gen

    assert cd.CAROUSEL_PROMPT_VERSION == "10.11" and "10.8" in cd.EDITORIAL_CRITIC_CAROUSEL_VERSIONS and "10.8" in cd.BODY_COPY_CAROUSEL_VERSIONS
    committed = yaml.safe_load((ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.8.yaml").read_text(encoding="utf-8"))
    assert committed == gen.build()
    schema = committed["output_schema"]
    assert schema["required"][0] == "angle_candidates" and schema["properties"]["slides"]["maxItems"] == 10
    assert "slide_body" in schema["properties"]["slides"]["items"]["required"]  # the v10.7 structural gains stay


@pytest.mark.parametrize(("text", "unit"), [("Титановые Watch 6 — от $149", "Watch 6 —"), ("Длинный текст. Два шага.", "Два шага."),
                                             ("на 600 млн слов", "на 600 млн"), ("Титан, сапфир и eSIM — от $149. Серьёзно?", "и eSIM —")])
def test_protected_units_are_never_split(text, unit):
    assert unit in wrap_units(text)
    assert all(not u.startswith(("—", "–")) for u in wrap_units(text))
    assert "$149. Серьёзно?" not in wrap_units(text)  # never glued across a sentence boundary


def test_a_narrow_column_never_breaks_a_protected_unit_or_starts_a_line_with_a_dash():
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for width in (260, 330, 420, 520):
        lines = _wrap(draw, "Титан, сапфир и eSIM — от $149. Серьёзно? Титановые Watch 6 — два шага", ig_font(80, "black"), width)
        assert not any(line.startswith("—") for line in lines)
        assert not any(line.endswith("Watch") or line.endswith("два") for line in lines)


def test_a_long_body_in_a_small_plan_box_keeps_its_image_instead_of_the_text_only_fallback():
    slide = _load("news_recap")["paid_output"]["slides"][5]  # the real paid Xiaomi card: a 135-character body in a 0.38 x 0.25 box
    img = Image.new("RGB", (1024, 1536), (60, 50, 80))
    result = render_carousel_slide(spec=profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE), role=slide["role"], index=5, total=8,
                                   slide_copy=slide["slide_copy"], slide_body=slide["slide_body"], source_evidence=None, package_identity="p",
                                   media_mode="GENERATED", layout_plan=slide["layout"], subject_assets={"generated": (img, "id")})
    assert result.notes["fallback_role_layout_used"] is False and result.notes["media_regions"]
    assert "body" in {m["ref"] for m in result.notes["text_metrics"]} and "body_min_relaxed" in result.notes["body_placement"]
