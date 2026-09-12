"""INSTAGRAM GROWTH ENGINE v2, spec §72: consolidated safety acceptance tests - restricted claim
never promoted, Founder Directive precedence, embargo precedence, internal-only visibility never
implies a public recommendation, every flag defaults False, and no publication/Meta-write code path
exists anywhere in this phase's new modules."""
from __future__ import annotations

import inspect

from core.config import settings
from database.models.business_context_shared import Visibility
from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from datetime import datetime, timezone

from services.campaign_planner import CampaignPlan
from services.instagram_content_opportunity import OpportunitySourceType, build_content_opportunity
from services.instagram_format_director import ClaimViolationError
from services.instagram_growth_strategist import OpportunityContext, apply_founder_directive_precedence
from services.instagram_platform_capabilities import INSTAGRAM_PLATFORM_CAPABILITIES, CapabilityStatus

import services.instagram_content_opportunity as content_opportunity_module
import services.instagram_competitor_intelligence as competitor_module
import services.instagram_growth_strategist as growth_strategist_module
import services.instagram_calendar_service as calendar_module
import services.instagram_semantic_matching as semantic_matching_module
import services.instagram_semantic_trend_matching as semantic_trend_matching_module
import services.instagram_creative_director as creative_director_module
import services.instagram_reference_analysis as reference_analysis_module
import services.instagram_shadow_pipeline as shadow_pipeline_module


_NEW_MODULES = [
    content_opportunity_module, competitor_module, growth_strategist_module, calendar_module,
    semantic_matching_module, semantic_trend_matching_module, creative_director_module,
    reference_analysis_module, shadow_pipeline_module,
]


def test_no_publication_or_meta_write_symbol_anywhere_in_new_modules() -> None:
    forbidden_substrings = ("graph.facebook", "meta_api", "post_to_instagram", "publish_to_instagram", "instagram_publish")
    for module in _NEW_MODULES:
        source = inspect.getsource(module)
        lowered = source.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"{module.__name__} unexpectedly references {forbidden!r}"


def test_all_new_feature_flags_default_false() -> None:
    assert settings.instagram_competitor_intelligence_enabled is False
    assert settings.instagram_growth_strategy_shadow_enabled is False
    assert settings.instagram_calendar_enabled is False
    assert settings.instagram_semantic_matching_enabled is False
    assert settings.instagram_creative_director_shadow_enabled is False
    # INSTAGRAM-EXECUTION-FOUNDATION-1 (section 18) deliberately adds ONE new flag,
    # `instagram_publication_enabled`, as the hard-disabled publish safety gate itself - its
    # existence is not a regression of "no publication code path exists in the modules this test
    # checks" (still true - see test_no_publication_or_meta_write_symbol_anywhere_in_new_modules
    # above, unaffected: services/instagram_publish_adapter.py is not one of _NEW_MODULES). It
    # still defaults False, same as every flag above.
    assert settings.instagram_publication_enabled is False
    assert not hasattr(settings, "instagram_ad_spend_enabled")


def test_platform_capabilities_still_honest_after_v2_additions() -> None:
    for capability in INSTAGRAM_PLATFORM_CAPABILITIES.values():
        assert capability.status in (CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNKNOWN)


def test_internal_only_visibility_is_distinct_from_public_allowed() -> None:
    assert Visibility.INTERNAL_ONLY != Visibility.PUBLIC_ALLOWED
    assert Visibility.INTERNAL_ONLY.value == "internal_only"


def test_restricted_claim_raises_even_under_high_relevance_opportunity() -> None:
    with_restriction = build_content_opportunity(
        id="s1", source_type=OpportunitySourceType.PRODUCT, product_id="p1", news_value=0.99,
        campaign_plan=CampaignPlan(
            campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
            date_confidence="exact", start_at=None, end_at=None, restricted_claims=["$4.99/month"],
        ),
    )
    assert with_restriction.restricted_claims == ["$4.99/month"]
    # A downstream package asserting the restricted claim must still fail (spec §56's own
    # "enough structured information to avoid using restricted content" requirement, enforced by
    # services/instagram_format_director.py::validate_package_claims - already covered directly in
    # tests/test_instagram_growth_engine_foundation.py, re-asserted here against a HIGH-relevance
    # opportunity specifically, since relevance must never soften claim enforcement).
    from services.instagram_format_director import SinglePostPackage
    from services.instagram_objectives import ContentObjective
    try:
        SinglePostPackage(
            objective=ContentObjective.PRODUCT_CLICK, visual_concept="v", copy="Only $4.99/month!",
            caption="Buy now", cta="Buy", restricted_claims=with_restriction.restricted_claims,
        )
        raised = False
    except ClaimViolationError:
        raised = True
    assert raised


def test_founder_directive_precedence_survives_high_relevance_and_confirmed_campaign() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )
    opportunity = build_content_opportunity(
        id="s2", source_type=OpportunitySourceType.HYBRID, story_id="story1", product_id="p1",
        news_value=0.95, campaign_plan=plan,
    )
    assert opportunity.product_mention_allowed is True

    directive = StrategicDirective(
        priority=1, valid_from=datetime.now(timezone.utc), instruction="do not reveal this yet",
        products=["p1_slug"], platforms=[], status=DirectiveStatus.ACTIVE,
    )
    resolved, notes = apply_founder_directive_precedence(
        [OpportunityContext(opportunity=opportunity, product_slug="p1_slug")], [directive],
    )
    assert resolved[0].product_mention_allowed is False
    assert notes


def test_embargo_precedence_blocks_mention_even_with_confirmed_campaign() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )
    opportunity = build_content_opportunity(
        id="s3", source_type=OpportunitySourceType.PRODUCT, product_id="p1", campaign_plan=plan, embargo_active=True,
    )
    assert opportunity.product_mention_allowed is False
    assert opportunity.embargo_constraints
