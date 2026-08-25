"""Tests for prompts/final_post_authoring/v1.yaml - Phase I.1. Uses the real FilePromptRepository
(never a fake) against the real prompts/ directory, mirroring tests/test_event_recap.py's own
established "resolve the real file" convention (e.g. test_e_file_prompt_repository_resolves_
event_recap_v3()). See tests/test_final_post_authoring_prompt_v2.py for v2's own contract tests
(Phase I.1.2)."""
from __future__ import annotations

from pathlib import Path

from integrations.prompts.file_repository import FilePromptRepository


def _repo() -> FilePromptRepository:
    return FilePromptRepository(Path("prompts"))


def test_v1_is_loadable_and_resolves_by_explicit_version():
    repo = _repo()
    prompt = repo.resolve("final_post_authoring", "1")
    assert prompt.name == "final_post_authoring"
    assert prompt.version == "1"
    assert prompt.system
    assert prompt.rules


def test_v1_still_loads_unchanged_after_v2_was_added():
    """Phase I.1.2: v1 must remain byte-identical and independently resolvable after v2 exists -
    prompt immutability, never a silent replace/delete."""
    prompt = _repo().resolve("final_post_authoring", "1")
    assert prompt.version == "1"
    assert prompt.output_schema["required"] == ["title", "body"]


def test_file_repository_latest_resolution_now_points_at_v2():
    """FilePromptRepository's own `resolve(name)` (no version) always returns the highest declared
    version - this is a property of the repository, not a production default: the real active
    version for FinalPostAuthoringCapability is governed by
    core.config.settings.final_post_authoring_prompt_version (defaults "2" as of Phase I.1.4), read
    explicitly at call time - see tests/test_final_post_authoring_capability.py's own
    version-selection tests."""
    repo = _repo()
    assert repo.resolve("final_post_authoring") == repo.resolve("final_post_authoring", "2")


def test_prompt_family_is_separate_from_copywriting_and_event_recap():
    """A genuinely new, distinct prompt family - never a shared name with prompts/copywriting/*
    or prompts/event_recap/* (instruction item 3)."""
    repo = _repo()
    final_post = repo.resolve("final_post_authoring", "1")
    copywriting = repo.resolve("copywriting")
    event_recap = repo.resolve("event_recap")
    assert final_post.name not in (copywriting.name, event_recap.name)
    assert final_post.system != copywriting.system
    assert final_post.system != event_recap.system


def test_output_schema_is_exactly_title_and_body():
    prompt = _repo().resolve("final_post_authoring", "1")
    assert prompt.output_schema["required"] == ["title", "body"]
    assert set(prompt.output_schema["properties"].keys()) == {"title", "body"}
    assert prompt.output_schema["additionalProperties"] is False


def test_approved_recap_is_framed_as_the_source_of_truth():
    prompt = _repo().resolve("final_post_authoring", "1")
    system_lower = prompt.system.lower()
    assert "approved" in system_lower
    assert "source of truth" in system_lower


def test_supporting_evidence_is_framed_as_a_guardrail_not_an_invitation_to_reinvestigate():
    prompt = _repo().resolve("final_post_authoring", "1")
    combined = (prompt.system + " " + " ".join(prompt.rules)).lower()
    assert "guardrail" in combined
    assert "never an invitation" in combined or "not an invitation" in combined


def test_prompt_requests_public_facing_copy_not_an_internal_artifact():
    prompt = _repo().resolve("final_post_authoring", "1")
    system_lower = prompt.system.lower()
    assert "public" in system_lower
    assert "internal" in system_lower  # explicitly contrasts against internal artifacts


def test_internal_recap_labels_are_explicitly_prohibited():
    combined = " ".join(_repo().resolve("final_post_authoring", "1").rules)
    assert "key takeaways" in combined.lower() or "ключевые пункты" in combined.lower()
    assert "heading" in combined.lower()


def test_no_research_or_reinvestigation_instruction_present():
    """The prompt must never instruct the model to fetch new sources or re-investigate the
    underlying Story - mirrors prompts/event_recap/v3.yaml's own honesty-about-capability
    disclosure."""
    system_lower = _repo().resolve("final_post_authoring", "1").system.lower()
    assert "do not have live web access" in system_lower or "cannot fetch new sources" in system_lower


def test_no_cta_or_footer_or_source_attribution_instruction():
    combined = " ".join(_repo().resolve("final_post_authoring", "1").rules).lower()
    assert "call-to-action" in combined or "footer" in combined
