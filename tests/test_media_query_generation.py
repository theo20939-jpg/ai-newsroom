"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 4: services.media_query_generation."""
from __future__ import annotations

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from services.media_query_generation import MAX_QUERY_VARIANTS, generate_search_queries


def _intent(**overrides) -> MediaIntent:
    defaults = dict(subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO)
    defaults.update(overrides)
    return MediaIntent(**defaults)


def test_never_exceeds_the_hard_cap() -> None:
    intent = _intent(model_name="iPhone Duo", company="Apple", event="Surprise and Shine", time_context="September 2026")
    queries = generate_search_queries(intent, max_variants=100)
    assert len(queries) <= MAX_QUERY_VARIANTS


def test_exact_identifier_combination_comes_first() -> None:
    intent = _intent(model_name="iPhone Duo", company="Apple")
    queries = generate_search_queries(intent)
    assert queries[0] == "Apple iPhone Duo"


def test_never_pads_a_thin_intent_with_junk() -> None:
    intent = _intent()  # only primary_entity set
    queries = generate_search_queries(intent)
    assert queries == ["iPhone Duo official photo", "iPhone Duo press image", "iPhone Duo"]
    assert all(q.strip() for q in queries)
    assert len(queries) == len(set(queries))  # never a duplicate query


def test_deterministic_same_intent_same_queries() -> None:
    intent = _intent(model_name="iPhone Duo", company="Apple", event="launch")
    assert generate_search_queries(intent) == generate_search_queries(intent)


def test_max_variants_is_respected_when_smaller_than_cap() -> None:
    intent = _intent(model_name="iPhone Duo", company="Apple", event="launch", time_context="2026")
    queries = generate_search_queries(intent, max_variants=2)
    assert len(queries) <= 2
