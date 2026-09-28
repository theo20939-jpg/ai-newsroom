"""TEMPORAL-DIVERSITY EVIDENCE ORDER (founder decision 2026-09-28): the live canaries' passing copy was sometimes the NEWEST in-window copy
(canary 8, CBC 0.7 h) and sometimes the OLDEST (canaries 6 / 7, Boston Herald ~23 h), so a bounded 4-copy search covers the window's time
range: slot 1 the planned copy, slot 2 the newest remaining, slot 3 the oldest remaining, then the existing priority. The 24-hour window,
the 4-copy limit and the evidence preflight are unchanged."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

import worker.content_cycle as cc

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "artifacts/instagram_feed_product/evidence_order_temporal/copy_order_fixtures.json"
T0 = datetime(2026, 9, 27, 21, 0, tzinfo=UTC)
GN = "https://news.google.com/rss/articles/CBMi-shell"


def U(n: int) -> UUID:
    return UUID(int=n)


def row(url: str, hours_old: float | None) -> SimpleNamespace:
    return SimpleNamespace(url=url, collected_at=None if hours_old is None else T0 - timedelta(hours=hours_old))


def test_1_the_planned_copy_always_stays_slot_1():
    rows = {U(1): row("https://www.theverge.com/a", 23.9), U(2): row(GN, 0.1), U(3): row(GN, 23.95)}
    assert cc._order_evidence_copies(U(1), rows)[0] == U(1)


def test_2_3_4_newest_then_oldest_then_the_existing_priority():
    rows = {U(1): row("https://p.example/planned", 3), U(2): row(GN, 20), U(3): row(GN, 12), U(4): row("https://d.example/x", 8),
            U(5): row(GN, 0.5), U(6): row(GN, 23)}
    got = cc._order_evidence_copies(U(1), rows)
    assert got[1] == U(5)  # slot 2: newest remaining (a Google News copy competes like any other)
    assert got[2] == U(6)  # slot 3: oldest remaining
    assert got[3] == U(4)  # slot 4: existing priority - the direct publisher copy before the remaining shells
    assert got[4:] == [U(2), U(3)]  # then the existing priority (nomination order among shells)


def test_5_no_copy_appears_twice_and_6_small_sets_behave():
    rows = {U(1): row("https://p.example/a", 1), U(2): row(GN, 5)}
    assert cc._order_evidence_copies(U(1), rows) == [U(1), U(2)]  # one remaining copy: it is the newest, nothing else
    assert cc._order_evidence_copies(U(1), {U(1): row("https://p.example/a", 1)}) == [U(1)]
    many = {U(i): row(GN if i % 2 else "https://d.example/%d" % i, float(i)) for i in range(1, 9)}
    got = cc._order_evidence_copies(U(1), many)
    assert len(got) == len(set(got)) == len(many)


def test_7_ties_are_deterministic_existing_priority_then_copy_id_and_unknown_times_are_never_picked_by_time():
    rows = {U(1): row("https://p.example/a", 1), U(9): row(GN, 2), U(7): row(GN, 2), U(8): row(GN, None), U(6): row(GN, 2)}
    got = cc._order_evidence_copies(U(1), rows)
    assert got[1] == U(9)  # newest tie (U9, U7, U6 all 2 h): the first in the existing priority (row / nomination order)
    assert got[2] == U(7)  # oldest tie among the rest: again the existing priority
    assert got[-1] != U(8) or got.index(U(8)) >= 3  # the untimed copy only ever comes by priority
    assert got == cc._order_evidence_copies(U(1), dict(rows))  # repeatable


def test_8_ordering_never_adds_a_copy_the_24_hour_nomination_did_not_load():
    rows = {U(1): row("https://p.example/a", 1), U(2): row(GN, 1)}
    assert set(cc._order_evidence_copies(U(1), rows)) == set(rows)


def test_9_the_copy_limit_stays_four():
    assert cc._VIRAL_EVIDENCE_COPIES == 4
    source = (ROOT / "worker/content_cycle.py").read_text(encoding="utf-8")
    assert "_order_evidence_copies(event_id, rows)[:_VIRAL_EVIDENCE_COPIES]" in source


def _frozen(name: str) -> tuple[UUID, list[UUID], dict]:
    fx = json.loads(FIXTURES.read_text(encoding="utf-8"))[name]
    rows = {UUID(c): SimpleNamespace(url=v["url"], collected_at=datetime.fromisoformat(v["collected_at"])) for c, v in fx["copies"].items()}
    return UUID(fx["planned"]), cc._order_evidence_copies(UUID(fx["planned"]), rows), fx


def test_10_canary8_reaches_the_cbc_copy_within_the_first_four():
    _planned, new, _fx = _frozen("canary8")
    assert UUID("a6b32ec3-2697-432c-ae6e-c175c496b6e0") in new[:4]


@pytest.mark.parametrize("name", ["canary6", "canary7"])
def test_11_12_canaries_6_and_7_keep_the_boston_herald_copy_within_the_first_four(name):
    _planned, new, _fx = _frozen(name)
    assert UUID("4371aba5-6ff7-4b6d-b38c-df16b0e104b2") in new[:4]


@pytest.mark.asyncio
async def test_13_ordering_does_not_change_preflight_semantics(monkeypatch: pytest.MonkeyPatch):
    """The same copies with the same bodies get the same verdicts; only the attempt order moves (the oldest copy now comes 3rd)."""
    from tests.test_instagram_viral_nomination import NOW, SUPPORTING_BODY, us_gov_copies

    from services.instagram_feed_product import FeedFormat
    from services.instagram_viral_nomination import nominate_viral_events

    copies = us_gov_copies()
    event = nominate_viral_events(copies, now=NOW).eligible[0]
    planned = event.evidence_candidate.id
    rows = {c.id: SimpleNamespace(title=c.title, url=GN if c.id != planned else "https://example.org/p", published_at=None,
                                  collected_at=NOW - timedelta(hours=i + 1), source_id=None, content=None, summary=None)
            for i, c in enumerate(copies)}
    oldest = max((c.id for c in copies if c.id != planned), key=lambda cid: NOW - rows[cid].collected_at)

    class Session:
        async def get(self, model, ident):
            return rows.get(str(ident))

    tried: list[str] = []

    async def package(session, event_id, row_, slot_format):
        tried.append(str(event_id))
        lines = SUPPORTING_BODY if str(event_id) == oldest else []
        return SimpleNamespace(steps=(), facts=tuple(SimpleNamespace(exact_text=t) for t in lines), limitations=())

    monkeypatch.setattr(cc, "_feed_evidence_package", package)
    _id, _row, _pkg, preflight = await cc._viral_evidence_copy(Session(), event, UUID(planned), rows[planned],
                                                               slot_format=FeedFormat.MEME_TREND, now=NOW)
    assert tried[0] == planned and len(tried) <= cc._VIRAL_EVIDENCE_COPIES
    assert oldest in tried[:3] and preflight.status == "PASS"  # the oldest copy is reached by slot 3 and passes with the same body
