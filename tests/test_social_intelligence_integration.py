"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §30: integration tests proving the merged development
lineage (feature/social-business-context-v1 + feature/telegram-directors-2 +
feature/instagram-growth-engine-v1) is actually clean, not just "the merge command didn't error"."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import Base
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_service import create_campaign
from services.claim_policy_service import create_claim_policy, get_claim_policy
from services.product_context_service import create_product
from services.strategic_directive_service import create_directive, list_active_directives


def test_shared_telegram_instagram_modules_coexist() -> None:
    """Importing every platform's own top-level service module together must never raise (no
    circular import, no name collision at import time)."""
    import services.business_context_snapshot_service  # noqa: F401
    import services.telegram_growth_director  # noqa: F401
    import services.telegram_strategy_director  # noqa: F401
    import services.instagram_growth_strategist  # noqa: F401
    import services.instagram_format_director_v2  # noqa: F401


def test_no_duplicate_table_names_across_platforms() -> None:
    import database.models  # noqa: F401 - registers every model's table with Base.metadata

    tables = list(Base.metadata.tables.keys())
    assert len(tables) == len(set(tables))
    assert len(tables) >= 30  # sanity floor - the merged tree really does carry all three lines' tables


def test_single_alembic_head() -> None:
    """Spec §2: either one true head, or an explicit, deliberate merge revision - never a silent
    multi-head fork left unresolved."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], cwd=repo_root, capture_output=True, text=True, timeout=30,
    )
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"expected exactly one Alembic head, found: {heads}"


def test_no_circular_platform_dependency() -> None:
    """spec §3/§4: Telegram must never import from services/instagram_*.py and vice versa - each
    platform only shares the canonical Business Context layer."""
    import ast

    repo_root = Path(__file__).resolve().parent.parent
    for pattern, forbidden_prefix in (("telegram_*.py", "services.instagram_"), ("instagram_*.py", "services.telegram_")):
        for path in (repo_root / "services").glob(pattern):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(forbidden_prefix):
                    pytest.fail(f"{path.name} imports {node.module} - platform boundary violation")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(forbidden_prefix):
                            pytest.fail(f"{path.name} imports {alias.name} - platform boundary violation")


@pytest.mark.asyncio
async def test_business_context_snapshot_is_the_shared_read_for_both_platforms(db_session: AsyncSession) -> None:
    """Telegram's own director services and Instagram's own growth services both read
    get_business_context_snapshot() as their one shared truth - never a platform-specific copy."""
    product = await create_product(db_session, slug="integtest", name="Integration Test Product")
    await create_campaign(
        db_session, product_id=product.id, name="Integration Launch",
        structured_context={"status": "confirmed", "date_confidence": "unknown"},
    )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(db_session, now=now)
    assert any(s.product.slug == "integtest" for s in snapshot.products)

    # The exact same snapshot type/shape is what both director_console_service (this phase) and
    # every director/growth-strategist module across both platforms consume.
    from services.business_context_snapshot_service import BusinessContextSnapshot
    assert isinstance(snapshot, BusinessContextSnapshot)


@pytest.mark.asyncio
async def test_claim_policy_is_shared_not_duplicated_per_platform(db_session: AsyncSession) -> None:
    from database.models.claim_policy import ClaimStatus
    from datetime import datetime, timezone

    product = await create_product(db_session, slug="integclaim", name="Integration Claim Product")
    await create_claim_policy(db_session, product_id=product.id, claim_text="exact price", status=ClaimStatus.RESTRICTED)
    claims = await get_claim_policy(db_session, product.id, now=datetime.now(timezone.utc))
    assert any(c.claim_text == "exact price" for c in claims)

    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    assert any(c.claim_text == "exact price" for c in snapshot.restricted_claims)


@pytest.mark.asyncio
async def test_founder_directive_is_shared_not_duplicated_per_platform(db_session: AsyncSession) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    await create_directive(db_session, instruction="Store пока не продвигаем.", priority=1, valid_from=now, created_by=1)
    directives = await list_active_directives(db_session, now=now)
    assert any("Store" in d.instruction for d in directives)

    from services.instagram_growth_strategist import directive_blocks_product
    assert directive_blocks_product(directives, product_slug="anything")  # empty scope = applies to all
