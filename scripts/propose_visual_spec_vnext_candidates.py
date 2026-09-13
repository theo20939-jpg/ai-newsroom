"""FOUNDER-VISUAL-BOARD-ALIGNMENT-1 - create the telegram_quote vNEXT CANDIDATE Design Spec
(see design/proposed_telegram_data_quote_vnext_candidates.md).

NOTE: the telegram_data vNEXT candidate this script originally also created carried hero-only
placement/logo/scrim fields that lie about the source-preserving MINIMAL render. It was
superseded by the truthful telegram_data v3 in
`scripts/propose_visual_spec_adaptive_candidates.py` (VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1)
and is no longer created here.

CANDIDATE ONLY. This script NEVER calls promote_candidate(). It is idempotent: on a DB that
already has a vNEXT CANDIDATE (or a later ACTIVE) for a scope it does nothing for that scope.
Applied to whatever database `async_session_factory` points at - the local dev control-plane DB
here; production is out of scope for this phase.

    python scripts/propose_visual_spec_vnext_candidates.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecStatus, DesignSpecType
from database.session import async_session_factory
from services.design_spec_registry import create_candidate_spec, list_history

_CANDIDATES: dict[str, dict] = {
    "telegram_quote": {
        "safe_margin_frac": 0.019,
        "logo_zone": "lower_right",
        "scrim_treatment": "none",
        "source_image_treatment": "preserve",
    },
}

_NOTES: dict[str, str] = {
    "telegram_data": (
        "vNEXT CANDIDATE (FOUNDER-VISUAL-BOARD-ALIGNMENT-1, board format 3): generated DATA "
        "hero-metric card - dominant primary number, unit in NNJ red, grey secondary line, "
        "optional red delta pill + trend line (plotted verbatim from a supplied series), "
        "technical grid, one NNJ mark. source_image_treatment removed (no source photo). "
        "EXISTING_INFOGRAPHIC still routes to MINIMAL_SOURCE_PRESERVING under v1 semantics. "
        "Not promoted - Founder review required."
    ),
    "telegram_quote": (
        "vNEXT CANDIDATE (FOUNDER-VISUAL-BOARD-ALIGNMENT-1, board format 4): large red "
        "quote-mark motif, dominant verbatim quote body, portrait on the supporting right strip, "
        "author name in NNJ red, author role in smaller grey (only when supplied). PULSE/QUOTE "
        "label + NP-xxxx code no longer baked into the media. Parameters byte-identical to v1. "
        "Not promoted - Founder review required."
    ),
}

_LIVE_STATUSES = {
    DesignSpecStatus.CANDIDATE,
    DesignSpecStatus.ACTIVE,
    DesignSpecStatus.FROZEN,
}


async def _run(session: AsyncSession, *, dry_run: bool) -> None:
    for scope, params in _CANDIDATES.items():
        history = await list_history(session, scope)
        versions = [h.version for h in history]
        next_version = (max(versions, default=0)) + 1
        already = [
            h
            for h in history
            if h.version >= 2
            and h.status in _LIVE_STATUSES
            and (h.notes or "").startswith(
                "vNEXT CANDIDATE (FOUNDER-VISUAL-BOARD-ALIGNMENT-1"
            )
        ]
        if already:
            print(
                f"[skip] {scope}: vNEXT candidate already exists (v{already[0].version}, {already[0].status.value})"
            )
            continue
        if dry_run:
            print(
                f"[dry-run] {scope}: would create CANDIDATE v{next_version} params={params}"
            )
            continue
        cand = await create_candidate_spec(
            session,
            scope=scope,
            spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
            parameters=params,
            notes=_NOTES[scope],
        )
        print(f"[created] {scope}: CANDIDATE v{cand.version} id={cand.id}")
    if not dry_run:
        await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    async with async_session_factory() as session:
        await _run(session, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
