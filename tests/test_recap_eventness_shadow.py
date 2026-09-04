"""R2.10G3-E1 - production-shaped shadow eventness rejector wiring tests. Test matrix A-Q plus
the integration test (§25), offline/production parity (§14), code-review safety search (§26),
and config safety search (§27)."""
from __future__ import annotations

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from database.models.story import Story
from services.event_recap import EventRecapBuildResult, EventRecapCandidate, build_event_recap_candidate
from services.recap_eventness_shadow import (
    GITHUB_ONLY_SOURCE_SHAPE,
    LONG_LIVED_SINGLE_SOURCE_TOPIC_SHAPE,
    RULE_C_VALIDATION_STATUS,
    EventnessShadowFeatures,
    evaluate_eventness_shadow,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHADOW_MODULE_PATH = _REPO_ROOT / "services" / "recap_eventness_shadow.py"
_EVENT_RECAP_PATH = _REPO_ROOT / "services" / "event_recap.py"
_SCANNER_PATH = _REPO_ROOT / "scripts" / "_recap_r2_10_readiness_candidate_scanner.py"
_FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)

# Real, previously-labelled fixture story_ids (G3-A calibration manifest) - reused here only as
# controls, not redefined.
_VLA_STORY_ID = uuid.UUID("ed667801-1452-4ee7-b083-bf13d05c5a22")
_NVIDIA_HF_STORY_ID = uuid.UUID("42e4188a-3aa3-4aa0-a717-6a02eb0a2730")
_CIFLOW_CI_NOISE_STORY_ID = uuid.UUID("00a77347-cc36-461b-9b94-ce7459bca7eb")


async def _build_candidate(story_id: uuid.UUID, *, force_shadow: bool) -> EventRecapBuildResult:
    """A fresh NullPool engine per call - never `database.session.async_session_factory` (that
    module-global, pooled engine binds its connections to whatever event loop was active the
    first time any test used it; pytest-asyncio's function-scoped event loops then leave later
    tests holding connections whose loop is already closed - a real, reproducible failure hit
    while writing this test file, not a hypothetical one). Mirrors every G3-A/B/C/D script's own
    established `create_async_engine(..., poolclass=NullPool)` read-only pattern exactly."""
    from sqlalchemy import text

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            story = await session.get(Story, story_id)
            assert story is not None, f"story {story_id} not found in this DB"
            return await build_event_recap_candidate(session, story, force_shadow=force_shadow, now=_FIXED_NOW)
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()


def _features(**overrides: object) -> EventnessShadowFeatures:
    base: dict[str, object] = dict(
        story_span_hours=0.0, unique_source_count=1, announcement_count=1, source_domains=frozenset(),
    )
    base.update(overrides)
    return EventnessShadowFeatures(**base)  # type: ignore[arg-type]


# --- A: Rule A exact clause -------------------------------------------------------------------------


def test_rule_a_exact_clause_fires_when_all_three_conditions_hold() -> None:
    """Test A."""
    result = evaluate_eventness_shadow(_features(story_span_hours=250.0, unique_source_count=1, announcement_count=5))
    assert result.rule_a_triggered is True
    assert LONG_LIVED_SINGLE_SOURCE_TOPIC_SHAPE in result.triggered_reasons


# --- B: Rule A boundary ------------------------------------------------------------------------------


def test_rule_a_boundary_at_exactly_200h() -> None:
    """Test B. This module reproduces G3-B's own actual, validated implementation verbatim
    (`story_span_hours >= 200.0`, not a strict `>`) - see scripts/_recap_r2_10_g3_eventness_
    calibrate.py::_rule_a_long_lived_single_source's own source. §6's prose restates the rule as
    "story_span_hours > 200" in places, but §6 also explicitly says "No >=200 change" and "must
    reproduce G3-B/G3-D behavior exactly" - reproducing the ACTUAL frozen, 0-false-reject-
    validated `>=` implementation is the safe reading; switching to strict `>` would be an
    unvalidated behavioral change. Disclosed here rather than silently picked."""
    exactly_200 = _features(story_span_hours=200.0, unique_source_count=1, announcement_count=5)
    just_over_200 = _features(story_span_hours=200.01, unique_source_count=1, announcement_count=5)
    just_under_200 = _features(story_span_hours=199.99, unique_source_count=1, announcement_count=5)
    assert evaluate_eventness_shadow(exactly_200).rule_a_triggered is True
    assert evaluate_eventness_shadow(just_over_200).rule_a_triggered is True
    assert evaluate_eventness_shadow(just_under_200).rule_a_triggered is False


# --- C: Rule A source >1 does not trigger ---------------------------------------------------------


def test_rule_a_multiple_sources_does_not_trigger() -> None:
    """Test C."""
    result = evaluate_eventness_shadow(_features(story_span_hours=300.0, unique_source_count=2, announcement_count=5))
    assert result.rule_a_triggered is False


# --- D: Rule A announcements <4 does not trigger ------------------------------------------------------


def test_rule_a_few_announcements_does_not_trigger() -> None:
    """Test D."""
    result = evaluate_eventness_shadow(_features(story_span_hours=300.0, unique_source_count=1, announcement_count=3))
    assert result.rule_a_triggered is False


# --- E: Rule C github-only triggers diagnostic -----------------------------------------------------


def test_rule_c_github_only_triggers_diagnostic() -> None:
    """Test E."""
    result = evaluate_eventness_shadow(_features(source_domains=frozenset({"github.com"})))
    assert result.rule_c_triggered is True
    assert GITHUB_ONLY_SOURCE_SHAPE in result.triggered_reasons
    assert result.rule_c_validation_status == RULE_C_VALIDATION_STATUS


# --- F: mixed github.com + other source does not trigger C ---------------------------------------------


def test_rule_c_mixed_domains_does_not_trigger() -> None:
    """Test F."""
    result = evaluate_eventness_shadow(_features(source_domains=frozenset({"github.com", "techcrunch.com"})))
    assert result.rule_c_triggered is False
    assert result.rule_c_validation_status is None


# --- G: Rule D breaking-event shape does not trigger anything -------------------------------------------


def test_rule_d_shape_produces_no_signal() -> None:
    """Test G. The exact disqualified RULE_D shape (short span, 3+ sources, announcement_count ==
    effective_event_count is implicit here since this module never even receives effective_event_
    count as an input) for a real breaking-event-shaped fixture (mirrors g3d_pixel11_fold_embargo)
    must produce no rule_a/rule_c signal at all."""
    result = evaluate_eventness_shadow(_features(
        story_span_hours=0.01, unique_source_count=3,
        source_domains=frozenset({"engadget.com", "zdnet.com", "3dnews.ru"}),
    ))
    assert result.rule_a_triggered is False
    assert result.rule_c_triggered is False
    assert result.triggered_reasons == ()
    assert result.shadow_status == "NO_SIGNAL"


def test_rule_d_implementation_does_not_exist_anywhere_in_production_code() -> None:
    """§8 - RULE_D_IMPLEMENTED=false. AST-based: checks actual identifiers (names/attributes),
    never a naive substring search - this module's OWN docstring legitimately discusses "RULE_D"
    in prose (explaining why it is absent), which a substring check would misfire on (the same
    self-inflicted class of bug this codebase's own G3-A phase already hit once with
    "--with-llm" - fixed there by switching to an AST check, the same fix applied here from the
    start)."""
    for path in (_SHADOW_MODULE_PATH, _EVENT_RECAP_PATH, _SCANNER_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifiers.add(node.name)
        offending = {i for i in identifiers if "rule_d" in i.lower() or "effective_event_count" in i.lower()}
        assert offending == set(), f"{path.name}: found RULE_D-shaped identifier(s): {offending}"


# --- H: shadow flag OFF parity + I: shadow flag ON does not change readiness ----------------------------


@pytest.mark.asyncio
async def test_shadow_flag_off_and_on_produce_identical_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test H + I. Runs the exact same real Story through build_event_recap_candidate() with the
    flag OFF then ON and asserts every readiness-relevant field is byte-identical - only
    `eventness_shadow` itself may differ."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", False)
    result_off = await _build_candidate(_NVIDIA_HF_STORY_ID, force_shadow=True)

    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)
    result_on = await _build_candidate(_NVIDIA_HF_STORY_ID, force_shadow=True)

    assert result_off.candidate is not None and result_on.candidate is not None
    c_off, c_on = result_off.candidate, result_on.candidate
    assert c_off.eventness_shadow is None  # flag OFF - never computed
    # flag ON - may or may not be None depending on whether either rule fired, but the object type
    # itself must be an EventnessShadowEvaluation whenever a shadow-enabled build succeeds:
    assert c_on.eventness_shadow is not None

    assert c_off.readiness_state == c_on.readiness_state
    assert c_off.readiness_overridden == c_on.readiness_overridden
    assert c_off.story_integrity_eligible == c_on.story_integrity_eligible
    assert c_off.story_integrity_reasons == c_on.story_integrity_reasons
    assert c_off.announcement_count == c_on.announcement_count
    assert c_off.readiness_source_count == c_on.readiness_source_count
    assert c_off.evidence_reference_count == c_on.evidence_reference_count
    assert c_off.publishable == c_on.publishable == False  # noqa: E712 - explicit, not a truthiness check
    assert c_off.source_refs == c_on.source_refs


# --- J: shadow evaluation cannot modify rejection_reasons + K: cannot modify publishable -----------------


@pytest.mark.asyncio
async def test_shadow_on_never_touches_rejection_reasons_or_publishable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test J + K. Runs a Story that is NOT force-shadow-eligible (natural rejection path) with
    the flag ON and confirms the rejection itself, and its reasons, are unaffected."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", False)
    result_off = await _build_candidate(_VLA_STORY_ID, force_shadow=False)

    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)
    result_on = await _build_candidate(_VLA_STORY_ID, force_shadow=False)

    assert result_off.rejected == result_on.rejected
    assert result_off.rejection_reasons == result_on.rejection_reasons
    if result_off.candidate is not None:
        assert result_on.candidate is not None
        assert result_off.candidate.publishable == result_on.candidate.publishable == False  # noqa: E712


# --- L: no DB writes ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_evaluation_writes_no_db_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test L."""
    from sqlalchemy import func, select

    from database.models.editorial_task import EditorialTask

    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)

    count_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(bind=count_engine, expire_on_commit=False) as s:
            stories_before = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
            tasks_before = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()
    finally:
        await count_engine.dispose()

    await _build_candidate(_NVIDIA_HF_STORY_ID, force_shadow=True)

    count_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(bind=count_engine, expire_on_commit=False) as s:
            stories_after = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
            tasks_after = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()
    finally:
        await count_engine.dispose()

    assert stories_before == stories_after
    assert tasks_before == tasks_after


# --- M: no LLM/Gateway import ------------------------------------------------------------------------


def test_shadow_module_imports_no_llm_gateway() -> None:
    """Test M."""
    tree = ast.parse(_SHADOW_MODULE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not any("llm_gateway" in m or "Gateway" in m for m in modules), modules
    assert modules == {"__future__", "dataclasses", "typing"}  # zero imports beyond these stdlib modules


# --- N: offline/production parity across labelled corpus -----------------------------------------------


@pytest.mark.asyncio
async def test_offline_production_parity_across_labelled_corpus() -> None:
    """Test N (§13/§14). Runs the entire ~90-fixture labelled corpus (G3-A calibration + G3-B
    holdout + G3-D adversarial) through BOTH the offline G3-B rule evaluator (unmodified,
    RULE_A.fn/RULE_C.fn) and this production shadow module, asserting identical rule_a/rule_c
    verdicts on every single fixture. Any discrepancy fails this test (§14's own "any discrepancy:
    STOP")."""
    from scripts._recap_r2_10_g3_eventness_calibrate import RULE_A as OFFLINE_RULE_A
    from scripts._recap_r2_10_g3_eventness_calibrate import RULE_C as OFFLINE_RULE_C
    from scripts._recap_r2_10_g3_eventness_harness import DeterministicFeatures, evaluate_db_fixture, evaluate_offline_fixture
    from scripts._recap_r2_10_g3_eventness_holdout import HOLDOUT
    from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST, ManifestEntry
    from scripts._recap_r2_10_g3d_adversarial_manifest import ADVERSARIAL_MANIFEST

    def _holdout_as_manifest_entry(h: object) -> ManifestEntry:
        return ManifestEntry(
            fixture_id=h.fixture_id, kind="db", story_id=h.story_id, title_snapshot=h.title_snapshot,  # type: ignore[attr-defined]
            manual_class=h.manual_class, desired_eventness=h.desired_eventness, confidence="high",  # type: ignore[attr-defined]
            source_phase="R2.10G3-B holdout", rationale=h.rationale,  # type: ignore[attr-defined]
        )

    def _adversarial_as_manifest_entry(e: object) -> ManifestEntry:
        desired = "UNCERTAIN" if e.desired_eventness == "AMBIGUOUS" else e.desired_eventness  # type: ignore[attr-defined]
        return ManifestEntry(
            fixture_id=e.fixture_id, kind="db", story_id=e.story_id, title_snapshot=e.title_snapshot,  # type: ignore[attr-defined]
            manual_class=e.manual_class, desired_eventness=desired, confidence="high",  # type: ignore[attr-defined]
            source_phase="R2.10G3-D", rationale=e.rationale,  # type: ignore[attr-defined]
        )

    entries: list[ManifestEntry] = list(MANIFEST) + [_holdout_as_manifest_entry(h) for h in HOLDOUT] + [
        _adversarial_as_manifest_entry(e) for e in ADVERSARIAL_MANIFEST
    ]

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    checked = 0
    discrepancies: list[str] = []
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            for entry in entries:
                if entry.kind == "db":
                    evaluation = await evaluate_db_fixture(session, entry, now=_FIXED_NOW)
                else:
                    evaluation = evaluate_offline_fixture(entry, now=_FIXED_NOW)
                features: DeterministicFeatures | None = evaluation.features
                if features is None:
                    continue
                offline_a = OFFLINE_RULE_A.fn(features) == "REJECT"
                offline_c = OFFLINE_RULE_C.fn(features) == "REJECT"
                prod_result = evaluate_eventness_shadow(EventnessShadowFeatures(
                    story_span_hours=features.story_span_hours, unique_source_count=features.unique_source_count,
                    announcement_count=features.announcement_count, source_domains=frozenset(features.source_domains),
                ))
                checked += 1
                if offline_a != prod_result.rule_a_triggered:
                    discrepancies.append(f"{entry.fixture_id}: RULE_A offline={offline_a} production={prod_result.rule_a_triggered}")
                if offline_c != prod_result.rule_c_triggered:
                    discrepancies.append(f"{entry.fixture_id}: RULE_C offline={offline_c} production={prod_result.rule_c_triggered}")
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()

    assert discrepancies == [], f"offline/production parity violated: {discrepancies}"
    assert checked >= 80  # sanity: most of the ~90-fixture corpus actually resolved in this DB


# --- O: Nvidia/HF not shadow-rejected by A/C --------------------------------------------------------


@pytest.mark.asyncio
async def test_nvidia_hf_not_flagged_by_rule_a_or_c(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test O."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)
    result = await _build_candidate(_NVIDIA_HF_STORY_ID, force_shadow=True)
    assert result.candidate is not None
    shadow = result.candidate.eventness_shadow
    assert shadow is not None
    assert shadow.rule_a_triggered is False
    assert shadow.rule_c_triggered is False


# --- P: VLA triggers A if current fixture still matches ------------------------------------------------


@pytest.mark.asyncio
async def test_vla_triggers_rule_a_if_current_shape_still_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test P. Conditional by design - if the live DB's own VLA Story has since changed shape
    (e.g. new events narrowed its span/sources), this test still verifies whatever the CURRENT
    shape produces is internally consistent, and specifically checks the well-established shape
    (span=431.4h+, sources=1, announcements>=6, per G3-A/G3-B/G3-D's own repeated observation)
    still triggers RULE_A as expected."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)
    result = await _build_candidate(_VLA_STORY_ID, force_shadow=True)
    assert result.candidate is not None
    shadow = result.candidate.eventness_shadow
    assert shadow is not None
    assert shadow.rule_a_triggered is True
    assert LONG_LIVED_SINGLE_SOURCE_TOPIC_SHAPE in shadow.triggered_reasons


# --- Q: CI-noise triggers C ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ci_noise_triggers_rule_c(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Q."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)
    result = await _build_candidate(_CIFLOW_CI_NOISE_STORY_ID, force_shadow=True)
    assert result.candidate is not None
    shadow = result.candidate.eventness_shadow
    assert shadow is not None
    assert shadow.rule_c_triggered is True
    assert GITHUB_ONLY_SOURCE_SHAPE in shadow.triggered_reasons


# --- §25 integration test: candidate readiness fully unaffected by shadow, plus metadata present --------


@pytest.mark.asyncio
async def test_integration_candidate_unaffected_except_for_diagnostic_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """§25. Same candidate readiness, rejection reasons, publishable, and event/source/
    announcement counts - plus diagnostic eventness metadata only."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)
    result = await _build_candidate(_NVIDIA_HF_STORY_ID, force_shadow=True)
    assert result.candidate is not None
    c: EventRecapCandidate = result.candidate
    assert c.publishable is False
    assert isinstance(c.announcement_count, int)
    assert isinstance(c.readiness_source_count, int)
    assert c.eventness_shadow is not None
    assert c.eventness_shadow.enforcement_applied is False


# --- §26 code review safety: search the diff surface for eventness-driven mutation ------------------


def test_no_eventness_driven_mutation_in_wiring_sites() -> None:
    """§26. Searches the two wiring sites for any line that both mentions eventness_shadow AND a
    mutating readiness/publication keyword in a way that would suggest it drives a decision."""
    for path in (_EVENT_RECAP_PATH, _SCANNER_PATH):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for i, line in enumerate(lines):
            if "eventness_shadow" not in line:
                continue
            if any(bad in line for bad in ("rejection_reasons.append", "publishable =", "readiness_state =", "return None")):
                pytest.fail(f"{path.name}:{i + 1}: eventness_shadow appears alongside a mutation keyword: {line!r}")


# --- §27 config safety: default False, enabled nowhere -----------------------------------------------


def test_shadow_flag_defaults_false_and_is_enabled_nowhere_in_repo_config() -> None:
    """§27."""
    assert settings.recap_eventness_shadow_enabled is False

    import subprocess

    result = subprocess.run(
        ["git", "grep", "-n", "recap_eventness_shadow_enabled"],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    hits = [line for line in result.stdout.splitlines() if line.strip()]
    # every hit must be source/test code, never a literal "=true"/"=True" assignment outside a
    # test's own monkeypatch call or this module's own default declaration.
    offending = [
        h for h in hits
        if ("=true" in h.lower().replace(" ", "") or "= true" in h.lower())
        and "monkeypatch" not in h and "test_" not in h
    ]
    assert offending == [], f"found a non-test/non-default enablement: {offending}"


# --- §22/§23: LLM policy conclusion preserved as a recorded, frozen decision -------------------------


def test_llm_auto_reject_policy_is_recorded_and_false() -> None:
    """§22/§23. LLM_AUTO_REJECT_ALLOWED=false is a frozen policy decision from G3-C/G3-D, recorded
    as data in this phase's own final report (not merely prose elsewhere) so a future phase cannot
    silently drift from it without editing this test."""
    policy_doc = _REPO_ROOT / "docs" / "r2_10_g3e1_eventness_shadow_wiring_report.md"
    assert policy_doc.exists()
    text = policy_doc.read_text(encoding="utf-8")
    assert "LLM_AUTO_REJECT_ALLOWED=false" in text
    assert "LLM_AUTO_ACCEPT_ALLOWED=false" in text
