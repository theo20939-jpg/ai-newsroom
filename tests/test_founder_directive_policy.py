"""SOCIAL-INTELLIGENCE-OPS-1, spec §19/§60: shared Founder Directive policy tests - the same
function services/instagram_growth_strategist.py and services/story_campaign_matcher.py both use."""
from __future__ import annotations

from datetime import datetime, timezone

from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from services.founder_directive_policy import directive_blocks_product


def _directive(**overrides: object) -> StrategicDirective:
    defaults: dict[str, object] = dict(
        priority=10, valid_from=datetime.now(timezone.utc), instruction="Store пока не продвигаем.",
        products=["store"], platforms=[], status=DirectiveStatus.ACTIVE,
    )
    defaults.update(overrides)
    return StrategicDirective(**defaults)  # type: ignore[arg-type]


def test_scoped_directive_blocks_only_named_product() -> None:
    directives = [_directive(products=["store"])]
    assert directive_blocks_product(directives, product_slug="store")
    assert not directive_blocks_product(directives, product_slug="vpn")


def test_empty_scope_blocks_everything() -> None:
    directives = [_directive(products=[], platforms=[])]
    assert directive_blocks_product(directives, product_slug="anything")


def test_inactive_directive_does_not_block() -> None:
    directives = [_directive(status=DirectiveStatus.SUPERSEDED)]
    assert not directive_blocks_product(directives, product_slug="store")


def test_platform_scope_is_respected() -> None:
    directives = [_directive(products=["store"], platforms=["telegram"])]
    assert directive_blocks_product(directives, product_slug="store", platform="telegram")
    assert not directive_blocks_product(directives, product_slug="store", platform="instagram")
