"""VISUAL-SPEC-V2-ACTIVATION-1 - apply the Founder-approved telegram_news v2 / telegram_breaking v2
Design Specs through the canonical registry lifecycle.

Founder decision (VISUAL-SPEC-V2-ACTIVATION-1): APPROVE telegram_news v2 + telegram_breaking v2.
The ONLY approved semantic change from v1 is: REMOVE placement_zone=lower_left. No other value
changes.

This script is idempotent and replayable against ANY database (the local dev DB now; the
production control-plane DB in a later, explicitly-authorized deploy phase):
  1. ensure each scope has an ACTIVE v1 with the exact Founder-approved v1 values (bootstrap a
     dev DB that has none; on a DB that already has v1 ACTIVE it only VERIFIES, never rewrites);
  2. STOP if any existing v1 value other than `placement_zone` differs from the v2 target;
  3. create the v2 CANDIDATE via `create_candidate_spec()` (placement_zone removed, everything
     else identical) - skipped if a v2 CANDIDATE/ACTIVE already exists;
  4. `promote_candidate()` the v2 - the canonical lifecycle marks v1 SUPERSEDED, never edited in
     place.
telegram_data / telegram_quote are seeded ACTIVE for local matrix verification but get NO v2.
No RECAP spec. No Instagram spec. No deploy. No public send.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecStatus, DesignSpecType, DesignSpecVersion
from database.session import async_session_factory
from services.design_spec_registry import (
    create_candidate_spec,
    get_active_spec,
    list_history,
    promote_candidate,
)

# Exact Founder-approved v1 parameter sets (DESIGN-SPEC-ACTIVATION-1).
_V1: dict[str, dict] = {
    "telegram_news": {
        "safe_margin_frac": 0.019, "placement_zone": "lower_left", "logo_zone": "lower_right",
        "scrim_treatment": "none", "source_image_treatment": "preserve",
    },
    "telegram_breaking": {
        "safe_margin_frac": 0.019, "placement_zone": "lower_left", "logo_zone": "lower_right",
        "scrim_treatment": "none", "source_image_treatment": "preserve",
    },
    "telegram_data": {
        "font_size_max": 88, "font_size_min": 48, "max_line_count": 2, "safe_margin_frac": 0.019,
        "logo_zone": "lower_right", "scrim_treatment": "none", "source_image_treatment": "preserve",
    },
    "telegram_quote": {
        "safe_margin_frac": 0.019, "logo_zone": "lower_right", "scrim_treatment": "none",
        "source_image_treatment": "preserve",
    },
}

# The ONLY approved change: placement_zone removed. Everything else byte-identical to v1.
_V2_SCOPES = ("telegram_news", "telegram_breaking")
_FOUNDER_APPROVAL_NOTE = (
    "v2 - Founder-approved (VISUAL-SPEC-V2-ACTIVATION-1). Sole semantic change vs v1: "
    "placement_zone=lower_left REMOVED (wrongly derived from the superseded render_news_hero note; "
    "the pulse is fused into the single lower-right MASTER NEWS signature - see "
    "design/proposed_telegram_news_breaking_v2_candidates.md and VISUAL-RENDERER-RECONCILIATION-1 "
    "§1/§3 case B). All other values unchanged."
)
_FOUNDER_CREATED_BY = 0  # 0 = "Founder / operator console" sentinel (no numeric Founder user row)


def _v2_params(scope: str) -> dict:
    return {k: v for k, v in _V1[scope].items() if k != "placement_zone"}


async def _ensure_v1_active(session: AsyncSession, scope: str, *, seed: bool) -> DesignSpecVersion:
    active = await get_active_spec(session, scope)
    if active is not None:
        return active
    if not seed:
        raise SystemExit(f"STOP: no ACTIVE spec for {scope!r} and --no-seed-v1 was given.")
    cand = await create_candidate_spec(
        session, scope=scope, spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        platform="telegram", surface="channel",
        presentation_type=scope.split("_", 1)[1].upper(),
        parameters=_V1[scope], created_by=_FOUNDER_CREATED_BY,
        notes="v1 - Founder-approved (DESIGN-SPEC-ACTIVATION-1). Seeded here for canonical-lifecycle replay.",
    )
    return await promote_candidate(session, cand.id)


def _stop_if_v1_diverges(scope: str, active_params: dict) -> None:
    target = _v2_params(scope)
    for key, want in target.items():
        got = active_params.get(key)
        if got != want:
            raise SystemExit(
                f"STOP (VISUAL-SPEC-V2-ACTIVATION-1 §1): {scope} v1 has {key}={got!r}, "
                f"expected {want!r}. Only placement_zone may differ between v1 and v2."
            )
    extra = set(active_params) - set(target) - {"placement_zone"}
    if extra:
        raise SystemExit(
            f"STOP (VISUAL-SPEC-V2-ACTIVATION-1 §1): {scope} v1 declares unexpected extra "
            f"parameter(s) {sorted(extra)} - the ONLY approved change is removing placement_zone."
        )


async def activate(*, seed_v1: bool, dry_run: bool) -> dict:
    report: dict = {"seed_v1": seed_v1, "dry_run": dry_run, "scopes": {}}
    async with async_session_factory() as session:
        # seed data/quote ACTIVE too (matrix verification), no v2 for them
        for scope in ("telegram_data", "telegram_quote"):
            await _ensure_v1_active(session, scope, seed=seed_v1)

        for scope in _V2_SCOPES:
            await _ensure_v1_active(session, scope, seed=seed_v1)
            history = await list_history(session, scope)
            # the true v1 row = the one still declaring placement_zone (ACTIVE before promotion,
            # SUPERSEDED after) - not just get_active_spec(), which returns v2 once promoted.
            v1_row = next(s for s in history if "placement_zone" in (s.parameters or {}))
            _stop_if_v1_diverges(scope, dict(v1_row.parameters or {}))

            existing_v2 = next(
                (s for s in history
                 if s.status in (DesignSpecStatus.CANDIDATE, DesignSpecStatus.ACTIVE)
                 and "placement_zone" not in (s.parameters or {})),
                None,
            )
            if existing_v2 is None:
                v2 = await create_candidate_spec(
                    session, scope=scope, spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
                    platform="telegram", surface="channel",
                    presentation_type=scope.split("_", 1)[1].upper(),
                    parameters=_v2_params(scope), created_by=_FOUNDER_CREATED_BY,
                    notes=_FOUNDER_APPROVAL_NOTE,
                )
            else:
                v2 = existing_v2

            if v2.status is DesignSpecStatus.CANDIDATE and not dry_run:
                v2 = await promote_candidate(session, v2.id)

            await session.refresh(v1_row)
            report["scopes"][scope] = {
                "v1_id": str(v1_row.id), "v1_version": v1_row.version, "v1_status": v1_row.status.value,
                "v2_id": str(v2.id), "v2_version": v2.version, "v2_status": v2.status.value,
                "v2_params": v2.parameters, "v1_params": v1_row.parameters,
            }

        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-seed-v1", action="store_true", help="fail instead of bootstrapping a missing v1 ACTIVE")
    ap.add_argument("--dry-run", action="store_true", help="roll back; create no rows, promote nothing")
    args = ap.parse_args()
    result = asyncio.run(activate(seed_v1=not args.no_seed_v1, dry_run=args.dry_run))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
