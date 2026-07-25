"""Phase 15 M2 - unit tests for services.event_category.categorize_from_tags(), the
single deterministic source-of-truth mapping from a source's config-level tags to the
existing EventCategory enum. No LLM/database/network involved anywhere in this file."""
import pytest

from database.models.news_event import EventCategory
from services.event_category import categorize_from_tags


# A. Known AI classification
@pytest.mark.parametrize(
    "tags",
    [
        ["ai", "llm", "openai"],
        ["ai", "research", "papers"],
        ["local-llm", "inference"],
        ["machine-learning", "research"],
    ],
)
def test_ai_tags_map_to_ai(tags: list[str]) -> None:
    assert categorize_from_tags(tags) == EventCategory.AI


# B. Known technology (general/catch-all) classification
@pytest.mark.parametrize(
    "tags",
    [
        ["technology", "global", "news", "trends"],
        ["technology", "trends", "aggregation"],
    ],
)
def test_tech_tags_map_to_tech(tags: list[str]) -> None:
    assert categorize_from_tags(tags) == EventCategory.TECH


# C. Gaming classification - EventCategory has no GAMING value (confirmed by inspection of
# database/models/news_event.py: AI, GADGETS, TECH, STARTUPS, SOFTWARE, HARDWARE,
# CYBERSECURITY, UNKNOWN). Per the task's own "if supported by existing enum" qualifier,
# there is nothing to test for a dedicated GAMING outcome. What IS tested: the "gaming" tag
# deterministically falls through to the general TECH bucket rather than being silently
# dropped or misrouted to an unrelated category.
def test_gaming_tag_falls_through_to_tech_no_gaming_enum_exists() -> None:
    assert categorize_from_tags(["gaming"]) == EventCategory.TECH


# D. Business/startup classification
@pytest.mark.parametrize(
    "tags",
    [
        ["startup", "business"],
        ["ai", "startup", "business"],
        ["enterprise"],
    ],
)
def test_business_tags_map_to_startups(tags: list[str]) -> None:
    assert categorize_from_tags(tags) == EventCategory.STARTUPS


# More specific categories
def test_security_tag_maps_to_cybersecurity() -> None:
    assert categorize_from_tags(["ai", "security", "openai"]) == EventCategory.CYBERSECURITY


def test_hardware_tags_map_to_hardware() -> None:
    assert categorize_from_tags(["ai", "gpu", "hardware"]) == EventCategory.HARDWARE


def test_gadget_tags_map_to_gadgets() -> None:
    assert categorize_from_tags(["gadgets", "consumer-tech", "ai"]) == EventCategory.GADGETS


def test_software_tags_map_to_software() -> None:
    assert categorize_from_tags(["ai", "coding", "ide"]) == EventCategory.SOFTWARE


# E. Unknown/unrecognized classification - UNKNOWN safely retained
@pytest.mark.parametrize(
    "tags",
    [
        None,
        [],
        ["totally-unrecognized-tag"],
        ["xyz123"],
    ],
)
def test_unrecognized_or_missing_tags_stay_unknown(tags: list[str] | None) -> None:
    assert categorize_from_tags(tags) == EventCategory.UNKNOWN


# F. Formatting/case variants
@pytest.mark.parametrize(
    "tags",
    [
        ["AI"],
        ["Ai"],
        [" ai "],
        ["artificial-intelligence"],
        ["Artificial-Intelligence"],
        ["artificial_intelligence"],
        ["ARTIFICIAL INTELLIGENCE".lower().replace(" ", "-")],
    ],
)
def test_case_and_format_variants_map_consistently(tags: list[str]) -> None:
    assert categorize_from_tags(tags) == EventCategory.AI


def test_underscore_and_space_variants_normalize_same_as_hyphen() -> None:
    hyphen = categorize_from_tags(["open-source", "coding"])
    underscore = categorize_from_tags(["open_source", "coding"])
    space = categorize_from_tags(["open source", "coding"])
    assert hyphen == underscore == space == EventCategory.SOFTWARE


# Priority order: a specific bucket wins over the broad AI catch-all when both are present -
# proves this is not a silent "everything = AI" fallback (explicitly forbidden by the M2
# contract). Mirrors real source-pack entries, e.g. nvidia_blog: ['ai', 'gpu', 'hardware',
# 'robotics', 'nvidia'].
def test_specific_category_wins_over_ai_when_both_tags_present() -> None:
    assert categorize_from_tags(["ai", "gpu", "hardware", "nvidia"]) == EventCategory.HARDWARE
    assert categorize_from_tags(["ai", "security", "openai"]) == EventCategory.CYBERSECURITY
    assert categorize_from_tags(["ai", "startup", "business"]) == EventCategory.STARTUPS


# H. No provider/LLM calls - structural proof: this module imports nothing from the LLM
# Gateway or any capability.
def test_module_imports_no_llm_gateway_or_capability() -> None:
    import inspect

    import services.event_category as module

    source_text = inspect.getsource(module)
    for forbidden in ("llm_gateway", "capabilities.", "call_generate"):
        assert forbidden not in source_text
