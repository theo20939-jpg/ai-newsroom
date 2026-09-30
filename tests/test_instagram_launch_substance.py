"""Launch substance in the evidence (founder task 2026-09-30, after the final natural acceptance on 4046376).

The naturally selected Claude Sonnet 5.5 launch passed evidence, yet its carousel explained Anthropic's product lineup instead of the model:
its 9to5Mac article DID say the model runs 30% faster, costs up to 30% less, is strongest at fixing bugs and documents / slides /
spreadsheets, keeps its $2 / $10 pricing and is the first Sonnet with cyber safeguards - but the package's 6 fact slots were filled in PAGE
order, and the page opened with the lineup (case A: the facts existed, packaging lost them). For a LAUNCH (the accepted selection's own
ai / device / software launch reading, read for the EVENT) the facts are chosen by what they say about the launch; a launch whose sources
never say what it is is held. The primary proof uses the EXACT saved sources (tests/fixtures/instagram_launch_substance); software
releases, which no saved canary selected, use neutral fixtures.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.instagram_evidence_package import (
    BLOCKING,
    NOT_AVAILABLE,
    ORIGINAL_ARTICLE,
    STORED_BODY,
    EvidenceSource,
    SourceMedia,
    assemble_package,
    launch_story,
    launch_substance,
)
from services.instagram_viral_nomination import evidence_preflight

SAVED = json.loads((Path(__file__).parent / "fixtures/instagram_launch_substance/saved_packages.json").read_text(encoding="utf-8"))
MEDIA = SourceMedia(status=NOT_AVAILABLE, reason="replay")


def package(key: str, *, launch: bool | None, sources: list[dict] | None = None):
    saved = SAVED[key]
    return assemble_package(post_id=key, fmt=saved["format"], premise=saved["premise"], media=MEDIA, launch=launch,
                            sources=[EvidenceSource(**s) for s in (sources if sources is not None else saved["sources"])])


def event_launch(key: str) -> bool:
    return bool({"ai_launch", "device_launch", "software_launch"} & set(SAVED[key]["event_verdict"]["mechanisms"]))


def preflight(key: str, pkg):
    saved = SAVED[key]
    lines = [item.exact_text for item in (*pkg.steps, *pkg.facts, *pkg.limitations)] + ([pkg.dateline] if pkg.dateline else [])
    return evidence_preflight(saved["event_verdict"]["hook"], lines, actuality=SimpleNamespace(type="CURRENT_EVENT"),
                              now=datetime.fromisoformat(saved["now"]), headlines=[saved["premise"]])


def substantive(pkg) -> int:
    return sum(launch_substance(f.text, pkg.premise) for f in pkg.facts)


# --- the saved Sonnet 5.5 run -----------------------------------------------------------------------------------------------------------

def test_saved_sonnet_package_lost_every_substantive_fact_before():
    before = package("sonnet_en", launch=False)
    assert [f.text for f in before.facts] == SAVED["sonnet_en"]["facts_before"]  # reproduces the saved run's package exactly
    assert substantive(before) == 0
    assert any(f.text.startswith("The three main models are Haiku") for f in before.facts)


def test_saved_sonnet_package_now_carries_what_the_launch_is():
    after = package("sonnet_en", launch=event_launch("sonnet_en"))
    texts = [f.text for f in after.facts]
    assert len(texts) == 6 and substantive(after) == 5
    assert texts[0].startswith("Anthropic is upgrading Claude Sonnet, replacing Sonnet 5")  # the lede: what was introduced
    for fact in ("runs more than 30% faster, and costs up to 30% less", "including fixing bugs and creating polished documents",
                 "design capabilities", "$2 per million input tokens", "first Sonnet model to launch with cyber safeguards"):
        assert any(fact in t for t in texts), fact
    assert not any("The three main models" in t or "Fable/Mythos" in t for t in texts)  # the lineup no longer takes a slot
    assert after.quality != BLOCKING


def test_saved_sonnet_evidence_preflight_is_unchanged():
    before, after = package("sonnet_en", launch=False), package("sonnet_en", launch=True)
    first, second = preflight("sonnet_en", before), preflight("sonnet_en", after)
    assert first.status == second.status == "PASS" and first.checks == second.checks


def test_the_launch_is_read_for_the_event_not_the_copy():
    # the event was read as ai_launch from its Russian copy; the English copy that supplied the evidence does not read so on its own
    saved = SAVED["sonnet_en"]
    lead = " ".join(s["text"] for s in saved["sources"] if s["source_type"] == STORED_BODY)
    assert event_launch("sonnet_en") and not launch_story(saved["premise"], lead)
    assert substantive(package("sonnet_en", launch=None)) == 0  # no event: the copy's own reading, the old order
    assert substantive(package("sonnet_en", launch=True)) == 5


# --- insufficient evidence: hold, never a lineup explainer ------------------------------------------------------------------------------

def _truncated_sonnet_sources() -> list[dict]:
    """The saved article cut where its substance begins: exactly what an information-poor launch report looks like."""
    sources = [dict(s) for s in SAVED["sonnet_en"]["sources"]]
    for s in sources:
        if s["source_type"] == ORIGINAL_ARTICLE:
            s["text"] = s["text"].split("Introducing Claude Sonnet 5.5")[0]
    return sources


def test_a_launch_whose_sources_never_say_what_it_is_is_held():
    held = package("sonnet_en", launch=True, sources=_truncated_sonnet_sources())
    assert held.quality == BLOCKING and "launch story without its substance" in held.why
    assert package("sonnet_en", launch=False, sources=_truncated_sonnet_sources()).quality != BLOCKING  # only launches are held


# --- generalisation -----------------------------------------------------------------------------------------------------------------------

def test_saved_gadget_launch_keeps_its_specs_and_every_headline_name():
    before, after = package("honor", launch=False), package("honor", launch=event_launch("honor"))
    texts = [f.text for f in after.facts]
    assert substantive(after) > substantive(before)
    assert any("Snapdragon" in t for t in texts)  # the headline's 'прошлогодний Snapdragon' keeps its sentence
    assert any("11 000 мА·ч" in t for t in texts) and any("200-Мп" in t for t in texts)
    assert preflight("honor", after).status == "PASS"


def test_saved_russian_ai_launch_copy_is_unchanged_it_already_fits():
    assert [f.text for f in package("sonnet_ru", launch=True).facts] == [f.text for f in package("sonnet_ru", launch=False).facts]


def _article(*paragraphs: str) -> list[dict]:
    return [{"url": "https://example.org/a", "source_type": ORIGINAL_ARTICLE, "text": "\n".join(paragraphs), "status": "FULL_TEXT"}]


SOFTWARE_TITLE = "Vendor releases PhoneOS 18 with new AI features"
SOFTWARE_ARTICLE = _article(
    "Vendor releases PhoneOS 18 with new AI features",
    "Vendor today released PhoneOS 18 to every supported phone after a summer of public testing.",
    "Vendor has shipped a major PhoneOS release every autumn since the platform first appeared a decade ago.",
    "The company also sells tablets, watches and laptops that run their own versions of the platform.",
    "Its tablet software usually follows a few weeks after the phone release in most regions.",
    "The previous release introduced a redesigned settings app and a new wallpaper gallery for all users.",
    "Vendor says the update is available in more than forty countries and dozens of languages at launch.",
    "The new assistant can now act inside apps, booking a table or sending a file without leaving the conversation.",
    "Photos gains on-device search that finds a picture by describing it, and it runs 40% faster than before.",
    "Battery life improves by up to 2 hours on older phones, according to the company's own testing.",
)


def test_a_meaningful_software_release_leads_with_what_changed():
    lead = "Vendor today released PhoneOS 18 to every supported phone after a summer of public testing."
    assert launch_story(SOFTWARE_TITLE, lead)  # the accepted selection's software_launch reading
    after = assemble_package(post_id="sw", fmt="meme_trend", premise=SOFTWARE_TITLE, sources=[EvidenceSource(**s) for s in SOFTWARE_ARTICLE],
                             media=MEDIA)
    texts = [f.text for f in after.facts]
    for fact in ("can now act inside apps", "runs 40% faster", "up to 2 hours"):
        assert any(fact in t for t in texts), fact
    assert not any("tablets, watches and laptops" in t for t in texts)


def test_an_offer_or_related_headline_with_numbers_is_never_launch_substance():
    lede = "Vendor today released PhoneOS 18 to every supported phone after a summer of public testing."
    for line in ("Save 20% on AirPods Pro 3 today with this limited offer from Amazon.",
                 "Samsung Galaxy S27 Ultra review: the camera is 50% brighter than last year."):
        assert not launch_substance(line, SOFTWARE_TITLE, lede)
    assert launch_substance("Battery life improves by up to 2 hours on older phones.", SOFTWARE_TITLE, lede)  # names nothing else
    polluted = _article(*SOFTWARE_ARTICLE[0]["text"].split("\n"), "Save 20% on AirPods Pro 3 today with this limited offer from Amazon.")
    kept = assemble_package(post_id="sw", fmt="meme_trend", premise=SOFTWARE_TITLE, sources=[EvidenceSource(**s) for s in polluted],
                            media=MEDIA, launch=True)
    assert not any("AirPods" in f.text for f in kept.facts)


def test_a_routine_point_release_is_not_a_launch_and_keeps_the_page_order():
    title = "Apple releases iOS 27.0.1 for iPhone, here’s what’s new"
    lead = ("Apple has just released iOS 27.0.1, a new iPhone software update with key bug fixes for issues introduced in iOS 27. "
            "Here’s what’s new.")
    assert not launch_story(title, lead)
    sources = [EvidenceSource(url=None, source_type=STORED_BODY, text=lead), *(EvidenceSource(**s) for s in SOFTWARE_ARTICLE)]
    self_read = assemble_package(post_id="pr", fmt="meme_trend", premise=title, sources=sources, media=MEDIA)
    page_order = assemble_package(post_id="pr", fmt="meme_trend", premise=title, sources=sources, media=MEDIA, launch=False)
    assert [f.text for f in self_read.facts] == [f.text for f in page_order.facts]


@pytest.mark.parametrize("key", ["incident", "viral"])
def test_incident_and_viral_packages_are_unchanged(key):
    for launch in (None, False):
        assert [f.text for f in package(key, launch=launch).facts] == SAVED[key]["facts_before"]


def test_how_to_packages_are_never_launch_selected():
    how_to = assemble_package(post_id="h", fmt="ai_hack", premise=SOFTWARE_TITLE, sources=[EvidenceSource(**s) for s in SOFTWARE_ARTICLE],
                              media=MEDIA, launch=True)
    page_order = assemble_package(post_id="h", fmt="ai_hack", premise=SOFTWARE_TITLE, sources=[EvidenceSource(**s) for s in SOFTWARE_ARTICLE],
                                  media=MEDIA, launch=False)
    assert [f.text for f in how_to.facts] == [f.text for f in page_order.facts]


# --- the worker ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_worker_reads_the_launch_for_the_event_and_a_held_copy_gives_way(monkeypatch: pytest.MonkeyPatch):
    from uuid import UUID

    import worker.content_cycle as cc

    ids = [str(UUID(int=i)) for i in (1, 2)]
    event = SimpleNamespace(candidate_ids=tuple(ids), verdict=SimpleNamespace(mechanisms=("ai_launch",)))
    rows = {cid: SimpleNamespace(title="Nimbus X", url=f"https://example.org/{cid}", published_at=None) for cid in ids}
    calls: list[tuple[str, bool | None]] = []

    class Session:
        async def get(self, model, ident):
            return rows.get(str(ident))

    async def fake_package(session, event_id, row, slot_format, *, launch=None):
        calls.append((str(event_id), launch))
        return SimpleNamespace(steps=(), facts=(), limitations=(), dateline=None,
                               quality=BLOCKING if len(calls) == 1 else "STRONG")  # the first copy cannot explain its launch

    monkeypatch.setattr(cc, "_feed_evidence_package", fake_package)
    monkeypatch.setattr(cc, "viral_evidence_preflight", lambda *a, **k: SimpleNamespace(status="PASS"))
    copy_id, _row, pkg, _pf = await cc._viral_evidence_copy(Session(), event, UUID(ids[0]), rows[ids[0]], slot_format=None,
                                                             now=datetime.fromisoformat(SAVED["sonnet_en"]["now"]))
    assert calls == [(ids[0], True), (ids[1], True)]
    assert str(copy_id) == ids[1] and pkg.quality == "STRONG"
