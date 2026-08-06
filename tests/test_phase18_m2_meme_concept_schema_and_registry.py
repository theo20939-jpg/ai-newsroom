"""Phase 18 M2: schema, migration-chain, capability-registration, and workflow-registration
sanity tests. No DB required - MemeCandidate persistence itself
(services/meme_candidate_service.py) needs a real Postgres connection and is not covered here
(same disclosed constraint as docs/phase18_m1_meme_opportunity_report.md §4 - the local stack is
unavailable in this session); everything checkable offline is checked here.
"""
from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError

from capabilities.capability_mapping import resolve_ai_capability
from capabilities.meme_concept_capability import MEME_CONCEPT_CAPABILITY_DEFINITION
from database.models.ai_execution import AICapability
from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from schemas.meme_concept import MemeConcept, MemeFormat
from schemas.workflow import WorkflowType

_VALID_KWARGS = dict(
    premise="p", setup="s", punchline="pl", humor_mechanism="irony", visual_scene="scene",
    characters_objects=["a"], text_overlay_intent="intent", source_fact_links=["fact 1"],
    forbidden_interpretations=[], meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
)


def test_meme_concept_is_frozen() -> None:
    concept = MemeConcept(**_VALID_KWARGS)
    with pytest.raises(ValidationError):
        concept.premise = "changed"  # type: ignore[misc]


def test_meme_concept_requires_at_least_one_source_fact_link() -> None:
    kwargs = {**_VALID_KWARGS, "source_fact_links": []}
    with pytest.raises(ValidationError):
        MemeConcept(**kwargs)


def test_meme_concept_rejects_unknown_field() -> None:
    kwargs = {**_VALID_KWARGS, "unexpected_field": "x"}
    with pytest.raises(ValidationError):
        MemeConcept(**kwargs)


def test_meme_concept_capability_maps_to_creative_ai_capability() -> None:
    """docs/phase18_m0_meme_discovery_report.md §4.3's own architecture decision: reuse the
    already-declared-but-unused AICapability.CREATIVE value, zero new enum member/migration."""
    assert resolve_ai_capability("meme_concept") == AICapability.CREATIVE


def test_meme_concept_capability_definition_expected_output_keys_match_schema() -> None:
    assert set(MEME_CONCEPT_CAPABILITY_DEFINITION.expected_output_keys) == set(MemeConcept.model_fields) - {
        "schema_version"
    }


def test_workflow_type_meme_generation_declared() -> None:
    assert WorkflowType.MEME_GENERATION.value == "MEME_GENERATION"


def test_workflow_type_meme_generation_registered_as_of_m4() -> None:
    """Registered in workflows/registry.py as of Phase 18 M4 (docs/
    phase18_m4_meme_copywriting_report.md) - concept+safety+copy is a coherent, independently
    useful chain. Superseded the M2-era "declared but unregistered, mirrors DAILY_DIGEST"
    expectation once M4 landed - see workflows/definitions/meme_generation.py's own docstring."""
    from workflows.registry import build_registry as build_workflow_registry

    registry = build_workflow_registry()
    definition = registry.resolve(WorkflowType.MEME_GENERATION)
    assert definition.name == WorkflowType.MEME_GENERATION


def test_meme_generation_workflow_definition_steps() -> None:
    from workflows.definitions.meme_generation import DEFINITION

    assert DEFINITION.name == WorkflowType.MEME_GENERATION
    expected = ["research", "intelligence", "meme_concept", "meme_copywriting"]
    assert [s.name for s in DEFINITION.steps] == expected
    assert [s.capability for s in DEFINITION.steps] == expected


def test_meme_candidate_model_default_status_is_concept_generated() -> None:
    """SQLAlchemy column `default=` only applies at flush/INSERT time, not at bare Python
    construction - so this checks the declared column default metadata directly rather than
    instantiating without a session (which would just be None), avoiding a live DB connection."""
    assert MemeCandidate.__table__.columns["status"].default.arg == MemeCandidateStatus.CONCEPT_GENERATED
    assert MemeCandidate.__table__.columns["concept_regeneration_count"].default.arg == 0
    assert MemeCandidate.__table__.columns["published"].default.arg is False


def test_alembic_migration_chain_has_a_single_head_including_meme_candidates() -> None:
    """Confirms the meme_candidates migration is a valid, linear link in the chain (no branch
    created there) - runnable offline, alembic only reads migration files for `heads`/`history`,
    no DB connection required.

    Phase 18.10 extended the chain past meme_candidates (M9's ai_capability enum fix, M1/M2's
    story-memory tables) - meme_candidates is therefore an ancestor revision, not the current
    head, checked via `alembic history` instead of `alembic heads`. The single-head assertion
    (no branch, anywhere in the chain) still holds and is still checked directly."""
    heads_result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], capture_output=True, text=True, cwd=".",
    )
    assert heads_result.returncode == 0, heads_result.stderr
    assert heads_result.stdout.count("(head)") == 1  # exactly one head - no branch, ever

    history_result = subprocess.run(
        [sys.executable, "-m", "alembic", "history"], capture_output=True, text=True, cwd=".",
    )
    assert history_result.returncode == 0, history_result.stderr
    assert "21177d5b859e" in history_result.stdout  # meme_candidates is still in the chain
