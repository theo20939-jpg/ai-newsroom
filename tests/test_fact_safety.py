"""Phase 15 M5 - Fact Safety tests.

Three tiers, mirroring tests/test_editorial_scoring.py's own established structure:
- Pure unit tests for services.fact_safety's extraction/normalization/classification - no DB,
  no LLM.
- Integration tests driving the real capabilities.executor.CapabilityExecutor +
  workflows.runner.WorkflowRunner path with a local fake "quality" Capability, using
  tests/conftest.py's db_session fixture (real Postgres, rolled back at teardown).
- Pure unit tests for the content_draft_service/content_cycle enforcement decision helpers.
"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.ai_execution import AIExecution
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowRunResult,
    WorkflowStepResult,
    WorkflowType,
)
from services import workflow_service
from services.content_draft_service import _draft_status_for, _fact_safety_status
from services.fact_safety import (
    FactEvidence,
    apply_fact_safety,
    evaluate_fact_safety,
    extract_claims,
    _normalize_date,
    _normalize_entity,
    _normalize_money,
    _normalize_percentage,
)
from worker.content_cycle import _fact_safety_delivery_decision
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc


def _ev(**kwargs) -> FactEvidence:
    defaults = {"source_title": "", "source_content": None, "source_url": None}
    defaults.update(kwargs)
    return FactEvidence(**defaults)


# ---------------------------------------------------------------------------
# M5.3 - normalization unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$1.7 billion", ("USD", 1_700_000_000.0)),
        ("$1,7 млрд", ("USD", 1_700_000_000.0)),
        ("$1.7B", ("USD", 1_700_000_000.0)),
        ("1.7 billion dollars", ("USD", 1_700_000_000.0)),
        ("1,7 млрд долларов", ("USD", 1_700_000_000.0)),
        ("$50", ("USD", 50.0)),
        ("50 dollars", ("USD", 50.0)),
        ("€500 million", ("EUR", 500_000_000.0)),
        ("1,700,000", None),  # no currency signal at all - correctly unresolvable
    ],
)
def test_money_normalization_formats(text: str, expected) -> None:
    assert _normalize_money(text) == expected


def test_money_thousands_grouping_vs_decimal_disambiguation() -> None:
    assert _normalize_money("$1,700,000") == ("USD", 1_700_000.0)
    assert _normalize_money("$1.700.000") == ("USD", 1_700_000.0)
    assert _normalize_money("$1,7") == ("USD", 1.7)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("14%", 14.0), ("14 percent", 14.0), ("14 процента", 14.0), ("14,5%", 14.5), ("14.5%", 14.5)],
)
def test_percentage_normalization_formats(text: str, expected: float) -> None:
    assert _normalize_percentage(text) == expected


@pytest.mark.parametrize(
    ("text", "year", "month", "day"),
    [
        ("2026-07-24", 2026, 7, 24),
        ("24.07.2026", 2026, 7, 24),
        ("July 24, 2026", 2026, 7, 24),
        ("24 июля 2026", 2026, 7, 24),
        ("2026", 2026, None, None),
    ],
)
def test_date_normalization_formats(text: str, year: int, month: int | None, day: int | None) -> None:
    parts = _normalize_date(text)
    assert parts is not None
    assert (parts.year, parts.month, parts.day) == (year, month, day)


def test_date_partial_specificity_is_compatible_not_contradictory() -> None:
    from services.fact_safety import _date_matches
    year_only = _normalize_date("2026")
    full_date = _normalize_date("24.07.2026")
    assert year_only is not None and full_date is not None
    assert _date_matches(year_only, full_date) is True  # "2026" doesn't contradict "24.07.2026"


def test_date_wrong_month_is_a_real_mismatch() -> None:
    from services.fact_safety import _date_matches
    july = _normalize_date("24.07.2026")
    august = _normalize_date("24.08.2026")
    assert july is not None and august is not None
    assert _date_matches(july, august) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Acme Corp.", "acme"),
        ("ACME CORP", "acme"),
        ("Acme Inc", "acme"),
        ("ООО Ромашка", "ромашка"),  # legal suffix stripped, case-insensitive
    ],
)
def test_entity_normalization_strips_legal_suffix_and_case(text: str, expected: str) -> None:
    assert _normalize_entity(text) == expected


def test_entity_unicode_nfkc_normalization_is_safe() -> None:
    # Full-width Latin "Ａ" (U+FF21) NFKC-normalizes to ordinary "A" - a real, safe Unicode fold,
    # not a fuzzy/lossy transformation (M5.3's own "safe Unicode normalization" requirement).
    assert _normalize_entity("Ａcme") == _normalize_entity("Acme")


# ---------------------------------------------------------------------------
# M5.2 - claim extraction unit tests
# ---------------------------------------------------------------------------


def test_extract_claims_does_not_flag_bare_numbers_as_money() -> None:
    assert extract_claims("There were 5 people in the room.")["money"] == []


def test_extract_claims_does_not_flag_ordinary_words_as_magnitude_prefix() -> None:
    """Regression: a lone-letter magnitude shorthand (b/m/k) must never match as a prefix of an
    unrelated word (e.g. "5 bears" must not be read as "5B")."""
    assert extract_claims("5 bears were seen near the site.")["money"] == []
    assert extract_claims("10 kittens were rescued today.")["money"] == []


def test_extract_claims_does_not_confuse_a_date_for_money() -> None:
    """Regression: a date like 24.07.2026 must never be parsed as a money amount."""
    assert extract_claims("The event happened on 24.07.2026.")["money"] == []


def test_extract_claims_entity_ignores_lone_sentence_initial_word() -> None:
    assert extract_claims("The company said it will grow rapidly next year.")["entity"] == []
    assert extract_claims("Компания объявила о расширении бизнеса.")["entity"] == []


def test_extract_claims_entity_catches_multiword_and_acronym_and_camelcase() -> None:
    entities = extract_claims("OpenAI announced a deal with Tesla Inc and NASA yesterday.")["entity"]
    assert "OpenAI" in entities
    assert "Tesla Inc" in entities
    assert "NASA" in entities


def test_extract_claims_entity_never_spans_a_newline_boundary() -> None:
    """Regression: a capitalized word ending one line (e.g. a title) must never concatenate with
    a capitalized word starting the next (e.g. body text) into one false multi-word entity."""
    text = "Title\nКомпания продолжает работу."
    assert extract_claims(text)["entity"] == []


def test_extract_claims_quote() -> None:
    assert extract_claims('The CEO said "we are thrilled" in a statement.')["quote"] == ["we are thrilled"]


# ---------------------------------------------------------------------------
# Required test cases 1-14 (task's own numbering) - end-to-end evaluate_fact_safety()
# ---------------------------------------------------------------------------


def test_1_supported_money_amount() -> None:
    ev = _ev(source_title="Startup raises $1.7 billion",
              source_content="The company announced it raised $1.7 billion in funding.")
    result = evaluate_fact_safety("Компания привлекла $1,7 млрд", "Отличная новость для стартапа.", ev)
    assert result["status"] == "pass"
    assert result["findings"] == []


def test_2_changed_money_amount_is_unsupported_high() -> None:
    ev = _ev(source_title="Startup raises $1.7 billion",
              source_content="The company announced it raised $1.7 billion in funding.")
    result = evaluate_fact_safety("Компания привлекла $2 billion", "body text", ev)
    assert result["status"] == "block"
    assert result["highest_risk"] == "high"
    finding = next(f for f in result["findings"] if f["type"] == "money")
    assert finding["support"] == "unsupported"
    assert finding["severity"] == "high"


def test_3_supported_percentage() -> None:
    ev = _ev(source_title="Rates cut by 14%", source_content="The central bank cut its key rate by 14%.")
    result = evaluate_fact_safety("Ставку снизили на 14%", "body", ev)
    assert result["status"] == "pass"


def test_4_unsupported_percentage_is_high() -> None:
    ev = _ev(source_title="Rates cut by 14%", source_content="The central bank cut its key rate by 14%.")
    result = evaluate_fact_safety("Ставку снизили на 20%", "body", ev)
    assert result["status"] == "block"
    finding = next(f for f in result["findings"] if f["type"] == "percentage")
    assert finding["support"] == "unsupported" and finding["severity"] == "high"


def test_5_supported_date_with_formatting_difference() -> None:
    ev = _ev(source_title="Launch set for July 24, 2026",
              source_content="The company confirmed the launch date of July 24, 2026 for the new product.")
    result = evaluate_fact_safety("Запуск назначен на 24.07.2026", "body", ev)
    assert result["status"] == "pass"


def test_6_unsupported_launch_date_is_high() -> None:
    ev = _ev(source_title="Launch set for July 24, 2026",
              source_content="The company confirmed the launch date of July 24, 2026 for the new product.")
    result = evaluate_fact_safety("Запуск назначен на 01.08.2026", "body", ev)
    assert result["status"] == "block"
    finding = next(f for f in result["findings"] if f["type"] == "date")
    assert finding["support"] == "unsupported" and finding["severity"] == "high"


def test_7_supported_named_company_and_person() -> None:
    ev = _ev(source_title="OpenAI raises $1.7 billion led by Sequoia",
              source_content="OpenAI announced funding of $1.7 billion led by Sequoia Capital.")
    result = evaluate_fact_safety("OpenAI привлекла $1,7 млрд", "При участии Sequoia компания планирует расширение.", ev)
    assert result["status"] == "pass"


def test_8_unsupported_secondary_investor_is_medium_not_high() -> None:
    """The exact Phase 14.5 live-defect shape: a secondary investor/company absent from the
    source, not the story's own central subject - M5.5 classifies this MEDIUM, not HIGH."""
    ev = _ev(source_title="OpenAI raises $1.7 billion led by Sequoia",
              source_content="OpenAI announced funding of $1.7 billion led by Sequoia Capital.")
    result = evaluate_fact_safety(
        "OpenAI привлекла $1,7 млрд", "При участии Andreessen Horowitz компания планирует расширение.", ev
    )
    assert result["status"] == "review"
    finding = next(f for f in result["findings"] if f["type"] == "entity")
    assert finding["support"] == "unsupported" and finding["severity"] == "medium"


def test_8b_unsupported_entity_central_to_story_is_high() -> None:
    """The same mechanism, but the fabricated entity IS the story's own subject (appears in the
    draft's own title) - correctly HIGH, not MEDIUM. Uses "OpenAI" (an internal-capital brand
    name - a strong single-token entity signal, see _is_strong_single_token_entity) since a
    lone ordinary Title-Case word is deliberately never extracted as an entity candidate at all
    (the single biggest false-positive source - see test_extract_claims_entity_ignores_lone_
    sentence_initial_word)."""
    ev = _ev(source_title="A company raised funding", source_content="A company raised funding today.")
    result = evaluate_fact_safety("OpenAI привлекла funding", "Компания довольна результатом.", ev)
    finding = next(f for f in result["findings"] if f["type"] == "entity")
    assert finding["severity"] == "high"


def test_9_harmless_editorial_wording_is_not_a_factual_claim() -> None:
    ev = _ev(source_title="x", source_content="y")
    result = evaluate_fact_safety("Крупная новость дня", "Это важное событие для индустрии в целом.", ev)
    assert result["status"] == "pass"
    assert result["claims_checked"] == 0


def test_10_missing_source_content_but_usable_title() -> None:
    ev = _ev(source_title="Company announces new product", source_content=None)
    result = evaluate_fact_safety("Заголовок", "Компания привлекла $5 million", ev)
    assert result["status"] == "review"  # not confidently "block" - content was never available
    finding = result["findings"][0]
    assert finding["support"] == "uncertain"


def test_11_research_fact_with_valid_provenance_supports() -> None:
    ev = _ev(
        source_title="Company launches product", source_content="A short announcement.",
        research_facts_provenanced=(("Funding round of $5 million", "https://example.com/a"),),
    )
    result = evaluate_fact_safety("Заголовок", "Компания привлекла $5 million", ev)
    assert result["status"] == "pass"


def test_12_research_claim_without_provenance_does_not_override_original_evidence() -> None:
    ev = _ev(
        source_title="Company launches product",
        source_content="A short announcement with no numbers.",
        research_facts=["Funding round of $5 million"],
    )
    result = evaluate_fact_safety("Заголовок", "Компания привлекла $5 million", ev)
    assert result["status"] == "review"  # uncertain, never promoted to "pass"
    assert result["findings"][0]["support"] == "uncertain"


def test_13_cyrillic_latin_and_punctuation_normalization() -> None:
    ev = _ev(source_title="Acme Corp. announces expansion",
              source_content="ACME CORP announced a major expansion today.")
    result = evaluate_fact_safety("Acme Corp расширяется", "Компания объявила о планах.", ev)
    assert result["status"] == "pass"


def test_14_null_missing_evidence_produces_uncertain_not_fabricated_support() -> None:
    ev = _ev(source_title="", source_content=None)
    result = evaluate_fact_safety("Заголовок", "Компания привлекла $5 million", ev)
    assert result["status"] == "review"
    assert result["findings"][0]["support"] == "uncertain"  # never "supported", never "block"


# ---------------------------------------------------------------------------
# 15/16 - mode behavior at the apply_fact_safety() integration-function level
# ---------------------------------------------------------------------------


def test_15_shadow_mode_records_but_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    original = {"title": "X", "body": "Компания привлекла $2 billion", "hashtags": []}
    out = apply_fact_safety(
        "Startup raises $1.7 billion", "The company announced it raised $1.7 billion in funding.",
        None, {}, original,
    )
    assert out["fact_safety"]["status"] == "block"  # correctly detected...
    assert out["title"] == "X" and out["body"] == original["body"]  # ...but nothing about the draft itself changed
    # And, at the enforcement-decision level, shadow mode never suppresses delivery:
    effective_dry_run, suppressed = _fact_safety_delivery_decision(False, "shadow", "block")
    assert suppressed is False
    assert effective_dry_run is False


def test_16_off_mode_preserves_previous_behavior_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "off")
    original = {"title": "X", "body": "Y", "hashtags": []}
    out = apply_fact_safety("Any title", "Any content", None, {}, original)
    assert out is original  # identity, not just equality - zero processing occurred
    assert "fact_safety" not in out


# ---------------------------------------------------------------------------
# 17 - enforce behavior (safely implemented, never activated by default)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base_dry_run", "mode", "status", "expected_effective", "expected_suppressed"),
    [
        (False, "enforce", "block", True, True),
        (False, "enforce", "review", True, True),
        (False, "enforce", "pass", False, False),
        (False, "shadow", "block", False, False),  # shadow never suppresses, even on "block"
        (False, "off", None, False, False),
        (True, "enforce", "pass", True, False),  # already dry-run for an unrelated reason - stays dry-run
    ],
)
def test_17_enforce_delivery_decision(
    base_dry_run: bool, mode: str, status: str | None, expected_effective: bool, expected_suppressed: bool
) -> None:
    effective, suppressed = _fact_safety_delivery_decision(base_dry_run, mode, status)
    assert (effective, suppressed) == (expected_effective, expected_suppressed)


@pytest.mark.parametrize(
    ("mode", "status", "expected"),
    [
        ("enforce", "block", "draft_blocked_fact_safety"),
        ("enforce", "review", "draft_review_fact_safety"),
        ("enforce", "pass", "draft"),
        ("enforce", None, "draft"),
        ("shadow", "block", "draft"),  # never changes ContentDraft.status outside enforce mode
        ("off", None, "draft"),
    ],
)
def test_17b_enforce_draft_status(monkeypatch: pytest.MonkeyPatch, mode: str, status: str | None, expected: str) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", mode)
    assert _draft_status_for(status) == expected


def test_17c_fact_safety_status_extraction_from_workflow_run_result() -> None:
    now = datetime.now(UTC)
    result = WorkflowRunResult(
        task_id=uuid4(), status="COMPLETED", iterations_used=1,
        step_results=[
            WorkflowStepResult(
                step_name="quality", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
                result={"passed": True, "issues": [], "fact_safety": {"status": "review"}},
            ),
        ],
    )
    assert _fact_safety_status(result) == "review"


def test_17d_fact_safety_status_none_when_absent() -> None:
    now = datetime.now(UTC)
    result = WorkflowRunResult(
        task_id=uuid4(), status="COMPLETED", iterations_used=1,
        step_results=[
            WorkflowStepResult(
                step_name="quality", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
                result={"passed": True, "issues": []},
            ),
        ],
    )
    assert _fact_safety_status(result) is None


# ---------------------------------------------------------------------------
# 18 - no new provider calls (structural)
# ---------------------------------------------------------------------------


def _import_lines(path: str) -> list[str]:
    return [
        line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]


def test_18_fact_safety_module_imports_no_llm_gateway_or_capability() -> None:
    for line in _import_lines("services/fact_safety.py"):
        for forbidden in ("llm_gateway", "capabilities."):
            assert forbidden not in line, f"unexpected import: {line}"
    assert "call_generate(" not in Path("services/fact_safety.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 19 - existing scoring output and eligibility remain unchanged (structural)
# ---------------------------------------------------------------------------


def test_19_fact_safety_does_not_import_editorial_scoring() -> None:
    for line in _import_lines("services/fact_safety.py"):
        assert "editorial_scoring" not in line, f"unexpected import: {line}"


def test_19b_editorial_scoring_does_not_import_fact_safety() -> None:
    for line in _import_lines("services/editorial_scoring.py"):
        assert "fact_safety" not in line, f"unexpected import: {line}"


# ---------------------------------------------------------------------------
# 20 - existing hard source-quality gates remain authoritative (structural)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["services/triage_orchestrator.py", "services/cleaning.py", "services/deduplication.py"],
)
def test_20_hard_gate_files_do_not_reference_fact_safety(path: str) -> None:
    source = Path(path).read_text(encoding="utf-8")
    assert "fact_safety" not in source


# ---------------------------------------------------------------------------
# Score bounds / output contract
# ---------------------------------------------------------------------------


def test_output_contains_all_expected_contract_keys() -> None:
    ev = _ev(source_title="x", source_content="y")
    result = evaluate_fact_safety("Title", "Body", ev)
    assert set(result) == {
        "version", "status", "mode", "claims_checked", "supported", "uncertain",
        "unsupported", "highest_risk", "findings",
    }
    assert result["status"] in ("pass", "review", "block")


def test_claim_counts_are_internally_consistent() -> None:
    ev = _ev(source_title="Startup raises $1.7 billion",
              source_content="The company announced it raised $1.7 billion in funding.")
    result = evaluate_fact_safety("Компания привлекла $2 billion, рост на 20%", "body", ev)
    assert result["claims_checked"] == result["supported"] + result["uncertain"] + result["unsupported"]


# ---------------------------------------------------------------------------
# Integration: capabilities.executor.CapabilityExecutor + WorkflowRunner, real "quality" step
# ---------------------------------------------------------------------------


class _FakeQualityCapability:
    """Deterministic fake mirroring capabilities/quality_capability.py's real output shape -
    zero LLMGateway, zero network. `draft` is what the *upstream* Copywriting step "wrote" -
    this fake stands in for Quality's own step but reports on that draft, exactly like the real
    QualityCapability's own `_format_copywriting_draft()` reads step_results["copywriting"]."""

    def __init__(self, draft_title: str, draft_body: str) -> None:
        self._draft_title = draft_title
        self._draft_body = draft_body

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(UTC)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"passed": True, "issues": [], "title": self._draft_title, "body": self._draft_body},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


class _FakeResearchCapability:
    def __init__(self, facts: list[str]) -> None:
        self._facts = facts

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(UTC)
        return CapabilityResult(
            status="SUCCESS", structured_output={"facts": self._facts, "confidence": 0.9, "gaps": []},
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


def _quality_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION, version=1,
            steps=[
                WorkflowStepDefinition(name="research", capability="research", timeout_seconds=10),
                WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=10),
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _quality_capability_registry(research_facts: list[str], draft_title: str, draft_body: str) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        _FakeResearchCapability(research_facts),
    )
    registry.register(
        CapabilityDefinition(
            name="quality", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["passed", "issues"],
        ),
        _FakeQualityCapability(draft_title, draft_body),
    )
    registry.seal()
    return registry


async def _ai_execution_count(session: AsyncSession) -> int:
    from sqlalchemy import func, select as sa_select
    result = await session.execute(sa_select(func.count()).select_from(AIExecution))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_off_mode_leaves_quality_step_result_completely_unchanged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "off")

    source = NewsSource(name="Off Source", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Startup raises $1.7 billion",
        content="The company announced it raised $1.7 billion in funding.",
        category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()

    workflow_registry = _quality_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _quality_capability_registry([], "X", "Компания привлекла $2 billion")
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    quality_result = next(r for r in result.step_results if r.step_name == "quality").result
    assert quality_result == {"passed": True, "issues": [], "title": "X", "body": "Компания привлекла $2 billion"}
    assert "fact_safety" not in quality_result
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")

    source = NewsSource(name="Shadow Source", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Startup raises $1.7 billion",
        content="The company announced it raised $1.7 billion in funding.",
        category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()

    workflow_registry = _quality_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _quality_capability_registry([], "X", "Компания привлекла $2 billion")
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    quality_result = next(r for r in result.step_results if r.step_name == "quality").result
    assert quality_result["passed"] is True  # original QualityCapability field preserved verbatim
    fact_safety = quality_result["fact_safety"]
    assert fact_safety["status"] == "block"
    assert fact_safety["highest_risk"] == "high"
    assert await _ai_execution_count(db_session) == 0  # zero provider calls, regardless of mode


@pytest.mark.asyncio
async def test_shadow_mode_uses_research_facts_from_step_results_without_extra_db_query(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the M5.0/M5.1 evidence-packet design: Research's completed step_results are
    already present on CapabilityContext at the "quality" step - fact safety reads them from
    there, not from a fresh query."""
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")

    source = NewsSource(name="Research Source", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Company launches product",
        content="A short announcement with no numbers.",
        category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()

    workflow_registry = _quality_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _quality_capability_registry(
        ["Funding round of $5 million"], "X", "Компания привлекла $5 million"
    )
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    quality_result = next(r for r in result.step_results if r.step_name == "quality").result
    fact_safety = quality_result["fact_safety"]
    # Unprovenanced Research fact -> uncertain, never silently promoted to "pass".
    assert fact_safety["status"] == "review"
