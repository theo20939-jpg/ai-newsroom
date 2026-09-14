"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §23: the required test matrix. `Bot` is a plain
`unittest.mock.AsyncMock` throughout - mirrors `tests/test_telegram_editorial_routing.py`'s own
established convention exactly, zero real Telegram API contact of any kind. All Creative Director
regeneration is a fake `CreativeRegenerator` - zero real LLM/network calls, mirroring this
codebase's own "no real network in tests" convention."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.instagram_editorial_review import build_review_keyboard, parse_callback_data
from core.config import settings
from database.models.instagram_editorial_delivery import InstagramEditorialDelivery, InstagramEditorialDeliveryState
from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative, InstagramSingleCreative
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeDirectorInput, CreativeGenerationOutcome
from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService, compute_package_identity
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_editorial_package_snapshot import build_package_snapshot, restore_media_identity, restore_package, restore_regeneration_inputs
from services.instagram_editorial_regeneration import RegenerationError, regenerate_full, regenerate_text_only, regenerate_visual_only
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel, render_instagram_feed_image, render_instagram_reel_cover
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import deliver_instagram_package, instagram_topic_configured
from services.instagram_telegram_package_presenter import present_carousel, present_reel, present_single

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
    audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


@pytest.fixture(autouse=True)
def _topic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -1009999)
    monkeypatch.setattr(settings, "instagram_topic_id", 77)


def _director_input() -> CreativeDirectorInput:
    return CreativeDirectorInput(objective="reach", format="single", opportunity_summary="A story", allowed_evidence=["fact-1"])


def _single_package(*, opp_id: str = "opp-1"):
    opp = ContentOpportunity(id=opp_id, source_type=OpportunitySourceType.NEWS, story_id="s1", product_mention_allowed=True)
    single = InstagramSingleCreative(creative_angle="a", visual_concept="v", on_image_copy="Headline", caption_direction="Original caption", cta="Learn more")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )
    render = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [render])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    return opp, single, pkg, render, gate


def _carousel_package(*, opp_id: str = "opp-2"):
    opp = ContentOpportunity(id=opp_id, source_type=OpportunitySourceType.NEWS, story_id="s2", product_mention_allowed=True)
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v1"),
        InstagramCarouselSlideCreative(role="body", slide_copy="Body", visual_direction="v2"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Swipe")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    renders = render_instagram_carousel(pkg)
    art = validate_instagram_art(pkg, renders)
    gate = evaluate_instagram_editorial_gate(pkg, art)
    return opp, carousel, pkg, renders, gate


def _snapshot_for(pkg, opp, format_decision, creative) -> dict:
    return build_package_snapshot(
        package=pkg, opportunity=opp, format_decision=format_decision, shadow_plan=_SP,
        director_input=_director_input(), previous_creative=creative, source_url="https://example.com/story",
    )


async def _seed_delivery(session: AsyncSession, *, package_identity: str, pkg, opp, format_decision, creative,
                          state: InstagramEditorialDeliveryState = InstagramEditorialDeliveryState.DELIVERED) -> InstagramEditorialDelivery:
    snapshot = _snapshot_for(pkg, opp, format_decision, creative)
    delivery = InstagramEditorialDelivery(
        package_identity=package_identity, version=1, source_story_id=opp.story_id,
        content_format=pkg.content_format.value, state=state, package_snapshot=snapshot,
        telegram_chat_id=-1009999, telegram_topic_id=77, media_message_ids=[501], control_message_id=502,
    )
    session.add(delivery)
    await session.flush()
    return delivery


# ---------------------------------------------------------------------------
# A/B/C/F/G - presentation + keyboard
# ---------------------------------------------------------------------------


def test_a_single_post_presentation_has_one_media_item_and_full_caption() -> None:
    _, _, pkg, render, _ = _single_package()
    presentation = present_single(pkg, render, version=1)
    assert presentation.kind == "single"
    assert len(presentation.media) == 1
    assert presentation.media[0] == render.image_bytes
    assert "Original caption" in presentation.control_text  # F: caption preserved, never dropped


def test_b_and_c_carousel_presentation_preserves_exact_slide_order() -> None:
    _, _, pkg, renders, _ = _carousel_package()
    presentation = present_carousel(pkg, renders, version=1)
    assert presentation.kind == "carousel"
    assert presentation.media == [r.image_bytes for r in renders]  # CAROUSEL_ORDER_PRESERVED=true


def test_e_reel_without_video_is_never_labeled_a_finished_video() -> None:
    opp = ContentOpportunity(id="opp-reel", source_type=OpportunitySourceType.NEWS, story_id="s3", product_mention_allowed=True)
    from schemas.instagram_creative import InstagramReelCreative

    reel = InstagramReelCreative(
        objective="reach", hook="Hook!", target_duration_seconds=30, scene_sequence=["scene1", "scene2"],
        pacing="fast", caption_direction="Reel caption",
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.REEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(reel=reel),
    )
    cover = render_instagram_reel_cover(pkg)
    presentation = present_reel(pkg, cover, version=1)
    assert presentation.kind == "reel_concept"
    assert "КОНЦЕПТ" in presentation.control_text
    assert "видео ещё не создано" in presentation.control_text
    assert "Hook!" in presentation.control_text  # real storyboard content, not a debug dump


def test_g_source_button_present_only_when_source_exists() -> None:
    delivery_id = uuid.uuid4()
    with_source = build_review_keyboard(delivery_id, 1, source_url="https://example.com/x")
    without_source = build_review_keyboard(delivery_id, 1, source_url=None)
    assert len(with_source.inline_keyboard) == 3
    assert len(without_source.inline_keyboard) == 2
    assert without_source.inline_keyboard[0][0].callback_data.startswith("igrev:approve:")


def test_no_publish_button_exists_anywhere_in_the_callback_codec() -> None:
    """§9 hard requirement - a structural guarantee, not a convention."""
    assert parse_callback_data("igrev:publish:" + str(uuid.uuid4()) + ":1") is None
    keyboard = build_review_keyboard(uuid.uuid4(), 1)
    all_texts = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert not any("публик" in t.lower() or "🚀" in t for t in all_texts)


# ---------------------------------------------------------------------------
# §4 topic discovery / fail-closed
# ---------------------------------------------------------------------------


def test_topic_not_configured_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_topic_id", None)
    assert instagram_topic_configured() is False


def test_topic_configured_when_both_ids_present() -> None:
    assert instagram_topic_configured() is True


@pytest.mark.asyncio
async def test_r_and_s_missing_topic_never_falls_back_to_chat_root(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 hard invariant INSTAGRAM_PACKAGE_WRONG_TOPIC=false - a missing topic id must be a safe
    no-op, never a send to the chat root. Also covers R/S: media-hosting/credentials are never even
    consulted by this code path (it doesn't import either module), so their absence cannot block
    it - only the topic id does."""
    monkeypatch.setattr(settings, "instagram_topic_id", None)
    bot = AsyncMock()
    opp, single, pkg, render, gate = _single_package(opp_id="opp-no-topic")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    snapshot = _snapshot_for(pkg, opp, FormatDecision(recommended_format=ContentFormat.SINGLE), single)
    from services.instagram_telegram_package_presenter import present_single as _ps

    presentation = _ps(pkg, render, version=1)
    outcome = await deliver_instagram_package(
        bot, db_session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opp.story_id, content_format="single", package_snapshot=snapshot,
    )
    assert outcome.sent is False
    assert outcome.reason == "topic_not_configured"
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_a_single_delivered_to_the_configured_instagram_topic(db_session: AsyncSession) -> None:
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 601
    bot.send_message.return_value.message_id = 602
    opp, single, pkg, render, gate = _single_package(opp_id="opp-deliver-single")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    snapshot = _snapshot_for(pkg, opp, FormatDecision(recommended_format=ContentFormat.SINGLE), single)
    presentation = present_single(pkg, render, version=1)

    outcome = await deliver_instagram_package(
        bot, db_session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opp.story_id, content_format="single", package_snapshot=snapshot,
    )
    assert outcome.sent is True
    bot.send_photo.assert_called_once()
    assert bot.send_photo.call_args.kwargs["message_thread_id"] == 77
    assert bot.send_photo.call_args.args[0] == -1009999


@pytest.mark.asyncio
async def test_q_duplicate_worker_cycle_does_not_resend(db_session: AsyncSession) -> None:
    """§21 DUPLICATE_TELEGRAM_PACKAGE_SENDS=0."""
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 701
    bot.send_message.return_value.message_id = 702
    opp, single, pkg, render, gate = _single_package(opp_id="opp-dup")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    snapshot = _snapshot_for(pkg, opp, FormatDecision(recommended_format=ContentFormat.SINGLE), single)
    presentation = present_single(pkg, render, version=1)

    first = await deliver_instagram_package(
        bot, db_session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opp.story_id, content_format="single", package_snapshot=snapshot,
    )
    assert first.sent is True
    second = await deliver_instagram_package(
        bot, db_session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opp.story_id, content_format="single", package_snapshot=snapshot,
    )
    assert second.sent is False
    assert second.reason == "duplicate_skipped"
    assert bot.send_photo.call_count == 1  # never resent


@pytest.mark.asyncio
async def test_o_and_p_hold_and_block_never_delivered_as_ready(db_session: AsyncSession) -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 801
    opp, single, pkg, render, _ = _single_package(opp_id="opp-hold")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    snapshot = _snapshot_for(pkg, opp, FormatDecision(recommended_format=ContentFormat.SINGLE), single)
    presentation = present_single(pkg, render, version=1)

    for decision in (InstagramGateDecision.HOLD, InstagramGateDecision.BLOCK):
        bot.reset_mock()
        outcome = await deliver_instagram_package(
            bot, db_session, presentation=presentation, gate_decision=decision,
            package_identity=identity + decision.value, source_story_id=opp.story_id, content_format="single",
            package_snapshot=snapshot, hold_or_block_reason="test reason",
        )
        assert outcome.sent is False
        bot.send_photo.assert_not_called()  # never delivered as if ready
        bot.send_message.assert_called_once()  # only the concise notice


# ---------------------------------------------------------------------------
# §T/U - hard publication-off invariants
# ---------------------------------------------------------------------------


def test_t_publication_flags_are_false() -> None:
    assert settings.instagram_publication_enabled is False
    assert settings.instagram_autonomous_publication_enabled is False


def test_u_no_instagram_write_call_anywhere_in_the_delivery_modules() -> None:
    """Structural guarantee, mirroring `tests/test_telegraph_article_review_handler.py`'s own
    "source-scan" convention - checks actual `import`/`import from` STATEMENTS via `ast`, never a
    raw substring match (which would also flag this module's own explanatory docstrings)."""
    import ast
    import inspect

    import services.instagram_telegram_delivery as delivery_module
    import bot.handlers.instagram_editorial_review as handler_module

    forbidden_modules = ("services.instagram_publish_adapter", "services.instagram_account_reader")
    for module in (delivery_module, handler_module):
        tree = ast.parse(inspect.getsource(module))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in forbidden_modules:
            assert forbidden not in imported, f"{module.__name__} unexpectedly imports {forbidden!r}"


# ---------------------------------------------------------------------------
# H/I - approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_and_i_approve_only_changes_state_never_publishes(db_session: AsyncSession) -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-approve")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    delivery = await _seed_delivery(db_session, package_identity=identity, pkg=pkg, opp=opp,
                                     format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), creative=single)
    service = InstagramEditorialDeliveryService()
    updated = await service.set_approved(db_session, delivery, telegram_user_id=555)
    assert updated.state == InstagramEditorialDeliveryState.APPROVED
    assert updated.decided_by_telegram_user_id == 555
    # Double-approval is idempotent/immutable-once-final:
    again = await service.set_approved(db_session, delivery, telegram_user_id=999)
    assert again.state == InstagramEditorialDeliveryState.APPROVED
    assert again.decided_by_telegram_user_id == 555  # unchanged - the second call never mutated it


@pytest.mark.asyncio
async def test_double_approval_has_zero_side_effects(db_session: AsyncSession) -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-double-approve")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    delivery = await _seed_delivery(db_session, package_identity=identity, pkg=pkg, opp=opp,
                                     format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), creative=single)
    service = InstagramEditorialDeliveryService()
    await service.set_approved(db_session, delivery, telegram_user_id=1)
    real_flush = db_session.flush
    flush_calls = {"n": 0}

    async def _counting_flush(*args, **kwargs):
        flush_calls["n"] += 1
        return await real_flush(*args, **kwargs)

    db_session.flush = _counting_flush
    try:
        await service.set_approved(db_session, delivery, telegram_user_id=2)
    finally:
        db_session.flush = real_flush
    assert flush_calls["n"] == 0  # already-final row - no second write attempted at all
    assert delivery.decided_by_telegram_user_id == 1  # unchanged


# ---------------------------------------------------------------------------
# N - stale callback safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n_stale_version_callback_is_not_actionable(db_session: AsyncSession) -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-stale")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    delivery = await _seed_delivery(db_session, package_identity=identity, pkg=pkg, opp=opp,
                                     format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), creative=single)
    service = InstagramEditorialDeliveryService()
    assert service.is_actionable(delivery, expected_version=delivery.version) is True
    assert service.is_actionable(delivery, expected_version=delivery.version + 1) is False  # a stale button from an old message


@pytest.mark.asyncio
async def test_n_already_approved_delivery_is_not_actionable(db_session: AsyncSession) -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-stale-approved")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    delivery = await _seed_delivery(db_session, package_identity=identity, pkg=pkg, opp=opp,
                                     format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), creative=single)
    service = InstagramEditorialDeliveryService()
    await service.set_approved(db_session, delivery, telegram_user_id=1)
    assert service.is_actionable(delivery, expected_version=delivery.version) is False


# ---------------------------------------------------------------------------
# K - double regeneration guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_double_regeneration_tap_only_starts_once(db_session: AsyncSession) -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-double-regen")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    delivery = await _seed_delivery(db_session, package_identity=identity, pkg=pkg, opp=opp,
                                     format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), creative=single)
    service = InstagramEditorialDeliveryService()
    first = await service.begin_regeneration(db_session, delivery, kind=InstagramEditorialDeliveryState.REGENERATING_FULL, expected_version=1)
    assert first is not None
    second = await service.begin_regeneration(db_session, delivery, kind=InstagramEditorialDeliveryState.REGENERATING_FULL, expected_version=1)
    assert second is None  # the second tap is a safe no-op, never a second job


# ---------------------------------------------------------------------------
# J/L/M - real regeneration (full / text-only / visual-only)
# ---------------------------------------------------------------------------


async def _fake_regenerator_factory(new_single: InstagramSingleCreative):
    async def _regen(director_input, fmt):
        return CreativeGenerationOutcome(single=new_single)
    return _regen


@pytest.mark.asyncio
async def test_j_full_regeneration_produces_a_new_version_and_supersedes_the_old(db_session: AsyncSession) -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-full-regen")
    identity = compute_package_identity(source_key=opp.id, content_format="single")
    delivery = await _seed_delivery(db_session, package_identity=identity, pkg=pkg, opp=opp,
                                     format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), creative=single)

    new_creative = InstagramSingleCreative(creative_angle="new angle", visual_concept="new visual", on_image_copy="New headline", caption_direction="New caption", cta="Shop now")
    regenerator = await _fake_regenerator_factory(new_creative)
    result = await regenerate_full(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        director_input=_director_input(), regenerator=regenerator,
    )
    assert result.package.caption != pkg.caption
    assert result.package.on_image_copy == "New headline"

    service = InstagramEditorialDeliveryService()
    new_version = await service.create_new_version(
        db_session, previous=delivery, package_snapshot=_snapshot_for(result.package, opp, FormatDecision(recommended_format=ContentFormat.SINGLE), new_creative),
    )
    assert new_version.version == 2
    refreshed_old = await db_session.get(InstagramEditorialDelivery, delivery.id)
    assert refreshed_old.state == InstagramEditorialDeliveryState.SUPERSEDED

    rows = (await db_session.execute(
        select(InstagramEditorialDelivery).where(InstagramEditorialDelivery.package_identity == identity)
    )).scalars().all()
    current = [r for r in rows if r.state != InstagramEditorialDeliveryState.SUPERSEDED]
    assert len(current) == 1  # the partial unique index invariant holds


@pytest.mark.asyncio
async def test_l_text_only_regeneration_preserves_visual_fields() -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-text-regen")
    new_creative = InstagramSingleCreative(creative_angle="ignored", visual_concept="ignored", on_image_copy="IGNORED HEADLINE", caption_direction="Brand new caption text", cta="New CTA")
    regenerator = await _fake_regenerator_factory(new_creative)

    result = await regenerate_text_only(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        director_input=_director_input(), previous_creative=single, regenerator=regenerator,
    )
    assert result.package.on_image_copy == pkg.on_image_copy  # visual UNCHANGED
    assert "Brand new caption text" in result.package.caption  # caption changed
    assert result.creative.on_image_copy == single.on_image_copy


@pytest.mark.asyncio
async def test_m_visual_only_regeneration_preserves_caption() -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-visual-regen")
    new_creative = InstagramSingleCreative(creative_angle="new angle", visual_concept="new visual", on_image_copy="Brand new headline", caption_direction="IGNORED CAPTION", cta="IGNORED")
    regenerator = await _fake_regenerator_factory(new_creative)

    result = await regenerate_visual_only(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        director_input=_director_input(), previous_creative=single, regenerator=regenerator,
    )
    assert result.package.on_image_copy == "Brand new headline"  # visual changed
    assert result.package.caption == pkg.caption  # caption UNCHANGED
    assert result.renders  # a fresh render did happen


@pytest.mark.asyncio
async def test_carousel_partial_regeneration_bails_out_safely_on_slide_count_mismatch() -> None:
    opp, carousel, pkg, renders, gate = _carousel_package(opp_id="opp-carousel-regen")
    from schemas.instagram_creative import InstagramCarouselSlideCreative as Slide

    mismatched = InstagramCarouselCreative(
        objective="saves",
        slides=[Slide(role="hook", slide_copy="H", visual_direction="v"), Slide(role="body", slide_copy="B", visual_direction="v2"), Slide(role="cta", slide_copy="C", visual_direction="v3")],
        final_cta="Go",
    )
    async def _regen(director_input, fmt):
        return CreativeGenerationOutcome(carousel=mismatched)

    with pytest.raises(RegenerationError):
        await regenerate_text_only(
            opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
            director_input=_director_input(), previous_creative=carousel, regenerator=_regen,
        )


# ---------------------------------------------------------------------------
# package_snapshot round-trip
# ---------------------------------------------------------------------------


def test_package_snapshot_round_trips_all_regeneration_inputs() -> None:
    opp, single, pkg, render, gate = _single_package(opp_id="opp-roundtrip")
    snapshot = _snapshot_for(pkg, opp, FormatDecision(recommended_format=ContentFormat.SINGLE), single)

    inputs = restore_regeneration_inputs(snapshot)
    assert inputs.opportunity == opp
    assert inputs.format_decision.recommended_format is ContentFormat.SINGLE
    assert inputs.previous_creative == single

    restored_pkg = restore_package(snapshot)
    assert restored_pkg.caption == pkg.caption
    assert restored_pkg.content_format is ContentFormat.SINGLE

    with_identity = restore_media_identity(restored_pkg, inputs)
    assert with_identity.media_candidate_id == pkg.media_candidate_id
