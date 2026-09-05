"""MEME-PROD-4: services.meme_shape_gate - pure, deterministic, zero LLM/network calls."""
from __future__ import annotations

from services.meme_shape_gate import assess_meme_shape_risk


def test_empty_visual_punchline_is_flagged() -> None:
    result = assess_meme_shape_risk(visual_scene="A chip on a toll road.", visual_punchline="   ", premise="Chip prices rise.")
    assert result.risk_reason == "visual_punchline_empty"


def test_visual_punchline_restating_visual_scene_is_flagged() -> None:
    """The confirmed production failure shape: the 'joke' field is just the scene again."""
    result = assess_meme_shape_risk(
        visual_scene="A large glowing chip passing through an expensive toll road booth with price gauges.",
        visual_punchline="A large glowing chip passing through an expensive toll road booth with gauges.",
        premise="Chip prices increase starting next month.",
    )
    assert result.risk_reason == "visual_punchline_restates_visual_scene"
    assert result.evidence is not None and "token_overlap_ratio" in result.evidence


def test_visual_punchline_restating_news_premise_is_flagged() -> None:
    result = assess_meme_shape_risk(
        visual_scene="A gamer character reacting.",
        visual_punchline="Chip prices increase starting next month across the board.",
        premise="Chip prices increase starting next month across the board.",
    )
    assert result.risk_reason == "visual_punchline_restates_news_premise"


def test_genuine_visual_joke_distinct_from_scene_and_premise_passes() -> None:
    """The GOOD example shape: the punchline is a real, distinct human-cost joke, not a
    restatement of either the scene description or the news premise."""
    result = assess_meme_shape_risk(
        visual_scene="A gamer at a checkout counter holding a tiny processor box.",
        visual_punchline=(
            "The cashier hands the gamer a mortgage contract instead of a receipt while he stares "
            "in horror, wallet already empty on the counter."
        ),
        premise="A major chip company raised processor prices this quarter.",
    )
    assert result.risk_reason is None
    assert result.evidence is None


def test_evidence_is_none_when_no_risk_flagged() -> None:
    result = assess_meme_shape_risk(
        visual_scene="A cat watching wildfire news on TV, alarmed.",
        visual_punchline="The same cat, moments later, relaxed in sunglasses sipping a drink, unbothered.",
        premise="Massive wildfires prompt evacuation orders.",
    )
    assert result.risk_reason is None
