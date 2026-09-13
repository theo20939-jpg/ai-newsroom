"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S13/S20/S21/S30/S35: the Instagram adapter.

Builds a REAL InstagramContentPackage via the real, existing, unmodified
build_instagram_content_package() (same construction shape as tests/
test_instagram_content_package.py's own established pattern) and renders it with the REAL,
unmodified services.instagram_platform_renderer - no fabricated packages/render results. Proves the
shared quality gate + recovery machinery integrates with Instagram's own real output, and that this
adapter never performs a network write (S30 - zero network writes, matching the S35 required test
class verbatim)."""
from uuid import uuid4

from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.platforms.instagram import evaluate_instagram_package
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative

_OPPORTUNITY = ContentOpportunity(
    id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="story-1", campaign_id="camp-1",
    product_mention_allowed=True, allowed_claims=["fast charging"], restricted_claims=[],
)
_SHADOW_PLAN = ShadowPlanResult(
    campaign_name="Product Launch", campaign_phase="LAUNCH", opportunity_description="NEWS opportunity",
    primary_objective="reach", audience_description="tech enthusiasts", recommended_format="single",
    hook_family="curiosity", creative_concept_summary="a strong concept", alternative_format=None,
    alternative_objective=None, product_mention_allowed=True, evidence=["evidence bullet 1"], confidence=0.65,
)


def _real_package(caption: str) -> "object":
    single = InstagramSingleCreative(
        creative_angle="angle", visual_concept="concept", on_image_copy="290 ТЫС. ЮАНЕЙ",
        caption_direction=caption, cta="Learn more",
    )
    return build_instagram_content_package(
        opportunity=_OPPORTUNITY,
        format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE, why="reach"),
        shadow_plan=_SHADOW_PLAN, creative_outcome=CreativeGenerationOutcome(single=single),
    )


def test_a_clean_real_package_passes_the_shared_gate_and_needs_no_recovery() -> None:
    package = _real_package("Стартовая цена Maxus 9 составляет 290 тыс. юаней.")
    render_result = render_instagram_feed_image(package)
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4(),
    )

    assert recovery is None
    assert gate_result.verdict.value == "READY"


def test_the_same_maxus_defect_caption_is_caught_here_too_never_platform_specific() -> None:
    """The shared LANGUAGE_QUALITY check (S22) is genuinely shared - it catches the exact same
    defect class regardless of which platform's package carries it."""
    package = _real_package("Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн рублей).")
    render_result = render_instagram_feed_image(package)
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4(),
    )

    assert recovery is not None
    assert gate_result.verdict.value in ("HOLD", "BLOCK")


def test_missing_render_result_fails_art_validation_produces_recovery_never_a_publish_path() -> None:
    package = _real_package("Нормальный текст без дефектов.")
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[], evidence=evidence, content_draft_id=uuid4(),
    )

    assert recovery is not None
    assert gate_result.verdict.value == "BLOCK"


def test_evaluate_instagram_package_never_touches_the_network(monkeypatch) -> None:
    """S30: zero network writes through the publication adapter path - this function does not even
    import services.instagram_publish_adapter, confirmed structurally (a real network call would
    require it), and monkeypatching socket.socket.connect to raise proves no attempt is made."""
    import socket

    def _forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluate_instagram_package must never open a network connection")

    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)

    package = _real_package("Нормальный текст без дефектов.")
    render_result = render_instagram_feed_image(package)
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    evaluate_instagram_package(package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4())
