"""NINJA PULSE RECAP Phase R1.3 - Story Integrity Gate fixture matrix, built from the TITLES
observed in the R1.2 production replay (spec's own required fixture set, cases A-I) plus the
R1.2 event_count mismatch regression (spec item 13).

Phase R1.5A.2 update: generic-leading-entity filtering is now decided PER anchor->member pair
(see `evaluate_recap_story_integrity()`'s own docstring) rather than once, globally, for the whole
Story - the Story-wide `generic_leading_entities_stripped` metric no longer exists; assertions here
instead read the pair-specific `pair_entity_exclusions` metric. Pure-function tests only - no DB,
network, or LLM, fully offline/deterministic."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from database.models.news_event import EventCategory, NewsEvent
from services.recap_event import StoryIntegrityResult, evaluate_recap_story_integrity

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _event(*, title: str, minutes_ago: float = 0.0) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(), source_id=uuid.uuid4(), title=title, category=EventCategory.TECH,
        url=f"https://example.com/{uuid.uuid4()}",
        published_at=_NOW - timedelta(minutes=minutes_ago),
        collected_at=_NOW - timedelta(minutes=minutes_ago),
        hash=f"h-{uuid.uuid4()}",
    )


def _integrity(anchor_title: str, *other_titles: str, spacing_minutes: float = 10.0) -> StoryIntegrityResult:
    anchor = _event(title=anchor_title, minutes_ago=len(other_titles) * spacing_minutes)
    others = [
        _event(title=t, minutes_ago=(len(other_titles) - i - 1) * spacing_minutes)
        for i, t in enumerate(other_titles)
    ]
    return evaluate_recap_story_integrity(anchor, [anchor, *others])


# ---------------------------------------------------------------------------
# FAIL cases (spec item 9, A-D) - the real R1.2 production false-positive patterns
# ---------------------------------------------------------------------------


def test_case_a_weekend_generic_opener_fails_integrity():
    result = _integrity(
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies in a used car you just bought?",
        "What the world's oldest telecommunications company is doing to survive",
        "What software do you use daily to get work done?",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"what"}


def test_case_b_accurate_generic_opener_fails_integrity():
    result = _integrity(
        "Accurate polyp segmentation using a lightweight vision transformer",
        "Accurate color conversions between RGB and CMYK for print workflows",
        "Accurate building height information from lidar without ground survey",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"accurate"}


def test_case_c_how_ai_generic_opener_fails_integrity():
    result = _integrity(
        "How AI is driving up consumer prices",
        "How AI is reshaping the path from junior to senior developer",
        "How AI text watermarking works",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"how ai"}


def test_case_d_arxiv_large_language_models_generic_opener_fails_integrity():
    result = _integrity(
        "Large language model guardrails for safety critical deployments",
        "Large language models for automated medical consultation triage",
        "Large language models generate executable programs from specifications",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"large"}


# ---------------------------------------------------------------------------
# PASS cases (spec item 9, E-I)
# ---------------------------------------------------------------------------


def test_case_e_openai_hugging_face_breach_passes_integrity():
    result = _integrity(
        "Hugging Face confirms data breach affecting OpenAI models",
        "OpenAI tightens safeguards after Hugging Face security breach",
        "Security researchers detail Hugging Face breach impact on OpenAI",
    )
    assert result.eligible is True


def test_case_f_taiwan_ai_dividend_passes_integrity():
    result = _integrity(
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "$314 AI dividend payment explained for Taiwan residents",
    )
    assert result.eligible is True


def test_case_g_risc_v_original_plus_response_article():
    """spec item 9.G: PASS or AMBIGUOUS/eligible is acceptable, but must be explicitly justified -
    see the R1.3 report's own item K for the reasoning. This fixture is deliberately designed to
    PASS: both titles share the real, specific "RISC-V" entity, and neither leads with a generic
    word, so the shared entity is never even a pair-specific-filtering candidate."""
    result = _integrity(
        "RISC-V International announces new vector extension for edge AI",
        "Why RISC-V's new vector extension matters for edge AI chips",
    )
    assert result.eligible is True


def test_case_h_qwen_launch_plus_overthinking_followups_passes_integrity():
    result = _integrity(
        "Qwen 3.8 27B launches with major reasoning upgrade",
        "Why Qwen 3.8 27B seems to overthink simple questions",
        "Developers report Qwen 3.8 27B overthinking basic prompts",
    )
    assert result.eligible is True


def test_case_i_identical_syndicated_articles_passes_integrity():
    title = "Schools embrace AI and VR tools to modernize classrooms"
    result = _integrity(title, title, title)
    assert result.eligible is True
    assert result.metrics["anchor_coherent_ratio"] == 1.0


# ---------------------------------------------------------------------------
# Mechanism-level tests
# ---------------------------------------------------------------------------


def test_single_event_story_trivially_passes():
    anchor = _event(title="Solo event with no other confirmed members")
    result = evaluate_recap_story_integrity(anchor, [anchor])
    assert result.eligible is True
    assert result.metrics["member_count"] == 1


def test_bad_integrity_is_never_compensated_by_high_event_count():
    """spec item 10: integrity FAIL must not be rescued by adding MORE unrelated events - a larger
    incoherent group is still incoherent."""
    result = _integrity(
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies",
        "What the world's oldest telecom company is doing",
        "What software do you use daily",
        "What movie should I watch tonight",
        "What is the best budget laptop in 2026",
    )
    assert result.eligible is False


def test_generic_leading_entity_stripping_does_not_remove_real_recurring_company_name():
    """The pair-specific generic filter must not strip a genuine company/product name merely
    because it happens to be the SAME word every time - only because it recurs specifically as the
    LEADING entity across members AND lacks residual evidence linking it to the anchor. Here
    "OpenAI" is the anchor's own subject but never leads another member's title, so it is never even
    a filtering candidate, and drives a real PASS."""
    result = _integrity(
        "OpenAI ships GPT-X with major reasoning improvements",
        "Developers are already building on top of OpenAI's new GPT-X model",
        "Early GPT-X benchmarks from OpenAI look promising",
    )
    assert result.eligible is True
    assert result.metrics["pair_entity_exclusions"] == {}


# ---------------------------------------------------------------------------
# Phase R1.5A.2 - PAIR-SPECIFIC generic entity filtering, replacing R1.5A's Story-wide anchor-
# centered fraction rule. Real PRODUCTION forensic evidence (R1.5A.1 replay) proved the Story-wide
# fraction rule was STILL a spillover-authority bug relocated to anchor scope: one genuine near-
# duplicate member among otherwise-unrelated members could clear the qualifying fraction alone and
# globally preserve the entity for every pairwise comparison, handing unrelated members a free
# `entity_jaccard=1.0` they never earned individually (the real production "Recent"/"Despite"
# Stories, both confirmed PASS in production despite containing genuinely unrelated papers).
# ---------------------------------------------------------------------------


def test_large_language_models_nine_member_lucky_pair_stress_case_still_fails():
    """Spec R1.5A item 5's mandatory stress case, still required under pair-specific filtering: 9
    real-shaped, genuinely unrelated arXiv titles, all leading with "Large". None of the anchor's 8
    individual pairwise residual links reach the 0.40 floor (max measured: 0.308), so "large" is
    excluded from every single pair independently - the Story correctly fails regardless of what any
    non-anchor pair measures."""
    result = _integrity(
        "Large language model guardrails for safety critical deployments",
        "Large language models for automated medical consultation triage",
        "Large language models generate executable programs from specifications",
        "Large language models struggle with multi-step arithmetic reasoning",
        "Large language models show promise in legal document summarization",
        "Large language models and their carbon footprint during training",
        "Large language models for low-resource language translation tasks",
        "Large language models used to detect phishing emails automatically",
        "Large language models evaluated on creative writing benchmarks",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"large"}


def test_large_language_models_duplicate_does_not_rescue_unrelated_members():
    """Spec R1.5A.2 item 10 control: injecting ONE genuine near-duplicate of the anchor into the
    9-member generic pool (spec's own explicit "a semantic duplicate must not rescue generic 'large'
    for unrelated members" requirement). Under the OLD Story-wide fraction rule this single strong
    link (residual ~1.0) would have cleared the 0.20 qualifying fraction and globally preserved
    "large" for the whole Story, flipping every unrelated member to `entity_jaccard=1.0`. Under
    pair-specific filtering, the duplicate's OWN pair is coherent, but the other 8 unrelated pairs
    each independently exclude "large" and remain incoherent - the Story still correctly fails, with
    ratio far below the 0.5 threshold."""
    result = _integrity(
        "Large language model guardrails for safety critical deployments",
        "Large language model guardrails for safety-critical deployments",
        "Large language models for automated medical consultation triage",
        "Large language models generate executable programs from specifications",
        "Large language models struggle with multi-step arithmetic reasoning",
        "Large language models show promise in legal document summarization",
        "Large language models and their carbon footprint during training",
        "Large language models for low-resource language translation tasks",
        "Large language models used to detect phishing emails automatically",
        "Large language models evaluated on creative writing benchmarks",
    )
    assert result.eligible is False
    assert result.metrics["anchor_coherent_ratio"] < 0.5
    assert result.metrics["anchor_coherent_count"] == 1  # only the duplicate


def test_recent_generic_opener_with_near_duplicate_fails_integrity():
    """Spec R1.5A.2 item 8 - production-shaped reconstruction (the exact real production titles were
    never available verbatim to this checkpoint, only the topic description in the R1.5A.2 message:
    "same video-generator paper, 3D foundation-model paper, robot-learning paper" plus an exact
    semantic duplicate of the anchor). Reproduces the real production false-positive mechanism: the
    duplicate pair is genuinely coherent, but the OLD Story-wide fraction rule let that one link
    globally preserve "recent" and hand the two genuinely unrelated papers a free pass (production
    PASS 3/3). Under pair-specific filtering, only the duplicate is coherent; the two unrelated
    members are each independently excluded and incoherent - ratio 1/3, correctly FAIL."""
    result = _integrity(
        "Recent video generators struggle with consistent physical motion",
        "Recent video generators still struggle with consistent physical motion",
        "Recent 3D foundation models enable zero-shot scene reconstruction",
        "Recent progress in robot learning accelerates real-world manipulation tasks",
    )
    assert result.eligible is False
    assert result.metrics["anchor_coherent_ratio"] == round(1 / 3, 3)
    assert result.metrics["anchor_coherent_count"] == 1
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"recent"}
    assert len(result.metrics["pair_entity_exclusions"]) == 2  # only the two unrelated members


def test_despite_generic_opener_with_near_duplicate_fails_integrity():
    """Spec R1.5A.2 item 9 - production-shaped reconstruction (topic description: "materials, video
    editing, multimodal image generation, medical visual recognition" plus an exact semantic
    duplicate of the anchor). Same mechanism as Recent: the duplicate pair is genuinely coherent, the
    three unrelated members are each independently excluded and incoherent under pair-specific
    filtering - ratio 1/4, correctly FAIL (production PASS 4/4 under the old Story-wide rule)."""
    result = _integrity(
        "Despite recent advances in unified multimodal models text accuracy remains poor",
        "Despite recent advances in unified multimodal models text accuracy is still poor",
        "Despite recent advances battery materials remain difficult to scale",
        "Despite recent advances video editing tools still require manual correction",
        "Despite recent advances medical visual recognition models show demographic bias",
    )
    assert result.eligible is False
    assert result.metrics["anchor_coherent_ratio"] == 0.25
    assert result.metrics["anchor_coherent_count"] == 1
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"despite"}
    assert len(result.metrics["pair_entity_exclusions"]) == 3  # only the three unrelated members


def test_autonomous_generic_opener_fails_integrity():
    result = _integrity(
        "Autonomous racecars complete first fully driverless championship lap",
        "Autonomous delivery robots expand to twelve new cities this year",
        "Autonomous farming equipment adoption grows among midwest producers",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"autonomous"}


def test_expert_generic_opener_fails_integrity_russian():
    result = _integrity(
        "Эксперт объяснил, почему цены на жильё продолжат расти",
        "Эксперт рассказал о новых правилах регистрации автомобилей",
        "Эксперт оценил перспективы урожая зерна в этом году",
    )
    assert result.eligible is False
    assert set(result.metrics["pair_entity_exclusions"].values()) == {"эксперт"}


def test_bashkiria_real_titles_conservative_fail_accepted():
    """Phase R1.5A.2 item 7/13 - explicit, deliberate reversal of the R1.4/R1.5A expectation that
    this fixture should PASS.

    Real PRODUCTION replay (R1.5A.1, then confirmed again by a second real replay in this
    checkpoint's own message) shows the real Bashkiria Story FAILING integrity - the real anchor's
    measured residual links to its other confirmed members do not clear the 0.40 floor strongly or
    consistently enough to justify treating "башкири" as safe evidence. This checkpoint's own
    reproduction using the same 4 verbatim titles documented since R1.3 (exact real ordering/anchor
    was never available to this checkpoint - only residual values were reported) measures one link
    at 0.429 (individually above the floor) and two links at 0.0/0.167 (below it) - ratio 1/3 = 0.33,
    still short of the required 0.5 and therefore still FAIL, consistent in direction with the real
    production result even though the exact per-link numbers reported in production (0.333/0.000/
    0.133) differ slightly, most likely because the true production anchor/member set is not exactly
    reproduced by this fixture.

    Per this checkpoint's own explicit instruction: "If exact production evidence cannot safely
    support Bashkiria as coherent under a deterministic lexical/entity gate: say so. Do not weaken
    generic protection just to recover it. Quality > recall." No special-case rule, no floor
    reduction, and no language-specific (Russian stemming) logic was added to force a PASS."""
    result = _integrity(
        "В Башкирии обозначили направления развития искусственного интеллекта в медицине",
        "В Башкирии определены приоритеты внедрения искусственного интеллекта в медицину",
        "Башкирия внедряет искусственный интеллект в медицину",
        "В Башкирии внедряют искусственный интеллект в медицину",
    )
    assert result.eligible is False


# ---------------------------------------------------------------------------
# Phase R1.5A.2 item 14/L - missing-anchor fail-closed regression (build_recap_event_snapshot's own
# contract, not evaluate_recap_story_integrity's - see that test in test_recap_event.py).
# ---------------------------------------------------------------------------


def test_large_generic_story_with_many_clusters_still_blocks_readiness():
    """A generic 8+-member Story whose announcement clustering happens to produce 4+ clusters (each
    title different enough in wording) must still never reach READY, because story_integrity_
    eligible=False blocks it unconditionally - announcement_count alone must never compensate."""
    from services.recap_event import (
        cluster_announcements,
        count_unique_sources,
        evaluate_recap_readiness,
    )

    titles = [
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies in a used car you just bought?",
        "What the world's oldest telecommunications company is doing to survive",
        "What software do you use daily to get work done?",
        "What movie should I watch tonight on a streaming service?",
        "What is the best budget laptop to buy in 2026?",
        "What your smart thermostat is quietly doing to your energy bill",
        "What a new archaeological dig in Egypt just revealed",
    ]
    anchor = _event(title=titles[0], minutes_ago=len(titles) * 10.0)
    others = [_event(title=t, minutes_ago=(len(titles) - i - 1) * 10.0) for i, t in enumerate(titles[1:], start=1)]
    events = [anchor, *others]

    integrity = evaluate_recap_story_integrity(anchor, events)
    assert integrity.eligible is False

    clusters = cluster_announcements(events)
    assert len(clusters) >= 4  # genuinely different wording - clusters legitimately fragment

    result = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events), last_event_at=events[-1].published_at,
        now=_NOW, research_complete=True, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )
    assert result.ready is False
    assert any("coherent_ratio" in reason or "integrity" in reason.lower() for reason in result.reasons)
