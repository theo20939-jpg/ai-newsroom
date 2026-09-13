"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S25/S28/S35: the shared orchestrator, end to end, with a
deterministic fake renderer standing in for the real Pillow-based V8 renderers (S17 - rendering is
injected, never performed by the orchestrator itself)."""
from uuid import uuid4

import pytest

from services.editorial_pipeline.contracts import Platform, PresentationFormat, QuoteCandidate
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.orchestrator import run_editorial_production_pipeline

pytestmark = pytest.mark.asyncio

_MAXUS_FACT = "Рекомендованная цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)."
_MAXUS_TITLE = "Представлен минивэн SAIC Maxus 9 2027 с заменой батареи за 90 секунд"
_MAXUS_BODY = (
    "SAIC представила минивэн Maxus 9 2027 года. Стартовая цена модели составляет "
    "290 тыс. юаней, что соответствует примерно 3,8 млн рублей."
)


async def _fake_render_success(composition_plan, structured_content):
    if structured_content is None:
        return None
    text = getattr(structured_content, "metric_label", None) or getattr(structured_content, "headline", "")
    return "fake-photo-input", f"<b>{text}</b>\nrendered caption"


async def _fake_render_none() -> None:
    return None


async def test_data_pipeline_end_to_end_produces_a_ready_package_with_the_maxus_fix() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url="https://example.com", research_facts=[_MAXUS_FACT])

    result = await run_editorial_production_pipeline(
        content_draft_id=uuid4(), presentation_format=PresentationFormat.DATA, title=_MAXUS_TITLE,
        main_body=_MAXUS_BODY, evidence=evidence, platform=Platform.TELEGRAM, render=_fake_render_success,
    )

    assert result.is_ready
    assert result.recovery_job is None
    assert "Стартовая цена Maxus 9" in result.delivery_package.caption_or_copy
    assert "290" not in result.delivery_package.caption_or_copy.split("\n")[0]  # label line has no raw number


async def test_render_failure_produces_recovery_never_a_silent_text_completion() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    async def always_fails(composition_plan, structured_content):
        return None

    result = await run_editorial_production_pipeline(
        content_draft_id=uuid4(), presentation_format=PresentationFormat.NEWS, title="Some real news title",
        main_body="Some real body.", evidence=evidence, platform=Platform.TELEGRAM, render=always_fails,
    )

    assert not result.is_ready
    assert result.recovery_job is not None
    assert result.recovery_job.reason_code.value == "RENDER_FAILED"


async def test_no_suitable_media_still_produces_a_ready_text_appropriate_package_when_render_allows_it() -> None:
    """A NEWS post with genuinely no photo is not automatically a failure - the renderer decides
    whether a text-appropriate composition is valid (mirrors S4-C's carve-out: not every
    no-visual outcome is wrong, only a SILENT one is). Here the fake renderer honestly returns
    photo_input=None with real caption text, and the pipeline still reaches READY."""
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=["a real, verified fact"])

    async def render_text_only(composition_plan, structured_content):
        return None, f"<b>{structured_content.headline}</b>\nBody text here."

    result = await run_editorial_production_pipeline(
        content_draft_id=uuid4(), presentation_format=PresentationFormat.NEWS, title="Operator status update",
        main_body="Body text here.", evidence=evidence, platform=Platform.TELEGRAM, render=render_text_only,
    )
    assert result.is_ready
    assert result.delivery_package.composition_plan.photo_input is None


async def test_the_real_maxus_defect_text_never_reaches_a_ready_package() -> None:
    """If a caller's render callable somehow produced the OLD, buggy label text anyway (e.g. a
    not-yet-migrated legacy renderer), the shared quality gate (S21) still catches it before a
    DeliveryPackage is ever produced - defense in depth, not reliance on a single fix point."""
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[_MAXUS_FACT])

    async def render_with_the_old_defect(composition_plan, structured_content):
        return "photo", "Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн рублей)."

    result = await run_editorial_production_pipeline(
        content_draft_id=uuid4(), presentation_format=PresentationFormat.DATA, title=_MAXUS_TITLE,
        main_body=_MAXUS_BODY, evidence=evidence, platform=Platform.TELEGRAM, render=render_with_the_old_defect,
    )
    assert not result.is_ready
    assert result.recovery_job is not None
    assert result.recovery_job.reason_code.value == "QUALITY_GATE_FAILED"


async def test_caption_too_long_holds_never_drops_the_visual_for_plain_text() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    async def render_too_long(composition_plan, structured_content):
        return "photo", "<b>Заголовок</b>\n" + ("А" * 2000)

    result = await run_editorial_production_pipeline(
        content_draft_id=uuid4(), presentation_format=PresentationFormat.NEWS, title="Long post",
        main_body="x" * 2000, evidence=evidence, platform=Platform.TELEGRAM, render=render_too_long,
    )
    assert not result.is_ready
    assert result.recovery_job.reason_code.value == "CAPTION_BUDGET_FAILED"


async def test_quote_pipeline_uses_structured_quote_content() -> None:
    fact = "Директор компании заявил: «Мы верим в будущее продукта»."
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[fact])
    quote_candidate = QuoteCandidate(text="Мы верим в будущее продукта", speaker="Директор компании", role=None)

    async def render_quote(composition_plan, structured_content):
        return "photo", f"<blockquote>{structured_content.quote}</blockquote> — {structured_content.speaker}"

    result = await run_editorial_production_pipeline(
        content_draft_id=uuid4(), presentation_format=PresentationFormat.QUOTE, title="Quote story",
        main_body=None, evidence=evidence, platform=Platform.TELEGRAM, render=render_quote, quote_candidate=quote_candidate,
    )
    assert result.is_ready
    assert "Мы верим в будущее продукта" in result.delivery_package.caption_or_copy
    assert "Директор компании" in result.delivery_package.caption_or_copy


async def test_media_send_failure_class_is_available_as_a_recovery_reason() -> None:
    """S28-F: a media-send failure (detected upstream of this orchestrator, by the platform's own
    transport call) must become a reason-coded recovery, never a silent text fallback - this test
    proves the reason code exists and round-trips through create_recovery_job() correctly; the
    live Telegram send-failure path itself is exercised by this session's own prior TELEGRAM-TEXT-
    ONLY-VISUAL-FALLBACK-REPAIR-1 test suite (test_photo_timeout_holds_for_visual_recovery_
    instead_of_text_fallback), reused rather than duplicated here."""
    from services.editorial_pipeline.contracts import RecoveryReasonCode
    from services.editorial_pipeline.recovery import create_recovery_job

    job = create_recovery_job(
        content_draft_id=uuid4(), reason_code=RecoveryReasonCode.MEDIA_SEND_FAILED, failed_stage="telegram_transport",
    )
    assert job.reason_code == RecoveryReasonCode.MEDIA_SEND_FAILED
    assert job.is_terminal  # bounded - never retried automatically beyond max_attempts
