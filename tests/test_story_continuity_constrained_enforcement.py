"""STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1 — focused tests for the enforcement predicate.

`evaluate_constrained_enforcement()` is pure. Every test builds a `ContinuityResult` (+ optional
`ContinuityIdentityAssessment`) directly and asserts whether the decision may be ACTUALLY
suppressed. The Founder policy (spec §0) allows suppression only for a near-certain,
identity-backed, delta-free `DUPLICATE_NO_DELTA` with the flag on.
"""
from __future__ import annotations

import pytest

from services.story_continuity import (
    CONTINUITY_AMBIGUOUS,
    CONTINUITY_DUPLICATE_NO_DELTA,
    CONTINUITY_MATERIAL_UPDATE_CANDIDATE,
    CONTINUITY_NEW_STORY,
    ContinuityResult,
    evaluate_constrained_enforcement,
    normalize_title_for_exact_match,
)
from services.story_delta_engine import DELTA_MATERIAL, DELTA_MINOR, DELTA_NONE
from services.story_identity_guard import (
    GUARD_FAIL_OPEN,
    GUARD_SAFE,
    IDENTITY_CONFLICT,
    IDENTITY_INSUFFICIENT,
    IDENTITY_MATCH,
    REASON_POLLUTED_STORY,
    REASON_STABLE_IDENTITY_CONFLICT,
    ContinuityIdentityAssessment,
)


def _dup(
    *,
    score: float = 1.0,
    delta_class: str | None = DELTA_NONE,
    guard_forced_fail_open: bool = False,
    stable_identity_status: str | None = IDENTITY_INSUFFICIENT,
    suppression_eligible: bool = True,
) -> ContinuityResult:
    return ContinuityResult(
        outcome=CONTINUITY_DUPLICATE_NO_DELTA,
        matched_story_id=None,
        match_score=score,
        confidence_band="high",
        delta_class=delta_class,
        suppression_eligible=suppression_eligible,
        reason_codes=("same_story", "semantic_duplicate", "no_new_facts"),
        guard_forced_fail_open=guard_forced_fail_open,
        stable_identity_status=stable_identity_status,
    )


def _ident(
    *,
    verdict: str = GUARD_SAFE,
    identity_status: str = IDENTITY_INSUFFICIENT,
    reason_codes: tuple[str, ...] = ("exact_title_identity_sufficient",),
) -> ContinuityIdentityAssessment:
    return ContinuityIdentityAssessment(
        verdict=verdict,
        identity_status=identity_status,
        identity_namespace="arxiv" if identity_status != IDENTITY_INSUFFICIENT else None,
        title_quality="TITLE_LIKE",
        new_identity=None,
        reason_codes=reason_codes,
    )


def _eval(continuity, *, enabled=True, would_suppress=True, ident=None, exact_title=False):
    return evaluate_constrained_enforcement(
        enabled=enabled,
        continuity=continuity,
        would_suppress_flag=would_suppress,
        identity_assessment=ident,
        exact_normalized_title_match=exact_title,
    )


# --- 1. true exact-title duplicate -> suppress eligible -----------------------------------------
def test_exact_normalized_title_duplicate_is_suppress_eligible() -> None:
    d = _eval(_dup(), ident=_ident(), exact_title=True)
    assert d.suppress is True
    assert d.reason.startswith("actually_suppressed:DUPLICATE_NO_DELTA")
    assert "EXACT_NORMALIZED_TITLE_MATCH" in d.reason
    assert d.evidence["exact_normalized_title_match"] is True
    assert d.evidence["polluted_story"] is False
    assert d.evidence["identity_conflict"] is False


# --- 2. stable identity (same base arXiv ID, clean) -> suppress eligible ------------------------
def test_stable_identity_match_duplicate_is_suppress_eligible() -> None:
    d = _eval(
        _dup(stable_identity_status=IDENTITY_MATCH),
        ident=_ident(identity_status=IDENTITY_MATCH, reason_codes=("stable_document_identity_match",)),
        exact_title=False,
    )
    assert d.suppress is True
    assert "STABLE_IDENTITY_MATCH" in d.reason


# --- 3. score just below 0.99 -> NOT suppressed ------------------------------------------------
def test_score_below_threshold_fails_open() -> None:
    d = _eval(_dup(score=0.989999), ident=_ident(), exact_title=True)
    assert d.suppress is False
    assert "below_0.99" in d.reason


# --- 4. score exactly 0.99 -> eligible only when an identity condition passes -----------------
def test_score_exactly_099_needs_identity() -> None:
    # exactly 0.99, exact-title present -> eligible
    ok = _eval(_dup(score=0.99), ident=_ident(), exact_title=True)
    assert ok.suppress is True
    # exactly 0.99, no stable-id and no exact-title -> fail open
    no = _eval(_dup(score=0.99), ident=_ident(reason_codes=("title_like_identity_not_required",)), exact_title=False)
    assert no.suppress is False
    assert "no_stable_identity_match_and_no_exact_title_match" in no.reason


# --- 5. fuzzy high score, no identity, no exact title -> NOT suppressed -----------------------
def test_fuzzy_high_score_without_identity_fails_open() -> None:
    d = _eval(
        _dup(score=1.0),
        ident=_ident(reason_codes=("title_like_identity_not_required",)),
        exact_title=False,
    )
    assert d.suppress is False
    assert "no_stable_identity_match_and_no_exact_title_match" in d.reason


# --- 6. AMBIGUOUS -> NOT suppressed ----------------------------------------------------------
def test_ambiguous_never_suppressed() -> None:
    c = ContinuityResult(
        outcome=CONTINUITY_AMBIGUOUS, matched_story_id=None, match_score=1.0,
        confidence_band="high", delta_class=DELTA_NONE, suppression_eligible=False,
        stable_identity_status=IDENTITY_MATCH,
    )
    d = _eval(c, ident=_ident(identity_status=IDENTITY_MATCH), exact_title=True)
    assert d.suppress is False
    assert "not_DUPLICATE_NO_DELTA" in d.reason


# --- 7. MATERIAL_UPDATE_CANDIDATE -> NOT suppressed -----------------------------------------
def test_material_update_candidate_never_suppressed() -> None:
    c = ContinuityResult(
        outcome=CONTINUITY_MATERIAL_UPDATE_CANDIDATE, matched_story_id=None, match_score=1.0,
        confidence_band="high", delta_class=DELTA_MATERIAL, suppression_eligible=False,
        stable_identity_status=IDENTITY_MATCH,
    )
    d = _eval(c, ident=_ident(identity_status=IDENTITY_MATCH), exact_title=True)
    assert d.suppress is False
    assert "not_DUPLICATE_NO_DELTA" in d.reason


# --- 8. different arXiv base IDs (identity conflict) -> NOT suppressed ------------------------
def test_stable_identity_conflict_never_suppressed() -> None:
    d = _eval(
        _dup(stable_identity_status=IDENTITY_CONFLICT),
        ident=_ident(
            verdict=GUARD_FAIL_OPEN, identity_status=IDENTITY_CONFLICT,
            reason_codes=(REASON_STABLE_IDENTITY_CONFLICT, "arxiv_identity_mismatch"),
        ),
        exact_title=True,
    )
    assert d.suppress is False
    # guard verdict is checked before the explicit conflict gate; either way it must fail open
    assert d.reason.startswith("fail_open:")
    assert d.evidence["identity_conflict"] is True


# --- 9. polluted Story at score 1.0 -> NOT suppressed ---------------------------------------
def test_polluted_story_never_suppressed_even_at_score_1() -> None:
    d = _eval(
        _dup(score=1.0),
        ident=_ident(
            verdict=GUARD_FAIL_OPEN, identity_status=IDENTITY_CONFLICT,
            reason_codes=(REASON_POLLUTED_STORY, "insufficient_document_identity"),
        ),
        exact_title=True,
    )
    assert d.suppress is False
    assert d.evidence["polluted_story"] is True


# --- 10. guard-forced fail-open -> NOT suppressed -----------------------------------------
def test_guard_forced_fail_open_never_suppressed() -> None:
    d = _eval(_dup(guard_forced_fail_open=True), ident=_ident(), exact_title=True)
    assert d.suppress is False
    assert "guard_forced_fail_open" in d.reason


# --- 11. same arXiv document, no material delta -> eligible -------------------------------
def test_same_arxiv_document_no_delta_is_eligible() -> None:
    d = _eval(
        _dup(delta_class=DELTA_NONE, stable_identity_status=IDENTITY_MATCH),
        ident=_ident(identity_status=IDENTITY_MATCH, reason_codes=("stable_document_identity_match",)),
    )
    assert d.suppress is True


# --- 12. same arXiv ID but a material/minor delta -> NOT suppressed ----------------------
@pytest.mark.parametrize("delta", [DELTA_MATERIAL, DELTA_MINOR, None])
def test_same_arxiv_id_with_delta_is_not_suppressed(delta: str | None) -> None:
    # A real delta would make classify_continuity() return MATERIAL_UPDATE_CANDIDATE, not
    # DUPLICATE_NO_DELTA - but even if a DUPLICATE_NO_DELTA row somehow carried a non-NONE
    # delta_class, the predicate must still refuse.
    d = _eval(
        _dup(delta_class=delta, stable_identity_status=IDENTITY_MATCH),
        ident=_ident(identity_status=IDENTITY_MATCH),
    )
    assert d.suppress is False
    assert "not_NO_DELTA" in d.reason


# --- 13. flag disabled -> NOT suppressed -------------------------------------------------
def test_flag_disabled_never_suppresses() -> None:
    d = _eval(_dup(), enabled=False, ident=_ident(), exact_title=True)
    assert d.suppress is False
    assert d.reason == "fail_open:flag_disabled"


# --- 14. would_suppress diagnostic not True -> NOT suppressed --------------------------
@pytest.mark.parametrize("ws", [False, None])
def test_would_suppress_flag_must_be_true(ws: bool | None) -> None:
    d = _eval(_dup(), would_suppress=ws, ident=_ident(), exact_title=True)
    assert d.suppress is False
    assert "would_suppress_not_true" in d.reason


# --- 15. NEW_STORY -> NOT suppressed ---------------------------------------------------
def test_new_story_never_suppressed() -> None:
    c = ContinuityResult(
        outcome=CONTINUITY_NEW_STORY, matched_story_id=None, match_score=1.0,
        confidence_band="high", delta_class=None, suppression_eligible=False,
    )
    d = _eval(c, ident=None, exact_title=False)
    assert d.suppress is False


# --- 16. suppression_eligible must be True on the ContinuityResult --------------------
def test_requires_suppression_eligible_flag() -> None:
    d = _eval(_dup(suppression_eligible=False), ident=_ident(), exact_title=True)
    assert d.suppress is False
    assert "not_suppression_eligible" in d.reason


# --- 17. identity guard verdict not SAFE (e.g. abstract-like unsafe) -> NOT suppressed
def test_identity_guard_non_safe_verdict_fails_open() -> None:
    d = _eval(
        _dup(),
        ident=_ident(verdict=GUARD_FAIL_OPEN, reason_codes=("abstract_like_title_unsafe_match",)),
        exact_title=True,
    )
    assert d.suppress is False
    assert "identity_guard_verdict_not_safe" in d.reason


# --- 18. deterministic normalization: only safe formatting differences collapse -------
def test_normalize_title_for_exact_match_is_narrow() -> None:
    assert normalize_title_for_exact_match("  Hello   World  ") == "hello world"
    assert normalize_title_for_exact_match("GPT-6 Released") == "gpt-6 released"
    # numbers and meaningful words are preserved (never stripped)
    assert normalize_title_for_exact_match("iPhone 17 Pro") == "iphone 17 pro"
    assert normalize_title_for_exact_match("Model v2 update") != normalize_title_for_exact_match("Model v3 update")
    # a paraphrase is NOT equal
    assert normalize_title_for_exact_match("Apple unveils the iPhone") != normalize_title_for_exact_match("Apple reveals the iPhone")


# --- 19. evidence record is always populated (audit, spec §9) ------------------------
def test_evidence_record_is_complete_on_fail_open_and_on_suppress() -> None:
    keys = {
        "policy_version", "enabled", "classification", "score", "delta_class",
        "suppression_eligible", "would_suppress", "guard_forced_fail_open",
        "stable_identity_status", "identity_verdict", "identity_namespace",
        "stable_identity_match", "exact_normalized_title_match", "polluted_story",
        "identity_conflict", "reason_codes",
    }
    suppressed = _eval(_dup(), ident=_ident(), exact_title=True)
    failed_open = _eval(_dup(score=0.5), ident=_ident(), exact_title=True)
    assert keys <= set(suppressed.evidence)
    assert keys <= set(failed_open.evidence)
    assert suppressed.evidence["policy_version"] == "p0_constrained_v1"


# =============================================================================================
# Integration: the predicate wired through _apply_story_memory() against a real DB session.
# =============================================================================================
from uuid import uuid4  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from database.models.news_source import NewsSource, SourceType  # noqa: E402
from database.models.story import Story  # noqa: E402
from database.models.story_link import NewsEventStoryLink  # noqa: E402
from services.story_memory import SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, MatchResult, extract_story_signature  # noqa: E402
from services.triage_orchestrator import TriageCycleReport, _apply_story_memory  # noqa: E402


async def _seed_story_with_prior(db_session: AsyncSession, title: str):
    src = NewsSource(name=f"p0-ce-{uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(src)
    await db_session.flush()
    prior = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI, hash=f"p0-ce-{uuid4()}")
    db_session.add(prior)
    await db_session.flush()
    sig = extract_story_signature(title, EventCategory.AI)
    story = Story(
        id=uuid4(), title=title, category=EventCategory.AI, entities=sig.entities,
        keywords=sig.keywords, topic_bucket=sig.topic_bucket, first_event_id=prior.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    db_session.add(NewsEventStoryLink(
        news_event_id=prior.id, story_id=story.id, match_type="new_story", match_score=1.0,
    ))
    await db_session.flush()
    return src, story, sig


@pytest.mark.asyncio
async def test_integration_exact_title_duplicate_suppressed_when_flag_on(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "story_continuity_p0_constrained_enforcement_enabled", True)
    title = "OpenAI releases GPT-6 with a 2M-token context window"
    src, story, sig = await _seed_story_with_prior(db_session, title)
    new_event = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI, hash=f"p0-ce-{uuid4()}")
    db_session.add(new_event)
    await db_session.flush()

    async def _fake(_s, *, title, category):  # noqa: ANN001, ARG001
        return sig, MatchResult(
            SEMANTIC_DUPLICATE, story.id, 1.0, "exact normalized title match",
            entity_overlap=0.0, has_distinctive_shared_entity=True,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake)
    report = TriageCycleReport()
    suppress = await _apply_story_memory(db_session, new_event, report)

    assert suppress is True
    assert report.story_tasks_suppressed == 1
    link = (
        await db_session.execute(
            select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == new_event.id)
        )
    ).scalar_one()
    assert link.final_decision == "DUPLICATE_NO_DELTA"
    assert "actually_suppressed=True" in link.decision_reason
    assert "actually_suppressed" in (link.material_delta or [])
    assert any(c.startswith("enforced:p0_constrained_v1") for c in (link.material_delta or []))
    # NewsEvent + Story history preserved
    assert await db_session.get(NewsEvent, new_event.id) is not None
    await db_session.refresh(story)
    assert story.event_count == 2  # SEMANTIC_DUPLICATE still bumps the story


@pytest.mark.asyncio
async def test_integration_flag_off_never_suppresses(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "story_continuity_p0_constrained_enforcement_enabled", False)
    title = "Anthropic ships Claude 5 to general availability"
    src, story, sig = await _seed_story_with_prior(db_session, title)
    new_event = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI, hash=f"p0-ce-{uuid4()}")
    db_session.add(new_event)
    await db_session.flush()

    async def _fake(_s, *, title, category):  # noqa: ANN001, ARG001
        return sig, MatchResult(
            SEMANTIC_DUPLICATE, story.id, 1.0, "exact normalized title match",
            entity_overlap=0.0, has_distinctive_shared_entity=True,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake)
    report = TriageCycleReport()
    suppress = await _apply_story_memory(db_session, new_event, report)

    assert suppress is False
    assert report.story_tasks_suppressed == 0
    link = (
        await db_session.execute(
            select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == new_event.id)
        )
    ).scalar_one()
    assert link.final_decision == "DUPLICATE_NO_DELTA"
    assert "actually_suppressed=False" in link.decision_reason
    assert "actually_suppressed" not in (link.material_delta or [])


@pytest.mark.asyncio
async def test_integration_low_score_fails_open_even_with_flag_on(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "story_continuity_p0_constrained_enforcement_enabled", True)
    title = "Google DeepMind announces Gemini 3 Ultra"
    src, story, sig = await _seed_story_with_prior(db_session, title)
    new_event = NewsEvent(source_id=src.id, title=title, category=EventCategory.AI, hash=f"p0-ce-{uuid4()}")
    db_session.add(new_event)
    await db_session.flush()

    async def _fake(_s, *, title, category):  # noqa: ANN001, ARG001
        return sig, MatchResult(
            SUPPORTING_SOURCE, story.id, 0.83, "supporting source, sub-threshold",
            entity_overlap=0.5, has_distinctive_shared_entity=True,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake)
    report = TriageCycleReport()
    suppress = await _apply_story_memory(db_session, new_event, report)

    assert suppress is False
    assert report.story_tasks_suppressed == 0
    link = (
        await db_session.execute(
            select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == new_event.id)
        )
    ).scalar_one()
    assert "actually_suppressed=False" in link.decision_reason
