"""VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1 §4/§5 - the phase's spec-semantics corrections, as
CANDIDATE rows only (never promoted), idempotently.

Founder decisions applied:

  * ADAPTIVE LOGO PLACEMENT - NEWS / BREAKING use select_master_news_branding(), which chooses
    ONE canonical NNJ mark among four bounded safe corners per photo. Declaring a constant
    `logo_zone=lower_right` is a falsification. `DeclarativeVisualParameters.logo_zone` is
    OPTIONAL and `_zone_check()` skips the comparison when it is absent, so OMITTING it is the
    truthful, schema-supported representation of adaptive placement (no schema change, no
    migration). -> telegram_news v3 / telegram_breaking v3 drop `logo_zone`.

  * DATA is source-dependent - the generated HERO card (metric upper-left, fixed lower_right
    mark, no scrim) and the source-preserving MINIMAL mode (adaptive bottom signature, occasional
    guaranteed-branding fallback scrim, may crop a non-16:9 source) genuinely differ on
    placement_zone / logo_zone / scrim_treatment / source_image_treatment. A single field-by-field
    spec that declared hero-only values would lie about the infographic render. -> telegram_data
    v3 keeps only what is true for BOTH modes: font range (hero-only, skipped by MINIMAL),
    max_line_count, safe_margin_frac. SOURCE_PRESERVATION + the always-on single-NNJ
    (logo_count>1) hard check still govern the infographic path.

  * QUOTE places its one mark deterministically lower_right (not adaptive) -> telegram_quote v2
    (from scripts/propose_visual_spec_vnext_candidates.py) already declares logo_zone truthfully
    and is unchanged here.

The earlier telegram_data v2 candidate (hero-only placement_zone/logo_zone/scrim) is REJECTED
with a reason (never deleted).

NOT PROMOTED. Applied to whatever `async_session_factory` points at (dev control-plane DB here;
production is out of scope - a later authorized rollout replays this after a backup).

    python scripts/propose_visual_spec_adaptive_candidates.py [--dry-run]
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
from services.design_spec_registry import (
    create_candidate_spec,
    list_history,
    reject_candidate,
)

_TAG = "VNEXT-PROD-ALIGN-1"
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
}
_NOTES: dict[str, str] = {
    "telegram_news": f"{_TAG}: adaptive safe logo placement (no logo_zone); RenderEvidence reports the actual zone. Otherwise identical to Founder-approved v2. Not promoted.",
    "telegram_breaking": f"{_TAG}: adaptive safe logo placement (no logo_zone); band/wordmark stay retired. Otherwise identical to Founder-approved v2. Not promoted.",
    "telegram_data": f"{_TAG}: truthful for BOTH the hero-metric and the source-preserving MINIMAL render - no placement_zone/logo_zone/scrim_treatment (they differ by mode). font 88-200 is hero-only. Not promoted.",
}
_LIVE = {DesignSpecStatus.CANDIDATE, DesignSpecStatus.ACTIVE, DesignSpecStatus.FROZEN}
_SUPERSEDED_PREFIXES = (
    "vNEXT CANDIDATE (FOUNDER-VISUAL-BOARD-ALIGNMENT-1",
    "vNEXT-ADAPTIVE CANDIDATE (VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1",
)


async def _run(session: AsyncSession, *, dry_run: bool) -> None:
    for scope, params in _TARGET.items():
        history = await list_history(session, scope)
        next_version = max((h.version for h in history), default=0) + 1

        already = [
            h
            for h in history
            if h.status in _LIVE and dict(h.parameters or {}) == params
        ]
        if already:
            print(
                f"[skip] {scope}: target candidate already exists (v{already[0].version}, {already[0].status.value})"
            )
            continue

        for h in history:
            if (
                h.status is DesignSpecStatus.CANDIDATE
                and (h.notes or "").startswith(_SUPERSEDED_PREFIXES)
                and dict(h.parameters or {}) != params
            ):
                if dry_run:
                    print(
                        f"[dry-run] {scope}: would REJECT superseded candidate v{h.version} params={dict(h.parameters or {})}"
                    )
                else:
                    await reject_candidate(
                        session,
                        h.id,
                        reason=f"{_TAG}: superseded by the truthful production-alignment candidate",
                    )
                    print(f"[rejected] {scope}: v{h.version} (superseded)")

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
