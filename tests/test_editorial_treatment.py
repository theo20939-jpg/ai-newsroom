"""Phase 23.1G - editorial output policy (SKIP/BRIEF/STANDARD/MAJOR) tests.

Pure unit tests only - `services/editorial_treatment.py::classify_editorial_treatment()` is a
deterministic function of plain values, no DB, no LLM.

Six required cases (phase brief "TEST-FIRST - TREATMENT"), each built from the module's own real,
investigated signal shapes (Intelligence significance/recommendation, Scoring score, article
acquisition completeness, source reliability) - not hardcoded to any specific real story.
"""
from services.editorial_treatment import (
    BRIEF,
    MAJOR,
    SKIP,
    STANDARD,
    classify_editorial_treatment,
)

# ---------------------------------------------------------------------------
# CASE A - weak niche story: generic scientific "AI may help..." claim, weak evidence, low
# Intelligence importance -> SKIP or BRIEF, never STANDARD/MAJOR
# ---------------------------------------------------------------------------


def test_case_a_weak_niche_story_never_standard_or_major() -> None:
    decision = classify_editorial_treatment(
        significance=3, recommendation="Требует дополнительной проверки перед публикацией.",
        scoring_score=78, source_reliability=None, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment in (SKIP, BRIEF)


# ---------------------------------------------------------------------------
# CASE B - weak unverified source: headline-only, Intelligence says verify/not publish -> SKIP
# ---------------------------------------------------------------------------


def test_case_b_weak_unverified_source_with_negative_recommendation_is_skip() -> None:
    decision = classify_editorial_treatment(
        significance=3,
        recommendation="Не публиковать как подтвержденную новость без дополнительной верификации.",
        scoring_score=88, source_reliability=None, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment == SKIP
    assert "weak evidence" in decision.reason.lower() or "headline_only" in decision.reason.lower()


def test_case_b_variant_low_reliability_no_acquisition_row_is_skip() -> None:
    """The same weak+negative combination, but via the source_reliability fallback path (no
    acquisition row at all - e.g. a Telegram-sourced event)."""
    decision = classify_editorial_treatment(
        significance=3, recommendation="Do not publish without independent verification.",
        scoring_score=80, source_reliability=0.4, evidence_completeness=None,
    )
    assert decision.treatment == SKIP


# ---------------------------------------------------------------------------
# CASE C - valid small update: concrete but low-impact product update -> BRIEF
# ---------------------------------------------------------------------------


def test_case_c_valid_small_update_is_brief() -> None:
    decision = classify_editorial_treatment(
        significance=4, recommendation="Публиковать как короткую заметку.",
        scoring_score=70, source_reliability=0.8, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == BRIEF


# ---------------------------------------------------------------------------
# CASE D - meaningful standard tech news: several concrete facts, reasonable source, clear
# relevance -> STANDARD
# ---------------------------------------------------------------------------


def test_case_d_meaningful_standard_news_is_standard() -> None:
    decision = classify_editorial_treatment(
        significance=7, recommendation="Публиковать как заметную технологическую новость.",
        scoring_score=82, source_reliability=0.8, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == STANDARD


# ---------------------------------------------------------------------------
# CASE E - major announcement: high importance, strong evidence, multiple distinct facts -> MAJOR
# ---------------------------------------------------------------------------


def test_case_e_major_announcement_strong_evidence_is_major() -> None:
    decision = classify_editorial_treatment(
        significance=9, recommendation="Публиковать как главную новость дня.",
        scoring_score=95, source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == MAJOR


def test_case_e_high_significance_but_weak_evidence_downgrades_from_major() -> None:
    """A high-significance claim resting on weak evidence must not become MAJOR - the phase
    brief's own "do not automatically make every high-scoring story long" principle."""
    decision = classify_editorial_treatment(
        significance=9, recommendation="Потенциально значимая новость, требует подтверждения.",
        scoring_score=90, source_reliability=None, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment != MAJOR


# ---------------------------------------------------------------------------
# CASE F - low Intelligence but strong compensating signals -> not blindly SKIP;
# BRIEF/review per the documented rule
# ---------------------------------------------------------------------------


def test_case_f_low_intelligence_strong_compensating_signal_not_blind_skip() -> None:
    decision = classify_editorial_treatment(
        significance=3, recommendation="Тема нишевая, но факты подтверждены.",
        scoring_score=90, source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment != SKIP
    assert decision.treatment == BRIEF


def test_case_f_low_intelligence_weak_evidence_is_skip_regardless_of_score() -> None:
    """2026-08-15 spec-compliance correction: an earlier pass of this recalibration kept the
    module's original carve-out ("very low Intelligence + strong score -> BRIEF + review flag"
    even when evidence IS weak). The corrected policy is narrower: at sig<=3.0, Scoring can only
    ever compensate for significance, never for evidence quality - weak evidence is an
    unconditional SKIP at this tier no matter how high scoring_score is."""
    decision = classify_editorial_treatment(
        significance=2, recommendation="Незначительная тема, но источник указан.",
        scoring_score=92, source_reliability=None, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment == SKIP


# ---------------------------------------------------------------------------
# Additional regression coverage: significance normalization, missing data, audit reason
# ---------------------------------------------------------------------------


def test_significance_on_a_0_to_1_scale_is_normalized() -> None:
    """A hypothetical future/legacy 0-1 fractional significance value must classify the same as
    its 0-10 equivalent - not be misread as "very low" across the board."""
    decision_fraction = classify_editorial_treatment(
        significance=0.9, recommendation="Публиковать.", scoring_score=90,
        source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    decision_int = classify_editorial_treatment(
        significance=9, recommendation="Публиковать.", scoring_score=90,
        source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision_fraction.treatment == decision_int.treatment == MAJOR


def test_missing_significance_never_defaults_to_major_or_standard() -> None:
    decision = classify_editorial_treatment(
        significance=None, recommendation=None, scoring_score=80,
        source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == BRIEF
    assert decision.human_review_required is True


def test_skip_always_has_a_non_empty_audit_reason() -> None:
    decision = classify_editorial_treatment(
        significance=1, recommendation="Не публиковать без проверки.",
        scoring_score=50, source_reliability=None, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment == SKIP
    assert decision.reason.strip() != ""


# ---------------------------------------------------------------------------
# Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md): the real Terraria regression
# (Phase 23.1O) - FETCH_FAILED was unconditionally treated as "not weak evidence," so a story
# Intelligence explicitly recommended against publishing (weak_evidence=False due solely to
# FETCH_FAILED, even though the event's own real news_event.content was only 59 chars, shorter
# than its own 122-char title) fell through the SKIP gate into BRIEF instead. Real field values
# from the actual persisted Phase 23.1O event.
# ---------------------------------------------------------------------------

_TERRARIA_TITLE = (
    "After 10 years, Terraria's biggest mod shuts down due to an 'irrecoverably tainted "
    "reputation' and grooming allegations"
)
_TERRARIA_CONTENT = "Almost all passion we've had for the mod has been soured."
_TERRARIA_RECOMMENDATION = (
    "Не публиковать как полноценную новость без дополнительной проверки: отсутствуют название "
    "мода, сведения о создателях, подтверждение закрытия и подробности обвинений."
)


def test_case_terraria_regression_fetch_failed_with_thin_content_and_negative_rec_is_skip() -> None:
    decision = classify_editorial_treatment(
        significance=4, recommendation=_TERRARIA_RECOMMENDATION, scoring_score=72,
        source_reliability=0.8, evidence_completeness="FETCH_FAILED",
        event_title=_TERRARIA_TITLE, event_content=_TERRARIA_CONTENT,
    )
    assert decision.treatment == SKIP
    assert "fetch_failed" in decision.reason.lower()


def test_fetch_failed_with_content_genuinely_richer_than_title_is_not_weak() -> None:
    """The Amazon/Gilroy shape this module's own FETCH_FAILED exclusion was originally built
    around: a failed full-article upgrade whose own RSS excerpt is still substantial (here,
    deliberately much longer than its title) must NOT be downgraded - protects against solving
    the Terraria regression by making FETCH_FAILED unconditionally weak instead of conditionally
    so."""
    rich_content = (
        "Amazon quietly negotiated a $2B data center project with Gilroy officials over several "
        "months, according to internal planning documents and interviews with three people "
        "familiar with the matter, bypassing the community vote residents had been promised."
    )
    decision = classify_editorial_treatment(
        significance=8, recommendation="Публиковать, evidence not weak.", scoring_score=90,
        source_reliability=0.9, evidence_completeness="FETCH_FAILED",
        event_title="Amazon circumvents Gilroy community vote for AI data center",
        event_content=rich_content,
    )
    assert decision.treatment == MAJOR


def test_fetch_failed_content_no_longer_than_title_is_weak_even_without_negative_recommendation() -> None:
    """Isolates the evidence-side fix from the recommendation-side gate: thin FETCH_FAILED content
    alone (no explicit negative recommendation) must still be treated as weak evidence - it simply
    won't reach SKIP alone (that still requires the independent negative_rec condition too), but it
    must visibly downgrade a high-significance story the same way HEADLINE_ONLY already does."""
    decision = classify_editorial_treatment(
        significance=8, recommendation="Публиковать как заметную новость.", scoring_score=90,
        source_reliability=0.9, evidence_completeness="FETCH_FAILED",
        event_title=_TERRARIA_TITLE, event_content=_TERRARIA_CONTENT,
    )
    assert decision.treatment == STANDARD  # downgraded from MAJOR, matching the weak-evidence path
    assert "weak evidence" in decision.reason.lower()


def test_fetch_failed_without_title_or_content_defaults_to_weak_not_the_old_unconditional_pass() -> None:
    """A caller that has not been updated to pass event_title/event_content (defensive default) -
    must lean conservative (weak), never silently reproduce the pre-23.1P unconditional
    FETCH_FAILED-is-never-weak behavior that caused the real Terraria regression."""
    decision = classify_editorial_treatment(
        significance=4, recommendation=_TERRARIA_RECOMMENDATION, scoring_score=72,
        source_reliability=0.8, evidence_completeness="FETCH_FAILED",
    )
    assert decision.treatment == SKIP


def test_recommendation_matching_itself_is_unaffected_by_the_fetch_failed_fix() -> None:
    """Confirms the root cause was on the evidence side, not the recommendation side (Part C1's
    own finding) - a POSITIVE recommendation with the same thin FETCH_FAILED content must NOT
    SKIP, only downgrade for weak evidence exactly like any other weak-evidence case."""
    decision = classify_editorial_treatment(
        significance=8, recommendation="Публиковать, история подтверждена несколькими источниками.",
        scoring_score=90, source_reliability=0.9, evidence_completeness="FETCH_FAILED",
        event_title=_TERRARIA_TITLE, event_content=_TERRARIA_CONTENT,
    )
    assert decision.treatment != SKIP
    assert decision.treatment == STANDARD


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (Case A, docs/news_output_stability_forensic_report.md §2): the real
# US Census AI-productivity draft's own signal shape - REDIRECT_UNRESOLVED (new, from services/
# article_acquisition.py's Google-News-redirect-shell detection) must be treated at least as
# weak as HEADLINE_ONLY was already being treated for this exact real case (unlike FETCH_FAILED,
# no content-vs-title exception - see _WEAK_COMPLETENESS_STATUSES's own updated comment).
# ---------------------------------------------------------------------------

_US_CENSUS_HEDGED_RECOMMENDATION = (
    "Рекомендуется к публикации как аналитический материал, но перед выпуском необходимо "
    "получить полный текст исследования с числовыми данными."
)


def test_redirect_unresolved_is_treated_as_weak_evidence() -> None:
    decision = classify_editorial_treatment(
        significance=6, recommendation=_US_CENSUS_HEDGED_RECOMMENDATION, scoring_score=70,
        source_reliability=None, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert "redirect_unresolved" in decision.reason.lower() or "weak evidence" in decision.reason.lower()
    assert decision.treatment in (SKIP, BRIEF)  # never STANDARD/MAJOR on unresolved-redirect evidence


def test_redirect_unresolved_with_hedged_non_negative_recommendation_downgrades_not_skips() -> None:
    """Mirrors the real Case A signal shape exactly (significance=0.58-ish/6, hedged
    "publish but verify first" recommendation that _is_negative_recommendation() does not match) -
    weak evidence alone (now correctly REDIRECT_UNRESOLVED, not silently HEADLINE_ONLY-by-
    coincidence) still downgrades away from STANDARD/MAJOR even without an unambiguous negative
    recommendation, exactly like the pre-existing HEADLINE_ONLY case already did."""
    decision = classify_editorial_treatment(
        significance=6, recommendation=_US_CENSUS_HEDGED_RECOMMENDATION, scoring_score=70,
        source_reliability=None, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert decision.treatment != STANDARD
    assert decision.treatment != MAJOR


# ---------------------------------------------------------------------------
# 2026-08-15 production forensic recalibration: real selected-candidate replay found 73% of
# posted stories scored only 70-79/100, and several of them carried REDIRECT_UNRESOLVED/thin
# evidence plus an Intelligence recommendation that, in plain language, said not to run the
# story as-is - but that wording ("не продвигать", "не использовать как самостоятельную/
# полноценную") was not in the old marker list, and the sig<=5 tiers gave an unconditional
# BRIEF regardless of evidence quality. Every fixture below is shaped after one real selected
# candidate from that forensic (paraphrased titles, real significance/evidence/score/
# recommendation shape).
# ---------------------------------------------------------------------------


def test_forensic_teenagers_trust_ai_is_skip() -> None:
    decision = classify_editorial_treatment(
        significance=0.35,
        recommendation="Не продвигать как подтвержденное значимое событие без дополнительных источников.",
        scoring_score=72, source_reliability=None, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert decision.treatment == SKIP


def test_forensic_chinese_technology_influence_is_skip() -> None:
    decision = classify_editorial_treatment(
        significance=0.35,
        recommendation="Не использовать как самостоятельную новость без дополнительной проверки.",
        scoring_score=72, source_reliability=None, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert decision.treatment == SKIP


def test_forensic_china_global_ai_governance_is_skip() -> None:
    decision = classify_editorial_treatment(
        significance=0.45,
        recommendation="Не использовать как полноценную новостную заметку.",
        scoring_score=72, source_reliability=None, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert decision.treatment == SKIP


def test_forensic_2005_concurrency_article_full_text_moderate_score_is_skip() -> None:
    """Do NOT allow a low significance story through just because FULL_TEXT exists - Scoring
    stays a secondary/compensating signal and 72 does not clear the strong-compensating bar."""
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать, историческая статья по теме параллелизма.",
        scoring_score=72, source_reliability=0.8, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == SKIP


def test_forensic_very_low_significance_full_text_strong_score_is_brief_with_review() -> None:
    """The one exception to the tier-1 default SKIP: evidence genuinely not weak AND Scoring
    clears the existing strong-compensating threshold (85)."""
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать, факты подтверждены несколькими источниками.",
        scoring_score=88, source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == BRIEF
    assert decision.human_review_required is True


# ---------------------------------------------------------------------------
# 2026-08-15 spec-compliance correction for sig<=3.0: Scoring can only ever compensate for
# significance, never for evidence quality. Weak evidence at this tier is an unconditional SKIP
# no matter how high scoring_score is - even a near-perfect 95 must not paper over evidence that
# is REDIRECT_UNRESOLVED/PARTIAL_TEXT/HEADLINE_ONLY. Non-weak evidence is the only path to the
# strong-compensating BRIEF+review exception, and only when score actually clears 85.
# ---------------------------------------------------------------------------


def test_very_low_significance_redirect_unresolved_very_high_score_is_still_skip() -> None:
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать.", scoring_score=95,
        source_reliability=0.9, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert decision.treatment == SKIP


def test_very_low_significance_partial_text_very_high_score_is_still_skip() -> None:
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать.", scoring_score=95,
        source_reliability=0.9, evidence_completeness="PARTIAL_TEXT",
    )
    assert decision.treatment == SKIP


def test_very_low_significance_headline_only_very_high_score_is_still_skip() -> None:
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать.", scoring_score=95,
        source_reliability=0.9, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment == SKIP


def test_very_low_significance_full_text_score_88_is_brief_with_review() -> None:
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать.", scoring_score=88,
        source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == BRIEF
    assert decision.human_review_required is True


def test_very_low_significance_full_text_score_84_is_skip() -> None:
    """One point below the strong-compensating threshold (85) - not weak evidence alone is not
    enough, exactly like the "Free Lunch" (score 72) case, just closer to the boundary."""
    decision = classify_editorial_treatment(
        significance=2, recommendation="Публиковать.", scoring_score=84,
        source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == SKIP


def test_forensic_petersburg_ai_tram_is_brief_not_standard() -> None:
    decision = classify_editorial_treatment(
        significance=0.55, recommendation="Публиковать как техническую новость регионального значения.",
        scoring_score=72, source_reliability=None, evidence_completeness="REDIRECT_UNRESOLVED",
    )
    assert decision.treatment == BRIEF
    assert decision.treatment != STANDARD


def test_forensic_valid_medium_full_text_story_is_standard() -> None:
    decision = classify_editorial_treatment(
        significance=6.5, recommendation="Публиковать как заметную технологическую новость.",
        scoring_score=78, source_reliability=0.85, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == STANDARD


def test_forensic_high_significance_full_text_is_major() -> None:
    decision = classify_editorial_treatment(
        significance=8.5, recommendation="Публиковать как главную новость дня.",
        scoring_score=90, source_reliability=0.9, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == MAJOR


def test_forensic_high_significance_weak_evidence_is_standard_with_review() -> None:
    decision = classify_editorial_treatment(
        significance=8.5, recommendation="Публиковать, требует подтверждения деталей.",
        scoring_score=80, source_reliability=None, evidence_completeness="HEADLINE_ONLY",
    )
    assert decision.treatment == STANDARD
    assert decision.human_review_required is True


# ---------------------------------------------------------------------------
# Negative-marker false-positive guard: generic hedging phrases that appear on many valid
# stories must not, by themselves, become an automatic veto.
# ---------------------------------------------------------------------------


def test_generic_caution_phrase_requires_additional_verification_is_not_negative() -> None:
    decision = classify_editorial_treatment(
        significance=6.5, recommendation="Требуется дополнительная проверка перед публикацией.",
        scoring_score=78, source_reliability=0.85, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == STANDARD
    assert decision.human_review_required is False


def test_generic_caution_phrase_sleduet_proverit_is_not_negative() -> None:
    decision = classify_editorial_treatment(
        significance=6.5, recommendation="Следует проверить детали перед публикацией.",
        scoring_score=78, source_reliability=0.85, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == STANDARD
    assert decision.human_review_required is False


def test_generic_caution_phrase_zhelatelno_utochnit_is_not_negative() -> None:
    decision = classify_editorial_treatment(
        significance=6.5, recommendation="Желательно уточнить некоторые детали.",
        scoring_score=78, source_reliability=0.85, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == STANDARD
    assert decision.human_review_required is False


def test_new_negative_markers_do_trigger_review_at_medium_significance_with_full_text() -> None:
    """A well-evidenced medium-significance story is not auto-SKIPped by a negative
    recommendation alone (no weak-evidence combination), but must be flagged for human review."""
    decision = classify_editorial_treatment(
        significance=6.5, recommendation="Не выносить в основную новостную повестку без уточнения деталей.",
        scoring_score=78, source_reliability=0.85, evidence_completeness="FULL_TEXT",
    )
    assert decision.treatment == STANDARD
    assert decision.human_review_required is True
