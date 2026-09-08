"""STORY-CONTINUITY-P0 - frozen replay of the confirmed live Meta 'Muse' incident (tests/
fixtures/meta_muse_incident.json) + the Section 19 adversarial matrix, end-to-end against real
Postgres (db_session, SAVEPOINT-rolled-back - read-only-effective).

The expected outcomes are reconstructed from the ACTUAL facts, not tuned to the fixture:
  - first true Muse-agent development        -> NEW_STORY
  - same development, another publisher       -> same Story (never NEW_STORY, never the "will"
                                                garbage cluster, never the Voice-Transcribe story)
  - same development + material new fact      -> MATERIAL_UPDATE_CANDIDATE
  - a DIFFERENT Muse product (Spark 1.3)      -> NEW_STORY (not merged with the agent/Transcribe)
  - a generic Meta/AI roundup                 -> no false merge
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from services.story_continuity import (
    CONTINUITY_AMBIGUOUS,
    CONTINUITY_DUPLICATE_NO_DELTA,
    CONTINUITY_MATERIAL_UPDATE_CANDIDATE,
    CONTINUITY_NEW_STORY,
    classify_continuity,
)
from services.story_delta_engine import compute_story_delta, gate_delta_by_identity
from services.story_memory import extract_story_signature, match_story

_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "meta_muse_incident.json").read_text("utf-8"))
_SAME_STORY = {CONTINUITY_DUPLICATE_NO_DELTA, CONTINUITY_MATERIAL_UPDATE_CANDIDATE}


async def _seed(session: AsyncSession, title: str, *, category: EventCategory,
                entities: list[str] | None = None, topic_bucket: str | None = None) -> Story:
    src = NewsSource(name=f"p0-replay-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(src)
    await session.flush()
    ev = NewsEvent(source_id=src.id, title=title, category=category, hash=f"p0-replay-{uuid4()}")
    session.add(ev)
    await session.flush()
    sig = extract_story_signature(title, category)
    story = Story(
        id=uuid4(), title=title, category=category,
        entities=entities if entities is not None else sig.entities,
        keywords=sig.keywords,
        topic_bucket=topic_bucket or sig.topic_bucket,
        first_event_id=ev.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    return story


def _creates_own_story(mr) -> bool:
    """Mirror services/triage_orchestrator.py::_apply_story_memory's own dispatch exactly."""
    from services.story_memory import _RELATED_STORY_ENTITY_FLOOR

    return (
        mr.matched_story_id is None
        or mr.outcome in ("new_story", "related_story")
        or (mr.outcome == "uncertain_match" and mr.entity_overlap < _RELATED_STORY_ENTITY_FLOOR)
        or (mr.outcome == "uncertain_match" and mr.company_only_match and mr.distinctive_overlap == 0.0)
    )


async def _continuity(session: AsyncSession, title: str, category: EventCategory):
    sig, mr = await match_story(session, title=title, category=category)
    creates_own = _creates_own_story(mr)
    delta = None
    if not creates_own and mr.matched_story_id is not None:
        try:
            delta = await compute_story_delta(session, new_title=title, story_id=mr.matched_story_id)  # type: ignore[arg-type]
            delta = gate_delta_by_identity(delta, has_distinctive_shared_entity=mr.has_distinctive_shared_entity)
        except Exception:
            delta = None
    return mr, classify_continuity(match_result=mr, delta_result=delta, creates_own_story=creates_own)


async def _seed_incident_context(session: AsyncSession) -> dict[str, Story]:
    """The two real pre-existing Stories the burst false-merged into, plus a realistic filler
    pool so document-frequency behaves like production."""
    ctx: dict[str, Story] = {}
    for s in _FIXTURE["pre_existing_stories"]:
        ctx[s["id"]] = await _seed(
            session, s["title"], category=EventCategory[s["category"]],
            entities=s["entities"], topic_bucket=s["topic_bucket"],
        )
    # filler pool - unrelated recent stories so "muse"/"meta" have a realistic df
    for i in range(30):
        await _seed(session, f"Unrelated tech headline number {i} about a different subject entirely",
                    category=EventCategory.AI)
    return ctx


# ===========================================================================
# Meta incident replay
# ===========================================================================

@pytest.mark.asyncio
async def test_meta_replay_agent_burst_does_not_fragment_or_false_merge(db_session: AsyncSession) -> None:
    ctx = await _seed_incident_context(db_session)
    will_story_id = ctx["will-garbage-cluster"].id
    transcribe_story_id = ctx["voice-transcribe-story"].id

    burst = _FIXTURE["muse_agent_sept8"]
    results: list[tuple[int, str, str]] = []  # (n, continuity_outcome, match_type)
    story_ids: set = set()
    first_story_id = None

    for item in burst:
        mr, cont = await _continuity(db_session, item["title"], EventCategory[item["category"]])
        results.append((item["n"], cont.outcome, mr.outcome))

        # NEVER *confidently merge* into the "will" garbage cluster or the Voice-Transcribe story
        # (a provisional AMBIGUOUS pointer is tolerated; a DUPLICATE/UPDATE merge is not).
        for bad_id in (will_story_id, transcribe_story_id):
            if mr.matched_story_id == bad_id:
                assert cont.outcome not in _SAME_STORY, (
                    f"item {item['n']} confidently merged into a wrong Story "
                    f"({cont.outcome}, {cont.reason_codes})"
                )

        if cont.outcome == CONTINUITY_NEW_STORY:
            # a story-creating event: register a Story so later items can attach to it
            st = await _seed(db_session, item["title"], category=EventCategory[item["category"]])
            story_ids.add(st.id)
            if first_story_id is None:
                first_story_id = st.id
        elif mr.matched_story_id is not None:
            story_ids.add(mr.matched_story_id)

    outcomes = [o for _, o, _ in results]
    # The burst must NOT shatter into a new Story per item (pre-P0: 7 stories for 13 items).
    new_story_count = outcomes.count(CONTINUITY_NEW_STORY)
    assert new_story_count <= 4, f"burst still fragmenting: {results}"
    # At least some paraphrases must be recognised as the same story (not all NEW_STORY/AMBIGUOUS).
    assert any(o in _SAME_STORY for o in outcomes), f"no paraphrase recognised as same-story: {results}"


@pytest.mark.asyncio
async def test_meta_replay_first_agent_item_is_new_story(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    anchor = _FIXTURE["muse_agent_sept8"][2]  # "Meta launches Muse, a personal AI agent that runs on a dedicated VM..."
    _mr, cont = await _continuity(db_session, anchor["title"], EventCategory[anchor["category"]])
    assert cont.outcome == CONTINUITY_NEW_STORY


@pytest.mark.asyncio
async def test_meta_replay_paraphrase_of_same_launch_is_same_story(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    anchor = _FIXTURE["muse_agent_sept8"][2]
    await _seed(db_session, anchor["title"], category=EventCategory[anchor["category"]])
    para = _FIXTURE["muse_agent_sept8"][3]  # "Meta launches personal AI agent, Muse, emphasizes safety and privacy - WRAL"
    _mr, cont = await _continuity(db_session, para["title"], EventCategory[para["category"]])
    assert cont.outcome in _SAME_STORY, cont.reason_codes


@pytest.mark.asyncio
async def test_meta_replay_material_capability_item_is_update_candidate(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    anchor = _FIXTURE["muse_agent_sept8"][2]
    await _seed(db_session, anchor["title"], category=EventCategory[anchor["category"]])
    # item 5 adds real capability substance ("connect their apps ... send emails ... purchases via agents")
    mat = _FIXTURE["muse_agent_sept8"][4]
    _mr, cont = await _continuity(db_session, mat["title"], EventCategory[mat["category"]])
    assert cont.outcome in {CONTINUITY_MATERIAL_UPDATE_CANDIDATE, CONTINUITY_AMBIGUOUS}
    assert cont.suppression_eligible is False


@pytest.mark.asyncio
async def test_meta_replay_muse_spark_is_a_separate_story_from_agent(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    anchor = _FIXTURE["muse_agent_sept8"][2]
    agent_story = await _seed(db_session, anchor["title"], category=EventCategory[anchor["category"]])
    spark = _FIXTURE["muse_spark_sept2_3"][0]
    _mr, cont = await _continuity(db_session, spark["title"], EventCategory[spark["category"]])
    # Muse Spark 1.3 is a DIFFERENT Meta product from the Muse personal agent - never a
    # confident merge into the agent Story (a provisional RELATED_STORY pointer is tolerated).
    assert cont.outcome not in _SAME_STORY, cont.reason_codes
    del agent_story


@pytest.mark.asyncio
async def test_meta_replay_roundup_does_not_false_merge(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    anchor = _FIXTURE["muse_agent_sept8"][2]
    agent_story = await _seed(db_session, anchor["title"], category=EventCategory[anchor["category"]])
    roundup = _FIXTURE["roundups_and_noise"][0]
    mr, cont = await _continuity(db_session, roundup["title"], EventCategory[roundup["category"]])
    assert cont.outcome != CONTINUITY_DUPLICATE_NO_DELTA
    assert mr.matched_story_id != agent_story.id


@pytest.mark.asyncio
async def test_meta_replay_unrelated_muse_ssd_does_not_merge(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    anchor = _FIXTURE["muse_agent_sept8"][2]
    agent_story = await _seed(db_session, anchor["title"], category=EventCategory[anchor["category"]])
    ssd = _FIXTURE["roundups_and_noise"][1]  # "Lexar ... Lexar Muse drive"
    mr, _cont = await _continuity(db_session, ssd["title"], EventCategory[ssd["category"]])
    assert mr.matched_story_id != agent_story.id


# ===========================================================================
# Section 19 adversarial matrix
# ===========================================================================

@pytest.mark.asyncio
async def test_adv_A_same_product_paraphrase_different_publisher_same_story(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "Acme launches Zephyr Copilot, a coding assistant for teams", category=EventCategory.AI)
    _mr, cont = await _continuity(db_session, "Acme debuts Zephyr Copilot to help developers write code", EventCategory.SOFTWARE)
    assert cont.outcome in _SAME_STORY or cont.outcome == CONTINUITY_AMBIGUOUS
    assert cont.outcome != CONTINUITY_NEW_STORY


@pytest.mark.asyncio
async def test_adv_B_same_company_same_domain_different_product_new_story(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "OpenAI launches Zephyr Copilot coding assistant", category=EventCategory.AI)
    _mr, cont = await _continuity(db_session, "OpenAI launches Nimbus Vision, an image generation model", EventCategory.AI)
    assert cont.outcome == CONTINUITY_NEW_STORY, cont.reason_codes


@pytest.mark.asyncio
async def test_adv_C_same_product_material_new_capability_update_candidate(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "OpenAI launches Zephyr Copilot, a coding assistant for developers", category=EventCategory.AI)
    _mr, cont = await _continuity(
        db_session,
        "OpenAI Zephyr Copilot now supports forty programming languages and offline on-device use",
        EventCategory.AI,
    )
    assert cont.outcome in {CONTINUITY_MATERIAL_UPDATE_CANDIDATE, CONTINUITY_AMBIGUOUS}, cont.reason_codes
    assert cont.suppression_eligible is False


@pytest.mark.asyncio
async def test_adv_D_generic_overlap_only_never_confident_same_story(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "Acme unveils new AI model for the enterprise", category=EventCategory.AI)
    _mr, cont = await _continuity(db_session, "Globex announces its own AI model and agent platform", EventCategory.AI)
    assert cont.outcome in {CONTINUITY_NEW_STORY, CONTINUITY_AMBIGUOUS}
    assert cont.outcome not in _SAME_STORY


@pytest.mark.asyncio
async def test_adv_E_russian_legal_boilerplate_no_false_merge(db_session: AsyncSession) -> None:
    ctx = await _seed_incident_context(db_session)
    # An unrelated Russian-language Meta story carrying the same mandatory legal prefix
    unrelated = await _seed(
        db_session,
        "Запрещённая в России Meta выплатит штраф за нарушение закона о персональных данных",
        category=EventCategory.AI,
    )
    _mr, cont = await _continuity(
        db_session, "Запрещённая в России Meta представила ИИ-агента Muse для повседневных задач", EventCategory.AI,
    )
    # the shared legal disclaimer + "Meta" must not confidently merge two unrelated RU items
    assert cont.outcome not in _SAME_STORY, cont.reason_codes
    if _mr.matched_story_id is not None:
        assert cont.outcome == CONTINUITY_AMBIGUOUS or cont.outcome == CONTINUITY_NEW_STORY
    assert _mr.matched_story_id != ctx["will-garbage-cluster"].id
    del unrelated


@pytest.mark.asyncio
async def test_adv_F_publisher_suffix_prefix_noise_no_identity_distortion(db_session: AsyncSession) -> None:
    from services.story_memory import extract_story_signature as ess

    a = ess("Investigation: Acme explored deep job cuts to become AI-native", EventCategory.TECH)
    b = ess("Acme explored deep job cuts to become AI-native", EventCategory.TECH)
    assert set(a.entities) == set(b.entities)  # wire-format label "Investigation:" doesn't add identity


def test_adv_G_url_tracking_param_variants_canonicalize_equal() -> None:
    from services.text_normalization import canonicalize_url

    base = "https://example.com/2026/09/08/meta-muse-agent"
    assert canonicalize_url(base + "?utm_source=twitter&utm_medium=social") == canonicalize_url(base)
    assert canonicalize_url(base + "/?fbclid=abc123") == canonicalize_url(base)
    assert canonicalize_url("https://example.com/a?id=42&utm_campaign=x") == "https://example.com/a?id=42"


def test_adv_H_syndicated_mirror_same_canonical_url_is_duplicate_key() -> None:
    from services.text_normalization import canonicalize_url

    mirror_a = "https://news.example.com/story/meta-muse?ref=partner&at_medium=rss"
    mirror_b = "https://news.example.com/story/meta-muse/"
    assert canonicalize_url(mirror_a) == canonicalize_url(mirror_b)


@pytest.mark.asyncio
async def test_adv_I_same_product_incompatible_version_separate_story(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "Acme releases Zephyr Model 2.1 with faster inference", category=EventCategory.AI)
    _mr, cont = await _continuity(db_session, "Acme releases Zephyr Model 3.0 with faster inference", EventCategory.AI)
    assert cont.outcome == CONTINUITY_NEW_STORY, cont.reason_codes


@pytest.mark.asyncio
async def test_adv_J_generic_token_will_cannot_anchor_a_story(db_session: AsyncSession) -> None:
    ctx = await _seed_incident_context(db_session)
    _mr, _cont = await _continuity(
        db_session, "Will your next laptop have an AI chip built in?", EventCategory.GADGETS,
    )
    assert _mr.matched_story_id != ctx["will-garbage-cluster"].id


@pytest.mark.asyncio
async def test_adv_K_minor_delta_is_safe_not_suppressed(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "Acme launches Zephyr Copilot coding assistant for developers", category=EventCategory.AI)
    _mr, cont = await _continuity(
        db_session, "Acme's Zephyr Copilot coding assistant for developers, now with a redesigned sidebar", EventCategory.AI,
    )
    # whatever the outcome, a small new fact is never silently dropped
    assert cont.suppression_eligible is False


@pytest.mark.asyncio
async def test_adv_L_missing_entities_fails_safe_not_aggressive_merge(db_session: AsyncSession) -> None:
    await _seed_incident_context(db_session)
    await _seed(db_session, "the quarterly numbers were released today after markets closed", category=EventCategory.AI)
    _mr, cont = await _continuity(
        db_session, "a different set of quarterly numbers came out this afternoon", EventCategory.AI,
    )
    assert cont.outcome != CONTINUITY_DUPLICATE_NO_DELTA


# ===========================================================================
# Section 13 safety: P0 must NOT enable production suppression
# ===========================================================================

@pytest.mark.asyncio
async def test_p0_does_not_suppress_delivery_under_current_orchestration(db_session: AsyncSession) -> None:
    """check_duplicate_story_delivery() must still unconditionally return blocked=False - P0
    persists suppression_eligible/would_suppress as DIAGNOSTICS only."""
    from services.story_duplicate_guard import check_duplicate_story_delivery

    src = NewsSource(name=f"p0-safety-{uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(src)
    await db_session.flush()
    ev = NewsEvent(source_id=src.id, title="Meta launches Muse personal AI agent",
                   category=EventCategory.AI, hash=f"p0-safety-{uuid4()}")
    db_session.add(ev)
    await db_session.flush()

    check = await check_duplicate_story_delivery(db_session, ev.id)
    assert check.blocked is False
