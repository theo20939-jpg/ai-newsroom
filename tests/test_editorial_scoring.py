"""Phase 15 M4 - Editorial Score V2 tests.

Two tiers:
- Pure unit tests for services.editorial_scoring.compute_editorial_score_v2() - no DB, no LLM,
  mirrors services/freshness.py's/services/triage.py's own test style
  (tests/test_freshness.py, tests/test_triage.py).
- Integration tests driving the real capabilities.executor.CapabilityExecutor +
  workflows.runner.WorkflowRunner path with a local fake "scoring" Capability, using
  tests/conftest.py's db_session fixture (real Postgres, rolled back at teardown - nothing
  this file does is ever actually persisted, so it is safe to run against the shared
  Observation Mode database without any extra isolation).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import Capability, CapabilityRegistry
from core.config import settings
from database.models.ai_execution import AIExecution
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.editorial_scoring import (
    DEFAULT_WEIGHTS,
    ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE,
    MIN_ENGAGEMENT_BASELINE_SAMPLE,
    NEUTRAL_COMPONENT_VALUE,
    apply_editorial_scoring_v2,
    compute_editorial_score_v2,
    fetch_engagement_baseline,
)
from services.triage import DEFAULT_RELIABILITY_SCORE
from worker.content_cycle import _extract_scoring_result
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_EMPTY_METRICS: dict[str, int | None] = {
    "views_count": None, "forwards_count": None, "replies_count": None, "reactions_count": None,
}


def _metrics(views: int | None = None, forwards: int | None = None,
             replies: int | None = None, reactions: int | None = None) -> dict[str, int | None]:
    return {
        "views_count": views, "forwards_count": forwards, "replies_count": replies, "reactions_count": reactions,
    }


def _compute(
    *,
    legacy_llm_score: int = 60,
    published_at: datetime | None = None,
    collected_at: datetime = NOW,
    reference_now: datetime = NOW,
    reliability_score: float | None = 0.5,
    event_metrics: dict[str, int | None] | None = None,
    baseline_samples: list[int] | None = None,
    weights: dict[str, float] | None = None,
):
    return compute_editorial_score_v2(
        legacy_llm_score=legacy_llm_score,
        published_at=NOW - timedelta(hours=1) if published_at is None else published_at,
        collected_at=collected_at,
        reference_now=reference_now,
        reliability_score=reliability_score,
        event_metrics=_EMPTY_METRICS if event_metrics is None else event_metrics,
        baseline_samples=[] if baseline_samples is None else baseline_samples,
        weights=weights,
    )


# ---------------------------------------------------------------------------
# A. Score bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("legacy_score", "reliability", "metrics", "baseline"),
    [
        (0, 0.0, _metrics(0, 0, 0, 0), [0, 0, 0]),
        (100, 1.0, _metrics(1_000_000, 500_000, 100_000, 900_000), [1, 1, 1]),
        (100, None, _EMPTY_METRICS, []),
        (0, 1.0, _metrics(0, 0, 0, 0), [10_000_000] * 10),
        (50, 0.5, _metrics(reactions=7), list(range(50))),
    ],
)
def test_score_always_within_0_100_bounds(legacy_score, reliability, metrics, baseline) -> None:
    result = _compute(
        legacy_llm_score=legacy_score, reliability_score=reliability,
        event_metrics=metrics, baseline_samples=baseline,
    )
    assert 0 <= result["score"] <= 100
    assert isinstance(result["score"], int)
    for value in result["components"].values():
        assert 0.0 <= value <= 1.0


# ---------------------------------------------------------------------------
# B. Weight contract
# ---------------------------------------------------------------------------


def test_default_weights_sum_to_one() -> None:
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_settings_weights_sum_to_one_and_match_defaults() -> None:
    settings_weights = {
        "semantic_editorial": settings.editorial_scoring_weight_semantic,
        "freshness": settings.editorial_scoring_weight_freshness,
        "engagement": settings.editorial_scoring_weight_engagement,
        "source_reliability": settings.editorial_scoring_weight_source_reliability,
        "novelty": settings.editorial_scoring_weight_novelty,
    }
    assert sum(settings_weights.values()) == pytest.approx(1.0)
    assert settings_weights == DEFAULT_WEIGHTS


def test_weights_used_are_echoed_back_in_output() -> None:
    """Phase 15 M4.1: novelty's slice is always redistributed (weight 0 in the output), so the
    echoed weights are the *effective* (renormalized) weights, not a literal copy of the input -
    their ratios relative to each other match the input's ratios among the four scored keys."""
    custom = {"semantic_editorial": 0.5, "freshness": 0.2, "engagement": 0.1, "source_reliability": 0.1, "novelty": 0.1}
    result = _compute(weights=custom)
    assert result["weights"]["novelty"] == 0.0
    assert sum(result["weights"].values()) == pytest.approx(1.0)
    scored = ("semantic_editorial", "freshness", "engagement", "source_reliability")
    nominal_sum = sum(custom[k] for k in scored)
    for k in scored:
        assert result["weights"][k] == pytest.approx(custom[k] / nominal_sum)


# ---------------------------------------------------------------------------
# C. Freshness
# ---------------------------------------------------------------------------


def test_freshness_very_fresh_scores_high_component() -> None:
    result = _compute(published_at=NOW - timedelta(minutes=30), collected_at=NOW - timedelta(minutes=25))
    assert result["components"]["freshness"] == 1.0


def test_freshness_moderately_fresh_scores_mid_component() -> None:
    result = _compute(published_at=NOW - timedelta(hours=8), collected_at=NOW - timedelta(hours=8))
    assert 0.0 < result["components"]["freshness"] < 1.0


def test_freshness_stale_scores_low_component() -> None:
    result = _compute(published_at=NOW - timedelta(hours=72), collected_at=NOW - timedelta(hours=72))
    assert result["components"]["freshness"] == pytest.approx(0.1)


def test_freshness_future_timestamp_is_clamped_not_raised() -> None:
    result = _compute(published_at=NOW + timedelta(hours=5), collected_at=NOW - timedelta(hours=1))
    assert result["components"]["freshness"] == 1.0  # clamped to zero age -> freshest tier, never an error


def test_freshness_missing_timestamp_falls_back_to_collected_at() -> None:
    result = _compute(published_at=None, collected_at=NOW - timedelta(hours=3))
    assert 0.0 < result["components"]["freshness"] <= 1.0  # no crash, no fabricated precision


# ---------------------------------------------------------------------------
# D. Engagement relative baseline
# ---------------------------------------------------------------------------


def test_engagement_above_baseline_scores_high_component() -> None:
    """Full-confidence baseline (>= ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE rows) so the
    result is the raw, unshrunk percentile - shrinkage itself is tested separately below."""
    baseline = [100, 200, 150, 180, 90, 110, 130, 170, 95, 105]
    assert len(baseline) >= ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE
    result = _compute(event_metrics=_metrics(views=10_000), baseline_samples=baseline)
    assert result["components"]["engagement"] == 1.0
    assert result["coverage"]["engagement_available"] is True
    assert result["coverage"]["source_baseline_available"] is True


def test_engagement_near_baseline_scores_mid_component() -> None:
    baseline = [100, 120, 150, 180, 200, 110, 130, 170, 95, 105]
    result = _compute(event_metrics=_metrics(views=150), baseline_samples=baseline)
    assert 0.0 < result["components"]["engagement"] < 1.0


def test_engagement_below_baseline_scores_low_component() -> None:
    baseline = [100, 200, 150, 180, 90, 110, 130, 170, 95, 105]
    assert len(baseline) >= ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE
    result = _compute(event_metrics=_metrics(views=1), baseline_samples=baseline)
    assert result["components"]["engagement"] == 0.0


def test_engagement_insufficient_baseline_sample_is_neutral_and_flagged() -> None:
    assert MIN_ENGAGEMENT_BASELINE_SAMPLE == 3
    result = _compute(event_metrics=_metrics(views=10_000), baseline_samples=[100, 200])
    assert result["components"]["engagement"] == NEUTRAL_COMPONENT_VALUE
    assert result["coverage"]["engagement_available"] is True
    assert result["coverage"]["source_baseline_available"] is False


def test_engagement_unsupported_metrics_is_neutral_and_flagged() -> None:
    result = _compute(event_metrics=_EMPTY_METRICS, baseline_samples=[100, 200, 300])
    assert result["components"]["engagement"] == NEUTRAL_COMPONENT_VALUE
    assert result["coverage"]["engagement_available"] is False
    assert result["coverage"]["source_baseline_available"] is False


def test_engagement_observed_zero_is_not_treated_as_unavailable() -> None:
    """A real, measured 0 (all four fields present, all zero) is a valid low-engagement
    observation, not a missing-metric fallback - it must still be ranked against the baseline,
    not silently defaulted to neutral. Full-confidence baseline so the ranking is unshrunk."""
    baseline = [10, 20, 30, 15, 25, 12, 18, 22, 28, 14]
    assert len(baseline) >= ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE
    result = _compute(event_metrics=_metrics(0, 0, 0, 0), baseline_samples=baseline)
    assert result["coverage"]["engagement_available"] is True
    assert result["components"]["engagement"] == 0.0  # correctly ranks at the bottom, not neutral


def test_engagement_extreme_outlier_still_bounded() -> None:
    baseline = [1, 2, 3, 2, 1, 2, 3, 1, 2, 3]
    assert len(baseline) >= ENGAGEMENT_BASELINE_FULL_CONFIDENCE_SAMPLE
    result = _compute(event_metrics=_metrics(views=10**9), baseline_samples=baseline)
    assert result["components"]["engagement"] == 1.0  # bounded, not blown up


# ---------------------------------------------------------------------------
# E. Cross-source fairness
# ---------------------------------------------------------------------------


def test_large_source_raw_count_does_not_automatically_outrank_smaller_relative_performer() -> None:
    """A big-audience channel's post with huge raw views but below-average for that channel
    must not outrank a small channel's post that is above-average for its own baseline."""
    big_source_result = _compute(
        event_metrics=_metrics(views=50_000),  # huge in absolute terms
        baseline_samples=[200_000, 180_000, 220_000, 190_000, 210_000],  # but this channel usually gets 200k+
    )
    small_source_result = _compute(
        event_metrics=_metrics(views=500),  # tiny in absolute terms
        baseline_samples=[50, 60, 40, 55, 45],  # but this channel usually gets ~50
    )
    assert small_source_result["components"]["engagement"] > big_source_result["components"]["engagement"]


# ---------------------------------------------------------------------------
# F. RSS missing metrics
# ---------------------------------------------------------------------------


def test_rss_missing_metrics_gives_neutral_not_zero() -> None:
    result = _compute(event_metrics=_EMPTY_METRICS, baseline_samples=[])
    assert result["components"]["engagement"] == NEUTRAL_COMPONENT_VALUE
    assert result["components"]["engagement"] != 0.0


# ---------------------------------------------------------------------------
# G. Source reliability
# ---------------------------------------------------------------------------


def test_known_reliability_score_passes_through() -> None:
    result = _compute(reliability_score=0.9)
    assert result["components"]["source_reliability"] == 0.9
    assert result["coverage"]["source_reliability_available"] is True


def test_missing_reliability_score_falls_back_to_triage_default() -> None:
    result = _compute(reliability_score=None)
    assert result["components"]["source_reliability"] == DEFAULT_RELIABILITY_SCORE
    assert result["coverage"]["source_reliability_available"] is False


# ---------------------------------------------------------------------------
# H. Novelty fallback
# ---------------------------------------------------------------------------


def test_novelty_is_always_neutral_fallback_and_flagged_unavailable() -> None:
    result = _compute()
    assert result["components"]["novelty"] == NEUTRAL_COMPONENT_VALUE
    assert result["coverage"]["novelty_available"] is False


# ---------------------------------------------------------------------------
# J. Score breakdown / explainability
# ---------------------------------------------------------------------------


def test_output_contains_all_expected_keys_and_version_metadata() -> None:
    result = _compute(legacy_llm_score=77)
    assert result["version"] == "v2"
    assert result["legacy_llm_score"] == 77
    assert set(result["components"]) == {
        "semantic_editorial", "freshness", "engagement", "source_reliability", "novelty",
    }
    assert set(result["coverage"]) == {
        "engagement_available", "source_baseline_available", "source_reliability_available", "novelty_available",
    }
    assert isinstance(result["reason"], str) and len(result["reason"]) > 0
    assert set(result["weights"]) == set(DEFAULT_WEIGHTS)
    assert result["weights"]["novelty"] == 0.0
    assert sum(result["weights"].values()) == pytest.approx(1.0)


def test_reason_is_deterministic_and_never_calls_an_llm() -> None:
    a = _compute(legacy_llm_score=90, reliability_score=0.9,
                 event_metrics=_metrics(views=5000), baseline_samples=[100, 200, 150])
    b = _compute(legacy_llm_score=90, reliability_score=0.9,
                 event_metrics=_metrics(views=5000), baseline_samples=[100, 200, 150])
    assert a["reason"] == b["reason"]
    assert "high semantic relevance" in a["reason"].lower()


# ---------------------------------------------------------------------------
# K. No new provider calls - structural
# ---------------------------------------------------------------------------


def test_editorial_scoring_module_imports_no_llm_gateway_or_capability() -> None:
    source = Path("services/editorial_scoring.py").read_text(encoding="utf-8")
    for forbidden in ("llm_gateway", "capabilities.", "call_generate"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# L. Eligibility safety - structural (hard gates live entirely outside the scoring step;
#    V2 only ever runs *inside* an already-created, already-eligible EditorialTask's
#    "scoring" step - see tests/test_phase15_m1_invalid_title_gate.py for the gate itself,
#    unmodified and untouched by M4).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["services/triage_orchestrator.py", "services/workflow_service.py", "services/triage.py"],
)
def test_hard_gate_files_do_not_reference_editorial_scoring(path: str) -> None:
    source = Path(path).read_text(encoding="utf-8")
    assert "editorial_scoring" not in source


# ---------------------------------------------------------------------------
# M. Threshold / backward-compatible extraction
# ---------------------------------------------------------------------------


def test_content_worker_extraction_still_reads_v2_shaped_top_level_score() -> None:
    v2_result = _compute(legacy_llm_score=82)
    workflow = {
        "step_results": [
            {"step_name": "scoring", "status": "SUCCESS", "result": {**v2_result, "rationale": "LLM said so"}},
        ]
    }
    assert _extract_scoring_result(workflow) == v2_result["score"]


def test_content_worker_extraction_still_reads_v1_shaped_top_level_score() -> None:
    workflow = {
        "step_results": [
            {"step_name": "scoring", "status": "SUCCESS", "result": {"score": 71, "rationale": "LLM said so"}},
        ]
    }
    assert _extract_scoring_result(workflow) == 71


# ---------------------------------------------------------------------------
# fetch_engagement_baseline - real Postgres, rolled back per test (db_session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_engagement_baseline_excludes_the_scored_event_and_nulls(db_session: AsyncSession) -> None:
    source = NewsSource(name="Baseline Source", type=SourceType.TELEGRAM, active=True)
    db_session.add(source)
    await db_session.flush()

    def _event(**engagement: int | None) -> NewsEvent:
        return NewsEvent(
            source_id=source.id, title="t", content="c", category=EventCategory.UNKNOWN,
            hash=f"h-{uuid4()}", **engagement,
        )

    scored_event = _event(views_count=999)  # must be excluded from its own baseline
    no_metrics_event = _event()  # all four None -> excluded from the baseline sample entirely
    with_metrics_a = _event(views_count=100, forwards_count=5)
    with_metrics_b = _event(views_count=50)

    db_session.add_all([scored_event, no_metrics_event, with_metrics_a, with_metrics_b])
    await db_session.flush()

    baseline = await fetch_engagement_baseline(db_session, source.id, scored_event.id)

    assert sorted(baseline) == sorted([105, 50])  # 100+5=105, 50 - the null-only event excluded


@pytest.mark.asyncio
async def test_fetch_engagement_baseline_is_scoped_to_the_given_source(db_session: AsyncSession) -> None:
    source_a = NewsSource(name="Source A", type=SourceType.TELEGRAM, active=True)
    source_b = NewsSource(name="Source B", type=SourceType.TELEGRAM, active=True)
    db_session.add_all([source_a, source_b])
    await db_session.flush()

    event_a = NewsEvent(
        source_id=source_a.id, title="t", content="c", category=EventCategory.UNKNOWN,
        hash=f"h-{uuid4()}", views_count=10,
    )
    event_b = NewsEvent(
        source_id=source_b.id, title="t", content="c", category=EventCategory.UNKNOWN,
        hash=f"h-{uuid4()}", views_count=99999,
    )
    db_session.add_all([event_a, event_b])
    await db_session.flush()

    baseline = await fetch_engagement_baseline(db_session, source_a.id, uuid4())

    assert baseline == [10]  # source_b's event never leaks into source_a's baseline


# ---------------------------------------------------------------------------
# Integration: capabilities.executor.CapabilityExecutor + WorkflowRunner, real "scoring" step
# ---------------------------------------------------------------------------


class _FakeScoringCapability:
    """Deterministic fake mirroring capabilities/scoring_capability.py's real output shape -
    zero LLMGateway, zero network, exactly like tests/fakes/fake_capability.py's own
    conventions (not reused directly: none of the existing fakes return a
    {"score", "rationale"} shape)."""

    def __init__(self, score: int = 80, rationale: str = "Strong story.") -> None:
        self._score = score
        self._rationale = rationale

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(UTC)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"score": self._score, "rationale": self._rationale},
            calls=[],
            started_at=now,
            finished_at=now,
            duration_seconds=0.0,
        )


def _scoring_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,  # any registered type works as the harness's own single-step host
            version=1,
            steps=[WorkflowStepDefinition(name="scoring", capability="scoring", timeout_seconds=10)],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _scoring_capability_registry(capability: Capability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDefinition(
            name="scoring", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["score", "rationale"],
        ),
        capability,
    )
    registry.seal()
    return registry


async def _ai_execution_count(session: AsyncSession) -> int:
    from sqlalchemy import func, select
    result = await session.execute(select(func.count()).select_from(AIExecution))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_v1_mode_leaves_scoring_step_result_completely_unchanged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "editorial_scoring_version", "v1")

    source = NewsSource(name="V1 Source", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="t", content="c", category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}"
    )
    db_session.add(event)
    await db_session.flush()

    workflow_registry = _scoring_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _scoring_capability_registry(_FakeScoringCapability(score=71, rationale="ok"))
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].result == {"score": 71, "rationale": "ok"}  # byte-identical to the raw LLM output
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_v2_mode_enriches_scoring_step_result_and_preserves_top_level_score(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "editorial_scoring_version", "v2")

    source = NewsSource(name="V2 Source", type=SourceType.TELEGRAM, active=True, reliability_score=0.7)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="t", content="c", category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}",
        published_at=datetime.now(UTC) - timedelta(minutes=10), views_count=500, forwards_count=20,
    )
    db_session.add(event)
    await db_session.flush()

    workflow_registry = _scoring_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _scoring_capability_registry(_FakeScoringCapability(score=71, rationale="ok"))
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    step_result = result.step_results[0].result
    assert isinstance(step_result["score"], int)
    assert 0 <= step_result["score"] <= 100
    assert step_result["version"] == "v2"
    assert step_result["legacy_llm_score"] == 71
    assert step_result["rationale"] == "ok"  # original LLM rationale preserved verbatim
    assert "components" in step_result and "coverage" in step_result and "reason" in step_result

    # Backward compatibility: worker/content_cycle.py's own extraction still works unmodified.
    workflow_dict = {"step_results": [{"step_name": "scoring", "status": "SUCCESS", "result": step_result}]}
    assert _extract_scoring_result(workflow_dict) == step_result["score"]

    # Zero new provider calls, regardless of scoring version.
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_v2_mode_with_no_engagement_data_still_completes_and_flags_coverage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An RSS-shaped event (no engagement, no reliability_score) must not error or be silently
    zeroed out - it gets a neutral engagement component and honest coverage flags."""
    monkeypatch.setattr(settings, "editorial_scoring_version", "v2")

    source = NewsSource(name="RSS No Reliability", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="t", content="c", category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}"
    )
    db_session.add(event)
    await db_session.flush()

    workflow_registry = _scoring_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _scoring_capability_registry(_FakeScoringCapability(score=60))
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    step_result = result.step_results[0].result
    assert step_result["coverage"]["engagement_available"] is False
    assert step_result["coverage"]["source_reliability_available"] is False
    assert step_result["components"]["engagement"] == NEUTRAL_COMPONENT_VALUE
    assert 0 <= step_result["score"] <= 100


@pytest.mark.asyncio
async def test_apply_editorial_scoring_v2_is_a_noop_passthrough_when_not_v2(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "editorial_scoring_version", "v1")

    source = NewsSource(name="Noop Source", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="t", content="c", category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}"
    )
    db_session.add(event)
    await db_session.flush()

    original = {"score": 55, "rationale": "unchanged"}
    output = await apply_editorial_scoring_v2(db_session, event, original, task_id=uuid4())

    assert output is original  # identity, not just equality - proves zero processing occurred


# ---------------------------------------------------------------------------
# M4.1 FAIRNESS CALIBRATION - focused tests for the diagnosed compression/self-referential-
# imputation bugs and their fix (novelty always redistributed; engagement/reliability never
# redistributed when unavailable; baseline-confidence shrinkage). See
# docs/phase15_m4_editorial_scoring_v2_report.md, "M4.1 FAIRNESS CALIBRATION" for the full
# offline evidence (Variant B's naive full redistribution was backtested, found to reward
# missing engagement data over honestly-measured-average engagement, and rejected).
# ---------------------------------------------------------------------------


def test_unsupported_engagement_gains_no_advantage_over_measured_average_engagement() -> None:
    """The bug this calibration specifically fixes: a story whose engagement is fully
    unsupported (RSS/NEWS_API-shaped - no fields at all) must score the SAME as an otherwise
    identical story whose engagement WAS measured and happened to land exactly at its source's
    own baseline average - not higher. (Full redistribution of engagement's weight, which was
    tested and rejected, would have made the unsupported story score strictly higher.)"""
    common = dict(legacy_llm_score=90, published_at=NOW - timedelta(hours=1), collected_at=NOW - timedelta(hours=1),
                  reference_now=NOW, reliability_score=0.8)
    baseline = [10, 20, 30, 15, 25, 12, 18, 22, 28, 14]  # full-confidence sample, median-ish = ~19-20

    unsupported = compute_editorial_score_v2(event_metrics=_EMPTY_METRICS, baseline_samples=[], **common)
    # A magnitude landing at exactly the 50th percentile of the baseline (5 of 10 values <= 19).
    measured_average = compute_editorial_score_v2(event_metrics=_metrics(views=19), baseline_samples=baseline, **common)

    assert unsupported["coverage"]["engagement_available"] is False
    assert measured_average["coverage"]["engagement_available"] is True
    assert measured_average["components"]["engagement"] == pytest.approx(0.5, abs=0.05)
    assert unsupported["score"] == measured_average["score"]  # no advantage for having no data


def test_measured_zero_and_unavailable_produce_different_coverage_even_when_scores_are_close() -> None:
    zero = compute_editorial_score_v2(
        legacy_llm_score=50, published_at=NOW - timedelta(hours=1), collected_at=NOW - timedelta(hours=1),
        reference_now=NOW, reliability_score=0.5, event_metrics=_metrics(0, 0, 0, 0),
        baseline_samples=[10, 20, 30, 15, 25, 12, 18, 22, 28, 14],
    )
    unavailable = compute_editorial_score_v2(
        legacy_llm_score=50, published_at=NOW - timedelta(hours=1), collected_at=NOW - timedelta(hours=1),
        reference_now=NOW, reliability_score=0.5, event_metrics=_EMPTY_METRICS, baseline_samples=[],
    )
    assert zero["coverage"]["engagement_available"] is True
    assert unavailable["coverage"]["engagement_available"] is False
    assert zero["components"]["engagement"] == 0.0  # ranks at the true bottom
    assert unavailable["components"]["engagement"] == NEUTRAL_COMPONENT_VALUE  # never conflated with 0


def test_thin_baseline_immature_engagement_is_shrunk_not_excessively_penalized() -> None:
    """A very fresh post whose same-source baseline has only just started accumulating (the
    minimum allowed 3 rows) and which currently ranks at the bottom of that thin sample must not
    receive the FULL penalty a confidently-measured below-baseline post would."""
    thin_baseline = [100, 200, 150]  # n=3, the floor
    full_baseline = [100, 200, 150, 120, 180, 140, 160, 110, 190, 130]  # n=10, full confidence

    thin = compute_editorial_score_v2(
        legacy_llm_score=60, published_at=NOW - timedelta(minutes=10), collected_at=NOW - timedelta(minutes=8),
        reference_now=NOW, reliability_score=0.5, event_metrics=_metrics(views=1), baseline_samples=thin_baseline,
    )
    mature = compute_editorial_score_v2(
        legacy_llm_score=60, published_at=NOW - timedelta(hours=6), collected_at=NOW - timedelta(hours=6),
        reference_now=NOW, reliability_score=0.5, event_metrics=_metrics(views=1), baseline_samples=full_baseline,
    )

    assert thin["coverage"]["source_baseline_available"] is True
    assert mature["coverage"]["source_baseline_available"] is True
    # Both rank at the bottom of their own baseline, but the thin sample is shrunk toward
    # neutral (0.5) while the full-confidence sample gets the full, undamped penalty (0.0).
    assert thin["components"]["engagement"] > mature["components"]["engagement"]
    assert mature["components"]["engagement"] == 0.0
    assert thin["components"]["engagement"] == pytest.approx(0.35, abs=0.01)  # 0.5 + 0.3*(0.0-0.5)


def test_mature_below_baseline_post_receives_full_justified_penalty() -> None:
    full_baseline = [100, 200, 150, 120, 180, 140, 160, 110, 190, 130]
    result = compute_editorial_score_v2(
        legacy_llm_score=70, published_at=NOW - timedelta(hours=10), collected_at=NOW - timedelta(hours=10),
        reference_now=NOW, reliability_score=0.7, event_metrics=_metrics(views=1), baseline_samples=full_baseline,
    )
    assert result["coverage"]["source_baseline_available"] is True
    assert result["components"]["engagement"] == 0.0  # full, undamped penalty - confidently measured


@pytest.mark.parametrize(
    ("engagement_available", "reliability_available"),
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_effective_weights_always_sum_to_one_regardless_of_availability(
    engagement_available: bool, reliability_available: bool
) -> None:
    metrics = _metrics(views=100) if engagement_available else _EMPTY_METRICS
    baseline = [10, 20, 30, 15, 25, 12, 18, 22, 28, 14] if engagement_available else []
    reliability = 0.6 if reliability_available else None

    result = _compute(event_metrics=metrics, baseline_samples=baseline, reliability_score=reliability)

    assert sum(result["weights"].values()) == pytest.approx(1.0)
    assert result["weights"]["novelty"] == 0.0  # always excluded, regardless of every other flag
    assert 0 <= result["score"] <= 100


def test_novelty_weight_is_permanently_zero_never_conditional() -> None:
    """Confirms the constant-reweighting design: novelty's effective weight is 0.0 even when
    every other signal is fully available (not merely when something else is missing)."""
    result = _compute(
        reliability_score=0.9,
        event_metrics=_metrics(views=1000),
        baseline_samples=[10, 20, 30, 15, 25, 12, 18, 22, 28, 14],
    )
    assert result["coverage"]["engagement_available"] is True
    assert result["coverage"]["source_reliability_available"] is True
    assert result["weights"]["novelty"] == 0.0
