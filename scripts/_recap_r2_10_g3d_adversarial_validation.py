"""R2.10G3-D - expanded adversarial validation of the frozen G3-B deterministic eventness
rejector (RULE_A / RULE_C / RULE_D / RULE_COMBINED - imported UNCHANGED, never tuned here, per
this phase's own §4/§5 "freeze the rules" instruction).

Read-only, deterministic-only (no LLM by default - §33 "Default: LLM_CALLS=0"). Reuses:
  - `evaluate_db_fixture()`/`evaluate_offline_fixture()`/`DeterministicFeatures`/`EventnessEvaluation`
    from scripts/_recap_r2_10_g3_eventness_harness.py (G3-A, frozen) - unmodified.
  - `RULE_A`/`RULE_C`/`RULE_D`/`RULE_COMBINED` from scripts/_recap_r2_10_g3_eventness_calibrate.py
    (G3-B, frozen) - unmodified, no new clause/threshold/whitelist/blacklist added here.
  - The G3-A calibration MANIFEST and G3-B HOLDOUT, for regression-continuity controls (§17) and
    for the combined-corpus dataset-expansion accounting (§28).

SAFE BY DEFAULT:
  - Never writes to the database (read-only transaction, verified - `_verify_read_only()`
    duplicated from the sibling scripts' own identically-behaved helper, per this codebase's own
    established per-script-private-helper convention).
  - No Gateway import anywhere on the default code path (verified structurally by this module's
    own test suite, test_no_gateway_import_on_default_path).
  - Never touches Telegram, never touches a worker, never publishes anything.

Run (deterministic only, the only mode this script's own CLI entry point exercises):
    docker compose run --rm --no-deps backend python scripts/_recap_r2_10_g3d_adversarial_validation.py

NOT executed against any production database or production Gateway config - developer/local DB
only, per this phase's own explicit safety boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from scripts._recap_r2_10_g3_eventness_calibrate import (  # noqa: E402
    RULE_A,
    RULE_C,
    RULE_D,
    RULE_COMBINED,
    RuleVerdict,
)
from scripts._recap_r2_10_g3_eventness_harness import (  # noqa: E402
    DeterministicFeatures,
    EventnessEvaluation,
    evaluate_db_fixture,
    evaluate_offline_fixture,
)
from scripts._recap_r2_10_g3_eventness_holdout import HOLDOUT, HoldoutEntry  # noqa: E402
from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST, ManifestEntry  # noqa: E402
from scripts._recap_r2_10_g3d_adversarial_manifest import (  # noqa: E402
    ADVERSARIAL_MANIFEST,
    AdversarialEntry,
    used_story_ids_overlap_with_prior_sets,
)

STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_OUTPUT_ROOT = Path("/tmp/r2_10_g3d_adversarial_runs")

# §17 - run for regression continuity, EXCLUDED from new-validation statistics.
CONTROL_FIXTURE_IDS: tuple[str, ...] = (
    "vla", "vlm", "nvidia_hf_main", "vk_apple_synthetic_4publisher_false_ready", "marvell_google",
    "ciflow_ci_noise", "holdout_pentagon_grok",
)


class ReadOnlyGuardError(RuntimeError):
    """Duplicated from the sibling G3 scripts' own identically-named, identically-behaved guard."""


async def _verify_read_only(conn) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


def _adversarial_as_manifest_entry(e: AdversarialEntry) -> ManifestEntry:
    """Adapter reusing evaluate_db_fixture() unchanged - AMBIGUOUS maps to UNCERTAIN, the same
    value UNCLEAR-class G3-A/G3-B fixtures already use, since ManifestEntry's own vocabulary has
    no separate AMBIGUOUS value."""
    desired = "UNCERTAIN" if e.desired_eventness == "AMBIGUOUS" else e.desired_eventness
    return ManifestEntry(
        fixture_id=e.fixture_id, kind="db", story_id=e.story_id, title_snapshot=e.title_snapshot,
        manual_class=e.manual_class, desired_eventness=desired, confidence="high",
        source_phase="R2.10G3-D", rationale=e.rationale,
    )


def _holdout_as_manifest_entry(h: HoldoutEntry) -> ManifestEntry:
    """Duplicated from scripts/_recap_r2_10_g3_eventness_calibrate.py's own identically-named,
    identically-behaved private adapter (that function is module-private there - per this
    codebase's own established per-script-private-helper convention, duplicated rather than
    imported across script files, matching G3-C's own identical precedent)."""
    return ManifestEntry(
        fixture_id=h.fixture_id, kind="db", story_id=h.story_id, title_snapshot=h.title_snapshot,
        manual_class=h.manual_class, desired_eventness=h.desired_eventness, confidence="high",
        source_phase="R2.10G3-B holdout", rationale=h.rationale,
    )


def _lookup_control_entry(fixture_id: str) -> ManifestEntry:
    for entry in MANIFEST:
        if entry.fixture_id == fixture_id:
            return entry
    for h in HOLDOUT:
        if h.fixture_id == fixture_id:
            return _holdout_as_manifest_entry(h)
    raise KeyError(f"control fixture_id {fixture_id!r} not found in MANIFEST or HOLDOUT")


@dataclass(frozen=True)
class G3DRecord:
    fixture_id: str
    group: Literal["NEW_VALIDATION", "CONTROL"]
    manual_class: str
    desired_eventness: str  # ACCEPT | REJECT | UNCERTAIN
    subtype: str | None
    story_id: str | None
    existing_readiness_state: str | None
    features: DeterministicFeatures | None
    A_triggered: bool | None
    C_triggered: bool | None
    D_triggered: bool | None
    combined_result: RuleVerdict | None
    skipped_reason: str | None


async def collect_records(*, now: datetime) -> list[G3DRecord]:
    """The one entry point tests/other callers should use. Read-only: opens one connection, one
    transaction, verified read-only, rolled back - never commits."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    records: list[G3DRecord] = []
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            for entry in ADVERSARIAL_MANIFEST:
                manifest_entry = _adversarial_as_manifest_entry(entry)
                evaluation = await evaluate_db_fixture(session, manifest_entry, now=now)
                records.append(_to_record(evaluation, group="NEW_VALIDATION", subtype=entry.subtype))

            for fixture_id in CONTROL_FIXTURE_IDS:
                control_entry = _lookup_control_entry(fixture_id)
                if control_entry.kind == "db":
                    evaluation = await evaluate_db_fixture(session, control_entry, now=now)
                else:
                    evaluation = evaluate_offline_fixture(control_entry, now=now)
                records.append(_to_record(evaluation, group="CONTROL", subtype=None))
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()
    return records


def _to_record(evaluation: EventnessEvaluation, *, group: Literal["NEW_VALIDATION", "CONTROL"], subtype: str | None) -> G3DRecord:
    features = evaluation.features
    a = c = d = None
    combined: RuleVerdict | None = None
    if features is not None:
        a = RULE_A.fn(features) == "REJECT"
        c = RULE_C.fn(features) == "REJECT"
        d = RULE_D.fn(features) == "REJECT"
        combined = RULE_COMBINED.fn(features)
    desired = evaluation.desired_eventness
    desired = "AMBIGUOUS" if desired in ("UNCERTAIN", "NEEDS_REVIEW") else desired
    return G3DRecord(
        fixture_id=evaluation.fixture_id, group=group, manual_class=evaluation.manual_class,
        desired_eventness=desired, subtype=subtype, story_id=evaluation.story_id,
        existing_readiness_state=evaluation.existing_readiness_state, features=features,
        A_triggered=a, C_triggered=c, D_triggered=d, combined_result=combined,
        skipped_reason=evaluation.skipped_reason,
    )


# --- §15/§16 metrics ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleSafetyMetrics:
    rule_id: str
    false_rejects: int
    false_reject_ids: list[str]
    true_negative_rejects: int
    negatives_evaluated: int
    positives_evaluated: int
    negative_coverage: float
    positive_preservation: float


def _scored_new_validation(records: list[G3DRecord]) -> list[G3DRecord]:
    return [r for r in records if r.group == "NEW_VALIDATION" and r.skipped_reason is None and r.desired_eventness != "AMBIGUOUS"]


def measure_rule_safety(rule_id: str, triggered_attr: str, records: list[G3DRecord]) -> RuleSafetyMetrics:
    scored = _scored_new_validation(records)
    negatives = [r for r in scored if r.desired_eventness == "REJECT"]
    positives = [r for r in scored if r.desired_eventness == "ACCEPT"]
    tn = [r for r in negatives if getattr(r, triggered_attr) is True]
    fr = [r for r in positives if getattr(r, triggered_attr) is True]
    return RuleSafetyMetrics(
        rule_id=rule_id, false_rejects=len(fr), false_reject_ids=[r.fixture_id for r in fr],
        true_negative_rejects=len(tn), negatives_evaluated=len(negatives), positives_evaluated=len(positives),
        negative_coverage=round(len(tn) / len(negatives), 3) if negatives else 0.0,
        positive_preservation=round(1 - len(fr) / len(positives), 3) if positives else 1.0,
    )


def measure_combined_safety(records: list[G3DRecord]) -> RuleSafetyMetrics:
    scored = _scored_new_validation(records)
    negatives = [r for r in scored if r.desired_eventness == "REJECT"]
    positives = [r for r in scored if r.desired_eventness == "ACCEPT"]
    tn = [r for r in negatives if r.combined_result == "REJECT"]
    fr = [r for r in positives if r.combined_result == "REJECT"]
    return RuleSafetyMetrics(
        rule_id="COMBINED", false_rejects=len(fr), false_reject_ids=[r.fixture_id for r in fr],
        true_negative_rejects=len(tn), negatives_evaluated=len(negatives), positives_evaluated=len(positives),
        negative_coverage=round(len(tn) / len(negatives), 3) if negatives else 0.0,
        positive_preservation=round(1 - len(fr) / len(positives), 3) if positives else 1.0,
    )


def class_specific_rejection_rates(records: list[G3DRecord]) -> dict[str, dict[str, float | int]]:
    scored = _scored_new_validation(records)
    by_class: dict[str, list[G3DRecord]] = {}
    for r in scored:
        by_class.setdefault(r.manual_class, []).append(r)
    out: dict[str, dict[str, float | int]] = {}
    for cls, rows in by_class.items():
        n = len(rows)
        rejected = sum(1 for r in rows if r.combined_result == "REJECT")
        out[cls] = {"n": n, "combined_rejected": rejected, "combined_rejection_rate": round(rejected / n, 3) if n else 0.0}
    return out


def subtype_false_rejects(records: list[G3DRecord]) -> dict[str, list[str]]:
    """§16 - EVENT_LIFECYCLE_FALSE_REJECTS, SHORT_MULTI_SOURCE_REAL_FALSE_REJECTS,
    LONG_LIFECYCLE_FALSE_REJECTS, GITHUB_REAL_EVENT_FALSE_REJECTS - keyed by subtype, combined rule."""
    scored = _scored_new_validation(records)
    positives = [r for r in scored if r.desired_eventness == "ACCEPT"]
    out: dict[str, list[str]] = {}
    for r in positives:
        if r.combined_result == "REJECT" and r.subtype:
            out.setdefault(r.subtype, []).append(r.fixture_id)
    return out


# --- §25 production candidacy -------------------------------------------------------------------


def production_candidacy(rule_id: str, *, g3b_calibration_fr: int, g3b_holdout_fr: int, g3d_fr: int) -> str:
    """PRODUCTION_CANDIDATE only if zero false rejects in ALL THREE evaluation stages. Passing does
    not deploy it (§25's own explicit caveat, enforced by this phase's own STOP)."""
    if g3b_calibration_fr == 0 and g3b_holdout_fr == 0 and g3d_fr == 0:
        return "PRODUCTION_CANDIDATE"
    return "REJECTED"


# --- §27 current readiness simulation -------------------------------------------------------------


def current_readiness_simulation(records: list[G3DRecord]) -> dict[str, object]:
    scored = _scored_new_validation(records)
    ready_states = {"READY"}
    false_ready_before = [r for r in scored if r.desired_eventness == "REJECT" and r.existing_readiness_state in ready_states]
    false_ready_removed = [r for r in false_ready_before if r.combined_result == "REJECT"]
    manual_positives_rejected_before = [r for r in scored if r.desired_eventness == "ACCEPT" and r.existing_readiness_state not in ready_states]
    additional_damage = [r for r in manual_positives_rejected_before if r.combined_result == "REJECT"]
    return {
        "false_ready_before": len(false_ready_before), "false_ready_before_ids": [r.fixture_id for r in false_ready_before],
        "false_ready_removed_by_safe_rules": len(false_ready_removed), "false_ready_removed_ids": [r.fixture_id for r in false_ready_removed],
        "manual_positives_rejected_before": len(manual_positives_rejected_before),
        "additional_positive_damage": len(additional_damage), "additional_positive_damage_ids": [r.fixture_id for r in additional_damage],
    }


# --- §28/§29 dataset expansion + consolidated manifest index --------------------------------------


def dataset_expansion_summary() -> dict[str, object]:
    g3a_db_ids = {e.story_id for e in MANIFEST if e.kind == "db" and e.story_id}
    g3a_offline_count = sum(1 for e in MANIFEST if e.kind == "offline")
    g3b_holdout_ids = {h.story_id for h in HOLDOUT}
    g3d_ids = {e.story_id for e in ADVERSARIAL_MANIFEST}
    all_db_ids = g3a_db_ids | g3b_holdout_ids | g3d_ids
    return {
        "g3a_calibration_db": len(g3a_db_ids), "g3a_calibration_offline": g3a_offline_count,
        "g3b_holdout": len(g3b_holdout_ids), "g3d_adversarial": len(g3d_ids),
        "total_unique_db_backed_labelled": len(all_db_ids),
        "total_unique_including_offline": len(all_db_ids) + g3a_offline_count,
    }


CONSOLIDATED_MANIFEST_INDEX: tuple[dict[str, str], ...] = tuple(
    {"fixture_id": e.fixture_id, "story_id": e.story_id or "(offline)", "split": "calibration", "source_phase": e.source_phase}
    for e in MANIFEST
) + tuple(
    {"fixture_id": h.fixture_id, "story_id": h.story_id, "split": "holdout", "source_phase": "R2.10G3-B"}
    for h in HOLDOUT
) + tuple(
    {"fixture_id": e.fixture_id, "story_id": e.story_id, "split": "adversarial", "source_phase": "R2.10G3-D"}
    for e in ADVERSARIAL_MANIFEST
)


class _G3DJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    print("LLM_ENABLED=False (this script never imports the Gateway on its default path)")
    overlap = used_story_ids_overlap_with_prior_sets()
    print(f"OVERLAP_WITH_PRIOR_SETS={sorted(overlap)}")

    now = datetime.now(timezone.utc)
    records = await collect_records(now=now)

    a_metrics = measure_rule_safety("RULE_A", "A_triggered", records)
    c_metrics = measure_rule_safety("RULE_C", "C_triggered", records)
    d_metrics = measure_rule_safety("RULE_D", "D_triggered", records)
    combined_metrics = measure_combined_safety(records)

    print(f"RULE_A: false_rejects={a_metrics.false_rejects} coverage={a_metrics.negative_coverage}")
    print(f"RULE_C: false_rejects={c_metrics.false_rejects} coverage={c_metrics.negative_coverage}")
    print(f"RULE_D: false_rejects={d_metrics.false_rejects} coverage={d_metrics.negative_coverage} ids={d_metrics.false_reject_ids}")
    print(f"COMBINED: false_rejects={combined_metrics.false_rejects} coverage={combined_metrics.negative_coverage}")

    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / now.strftime("%Y%m%dT%H%M%SZ"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "g3d_records.json").write_text(
        json.dumps([dataclasses.asdict(r) for r in records], cls=_G3DJSONEncoder, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    (output_dir / "g3d_metrics.json").write_text(
        json.dumps({
            "rule_a": dataclasses.asdict(a_metrics), "rule_c": dataclasses.asdict(c_metrics),
            "rule_d": dataclasses.asdict(d_metrics), "combined": dataclasses.asdict(combined_metrics),
            "class_specific": class_specific_rejection_rates(records),
            "subtype_false_rejects": subtype_false_rejects(records),
            "readiness_simulation": current_readiness_simulation(records),
            "dataset_expansion": dataset_expansion_summary(),
        }, indent=2), encoding="utf-8",
    )
    print(f"Wrote output to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
