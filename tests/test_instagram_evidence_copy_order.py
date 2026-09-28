"""EVIDENCE COPY ORDER (founder decision 2026-09-28, after the canary-8 copy-limit diagnostic): the 24-hour window and the 4-copy limit are
unchanged; only the order of the Google News copies changes - newest first by collected_at - so the bounded search reaches the current,
most complete copy of an evolving story sooner (canary 8: the passing CBC copy was 0.7 h old and tried last)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

import worker.content_cycle as cc

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary8_20260928/offline_evidence_order/copy_order_fixture.json"
REPLAY = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary8_20260928/offline_evidence_order/evidence_order_replay.json"
T0 = datetime(2026, 9, 27, 21, 0, tzinfo=UTC)
GN = "https://news.google.com/rss/articles/CBMi-shell"


def U(n: int) -> UUID:
    return UUID(int=n)


def row(url: str, hours_old: float | None) -> SimpleNamespace:
    return SimpleNamespace(url=url, collected_at=None if hours_old is None else T0 - timedelta(hours=hours_old))


def order(rows: dict, planned: UUID, candidate_ids: list[str] | None = None) -> list[UUID]:
    return cc._order_evidence_copies(planned, rows, candidate_ids if candidate_ids is not None else [str(k) for k in rows])


def test_the_planned_copy_stays_first_even_when_a_google_news_copy_is_newer():
    rows = {U(1): row("https://www.theverge.com/a", 20), U(2): row(GN, 0.1)}
    assert order(rows, U(1))[0] == U(1)


def test_direct_publisher_copies_stay_ahead_of_google_news_and_keep_their_nomination_order():
    rows = {U(1): row(GN, 5), U(2): row(GN, 0.5), U(3): row("https://b.example/x", 20), U(4): row("https://a.example/y", 10),
            U(5): row(GN, 1)}
    got = order(rows, U(1), [str(U(1)), str(U(3)), str(U(4)), str(U(2)), str(U(5))])
    assert got[:3] == [U(1), U(3), U(4)]  # direct copies: nomination order, NOT freshness (U(4) is newer but nominated later)


def test_google_news_copies_are_ordered_newest_first():
    rows = {U(1): row("https://www.theverge.com/a", 3), U(2): row(GN, 23), U(3): row(GN, 22), U(4): row(GN, 0.7), U(5): row(GN, 11)}
    assert order(rows, U(1))[1:] == [U(4), U(5), U(3), U(2)]


def test_ties_are_stable_nomination_order_then_copy_id_and_unknown_times_go_last():
    rows = {U(1): row("https://d.example/a", 1), U(9): row(GN, 2), U(7): row(GN, 2), U(8): row(GN, None)}
    assert order(rows, U(1), [str(U(1)), str(U(9)), str(U(7)), str(U(8))])[1:] == [U(9), U(7), U(8)]  # same time: nomination order
    assert order(rows, U(1), [str(U(1))])[1:] == [U(7), U(9), U(8)]  # not in the nomination: copy id
    fixed = [str(U(1)), str(U(9)), str(U(7)), str(U(8))]
    assert order(rows, U(1), fixed) == order(dict(reversed(list(rows.items()))), U(1), fixed)  # independent of dict / load order


def test_ordering_never_adds_a_copy_the_24_hour_nomination_did_not_make_eligible():
    rows = {U(1): row("https://d.example/a", 1), U(2): row(GN, 1)}
    assert set(order(rows, U(1), [str(U(1)), str(U(2)), str(U(3))])) == {U(1), U(2)}  # U(3) (e.g. aged out) was never loaded


def test_the_copy_limit_stays_four_and_bounds_the_attempts():
    assert cc._VIRAL_EVIDENCE_COPIES == 4
    source = (ROOT / "worker/content_cycle.py").read_text(encoding="utf-8")
    assert "_order_evidence_copies(event_id, rows, candidate_ids)[:_VIRAL_EVIDENCE_COPIES]" in source


def test_the_frozen_canary8_pool_reaches_the_cbc_copy_within_the_first_four():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = {UUID(c): SimpleNamespace(url=v["url"], collected_at=datetime.fromisoformat(v["collected_at"])) for c, v in fixture["copies"].items()}
    new = cc._order_evidence_copies(UUID(fixture["planned"]), rows, fixture["candidate_ids"])
    cbc = UUID("a6b32ec3-2697-432c-ae6e-c175c496b6e0")
    assert new[0] == UUID(fixture["planned"]) and cbc in new[: cc._VIRAL_EVIDENCE_COPIES]
    old = [UUID(fixture["planned"]), *(UUID(c) for c in fixture["candidate_ids"] if c != fixture["planned"])]
    assert cbc not in old[: cc._VIRAL_EVIDENCE_COPIES]  # canary 8 as it ran: CBC was position 7
    assert set(new) == set(old)  # the same eligible copies, only reordered


def test_the_replay_passed_the_unchanged_preflight_within_the_first_four():
    report = json.loads(REPLAY.read_text(encoding="utf-8"))
    assert report["provider_calls"] == 0 and report["image_calls"] == 0 and report["max_copies"] == 4
    assert len(report["attempts_new_order"]) <= 4 and report["passing_copy"] == "a6b32ec3-2697-432c-ae6e-c175c496b6e0"
    passing = report["attempts_new_order"][-1]
    assert passing["preflight"] == "PASS" and set(passing["checks"].values()) == {"SUPPORTED"}


@pytest.mark.asyncio
async def test_ordering_does_not_change_preflight_semantics_each_copy_gets_the_same_verdict(monkeypatch: pytest.MonkeyPatch):
    """The same copies with the same bodies get the same preflight verdicts under either order; only which one is tried first moves."""
    from tests.test_instagram_viral_nomination import NOW, SUPPORTING_BODY, us_gov_copies

    from services.instagram_feed_product import FeedFormat
    from services.instagram_viral_nomination import nominate_viral_events

    copies = us_gov_copies()
    event = nominate_viral_events(copies, now=NOW).eligible[0]
    planned = event.evidence_candidate.id
    rows = {c.id: SimpleNamespace(title=c.title, url=GN if c.id != planned else "https://example.org/p", published_at=None,
                                  collected_at=NOW - timedelta(hours=i), source_id=None, content=None, summary=None)
            for i, c in enumerate(copies)}
    passing = copies[-1].id  # the OLDEST shell carries the supporting body here

    class Session:
        async def get(self, model, ident):
            return rows.get(str(ident))

    tried: list[str] = []

    async def package(session, event_id, row_, slot_format):
        tried.append(str(event_id))
        lines = SUPPORTING_BODY if str(event_id) == passing else []
        return SimpleNamespace(steps=(), facts=tuple(SimpleNamespace(exact_text=t) for t in lines), limitations=())

    monkeypatch.setattr(cc, "_feed_evidence_package", package)
    _id, _row, _pkg, preflight = await cc._viral_evidence_copy(Session(), event, UUID(planned), rows[planned],
                                                               slot_format=FeedFormat.MEME_TREND, now=NOW)
    assert len(tried) <= cc._VIRAL_EVIDENCE_COPIES and tried[0] == planned
    # the oldest copy is now tried last: if it is inside the limit it still passes with the same body, otherwise the result is not PASS
    assert (preflight.status == "PASS") == (passing in tried)
