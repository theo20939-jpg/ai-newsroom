"""Phase 18.10 M1/M2: pure, tier-1 unit tests for services.story_memory - no DB, no LLM. Covers
signature extraction (entities/keywords/topic_bucket) and the pure scoring function directly.
See tests/test_story_memory_integration.py for the full match_story() outcome tests (new_story/
story_update/semantic_duplicate/uncertain_match), which need real Story rows in the database.
"""
from uuid import uuid4

import pytest

from database.models.news_event import EventCategory
from database.models.story import Story
from services.story_memory import (
    NEW_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    TOPIC_CORPORATE,
    TOPIC_FINANCIAL,
    TOPIC_LEGAL_REGULATORY,
    TOPIC_OTHER,
    TOPIC_PRODUCT,
    TOPIC_SECURITY_INCIDENT,
    UNCERTAIN_MATCH,
    extract_story_signature,
    score_candidate,
)


# --- topic classification ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected_bucket",
    [
        ("OpenAI releases GPT-X", TOPIC_PRODUCT),
        ("OpenAI reveals GPT-X benchmarks", TOPIC_PRODUCT),
        ("Company unveils new AI chip", TOPIC_PRODUCT),
        ("Компания представила новую модель ИИ", TOPIC_PRODUCT),
        ("Startup raises $50M in Series B funding", TOPIC_FINANCIAL),
        ("Company reports quarterly earnings decline", TOPIC_FINANCIAL),
        ("Компания привлекла инвестиции в новом раунде", TOPIC_FINANCIAL),
        ("OpenAI CEO comments on regulation", TOPIC_LEGAL_REGULATORY),
        ("Regulator opens antitrust investigation into Big Tech", TOPIC_LEGAL_REGULATORY),
        ("Company appoints new CEO after board shakeup", TOPIC_CORPORATE),
        ("Two firms announce merger", TOPIC_CORPORATE),
        ("Hackers exploit vulnerability in popular app", TOPIC_SECURITY_INCIDENT),
        ("Data breach exposes millions of user records", TOPIC_SECURITY_INCIDENT),
        ("A cat sat on a mat", TOPIC_OTHER),
    ],
)
def test_topic_classification(title: str, expected_bucket: str) -> None:
    signature = extract_story_signature(title, EventCategory.AI)
    assert signature.topic_bucket == expected_bucket


def test_legal_regulatory_takes_priority_over_product_keywords_in_the_same_title() -> None:
    """False-positive protection worked example: a title that could plausibly match both
    "product" and "legal_regulatory" keywords must classify as the more specific bucket."""
    signature = extract_story_signature("Regulator opens probe into new AI chip launch", EventCategory.AI)
    assert signature.topic_bucket == TOPIC_LEGAL_REGULATORY


# --- entity/keyword extraction ------------------------------------------------------------------


def test_entities_extracted_as_capitalized_runs() -> None:
    signature = extract_story_signature("OpenAI releases GPT-X for developers", EventCategory.AI)
    # Normalized (casefolded) - compare case-insensitively via membership on the normalized set.
    assert any("openai" in e for e in signature.entities)
    assert any("gpt" in e for e in signature.entities)


def test_entities_are_deduplicated() -> None:
    signature = extract_story_signature("OpenAI and OpenAI again", EventCategory.AI)
    assert len(signature.entities) == len(set(signature.entities))


def test_keywords_are_length_filtered_and_lowercased() -> None:
    signature = extract_story_signature("OpenAI Releases A New AI Model", EventCategory.AI)
    assert "releases" in signature.keywords
    assert "a" not in signature.keywords  # below min length


def test_signature_extraction_is_deterministic() -> None:
    title = "OpenAI releases GPT-X benchmarks"
    first = extract_story_signature(title, EventCategory.AI)
    second = extract_story_signature(title, EventCategory.AI)
    assert first == second


# --- score_candidate() (pure) -------------------------------------------------------------------


def _story(*, title: str, entities: list[str], topic_bucket: str) -> Story:
    return Story(
        id=uuid4(), title=title, category=EventCategory.AI, entities=entities, keywords=[],
        topic_bucket=topic_bucket, first_event_id=uuid4(), event_count=1,
    )


def test_score_candidate_high_for_shared_entities_and_similar_title() -> None:
    title = "OpenAI reveals GPT-X benchmarks"
    signature = extract_story_signature(title, EventCategory.AI)
    candidate = _story(
        title="OpenAI releases GPT-X", entities=signature.entities, topic_bucket=TOPIC_PRODUCT,
    )
    combined, entity_overlap, title_overlap = score_candidate(title, signature, candidate.title, candidate)
    assert entity_overlap > 0.5
    assert combined > 0.3


def test_score_candidate_zero_for_no_entity_overlap() -> None:
    title = "OpenAI releases GPT-X"
    signature = extract_story_signature(title, EventCategory.AI)
    candidate = _story(title="A cat sat on a mat", entities=[], topic_bucket=TOPIC_OTHER)
    combined, entity_overlap, title_overlap = score_candidate(title, signature, candidate.title, candidate)
    assert entity_overlap == 0.0


# --- outcome constants sanity (defensive - catches an accidental rename) ------------------------


def test_outcome_constants_are_distinct_strings() -> None:
    outcomes = {NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE, UNCERTAIN_MATCH}
    assert len(outcomes) == 5
