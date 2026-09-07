"""DIRECTOR-CONTROL-PLANE-1 §17-18: DesignReferenceAsset registry, plus `import_known_manifests()`
- the real, forensic import of this project's ALREADY-EXISTING approved/rejected classification
data (assets/brand/newsroom_visuals/v1/manifests/overlays.yaml,
assets/brand/newsroom_visuals/v1/references/data/data_template_manifest.json) rather than
re-deriving or guessing approval status (spec §18's own "do not silently ignore old approved
boards", spec §29's own "do not auto-label as approved" - both satisfied together here because the
classification is READ from the project's own prior, real decisions, never invented fresh).

Everything under assets/brand/newsroom_visuals/ this function does NOT find an explicit approval/
rejection signal for lands as NEEDS_FOUNDER_REVIEW - see this phase's own design/reference_manifest
report for the full accounting."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_reference_asset import DesignReferenceAsset, DesignReferenceRole

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OVERLAYS_MANIFEST = _REPO_ROOT / "assets/brand/newsroom_visuals/v1/manifests/overlays.yaml"
_DATA_MANIFEST = _REPO_ROOT / "assets/brand/newsroom_visuals/v1/references/data/data_template_manifest.json"
_REFERENCES_DIR = _REPO_ROOT / "assets/brand/newsroom_visuals/v1/references"
_OVERLAYS_DIR = _REPO_ROOT / "assets/brand/newsroom_visuals/v1/overlays"

# Spec §22 (master prototype) - the manifest's own documented "design-authority hierarchy, highest
# first" names this file explicitly as rank 1, above even the approved overlay assets.
_MASTER_PROTOTYPE = "assets/brand/newsroom_visuals/v1/references/nnj_editorial_visual_system_master_prototype.png"


async def upsert_asset(
    session: AsyncSession, *, asset_path: str, reference_role: DesignReferenceRole,
    platform: str | None = None, presentation_type: str | None = None, notes: str | None = None,
    source: str | None = None,
) -> DesignReferenceAsset:
    stmt = select(DesignReferenceAsset).where(DesignReferenceAsset.asset_path == asset_path)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.reference_role = reference_role
        existing.platform = platform
        existing.presentation_type = presentation_type
        existing.notes = notes
        existing.source = source
        await session.flush()
        return existing
    asset = DesignReferenceAsset(
        asset_path=asset_path, reference_role=reference_role, platform=platform,
        presentation_type=presentation_type, notes=notes, source=source,
    )
    session.add(asset)
    await session.flush()
    return asset


async def list_assets(
    session: AsyncSession, *, reference_role: DesignReferenceRole | None = None,
    presentation_type: str | None = None,
) -> list[DesignReferenceAsset]:
    stmt = select(DesignReferenceAsset)
    if reference_role is not None:
        stmt = stmt.where(DesignReferenceAsset.reference_role == reference_role)
    if presentation_type is not None:
        stmt = stmt.where(DesignReferenceAsset.presentation_type == presentation_type)
    return list((await session.execute(stmt)).scalars().all())


def _relpath(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def inventory_manifest_classifications() -> dict[str, dict]:
    """Pure, filesystem-only inventory (spec §18/§42) - no DB, no session, so it can be called from
    a plain report script or a test. Returns `{asset_path: {"role": ..., "notes": ..., "source": ...}}`
    for every asset this function can confidently classify from the project's own real manifests,
    PLUS a `"_unclassified"` key listing every real image file under assets/brand/newsroom_visuals/
    v1/ that neither manifest mentions at all (ambiguous, per spec §18's own explicit instruction:
    "For ambiguous assets: do not auto-label as approved. Create an explicit review-needed
    manifest.")."""
    classified: dict[str, dict] = {}
    known_paths: set[str] = set()

    classified[_relpath(_REPO_ROOT / _MASTER_PROTOTYPE)] = {
        "role": DesignReferenceRole.APPROVED_REFERENCE.value,
        "notes": "Canonical master prototype - highest design authority per the overlays manifest's own documented hierarchy.",
        "source": _relpath(_OVERLAYS_MANIFEST),
    }
    known_paths.add(_relpath(_REPO_ROOT / _MASTER_PROTOTYPE))

    if _DATA_MANIFEST.is_file():
        data_manifest = json.loads(_DATA_MANIFEST.read_text(encoding="utf-8"))
        data_dir = _DATA_MANIFEST.parent
        for key in ("white_template", "red_template"):
            filename = data_manifest.get(key)
            if not filename:
                continue
            asset_path = _relpath(data_dir / filename)
            classified[asset_path] = {
                "role": DesignReferenceRole.APPROVED_REFERENCE.value,
                "notes": f"DATA reference template ({key}) - manifest states production_usage={data_manifest.get('production_usage')!r}.",
                "source": _relpath(_DATA_MANIFEST),
            }
            known_paths.add(asset_path)

    if _OVERLAYS_MANIFEST.is_file():
        overlays_manifest = yaml.safe_load(_OVERLAYS_MANIFEST.read_text(encoding="utf-8"))
        for entry in overlays_manifest.get("overlays", []):
            asset_path = _relpath(_REPO_ROOT / "assets/brand/newsroom_visuals/v1" / entry["path"])
            # The manifest's own explicit `production_approved: false` is the strongest, most
            # explicit rejection signal - honored first. Absent that key entirely, the manifest's
            # own preamble states `active: true` means "an approved design reference, not
            # rejected/superseded" - honored as APPROVED_REFERENCE (a design-direction approval,
            # never a literal-pixel-copy claim - spec §29's own distinction).
            if entry.get("production_approved") is False:
                role = DesignReferenceRole.REJECTED_REFERENCE
                notes = entry.get("notes", "").strip() or "Explicitly marked production_approved: false in the project's own overlay manifest."
            elif entry.get("active") is True:
                role = DesignReferenceRole.APPROVED_REFERENCE
                notes = entry.get("notes", "").strip() or "Design-direction reference, approved per the project's own overlay manifest."
            else:
                role = DesignReferenceRole.NEEDS_FOUNDER_REVIEW
                notes = "No explicit approval/rejection signal in the manifest entry itself."
            classified[asset_path] = {
                "role": role.value, "notes": notes, "source": _relpath(_OVERLAYS_MANIFEST),
                "presentation_type": entry.get("presentation_type"),
            }
            known_paths.add(asset_path)

    unclassified: list[str] = []
    for directory in (_REFERENCES_DIR, _OVERLAYS_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            rel = _relpath(path)
            if rel not in known_paths:
                unclassified.append(rel)

    classified["_unclassified"] = {"paths": unclassified}
    return classified


async def import_known_manifests(session: AsyncSession) -> dict[str, int]:
    """The real write path - persists `inventory_manifest_classifications()`'s output as
    DesignReferenceAsset rows (idempotent via upsert_asset()) and any unclassified real file as
    NEEDS_FOUNDER_REVIEW. Returns a small summary count dict for a caller/report to render."""
    inventory = inventory_manifest_classifications()
    counts = {"approved": 0, "rejected": 0, "needs_review": 0}

    for asset_path, meta in inventory.items():
        if asset_path == "_unclassified":
            continue
        role = DesignReferenceRole(meta["role"])
        await upsert_asset(
            session, asset_path=asset_path, reference_role=role,
            presentation_type=meta.get("presentation_type"), notes=meta.get("notes"), source=meta.get("source"),
        )
        if role == DesignReferenceRole.APPROVED_REFERENCE:
            counts["approved"] += 1
        elif role == DesignReferenceRole.REJECTED_REFERENCE:
            counts["rejected"] += 1
        else:
            counts["needs_review"] += 1

    for asset_path in inventory["_unclassified"]["paths"]:
        await upsert_asset(
            session, asset_path=asset_path, reference_role=DesignReferenceRole.NEEDS_FOUNDER_REVIEW,
            notes="Not mentioned in any known project manifest - ambiguous, never auto-approved.",
            source="filesystem_scan",
        )
        counts["needs_review"] += 1

    return counts
