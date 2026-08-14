"""Phase 18.10 M1/M2: pure, tier-1 unit tests for services.story_memory - no DB, no LLM. Covers
signature extraction (entities/keywords/topic_bucket) and the pure scoring function directly.
See tests/test_story_memory_integration.py for the full match_story() outcome tests (new_story/
story_update/semantic_duplicate/uncertain_match), which need real Story rows in the database.
"""
from uuid import uuid4

import pytest

from database.models.news_event import EventCategory
from database.models.story import Story
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    TOPIC_CORPORATE,
    TOPIC_FINANCIAL,
    TOPIC_LEGAL_REGULATORY,
    TOPIC_OTHER,
    TOPIC_PRODUCT,
    TOPIC_SECURITY_INCIDENT,
    UNCERTAIN_MATCH,
    extract_story_signature,
    score_candidate,
)


# --- topic classification ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected_bucket",
    [
        ("OpenAI releases GPT-X", TOPIC_PRODUCT),
        ("OpenAI reveals GPT-X benchmarks", TOPIC_PRODUCT),
        ("Company unveils new AI chip", TOPIC_PRODUCT),
        ("Компания представила новую модель ИИ", TOPIC_PRODUCT),
        ("Startup raises $50M in Series B funding", TOPIC_FINANCIAL),
        ("Company reports quarterly earnings decline", TOPIC_FINANCIAL),
        ("Компания привлекла инвестиции в новом раунде", TOPIC_FINANCIAL),
        ("OpenAI CEO comments on regulation", TOPIC_LEGAL_REGULATORY),
        ("Regulator opens antitrust investigation into Big Tech", TOPIC_LEGAL_REGULATORY),
        ("Company appoints new CEO after board shakeup", TOPIC_CORPORATE),
        ("Two firms announce merger", TOPIC_CORPORATE),
        ("Hackers exploit vulnerability in popular app", TOPIC_SECURITY_INCIDENT),
        ("Data breach exposes millions of user records", TOPIC_SECURITY_INCIDENT),
        ("A cat sat on a mat", TOPIC_OTHER),
    ],
)
def test_topic_classification(title: str, expected_bucket: str) -> None:
    signature = extract_story_signature(title, EventCategory.AI)
    assert signature.topic_bucket == expected_bucket


def test_legal_regulatory_takes_priority_over_product_keywords_in_the_same_title() -> None:
    """False-positive protection worked example: a title that could plausibly match both
    "product" and "legal_regulatory" keywords must classify as the more specific bucket."""
    signature = extract_story_signature("Regulator opens probe into new AI chip launch", EventCategory.AI)
    assert signature.topic_bucket == TOPIC_LEGAL_REGULATORY


# --- entity/keyword extraction ------------------------------------------------------------------


def test_entities_extracted_as_capitalized_runs() -> None:
    signature = extract_story_signature("OpenAI releases GPT-X for developers", EventCategory.AI)
    # Normalized (casefolded) - compare case-insensitively via membership on the normalized set.
    assert any("openai" in e for e in signature.entities)
    assert any("gpt" in e for e in signature.entities)


def test_entities_are_deduplicated() -> None:
    signature = extract_story_signature("OpenAI and OpenAI again", EventCategory.AI)
    assert len(signature.entities) == len(set(signature.entities))


def test_keywords_are_length_filtered_and_lowercased() -> None:
    signature = extract_story_signature("OpenAI Releases A New AI Model", EventCategory.AI)
    assert "releases" in signature.keywords
    assert "a" not in signature.keywords  # below min length


def test_signature_extraction_is_deterministic() -> None:
    title = "OpenAI releases GPT-X benchmarks"
    first = extract_story_signature(title, EventCategory.AI)
    second = extract_story_signature(title, EventCategory.AI)
    assert first == second


# --- score_candidate() (pure) -------------------------------------------------------------------


def _story(*, title: str, entities: list[str], topic_bucket: str) -> Story:
    return Story(
        id=uuid4(), title=title, category=EventCategory.AI, entities=entities, keywords=[],
        topic_bucket=topic_bucket, first_event_id=uuid4(), event_count=1,
    )


def test_score_candidate_high_for_shared_entities_and_similar_title() -> None:
    title = "OpenAI reveals GPT-X benchmarks"
    signature = extract_story_signature(title, EventCategory.AI)
    candidate = _story(
        title="OpenAI releases GPT-X", entities=signature.entities, topic_bucket=TOPIC_PRODUCT,
    )
    combined, entity_overlap, title_overlap = score_candidate(title, signature, EventCategory.AI, candidate.title, candidate)
    assert entity_overlap > 0.5
    assert combined > 0.3


def test_score_candidate_zero_for_no_entity_overlap() -> None:
    title = "OpenAI releases GPT-X"
    signature = extract_story_signature(title, EventCategory.AI)
    candidate = _story(title="A cat sat on a mat", entities=[], topic_bucket=TOPIC_OTHER)
    combined, entity_overlap, title_overlap = score_candidate(title, signature, EventCategory.AI, candidate.title, candidate)
    assert entity_overlap == 0.0


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (CD Projekt/Project Sirius duplicate-story miss, docs/
# news_output_stability_forensic_report.md §10): _strip_leading_determiner() - a captured entity
# run whose leading word is a determiner/article ("The Witcher") must normalize identically to
# the same entity captured without it elsewhere ("Witcher").
# ---------------------------------------------------------------------------

_CD_PROJEKT_TITLE_A = "Witcher multiplayer spin-off Project Sirius hit by fresh layoffs"
_CD_PROJEKT_TITLE_B = (
    "CD Projekt cuts more than 20% of The Witcher spinoff development team "
    "'to reflect the project's needs at this stage of development'"
)


def test_leading_the_is_stripped_from_a_captured_multi_word_entity() -> None:
    signature = extract_story_signature("Report on The Witcher spinoff", EventCategory.AI)
    assert "witcher" in signature.entities
    assert "the witcher" not in signature.entities


def test_bare_entity_and_the_prefixed_entity_normalize_identically() -> None:
    """The exact real mechanism: the same real-world entity ("Witcher") must produce the same
    normalized string whether or not a given headline's own phrasing happens to capitalize a
    leading "The" immediately before it."""
    sig_bare = extract_story_signature("Witcher spinoff hit by layoffs", EventCategory.AI)
    sig_the = extract_story_signature("Company cuts jobs at The Witcher spinoff studio", EventCategory.AI)
    assert set(sig_bare.entities) & set(sig_the.entities)  # real, non-empty overlap now exists
    assert "witcher" in sig_bare.entities
    assert "witcher" in sig_the.entities


def test_standalone_the_is_still_fully_excluded() -> None:
    """Regression guard: the pre-existing Checkpoint 6 behavior (a determiner that is the ENTIRE
    captured entity on its own, e.g. sentence-initial "The state of AI...") must be unaffected by
    this fix - still excluded outright, never reduced to an empty-string entity."""
    signature = extract_story_signature("The state of AI in 2026", EventCategory.AI)
    assert "" not in signature.entities
    assert "the" not in signature.entities


def test_real_cd_projekt_pair_entity_overlap_measurably_improves() -> None:
    """Uses the exact real headline pair from the forensic report as the regression case. Honest,
    measured outcome (not an aspirational one): entity_overlap improves from 0.0 (both events
    classified new_story, completely disconnected) to a real, non-zero value now that "Witcher"
    matches across both headlines - but title_overlap between these two independently-worded real
    headlines remains genuinely low (0.09), so the combined score does not clear
    services.story_memory._HIGH_THRESHOLD (0.65) required for a confident STORY_UPDATE/
    SUPPORTING_SOURCE merge on this narrow fix alone - see the checkpoint's own documented
    before/after numbers and explicit policy-decision flag for achieving a full merge here."""
    signature_b = extract_story_signature(_CD_PROJEKT_TITLE_B, EventCategory.HARDWARE)
    signature_a = extract_story_signature(_CD_PROJEKT_TITLE_A, EventCategory.STARTUPS)
    candidate = _story(title=_CD_PROJEKT_TITLE_A, entities=signature_a.entities, topic_bucket=signature_a.topic_bucket)

    combined, entity_overlap, title_overlap = score_candidate(
        _CD_PROJEKT_TITLE_B, signature_b, EventCategory.HARDWARE, _CD_PROJEKT_TITLE_A, candidate,
    )

    assert entity_overlap > 0.0  # was exactly 0.0 before this fix - the real, confirmed regression
    assert "witcher" in signature_a.entities
    assert "witcher" in signature_b.entities  # was "the witcher" before this fix


def test_same_company_genuinely_different_event_remains_separate() -> None:
    """Regression guard: the fix must not cause an unrelated same-entity-family pair to merge -
    two different CD Projekt stories with no other shared signal stay well below the confident-
    match threshold."""
    title_layoffs = "CD Projekt cuts more than 20% of The Witcher spinoff development team"
    title_earnings = "CD Projekt reports quarterly earnings decline amid investor concerns"
    signature = extract_story_signature(title_earnings, EventCategory.STARTUPS)
    layoffs_signature = extract_story_signature(title_layoffs, EventCategory.HARDWARE)
    candidate = _story(
        title=title_layoffs, entities=layoffs_signature.entities, topic_bucket=layoffs_signature.topic_bucket,
    )
    combined, entity_overlap, title_overlap = score_candidate(
        title_earnings, signature, EventCategory.STARTUPS, title_layoffs, candidate,
    )
    from services.story_memory import _HIGH_THRESHOLD
    assert combined < _HIGH_THRESHOLD  # never a confident same-story merge on entity alone


def test_real_material_update_with_similar_wording_remains_update_capable() -> None:
    """Regression guard: the fix must not weaken a genuine, easily-matched update case - a
    materially-different-but-clearly-related headline about the same story, sharing both a
    leading-"The" entity and substantial title wording, still clears the confident-match
    threshold."""
    root_title = "The Witcher 4 delayed to next year, CD Projekt confirms"
    update_title = "CD Projekt delays The Witcher 4 release to next year amid development concerns"
    root_signature = extract_story_signature(root_title, EventCategory.AI)
    update_signature = extract_story_signature(update_title, EventCategory.AI)
    candidate = _story(title=root_title, entities=root_signature.entities, topic_bucket=root_signature.topic_bucket)

    combined, entity_overlap, title_overlap = score_candidate(
        update_title, update_signature, EventCategory.AI, root_title, candidate,
    )
    from services.story_memory import _HIGH_THRESHOLD
    assert combined >= _HIGH_THRESHOLD
    assert "witcher 4" in root_signature.entities or "witcher" in root_signature.entities


# --- outcome constants sanity (defensive - catches an accidental rename) ------------------------


def test_outcome_constants_are_distinct_strings() -> None:
    outcomes = {NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE, UNCERTAIN_MATCH, RELATED_STORY}
    assert len(outcomes) == 6


# --- Phase 20 M11.2: _preselect_candidates() two-stage retrieval (pure, no DB) -----------------


def _story_with_keywords(*, title: str, entities: list[str], keywords: list[str]) -> Story:
    from database.models.story import Story as StoryModel

    return StoryModel(
        id=uuid4(), title=title, category=EventCategory.AI, entities=entities, keywords=keywords,
        topic_bucket=TOPIC_OTHER, first_event_id=uuid4(), event_count=1,
    )


def test_preselect_includes_high_relevance_candidate_even_if_not_in_recency_window() -> None:
    from services.story_memory import _PRESELECTION_RECENCY_LIMIT, _preselect_candidates

    signature = extract_story_signature("Cloudflare launches Kitesurf", EventCategory.AI)
    true_match = _story_with_keywords(title="Cloudflare launches Kitesurf", entities=signature.entities, keywords=signature.keywords)
    # Simulate the true match having aged out of the recency tier: put it AFTER _PRESELECTION_
    # RECENCY_LIMIT other, unrelated, more-recently-updated candidates in the (already
    # recency-ordered) input list.
    filler = [
        _story_with_keywords(title=f"Unrelated filler story {i}", entities=[], keywords=[f"filler{i}"])
        for i in range(_PRESELECTION_RECENCY_LIMIT + 5)
    ]
    candidates = filler + [true_match]

    result = _preselect_candidates(signature, candidates)
    assert true_match.id in {c.id for c in result}


def test_preselect_includes_zero_overlap_candidate_within_recency_window() -> None:
    from services.story_memory import _preselect_candidates

    signature = extract_story_signature("Some brand-new headline about a fresh topic", EventCategory.AI)
    fresh_unrelated = _story_with_keywords(title="Completely unrelated fresh headline", entities=[], keywords=["totally", "different"])

    result = _preselect_candidates(signature, [fresh_unrelated])
    assert fresh_unrelated.id in {c.id for c in result}


def test_preselect_excludes_old_zero_overlap_candidate_beyond_recency_window() -> None:
    from services.story_memory import _PRESELECTION_RECENCY_LIMIT, _preselect_candidates

    signature = extract_story_signature("Some brand-new headline about a fresh topic", EventCategory.AI)
    old_unrelated = _story_with_keywords(title="Old unrelated headline", entities=[], keywords=["old", "irrelevant"])
    filler = [
        _story_with_keywords(title=f"Filler story {i}", entities=[], keywords=[f"filler{i}"])
        for i in range(_PRESELECTION_RECENCY_LIMIT)
    ]
    candidates = filler + [old_unrelated]  # old_unrelated is beyond the recency window and shares nothing

    result = _preselect_candidates(signature, candidates)
    assert old_unrelated.id not in {c.id for c in result}


def test_preselect_deduplicates_candidates_present_in_both_tiers() -> None:
    from services.story_memory import _preselect_candidates

    signature = extract_story_signature("OpenAI launches new product", EventCategory.AI)
    both_tiers = _story_with_keywords(title="OpenAI launches new product update", entities=signature.entities, keywords=signature.keywords)

    result = _preselect_candidates(signature, [both_tiers])
    ids = [c.id for c in result]
    assert ids.count(both_tiers.id) == 1


def test_preselect_caps_at_story_match_candidate_limit() -> None:
    from services.story_memory import STORY_MATCH_CANDIDATE_LIMIT, _preselect_candidates

    signature = extract_story_signature("OpenAI launches new product", EventCategory.AI)
    many_relevant = [
        _story_with_keywords(title=f"OpenAI launches new product variant {i}", entities=signature.entities, keywords=signature.keywords)
        for i in range(STORY_MATCH_CANDIDATE_LIMIT + 100)
    ]

    result = _preselect_candidates(signature, many_relevant)
    assert len(result) <= STORY_MATCH_CANDIDATE_LIMIT


# ---------------------------------------------------------------------------
# Entity Normalization Calibration fix (docs/research_reuse_entity_normalization_checkpoint.md
# Sections B/C): _CALIBRATED_GENERIC_PREFIX_ENTITIES ("в", "от", "отчёт", "компани",
# "правительств") - real, corpus-calibrated tokens, kept deliberately separate from
# _GENERIC_DETERMINER_ENTITIES. The real VK forensic pair is the primary regression case.
# ---------------------------------------------------------------------------

_VK_TITLE_1 = (
    "VK отчиталась за квартал: выручка выросла на 17%, до 43,5 млрд рублей, "
    "чистая прибыль составила 328 млн рублей."
)
_VK_TITLE_2 = "Отчёт VK за квартал: выручка — 43,5 млрд рублей, чистая прибыль — 328 млн рублей"


def test_real_vk_pair_entity_overlap_and_score_reach_calibrated_counterfactual() -> None:
    """The exact real VK forensic case, before/after: previously entity_overlap=0.0, combined=0.37
    (uncertain_match) - the checkpoint's own calibrated counterfactual predicted entity_overlap=1.0,
    combined≈0.97 once "Отчёт" no longer contaminates the captured entity. Reports the actual
    result rather than asserting the exact float, per the phase brief's own "do not force the
    exact final number" instruction - but the real result does land almost exactly on the
    predicted 0.97."""
    sig_1 = extract_story_signature(_VK_TITLE_1, EventCategory.UNKNOWN)
    story_1 = _story(title=_VK_TITLE_1, entities=sig_1.entities, topic_bucket=sig_1.topic_bucket)

    sig_2 = extract_story_signature(_VK_TITLE_2, EventCategory.STARTUPS)
    combined, entity_overlap, title_overlap = score_candidate(
        _VK_TITLE_2, sig_2, EventCategory.STARTUPS, story_1.title, story_1,
    )

    assert sig_1.entities == ["vk"]
    assert sig_2.entities == ["vk"]  # was ["отчёт vk"] before this fix
    assert entity_overlap == 1.0  # was 0.0 before this fix
    assert combined > 0.9  # was 0.37 before this fix (uncertain_match) - now well past _HIGH_THRESHOLD
    from services.story_memory import _HIGH_THRESHOLD
    assert combined >= _HIGH_THRESHOLD  # now a confident match, not uncertain_match


def test_otchet_vk_normalizes_to_bare_vk() -> None:
    signature = extract_story_signature("Отчёт VK за квартал", EventCategory.STARTUPS)
    assert "vk" in signature.entities
    assert "отчёт vk" not in signature.entities


def test_kompaniya_vk_normalizes_to_bare_vk() -> None:
    signature = extract_story_signature("Компания VK объявила о результатах", EventCategory.STARTUPS)
    assert "vk" in signature.entities
    assert not any(e.startswith("компани") for e in signature.entities)


def test_prepositional_wrappers_v_and_ot_are_stripped() -> None:
    sig_v = extract_story_signature("В Steam вышла демоверсия новой игры", EventCategory.TECH)
    assert "steam" in sig_v.entities
    assert "в steam" not in sig_v.entities

    sig_ot = extract_story_signature("От MCP к Agent Plugins 1.0", EventCategory.AI)
    assert "mcp" in sig_ot.entities
    assert "от mcp" not in sig_ot.entities


def test_government_wrapper_case_from_real_calibration_set() -> None:
    """Real calibration example: "Правительство России проработает новые меры поддержки
    ИИ-проектов" - "россия" (in its real stemmed form) must survive, "правительств" must not lead
    the captured entity."""
    signature = extract_story_signature(
        "Правительство России проработает новые меры поддержки ИИ-проектов", EventCategory.AI,
    )
    assert not any(e.startswith("правительств") for e in signature.entities)
    assert any("росси" in e for e in signature.entities)


def test_calibration_negative_controls_preserved() -> None:
    """Real negative controls from the checkpoint's own calibration - none of these are members of
    _CALIBRATED_GENERIC_PREFIX_ENTITIES, and none should be affected by this fix at all."""
    ai_sig = extract_story_signature(
        "Nebius увеличила выручку во II квартале в 5,5 раза за счет сегмента AI Cloud", EventCategory.AI,
    )
    assert "ai cloud" in ai_sig.entities  # standalone "ai" (149 real corpus occurrences) never stripped

    pixel_sig = extract_story_signature("Google Pixel 11 launch: Live updates", EventCategory.GADGETS)
    assert "google pixel" in pixel_sig.entities  # real company-prefixed product, untouched

    watch_sig = extract_story_signature("Apple Watch face gets new options", EventCategory.GADGETS)
    assert "apple watch" in watch_sig.entities

    bedrock_sig = extract_story_signature("Amazon Bedrock cost attribution guide", EventCategory.AI)
    assert "amazon bedrock" in bedrock_sig.entities

    copilot_sig = extract_story_signature("Write your first prompt with the GitHub Copilot app", EventCategory.SOFTWARE)
    assert "github copilot" in copilot_sig.entities


def test_cd_projekt_regression_unaffected_by_the_new_calibrated_set() -> None:
    """The already-shipped CD Projekt fix (_GENERIC_DETERMINER_ENTITIES's own "the"/"это" handling)
    must remain completely unaffected by the new, separate _CALIBRATED_GENERIC_PREFIX_ENTITIES set
    - re-run here as an explicit regression guard for this phase specifically, alongside the
    pre-existing dedicated CD Projekt tests above."""
    sig_bare = extract_story_signature(_CD_PROJEKT_TITLE_A, EventCategory.STARTUPS)
    sig_the = extract_story_signature(_CD_PROJEKT_TITLE_B, EventCategory.HARDWARE)
    assert "witcher" in sig_bare.entities
    assert "witcher" in sig_the.entities
    assert set(sig_bare.entities) & set(sig_the.entities)


def test_distinct_same_entity_vk_stories_remain_separate() -> None:
    """Regression guard: the fix must not cause an unrelated same-entity VK story to falsely merge
    - two genuinely different VK stories (earnings vs. a product launch) share the "vk" entity but
    must stay well below the confident-match threshold on title overlap alone."""
    title_earnings = _VK_TITLE_1
    title_product = "VK запустила новый видеосервис с функцией совместного просмотра для пользователей"
    sig_earnings = extract_story_signature(title_earnings, EventCategory.UNKNOWN)
    sig_product = extract_story_signature(title_product, EventCategory.STARTUPS)
    candidate = _story(title=title_earnings, entities=sig_earnings.entities, topic_bucket=sig_earnings.topic_bucket)

    combined, entity_overlap, title_overlap = score_candidate(
        title_product, sig_product, EventCategory.STARTUPS, title_earnings, candidate,
    )

    assert entity_overlap == 1.0  # "vk" genuinely shared - correct, not a false negative
    assert title_overlap < 0.3  # genuinely different stories - low title overlap
    from services.story_memory import _HIGH_THRESHOLD
    assert combined < _HIGH_THRESHOLD  # entity overlap alone never forces a confident merge


def test_generic_ai_entity_cannot_be_distinctive_identity_evidence() -> None:
    """Real shadow false-positive component: broad AI-topic language is not Story identity."""
    from services.story_memory import _distinctive_shared_entities

    result = _distinctive_shared_entities(
        ["\u0438\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d"],
        ["\u0438\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d"],
        {"\u0438\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d": 3},
        pool_size=56,
    )

    assert result == []


def test_real_specific_product_entity_remains_distinctive_identity_evidence() -> None:
    """Positive control: genuine product identity must remain usable."""
    from services.story_memory import _distinctive_shared_entities

    result = _distinctive_shared_entities(
        ["deepseek", "deepseek v4 pro"],
        ["deepseek", "deepseek v4 pro"],
        {"deepseek": 3, "deepseek v4 pro": 1},
        pool_size=56,
    )

    assert "deepseek v4 pro" in result


def test_short_two_word_product_entity_is_not_treated_as_a_publisher_domain() -> None:
    """Safety control for the Vietnam.vn fix: Apple TV is a product, not publisher metadata."""
    from services.story_memory import _distinctive_shared_entities

    result = _distinctive_shared_entities(
        ["apple tv"],
        ["apple tv"],
        {"apple tv": 1},
        pool_size=56,
    )

    assert "apple tv" in result


def test_russian_sentence_opener_kak_is_not_distinctive_identity_evidence() -> None:
    from services.story_memory import _distinctive_shared_entities

    result = _distinctive_shared_entities(
        ["\u043a\u0430\u043a"],
        ["\u043a\u0430\u043a"],
        {"\u043a\u0430\u043a": 1},
        pool_size=100,
    )

    assert result == []


def test_english_sentence_opener_we_is_not_distinctive_identity_evidence() -> None:
    from services.story_memory import _distinctive_shared_entities

    result = _distinctive_shared_entities(
        ["we"],
        ["we"],
        {"we": 1},
        pool_size=100,
    )

    assert result == []
