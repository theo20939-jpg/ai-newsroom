"""SOCIAL-INTELLIGENCE-OPS-1, spec §9/§10/§59: DirectorConsoleAccessPolicy unit tests - the
centralized decision table every console renderer consults."""
from __future__ import annotations

from services.business_context_roles import BusinessContextRole
from services.director_console_access_policy import DirectorConsoleAccessPolicy


def test_founder_sees_everything() -> None:
    policy = DirectorConsoleAccessPolicy(role=BusinessContextRole.FOUNDER)
    assert policy.can_see_founder_directive_text()
    assert policy.can_see_restricted_claims()
    assert policy.can_see_embargo_details()
    assert policy.can_see_tentative_launch_dates()
    assert policy.can_see_internal_only_milestones()
    assert policy.can_see_unpublished_calendar()
    assert policy.can_see_unreleased_creative_concepts()
    assert policy.can_see_internal_campaign_strategy_notes()
    assert policy.is_founder


def test_viewer_sees_none_of_the_sensitive_categories() -> None:
    policy = DirectorConsoleAccessPolicy(role=BusinessContextRole.VIEWER)
    assert not policy.can_see_founder_directive_text()
    assert not policy.can_see_restricted_claims()
    assert not policy.can_see_embargo_details()
    assert not policy.can_see_tentative_launch_dates()
    assert not policy.can_see_internal_only_milestones()
    assert not policy.can_see_unpublished_calendar()
    assert not policy.can_see_unreleased_creative_concepts()
    assert not policy.can_see_internal_campaign_strategy_notes()
    assert not policy.is_founder


def test_product_owner_and_marketing_get_full_strategic_access() -> None:
    for role in (BusinessContextRole.PRODUCT_OWNER, BusinessContextRole.MARKETING):
        policy = DirectorConsoleAccessPolicy(role=role)
        assert policy.can_see_founder_directive_text()
        assert policy.can_see_restricted_claims()
        assert policy.can_see_embargo_details()
        assert policy.can_see_unpublished_calendar()


def test_editor_gets_operational_access_only() -> None:
    policy = DirectorConsoleAccessPolicy(role=BusinessContextRole.EDITOR)
    assert policy.can_see_unpublished_calendar()
    assert policy.can_see_unreleased_creative_concepts()
    assert not policy.can_see_founder_directive_text()
    assert not policy.can_see_restricted_claims()
    assert not policy.can_see_embargo_details()
    assert not policy.can_see_tentative_launch_dates()
