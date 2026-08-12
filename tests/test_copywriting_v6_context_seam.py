"""Offline proof suite for the Phase 19 overnight A/B/C validation seam (BusinessContext.
editorial_plan_context / prior_coverage_context -> CopywritingCapability -> prompts/copywriting/
v6.yaml). Required before any real paid canary run, per the seam's own authorization.

Naming note: the authorization's checklist refers to "V5" throughout, but the repository's own
prompt-immutability rule (prompts/copywriting/v5.yaml touched by exactly one commit, its own
creation - "no existing prompt version was ever edited") means the actual context-aware version
built here is v6, a new immutable file, never an edit of v5. Every test below that the checklist
labels "V5" is written against v6 - the next-immutable-version fallback the authorization itself
explicitly permits. v5 itself is asserted untouched (test_v5_still_behaves_exactly_as_before).

Unit-tier only: FakeLLMGateway + FakePromptRepository, mirroring tests/test_copywriting_
capability.py's own established convention - no real provider, no real DB, no real cost.
"""
import inspect
from pathlib import Path
from uuid import uuid4

import pytest

from capabilities.copywriting_capability import CAPABILITY_NAME, CopywritingCapability
from database.models.editorial_task import TaskPriority
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    CapabilityUsage,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from services.editorial_plan_serializer import serialize_editorial_plan
from services.story_context_serializer import serialize_prior_coverage
from services.story_context import StoryTimelineEntry
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
}
_VALID_OUTPUT = {"title": "x"}

_REAL_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _fake_repository(version: str, *, rules: list[str] | None = None) -> FakePromptRepository:
    repo = FakePromptRepository()
    repo.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version=version,
            system="fake system prompt", rules=rules or ["fake rule"], output_schema=_OUTPUT_SCHEMA,
        )
    )
    return repo


def _context(*, editorial_plan_context: str | None = None, prior_coverage_context: str | None = None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Example headline", summary=None, content="Example body.",
                url=None, category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="content_generation", workflow_version=1, completed_steps=[],
            ),
            language="en",
            editorial_plan_context=editorial_plan_context,
            prior_coverage_context=prior_coverage_context,
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.B, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def _request_text(gateway: FakeLLMGateway) -> str:
    return "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )


# --- A: existing BusinessContext callers still validate unchanged ---------------------------

def test_a_business_context_without_new_fields_still_constructs() -> None:
    ctx = _context()  # neither field supplied
    assert ctx.business.editorial_plan_context is None
    assert ctx.business.prior_coverage_context is None


# --- B/C: V4 ignores the new fields completely, even if supplied ----------------------------

@pytest.mark.asyncio
async def test_b_v4_context_text_has_no_plan_or_coverage_markers_when_fields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "4")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("4"))
    await capability.execute(_context())
    text = _request_text(gateway)
    assert "EDITORIAL PLAN" not in text
    assert "PRIOR COVERAGE" not in text


@pytest.mark.asyncio
async def test_c_v4_ignores_new_fields_even_when_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "4")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("4"))
    await capability.execute(_context(
        editorial_plan_context="central_fact: should never appear",
        prior_coverage_context="story_match_type: should never appear",
    ))
    text = _request_text(gateway)
    assert "should never appear" not in text
    assert "EDITORIAL PLAN" not in text
    assert "PRIOR COVERAGE" not in text


def test_v5_still_behaves_exactly_as_before_untouched_file() -> None:
    """v5.yaml itself was never edited - git history shows exactly one commit (its own
    creation). This is a repo-state assertion, not a behavioral one."""
    import subprocess
    result = subprocess.run(
        ["git", "log", "--oneline", "--", "prompts/copywriting/v5.yaml"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    commits = [line for line in result.stdout.strip().splitlines() if line]
    assert len(commits) == 1, f"v5.yaml must be touched by exactly its creation commit, found: {commits}"


@pytest.mark.asyncio
async def test_v5_also_ignores_new_fields_even_when_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    """v5 gets the identical treatment as v4 for these fields - only v6 ever reads them."""
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "5")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("5"))
    await capability.execute(_context(
        editorial_plan_context="should never appear for v5 either",
        prior_coverage_context="should never appear for v5 either",
    ))
    text = _request_text(gateway)
    assert "should never appear" not in text


# --- D/E: v6 (the context-aware version) includes each block only when present --------------

@pytest.mark.asyncio
async def test_d_v6_includes_editorial_plan_only_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("6"))
    await capability.execute(_context(editorial_plan_context="central_fact: a real plan fact"))
    text = _request_text(gateway)
    assert "EDITORIAL PLAN:" in text
    assert "central_fact: a real plan fact" in text
    assert "PRIOR COVERAGE" not in text  # not supplied this call


@pytest.mark.asyncio
async def test_e_v6_includes_prior_coverage_only_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("6"))
    await capability.execute(_context(prior_coverage_context="story_match_type: story_update"))
    text = _request_text(gateway)
    assert "PRIOR COVERAGE / STORY CONTEXT:" in text
    assert "story_match_type: story_update" in text
    assert "EDITORIAL PLAN" not in text  # not supplied this call


# --- F: no-plan/no-memory v6 still works normally --------------------------------------------

@pytest.mark.asyncio
async def test_f_v6_with_both_fields_none_still_succeeds_with_no_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("6"))
    result = await capability.execute(_context())
    assert result.status == "SUCCESS"
    text = _request_text(gateway)
    assert "EDITORIAL PLAN" not in text
    assert "PRIOR COVERAGE" not in text


# --- G: plan serializer is deterministic and bounded ------------------------------------------

def test_g_plan_serializer_is_deterministic() -> None:
    plan = {
        "central_fact": "Company X launched product Y.",
        "story_classification": "new_story",
        "what_changed": None,
        "why_it_matters": "Significant market impact.",
        "essential_facts": ["fact one", "fact two"],
        "secondary_facts_omittable": [],
        "necessary_background": None,
        "already_published_summary": None,
        "must_not_repeat": None,
        "what_remains_unknown": None,
        "media_role_needed": "none",
        "editorial_risks": [],
    }
    first = serialize_editorial_plan(plan)
    second = serialize_editorial_plan(plan)
    assert first == second
    assert "Company X launched product Y." in first


def test_g_plan_serializer_is_bounded() -> None:
    huge_fact = "x" * 5000
    plan = {"central_fact": huge_fact, "essential_facts": [f"fact {i}" for i in range(50)]}
    result = serialize_editorial_plan(plan)
    assert len(result) < 4000  # bounded, not the full 5000+ raw input
    assert "more, omitted for length" in result


# --- H: story-context serializer is deterministic and bounded --------------------------------

def _entry(event_id, *, published_at, delta="new_information", already_published=False, match_type="story_update"):
    return StoryTimelineEntry(
        event_id=event_id, source="Example Source", published_at=published_at, collected_at=published_at,
        match_type=match_type, match_score=0.9, source_role=None, content_draft_id=None,
        telegram_message_id=None, delta=delta, already_published=already_published,
        introduced_new_facts=["launch_date"], confirmed_existing_facts=["product_x"],
    )


def test_h_story_context_serializer_is_deterministic_and_bounded() -> None:
    from datetime import datetime, timezone
    current_id = uuid4()
    prior_id = uuid4()
    timeline = [
        _entry(prior_id, published_at=datetime(2026, 8, 1, tzinfo=timezone.utc), already_published=True),
        _entry(current_id, published_at=datetime(2026, 8, 7, tzinfo=timezone.utc)),
    ]
    first = serialize_prior_coverage(timeline, current_event_id=current_id, match_type="story_update", match_score=0.9)
    second = serialize_prior_coverage(timeline, current_event_id=current_id, match_type="story_update", match_score=0.9)
    assert first == second
    assert first is not None
    assert "PUBLISHED TO TELEGRAM" in first
    assert len(first) < 4000


# --- I: uncertain Story Memory remains visibly uncertain --------------------------------------

def test_i_uncertain_match_stays_visibly_uncertain() -> None:
    from datetime import datetime, timezone
    current_id = uuid4()
    prior_id = uuid4()
    timeline = [
        _entry(prior_id, published_at=datetime(2026, 8, 1, tzinfo=timezone.utc), match_type="uncertain_match"),
        _entry(current_id, published_at=datetime(2026, 8, 7, tzinfo=timezone.utc), match_type="uncertain_match"),
    ]
    result = serialize_prior_coverage(timeline, current_event_id=current_id, match_type="uncertain_match", match_score=0.4)
    assert result is not None
    assert "UNCERTAIN" in result


# --- J: no previous coverage -> no fake memory -------------------------------------------------

def test_j_no_match_type_returns_none() -> None:
    from datetime import datetime, timezone
    current_id = uuid4()
    timeline = [_entry(current_id, published_at=datetime(2026, 8, 7, tzinfo=timezone.utc))]
    assert serialize_prior_coverage(timeline, current_event_id=current_id, match_type=None, match_score=None) is None


def test_j_empty_timeline_returns_none() -> None:
    current_id = uuid4()
    assert serialize_prior_coverage([], current_event_id=current_id, match_type="new_story", match_score=1.0) is None


def test_j_no_prior_entries_before_current_returns_none() -> None:
    """Only the current event itself is in the timeline (a genuinely new story) - no prior
    coverage should ever be fabricated."""
    from datetime import datetime, timezone
    current_id = uuid4()
    timeline = [_entry(current_id, published_at=datetime(2026, 8, 7, tzinfo=timezone.utc), match_type="new_story")]
    result = serialize_prior_coverage(timeline, current_event_id=current_id, match_type="new_story", match_score=1.0)
    assert result is None


# --- K: CopywritingCapability performs no new DB query (structural) --------------------------

def test_k_execute_signature_has_no_session_parameter() -> None:
    sig = inspect.signature(CopywritingCapability.execute)
    assert list(sig.parameters.keys()) == ["self", "context"]


def test_k_copywriting_capability_module_has_no_db_session_import() -> None:
    import capabilities.copywriting_capability as mod
    source = inspect.getsource(mod)
    assert "AsyncSession" not in source
    assert "session" not in source.lower()  # no session-querying identifiers anywhere


# --- L: no new provider bypass - import set is unchanged except nothing new ------------------

def test_l_copywriting_capability_imports_no_new_provider_or_serializer_modules() -> None:
    import capabilities.copywriting_capability as mod
    source = inspect.getsource(mod)
    assert "editorial_plan_serializer" not in source
    assert "story_context_serializer" not in source
    assert "import services.story_context" not in source


# --- M: FakeGateway-only capability tests pass (covered by running the full existing suite,
# see the offline-tests report - not re-duplicated here) --------------------------------------


# --- N: production content_worker call path remains unchanged --------------------------------

def test_n_capability_executor_never_sets_new_context_fields() -> None:
    import capabilities.executor as executor_mod
    source = inspect.getsource(executor_mod)
    assert "editorial_plan_context=" not in source
    assert "prior_coverage_context=" not in source


# --- O: current default Copywriting remains V4 -------------------------------------------------

def test_o_default_copywriting_prompt_version_is_still_4() -> None:
    from core.config import Settings
    assert Settings.model_fields["copywriting_prompt_version"].default == "4"


def _valid_response():
    from integrations.llm_gateway.protocol import GenerateResponse
    return GenerateResponse(
        text=None, structured_output=_VALID_OUTPUT, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


# --- Bonus: prove the real FilePromptRepository (not fake) resolves v6 correctly, with the
# same output_schema as v5 (structured-output shape unchanged) ---------------------------------

# --- P: Phase 20 M9 - Delta Engine context serializer is deterministic, bounded, and additive ---

def test_p_delta_engine_serializer_is_deterministic() -> None:
    from services.story_confidence import HIGH
    from services.story_context_serializer import serialize_delta_engine_context
    from services.story_delta_engine import MATERIAL_UPDATE, DeltaResult

    delta = DeltaResult(
        MATERIAL_UPDATE, new_material_claims=["92%"], new_keywords=["benchmark"],
        max_title_overlap_vs_prior=0.6, reason="genuinely new material claim(s): ['92%']",
    )
    first = serialize_delta_engine_context(delta_result=delta, confidence_band=HIGH, would_suppress=False)
    second = serialize_delta_engine_context(delta_result=delta, confidence_band=HIGH, would_suppress=False)
    assert first == second
    assert "delta_classification: material_update" in first
    assert "92%" in first
    assert "would_suppress_as_duplicate" in first
    assert "False" in first


def test_p_delta_engine_serializer_is_bounded() -> None:
    from services.story_confidence import MEDIUM
    from services.story_context_serializer import serialize_delta_engine_context
    from services.story_delta_engine import UNCERTAIN_DELTA, DeltaResult

    delta = DeltaResult(
        UNCERTAIN_DELTA, new_keywords=[f"keyword{i}" for i in range(50)],
        max_title_overlap_vs_prior=0.4, reason="ambiguous",
    )
    result = serialize_delta_engine_context(delta_result=delta, confidence_band=MEDIUM, would_suppress=False)
    assert result.count("keyword") <= 9  # 8 bounded items + the word "new_keywords" itself


def test_p_delta_engine_serializer_never_claims_suppression_is_enforced() -> None:
    """The exact language matters here - this is a shadow-only proposal, and the text must say
    so explicitly every time, not just when true, since a future reader/reviewer of raw prompt
    text should never mistake this for an active suppression mechanism."""
    from services.story_confidence import LOW
    from services.story_context_serializer import serialize_delta_engine_context
    from services.story_delta_engine import NO_NEW_FACTS, DeltaResult

    delta = DeltaResult(NO_NEW_FACTS, max_title_overlap_vs_prior=0.9, reason="identical")
    result = serialize_delta_engine_context(delta_result=delta, confidence_band=LOW, would_suppress=True)
    assert "NOT enforced" in result


# --- Q: Delta Engine serializer stays out of the live capability path, same as story_context_
# serializer's own existing isolation guarantee (test_l/_n above) --------------------------------

def test_q_copywriting_capability_does_not_import_delta_engine_modules() -> None:
    import capabilities.copywriting_capability as mod
    source = inspect.getsource(mod)
    assert "story_delta_engine" not in source
    assert "story_suppression" not in source
    assert "story_confidence" not in source


def test_q_capability_executor_does_not_import_delta_engine_modules() -> None:
    import capabilities.executor as executor_mod
    source = inspect.getsource(executor_mod)
    assert "story_delta_engine" not in source
    assert "story_suppression" not in source


def test_real_file_prompt_repository_resolves_v6_with_v5s_output_schema() -> None:
    repo = FilePromptRepository(_REAL_PROMPTS_ROOT)
    v5 = repo.resolve(CAPABILITY_NAME, "5")
    v6 = repo.resolve(CAPABILITY_NAME, "6")
    assert v6.version == "6"
    assert v6.output_schema == v5.output_schema
    assert len(v6.rules) > len(v5.rules)  # v6 adds plan/coverage rules on top of v5's own


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (Case F, docs/news_output_stability_forensic_report.md §7/§13 item 2):
# v8.6 was entirely missing from _build_request()'s version-gated context-injection tuple - would
# have silently dropped EDITORIAL PLAN/PRIOR COVERAGE context the moment v8.6 went live, a real
# regression this activation would otherwise have introduced (v8.5 already included them).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v86_includes_editorial_plan_and_prior_coverage_same_as_v85(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.6")
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _fake_repository("8.6"))
    await capability.execute(_context(
        editorial_plan_context="central_fact: a real plan fact",
        prior_coverage_context="story_match_type: story_update",
    ))
    text = _request_text(gateway)
    assert "EDITORIAL PLAN:" in text
    assert "central_fact: a real plan fact" in text
    assert "PRIOR COVERAGE / STORY CONTEXT:" in text
    assert "story_match_type: story_update" in text
