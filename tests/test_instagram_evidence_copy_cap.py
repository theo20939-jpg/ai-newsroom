"""EVIDENCE COPY CAP 4 -> 8 (founder decision 2026-09-28, after canary 8): across the eight frozen canaries the passing copy was the newest,
the oldest or a mid-age direct publisher, so the accepted order is kept and only the bound rises. The search still stops at the first
PASS and never goes past the bound; the 24-hour window and the preflight are unchanged."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

import worker.content_cycle as cc
from services.instagram_feed_product import FeedFormat
from services.instagram_viral_nomination import nominate_viral_events
from tests.test_instagram_viral_nomination import NOW, SUPPORTING_BODY, us_gov_copies

ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "artifacts/instagram_feed_product/evidence_cap8_replay/evidence_cap_replay.json"


def _ids(n: int) -> list[str]:
    return [str(UUID(int=i + 1)) for i in range(n)]


async def _search(monkeypatch: pytest.MonkeyPatch, n_copies: int, passing_position: int | None, *, urls=None):
    """The real _viral_evidence_copy over n copies of one event; only the copy at `passing_position` (1-based, in attempt order) has a
    supporting body. Returns (attempted copy ids in order, preflight)."""
    event = nominate_viral_events(us_gov_copies(), now=NOW).eligible[0]
    ids = _ids(n_copies)
    event = dataclasses.replace(event, candidate_ids=tuple(ids))
    rows = {cid: SimpleNamespace(title=event.evidence_candidate.title, url=(urls or {}).get(cid, f"https://example.org/{i}"),
                                 published_at=None, source_id=None, content=None, summary=None)
            for i, cid in enumerate(ids)}

    class Session:
        async def get(self, model, ident):
            return rows.get(str(ident))

    tried: list[str] = []

    async def package(session, event_id, row, slot_format, *, launch=None):
        tried.append(str(event_id))
        lines = SUPPORTING_BODY if passing_position is not None and len(tried) == passing_position else []
        return SimpleNamespace(steps=(), facts=tuple(SimpleNamespace(exact_text=t) for t in lines), limitations=(), quality="STRONG")

    monkeypatch.setattr(cc, "_feed_evidence_package", package)
    _id, _row, _pkg, preflight = await cc._viral_evidence_copy(Session(), event, UUID(ids[0]), rows[ids[0]],
                                                               slot_format=FeedFormat.MEME_TREND, now=NOW)
    return tried, preflight


def test_1_the_limit_is_exactly_eight():
    assert cc._VIRAL_EVIDENCE_COPIES == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("position", [1, 4, 7])
async def test_2_3_4_the_search_stops_at_the_first_pass(monkeypatch: pytest.MonkeyPatch, position):
    tried, preflight = await _search(monkeypatch, 12, position)
    assert preflight.status == "PASS" and len(tried) == position  # nothing is fetched after the PASS


@pytest.mark.asyncio
async def test_5_6_no_pass_stops_after_eight_and_copy_nine_is_never_attempted(monkeypatch: pytest.MonkeyPatch):
    tried, preflight = await _search(monkeypatch, 12, None)
    assert preflight.status != "PASS" and len(tried) == 8
    assert _ids(12)[8] not in tried  # copy 9
    tried, preflight = await _search(monkeypatch, 12, 9)  # a passing 9th copy is out of bounds
    assert preflight.status != "PASS" and len(tried) == 8


@pytest.mark.asyncio
async def test_7_fewer_than_eight_copies_are_all_tried_once(monkeypatch: pytest.MonkeyPatch):
    tried, preflight = await _search(monkeypatch, 3, None)
    assert tried == _ids(3) and preflight.status != "PASS"


@pytest.mark.asyncio
async def test_8_9_the_order_is_the_accepted_one_planned_then_direct_then_redirect_shells_in_nomination_order(monkeypatch):
    ids = _ids(10)
    shells = {cid: "https://news.google.com/rss/articles/CBMi-shell" for cid in ids[1:6]}  # copies 2-6 are shells, 7-10 direct
    tried, _ = await _search(monkeypatch, 10, None, urls=shells)
    assert tried == [ids[0], *ids[6:10], *ids[1:4]]  # planned, the 4 direct copies (nomination order), then shells, bounded at 8
    # the 24-hour window is the nomination's: _viral_evidence_copy only ever loads the event's own candidate_ids (it adds no copy)
    assert set(tried) <= set(ids)


def test_10_all_eight_frozen_canary_pools_replay_without_regression():
    report = json.loads(REPLAY.read_text(encoding="utf-8"))
    assert report["provider_calls"] == 0 and report["image_calls"] == 0
    by = {r["canary"]: r for r in report["canaries"]}
    assert set(by) == {"canary", "canary2", "canary3", "canary4", "canary5", "canary6", "canary7", "canary8"}
    for r in report["canaries"]:
        assert r["copies_fetched"] <= 8 and r["cap"] == 8
        if r["original_passing"]:  # every canary that passed evidence before still passes, on the same copy
            assert r["result"] == "PASS" and r["result_copy"] in r["original_passing"], r["canary"]
    assert by["canary8"]["result"] == "PASS" and by["canary8"]["result_copy"] == "a6b32ec3-2697-432c-ae6e-c175c496b6e0"
