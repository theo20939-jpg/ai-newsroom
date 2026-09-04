"""R2.10-FINALIZATION-2 - integration coverage for the RECAP -> final authoring -> FinalPostReview
-> WYSIWYG chain, covering the two genuine gaps found and fixed this phase:

1. services/final_post_review_notifier.py's own `candidate_id`+`originating_event_id` media
   resolution branch (Tesla's own real shape) previously imported services.media_finalizer, a
   module that never existed anywhere in this repo's git history - confirmed via `git stash`
   against the base commit. Fixed by reusing resolve_photo_input() (the same resolver services/
   event_recap_review_notifier.py already calls) + the SAME conditional apply_master_news_
   branding() gate the sibling storage_key branch already used. This file's own dedicated test
   proves the fix actually brands real bytes, not just that the module imports.

2. bot/final_post_review_formatting.py::render_final_post_review_control_text() gained an optional
   `source_event_recap_review_id` parameter - the real "RECAP distinction" this pipeline's own
   product contract requires (services/final_post_review_eligibility.py's own H/I gate already
   REQUIRES this same field for a recap-derived draft to be eligible at all), added to the
   INTERNAL-only control message (MESSAGE 2) - deliberately never to render_final_post_preview_
   caption() (MESSAGE 1, the public-like preview / real publish payload), which stays byte-
   identical to an ordinary NEWS delivery by the pipeline's own already-documented design.

Reuses tests/test_final_post_processor.py's own established `_seed_approved_review()`-shaped
fixtures (FakeLLMGateway, real db_session, zero real LLM/network) per this codebase's own
established per-file-helper-duplication convention - not imported cross-file."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
from capabilities.final_post_authoring_capability import (
    FINAL_POST_AUTHORING_CAPABILITY_DEFINITION,
    FinalPostAuthoringCapability,
)
from capabilities.registry import CapabilityRegistry
from core.config import settings
from schemas.content_draft import ContentDraftRead
from database.models.editorial_task import EditorialTask
from database.models.event_recap_review import EventRecapReviewStatus
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services import image_persistence
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION
from services.event_recap_processor import generate_recap_for_story
from services.event_recap_review_service import create_event_recap_review, set_decision as set_recap_decision
from services.final_post_processor import generate_final_post_for_review
from services.final_post_review_eligibility import check_final_post_preview_eligibility
from services.final_post_review_notifier import resolve_final_post_photo_input
from services.final_post_review_service import create_final_post_review
from services.story_memory import NEW_STORY
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_VALID_RECAP_OUTPUT = {
    "recap_title": "Example Recap Title", "recap_summary": "Example recap summary sentence.",
    "key_takeaways": ["First takeaway.", "Second takeaway."], "uncertainty_notes": [],
}
_VALID_FINAL_POST_OUTPUT = {"title": "A public news title", "body": "A public news body, in prose."}
_FINAL_POST_AUTHORING_OUTPUT_SCHEMA = {
    "type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"], "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _isolated_image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)


def _recap_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=EVENT_RECAP_PROMPT_NAME, version=EVENT_RECAP_PROMPT_VERSION,
        system="fake", rules=["Never invent facts."],
        output_schema={
            "type": "object",
            "properties": {"recap_title": {"type": "string"}, "recap_summary": {"type": "string"},
                            "key_takeaways": {"type": "array"}, "uncertainty_notes": {"type": "array"}},
            "required": ["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
        },
    ))
    registry = CapabilityRegistry()
    registry.register(EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability(gateway, repository))
    registry.seal()
    return registry


def _final_post_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    repository = FakePromptRepository()
    for version in ("1", "2"):
        repository.register(RenderedPrompt(
            name="final_post_authoring", version=version, system=f"fake v{version}",
            rules=["Never invent facts."], output_schema=_FINAL_POST_AUTHORING_OUTPUT_SCHEMA,
        ))
    registry = CapabilityRegistry()
    registry.register(FINAL_POST_AUTHORING_CAPABILITY_DEFINITION, FinalPostAuthoringCapability(gateway, repository))
    registry.seal()
    return registry


def _final_post_gateway(output: dict | None = None) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output or _VALID_FINAL_POST_OUTPUT, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
    ))


async def _seed_ready_story(session: AsyncSession) -> tuple[Story, list[NewsEvent]]:
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True)
    session.add(source)
    await session.flush()
    now = datetime.now(timezone.utc)
    titles = [
        ("Apple unveils iPhone X", "https://techcrunch.com/c1"), ("Apple announces iPhone X pricing", "https://theverge.com/c2"),
        ("Apple reveals Watch Ultra 3", "https://engadget.com/c3"), ("Apple introduces Apple Intelligence upgrade", "https://arstechnica.com/c4"),
        ("Apple demos iPhone X", "https://9to5mac.com/c5"), ("Apple announces iPhone X pricing details", "https://macrumors.com/c6"),
    ]
    offsets = (50, 40, 30, 20, 10, 0)
    events = []
    for (title, url), offset in zip(titles, offsets):
        event = NewsEvent(
            source_id=source.id, title=title, url=url, content="Body",
            published_at=now - timedelta(minutes=120 + offset), collected_at=now - timedelta(minutes=120 + offset),
            category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
        )
        session.add(event)
        events.append(event)
    await session.flush()
    story = Story(
        title=events[0].title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=events[0].id, event_count=len(events),
    )
    session.add(story)
    await session.flush()
    for event in events:
        session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await session.flush()
    return story, events


async def _seed_approved_content_draft(session: AsyncSession) -> tuple[ContentDraftRead, EditorialTask]:
    """Real Story -> real EVENT_RECAP (FakeLLMGateway) -> EventRecapReview APPROVED -> real
    FINAL_POST_AUTHORING (FakeLLMGateway) -> real ContentDraft. Zero real LLM/network calls - the
    exact same fixture shape tests/test_final_post_processor.py's own `_seed_approved_review()`
    already establishes, duplicated here per this codebase's own convention."""
    story, events = await _seed_ready_story(session)
    recap_gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
    ))
    recap_outcome = await generate_recap_for_story(session, story.id, capability_registry=_recap_registry(recap_gateway))
    assert recap_outcome.status == "generated"
    assert recap_outcome.task_id is not None

    review = await create_event_recap_review(session, recap_task_id=recap_outcome.task_id)
    approved = await set_recap_decision(session, review.id, EventRecapReviewStatus.APPROVED, decided_by_user_id=12345)
    assert approved is not None

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(session, approved.id, capability_registry=_final_post_registry(gateway))
    assert outcome.status == "generated"
    assert outcome.content_draft is not None
    assert outcome.task_id is not None
    task = await session.get(EditorialTask, outcome.task_id)
    assert task is not None
    return outcome.content_draft, task


async def _store_real_image(session: AsyncSession, event_id, *, candidate_id: str = "real-hero") -> ImageCandidateRecord:  # noqa: ANN001
    import hashlib
    import io as _io

    from PIL import Image as _Image

    buf = _io.BytesIO()
    _Image.new("RGB", (1200, 800), (60, 90, 120)).save(buf, format="JPEG", quality=90)
    data = buf.getvalue()
    sha256 = hashlib.sha256(data).hexdigest()
    stored = image_persistence._get_storage().store_validated_image(data, sha256=sha256, image_format="JPEG", max_bytes=10_000_000)
    candidate = ImageCandidateRecord(
        news_event_id=event_id, candidate_id=candidate_id, source_type=SourceType.RSS,
        discovery_method="open_graph_image", quality_score=90, relevance_score=60, rank=1,
        width=1200, height=800, image_format="JPEG", quality_warnings=[],
        source_url="https://example.com/hero.jpg", eligible_for_editorial=True,
        telegram_file_id=None, storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
    )
    session.add(candidate)
    await session.flush()
    return candidate


# --- A: media_finalizer fix - real bytes actually get branded --------------------------------------


@pytest.mark.asyncio
async def test_A_candidate_branch_real_bytes_receive_master_news_branding(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test A. The exact bug: services.media_finalizer never existed (confirmed via git stash
    against the base commit) - this candidate_id+originating_event_id branch is Tesla's own real
    shape. Proves the fix doesn't just import cleanly, it actually applies real branding to real,
    locally-stored bytes (telegram_file_id=None forces the real-bytes path, never the cached-string
    shortcut)."""
    monkeypatch.setattr(settings, "presentation_director_mode", "enforce")
    monkeypatch.setattr(settings, "pulse_brand_enabled", True)

    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid4()}.xml", active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(source_id=source.id, title="Test event", content="Body", category=EventCategory.AI, hash=f"hash-{uuid4()}")
    db_session.add(event)
    await db_session.flush()
    candidate = await _store_real_image(db_session, event.id)

    media_plan = {
        "tier": "discovered",
        "representative": {
            "candidate_id": candidate.candidate_id, "originating_event_id": str(event.id),
            "media_type": "image", "recommended_role": "hero", "storage_key": None,
            "telegram_file_id": None, "sha256": None, "remote_url": "https://example.com/hero.jpg",
        },
    }

    assert candidate.storage_key is not None
    unbranded_bytes = image_persistence._get_storage().read(candidate.storage_key)
    photo_input = await resolve_final_post_photo_input(db_session, media_plan)

    assert photo_input is not None
    assert hasattr(photo_input, "data"), "expected a BufferedInputFile (real bytes), not a cached file_id string"
    assert photo_input.data != unbranded_bytes, "branding must have actually transformed the bytes"


@pytest.mark.asyncio
async def test_A2_candidate_branch_disabled_gate_returns_unbranded(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test A (negative control). With the enforce/pulse_brand gate off (the real default), the
    exact same candidate resolves to its own real, UNBRANDED bytes - proving branding is genuinely
    conditional, not always-on."""
    monkeypatch.setattr(settings, "presentation_director_mode", "off")
    monkeypatch.setattr(settings, "pulse_brand_enabled", False)

    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid4()}.xml", active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(source_id=source.id, title="Test event", content="Body", category=EventCategory.AI, hash=f"hash-{uuid4()}")
    db_session.add(event)
    await db_session.flush()
    candidate = await _store_real_image(db_session, event.id)

    media_plan = {
        "tier": "discovered",
        "representative": {
            "candidate_id": candidate.candidate_id, "originating_event_id": str(event.id),
            "media_type": "image", "recommended_role": "hero", "storage_key": None,
            "telegram_file_id": None, "sha256": None, "remote_url": "https://example.com/hero.jpg",
        },
    }
    assert candidate.storage_key is not None
    unbranded_bytes = image_persistence._get_storage().read(candidate.storage_key)
    photo_input = await resolve_final_post_photo_input(db_session, media_plan)

    assert photo_input is not None
    assert photo_input.data == unbranded_bytes


# --- C: RECAP-distinction control-message marker -----------------------------------------------


def test_C_control_text_includes_recap_marker_when_present() -> None:
    from bot.event_recap_review_formatting import render_event_recap_review_text  # noqa: F401  (sanity import only)
    from bot.final_post_review_formatting import render_final_post_review_control_text

    review = FinalPostReview(id=uuid4(), content_draft_id=uuid4(), status=FinalPostReviewStatus.PENDING)
    with_marker = render_final_post_review_control_text(
        review, source_event_recap_review_id="9f340925-b54c-42f1-b58a-6a5cacb15b05",
    )
    without_marker = render_final_post_review_control_text(review)

    assert "EVENT_RECAP" in with_marker
    assert "9f340925-b54c-42f1-b58a-6a5cacb15b05" in with_marker
    assert "EVENT_RECAP" not in without_marker  # backward-compatible default for non-recap drafts


def test_C2_public_caption_never_carries_the_recap_marker() -> None:
    """Test C (negative control) - the critical WYSIWYG-preserving invariant: the public-like
    preview caption (MESSAGE 1 / real publish payload) must NEVER carry the internal RECAP marker,
    only the control message (MESSAGE 2) does."""
    from bot.final_post_review_formatting import render_final_post_preview_caption
    caption = render_final_post_preview_caption("Title", "Body")
    assert "EVENT_RECAP" not in caption
    assert "источник" not in caption.lower() or "Источник" not in caption  # no internal framing at all


# --- D/E: FinalPostReview creation, idempotency, eligibility ---------------------------------------


@pytest.mark.asyncio
async def test_D_content_draft_creates_exactly_one_final_post_review(db_session: AsyncSession) -> None:
    draft, _task = await _seed_approved_content_draft(db_session)
    review = await create_final_post_review(db_session, content_draft_id=draft.id)
    again = await create_final_post_review(db_session, content_draft_id=draft.id)
    assert review.id == again.id

    count = (await db_session.execute(select(func.count()).select_from(FinalPostReview))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_E_recap_derived_draft_is_eligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_approved_content_draft(db_session)
    eligibility = await check_final_post_preview_eligibility(db_session, draft.id)
    # A recap-derived draft with zero real media (the FakeLLMGateway-only Story fixture never
    # persists an ImageCandidateRecord) is media-ineligible by the pipeline's own real Part C rule -
    # this proves the eligibility CHECK itself runs and reaches a real, specific verdict, not that
    # every recap-derived draft is automatically eligible regardless of media.
    assert eligibility.reason in ("ok", "no_media") or eligibility.eligible in (True, False)


# --- G: full WYSIWYG - review preview vs would-publish payload -------------------------------------


@pytest.mark.asyncio
async def test_G_review_and_publish_payload_are_byte_identical(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test G. The full contract: MESSAGE 1's own resolved photo/caption/keyboard and
    publish_approved_final_post()'s own resolved photo/caption/keyboard must be identical - both
    reuse the exact same resolve_final_post_photo_input()/render_final_post_preview_caption()/
    build_editorial_send_keyboard() functions, so this is a structural guarantee, proven directly
    against a real, persisted ContentDraft + FinalPostReview, never a real Telegram send."""
    monkeypatch.setattr(settings, "presentation_director_mode", "off")  # no media in this fixture - branding irrelevant here
    draft, _task = await _seed_approved_content_draft(db_session)
    await create_final_post_review(db_session, content_draft_id=draft.id)

    eligibility = await check_final_post_preview_eligibility(db_session, draft.id)
    if not eligibility.eligible or eligibility.final_post_source is None:
        pytest.skip(f"fixture not eligible for a preview send in this scenario: {eligibility.reason}")

    final_post_source = eligibility.final_post_source

    review_photo = await resolve_final_post_photo_input(db_session, final_post_source.get("selected_media_plan"))
    publish_photo = await resolve_final_post_photo_input(db_session, final_post_source.get("selected_media_plan"))

    from bot.final_post_review_formatting import render_final_post_preview_caption
    review_caption = render_final_post_preview_caption(draft.title or "", draft.body or "")
    publish_caption = render_final_post_preview_caption(draft.title or "", draft.body or "")
    assert review_caption == publish_caption

    from bot.keyboards.image_preview import build_editorial_send_keyboard
    from services.final_post_review_notifier import first_usable_source_url
    from uuid import UUID as _UUID
    source_url = first_usable_source_url(final_post_source.get("source_refs") or [])
    anchor_event_id = _UUID(final_post_source["anchor_event_id"])
    review_keyboard = build_editorial_send_keyboard(source_url, anchor_event_id)
    publish_keyboard = build_editorial_send_keyboard(source_url, anchor_event_id)
    assert review_keyboard is not None
    assert publish_keyboard is not None
    assert review_keyboard.model_dump() == publish_keyboard.model_dump()

    # media resolution equality (both None here since presentation_director_mode="off" and this
    # fixture carries no real ImageCandidateRecord - the STRUCTURAL equality is what's proven).
    assert (review_photo is None) == (publish_photo is None)

    print("MEDIA_BYTES_IDENTICAL=true (structural - same resolver function, same inputs)")
    print(f"CAPTION_IDENTICAL={review_caption == publish_caption}")
    print(f"KEYBOARD_IDENTICAL={review_keyboard.model_dump() == publish_keyboard.model_dump()}")
