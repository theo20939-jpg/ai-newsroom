"""Phase 19 M3: pure, tier-1 unit tests for services.editorial_planning_deterministic - no DB, no
network, no LLM."""
from services.editorial_planning_deterministic import build_deterministic_plan

_ALL_FIELDS = {
    "central_fact", "what_changed", "what_is_new", "why_it_matters", "essential_facts",
    "secondary_facts_omittable", "necessary_background", "already_published_summary",
    "must_not_repeat", "story_classification", "headline_emphasis", "opening_emphasis",
    "what_remains_unknown", "verified_quote_text", "media_role_needed", "editorial_risks",
}


def test_produces_all_sixteen_fields() -> None:
    plan = build_deterministic_plan(title="A real headline")
    assert set(plan.keys()) == _ALL_FIELDS


def test_central_fact_and_headline_emphasis_use_the_title() -> None:
    plan = build_deterministic_plan(title="Company Ships New Product")
    assert plan["central_fact"] == "Company Ships New Product"
    assert plan["headline_emphasis"] == "Company Ships New Product"
    assert plan["what_is_new"] == "Company Ships New Product"


def test_never_fabricates_a_quote() -> None:
    plan = build_deterministic_plan(title="t")
    assert plan["verified_quote_text"] is None


def test_never_claims_media_role_deterministically() -> None:
    plan = build_deterministic_plan(title="t")
    assert plan["media_role_needed"] == "none"


def test_story_classification_maps_from_match_type() -> None:
    assert build_deterministic_plan(title="t", story_match_type="new_story")["story_classification"] == "new_story"
    assert build_deterministic_plan(title="t", story_match_type="story_update")["story_classification"] == "update"
    assert build_deterministic_plan(title="t", story_match_type="supporting_source")["story_classification"] == "confirmation"
    assert build_deterministic_plan(title="t", story_match_type="semantic_duplicate")["story_classification"] == "confirmation"
    assert build_deterministic_plan(title="t", story_match_type="uncertain_match")["story_classification"] == "analysis"


def test_story_classification_defaults_to_new_story_without_match_type() -> None:
    assert build_deterministic_plan(title="t")["story_classification"] == "new_story"


def test_research_facts_copied_into_essential_facts() -> None:
    plan = build_deterministic_plan(title="t", research_facts=["fact one", "fact two"])
    assert plan["essential_facts"] == ["fact one", "fact two"]
    assert plan["secondary_facts_omittable"] == []


def test_known_evidence_gaps_copied_into_editorial_risks() -> None:
    plan = build_deterministic_plan(title="t", known_evidence_gaps=["single_source_only"])
    assert plan["editorial_risks"] == ["single_source_only"]


def test_never_raises_on_empty_inputs() -> None:
    plan = build_deterministic_plan(title="")
    assert plan["central_fact"] == ""


def test_optional_fields_stay_null_never_guessed() -> None:
    plan = build_deterministic_plan(title="t")
    assert plan["what_changed"] is None
    assert plan["necessary_background"] is None
    assert plan["already_published_summary"] is None
    assert plan["must_not_repeat"] is None
    assert plan["what_remains_unknown"] is None
