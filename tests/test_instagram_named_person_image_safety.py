"""NAMED-PERSON IMAGE SAFETY - context, not keywords (founder task 2026-09-27, after the sixth paid viral canary).

Canary 6 was stopped by the generated-image likeness gate on 'a blank clock face' (slide 2) and on 'without depicting a real person' /
'No ... identifiable people are visible' (slide 4) - the named person (Sam Altman) was only in a photo caption of the evidence. The gate now
separates A (the evidence names a real person) from B (the brief POSITIVELY asks to depict them); only B blocks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.instagram_viral_format import depiction_findings, generated_person_risks, named_identities, named_people

ROOT = Path(__file__).resolve().parent.parent
CANARY6 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary6_20260927/post"
ALTMAN = ["Sam Altman, CEO of OpenAI, listens during a Security Council meeting on artificial intelligence at the United Nations.",
          "OpenAI disclosed that its agents interacted with several U.S. government websites in unexpected ways."]


def risks(brief: str, evidence=ALTMAN) -> list[str]:
    return generated_person_risks([{"media_source": "generated", "generation_brief": brief}], evidence)


def test_question_a_reads_the_named_person_and_their_role_from_the_evidence():
    assert named_people(ALTMAN) == {"Sam Altman"}
    assert named_identities(ALTMAN) == {"Sam Altman": {"ceo"}}
    assert named_identities(["OpenAI chief executive Sam Altman said so."]) == {"Sam Altman": {"ceo"}}


PASS = [
    "Portrait collage of a blank clock face, a sealed blank folder and a blank browser window.",
    "A close-up of a smartwatch face showing no digits, on a dark desk.",
    "Anonymous hands holding a frame; the visual works as a metaphor without depicting a real person, company interface or breach.",
    "Blank browser windows in a frame. No text, logos, fake UI or identifiable people are visible.",
    "Anonymous hands arranging blank folders on a desk.",
    "Generic hands holding a phone with a blank screen.",
    "Abstract anonymous silhouettes walking past a glass government building.",
    "A blank app screen with a person icon in the UI corner and an empty search field.",
    "An abstract data-centre corridor of servers with a single glowing cable leading to a government building.",
    "Portrait close-up of human hands attaching a blank sensor to a wheel.",
    "A hamster posed like an athlete beside a stopwatch.",
    "A laptop and a filing cabinet; never show Sam Altman or any real person.",
    "An empty chair at a UN-style table; Sam Altman must not appear.",
    "A laptop - no likeness of any real person, no portrait.",
    "A clock face and a watch face on a map; faces of the clocks are blank.",
    "An icon of a person on a blank login screen.",
    "A lone figure in silhouette seen from behind looking at a wall of screens.",
]


@pytest.mark.parametrize("brief", PASS)
def test_objects_negations_and_anonymous_human_elements_pass(brief):
    assert risks(brief) == [], risks(brief)


FAIL = [
    "Portrait of Sam Altman at a podium.",
    "Sam Altman at a computer, typing late at night.",
    "A person resembling Sam Altman in a dark office.",
    "A photorealistic likeness of the executive in a meeting room.",
    "Recreate Sam Altman's face on a large screen.",
    "A recognizable depiction of the named CEO at the Security Council.",
    "Do not hide Sam Altman's face; show him clearly.",
    "Not only Sam Altman's face but his full body in a suit.",
    "The OpenAI CEO speaking at a microphone.",
    "Altman listening at the Security Council table.",
    "“Sam Altman” on stage, lit from the side.",
    "Blank screens. A man in a grey suit listens at a round table.",
    "A laptop, and a realistic face looking at it.",
    "A lookalike of the tech executive smiling.",
    "Blank folders - but show Sam Altman behind them.",
    "No logos; a recognizable person at a desk.",
    "Do not show Sam Altman; show him clearly instead.",
]


@pytest.mark.parametrize("brief", FAIL)
def test_a_positive_depiction_of_the_named_person_or_a_likeness_is_blocked(brief):
    found = risks(brief)
    assert found and "named real person (Sam Altman)" in found[0], brief


def test_clause_boundaries_scope_negation_to_its_own_clause():
    # the prohibition covers only its own clause: the name in the next clause is positive
    assert risks("No text or logos. Sam Altman at the table.")
    assert risks("Without logos; Sam Altman at the table.")
    assert not risks("Blank screens, without Sam Altman or any other real person.")
    assert risks("Not a real person: Sam Altman himself at the desk.")  # a colon closes the clause
    # a new article-led noun phrase after a comma leaves the prohibition's list (conservative - may over-block, never under-block)
    assert risks("Without logos, a man at a desk.") and risks("No text, a logo or a person.")
    # punctuation around the name does not hide it
    assert risks("Sam Altman, at a desk.") and risks("(Sam Altman) at a desk") and risks("Sam Altman's desk, with him seated")


def test_nothing_changes_when_no_person_is_named_and_source_photos_are_not_affected():
    assert risks("Portrait of a man at a computer", ["OpenAI disclosed unexpected agent behaviour."]) == []
    assert generated_person_risks([{"media_source": "source", "generation_brief": "Sam Altman portrait"}], ALTMAN) == []


def test_no_policy_weakening_the_previous_positive_cases_still_block():
    thijs = ["Thijs de Buck, an MRI physicist based in Utrecht, built a tracker."]
    assert risks("A young man attaching a sensor to a wheel", thijs)
    assert risks("Thijs de Buck smiling at his desk", thijs)
    assert risks("de Buck smiling at his desk", thijs)
    assert risks("A physicist attaching a sensor to the wheel", thijs)  # the role resolves to the named person
    # the accepted hamster carousel: the role only possesses anonymous hands - hands, not the person; the NAME stays blocked
    assert not risks("Close-up of an MRI physicist's hands assembling a blank sensor near a hamster wheel", thijs)
    assert risks("Close-up of Thijs de Buck's hands assembling a blank sensor", thijs)
    assert depiction_findings("anonymous Sam Altman", {"Sam Altman": {"ceo"}}) == ["Sam Altman"]  # anonymity never excuses the name
    # the IShowSpeed canary's three generated briefs still block (the name, a skater figure)
    fresh = ROOT / "artifacts/instagram_feed_product/fresh_viral_canary_20260926/post"
    raw = json.loads((fresh / "calls/03_director.json").read_text(encoding="utf-8"))["response"]["structured_output"]
    evidence = json.loads((fresh / "director_input.json").read_text(encoding="utf-8"))["allowed_evidence"]
    assert [r.split(":")[0] for r in generated_person_risks(raw["slides"], evidence)] == ["slide 1", "slide 3", "slide 4"]


def test_canary6_first_director_output_passes_image_safety():
    raw = json.loads((CANARY6 / "director_raw_output_initial.json").read_text(encoding="utf-8"))["structured_output"]
    call = json.loads((CANARY6 / "calls/03_director.json").read_text(encoding="utf-8"))
    import re

    evidence = [line for _n, line in re.findall(r"^E(\d+): (.*)$", "\n".join(t for m in call["request"] for t in m["text"]), re.M)]
    assert named_people(evidence) == {"Sam Altman"}  # A: yes - only in a photo caption (E3)
    assert generated_person_risks(raw["slides"], evidence) == []  # B: no brief positively depicts him
