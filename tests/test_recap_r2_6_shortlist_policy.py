"""NINJA PULSE RECAP Phase R2.6a - broader-shadow shortlist policy correction tests.

Pure, offline tests against `scripts/_recap_r2_6_broader_shadow_candidate_selection.py`'s own
diagnostic-only classification functions - no DB, no LLM, no network. Loaded the same way
`tests/test_recap_r2_single_attempt_gateway.py` already loads a `scripts/_recap_*` module (that
directory is not a package), via `importlib.util.spec_from_file_location`.

Covers exactly the six regression categories the R2.6a checkpoint required:
    1. already-calibrated Story exclusion (Sverdlovsk + Taiwan)
    2. academic-abstract conservative detection (calibrated against the two real production
       titles the checkpoint reported)
    3. real product/news headline not falsely rejected
    4. routine finance/investment rejection
    5. maximum one minimal edge case in a selected shortlist
    6. quality-over-quota behavior (fewer than TARGET_SHORTLIST when fewer genuinely qualify)
plus one guard test tying `_relevance_accepted()`'s hardcoded neutral-default reason string to
`services/news_editorial_relevance.py`'s own real, unmodified output.

R2.6b additions: the real Nvidia insider-stock-purchase Story is now caught by the extended
`_is_finance_advice_like()`, a normal hardware "in stock" (inventory-availability) headline is
proven to NOT false-positive, and `_evidence_shape_reason()`/`_quality_preflight()` are proven to
read the SYNTHESIS-PROJECTED facts rather than the raw forensic set (spec item 10's own "truthful
evidence shape" requirement).
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from services.event_recap import EventRecapCandidate
from services.news_editorial_relevance import classify_editorial_relevance


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_recap_r2_6_shortlist_policy_test_import",
        "scripts/_recap_r2_6_broader_shadow_candidate_selection.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r26 = _load_module()

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _minimal_candidate(*, announcement_count: int, evidence_reference_count: int = 1, verified_facts=()) -> EventRecapCandidate:
    return EventRecapCandidate(
        story_id=uuid4(), anchor_event_id=uuid4(), story_title="placeholder", generated_at=_NOW,
        readiness_state="COOLING", readiness_overridden=True, story_integrity_eligible=True,
        story_integrity_reasons=[], announcement_count=announcement_count, readiness_source_count=1,
        evidence_reference_count=evidence_reference_count, announcements=[], timeline=[],
        verified_facts=list(verified_facts), source_refs=[], media_candidates=[],
    )


def _usable_record(
    story_id: UUID, *, announcement_count: int, quality_verdict: str = "PASS",
    editorial_event_class: str = "NEWS_EVENT", shortlist_eligible: bool = True,
) -> dict:
    class _StoryStub:
        def __init__(self, id_: UUID) -> None:
            self.id = id_

    candidate = _minimal_candidate(announcement_count=announcement_count)
    return {
        "story": _StoryStub(story_id), "candidate": candidate,
        "relevance": classify_editorial_relevance("placeholder"),
        "quality_verdict": quality_verdict, "quality_dims": {}, "hygiene_findings": [],
        "bundle_text": "", "projected": list(candidate.verified_facts),
        "original_ready": False, "is_research_abstract": False,
        "is_finance_advice": False, "relevance_accepted": True,
        "editorial_event_class": editorial_event_class, "shortlist_eligible": shortlist_eligible,
    }


# ---------------------------------------------------------------------------
# 1. Already-calibrated Story exclusion
# ---------------------------------------------------------------------------


def test_sverdlovsk_and_taiwan_are_both_hard_excluded():
    assert UUID("60be3f72-28d3-4c5a-af65-f0550923fe94") in r26.EXCLUDED_STORY_IDS
    assert UUID("859ffea0-9b54-41cb-be25-13c061ca75ad") in r26.EXCLUDED_STORY_IDS


# ---------------------------------------------------------------------------
# 2. Academic-abstract conservative detection (real production titles)
# ---------------------------------------------------------------------------


def test_real_production_abstract_titles_are_detected():
    assert r26._is_research_abstract_like(
        "Diffusion models have recently shown strong potential for multivariate "
        "time-series anomaly detection..."
    )
    assert r26._is_research_abstract_like(
        "On-policy distillation (OPD) offers a promising way to improve model performance..."
    )


def test_generic_academic_openers_are_detected():
    assert r26._is_research_abstract_like("We propose a novel framework for image segmentation")
    assert r26._is_research_abstract_like("This study examines the effects of pruning on LLMs")
    assert r26._is_research_abstract_like("In this paper, we present a new benchmark dataset")


# ---------------------------------------------------------------------------
# 3. Real product/news headlines are NOT falsely rejected
# ---------------------------------------------------------------------------


def test_real_headlines_are_never_flagged_as_research_abstracts():
    real_headlines = [
        "Apple unveils new $999 Watch Ultra with titanium casing",
        "Nvidia releases new GPU driver update",
        "Google unveils updated Gemini model with new reasoning mode",
        "Samsung launches Galaxy S25 with new AI features",
        "OpenAI launches GPT-X after raising $10B",
        "Microsoft ships security update for actively exploited vulnerability",
        "Israel Launches National AI Action Plan",
        "В Якутии разрабатывают проект создания дальневосточного ИИ-кластера",
    ]
    for title in real_headlines:
        assert not r26._is_research_abstract_like(title), title
        assert not r26._is_finance_advice_like(title), title


def test_real_headlines_are_relevance_accepted_when_genuinely_core_or_adjacent():
    decision = classify_editorial_relevance("Apple unveils new $999 Watch Ultra with titanium casing")
    assert decision.tier == "CORE"
    assert r26._relevance_accepted(decision)


# ---------------------------------------------------------------------------
# 4. Finance/investment rejection
# ---------------------------------------------------------------------------


def test_finance_advice_titles_are_detected():
    assert r26._is_finance_advice_like("Should You Buy This AI Stock Now?")
    assert r26._is_finance_advice_like("The World's Newest AI Billionaire Has a Net Worth of $12 Billion")
    assert r26._is_finance_advice_like("Top Stocks to Buy Before the AI Boom")


# ---------------------------------------------------------------------------
# Root-cause guard: the "neutral default" ADJACENT branch is correctly rejected
# ---------------------------------------------------------------------------


def test_neutral_default_adjacent_is_rejected_but_genuine_adjacent_is_accepted():
    neutral = classify_editorial_relevance(
        "Открыт предзаказ на второе издание «Грокаем алгоритмы искусственного интеллекта»"
    )
    assert neutral.tier == "ADJACENT"
    assert neutral.reason == r26._NEUTRAL_DEFAULT_RELEVANCE_REASON
    assert not r26._relevance_accepted(neutral)

    genuine_adjacent = classify_editorial_relevance("New humanoid robot unveiled at trade show")
    assert genuine_adjacent.tier == "ADJACENT"
    assert genuine_adjacent.reason != r26._NEUTRAL_DEFAULT_RELEVANCE_REASON
    assert r26._relevance_accepted(genuine_adjacent)


def test_neutral_default_reason_string_matches_production():
    """Ties the hardcoded diagnostic-only reason string to the real, unmodified production
    classifier's actual output - if that module's own wording ever changes, this fails loudly
    instead of silently letting the neutral-default leak back into the shortlist."""
    decision = classify_editorial_relevance("a title with no keyword signal at all whatsoever")
    assert decision.tier == "ADJACENT"
    assert decision.reason == r26._NEUTRAL_DEFAULT_RELEVANCE_REASON


# ---------------------------------------------------------------------------
# 5. Maximum one minimal edge case per shortlist
# ---------------------------------------------------------------------------


def test_shortlist_never_includes_more_than_one_minimal_edge_case():
    usable = [
        _usable_record(uuid4(), announcement_count=1, editorial_event_class="MINIMAL_EDGE"),
        _usable_record(uuid4(), announcement_count=1, editorial_event_class="MINIMAL_EDGE"),
        _usable_record(uuid4(), announcement_count=3, editorial_event_class="NEWS_EVENT"),
        _usable_record(uuid4(), announcement_count=2, editorial_event_class="NEWS_EVENT"),
    ]
    shortlist = r26._select_shortlist(usable)
    minimal_count = sum(1 for u in shortlist if u["editorial_event_class"] == "MINIMAL_EDGE")
    assert minimal_count <= 1


# ---------------------------------------------------------------------------
# 6. Quality over quota
# ---------------------------------------------------------------------------


def test_shortlist_returns_fewer_than_target_when_corpus_does_not_support_target():
    usable = [
        _usable_record(uuid4(), announcement_count=3, editorial_event_class="NEWS_EVENT"),
        _usable_record(uuid4(), announcement_count=2, editorial_event_class="NEWS_EVENT"),
        _usable_record(uuid4(), announcement_count=1, quality_verdict="FAIL", shortlist_eligible=False),
        _usable_record(uuid4(), announcement_count=1, editorial_event_class="RESEARCH_ABSTRACT_REJECTED", shortlist_eligible=False),
    ]
    shortlist = r26._select_shortlist(usable)
    assert len(shortlist) == 2
    assert len(shortlist) < r26.TARGET_SHORTLIST


def test_shortlist_never_fabricates_ineligible_stories_to_reach_target():
    ineligible = [
        _usable_record(uuid4(), announcement_count=1, quality_verdict="FAIL", shortlist_eligible=False)
        for _ in range(5)
    ]
    shortlist = r26._select_shortlist(ineligible)
    assert shortlist == []


# ---------------------------------------------------------------------------
# R2.6b - finance-filter miss correction (real production finding: the Nvidia insider-stock-
# purchase Story slipped through the R2.6a finance filter and was classified MINIMAL_EDGE)
# ---------------------------------------------------------------------------

_NVIDIA_STOCK_TITLE = (
    "The CEO of This Nvidia-Backed Artificial Intelligence (AI) Chip Company Just Bought "
    "$10 Million of His Own Stock."
)


def test_nvidia_insider_stock_purchase_story_is_caught_by_finance_gate():
    assert r26._is_finance_advice_like(_NVIDIA_STOCK_TITLE)


def test_hardware_in_stock_availability_headline_is_not_falsely_rejected():
    """Distinguishes insider-stock-PURCHASE-disclosure language ("own stock", "bought shares")
    from ordinary inventory-availability language ("in stock", "back in stock") - a real,
    plausible NINJA PULSE headline must never be rejected by this gate."""
    real_headlines = [
        "Nvidia RTX 5090 GPU back in stock at major retailers",
        "iPhone 17 is now in stock at Apple Stores",
        "Nvidia unveils new GPU architecture with improved AI performance",
    ]
    for title in real_headlines:
        assert not r26._is_finance_advice_like(title), title
        assert not r26._is_research_abstract_like(title), title


# ---------------------------------------------------------------------------
# R2.6b - _evidence_shape_reason()/_quality_preflight() read PROJECTED facts, not raw ones
# (spec item 10 - "truthful evidence shape"; real Yakutia finding: raw "24" was publisher noise)
# ---------------------------------------------------------------------------


def _real_candidate(titles: list[str], story_title: str):
    """Builds a full candidate via the REAL pipeline (services.recap_event.cluster_announcements +
    services.event_recap._build_announcement_summaries/_build_verified_facts), so publisher-suffix
    numeric contamination and generic entity phrases actually manifest exactly as they would in
    production - unlike the bare _minimal_candidate() stub used elsewhere in this file."""
    from database.models.news_event import EventCategory, NewsEvent
    from services.event_recap import (
        EventRecapCandidate as _Candidate,
        _build_announcement_summaries,
        _build_verified_facts,
    )
    from services.recap_event import cluster_announcements

    events = [
        NewsEvent(
            id=uuid4(), source_id=uuid4(), title=t, category=EventCategory.TECH,
            url=f"https://example.com/{uuid4()}",
            published_at=_NOW - timedelta(minutes=(len(titles) - i - 1) * 30),
            collected_at=_NOW - timedelta(minutes=(len(titles) - i - 1) * 30),
            hash=f"h-{uuid4()}",
        )
        for i, t in enumerate(titles)
    ]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    facts = _build_verified_facts(summaries)
    source_refs = list(dict.fromkeys(ref for s in summaries for ref in s.source_refs))
    return _Candidate(
        story_id=uuid4(), anchor_event_id=events[0].id, story_title=story_title, generated_at=_NOW,
        readiness_state="COOLING", readiness_overridden=True, story_integrity_eligible=True,
        story_integrity_reasons=[], announcement_count=len(clusters), readiness_source_count=1,
        evidence_reference_count=len(source_refs), announcements=summaries, timeline=[],
        verified_facts=facts, source_refs=source_refs, media_candidates=[],
    )


def test_evidence_shape_reason_reflects_projected_facts_not_raw_publisher_noise():
    """The real Yakutia finding: raw verified_facts contains numeric "24" (publisher-suffix noise
    from "... - RuNews24"), but the TRUTHFUL synthesis-facing shape has zero numeric facts - shape
    must never read "numeric-heavy" once "24" is proven to be publisher-derived-only."""
    titles = [
        "В Якутии разработают проект ЦОД для создания дальневосточного кластера искусственного интеллекта - RuNews24",
        "В Якутии разрабатывают проект создания дальневосточного ИИ-кластера на базе ЦОД - ЯСИА",
    ]
    candidate = _real_candidate(titles, "Якутия ИИ-кластер")
    projected = r26._projected_facts(candidate)
    assert not any(f.fact_type == "numeric" for f in projected)
    shape = r26._evidence_shape_reason(candidate, projected)
    assert "numeric-heavy" not in shape


def test_semantic_contamination_findings_flag_publisher_derived_number_but_not_ordinary_single_source_facts():
    """Spec item 15's own explicit "do NOT label all single-source facts as garbage" - an ordinary
    single-source entity/number is never flagged, only the two NEW R2.6b contamination classes."""
    titles = [
        "В Якутии разработают проект ЦОД для создания дальневосточного кластера искусственного интеллекта - RuNews24",
        "В Якутии разрабатывают проект создания дальневосточного ИИ-кластера на базе ЦОД - ЯСИА",
    ]
    candidate = _real_candidate(titles, "Якутия ИИ-кластер")
    projected = r26._projected_facts(candidate)
    findings = r26._semantic_contamination_findings(candidate, projected)
    assert any(f.startswith("publisher-derived-numeric:24") for f in findings)

    clean_titles = ["Apple unveils new AI chip with faster inference", "Apple confirms new AI chip release date"]
    clean_candidate = _real_candidate(clean_titles, "Apple AI chip")
    clean_projected = r26._projected_facts(clean_candidate)
    clean_findings = r26._semantic_contamination_findings(clean_candidate, clean_projected)
    assert clean_findings == []


# ---------------------------------------------------------------------------
# R2.6c - projection-aware shortlist eligibility (real production finding: R2.6b's combined
# hygiene-findings gate rejected Yakutia - a genuine NEWS_EVENT, Story Integrity PASS - purely
# because its RAW forensic candidate still contained the publisher-derived "24", even though the
# actual rendered synthesis evidence never shows it). Proves two distinct quality surfaces:
# RAW_FORENSIC (informational, never blocks) vs SYNTHESIS_INPUT (the real eligibility gate,
# verified against the actual rendered bundle_text, never inferred from projection intent alone).
# ---------------------------------------------------------------------------

_YAKUTIA_TITLES = [
    "В Якутии разработают проект ЦОД для создания дальневосточного кластера искусственного интеллекта - RuNews24",
    "В Якутии разрабатывают проект создания дальневосточного ИИ-кластера на базе ЦОД - ЯСИА",
]


def test_raw_contamination_exists_while_synthesis_input_is_clean_publisher_numeric():
    """The real Yakutia finding: raw finding present, synthesis-input finding absent."""
    from services.event_recap import render_event_recap_bundle_text

    candidate = _real_candidate(_YAKUTIA_TITLES, _YAKUTIA_TITLES[1].rsplit(" - ", 1)[0])
    projected = r26._projected_facts(candidate)
    raw_findings = r26._semantic_contamination_findings(candidate, projected)
    assert any(f.startswith("publisher-derived-numeric:24") for f in raw_findings)

    bundle_text = render_event_recap_bundle_text(candidate)
    synthesis_findings = r26._synthesis_input_findings(bundle_text, raw_findings)
    assert synthesis_findings == []


def test_yakutia_quality_preflight_no_longer_fails_on_safely_projected_contamination():
    """The actual R2.6c bug: C/H dimensions, and therefore overall quality_verdict, must not FAIL
    for Yakutia once the contamination is proven absent from the rendered synthesis evidence -
    shortlist_eligible logic (quality_verdict != "FAIL") must therefore become True."""
    from services.event_recap import render_event_recap_bundle_text
    from services.news_editorial_relevance import classify_editorial_relevance

    candidate = _real_candidate(_YAKUTIA_TITLES, _YAKUTIA_TITLES[1].rsplit(" - ", 1)[0])
    projected = r26._projected_facts(candidate)
    raw_findings = r26._semantic_contamination_findings(candidate, projected)
    bundle_text = render_event_recap_bundle_text(candidate)
    synthesis_findings = r26._synthesis_input_findings(bundle_text, raw_findings)
    relevance = classify_editorial_relevance(candidate.story_title)

    verdict, dims = r26._quality_preflight(
        candidate, projected, synthesis_findings, relevance,
        is_research_abstract=False, is_finance_advice=False,
    )
    assert dims["C_evidence_cleanliness"] == "PASS"
    assert dims["H_publisher_noise_exposure"] == "PASS"
    assert verdict != "FAIL"


def test_generic_entity_phrase_raw_warning_but_synthesis_pass_when_removed():
    from services.event_recap import render_event_recap_bundle_text

    titles = [
        "Nvidia CEO boosts His Own Stock position again",
        "Nvidia CEO increases His Own Stock holdings this week",
    ]
    candidate = _real_candidate(titles, "Nvidia CEO stock activity")
    projected = r26._projected_facts(candidate)
    raw_findings = r26._semantic_contamination_findings(candidate, projected)
    assert any(f.startswith("generic-entity-phrase:his own stock") for f in raw_findings)

    bundle_text = render_event_recap_bundle_text(candidate)
    synthesis_findings = r26._synthesis_input_findings(bundle_text, raw_findings)
    assert synthesis_findings == []


def test_contamination_still_present_in_rendered_synthesis_fails_the_gate():
    """A defense-in-depth case: if a raw-forensic-contaminated value were somehow STILL present in
    the actual rendered bundle (e.g. a future regression reintroducing it), `_synthesis_input_
    findings()` must catch it directly from the rendered text, never trusting projection intent
    alone (spec item 6)."""
    fabricated_bundle_text = (
        "Story: Test\n\nVERIFIED FACTS (from stored evidence, not LLM-generated):\n"
        "- 24 - mentioned in a single stored report only\n\n"
        "ANNOUNCEMENTS (detail):\n- #0: 'Test - RuNews24' | numbers=['24'] | entities=[] | evidence_refs=1"
    )
    raw_findings = ["publisher-derived-numeric:24"]
    synthesis_findings = r26._synthesis_input_findings(fabricated_bundle_text, raw_findings)
    assert any(f.startswith("still-present-in-rendered-synthesis:publisher-derived-numeric:24") for f in synthesis_findings)


def test_editorial_rejection_remains_hard_even_with_clean_synthesis():
    """Spec item 9 - the Nvidia stock Story must remain rejected via the finance gate regardless of
    whether its synthesis evidence happens to be clean (an independent gate, never bypassed by
    evidence cleanliness)."""
    from services.event_recap import render_event_recap_bundle_text
    from services.news_editorial_relevance import classify_editorial_relevance

    title = (
        "The CEO of This Nvidia-Backed Artificial Intelligence (AI) Chip Company Just Bought "
        "$10 Million of His Own Stock."
    )
    candidate = _real_candidate([title], title)
    projected = r26._projected_facts(candidate)
    raw_findings = r26._semantic_contamination_findings(candidate, projected)
    bundle_text = render_event_recap_bundle_text(candidate)
    synthesis_findings = r26._synthesis_input_findings(bundle_text, raw_findings)
    relevance = classify_editorial_relevance(candidate.story_title)
    is_finance = r26._is_finance_advice_like(candidate.story_title)

    verdict, dims = r26._quality_preflight(
        candidate, projected, synthesis_findings, relevance,
        is_research_abstract=False, is_finance_advice=is_finance,
    )
    assert is_finance is True
    assert dims["I_editorial_relevance"] == "FAIL"
    assert verdict == "FAIL"
    shortlist_eligible = verdict != "FAIL" and r26._relevance_accepted(relevance) and not is_finance
    assert shortlist_eligible is False


def test_story_integrity_failure_remains_hard_gate():
    """render_story() never builds a candidate at all for a Story Integrity FAIL - unaffected by
    this checkpoint's projection-awareness change, verified structurally: _quality_preflight() is
    never reachable without a candidate."""
    import inspect

    source = inspect.getsource(r26.render_story)
    integrity_check_index = source.index("integrity.eligible")
    quality_preflight_index = source.index("_quality_preflight(")
    assert integrity_check_index < quality_preflight_index


def test_max_one_minimal_edge_case_still_enforced_after_r2_6c():
    usable = [
        _usable_record(uuid4(), announcement_count=1, editorial_event_class="MINIMAL_EDGE"),
        _usable_record(uuid4(), announcement_count=1, editorial_event_class="MINIMAL_EDGE"),
        _usable_record(uuid4(), announcement_count=3, editorial_event_class="NEWS_EVENT"),
    ]
    shortlist = r26._select_shortlist(usable)
    assert sum(1 for u in shortlist if u["editorial_event_class"] == "MINIMAL_EDGE") <= 1


def test_quality_over_quota_still_enforced_after_r2_6c():
    usable = [
        _usable_record(uuid4(), announcement_count=3, editorial_event_class="NEWS_EVENT"),
        _usable_record(uuid4(), announcement_count=1, quality_verdict="FAIL", shortlist_eligible=False),
    ]
    shortlist = r26._select_shortlist(usable)
    assert len(shortlist) == 1
