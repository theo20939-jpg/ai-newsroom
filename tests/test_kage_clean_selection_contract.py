"""Artifact-free checks for the founder-frozen Telegram selection behavior."""

from pathlib import Path

from integrations.prompts.file_repository import FilePromptRepository
from services.kage_event_dedup import same_underlying_change
from services.news_editorial_relevance import classify_product_quality


def test_precision_dedup_merges_meta_tools_but_not_distinct_gemini_features():
    meta_mobile = {
        "title": "Meta is going to let you build games with AI right on your phone",
        "lead": "Horizon Create is a mobile app and Horizon Studio is a browser app for making games with prompts.",
    }
    meta_tools = {
        "title": "Meta unveils AI-powered game tools for mobile devices and browsers",
        "lead": "Two tools let people develop games with AI prompts on mobile devices and browsers.",
    }
    avatar = {
        "title": "Gemini 3.8 Live with Live Avatar gives Google's AI a face",
        "lead": "An animated AI persona responds in real time during conversations.",
    }
    calls = {
        "title": "Google's Gemini Can Now Make Calls for You on Pixel Phones",
        "lead": "Call for Me places calls on Pixel phones.",
    }
    assert same_underlying_change(meta_mobile, meta_tools) == "prompt-based game creation"
    assert same_underlying_change(avatar, calls) is None


def test_concrete_copilot_launch_is_not_rejected_as_aspiration():
    decision = classify_product_quality(
        "Microsoft thinks its new Copilot 'super app' will be as influential as Office",
        "After teasing its new Copilot super app last month, Microsoft is officially unveiling it today. "
        "The redesigned Copilot app bundles three AI capabilities into a single interface of chat, coding, and agents. "
        "As part of the launch, Microsoft is also rebranding Scout, the AI personal assistant it unveiled at Build earlier this year, as Autopilot.",
        product_loop=True,
    )
    assert decision.target_profile
    assert decision.lane == "AI_PRODUCT"


def test_only_frozen_prompt_versions_are_packaged_for_new_stack():
    repo = FilePromptRepository(Path(__file__).resolve().parents[1] / "prompts")
    for name, version in (
        ("copywriting", "11.10"), ("research", "5"),
        ("intelligence", "4"), ("quality", "9.2"),
        ("publication_factual_gate", "1"),
    ):
        assert repo.resolve(name, version).version == version
