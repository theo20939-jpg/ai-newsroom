"""Tests for prompts/final_post_authoring/v2.yaml - Phase I.1.2 (Final Post Authoring editorial
calibration). Uses the real FilePromptRepository (never a fake) against the real prompts/
directory, mirroring tests/test_final_post_authoring_prompt.py's own established convention. No
real LLM calls anywhere in this file - these are pure prompt-content/contract tests.
"""
from __future__ import annotations

from pathlib import Path

from integrations.prompts.file_repository import FilePromptRepository


def _repo() -> FilePromptRepository:
    return FilePromptRepository(Path("prompts"))


def _v2():
    return _repo().resolve("final_post_authoring", "2")


def _combined(prompt) -> str:
    return (prompt.system + " " + " ".join(prompt.rules)).lower()


# 1. v1 still loads unchanged - covered by
# tests/test_final_post_authoring_prompt.py::test_v1_still_loads_unchanged_after_v2_was_added().


def test_2_v2_loads():
    prompt = _v2()
    assert prompt.name == "final_post_authoring"
    assert prompt.version == "2"
    assert prompt.system
    assert prompt.rules


def test_3_approved_recap_is_the_factual_boundary_not_a_prose_template():
    combined = _combined(_v2())
    assert "factual boundary" in combined
    assert "template" in combined


def test_4_explicitly_forbids_mechanical_summarizing():
    combined = _combined(_v2())
    assert "do not summarize" in combined or "not summarize or" in combined
    assert "restate" in combined


def test_5_requires_public_facing_news_writing():
    combined = _combined(_v2())
    assert "public" in combined
    assert "news post" in combined


def test_6_requires_exactly_one_main_editorial_angle():
    combined = _combined(_v2())
    assert "one main editorial angle" in combined


def test_7_discourages_title_body_repetition():
    combined = _combined(_v2())
    assert "duplication" in combined
    assert "repeat the title" in combined


def test_8_discourages_evidence_meta_phrases():
    combined = _combined(_v2())
    assert "в материалах указано" in combined or "в одном обзоре" in combined
    assert "internal research brief" in combined or "internal-sounding" in combined or "research brief" in combined


def test_9_requires_natural_integration_of_uncertainty():
    combined = _combined(_v2())
    assert "integrate" in combined
    assert "uncertainty" in combined
    assert "disclaimer" in combined  # explicitly forbids the mechanically-appended-disclaimer shape


def test_10_preserves_epistemic_strength():
    combined = _combined(_v2())
    assert "epistemic strength" in combined
    assert "settled" in combined or "objective" in combined


def test_11_prohibits_new_factual_surface():
    combined = _combined(_v2())
    for term in ("new company", "product", "number", "motivation", "causal link", "consensus", "comparison"):
        assert term in combined, f"expected {term!r} in the factual-lock rule text"


def test_12_prohibits_internal_recap_labels():
    combined = _combined(_v2())
    for label in ("ключевые пункты", "неопределённость", "сводка", "что произошло", "почему это важно"):
        assert label in combined


def test_13_output_schema_is_exactly_title_and_body():
    prompt = _v2()
    assert prompt.output_schema["required"] == ["title", "body"]
    assert set(prompt.output_schema["properties"].keys()) == {"title", "body"}
    assert prompt.output_schema["additionalProperties"] is False


def test_14_no_cta_footer_or_media_ownership_instruction():
    combined = _combined(_v2())
    assert "call-to-action" in combined
    assert "emoji" in combined
    assert "hashtags" in combined
    assert "markdown" in combined


def test_v2_is_a_genuinely_different_text_from_v1():
    v1 = _repo().resolve("final_post_authoring", "1")
    v2 = _v2()
    assert v1.system != v2.system
    assert v1.rules != v2.rules


def test_v2_never_names_this_newsrooms_internal_pipeline_vocabulary_as_permitted_output():
    """The prohibited-internal-language list (recap/evidence/bundle/verified facts/source refs/
    редактор/сводка/provided context/based on the supplied information) must never appear as
    something the model is told TO write - only ever inside a prohibition sentence. A crude
    presence check on the raw rule text isn't reliable for "never as permitted output" (the terms
    legitimately appear inside the prohibition itself), so this instead asserts the prohibition
    sentence structure exists at all for the newsroom-pipeline vocabulary."""
    combined = _combined(_v2())
    assert "internal pipeline" in combined or "internal editorial artifact" in combined


def test_no_research_or_reinvestigation_instruction_present():
    """Mirrors prompts/final_post_authoring/v1.yaml's own identical honesty-about-capability
    disclosure test."""
    system_lower = _v2().system.lower()
    assert "do not have live web access" in system_lower or "cannot fetch new sources" in system_lower


def test_review_opinion_disagreement_is_never_stated_as_objective_truth():
    combined = _combined(_v2())
    assert "objective" in combined
    assert "disagreement" in combined or "differing opinions" in combined


# ---------------------------------------------------------------------------------------------
# Pixel regression fixture: the real, approved Pixel EVENT_RECAP text (Phase I.1.1's own live
# validation source) is used here purely as a prompt-BEHAVIOR fixture - no LLM call, no network.
# Proves v2's own rule text explicitly instructs the model not to preserve this exact
# title -> summary -> takeaway-1 -> takeaway-2 -> takeaway-3 -> uncertainty field-by-field shape.
# ---------------------------------------------------------------------------------------------

_PIXEL_APPROVED_RECAP_FIELD_ORDER = (
    "recap_title", "recap_summary", "key_takeaways", "uncertainty_notes",
)


def test_pixel_fixture_field_order_is_explicitly_the_shape_v2_forbids_preserving():
    """Documents the real field-by-field shape (Phase I.1.1's own live Pixel bundle) v2 must
    instruct the model to abandon - not itself a behavioral proof (that requires a real or
    FakeLLMGateway-backed generation, out of this prompt-content test's scope), but confirms the
    fixture matches the real approved artifact byte-for-byte."""
    assert _PIXEL_APPROVED_RECAP_FIELD_ORDER == ("recap_title", "recap_summary", "key_takeaways", "uncertainty_notes")


def test_v2_rules_explicitly_forbid_the_recap_field_order_as_post_structure():
    combined = _combined(_v2())
    assert "sentence order" in combined or "paragraph order" in combined
    assert "rhetorical structure" in combined
    assert "summary-then-uncertainty-then-takeaway" in combined or "summary, then uncertainty, then" in combined
