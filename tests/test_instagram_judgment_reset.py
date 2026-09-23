"""Creative Director judgment reset (prompt v10.9) - zero provider calls.

The v10.8 paid run (0/4 product-strong) is the regression set, next to the v10.7 run and the founder reference. The failures came from
conflicting and piled-up instructions: a recap rule that asked for a "synthesis of the week" against one that asked for the strongest fact;
an unscoped product rule that made the model refuse a gadget story; a ban on unsupported facts read as a ban on any advice; a reviewer
threat that pushed toward caution. These tests pin the removal of those causes, the editor-first decision order, and a critic that is a
safety net (it gates only what is false, loses core value or cannot be displayed) rather than the editor."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

import services.instagram_creative_director as cd
from schemas.instagram_creative import InstagramCarouselCreative
from services.instagram_editorial_critic import GATING_CODES, critique

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts" / "instagram_creative_director_carousel"
V108 = ROOT / "tests" / "fixtures" / "instagram_v108_validation"
ARCHETYPES = ("ai_hack", "news_insight", "news_recap", "trend_generative")


def _prompt(version: str) -> dict:
    return yaml.safe_load((PROMPTS / f"v{version}.yaml").read_text(encoding="utf-8"))


def _text(doc: dict) -> str:
    return doc["system"] + "\n" + "\n".join(doc["rules"])


def _v108(name: str) -> dict:
    return json.loads((V108 / f"{name}.json").read_text(encoding="utf-8"))


def test_v10_9_is_active_and_is_exactly_what_its_generator_builds():
    import scripts._instagram_make_prompt_v10_9 as gen

    assert cd.CAROUSEL_PROMPT_VERSION == "10.9"
    assert _prompt("10.9") == gen.build()


def test_the_product_rule_is_about_our_product_and_never_the_news_subject():
    """v10.8 TREND refused the vivo Watch 6 story: 'do not name, imply or hint at the product / its brand' never said WHICH product."""
    doc = _prompt("10.9")
    text = _text(doc)
    assert "or its brand" not in text and "hint at the product" not in text
    assert "NEWS SUBJECT" in doc["system"] and "name it normally" in doc["system"]
    assert "OUR OWN brand's product only" in doc["system"] and "never limits naming the news subject" in doc["system"]
    assert "hint at the product" in _text(_prompt("10.8"))  # the ambiguous wording the refusal came from


def test_the_conflicting_and_cautious_instructions_are_gone():
    text = _text(_prompt("10.9"))
    assert "strongest emotional pattern" not in text  # the recap 'synthesise the week' rule that competed with 'strongest fact first'
    assert "editorial reviewer that rejects" not in text  # the v10.8 caution primer
    assert not re.search(r"2 to 7 words|about 45 characters|Instagram copy is SHORT", text)  # the caps that produced empty slides
    assert not re.search(r"angle_candidates|editorial_angle\b", text)  # listing candidates is not committing to one
    assert any("leads with the week's single strongest fact" in rule for rule in _prompt("10.9")["rules"])


def test_editor_first_order_and_the_decision_is_written_before_the_slides():
    doc = _prompt("10.9")
    order = [doc["system"].index(f"{n}. ") for n in range(1, 7)]
    assert order == sorted(order) and "Only then: check facts and format" in doc["system"]
    schema = doc["output_schema"]
    assert list(schema["properties"])[0] == "editorial_decision" and schema["required"][0] == "editorial_decision"
    decision = schema["properties"]["editorial_decision"]["properties"]
    assert {"strongest_true_thing", "why_a_reader_cares", "must_survive", "card_plan"} <= set(decision)
    assert "Practical advice that follows directly from the evidence" in doc["system"]  # a method is not an invented fact
    creative = InstagramCarouselCreative.model_validate({**_v108("ai_hack")["paid_output"], "editorial_decision": {"strongest_true_thing": "x"}})
    assert creative.editorial_decision == {"strongest_true_thing": "x"}


def test_the_prompt_got_smaller_not_bigger():
    size = {v: len(_text(_prompt(v))) for v in ("10.6", "10.8", "10.9")}
    assert size["10.9"] < size["10.6"] < size["10.8"]
    assert len(_prompt("10.9")["rules"]) < len(_prompt("10.8")["rules"])


def test_the_v10_8_critic_false_positive_is_understood_and_gone():
    """v10.8 AI_HACK card 3: 'Шаг 2. Сожми вывод до трёх пунктов' / 'Попроси модель: «Переформулируй вывод в чек-лист из трёх пунктов».'
    The quoted prompt IS the save value; it shares the headline's words by design."""
    data = _v108("ai_hack")
    assert "body_repeats_headline" in data["critic_at_run"]["blocking"][1]
    findings = critique(data["paid_output"]["slides"], list(data["evidence_handles"].values()), archetype="ai_hack")
    assert not any(f.code == "body_repeats_headline" and f.card == 2 for f in findings)


@pytest.mark.parametrize("name", ARCHETYPES)
def test_the_critic_gates_only_false_lost_or_undisplayable_output(name):
    data = _v108(name)
    findings = critique(data["paid_output"]["slides"], list(data["evidence_handles"].values()), archetype=name,
                        caption=data["paid_output"].get("final_caption") or "")
    assert all((f.severity == "blocking") == (f.code in GATING_CODES) for f in findings)


def test_the_v10_8_refusal_and_false_generalisation_are_still_caught():
    trend = _v108("trend_generative")
    codes = {f.code for f in critique(trend["paid_output"]["slides"], list(trend["evidence_handles"].values()), archetype="trend_generative")
             if f.severity == "blocking"}
    assert "strongest_fact_dropped" in codes  # a post that never names $149 cannot ship
    recap = _v108("news_recap")
    codes = {f.code for f in critique(recap["paid_output"]["slides"], list(recap["evidence_handles"].values()), archetype="news_recap")}
    assert {"claim_stronger_than_evidence", "hook_misses_strongest_fact", "russian_temporal_where"} <= codes
