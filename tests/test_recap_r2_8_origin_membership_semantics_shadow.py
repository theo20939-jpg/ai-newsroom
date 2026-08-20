"""NINJA PULSE RECAP Phase R2.8 - Story Origin/Membership Semantics Shadow tests.

Covers `scripts/_recap_r2_8_origin_membership_semantics_shadow.py`'s own fail-closed
`classify_origin_projection()`, the `ORIGIN_ANCHOR_ONLY` A1/A2 equivalence claim, the
`ORIGIN_IS_OWN_MEMBER` strict-eligibility model, `shadow_build_candidate()`'s structural-only RECAP
candidate shadow, and a source-level write-safety audit (never trusts the script's own docstring -
verifies by inspecting its actual text for write-capable calls).

NO production DB, NO LLM, NO Gateway, NO provider, NO network, NO writes anywhere in this file -
DB-touching cases use only the shared `db_session` fixture (tests/conftest.py, SAVEPOINT-rolled-
back local test DB), mirroring `tests/test_recap_r2_7_anchor_lifecycle_forensic.py`'s own pattern.
`scripts` is a real Python package (`scripts/__init__.py` exists) so the module under test is
imported normally - no importlib.util loader hack needed here.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from scripts._recap_r2_8_origin_membership_semantics_shadow import (
    ORIGIN_EVENT_MISSING,
    ORIGIN_LINK_MISSING,
    ORIGIN_LINK_WRONG_STORY,
    ORIGIN_MATCH_TYPE_UNEXPECTED,
    ORIGIN_PLUS_COHERENT_MEMBERS,
    ORIGIN_PLUS_INCOHERENT_MEMBERS,
    ORIGIN_PROJECTION_ELIGIBLE,
    ORIGIN_PROJECTION_NOT_NEEDED,
    ZERO_CONFIRMED_ORIGIN_ONLY,
    RecapCandidateShadow,
    _process_story,
    classify_origin_projection,
    classify_semantic_shape,
    evaluate_origin_anchor_only,
    shadow_build_candidate,
)
from services.recap_event import load_story_events
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    MatchResult,
    extract_story_signature,
)
from services.triage_orchestrator import TriageCycleReport, _apply_story_memory

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


async def _seed_existing_story(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> Story:
    source = NewsSource(name=f"r28-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"r28-test-{uuid4()}")
    session.add(event)
    await session.flush()
    signature = extract_story_signature(title, category)
    story = Story(
        id=uuid4(), title=title, category=category, entities=signature.entities,
        keywords=signature.keywords, topic_bucket=signature.topic_bucket, first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    return story


async def _new_event(
    session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI,
    published_at: datetime | None = None,
) -> NewsEvent:
    source = NewsSource(name=f"r28-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, category=category, hash=f"r28-test-{uuid4()}", published_at=published_at,
    )
    session.add(event)
    await session.flush()
    return event


async def _attach_link(session: AsyncSession, event: NewsEvent, story: Story, match_type: str, score: float = 0.9) -> NewsEventStoryLink:
    link = NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=score)
    session.add(link)
    await session.flush()
    return link


async def _apply_related_or_uncertain_root(
    session: AsyncSession, title: str, *, outcome: str, monkeypatch: pytest.MonkeyPatch,
    entity_overlap: float = 0.1, category: EventCategory = EventCategory.AI,
) -> tuple[Story, NewsEvent]:
    """Real, unmodified `_apply_story_memory()` call (mirrors R2.7's own reproduction pattern) -
    the SAME production code path that creates the anchor-missing state, never hand-constructed."""
    unrelated = await _seed_existing_story(session, "Unrelated older story about something else entirely", category=category)
    root_event = await _new_event(session, title, category=category)

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(outcome, unrelated.id, 0.3, "test", entity_overlap=entity_overlap)

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)
    report = TriageCycleReport()
    await _apply_story_memory(session, root_event, report)

    link = (
        await session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    story = await session.get(Story, link.story_id)
    assert story is not None
    return story, root_event


# ---------------------------------------------------------------------------
# 1. NEW_STORY root already confirmed - projection not needed; all models equivalent.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_story_root_already_confirmed_projection_not_needed(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story = await _seed_existing_story(db_session, "A genuinely new, self-originating story")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    # NEW_STORY-created Stories via _seed_existing_story never write a link row themselves (that
    # helper mirrors R2.7's own seeding convention) - use _apply_story_memory() for a real NEW_STORY
    # link instead, so this test actually exercises a real confirmed own-link.
    other_story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Totally standalone headline nobody has covered", outcome=NEW_STORY, entity_overlap=0.0, monkeypatch=monkeypatch,
    )
    own_link = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    assert own_link.match_type == NEW_STORY

    decision = classify_origin_projection(other_story, root_event, [own_link])
    assert decision.reason_code == ORIGIN_PROJECTION_NOT_NEEDED
    assert decision.eligible is False

    confirmed = await load_story_events(db_session, other_story.id)
    assert root_event.id in {e.id for e in confirmed}
    classification = classify_semantic_shape(confirmed, decision, None)
    from scripts._recap_r2_8_origin_membership_semantics_shadow import UNEXPECTED_STATE
    assert classification == UNEXPECTED_STATE  # this Story was never actually anchor-missing


# ---------------------------------------------------------------------------
# 2/3/13. RELATED_STORY / UNCERTAIN_MATCH root, zero confirmed members (dominant production shape,
# 90/106 per R2.7's own frozen evidence - item 13 = the exact R2.7 production shape).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [RELATED_STORY, UNCERTAIN_MATCH])
async def test_root_zero_confirmed_origin_projection_deterministic(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, outcome: str) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, f"Zero-confirmed {outcome} root story", outcome=outcome, monkeypatch=monkeypatch,
    )
    confirmed = await load_story_events(db_session, story.id)
    assert confirmed == []
    assert story.event_count == 1  # declared_event_count - the R2.7-documented mismatch (Part F)

    bundle = await _process_story(db_session, story, confirmed, now=_NOW)
    assert bundle["projection"].reason_code == ORIGIN_PROJECTION_ELIGIBLE
    assert bundle["current_rejected"] is True
    # Single-event story - evaluate_recap_story_integrity()'s own "no group to be incoherent" PASS.
    assert bundle["origin_anchor_only_a1"].eligible is True
    assert bundle["origin_anchor_only_a2"].eligible is True
    assert bundle["origin_is_own_member_integrity"].eligible is True
    assert bundle["classification"] == ZERO_CONFIRMED_ORIGIN_ONLY
    # Story Integrity PASS != RECAP readiness (spec's own explicit distinction) - a single real
    # event can never clear recap_min_event_count/announcement_count, so the candidate shadow must
    # still be rejected (on READINESS grounds, not integrity) unless force_shadow-style override
    # semantics are applied elsewhere - shadow_build_candidate() itself has no force_shadow bypass,
    # so it reports readiness_ready=False here, never silently treating this as publishable.
    candidate = bundle["origin_is_own_member_candidate"]
    assert candidate.rejected is False  # integrity passed, so a structural shadow candidate exists
    assert candidate.story_integrity_eligible is True
    assert candidate.readiness_ready is False  # single event never meets recap_min_event_count


# ---------------------------------------------------------------------------
# 4. RELATED root + identical later confirmed duplicate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_related_root_plus_identical_confirmed_duplicate(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    title = "Central bank announces new interest rate policy for next quarter"
    story, root_event = await _apply_related_or_uncertain_root(db_session, title, outcome=RELATED_STORY, monkeypatch=monkeypatch)
    dup_event = await _new_event(db_session, title, published_at=_NOW - timedelta(minutes=5))
    await _attach_link(db_session, dup_event, story, SUPPORTING_SOURCE)
    story.event_count += 1
    await db_session.flush()

    confirmed = await load_story_events(db_session, story.id)
    assert [e.id for e in confirmed] == [dup_event.id]

    bundle = await _process_story(db_session, story, confirmed, now=_NOW)
    assert bundle["origin_is_own_member_integrity"].eligible is True
    assert bundle["classification"] == ORIGIN_PLUS_COHERENT_MEMBERS


# ---------------------------------------------------------------------------
# 5. RELATED root + two coherent later members.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_related_root_plus_coherent_members(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Acme Corp announces record quarterly earnings driven by cloud division", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    m1 = await _new_event(
        db_session, "Acme Corp cloud division revenue up sharply this quarter", published_at=_NOW - timedelta(hours=1),
    )
    m2 = await _new_event(
        db_session, "Acme Corp stock jumps after strong cloud earnings report", published_at=_NOW - timedelta(minutes=30),
    )
    await _attach_link(db_session, m1, story, STORY_UPDATE)
    await _attach_link(db_session, m2, story, STORY_UPDATE)
    story.event_count += 2
    await db_session.flush()

    confirmed = await load_story_events(db_session, story.id)
    assert len(confirmed) == 2

    bundle = await _process_story(db_session, story, confirmed, now=_NOW)
    assert bundle["origin_is_own_member_integrity"].eligible is True
    assert bundle["classification"] == ORIGIN_PLUS_COHERENT_MEMBERS


# ---------------------------------------------------------------------------
# 6/14/15. RELATED/UNCERTAIN root + INCOHERENT later members - origin projection must NOT create a
# false PASS. Item 14 = broad generic-research-cluster style, item 15 = unrelated-topics style
# (mirrors R2.7's own two named production FAIL examples).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_related_root_plus_incoherent_members_stays_fail(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Quantum computing startup raises new funding round", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    m1 = await _new_event(db_session, "Local bakery wins regional pastry competition", published_at=_NOW - timedelta(hours=2))
    m2 = await _new_event(db_session, "City council approves new bike lane project", published_at=_NOW - timedelta(hours=1))
    await _attach_link(db_session, m1, story, STORY_UPDATE)
    await _attach_link(db_session, m2, story, STORY_UPDATE)
    story.event_count += 2
    await db_session.flush()

    confirmed = await load_story_events(db_session, story.id)
    bundle = await _process_story(db_session, story, confirmed, now=_NOW)
    assert bundle["origin_anchor_only_a1"].eligible is False
    assert bundle["origin_anchor_only_a2"].eligible is False
    assert bundle["origin_is_own_member_integrity"].eligible is False
    assert bundle["classification"] == ORIGIN_PLUS_INCOHERENT_MEMBERS
    assert bundle["origin_is_own_member_candidate"].rejected is True


@pytest.mark.asyncio
async def test_broad_generic_research_cluster_style_projection_preserves_fail(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors R2.7's own real production FAIL example (Story b312bb8b..., 14 confirmed members,
    anchor_coherent_ratio ~0.077) - a generic "Large language models..." opener shared by otherwise
    unrelated abstracts must not become a false PASS merely because the anchor changed."""
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Large language models show emergent reasoning capabilities in new study", outcome=UNCERTAIN_MATCH,
        entity_overlap=0.1, monkeypatch=monkeypatch,
    )
    members = [
        "Large language models for medical diagnosis show promising early results",
        "Large language models struggle with basic arithmetic tasks study finds",
        "Large language models raise new questions about copyright and training data",
        "Large language models deployed in customer service see mixed reception",
    ]
    for i, title in enumerate(members):
        event = await _new_event(db_session, title, published_at=_NOW - timedelta(hours=i + 1))
        await _attach_link(db_session, event, story, STORY_UPDATE)
    story.event_count += len(members)
    await db_session.flush()

    confirmed = await load_story_events(db_session, story.id)
    bundle = await _process_story(db_session, story, confirmed, now=_NOW)
    assert bundle["origin_is_own_member_integrity"].eligible is False, (
        f"false PASS on a broad generic-opener cluster: {bundle['origin_is_own_member_integrity']}"
    )
    assert bundle["classification"] == ORIGIN_PLUS_INCOHERENT_MEMBERS


@pytest.mark.asyncio
async def test_unrelated_topics_cluster_style_projection_preserves_fail(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors R2.7's own real production FAIL example (Story 272352b7..., Russian .ru/.рф domains
    origin with unrelated web-standards/fastest-star members, coherence=0.0)."""
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Почта на русском: в доменах .ru и .рф разрешили полностью кириллические адреса",
        outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    web_standards = await _new_event(
        db_session, "New web standards proposal aims to simplify browser APIs", published_at=_NOW - timedelta(hours=2),
    )
    fastest_star = await _new_event(
        db_session, "Astronomers discover the fastest-moving star ever recorded", published_at=_NOW - timedelta(hours=1),
    )
    await _attach_link(db_session, web_standards, story, STORY_UPDATE)
    await _attach_link(db_session, fastest_star, story, STORY_UPDATE)
    story.event_count += 2
    await db_session.flush()

    confirmed = await load_story_events(db_session, story.id)
    bundle = await _process_story(db_session, story, confirmed, now=_NOW)
    assert bundle["origin_is_own_member_integrity"].eligible is False
    assert bundle["classification"] == ORIGIN_PLUS_INCOHERENT_MEMBERS


# ---------------------------------------------------------------------------
# 7/10. Wrong-story origin link - fail closed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_origin_link_points_to_another_story_fails_closed(db_session: AsyncSession) -> None:
    other_story = await _seed_existing_story(db_session, "Some other, unrelated story")
    fabricated_story = Story(
        id=uuid4(), title="Fabricated Story pointing at someone else's event", category=EventCategory.AI,
        entities=[], keywords=[], topic_bucket="general",
        first_event_id=other_story.first_event_id, event_count=1,
    )
    db_session.add(fabricated_story)
    await db_session.flush()

    origin_event = await db_session.get(NewsEvent, other_story.first_event_id)
    assert origin_event is not None
    all_links = list(
        (await db_session.execute(
            select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == origin_event.id)
        )).scalars().all()
    )
    # other_story's own seeding helper never wrote a link row - simulate the real current-other-
    # story link this check exists to catch.
    link = NewsEventStoryLink(news_event_id=origin_event.id, story_id=other_story.id, match_type=RELATED_STORY, match_score=0.3)
    db_session.add(link)
    await db_session.flush()
    all_links = [link]

    decision = classify_origin_projection(fabricated_story, origin_event, all_links)
    assert decision.reason_code == ORIGIN_LINK_WRONG_STORY
    assert decision.eligible is False


# ---------------------------------------------------------------------------
# 8. Missing origin event - fail closed.
# ---------------------------------------------------------------------------


def test_missing_origin_event_fails_closed() -> None:
    story = Story(
        id=uuid4(), title="Story with a phantom origin", category=EventCategory.AI,
        entities=[], keywords=[], topic_bucket="general", first_event_id=uuid4(), event_count=1,
    )
    decision = classify_origin_projection(story, None, [])
    assert decision.reason_code == ORIGIN_EVENT_MISSING
    assert decision.eligible is False


# ---------------------------------------------------------------------------
# 9. Unexpected origin match type - fail closed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_match_type_fails_closed(db_session: AsyncSession) -> None:
    story = await _seed_existing_story(db_session, "Story whose origin link has a future/unknown match_type")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    link = NewsEventStoryLink(
        news_event_id=event.id, story_id=story.id, match_type="future_unknown_outcome", match_score=0.5,
    )
    db_session.add(link)
    await db_session.flush()

    decision = classify_origin_projection(story, event, [link])
    assert decision.reason_code == ORIGIN_MATCH_TYPE_UNEXPECTED
    assert decision.eligible is False


@pytest.mark.asyncio
async def test_origin_event_with_no_link_at_all_fails_closed(db_session: AsyncSession) -> None:
    """Part H's ORIGIN_LINK_MISSING - the declared event exists but no NewsEventStoryLink row was
    ever written for it (possible in principle - `_apply_story_memory()` always writes one for the
    real production path, but this checker must not assume that invariant, only prove it)."""
    story = await _seed_existing_story(db_session, "Story whose origin has literally no link row")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    decision = classify_origin_projection(story, event, [])
    assert decision.reason_code == ORIGIN_LINK_MISSING
    assert decision.eligible is False


# ---------------------------------------------------------------------------
# 11. No mutation - original Story/Event/Link snapshots unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_mutation_of_story_event_or_link(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "A story that must remain byte-identical after shadow analysis", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    before_story = (story.id, story.title, story.first_event_id, story.event_count)
    before_event = (root_event.id, root_event.title)
    link_before = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    before_link = (link_before.news_event_id, link_before.story_id, link_before.match_type, link_before.match_score)

    confirmed = await load_story_events(db_session, story.id)
    await _process_story(db_session, story, confirmed, now=_NOW)

    await db_session.refresh(story)
    await db_session.refresh(root_event)
    link_after = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()

    assert (story.id, story.title, story.first_event_id, story.event_count) == before_story
    assert (root_event.id, root_event.title) == before_event
    assert (link_after.news_event_id, link_after.story_id, link_after.match_type, link_after.match_score) == before_link


# ---------------------------------------------------------------------------
# 12. event_count mismatch forensic fixture.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_count_forensic_mismatch_documented(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Part F: Story.event_count=1 at RELATED_STORY-rooted creation, one actual link row, but ZERO
    confirmed members - the exact same creation-time split R2.7 found for first_event_id, exposed
    identically by event_count. Documented only - never fixed here."""
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "event_count forensic fixture story", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    confirmed = await load_story_events(db_session, story.id)
    bundle = await _process_story(db_session, story, confirmed, now=_NOW)

    assert bundle["declared_event_count"] == 1
    assert bundle["actual_link_count_for_declared_event"] == 1
    assert bundle["confirmed_member_count"] == 0


# ---------------------------------------------------------------------------
# 16. Candidate build shadow - no LLM, publishable never representable as True.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_candidate_never_representable_as_publishable(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Shadow candidate publishable=False check story", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    result = await shadow_build_candidate(db_session, root_event, [root_event], now=_NOW)
    assert "publishable" not in RecapCandidateShadow.__dataclass_fields__
    assert result.force_shadow is True


@pytest.mark.asyncio
async def test_shadow_candidate_rejects_when_anchor_not_in_members(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "Anchor-not-in-members shadow rejection story", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    other_event = await _new_event(db_session, "A completely different event not in the member list")
    result = await shadow_build_candidate(db_session, root_event, [other_event], now=_NOW)
    assert result.rejected is True
    assert "anchor not present" in result.rejection_reasons[0]


# ---------------------------------------------------------------------------
# ORIGIN_ANCHOR_ONLY A1/A2 equivalence claim (Part G "do not silently choose between them" -
# proven, not assumed).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_origin_anchor_only_a1_a2_integrity_equivalence(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "A1/A2 equivalence check story", outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    m1 = await _new_event(db_session, "A1/A2 equivalence check story follow-up coverage", published_at=_NOW)
    await _attach_link(db_session, m1, story, STORY_UPDATE)
    await db_session.flush()

    confirmed = await load_story_events(db_session, story.id)
    a1, a2 = evaluate_origin_anchor_only(root_event, confirmed)
    assert a1.eligible == a2.eligible
    assert a1.reasons == a2.reasons
    assert a1.metrics == a2.metrics


# ---------------------------------------------------------------------------
# Write-safety audit - AST-based, over actual CODE nodes only (module/function docstrings are
# plain `ast.Expr(ast.Constant(str))` nodes, structurally distinct from a real `Call` node, so a
# docstring merely mentioning "session.add(" in prose - as this module's own header does, to
# explain what it does NOT do - can never masquerade as an executed call here. Never trusts the
# module's own docstring claims by string-matching alone.
# ---------------------------------------------------------------------------

_SCRIPT_PATH = Path("scripts/_recap_r2_8_origin_membership_semantics_shadow.py")

_FORBIDDEN_ATTR_CALLS = {"add", "add_all", "delete", "merge", "commit", "flush"}
_FORBIDDEN_SQL_KEYWORDS = ("update ", "delete from", "insert into")


def _parse_script() -> ast.Module:
    return ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(_SCRIPT_PATH))


def test_r2_8_shadow_script_contains_no_write_calls() -> None:
    tree = _parse_script()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _FORBIDDEN_ATTR_CALLS:
                offenders.append(f"{node.func.attr}() at line {node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            for keyword in _FORBIDDEN_SQL_KEYWORDS:
                if keyword in lowered:
                    offenders.append(f"SQL string literal containing {keyword!r} at line {node.lineno}")
    assert offenders == [], f"write-capable code found in R2.8 shadow script: {offenders}"

    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "await trans.rollback()" in source
    assert "SET TRANSACTION READ ONLY" in source


def test_r2_8_shadow_script_never_imports_llm_or_telegram() -> None:
    tree = _parse_script()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    lowered = {name.lower() for name in imported_names}
    for forbidden in ("llm_gateway", "telegram", "anthropic", "openai", "deepseek"):
        assert not any(forbidden in name for name in lowered), (
            f"unexpected {forbidden!r} import in R2.8 shadow script: {imported_names}"
        )


def test_r2_8_shadow_script_does_not_import_frozen_services_for_mutation() -> None:
    """Confirms the module docstring's own "READ-ONLY references" claim for the five frozen
    services - imports only pure/read functions, never anything that mutates. AST-based (checks
    actual `ImportFrom` names), so this cannot be fooled by the module's own prose explaining why
    it avoids them."""
    tree = _parse_script()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
    assert "_apply_story_memory" not in imported_names
    assert "match_story" not in imported_names
