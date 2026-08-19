"""NINJA PULSE RECAP Phase R1.4 - announcement identity precedence + clustering regression matrix
(spec's own required fixture set, items 4/13). Pure-function tests only - no DB, no network, no
LLM, fully offline/deterministic. Built from the real R1.3 production replay findings.

Every MUST-COLLAPSE fixture below deliberately spaces its events within a few minutes of each
other (near-simultaneous syndicated/paraphrased pickup of ONE real announcement - realistic for
multiple outlets republishing the same wire story or regional press release). Every MUST-REMAIN-
SEPARATE fixture spaces its events well outside the 5-minute distinctive-evidence temporal window
(a real staged announcement sequence, or genuinely different developments within one incident) -
this distinction is the deliberate R1.4 design (see services/recap_event.py::
_has_distinctive_shared_evidence()'s own docstring)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from database.models.news_event import EventCategory, NewsEvent
from services.recap_event import cluster_announcements, evaluate_recap_story_integrity

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _event(*, title: str, minutes_ago: float) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(), source_id=uuid.uuid4(), title=title, category=EventCategory.TECH,
        url=f"https://example.com/{uuid.uuid4()}",
        published_at=_NOW - timedelta(minutes=minutes_ago), collected_at=_NOW - timedelta(minutes=minutes_ago),
        hash=f"h-{uuid.uuid4()}",
    )


def _tight(*titles: str, gap_minutes: float = 2.0) -> list[NewsEvent]:
    """Events spaced `gap_minutes` apart, chronological - well within the 5-minute distinctive-
    evidence temporal window used throughout the MUST-COLLAPSE fixtures below."""
    n = len(titles)
    return [_event(title=t, minutes_ago=(n - i - 1) * gap_minutes) for i, t in enumerate(titles)]


def _wide(*titles: str, gap_minutes: float = 45.0) -> list[NewsEvent]:
    """Events spaced `gap_minutes` apart - well outside the temporal window, for the MUST-REMAIN-
    SEPARATE fixtures (a real staged sequence or genuinely different developments)."""
    n = len(titles)
    return [_event(title=t, minutes_ago=(n - i - 1) * gap_minutes) for i, t in enumerate(titles)]


# ---------------------------------------------------------------------------
# MUST COLLAPSE TO 1 (spec item 13, A-E)
# ---------------------------------------------------------------------------


def test_case_a_three_identical_titles_collapse_to_one():
    title = "The rapid growth of social media has greatly influenced political discourse in modern societies"
    events = _tight(title, title, title)
    clusters = cluster_announcements(events)
    assert len(clusters) == 1
    assert len(clusters[0].event_ids) == 3


def test_case_b_same_headline_different_publisher_suffix_collapses_to_one():
    events = _tight(
        "Apple unveils new AI features for iPhone - 3DNews",
        "Apple unveils new AI features for iPhone - Хабр",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1


def test_case_c_six_syndicated_classroom_variants_collapse_to_one():
    events = _tight(
        "Schools embrace AI and VR tools to modernize classrooms",
        "Schools embrace AI and VR tools to modernize classrooms - Yahoo Finance",
        "Schools are embracing AI and VR tools to modernize classrooms",
        "Schools embrace AI, VR tools to modernize classrooms",
        "How schools embrace AI and VR tools to modernize classrooms",
        "Schools embrace AI and VR tools in classroom modernization push",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1
    assert len(clusters[0].event_ids) == 6


def test_case_d_four_taiwan_dividend_variants_safely_split_not_forced_merge():
    """Phase R1.4.2 correction (spec §5's own explicit "if safely supported" hedge on this exact
    fixture, and its "prefer conservative split over unsafe general merge - quality > recall"
    instruction): once temporal distinctive evidence is restricted to the cluster's STABLE
    REFERENCE only (spec §6's own required anti-chain fix - see test_temporal_evidence_anti_chain_
    c_does_not_join_through_b below), the 4th real variant ("Taiwan approves $314 AI dividend
    payment for every citizen") no longer has ANY qualifying connection to the stable reference
    (title #0) - measured directly, its entity-excluded content overlap with #0 is 0.0, below the
    0.20 floor - so it cannot be safely corroborated into the same cluster. This is the disclosed,
    safe outcome: 2 clusters (a 3-member cluster of #0/#1/#2, plus #3 alone), not a forced 1."""
    events = _tight(
        "Taiwan will pay every citizen about $314 as part of new AI dividend",
        "Taiwan will pay every citizen $314 under new AI dividend program",
        "Taiwan to pay all citizens dividends worth $314 from AI fund",
        "Taiwan approves $314 AI dividend payment for every citizen",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2
    sizes = sorted(len(c.event_ids) for c in clusters)
    assert sizes == [1, 3]


def test_case_e_bashkiria_regional_variants_safely_split_not_forced_merge():
    """Phase R1.4.2 correction (spec §5's own explicit "if safely supported" hedge on this exact
    fixture, and its "prefer conservative split over unsafe general merge - quality > recall"
    instruction). Once temporal distinctive evidence is restricted to the cluster's STABLE
    REFERENCE only (title #0), only title #1 (entity-excluded overlap 0.429 with #0) still connects
    directly to it; titles #2 and #3 do not (0.0 and measured-low against #0), but #2 and #3
    connect to EACH OTHER (0.6, well above the floor) once #2 becomes its own cluster's own stable
    reference. Measured, disclosed outcome: 2 clusters of 2 members each, not a forced 1."""
    events = _tight(
        "В Башкирии обозначили направления развития искусственного интеллекта в медицине",
        "В Башкирии определены приоритеты внедрения искусственного интеллекта в медицину",
        "Башкирия внедряет искусственный интеллект в медицину",
        "В Башкирии внедряют искусственный интеллект в медицину",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2
    sizes = sorted(len(c.event_ids) for c in clusters)
    assert sizes == [2, 2]


# ---------------------------------------------------------------------------
# MUST REMAIN SEPARATE (spec item 13, F-H)
# ---------------------------------------------------------------------------


def test_case_f_apple_launch_pricing_watch_ai_feature_remain_separate():
    events = _wide(
        "Apple unveils iPhone X",
        "Apple announces iPhone X pricing",
        "Apple reveals Watch Ultra 3",
        "Apple introduces new AI feature for Siri",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 4


def test_case_g_distinct_developments_within_one_security_incident_remain_separate():
    events = _wide(
        "Hugging Face confirms data breach affecting OpenAI models",
        "OpenAI patches vulnerability exposed by Hugging Face breach",
        "Regulators open investigation into Hugging Face breach fallout",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 3


def test_case_h_qwen_launch_vs_materially_new_later_model_remain_separate():
    events = _wide(
        "Qwen 3.8 27B launches with major reasoning upgrade",
        "Alibaba releases Qwen 4.0 with a completely new architecture",
        gap_minutes=60 * 24 * 10,  # ~10 days apart - a genuinely later, separate model release
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2


# ---------------------------------------------------------------------------
# OpenAI / Hugging Face - real production case, 5 reports of the same core announcement
# ---------------------------------------------------------------------------


def test_openai_hugging_face_five_reports_collapse_substantially():
    """R1.3 production replay: 5 reports at threshold 0.75 produced 5 separate clusters -
    "unsuitable for recap_min_announcement_count" per spec §3.E. These 5 titles paraphrase the
    same core fact (OpenAI changed safeguards after the Hugging Face incident) closely enough,
    published near-simultaneously, that they should now collapse substantially - not necessarily
    to exactly 1 (spec item 3.E says "most/all describe the same core announcement," not
    "all 5 are byte-identical"), but far fewer than 5.

    Phase R1.4.2 disclosed result: restricting temporal distinctive evidence to the cluster's
    stable reference (spec §6's mandatory anti-chain fix) produces 3 clusters here (a dominant
    3-member cluster, plus 2 singletons), one more than R1.4.1's own "<=2" result - measured
    directly: titles #3 ("OpenAI updates safety policy following Hugging Face incident") and #4
    ("How the Hugging Face breach led OpenAI to change its safeguards") both measure 0.0 entity-
    excluded content overlap against the cluster's stable reference (title #0), so neither can be
    safely corroborated into it even via temporal proximity. This is the same "prefer conservative
    split over unsafe general merge" tradeoff already accepted for Taiwan/Bashkiria (spec §5),
    disclosed here rather than forced to a tighter bound the safe algorithm cannot honestly reach -
    3 clusters is still a substantial, real improvement over R1.3's original 5."""
    events = _tight(
        "Hugging Face confirms data breach affecting OpenAI models",
        "OpenAI tightens safeguards after Hugging Face security breach",
        "Security researchers detail Hugging Face breach impact on OpenAI",
        "OpenAI updates safety policy following Hugging Face incident",
        "How the Hugging Face breach led OpenAI to change its safeguards",
        gap_minutes=1.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) < 5
    assert max(len(c.event_ids) for c in clusters) >= 3  # a real, dominant same-announcement cluster still forms


# ---------------------------------------------------------------------------
# ADRES - same announcement with different publisher suffixes
# ---------------------------------------------------------------------------


def test_adres_ai_practice_launch_different_publisher_suffixes_collapse_to_one():
    events = _tight(
        "ADRES launches new artificial intelligence practice",
        "ADRES launches new artificial intelligence practice - The AI Journal",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1


# ---------------------------------------------------------------------------
# Phase R1.4.1 - anti-chaining safety regressions
# ---------------------------------------------------------------------------


def test_anti_chain_c_does_not_join_through_b_on_ordinary_fuzzy_evidence_alone():
    """Spec R1.4.1 §5's mandatory anti-chain test. Real measured values (no entities involved on
    either side - a clean, isolated test of the ordinary weighted-fuzzy tier specifically):
    sim(A,B) = 0.769 >= 0.75 (may cluster)
    sim(B,C) = 0.769 >= 0.75
    sim(A,C) = 0.600 <  0.75 (must NOT cluster directly)
    Expected: A and B cluster together; C must NOT join that cluster through B on ordinary fuzzy
    evidence alone - it must land in its own, separate cluster."""
    events = _tight(
        "battery life gains this quarter",
        "battery life gains and camera zoom gains this quarter",
        "camera zoom gains this quarter",
        gap_minutes=10.0,  # outside the 5-minute distinctive-evidence window - isolates pure fuzzy
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2
    cluster_membership = [
        sorted(e.title for e in events if e.id in c.event_ids) for c in clusters
    ]
    assert sorted(["battery life gains this quarter", "battery life gains and camera zoom gains this quarter"]) in cluster_membership
    assert ["camera zoom gains this quarter"] in cluster_membership


def test_numeric_conflict_blocks_merge_despite_shared_entity_and_close_time():
    """Spec R1.4.1 §8: same company/product/time-window, but three DIFFERENT specific numbers
    (price/storage/ship-date) - must never merge solely because a shared entity ("Product X") and
    close timing are present. Numeric evidence only counts when the SAME number is shared."""
    events = _tight(
        "Apple sets Product X price at $999",
        "Apple confirms Product X storage options up to 256GB",
        "Apple reveals Product X ships on the 18th",
        gap_minutes=1.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 3


def test_live_event_five_distinct_announcements_pass_integrity_stay_separate():
    """Spec R1.4.1 §9: one coherent live event (Story Integrity PASS), five GENUINELY separate
    announcements (unveil / price / availability / a different product / a different feature),
    all published within a 1-4 minute window - directly exercises the unsafe "shared entity + close
    time" path this checkpoint fixes. None of these five titles are exact/near-exact of each other,
    so none should merge."""
    events = _tight(
        "Apple unveils Product X",
        "Apple announces Product X price $999",
        "Apple announces Product X availability September 18",
        "Apple unveils Watch Y",
        "Apple announces AI Feature Z",
        gap_minutes=1.0,
    )
    integrity = evaluate_recap_story_integrity(events[0], events)
    assert integrity.eligible is True

    clusters = cluster_announcements(events)
    assert len(clusters) == 5


# ---------------------------------------------------------------------------
# Phase R1.4.2 - temporal evidence must SUPPORT content, never PROVE identity by itself
# ---------------------------------------------------------------------------


def test_apple_camera_vs_battery_isolated_temporal_path_stays_separate():
    """Spec R1.4.2 §2's exact counterexample, with wording chosen to isolate the temporal-evidence
    path specifically (see the R1.4.2 report's own item A/B for why the LITERAL "Apple announces
    iPhone camera improvements" / "...battery improvements" wording is a poor isolated test - it
    also independently clears the FROZEN ordinary-fuzzy threshold via sheer sentence-template
    similarity, 0.88, regardless of the temporal-evidence bug being tested here). This wording
    keeps the same real-world shape (shared "Apple"/"iPhone" entities, no conflicting fact, 2
    minutes apart, genuinely different product aspects) while measuring low on both ordinary fuzzy
    (0.57) and the entity-excluded content floor (0.17 < 0.20) - a clean, isolated proof that the
    temporal path itself no longer merges on entity+time alone."""
    events = _tight(
        "Apple improves iPhone camera low-light performance",
        "Apple extends iPhone battery life with new update",
        gap_minutes=2.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2


def test_apple_camera_vs_battery_literal_wording_disclosed_frozen_mechanism():
    """Disclosed, not hidden: the LITERAL spec §2 wording ("Apple announces iPhone camera
    improvements" / "Apple announces iPhone battery improvements") still merges - via the FROZEN
    ordinary weighted-fuzzy path (measured 0.88, driven by the "Apple announces iPhone X
    improvements" template shared almost verbatim), which this checkpoint's own accepted/frozen
    list explicitly puts out of scope ("ordinary fuzzy similarity uses stable cluster reference" -
    the MECHANISM is frozen, and this pair's high score is a property of the frozen 0.4/0.6
    weighting applied to genuinely high template overlap, not the temporal-evidence bug R1.4.2
    fixes). See test_apple_camera_vs_battery_isolated_temporal_path_stays_separate above for a
    clean proof that the temporal path itself is fixed, independent of this pre-existing,
    out-of-scope interaction."""
    events = _tight(
        "Apple announces iPhone camera improvements",
        "Apple announces iPhone battery improvements",
        gap_minutes=2.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1  # frozen ordinary-fuzzy mechanism, not the temporal path - disclosed above


def test_google_gemini_performance_vs_safety_stays_separate():
    """Spec R1.4.2 §2's second counterexample, isolated wording (see the note on the Apple test
    above - the literal "Google announces Gemini API performance/safety improvements" wording also
    independently clears the frozen ordinary-fuzzy threshold at 0.90 via template similarity)."""
    events = _tight(
        "Google speeds up Gemini API response times for developers",
        "Google strengthens Gemini API content safety filters",
        gap_minutes=2.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2



# ---------------------------------------------------------------------------
# Phase R1.5B.1 - publisher-suffix evidence sanitization (real R1.5B production forensic finding:
# a trailing publisher/source-suffix segment - "Ведомости"/"Хабр"/"Эксперт"/"CNews.ru" - is captured
# as its own spurious entity by the SAME capitalized-run heuristic that correctly captures real
# entities, artificially lowering entity jaccard and falsely triggering
# `_has_conflicting_distinctive_facts()`'s entity-asymmetry check for reports that share every real
# content fact and differ only in which outlet published them).
# ---------------------------------------------------------------------------


def test_taiwan_real_production_titles_three_same_dividend_reports_collapse_despite_different_publishers():
    """Real production titles, verbatim, from the R1.5B.1 checkpoint message. Before this fix,
    production measured entity_jaccard=0.500 and `has_conflicting_distinctive_facts=True` for every
    pair among A/B/C - caused entirely by each report's own different publisher entity (Ведомости/
    Хабр/Эксперт) being added as a non-overlapping fourth set member, not by any real content
    difference (all three share тайвань/ии and the same $314 figure). After publisher-suffix
    sanitization, A/B/C collapse into one cluster; D (the 4th real title - materially weaker
    lexical overlap AND genuinely omits the $314 figure entirely, a real distinguishing fact, not
    publisher noise) correctly stays out - 4 -> 2, not forced to 1 (spec R1.5B.1 §7's own explicit
    "the requirement is NOT 'Taiwan must become 1'")."""
    events = _wide(
        "Тайвань выплатит каждому гражданину страны около $314 «дивидендов от ИИ» - Ведомости",
        "Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
        "Тайвань выплатит каждому гражданину «дивиденды от ИИ» в $314 - Эксперт",
        "Тайвань выплатит всем своим гражданам «дивиденды» от мирового бума ИИ - CNews.ru",
        gap_minutes=75.0,  # real production gap order-of-magnitude (45-300 minutes apart per R1.5B)
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2
    sizes = sorted(len(c.event_ids) for c in clusters)
    assert sizes == [1, 3]

    titles_by_id = {e.id: e.title for e in events}
    dividend_cluster = next(c for c in clusters if len(c.event_ids) == 3)
    merged_titles = {titles_by_id[eid] for eid in dividend_cluster.event_ids}
    assert not any("CNews" in t for t in merged_titles)  # the genuinely weaker 4th report never joins


def test_publisher_suffix_conflict_disappears_only_when_content_facts_actually_match():
    """spec R1.5B.1 §6's exact required safety property: the SAME number ($314), reported by
    different publishers, must not be treated as conflicting merely because the publisher entities
    differ - two of the three real Taiwan reports (near-identical wording, different publisher)
    must land in the very same cluster."""
    events = _tight(
        "Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
        "Тайвань выплатит каждому гражданину «дивиденды от ИИ» в $314 - Эксперт",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1


def test_genuine_numeric_conflict_survives_publisher_suffix_sanitization():
    """spec R1.5B.1 §11 mandatory negative control: a genuinely DIFFERENT number ($314 vs $500),
    reported under two different publisher suffixes, must remain conflicting and must NOT merge -
    publisher-suffix sanitization must remove publisher noise, never substantive identity
    evidence. (This is also the exact regression this checkpoint found and fixed within
    `_announcement_similarity()` itself - see that function's own docstring - publisher
    sanitization legitimately raises entity_jaccard for same-content pairs, which without an
    explicit conflict guard could let two titles differing only in a conflicting number cross the
    ordinary-fuzzy threshold on title overlap alone.)"""
    events = _tight(
        "Taiwan approves $314 AI dividend for every citizen - Reuters",
        "Taiwan approves $500 AI dividend for every citizen - Bloomberg",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2


def test_genuinely_distinct_content_survives_publisher_suffix_sanitization():
    """spec R1.5B.1 §11 mandatory negative control: two genuinely different developments (a cash
    payment vs. a factory opening), reported under two different publisher suffixes, must not merge
    merely because their publisher entities were removed - only the shared "Taiwan" entity and
    weak title overlap remain, nowhere near the 0.75 threshold."""
    events = _tight(
        "Taiwan approves $314 AI dividend for every citizen - Reuters",
        "Taiwan opens new semiconductor factory near Hsinchu - Bloomberg",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2


def test_ai_vr_classrooms_control_with_different_publisher_suffixes_still_collapses_to_one():
    """spec R1.5B.1 §12: a known-good near-exact/syndicated case, reconstructed with a DIFFERENT
    publisher suffix on every title (unlike the original test_case_c fixture above, which uses only
    one publisher suffix and otherwise-bare titles) - must still collapse to one cluster after
    publisher-suffix sanitization, proving the near-exact/syndicated path is unaffected."""
    events = _tight(
        "Schools embrace AI and VR tools to modernize classrooms - EdTech Weekly",
        "Schools are embracing AI and VR tools to modernize classrooms - Campus Technology",
        "How schools embrace AI and VR tools to modernize classrooms - The Hechinger Report",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1


def test_adres_control_with_three_different_publisher_suffixes_still_collapses_to_one():
    """spec R1.5B.1 §13: extends the existing 2-title/1-suffix ADRES fixture above to 3 titles, each
    under a DIFFERENT publisher suffix - still collapses to one cluster."""
    events = _tight(
        "ADRES launches new artificial intelligence practice - Portafolio",
        "ADRES launches new artificial intelligence practice - El Tiempo",
        "ADRES launches new artificial intelligence practice - La Republica",
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 1


def test_openai_hugging_face_with_publisher_suffixes_stays_conservative_not_force_merged():
    """spec R1.5B.1 §14: the existing 5-report OpenAI/Hugging Face fixture (test_openai_hugging_
    face_five_reports_collapse_substantially above), reconstructed with a different publisher
    suffix added to every title. Verifies only the conservative safety bounds spec §8/§14 require:
    no unsafe broad merge (never all 5 forced into 1), and the 0.75 threshold is not being crossed
    by weak pairs merely because publisher-suffix sanitization raised their entity_jaccard - a
    dominant same-announcement cluster may still legitimately form, exactly as it already does
    without publisher suffixes."""
    events = _tight(
        "Hugging Face confirms data breach affecting OpenAI models - TechCrunch",
        "OpenAI tightens safeguards after Hugging Face security breach - The Verge",
        "Security researchers detail Hugging Face breach impact on OpenAI - Ars Technica",
        "OpenAI updates safety policy following Hugging Face incident - VentureBeat",
        "How the Hugging Face breach led OpenAI to change its safeguards - Wired",
        gap_minutes=1.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) > 1  # never a single unsafe forced merge
    assert len(clusters) < 5  # a real dominant cluster may still legitimately form


def test_temporal_evidence_anti_chain_c_does_not_join_through_b():
    """Spec R1.4.2 §6's mandatory temporal any-member chaining test. Real measured values (same
    entity, "openai", shared throughout; no conflicting fact anywhere):
    entity-excluded overlap(A,B) = 0.526 (qualifies)
    entity-excluded overlap(B,C) = 0.316 (qualifies)
    entity-excluded overlap(A,C) = 0.125 (does NOT qualify, < 0.20 floor)
    Before this checkpoint's stable-reference restriction, C joined A/B's cluster via chaining
    through B despite failing directly against A. Expected: A and B may cluster; C must NOT join
    through B on temporal distinctive evidence alone."""
    events = _tight(
        "OpenAI announces new safety research initiative for enterprise customers",
        "OpenAI safety research initiative gains support from enterprise customers and academic partners",
        "OpenAI partners with academic institutions on long-term alignment research funding",
        gap_minutes=2.0,
    )
    clusters = cluster_announcements(events)
    assert len(clusters) == 2
    cluster_sizes = sorted(len(c.event_ids) for c in clusters)
    assert cluster_sizes == [1, 2]
