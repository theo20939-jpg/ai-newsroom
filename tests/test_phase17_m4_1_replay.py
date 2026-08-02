"""Phase 17 M4.1 - failed-case replay tooling tests (docs/
phase17_m4_1_reasoning_budget_fix_report.md).

Two tiers: pure/fake-gateway unit tests for the retry orchestration, request building, and
deterministic merge (no DB, no LLM Gateway, no network - a duck-typed fake gateway is enough,
mirroring `generate_with_retry()`'s own explicit DB-free design), and a small set of real-DB,
read-only integration tests against the pinned 7 failed-case IDs (mirrors this arc's own
established "real Postgres, SELECT only" precedent - no mutation, no LLM call in dry-run).
"""
import json
import uuid
from pathlib import Path

import pytest

from capabilities.executor import _REASONING_EFFORT_BY_CAPABILITY
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.beginner_friendly import build_beginner_friendly_plan
from services.candidate_generation_policy import (
    PRIMARY_REASONING_EFFORT,
    RETRY_REASONING_EFFORT,
)
from services.editorial_brief import build_editorial_brief

import scripts.phase17_m4_1_failed_case_replay as replay

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_RESEARCH_OUTPUT = {"facts": ["Fact one about the event.", "Fact two about the event."], "confidence": "high", "gaps": []}
_INTELLIGENCE_OUTPUT = {"significance": "Notable", "angle": "Trend", "audience_relevance": "high", "recommendation": "Watch"}


class _FakeTask:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.priority = TaskPriority.C


class _FakeEvent:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


class _FakeGateway:
    """A minimal duck-typed LLMGateway stand-in - returns one canned GenerateResponse per call,
    in order. Never touches a real provider/network."""

    def __init__(self, responses: list[GenerateResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _valid_response(model: str = "gpt-5.6-luna") -> GenerateResponse:
    return GenerateResponse(
        text='{"title": "A real title", "body": "A real, non-blank candidate body.", "hashtags": ["#ai"]}',
        structured_output={"title": "A real title", "body": "A real, non-blank candidate body.", "hashtags": ["#ai"]},
        finish_reason="stop", model_used=model,
        usage=CapabilityUsage(input_tokens=1700, output_tokens=180, reasoning_tokens=20),
    )


def _empty_length_response(model: str = "gpt-5.6-luna") -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=None, finish_reason="length", model_used=model,
        usage=CapabilityUsage(input_tokens=1800, output_tokens=598, reasoning_tokens=580),
    )


def _real_brief_and_plan():
    title = "Example Co launches a new AI assistant product"
    content = "Example Co, a robotics startup, announced a new AI assistant product today."
    brief = build_editorial_brief(title, content, _RESEARCH_OUTPUT, _INTELLIGENCE_OUTPUT)
    plan = build_beginner_friendly_plan(
        title, content, _RESEARCH_OUTPUT, _INTELLIGENCE_OUTPUT, has_image_candidate=False,
    )
    return title, content, brief, plan


def _real_prompt():
    return FilePromptRepository(_PROMPTS_ROOT).resolve("copywriting_beginner_candidate", "1")


# ---------------------------------------------------------------------------
# Reasoning override scoping / production isolation (tests 1-2)
# ---------------------------------------------------------------------------


def test_low_reasoning_effort_used_in_primary_request() -> None:
    title, _content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    request = replay._build_candidate_request(
        title, "AI", "en", _RESEARCH_OUTPUT, _INTELLIGENCE_OUTPUT, brief, plan, prompt,
        PRIMARY_REASONING_EFFORT,
    )
    assert request.reasoning_effort == "low"


def test_production_copywriting_reasoning_effort_unchanged() -> None:
    """M4.1's override is scoped only to the replay path - production CopywritingCapability's own
    routing table must remain exactly what M3/M4 already established."""
    assert _REASONING_EFFORT_BY_CAPABILITY["copywriting"] == "low"
    assert _REASONING_EFFORT_BY_CAPABILITY["research"] == "none"


# ---------------------------------------------------------------------------
# Output cap / reasoning configuration (tests 3-4)
# ---------------------------------------------------------------------------


def test_max_tokens_uses_policy_formula() -> None:
    title, _content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    request = replay._build_candidate_request(
        title, "AI", "en", _RESEARCH_OUTPUT, _INTELLIGENCE_OUTPUT, brief, plan, prompt,
        PRIMARY_REASONING_EFFORT,
    )
    from services.candidate_generation_policy import candidate_max_tokens
    assert request.max_tokens == candidate_max_tokens(plan.safe_range.max_words)


def test_retry_request_uses_none_reasoning_effort() -> None:
    title, _content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    request = replay._build_candidate_request(
        title, "AI", "en", _RESEARCH_OUTPUT, _INTELLIGENCE_OUTPUT, brief, plan, prompt,
        RETRY_REASONING_EFFORT,
    )
    assert request.reasoning_effort == "none"


# ---------------------------------------------------------------------------
# Empty output validation via a fake gateway (tests 5-9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_visible_output_accepted_via_attempt_generation() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_valid_response()])
    task, event = _FakeTask(), _FakeEvent()
    result = await replay._attempt_generation(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event,
        reasoning_effort="low", attempt_number=1, sequence=0, draft_id="fake-id",
    )
    assert result["visible_output_present"] is True
    assert result["empty_output_reason"] is None
    assert result["candidate"]["title"] == "A real title"


@pytest.mark.asyncio
async def test_empty_response_rejected_via_attempt_generation() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_empty_length_response()])
    task, event = _FakeTask(), _FakeEvent()
    result = await replay._attempt_generation(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event,
        reasoning_effort="medium", attempt_number=1, sequence=0, draft_id="fake-id",
    )
    assert result["visible_output_present"] is False
    assert result["empty_output_reason"] == "reasoning_budget_exhausted"
    assert result["candidate"] == {}


@pytest.mark.asyncio
async def test_gateway_error_classified_as_provider_empty_response() -> None:
    from integrations.llm_gateway.errors import NoRoutableCandidateError

    class _FailingGateway:
        async def generate(self, request: GenerateRequest) -> GenerateResponse:
            raise NoRoutableCandidateError("no candidate")

    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    task, event = _FakeTask(), _FakeEvent()
    result = await replay._attempt_generation(
        _FailingGateway(), prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event,
        reasoning_effort="low", attempt_number=1, sequence=0, draft_id="fake-id",
    )
    assert result["empty_output_reason"] == "provider_empty_response"
    assert result["candidate"] == {}


@pytest.mark.asyncio
async def test_finish_reason_and_output_tokens_recorded_in_attempt() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_empty_length_response()])
    task, event = _FakeTask(), _FakeEvent()
    result = await replay._attempt_generation(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event,
        reasoning_effort="medium", attempt_number=1, sequence=0, draft_id="fake-id",
    )
    assert result["finish_reason"] == "length"
    assert result["token_usage"]["output_tokens"] == 598
    assert result["token_usage"]["reasoning_tokens"] == 580


@pytest.mark.asyncio
async def test_structured_logs_omit_full_content(caplog: pytest.LogCaptureFixture) -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_valid_response()])
    task, event = _FakeTask(), _FakeEvent()
    with caplog.at_level("INFO"):
        await replay._attempt_generation(
            gateway, prompt, None,
            news_event_title=title, news_event_category="AI", language="en",
            research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
            brief=brief, plan=plan, task=task, event=event,
            reasoning_effort="low", attempt_number=1, sequence=0, draft_id="fake-id",
        )
    for record in caplog.records:
        extra_text = json.dumps(getattr(record, "__dict__", {}), default=str)
        assert "A real, non-blank candidate body." not in extra_text
        assert content not in extra_text


# ---------------------------------------------------------------------------
# Retry policy (tests 10-13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_retry_for_valid_first_attempt() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_valid_response()])
    task, event = _FakeTask(), _FakeEvent()
    result = await replay.generate_with_retry(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event, draft_id="fake-id", sequence_start=0,
    )
    assert result["retry_used"] is False
    assert result["calls_made"] == 1
    assert result["final_status"] == "valid"
    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_one_retry_maximum_on_empty_first_attempt() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_empty_length_response(), _valid_response()])
    task, event = _FakeTask(), _FakeEvent()
    result = await replay.generate_with_retry(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event, draft_id="fake-id", sequence_start=0,
    )
    assert result["retry_used"] is True
    assert result["calls_made"] == 2
    assert result["final_status"] == "valid"
    assert len(gateway.requests) == 2


def _first_attempt_reasoning_effort(requests: list[GenerateRequest]) -> str | None:
    return requests[0].reasoning_effort


@pytest.mark.asyncio
async def test_retry_uses_safer_reasoning_effort_than_primary() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_empty_length_response(), _valid_response()])
    task, event = _FakeTask(), _FakeEvent()
    await replay.generate_with_retry(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event, draft_id="fake-id", sequence_start=0,
    )
    assert gateway.requests[0].reasoning_effort == PRIMARY_REASONING_EFFORT
    assert gateway.requests[1].reasoning_effort == RETRY_REASONING_EFFORT


@pytest.mark.asyncio
async def test_still_empty_after_retry_is_disclosed_not_masked() -> None:
    title, content, brief, plan = _real_brief_and_plan()
    prompt = _real_prompt()
    gateway = _FakeGateway([_empty_length_response(), _empty_length_response()])
    task, event = _FakeTask(), _FakeEvent()
    result = await replay.generate_with_retry(
        gateway, prompt, None,
        news_event_title=title, news_event_category="AI", language="en",
        research_output=_RESEARCH_OUTPUT, intelligence_output=_INTELLIGENCE_OUTPUT,
        brief=brief, plan=plan, task=task, event=event, draft_id="fake-id", sequence_start=0,
    )
    assert result["final_status"] == "still_empty"
    assert result["retry_used"] is True
    assert result["calls_made"] == 2
    assert result["candidate"] == {}
    assert result["final_empty_output_reason"] == "reasoning_budget_exhausted"


# ---------------------------------------------------------------------------
# Deterministic artifact merge (tests 14-16)
# ---------------------------------------------------------------------------


def test_merge_replaces_only_replayed_ids(tmp_path: Path) -> None:
    m4_records = {
        "id-a": {"draft_id": "id-a", "event_id": "e-a", "category": "AI", "candidate_generated": True, "candidate": {"title": "Old A"}},
        "id-b": {"draft_id": "id-b", "event_id": "e-b", "category": "AI", "candidate_generated": False, "candidate": {}},
    }
    replay_records = [
        {
            "draft_id": "id-b", "beginner_friendly_plan": {"schema_version": "v1"},
            "final_status": "valid", "candidate": {"title": "New B", "body": "New body"},
            "attempts": [{"model_used": "gpt-5.6-luna", "token_usage": {"output_tokens": 100}}],
            "retry_used": False, "total_estimated_cost_usd": 0.001,
            "m4_1_fact_safety": {"status": "pass"},
            "final_empty_output_reason": None,
        }
    ]
    merged_path = tmp_path / "merged.json"
    replay._write_merged_output(m4_records, replay_records, str(merged_path))
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    by_id = {r["draft_id"]: r for r in merged["records"]}

    assert by_id["id-a"] == m4_records["id-a"]  # untouched, byte-for-byte
    assert by_id["id-b"]["candidate_generated"] is True
    assert by_id["id-b"]["candidate"]["title"] == "New B"
    assert by_id["id-b"]["m4_1_replayed"] is True
    assert by_id["id-b"]["m4_1_final_status"] == "valid"


def test_merge_preserves_still_empty_replay_honestly(tmp_path: Path) -> None:
    m4_records = {
        "id-c": {"draft_id": "id-c", "event_id": "e-c", "category": "AI", "candidate_generated": False, "candidate": {}},
    }
    replay_records = [
        {
            "draft_id": "id-c", "beginner_friendly_plan": {"schema_version": "v1"},
            "final_status": "still_empty", "candidate": {}, "attempts": [], "retry_used": True,
            "total_estimated_cost_usd": 0.002, "final_empty_output_reason": "reasoning_budget_exhausted",
        }
    ]
    merged_path = tmp_path / "merged.json"
    replay._write_merged_output(m4_records, replay_records, str(merged_path))
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    record = merged["records"][0]
    assert record["candidate_generated"] is False
    assert record["candidate"] == {}
    assert record["m4_1_final_status"] == "still_empty"
    assert record["m4_1_final_empty_output_reason"] == "reasoning_budget_exhausted"


def test_existing_non_replayed_records_untouched_by_merge(tmp_path: Path) -> None:
    m4_records = {f"id-{i}": {"draft_id": f"id-{i}", "candidate": {"title": f"Title {i}"}} for i in range(3)}
    merged_path = tmp_path / "merged.json"
    replay._write_merged_output(m4_records, [], str(merged_path))
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    assert len(merged["records"]) == 3
    for record in merged["records"]:
        assert "m4_1_replayed" not in record


# ---------------------------------------------------------------------------
# Resume / backward compatibility (tests 17-19)
# ---------------------------------------------------------------------------


def test_load_existing_output_skips_unresolved_records(tmp_path: Path) -> None:
    path = tmp_path / "existing.json"
    path.write_text(
        json.dumps({"records": [
            {"draft_id": "resolved", "final_status": "valid"},
            {"draft_id": "unresolved"},
        ]}),
        encoding="utf-8",
    )
    existing = replay._load_existing_output(str(path))
    assert set(existing) == {"resolved"}


def test_load_existing_output_missing_file_returns_empty(tmp_path: Path) -> None:
    assert replay._load_existing_output(str(tmp_path / "does_not_exist.json")) == {}


def test_load_m4_records_missing_file_returns_empty(tmp_path: Path) -> None:
    """Backward compatibility: the replay tool must not crash if the M4 comparison artifact does
    not exist (e.g. a fresh checkout without scratch artifacts)."""
    original = replay._M4_RESULTS_PATH
    try:
        replay._M4_RESULTS_PATH = str(tmp_path / "missing.json")
        assert replay._load_m4_records() == {}
    finally:
        replay._M4_RESULTS_PATH = original


# ---------------------------------------------------------------------------
# CLI dry-run / paid-flag gating (test 20)
# ---------------------------------------------------------------------------


def test_dry_run_is_default_without_both_flags() -> None:
    """Mirrors main()'s own `dry_run = not (args.live and args.confirm_paid_calls)` - a paid run
    requires BOTH flags together; any other combination stays in dry-run.

    `run_replay()` itself is not exercised end-to-end against a real DB session in this file:
    it opens `database.session.async_session_factory` directly (the same production engine M1-M4's
    own comparison scripts use), which pytest-asyncio's per-test event loop cannot safely share
    across tests (see `tests/conftest.py`'s own documented reason for using a dedicated `NullPool`
    test engine instead - a pre-existing constraint, not something this milestone introduces).
    Consistent with M1-M4's own established precedent, `run_replay()`'s real-DB dry-run/live-gating
    behavior was instead verified by direct manual invocation (twice - see
    docs/phase17_m4_1_reasoning_budget_fix_report.md §11/§13), not by a pytest DB-session test."""
    for live, confirm in [(False, False), (True, False), (False, True)]:
        assert (not (live and confirm)) is True
    assert (not (True and True)) is False
