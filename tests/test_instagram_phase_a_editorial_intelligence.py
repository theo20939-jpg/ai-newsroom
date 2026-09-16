from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.instagram_editorial_delivery import (
    InstagramEditorialDelivery,
    InstagramEditorialDeliveryState,
)
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramEditorialDecision
from services.instagram_creative_director import (
    AudienceFacingCopyError,
    CreativeLanguageError,
    InstagramEditorialDecisionInput,
    assert_audience_facing_copy,
    assert_russian_final_text,
    generate_editorial_decision,
)
from services.instagram_director_context import load_instagram_director_context, render_product_truth
from services.instagram_editorial_delivery_state import (
    angle_similarity,
    check_instagram_editorial_duplicate,
)
from services.instagram_format_director import ContentFormat
from services.instagram_trend_radar import TrendKind
from tests.fakes.fake_gateway import FakeLLMGateway

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _decision(**overrides: object) -> InstagramEditorialDecision:
    values: dict[str, object] = {
        "source_summary": "Apple выпустила обновление iOS",
        "opportunity_type": "NEWS",
        "why_now": "Обновление выходит сейчас и затрагивает пользователей iPhone.",
        "audience_value": "Читатель быстро поймёт, что изменилось и стоит ли обновляться.",
        "angle": "Что на самом деле изменилось в Siri AI",
        "angle_intent": "EXPLAINER",
        "topic": "Apple и Siri AI",
        "purpose": "VALUE",
        "origin": "NEWS",
        "recommended_format": "carousel",
        "format_reason": "Изменения лучше разобрать по нескольким карточкам.",
        "creative_direction": "Короткий разбор от главного изменения к практическому выводу.",
        "product_connection": None,
        "trend_rationale": None,
        "supplementary_story_idea": None,
        "evidence_used": ["Apple выпустила iOS 27"],
    }
    values.update(overrides)
    return InstagramEditorialDecision(**values)  # type: ignore[arg-type]


def _response(payload: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=payload,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=100, output_tokens=100),
    )


def test_russian_post_and_reel_final_copy_are_accepted() -> None:
    assert_russian_final_text(["Apple выпустила iOS 27 — вот что изменилось.", "Сохраните разбор."])
    assert_russian_final_text([
        "Почему Apple снова отстаёт в гонке ИИ?",
        "Разбираем три причины и показываем, что это значит для пользователей iPhone.",
    ])


def test_clearly_english_reel_for_ru_account_is_rejected() -> None:
    with pytest.raises(CreativeLanguageError):
        assert_russian_final_text([
            "Apple is rolling out iOS 27 with Siri AI across all supported devices.",
            "Which update are you watching most closely this week?",
        ])


def test_english_product_and_company_names_inside_russian_copy_are_allowed() -> None:
    assert_russian_final_text([
        "OpenAI добавила новый режим в ChatGPT, а NINJA AI помогает встроить ИИ в ежедневный workflow."
    ])


def test_visible_cta_service_label_is_rejected() -> None:
    with pytest.raises(AudienceFacingCopyError):
        assert_audience_facing_copy(["CTA: Что думаете?"])


def test_director_context_contains_brand_goals_and_product_boundary() -> None:
    context = load_instagram_director_context()
    assert "Технологии на твоей стороне" in context
    assert "Живи проще. Делай больше" in context
    assert "audience growth" in context
    assert "External editorial news" in context
    assert "NINJA AI" in context and "NINJA VPN" in context and "NINJA Store" in context


def test_runtime_product_truth_keeps_planned_feature_and_launch_state_explicit() -> None:
    product = SimpleNamespace(
        id=uuid4(), name="Ninja AI", slug="ninja_ai", status=SimpleNamespace(value="pre_launch"),
        current_stage=None, description=None, current_features=[],
        planned_features=["Релиз Ninja AI в Telegram"], undecided_facts=[], pricing_status=None,
        product_url=None, waitlist_url=None,
    )
    snapshot = SimpleNamespace(
        as_of=datetime(2026, 9, 16, tzinfo=UTC),
        products=[SimpleNamespace(product=product, active_campaign=None)],
        approved_claims=[], restricted_claims=[], active_directives=[],
    )
    rendered = render_product_truth(snapshot)
    assert "status=pre_launch" in rendered
    assert "planned, not yet live feature: Релиз Ninja AI в Telegram" in rendered
    assert "confirmed current feature" not in rendered


@pytest.mark.asyncio
async def test_editorial_director_receives_brand_account_product_and_history_context() -> None:
    decision = _decision().model_dump()
    gateway = FakeLLMGateway(generate_response=_response(decision))
    result, call = await generate_editorial_decision(
        gateway,
        FilePromptRepository(_PROMPTS_ROOT),
        decision_input=InstagramEditorialDecisionInput(
            source_type="news",
            source_summary="Apple выпустила iOS 27",
            allowed_evidence=["Apple выпустила iOS 27"],
            brand_context="NINJA — Технологии на твоей стороне.",
            account_context="launch_state=pre_launch",
            product_context="Ninja AI status=pre_launch",
            recent_content_context="single | AI | reach | news",
        ),
    )
    assert result.recommended_format == "carousel"
    assert call is not None
    prompt = str(gateway.received_requests[-1].messages[-1].content[0].text)
    assert "Технологии на твоей стороне" in prompt
    assert "launch_state=pre_launch" in prompt
    assert "Ninja AI status=pre_launch" in prompt
    assert "single | AI | reach | news" in prompt
    assert "OUTPUT LOCALE: ru" in prompt


def test_news_x_trend_requires_explicit_rationale_and_no_fit_is_not_forced() -> None:
    with pytest.raises(ValidationError):
        _decision(opportunity_type="NEWS_X_TREND", trend_rationale=None)
    ordinary = _decision(opportunity_type="NEWS", trend_rationale=None)
    assert ordinary.trend_rationale is None


def test_product_x_trend_requires_real_ninja_product_connection() -> None:
    decision = _decision(
        opportunity_type="PRODUCT_X_TREND", origin="PRODUCT", purpose="PRODUCT",
        angle_intent="PRODUCT_USE_CASE", product_connection="NINJA AI: сценарий использования подтверждён контекстом",
        trend_rationale="Формат тренда естественно показывает этот сценарий без выдуманных функций.",
    )
    assert decision.product_connection.startswith("NINJA AI")
    with pytest.raises(ValidationError):
        _decision(
            opportunity_type="PRODUCT_X_TREND", origin="PRODUCT", purpose="PRODUCT",
            angle_intent="PRODUCT_USE_CASE", product_connection=None,
            trend_rationale="Есть тренд.",
        )


@pytest.mark.parametrize("fmt", ["single", "carousel", "reel"])
def test_director_can_select_every_executable_format(fmt: str) -> None:
    assert _decision(recommended_format=fmt).recommended_format == fmt
    assert fmt in {item.value for item in ContentFormat}


def test_trend_taxonomy_distinguishes_supported_signal_types() -> None:
    assert {kind.value for kind in TrendKind} == {"topic", "meme_culture", "format", "discussion"}


class _ScalarRows:
    def __init__(self, rows: list[InstagramEditorialDelivery]) -> None:
        self.rows = rows

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[InstagramEditorialDelivery]:
        return self.rows


class _HistorySession:
    def __init__(self, rows: list[InstagramEditorialDelivery]) -> None:
        self.rows = rows

    async def execute(self, _stmt: object) -> _ScalarRows:
        return _ScalarRows(self.rows)


def _delivery(
    *, story_id: str, angle: str, intent: str = "EXPLAINER", fmt: str = "single",
    state: InstagramEditorialDeliveryState = InstagramEditorialDeliveryState.DELIVERED,
) -> InstagramEditorialDelivery:
    return InstagramEditorialDelivery(
        id=uuid4(), package_identity=uuid4().hex, version=1, source_story_id=story_id,
        content_format=fmt, state=state, created_at=datetime.now(UTC),
        package_snapshot={
            "opportunity": {
                "id": uuid4().hex,
                "editorial_decision": {
                    "angle": angle, "angle_intent": intent, "topic": "Apple",
                    "purpose": "VALUE", "origin": "NEWS",
                },
            },
            "package": {"caption": angle},
        },
    )


def test_angle_similarity_is_semantic_token_based_not_headline_equality() -> None:
    assert angle_similarity(
        "Что на самом деле изменилось в Siri AI",
        "Разбираем, что изменилось в Siri после обновления AI",
    ) > 0.25


@pytest.mark.asyncio
async def test_same_story_same_angle_different_format_is_blocked() -> None:
    story_id = str(uuid4())
    session = _HistorySession([_delivery(story_id=story_id, angle="Что изменилось в Siri AI", fmt="reel")])
    result = await check_instagram_editorial_duplicate(
        session, source_story_id=story_id, angle="Что изменилось в Siri AI", angle_intent="EXPLAINER",
    )
    assert result.blocked is True
    assert "as reel" in result.reason


@pytest.mark.asyncio
async def test_same_story_materially_different_angle_is_allowed() -> None:
    story_id = str(uuid4())
    session = _HistorySession([_delivery(story_id=story_id, angle="Что изменилось в Siri AI", intent="EXPLAINER")])
    result = await check_instagram_editorial_duplicate(
        session, source_story_id=story_id,
        angle="Почему Apple всё ещё отстаёт в гонке ИИ", angle_intent="IMPACT",
    )
    assert result.blocked is False


@pytest.mark.asyncio
async def test_semantically_clustered_source_events_share_duplicate_guard() -> None:
    canonical_story_id = str(uuid4())
    session = _HistorySession([_delivery(story_id=canonical_story_id, angle="Разбор запуска iOS 27")])
    result = await check_instagram_editorial_duplicate(
        session, source_story_id=canonical_story_id,
        angle="Разбор запуска iOS 27", angle_intent="EXPLAINER",
    )
    assert result.blocked is True


@pytest.mark.asyncio
async def test_unrelated_story_is_not_blocked() -> None:
    session = _HistorySession([_delivery(story_id=str(uuid4()), angle="Разбор запуска iOS 27")])
    result = await check_instagram_editorial_duplicate(
        session, source_story_id=str(uuid4()), angle="Новый чип Nvidia", angle_intent="BREAKING",
    )
    assert result.blocked is False


@pytest.mark.asyncio
async def test_in_flight_and_recent_delivered_duplicates_are_blocked() -> None:
    story_id = str(uuid4())
    for state in (InstagramEditorialDeliveryState.PENDING, InstagramEditorialDeliveryState.DELIVERED):
        session = _HistorySession([_delivery(story_id=story_id, angle="Разбор запуска iOS 27", state=state)])
        result = await check_instagram_editorial_duplicate(
            session, source_story_id=story_id, angle="Разбор запуска iOS 27", angle_intent="EXPLAINER",
        )
        assert result.blocked is True


@pytest.mark.asyncio
async def test_explicit_canary_override_does_not_weaken_normal_behavior() -> None:
    story_id = str(uuid4())
    session = _HistorySession([_delivery(story_id=story_id, angle="Разбор запуска iOS 27")])
    canary = await check_instagram_editorial_duplicate(
        session, source_story_id=story_id, angle="Разбор запуска iOS 27",
        angle_intent="EXPLAINER", allow_duplicate_canary=True,
    )
    normal = await check_instagram_editorial_duplicate(
        session, source_story_id=story_id, angle="Разбор запуска iOS 27", angle_intent="EXPLAINER",
    )
    assert canary.blocked is False and canary.canary_override_used is True
    assert normal.blocked is True and normal.canary_override_used is False
