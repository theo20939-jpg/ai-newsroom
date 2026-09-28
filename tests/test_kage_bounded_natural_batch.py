"""Bounded natural batch: limits, reserve-before-claim cost cap, stop conditions, run-id isolation.

Everything that would touch the DB, providers or Telegram is a deterministic fake; no network."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.config import settings
from scripts import _kage_telegram_bounded_natural_batch as batch
from scripts._kage_telegram_bounded_natural_batch import (
    BatchDeps, BatchLimits, BatchStop, BoundedNaturalBatch, claim_run_dir, validate_run_id,
)

CHAT, TOPIC = -1004297182444, 2
FOOTER = "\U0001F977 KAGE"


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


class World:
    """Fake production: a queue of naturally selectable events and the accepted pipeline's results."""

    def __init__(self, specs: list[dict]) -> None:
        self.specs = {UUID(s["id"]) if "id" in s else uuid4(): s for s in specs}
        self.queue = list(self.specs)
        self.claims: list[UUID] = []
        self.runs: list[UUID] = []
        self.releases: list[bool] = []
        self.delivered: set[UUID] = {e for e, s in self.specs.items() if s.get("delivered_before")}
        self.unlock_ok = True

    async def select_top(self):
        if not self.queue:
            return None
        event_id = self.queue[0]
        return {"event_id": str(event_id), "story_id": str(uuid4()), "title": "t", "valid": True,
                "analysis_fresh": True, "content_generation_tasks": 0, "delivery_records": 0,
                "selector_selected_at": "2026-09-27T00:00:00+00:00"}

    async def publication_state(self, event_id):
        delivered = event_id in self.delivered
        if delivered and event_id in self.queue and self.specs[event_id].get("delivered_before"):
            self.queue.remove(event_id)  # the real selector stops offering it once it has a task
        return {"already_delivered": delivered, "delivered_task_ids": ["t"] if delivered else [],
                "sent_receipt_ids": ["r"] if delivered else [], "in_flight_task_ids": []}

    async def claim(self, event_id):
        self.claims.append(event_id)
        return True

    async def recheck(self, event_id):
        return await self.select_top()

    async def release(self, held):
        self.releases.append(held)
        return self.unlock_ok if held else True

    async def run_story(self, event_id, selection):
        self.runs.append(event_id)
        self.queue.remove(event_id)
        spec = self.specs[event_id]
        cost = Decimal(str(spec.get("cost", "0.02")))
        per = cost / 6
        dispatches = [{"stage": f"s{i}", "model": "m", "status": "COMPLETED",
                       "actual_cost_usd": None if spec.get("cost_gap") and i == 0 else str(per),
                       "reserved_max_cost_usd": "0.1"} for i in range(6)]
        dispatches[-1]["actual_cost_usd"] = str(cost - per * 5) if not spec.get("cost_gap") else str(per)
        status = spec.get("status", "DELIVERED")
        sends = []
        if status == "DELIVERED" or spec.get("sends"):
            sends = spec.get("sends") or [{"method": "send_photo", "status": "accepted", "chat_id": CHAT,
                                           "topic_id": TOPIC, "message_id": 5000 + len(self.runs),
                                           "caption": f"Title\nBody text.\n{spec.get('footer', FOOTER)}",
                                           "buttons": [[{"text": "🔗 Источник", "url": "https://x"}],
                                                       [{"text": "😂 Сгенерировать мем", "url": None}]],
                                           "sent_photo": {"sha256": "ab", "bytes": 10}}]
        if status == "DELIVERED" and not spec.get("no_receipt"):
            self.delivered.add(event_id)
        return {"cycle": {"event_ids": [str(event_id)], "generation_attempts": 1},
                "provider_dispatches": dispatches, "sends": sends}

    async def forensics(self, event_id):
        spec = self.specs[event_id]
        status = spec.get("status", "DELIVERED")
        if spec.get("no_lineage"):
            return {"tasks": ["task"], "lineage": None, "publication": {}}
        message_id = 5000 + self.runs.index(event_id) + 1 if status == "DELIVERED" else None
        receipts = ["r-" + str(event_id)] if status == "DELIVERED" and not spec.get("no_receipt") else []
        return {
            "tasks": ["task-" + str(event_id)],
            "lineage": {"identity": {"generation_task_id": "task", "draft_id": "draft",
                                     "delivery_receipt_id": receipts[0] if receipts else None,
                                     "telegram_message_id": message_id},
                        "stages": {"research": {}, "intelligence": {}, "copywriting": {}, "quality": {}},
                        "publication_factual_gate": {"structured_result": {"FACTUAL_SAFETY": "PASS"}},
                        "publication_outcome": {"status": status, "message_id": message_id}},
            "publication": {"already_delivered": bool(receipts), "delivered_task_ids": ["task"] if receipts else [],
                            "sent_receipt_ids": receipts},
        }

    def deps(self) -> BatchDeps:
        return BatchDeps(select_top=self.select_top, publication_state=self.publication_state, claim=self.claim,
                         recheck=self.recheck, release=self.release, run_story=self.run_story,
                         forensics=self.forensics)


async def _run(tmp_path: Path, specs: list[dict], limits: BatchLimits = BatchLimits(), run_id="run-a"):
    world = World(specs)
    clock = Clock()
    runner = BoundedNaturalBatch(run_id=run_id, out_dir=claim_run_dir(tmp_path / run_id, run_id),
                                 deps=world.deps(), limits=limits, clock=clock, sleep=clock.sleep)
    manifest = await runner.run()
    return manifest, world


def test_release_constants_are_the_accepted_bounds():
    assert (batch.MAX_ATTEMPTS, batch.MAX_DELIVERIES, batch.MIN_DESIRED_ATTEMPTS) == (10, 10, 5)
    assert batch.BATCH_HARD_CAP_USD == Decimal("3.74")
    assert batch.PER_STORY_MAX_USD == Decimal("0.977229")  # text 0.746389 + visual 0.230840
    assert batch.NATURAL_WINDOW_SECONDS == 12 * 3600


@pytest.mark.asyncio
async def test_five_normal_attempts_one_event_at_a_time(tmp_path):
    manifest, world = await _run(tmp_path, [{} for _ in range(5)])
    assert manifest["terminal_reason"] == "NATURAL_WINDOW_ELAPSED" and manifest["clean"]
    assert manifest["attempts"] == 5 and manifest["deliveries"] == 5
    assert world.claims == world.runs and len(world.runs) == 5
    assert world.releases == [True] * 5  # every claim released before the next one
    story = manifest["stories"][0]
    assert story["delivered_post"]["footer"] == FOOTER and story["delivered_post"]["footer_matches_release"]
    assert story["delivered_post"]["buttons"][1][0]["text"] == "😂 Сгенерировать мем"
    assert (tmp_path / "run-a" / story["artifact"]).exists()


@pytest.mark.asyncio
async def test_never_more_than_ten_attempts(tmp_path):
    manifest, world = await _run(tmp_path, [{"status": "BLOCKED_FACTUAL_GATE"} for _ in range(15)])
    assert manifest["terminal_reason"] == "COMPLETED_MAX_ATTEMPTS"
    assert manifest["attempts"] == 10 and len(world.runs) == 10 and manifest["deliveries"] == 0


@pytest.mark.asyncio
async def test_never_more_than_ten_deliveries(tmp_path):
    manifest, world = await _run(tmp_path, [{} for _ in range(15)], BatchLimits(max_attempts=20))
    assert manifest["terminal_reason"] == "COMPLETED_MAX_DELIVERIES"
    assert manifest["deliveries"] == 10 and len(world.runs) == 10


@pytest.mark.asyncio
async def test_reserve_before_next_claim(tmp_path):
    manifest, world = await _run(tmp_path, [{"cost": "0.70"} for _ in range(10)])
    # after 4 stories: 2.80 spent; 2.80 + 0.977229 (text+visual worst case) > 3.74 -> no 5th claim
    assert manifest["terminal_reason"] == "BUDGET_RESERVATION_EXHAUSTED" and manifest["clean"]
    assert len(world.claims) == 4 and Decimal(manifest["cumulative_cost_usd"]) == Decimal("2.80")


@pytest.mark.asyncio
async def test_worst_case_every_story_cannot_exceed_the_cap(tmp_path):
    manifest, world = await _run(tmp_path, [{"cost": "0.977229"} for _ in range(10)])
    # the unchanged $3.74 cap guarantees only 3 fully-reserved worst-case stories (5 needs $4.89)
    assert len(world.claims) == 3
    assert Decimal(manifest["cumulative_cost_usd"]) == Decimal("2.931687") <= Decimal("3.74")


@pytest.mark.asyncio
async def test_story_above_per_story_max_is_a_hard_budget_violation(tmp_path):
    manifest, _ = await _run(tmp_path, [{"cost": "1.00"}, {}])
    assert manifest["terminal_reason"] == "HARD_BUDGET_VIOLATION" and not manifest["clean"]
    assert manifest["attempts"] == 1


@pytest.mark.asyncio
async def test_cost_accounting_gap_stops(tmp_path):
    manifest, _ = await _run(tmp_path, [{"cost_gap": True}, {}])
    assert manifest["terminal_reason"] == "COST_ACCOUNTING_FAILURE" and manifest["attempts"] == 1


@pytest.mark.asyncio
async def test_factual_block_counts_sends_nothing_and_continues(tmp_path):
    manifest, world = await _run(tmp_path, [{"status": "BLOCKED_FACTUAL_GATE"}, {}, {}])
    assert manifest["attempts"] == 3 and manifest["deliveries"] == 2
    assert manifest["stories"][0]["terminal_reason"] == "BLOCKED_FACTUAL_GATE"
    assert manifest["stories"][0]["factual_gate"] is not None
    assert "delivered_post" not in manifest["stories"][0]


@pytest.mark.asyncio
async def test_already_delivered_event_is_skipped_before_claim_and_provider_calls(tmp_path):
    delivered = str(uuid4())
    manifest, world = await _run(tmp_path, [{"id": delivered, "delivered_before": True}, {}])
    assert UUID(delivered) not in world.claims and UUID(delivered) not in world.runs
    assert manifest["skipped"] == [{"event_id": delivered, "reason": "ALREADY_DELIVERED_BEFORE_CLAIM",
                                    "at_utc": manifest["skipped"][0]["at_utc"]}]
    assert manifest["attempts"] == 1


@pytest.mark.asyncio
async def test_destination_mismatch_stops(tmp_path):
    bad = [{"method": "send_message", "status": "accepted", "chat_id": CHAT, "topic_id": 40,
            "message_id": 1, "text": f"T\nB\n{FOOTER}"}]
    manifest, world = await _run(tmp_path, [{"sends": bad}, {}])
    assert manifest["terminal_reason"] == "DESTINATION_MISMATCH" and len(world.runs) == 1


@pytest.mark.asyncio
async def test_more_than_one_send_for_a_story_stops(tmp_path):
    one = {"method": "send_message", "status": "accepted", "chat_id": CHAT, "topic_id": TOPIC,
           "message_id": 1, "text": f"T\nB\n{FOOTER}"}
    manifest, world = await _run(tmp_path, [{"sends": [one, {**one, "message_id": 2}]}, {}])
    assert manifest["terminal_reason"] == "DUPLICATE_SEND" and len(world.runs) == 1


@pytest.mark.asyncio
async def test_missing_lineage_stops(tmp_path):
    manifest, world = await _run(tmp_path, [{"no_lineage": True}, {}])
    assert manifest["terminal_reason"] == "MISSING_DURABLE_LINEAGE" and len(world.runs) == 1


@pytest.mark.asyncio
async def test_delivered_message_without_receipt_stops(tmp_path):
    manifest, world = await _run(tmp_path, [{"no_receipt": True}, {}])
    assert manifest["terminal_reason"] == "RECEIPT_OUTCOME_MISMATCH" and len(world.runs) == 1


@pytest.mark.asyncio
async def test_gate_technical_failure_stops(tmp_path):
    manifest, _ = await _run(tmp_path, [{"status": "GATE_TECHNICAL_BLOCK"}, {}])
    assert manifest["terminal_reason"] == "FACTUAL_GATE_TECHNICAL_FAILURE"


@pytest.mark.asyncio
async def test_footer_contract_mismatch_stops(tmp_path):
    manifest, _ = await _run(tmp_path, [{"footer": "KAGE"}, {}])
    assert manifest["terminal_reason"] == "FOOTER_CONTRACT_MISMATCH" and manifest["attempts"] == 1


@pytest.mark.asyncio
async def test_advisory_lock_integrity_failure_stops(tmp_path):
    world = World([{}, {}])
    world.unlock_ok = False
    clock = Clock()
    runner = BoundedNaturalBatch(run_id="run-lock", out_dir=claim_run_dir(tmp_path / "l", "run-lock"),
                                 deps=world.deps(), clock=clock, sleep=clock.sleep)
    manifest = await runner.run()
    assert manifest["terminal_reason"] == "ADVISORY_LOCK_INTEGRITY" and len(world.runs) == 1


@pytest.mark.asyncio
async def test_unexpected_exception_stops_and_is_recorded(tmp_path):
    world = World([{}, {}])

    async def boom(event_id, selection):
        raise RuntimeError("pipeline exploded")

    deps = world.deps()
    deps.run_story = boom
    clock = Clock()
    runner = BoundedNaturalBatch(run_id="run-exc", out_dir=claim_run_dir(tmp_path / "e", "run-exc"),
                                 deps=deps, clock=clock, sleep=clock.sleep)
    manifest = await runner.run()
    assert manifest["terminal_reason"] == "UNEXPECTED_EXCEPTION" and "pipeline exploded" in manifest["terminal_detail"]
    assert world.releases == [True]  # the claim is still released


@pytest.mark.asyncio
async def test_insufficient_natural_volume_ends_cleanly(tmp_path):
    manifest, _ = await _run(tmp_path, [{}, {"status": "BLOCKED_FACTUAL_GATE"}])
    assert manifest["terminal_reason"] == "INSUFFICIENT_NATURAL_VOLUME" and manifest["clean"]
    assert manifest["attempts"] == 2


@pytest.mark.asyncio
async def test_manifest_is_durable_and_complete(tmp_path):
    manifest, _ = await _run(tmp_path, [{}])
    on_disk = json.loads((tmp_path / "run-a" / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["run_id"] == "run-a" and on_disk["terminal_reason"] == manifest["terminal_reason"]
    story = on_disk["stories"][0]
    for key in ("event_id", "story_id", "task_id", "draft_id", "factual_gate", "outcome", "receipt_id",
                "telegram_message_id", "provider_calls", "stage_costs", "story_cost_usd",
                "cumulative_cost_usd", "terminal_reason"):
        assert key in story
    assert story["provider_calls"] == 6 and len(story["stage_costs"]) == 6


@pytest.mark.parametrize("bad", ["", "a", "Run1", "run_1", "run/../x", "-run", "r" * 41, "run 1", None])
def test_invalid_run_ids_are_refused(bad):
    with pytest.raises(BatchStop) as err:
        validate_run_id(bad)
    assert err.value.reason == "INVALID_RUN_ID"


def test_run_id_collision_is_a_hard_stop_and_never_overwrites(tmp_path):
    out = claim_run_dir(tmp_path / "batch-x", "run-x")
    (out / "manifest.json").write_text('{"keep": true}', encoding="utf-8")
    with pytest.raises(BatchStop) as err:
        claim_run_dir(tmp_path / "batch-x", "run-x")
    assert err.value.reason == "RUN_ID_COLLISION"
    with pytest.raises(BatchStop):
        claim_run_dir(tmp_path / "batch-x", "run-y")  # a directory bound to another run is never reused
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == {"keep": True}


@pytest.mark.asyncio
async def test_different_run_ids_are_isolated(tmp_path):
    first, _ = await _run(tmp_path, [{}], run_id="run-one")
    second, _ = await _run(tmp_path, [{"status": "BLOCKED_FACTUAL_GATE"}], run_id="run-two")
    one = json.loads((tmp_path / "run-one" / "manifest.json").read_text(encoding="utf-8"))
    two = json.loads((tmp_path / "run-two" / "manifest.json").read_text(encoding="utf-8"))
    assert (one["run_id"], two["run_id"]) == ("run-one", "run-two")
    assert one["deliveries"] == 1 and two["deliveries"] == 0
    assert (tmp_path / "run-one" / "RUN_ID.lock").read_text(encoding="utf-8") == "run-one"


@pytest.mark.asyncio
async def test_runner_never_touches_the_persistent_generation_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "content_generation_enabled", False)
    await _run(tmp_path, [{}, {"status": "BLOCKED_FACTUAL_GATE"}])
    assert settings.content_generation_enabled is False
    source = Path(batch.__file__).read_text(encoding="utf-8")
    assert "content_generation_enabled =" not in source and "content_generation_enabled=" not in source


@pytest.mark.asyncio
async def test_production_entry_refuses_when_generation_flag_is_true(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGE_BATCH_RUN_ID", "run-flag")
    monkeypatch.setenv("KAGE_BATCH_OUTPUT_DIR", str(tmp_path / "flag"))
    monkeypatch.setattr(settings, "content_generation_enabled", True)
    with pytest.raises(BatchStop) as err:
        await batch._production_main()
    assert err.value.reason == "CONTENT_GENERATION_ENABLED_TRUE"
