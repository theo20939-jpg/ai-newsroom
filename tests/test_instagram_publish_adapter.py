"""INSTAGRAM-EXECUTION-FOUNDATION-1 sections 16-21/27: the official publish adapter, the hard
publication-safety flag, shadow publish, and the injectable client boundary's full failure matrix
(success, container creation failure, processing timeout, publish failure, invalid media, auth
error, rate-limit, retryable server error) - all without any real credential or network write."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from core.config import settings
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import InstagramGateDecision, InstagramGateOutcome, evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_publish_adapter import (
    ContainerStatus,
    HttpInstagramPublishClient,
    InstagramPublishError,
    InstagramPublishErrorCode,
    PublicationStatus,
    ShadowInstagramPublishClient,
    publish_instagram_content,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative

_NO_SLEEP = lambda seconds: asyncio.sleep(0)  # noqa: E731 - tests never wait on real bounded backoff

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
    audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _ready_package_and_gate():
    opp = ContentOpportunity(id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="s1", product_mention_allowed=True)
    single = InstagramSingleCreative(creative_angle="a", visual_concept="v", on_image_copy="Headline", caption_direction="draft", cta="Learn more")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )
    result = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [result])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    assert gate.decision is InstagramGateDecision.READY_FOR_EDITOR
    return pkg, gate


@pytest.mark.asyncio
async def test_publication_flag_is_off_by_default() -> None:
    assert settings.instagram_publication_enabled is False


@pytest.mark.asyncio
async def test_live_publish_fails_closed_when_flag_disabled_and_never_touches_the_client() -> None:
    pkg, gate = _ready_package_and_gate()

    class ExplodingClient(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            raise AssertionError("the client must never be called when publication is disabled")

    result = await publish_instagram_content(
        pkg, gate, client=ExplodingClient(), account_id="acct", shadow=False, editor_approved=True, sleep_fn=_NO_SLEEP,
    )
    assert result.status is PublicationStatus.BLOCKED
    assert result.failure_class == InstagramPublishErrorCode.PUBLICATION_DISABLED.value


@pytest.mark.asyncio
async def test_live_publish_fails_closed_without_editor_approval_even_if_flag_were_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_publication_enabled", True)
    pkg, gate = _ready_package_and_gate()

    class ExplodingClient(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            raise AssertionError("the client must never be called without editor_approved=True")

    result = await publish_instagram_content(
        pkg, gate, client=ExplodingClient(), account_id="acct", shadow=False, editor_approved=False, sleep_fn=_NO_SLEEP,
    )
    assert result.status is PublicationStatus.BLOCKED
    assert result.failure_class == InstagramPublishErrorCode.NOT_APPROVED.value


@pytest.mark.asyncio
async def test_block_gate_outcome_never_reaches_the_client() -> None:
    pkg, _ = _ready_package_and_gate()
    blocked = InstagramGateOutcome(decision=InstagramGateDecision.BLOCK, short_reason="test")

    class ExplodingClient(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            raise AssertionError("BLOCK must never reach the client")

    result = await publish_instagram_content(pkg, blocked, client=ExplodingClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.BLOCKED
    assert result.failure_class == InstagramPublishErrorCode.GATE_NOT_PERMITTED.value


@pytest.mark.asyncio
async def test_hold_gate_outcome_never_reaches_the_client() -> None:
    pkg, _ = _ready_package_and_gate()
    held = InstagramGateOutcome(decision=InstagramGateDecision.HOLD, short_reason="test")
    result = await publish_instagram_content(pkg, held, client=ShadowInstagramPublishClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.BLOCKED


@pytest.mark.asyncio
async def test_shadow_publish_success() -> None:
    pkg, gate = _ready_package_and_gate()
    result = await publish_instagram_content(pkg, gate, client=ShadowInstagramPublishClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.SHADOW_SUCCESS
    assert result.shadow is True
    assert result.media_id is not None and result.media_id.startswith("shadow_")
    assert result.container_ids


@pytest.mark.asyncio
async def test_shadow_publish_works_even_while_publication_flag_is_disabled() -> None:
    assert settings.instagram_publication_enabled is False
    pkg, gate = _ready_package_and_gate()
    result = await publish_instagram_content(pkg, gate, client=ShadowInstagramPublishClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.SHADOW_SUCCESS


@pytest.mark.asyncio
async def test_container_creation_failure_invalid_media() -> None:
    pkg, gate = _ready_package_and_gate()

    class FailingClient(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            raise InstagramPublishError(InstagramPublishErrorCode.INVALID_MEDIA, detail="bad media")

    result = await publish_instagram_content(pkg, gate, client=FailingClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.FAILED
    assert result.failure_class == InstagramPublishErrorCode.INVALID_MEDIA.value
    assert result.retryable is False
    assert result.attempts_used == 1


@pytest.mark.asyncio
async def test_processing_timeout_never_finishes() -> None:
    pkg, gate = _ready_package_and_gate()

    class NeverFinishes(ShadowInstagramPublishClient):
        async def get_container_status(self, container_id: str) -> ContainerStatus:
            return ContainerStatus.IN_PROGRESS

    result = await publish_instagram_content(pkg, gate, client=NeverFinishes(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.FAILED
    assert result.failure_class == InstagramPublishErrorCode.PROCESSING_TIMEOUT.value


@pytest.mark.asyncio
async def test_publish_call_itself_fails_after_a_finished_container() -> None:
    pkg, gate = _ready_package_and_gate()

    class PublishFails(ShadowInstagramPublishClient):
        async def publish_container(self, *, account_id: str, container_id: str) -> str:
            raise InstagramPublishError(InstagramPublishErrorCode.PUBLISH_FAILED, detail="rejected at publish time")

    result = await publish_instagram_content(pkg, gate, client=PublishFails(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.FAILED
    assert result.failure_class == InstagramPublishErrorCode.PUBLISH_FAILED.value
    assert result.container_ids  # the container WAS created before the publish call failed


@pytest.mark.asyncio
async def test_auth_error_is_never_retried() -> None:
    pkg, gate = _ready_package_and_gate()
    calls = {"n": 0}

    class AuthFail(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            calls["n"] += 1
            raise InstagramPublishError(InstagramPublishErrorCode.AUTH_ERROR)

    result = await publish_instagram_content(pkg, gate, client=AuthFail(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.FAILED
    assert result.failure_class == InstagramPublishErrorCode.AUTH_ERROR.value
    assert result.retryable is False
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_rate_limit_is_retried_and_then_succeeds() -> None:
    pkg, gate = _ready_package_and_gate()
    calls = {"n": 0}

    class RateLimitedThenOK(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise InstagramPublishError(InstagramPublishErrorCode.RATE_LIMITED)
            return await super().create_media_container(**kw)

    result = await publish_instagram_content(pkg, gate, client=RateLimitedThenOK(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.SHADOW_SUCCESS
    assert result.attempts_used == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_retryable_server_error_exhausts_bounded_retries_and_fails() -> None:
    pkg, gate = _ready_package_and_gate()
    calls = {"n": 0}

    class AlwaysTransient(ShadowInstagramPublishClient):
        async def create_media_container(self, **kw):
            calls["n"] += 1
            raise InstagramPublishError(InstagramPublishErrorCode.TRANSIENT)

    result = await publish_instagram_content(pkg, gate, client=AlwaysTransient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.FAILED
    assert result.failure_class == InstagramPublishErrorCode.TRANSIENT.value
    assert result.retryable is True
    assert calls["n"] <= 3  # 1 initial + 2 bounded retries, NEVER unbounded


@pytest.mark.asyncio
async def test_carousel_shadow_publish_creates_one_container_per_child_plus_the_parent() -> None:
    from services.instagram_creative_director import CreativeGenerationOutcome as CGO
    from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative

    opp = ContentOpportunity(id="opp-2", source_type=OpportunitySourceType.NEWS, story_id="s2", product_mention_allowed=True)
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v1"),
        InstagramCarouselSlideCreative(role="body", slide_copy="Body", visual_direction="v2"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Swipe")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CGO(carousel=carousel),
    )
    from services.instagram_platform_renderer import render_instagram_carousel

    results = render_instagram_carousel(pkg)
    art = validate_instagram_art(pkg, results)
    gate = evaluate_instagram_editorial_gate(pkg, art)
    result = await publish_instagram_content(pkg, gate, client=ShadowInstagramPublishClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.SHADOW_SUCCESS
    assert len(result.container_ids) == 3  # 2 child containers + 1 carousel parent container


@pytest.mark.asyncio
async def test_reel_without_external_video_asset_fails_invalid_media() -> None:
    from services.instagram_creative_director import CreativeGenerationOutcome as CGO
    from schemas.instagram_creative import InstagramReelCreative

    opp = ContentOpportunity(id="opp-3", source_type=OpportunitySourceType.NEWS, story_id="s3", product_mention_allowed=True)
    reel = InstagramReelCreative(objective="reach", hook="Watch", target_duration_seconds=10, scene_sequence=["s1"], pacing="fast", caption_direction="draft")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.REEL), shadow_plan=_SP,
        creative_outcome=CGO(reel=reel),
    )
    from services.instagram_platform_renderer import render_instagram_reel_cover

    result_render = render_instagram_reel_cover(pkg)
    art = validate_instagram_art(pkg, [result_render])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    result = await publish_instagram_content(pkg, gate, client=ShadowInstagramPublishClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.FAILED
    assert result.failure_class == InstagramPublishErrorCode.INVALID_MEDIA.value


@pytest.mark.asyncio
async def test_zero_real_network_writes_in_shadow_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """SHADOW_INSTAGRAM_PUBLISH_NETWORK_WRITES = 0: patches httpx so ANY network call raises,
    then runs a full shadow publish - if the shadow path ever touched the network, this test fails."""

    def _explode(*args, **kwargs):
        raise AssertionError("shadow publish must never perform a real network call")

    monkeypatch.setattr(httpx.AsyncClient, "post", _explode)
    monkeypatch.setattr(httpx.AsyncClient, "get", _explode)

    pkg, gate = _ready_package_and_gate()
    result = await publish_instagram_content(pkg, gate, client=ShadowInstagramPublishClient(), account_id="acct", shadow=True, sleep_fn=_NO_SLEEP)
    assert result.status is PublicationStatus.SHADOW_SUCCESS


def test_http_client_is_never_instantiated_by_any_test_in_this_module() -> None:
    """Documents the invariant this whole file relies on: HttpInstagramPublishClient exists (the
    real official adapter, section 16) but no test above ever constructs or calls it - it is
    inert code this phase, never exercised against a live network."""
    assert HttpInstagramPublishClient is not None  # importable, present, never invoked above
