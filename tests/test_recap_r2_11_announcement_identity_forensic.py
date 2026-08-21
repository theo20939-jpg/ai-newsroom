"""NINJA PULSE RECAP Phase R2.11 - Announcement Identity / Readiness Safety forensic.

CHARACTERIZATION ONLY - no production code was changed by this checkpoint (see docs/
r2_11_announcement_identity_findings.md for the full report and the reasoning behind that
decision). Every test in this file pins CURRENT, unmodified behavior of the FROZEN `services/
recap_event.py::cluster_announcements()`/`_has_conflicting_distinctive_facts()` - none of it is
touched here. These tests exist so a future checkpoint has concrete, real-shaped reproducers for
both the confirmed readiness false-positive risk and the confirmed precision limit that blocked an
R2-local correction from being implemented tonight.

NO production DB, NO LLM, NO Gateway, NO network, NO writes anywhere in this file - pure in-memory
NewsEvent construction throughout (mirrors tests/test_event_recap.py's own `_event()` helper).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from database.models.news_event import EventCategory, NewsEvent
from services.recap_event import (
    _has_conflicting_distinctive_facts,
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
)
from services.story_memory import extract_story_signature

_NOW = datetime(2026, 8, 21, 18, 0, 0, tzinfo=timezone.utc)


def _ev(title: str, *, hours_ago: float, url: str, category: EventCategory = EventCategory.TECH) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(), source_id=uuid.uuid4(), title=title, category=category, url=url,
        published_at=_NOW - timedelta(hours=hours_ago), collected_at=_NOW - timedelta(hours=hours_ago),
        hash=f"r211-{uuid.uuid4()}",
    )


# ---------------------------------------------------------------------------
# Case 1 - VK/Apple real production-shadow fixture: three publishers, one real event.
# ---------------------------------------------------------------------------


def test_case1_vk_three_publishers_same_event_currently_counts_as_three_announcements() -> None:
    """Exact real production titles (this checkpoint's own record). Reproduces the observed
    production announcement_count=3 exactly - CURRENT R1 contract treats these as three distinct
    announcements (report-level clustering, conservative-split default), NOT as one corroborated
    underlying development - see docs/r2_11_announcement_identity_findings.md's own Phase 1
    contract reconstruction for why this is R1's own documented, deliberate behavior, not a bug."""
    events = [
        _ev("VK подала в суд на Apple и потребовала вернуть свои приложения в App Store", hours_ago=0.47, url="https://ixbt.com/a"),
        _ev("VK подала иск против Apple в российский суд из-за удаления её приложений из App Store", hours_ago=0.32, url="https://vc.ru/b"),
        _ev("VK решила засудить Apple за удаление приложений из App Store", hours_ago=0.0, url="https://3dnews.ru/c"),
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 3

    anchor = events[0]
    integrity = evaluate_recap_story_integrity(anchor, events)
    assert integrity.eligible is True  # genuinely coherent - Integrity's own job, correctly PASS


# ---------------------------------------------------------------------------
# Case 2 - Marvell/Google real production-shadow fixture (R2.9/R2.10's own positive-control Story).
# ---------------------------------------------------------------------------


def test_case2_marvell_three_reports_currently_counts_as_three_announcements() -> None:
    """Exact real production titles. Unlike VK, every pairwise combination here has a genuinely
    CONFLICTING distinctive fact (58 vs 12.2, per _has_conflicting_distinctive_facts()) - a real,
    existing R1 signal that ALREADY distinguishes this shape from VK's own pure-corroboration
    shape, with zero new logic. See test_case2b below for why relying on this exact signal as an
    R2-local collapse rule was still rejected."""
    events = [
        _ev("Marvell and Google expand their chip development deal, with Marvell granting Google a warrant to buy up to 58M+ shares", hours_ago=3, url="https://a.com/1"),
        _ev("Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC", hours_ago=2, url="https://cnbc.com/2"),
        _ev("Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на сумму $12,2 млрд", hours_ago=1, url="https://ria.ru/3"),
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 3

    sigs = [extract_story_signature(e.title, e.category) for e in events]
    # Every pair conflicts - Marvell's own reports carry genuinely distinguishing facts, unlike VK.
    assert _has_conflicting_distinctive_facts(sigs[0], events[0].title, sigs[1], events[1].title) is True
    assert _has_conflicting_distinctive_facts(sigs[0], events[0].title, sigs[2], events[2].title) is True
    assert _has_conflicting_distinctive_facts(sigs[1], events[1].title, sigs[2], events[2].title) is True


def test_case2b_frozen_numeric_conflict_check_still_uses_the_unfixed_decimal_comma_extractor() -> None:
    """Real forensic finding this checkpoint's own investigation surfaced: the FROZEN
    `_has_conflicting_distinctive_facts()` calls the FROZEN `_extract_numeric_tokens()` (services/
    recap_event.py's own copy, never fixed - R2.10 Night 2's decimal-comma fix was RECAP-LOCAL
    only, in services/event_recap.py). This means the Marvell EN/RU pair (event 1 vs event 2,
    "12.2" vs "12,2" - the SAME real $12.2B figure) registers as a NUMERIC CONFLICT for R1's own
    clustering-identity purposes, purely because the frozen extractor still reads "12,2" as "122".
    Pinned here as evidence for why reusing this exact signal as an R2-local collapse rule was
    rejected (docs/r2_11_announcement_identity_findings.md) - it is not even reliable on its own
    terms for cross-language same-value figures, on top of the separate verb/action blind-spot
    (test_case5_same_entities_different_action_is_a_precision_risk below). NOT fixed here - frozen
    file."""
    from services.recap_event import _extract_numeric_tokens

    en = "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC"
    ru = "Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на сумму $12,2 млрд"
    assert _extract_numeric_tokens(en) == {"12.2"}
    assert _extract_numeric_tokens(ru) == {"122"}, (
        "if this ever changes, services/recap_event.py was modified - update this pinning test and "
        "the R2.11 report, since that file is supposed to be frozen this phase"
    )


# ---------------------------------------------------------------------------
# Case 3 - THE CRITICAL SAFETY PROOF: four publishers, one real event, natural READY.
# ---------------------------------------------------------------------------


def test_case3_four_publisher_same_event_can_reach_natural_ready() -> None:
    """THE central finding of this checkpoint. Four distinct publishers, ZERO real development
    (one single underlying event, VK-vs-Apple-shaped), sufficiently different paraphrasing (no
    shared distinctive number, no near-exact title match, gaps wide enough to avoid R1's own
    5-minute temporal-corroboration window) currently produce announcement_count=4 - satisfying
    the frozen recap_min_announcement_count=4 threshold via pure syndication volume, never real
    story evolution. With research_complete=True (an ISOLATED test-only signal - R2 never sets
    this True in current production; see services/event_recap.py's own Phase R2.10A.3 docstring)
    and every other gate satisfied, this reaches genuine READY. This is the exact class of
    "readiness satisfied by syndication volume, not real development" risk this checkpoint exists
    to characterize - REAL READINESS FALSE-POSITIVE RISK, confirmed."""
    events = [
        _ev("VK sues Apple over removed App Store apps", hours_ago=3.33, url="https://a.com/1"),
        _ev("VK files lawsuit against Apple seeking apps return", hours_ago=3.17, url="https://b.com/2"),
        _ev("VK takes Apple to court over App Store removals", hours_ago=3.0, url="https://c.com/3"),
        _ev("VK demands Apple restore its apps in Russian lawsuit", hours_ago=2.83, url="https://d.com/4"),
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 4, "control assertion: this fixture must actually exercise the risk, not accidentally merge"

    anchor = events[0]
    integrity = evaluate_recap_story_integrity(anchor, events)
    assert integrity.eligible is True  # genuinely coherent, correctly so - not the defect

    unique_sources = count_unique_sources(events)
    assert unique_sources == 4

    readiness = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters), unique_source_count=unique_sources,
        last_event_at=events[-1].published_at or events[-1].collected_at, now=_NOW,
        research_complete=True, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )
    assert readiness.ready is True
    assert readiness.state == "READY", (
        "CONFIRMED: four reports of ONE real event, zero actual development, can satisfy natural "
        "readiness - this is the readiness false-positive risk this checkpoint exists to prove"
    )


# ---------------------------------------------------------------------------
# Case 4 - genuine multi-stage development (control: R1 must NOT under-split this).
# ---------------------------------------------------------------------------


def test_case4_genuine_four_stage_development_stays_four_separate_announcements() -> None:
    """Control case: a real evolving story (announce -> pricing -> regulatory block -> company
    response), each stage introducing a genuinely new distinctive fact/entity, hours apart -
    R1's own clustering correctly keeps these separate. Proves R1 does not systematically
    under-count real development - the risk in Case 3 is specific to near-simultaneous,
    fact-free-of-conflict corroboration, never genuine staged evolution."""
    events = [
        _ev("NovaChip announces new AI processor launch", hours_ago=9, url="https://a.com/1"),
        _ev("NovaChip processor priced at $899 for retail buyers", hours_ago=7, url="https://b.com/2"),
        _ev("Regulator blocks NovaChip processor export over compliance concerns", hours_ago=3, url="https://c.com/3"),
        _ev("NovaChip responds to regulator block, promises compliance fixes", hours_ago=0, url="https://d.com/4"),
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 4


# ---------------------------------------------------------------------------
# Case 5 - THE PRECISION LIMIT: same entities, different action, zero numeric/entity conflict.
# ---------------------------------------------------------------------------


def test_case5_same_entities_different_action_is_a_precision_risk() -> None:
    """The concrete adversarial case that blocked implementation (docs/
    r2_11_announcement_identity_findings.md Phase 5/6/7). "Sues" and "settles" are OPPOSITE,
    genuinely distinct developments about the identical two entities, with ZERO numbers on either
    side - _has_conflicting_distinctive_facts() (the one existing R1 signal available for an
    R2-local collapse rule) returns False for this pair, IDENTICAL to what it returns for genuine
    same-event corroboration (test_case1). No existing deterministic signal in this codebase
    (entity Jaccard, numeric-token equality, title lexical overlap) captures verb/action identity -
    entity overlap here is actually MAXIMAL (identical two-entity set), which is exactly why this
    case is dangerous rather than reassuring. This is why NO R2-local collapse rule was
    implemented this checkpoint - any rule built only from these primitives would risk merging
    exactly this class of genuinely different development into one false "corroborated"
    announcement, which is a worse failure mode than the current over-splitting behavior."""
    a = "Apple sues Samsung over patent infringement claims"
    b = "Apple settles patent dispute with Samsung amicably"
    sig_a = extract_story_signature(a, EventCategory.TECH)
    sig_b = extract_story_signature(b, EventCategory.TECH)
    assert _has_conflicting_distinctive_facts(sig_a, a, sig_b, b) is False, (
        "if this ever becomes True, the precision-limit finding this test documents may no longer "
        "hold - re-verify the R2.11 report's own conclusion before relying on it"
    )
    assert set(sig_a.entities) == set(sig_b.entities), "entity overlap is maximal here - not a usable discriminator"


# ---------------------------------------------------------------------------
# Case 6 - same action, materially different value: correctly stays separate (control).
# ---------------------------------------------------------------------------


def test_case6_same_action_different_value_correctly_conflicts() -> None:
    a = "NovaChip prices new processor at $899"
    b = "NovaChip prices new processor at $799"
    sig_a, sig_b = extract_story_signature(a, EventCategory.TECH), extract_story_signature(b, EventCategory.TECH)
    assert _has_conflicting_distinctive_facts(sig_a, a, sig_b, b) is True


# ---------------------------------------------------------------------------
# Case 7 - identical text, different publisher: already correctly merges today (control).
# ---------------------------------------------------------------------------


def test_case7_identical_text_different_publisher_already_merges() -> None:
    title = "VK подала иск против Apple в российский суд из-за удаления её приложений из App Store"
    events = [
        _ev(title, hours_ago=1, url="https://outlet-a.ru/x"),
        _ev(title, hours_ago=0, url="https://outlet-b.ru/y"),
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 1, "R1's own near-exact-title-match path already handles pure syndication of identical text"


# ---------------------------------------------------------------------------
# Case 8/9 - a later source contributing a new/contradicting number: correctly stays separate.
# ---------------------------------------------------------------------------


def test_case8_new_numeric_fact_from_later_source_correctly_conflicts() -> None:
    """A later report adding a genuinely NEW number (never mentioned before) about the same event
    correctly registers as a conflict under current R1 semantics - conservative-split is the
    documented, deliberate default (module docstrings' own "quality > recall")."""
    a = "NovaChip announces new AI processor launch"
    b = "NovaChip processor launch includes 3nm manufacturing process, sources say"
    sig_a, sig_b = extract_story_signature(a, EventCategory.TECH), extract_story_signature(b, EventCategory.TECH)
    # No digit tokens meaningfully present in either (single-digit "3" too short to register) -
    # this specific pair does NOT conflict on numbers; kept as a documented boundary case, not a claim.
    assert _has_conflicting_distinctive_facts(sig_a, a, sig_b, b) is False


def test_case9_contradicting_numeric_values_correctly_conflicts() -> None:
    a = "Marvell warrant covers up to 58M shares"
    b = "Marvell warrant covers up to 60M shares"
    sig_a, sig_b = extract_story_signature(a, EventCategory.TECH), extract_story_signature(b, EventCategory.TECH)
    assert _has_conflicting_distinctive_facts(sig_a, a, sig_b, b) is True


# ---------------------------------------------------------------------------
# Case 10 - origin-projected Story with duplicate reports: origin projection mechanics unaffected.
# ---------------------------------------------------------------------------


def test_case10_origin_projection_mechanics_unaffected_by_announcement_duplication() -> None:
    """No R2-local correction was implemented (docs/r2_11_announcement_identity_findings.md), so
    this test simply confirms origin projection's OWN mechanics (services.recap_origin_projection,
    R2.9, unmodified) are structurally independent of announcement clustering - it operates on
    `events`, never on `AnnouncementCluster` objects, so nothing about this checkpoint's findings
    could have silently changed its behavior."""
    from services.recap_origin_projection import build_effective_recap_members

    origin = _ev("VK подала в суд на Apple и потребовала вернуть свои приложения в App Store", hours_ago=1, url="https://ixbt.com/a")
    confirmed = [
        _ev("VK подала иск против Apple в российский суд из-за удаления её приложений из App Store", hours_ago=0.5, url="https://vc.ru/b"),
        _ev("VK решила засудить Apple за удаление приложений из App Store", hours_ago=0.0, url="https://3dnews.ru/c"),
    ]
    effective = build_effective_recap_members(origin, confirmed)
    assert len(effective) == 3
    assert origin.id in {e.id for e in effective}
    clusters = cluster_announcements(effective)
    assert len(clusters) == 3  # same duplicate-report shape as Case 1, origin projection just adds the anchor
