"""VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1 - promote the truthful Founder-approved vNEXT visual
specs through the canonical registry lifecycle.

    telegram_news     -> v3 ({safe_margin_frac, scrim_treatment:none, source_image_treatment:preserve})
    telegram_breaking -> v3 (same)
    telegram_data     -> v3 ({font_size_max:200, font_size_min:88, max_line_count:2, safe_margin_frac})
    telegram_quote    -> v2 ({safe_margin_frac, logo_zone:lower_right, scrim_treatment:none, source_image_treatment:preserve})

PREPARED, NOT RUN by this phase. It is idempotent and replayable against ANY database:
  1. verify a CANDIDATE row with EXACTLY the target parameters exists for the scope (created by
     scripts/propose_visual_spec_adaptive_candidates.py + scripts/propose_visual_spec_vnext_candidates.py);
     STOP if absent or if its params differ from the target;
  2. `promote_candidate()` it - the lifecycle marks the prior ACTIVE SUPERSEDED, never edited/deleted;
  3. re-assert exactly one ACTIVE spec per scope afterwards.

`--dry-run` rolls the transaction back (promotes nothing). Rollback after a real run: re-promote
the prior version (a fresh CANDIDATE cloned from the SUPERSEDED row, then promote) - see
`--print-rollback`.

Story Continuity is NOT touched: this only writes `design_spec_versions` rows.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecStatus
from database.session import async_session_factory
from services.design_spec_registry import (
    get_active_spec,
    list_history,
    promote_candidate,
)

_TARGET: dict[str, dict] = {
    "telegram_news": {
        "safe_margin_frac": 0.019,
        "scrim_treatment": "none",
        "source_image_treatment": "preserve",
    },
    "telegram_breaking": {
        "safe_margin_frac": 0.019,
        "scrim_treatment": "none",
        "source_image_treatment": "preserve",
    },
    "telegram_data": {
        "font_size_max": 200,
        "font_size_min": 88,
        "max_line_count": 2,
        "safe_margin_frac": 0.019,
    },
    "telegram_quote": {
        "safe_margin_frac": 0.019,
        "logo_zone": "lower_right",
        "scrim_treatment": "none",
        "source_image_treatment": "preserve",
    },
}


async def _activate(session: AsyncSession, *, dry_run: bool) -> list[str]:
    log: list[str] = []
    for scope, params in _TARGET.items():
        history = await list_history(session, scope)
        active = await get_active_spec(session, scope)
        if active is not None and dict(active.parameters or {}) == params:
            log.append(
                f"[ok] {scope}: target already ACTIVE (v{active.version}) - nothing to do"
            )
            continue
        candidates = [
            h
            for h in history
            if h.status is DesignSpecStatus.CANDIDATE
            and dict(h.parameters or {}) == params
        ]
        if not candidates:
            raise SystemExit(
                f"STOP: {scope} has no CANDIDATE row matching the target params {params}. "
                f"Run the propose scripts against this DB first."
            )
        cand = max(candidates, key=lambda h: h.version)
        if dry_run:
            log.append(
                f"[dry-run] {scope}: would promote CANDIDATE v{cand.version} -> ACTIVE (v{active.version if active else '-'} -> SUPERSEDED)"
            )
            continue
        promoted = await promote_candidate(session, cand.id)
        log.append(f"[promoted] {scope}: v{promoted.version} ACTIVE")

    # invariant re-assertion
    for scope in _TARGET:
        actives = [
            h
            for h in await list_history(session, scope)
            if h.status in (DesignSpecStatus.ACTIVE, DesignSpecStatus.FROZEN)
        ]
        if len(actives) != 1:
            raise SystemExit(
                f"STOP: {scope} has {len(actives)} ACTIVE/FROZEN specs after activation (expected exactly 1)"
            )
        log.append(f"[invariant] {scope}: ACTIVE_COUNT=1 (v{actives[0].version})")
    return log


async def _print_rollback(session: AsyncSession) -> None:
    for scope in _TARGET:
        history = sorted(await list_history(session, scope), key=lambda h: h.version)
        superseded = [h for h in history if h.status is DesignSpecStatus.SUPERSEDED]
        prior = superseded[-1] if superseded else None
        if prior is None:
            print(
                f"  {scope}: no SUPERSEDED prior version recorded - rollback would re-create v1 from its params"
            )
        else:
            print(
                f"  {scope}: rollback -> clone v{prior.version} params {dict(prior.parameters or {})} to a fresh CANDIDATE, then promote_candidate()"
            )


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="roll back; promote nothing")
    ap.add_argument(
        "--print-rollback",
        action="store_true",
        help="print the exact rollback operation and exit",
    )
    args = ap.parse_args()

    async with async_session_factory() as session:
        if args.print_rollback:
            await _print_rollback(session)
            return
        log = await _activate(session, dry_run=args.dry_run)
        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()
    for line in log:
        print(line)
    print(
        "DRY RUN - rolled back, nothing changed."
        if args.dry_run
        else "ACTIVATION COMMITTED."
    )


if __name__ == "__main__":
    asyncio.run(main())
