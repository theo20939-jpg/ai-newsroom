"""MEME-PROD-4 §17: deterministic, offline acceptance scenarios for the Meme Director redesign.

No real LLM call anywhere in this file (matches this phase's own "no paid API calls unless
explicitly authorized" constraint) - these are fixture-level concept assertions proving the
DETERMINISTIC parts of the redesign behave as intended: services/meme_shape_gate.py correctly
distinguishes the brief's own confirmed BAD (editorial-illustration) examples from GOOD (real
visual-joke) examples for each scenario, and services/meme_image_generation.py::build_image_prompt()
produces coherent, panel-aware prompt text for the concepts that need it. Whether gpt-image-2
ITSELF actually produces a good meme for these prompts can only be judged by a real, separately-
authorized paid canary and human review (module docstring's own disclosed limitation - see this
phase's final report §J for the exact canary sequence) - these tests prove the pipeline's own
deterministic logic, never claim a real generated image's quality.
"""
from __future__ import annotations

from schemas.meme_concept import MemeConcept
from services.meme_image_generation import build_image_prompt
from services.meme_shape_gate import assess_meme_shape_risk

# ---------------------------------------------------------------------------
# Scenario A - price increase (brief's own confirmed real production failure)
# ---------------------------------------------------------------------------

_SCENARIO_A_PREMISE = "A major chip company raises processor prices starting next quarter."
_SCENARIO_A_BAD_SCENE = "A large glowing chip passing through an expensive toll road booth with price gauges."


def test_scenario_a_price_increase_bad_illustration_is_flagged() -> None:
    """The confirmed real production failure: a beautiful chip/toll-road metaphor that visualizes
    the economics rather than telling a joke."""
    result = assess_meme_shape_risk(
        visual_scene=_SCENARIO_A_BAD_SCENE,
        visual_punchline="A large glowing chip passing through an expensive toll booth with gauges.",
        premise=_SCENARIO_A_PREMISE,
    )
    assert result.risk_reason is not None


def test_scenario_a_price_increase_good_human_cost_joke_passes() -> None:
    result = assess_meme_shape_risk(
        visual_scene="A gamer at a checkout counter holding a tiny processor box.",
        visual_punchline=(
            "The cashier hands the gamer a mortgage contract instead of a receipt while he stares "
            "in horror, wallet already empty on the counter."
        ),
        premise=_SCENARIO_A_PREMISE,
    )
    assert result.risk_reason is None


# ---------------------------------------------------------------------------
# Scenario B - product discontinuation
# ---------------------------------------------------------------------------

_SCENARIO_B_PREMISE = "Apple may discontinue more than ten popular products this year."


def test_scenario_b_discontinuation_bad_showroom_illustration_is_flagged() -> None:
    result = assess_meme_shape_risk(
        visual_scene="Tim Cook standing in a showroom surrounded by devices with price tags.",
        visual_punchline="Tim Cook standing in a showroom surrounded by devices with price tags on them.",
        premise=_SCENARIO_B_PREMISE,
    )
    assert result.risk_reason is not None


def test_scenario_b_discontinuation_good_funeral_concept_passes() -> None:
    result = assess_meme_shape_risk(
        visual_scene="A small funeral procession carrying a coffin shaped like a discontinued gadget.",
        visual_punchline=(
            "Mourners in black gather around the tiny gadget-shaped coffin while one wipes away a "
            "tear, treating a product cancellation like a genuine death in the family."
        ),
        premise=_SCENARIO_B_PREMISE,
    )
    assert result.risk_reason is None


# ---------------------------------------------------------------------------
# Scenario C - AI assistant improvement
# ---------------------------------------------------------------------------

_SCENARIO_C_PREMISE = "Siri receives a major AI upgrade with stronger on-screen context understanding."


def test_scenario_c_ai_upgrade_bad_glowing_orb_is_flagged() -> None:
    result = assess_meme_shape_risk(
        visual_scene="A glowing futuristic AI orb hovering in a dark high-tech room.",
        visual_punchline="A glowing futuristic AI orb hovering in a dark high-tech room, pulsing with light.",
        premise=_SCENARIO_C_PREMISE,
    )
    assert result.risk_reason is not None


def test_scenario_c_ai_upgrade_good_expectation_reality_passes() -> None:
    result = assess_meme_shape_risk(
        visual_scene="A phone screen split into two halves.",
        visual_punchline=(
            "Expectation: Siri effortlessly reads and understands everything on screen. Reality: "
            "the user is trapped in a giant maze built from permission toggles and settings menus."
        ),
        premise=_SCENARIO_C_PREMISE,
    )
    assert result.risk_reason is None


def test_scenario_c_expectation_reality_concept_builds_a_coherent_two_panel_prompt() -> None:
    """The GOOD example above is naturally a TWO_PANEL/EXPECTATION_REALITY format - confirms the
    full MemeConcept (panel_count=2) validates and produces a coherent panel-composition prompt,
    reusing the classic top_text/bottom_text renderer path (zero renderer change for panel_count=2,
    per this phase's own design)."""
    concept = MemeConcept(
        premise=_SCENARIO_C_PREMISE, setup="s", punchline="pl", humor_mechanism="expectation_reality",
        visual_scene="A phone screen split into two halves.",
        visual_punchline=(
            "Expectation: Siri effortlessly reads everything on screen. Reality: the user is lost "
            "in a giant maze of permission toggles."
        ),
        visual_style="low-budget internet meme", characters_objects=["phone", "user"],
        text_overlay_intent="intent", source_fact_links=["fact"], forbidden_interpretations=[],
        meme_format="expectation_reality", panel_count=2,
        panel_beats=["Siri effortlessly understanding the screen", "user lost in a giant maze of toggles"],
    )
    prompt = build_image_prompt(concept).lower()
    assert "two clean side-by-side or stacked halves" in prompt
    assert "maze" in prompt
    assert "no text" in prompt  # anti-pseudo-text hardening still present


# ---------------------------------------------------------------------------
# Scenario D - gaming hype / shortage (the GTA 6 / PS5 Pro flagship target)
# ---------------------------------------------------------------------------

_SCENARIO_D_PREMISE = "The PS5 Pro sold out at major retailers due to GTA 6 hype."


def test_scenario_d_shortage_bad_literal_crowded_store_is_flagged() -> None:
    """The realistic failure shape: the model's own "visual_punchline" is effectively the same
    scene restated, the exact confirmed production pattern this gate exists to catch."""
    result = assess_meme_shape_risk(
        visual_scene="A crowded electronics store with empty shelves where the PS5 Pro consoles used to be.",
        visual_punchline="A crowded electronics store with empty shelves where the PS5 Pro consoles were.",
        premise=_SCENARIO_D_PREMISE,
    )
    assert result.risk_reason is not None


def test_scenario_d_shortage_four_panel_character_escalation_concept_validates() -> None:
    """The brief's own flagship acceptance target: a four-panel mini-story starring a recurring
    character, not a literal shortage illustration."""
    concept = MemeConcept(
        premise=_SCENARIO_D_PREMISE, setup="s", punchline="pl", humor_mechanism="escalation",
        visual_scene="A cat gamer at home.",
        visual_punchline="The cat ends up living in the cardboard box the console would have come in.",
        visual_style="cartoon", characters_objects=["cat"], text_overlay_intent="intent",
        source_fact_links=["fact"], forbidden_interpretations=[], meme_format="four_panel_escalation",
        panel_count=4,
        panel_beats=[
            "making a hype plan", "obsessively refreshing for GTA 6 news",
            "discovering the PS5 Pro is sold out", "sitting in a cardboard box joking about selling a kidney",
        ],
    )
    shape_risk = assess_meme_shape_risk(
        visual_scene=concept.visual_scene, visual_punchline=concept.visual_punchline, premise=concept.premise,
    )
    assert shape_risk.risk_reason is None

    prompt = build_image_prompt(concept).lower()
    assert "2x2 grid of four panels" in prompt
    assert "same recurring character" in prompt
    assert "kidney" in prompt
    assert "no text" in prompt  # anti-pseudo-text hardening still present


# ---------------------------------------------------------------------------
# Scenario E - inherently absurd news: a simple reaction meme must be ALLOWED, not penalized for
# being simple (the brief's own explicit "do not over-complicate" allowance).
# ---------------------------------------------------------------------------


def test_scenario_e_simple_reaction_meme_is_not_penalized_for_being_simple() -> None:
    """A genuinely absurd/self-explanatory news story doesn't need a four-panel epic - a single,
    strong reaction image with a real, distinct visual_punchline must pass the shape gate exactly
    like a more elaborate multi-panel concept would."""
    result = assess_meme_shape_risk(
        visual_scene="A office worker at his desk.",
        visual_punchline="The worker's coffee mug is visibly shaking in fear at the news on his monitor.",
        premise="A company announces a genuinely bizarre, self-evidently absurd policy change.",
    )
    assert result.risk_reason is None

    concept = MemeConcept(
        premise="A company announces a genuinely bizarre, self-evidently absurd policy change.",
        setup="s", punchline="pl", humor_mechanism="absurdity",
        visual_scene="A office worker at his desk.",
        visual_punchline="The worker's coffee mug is visibly shaking in fear at the news on his monitor.",
        visual_style="reaction photo", characters_objects=["office worker", "coffee mug"],
        text_overlay_intent="intent", source_fact_links=["fact"], forbidden_interpretations=[],
        meme_format="reaction", panel_count=1, panel_beats=[],
    )
    prompt = build_image_prompt(concept).lower()
    # panel_count==1 must NOT trigger any panel-composition instruction - the single-scene path
    # stays exactly as simple as before this phase for a format that doesn't need more.
    assert "2x2" not in prompt
    assert "panel 1" not in prompt
