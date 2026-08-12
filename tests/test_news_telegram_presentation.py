"""Phase 23.1E - Telegram NEWS compact editorial profile.

Written test-first (docs/phase23_1e_telegram_news_compact_profile_report.md's own baseline
section records the exact pre-implementation import failure). Pure unit tests only - no DB, no
LLM, no Telegram - `services/news_telegram_presentation.py::build_compact_news_body()` is a
deterministic function of a plain dict.

Root cause this fixes (see the report's own §1/§2): Phase 23.1C's `_extract_title_and_body()`
concatenates ALL V6 narrative sections (opening/context/why_it_matters/what_changed/
what_happens_next/conclusion/what_remains_unknown) into one flat `ContentDraft.body` blob - correct
for persistence/Fact Safety, but far too long and repetitive for a Telegram NEWS card once
delivered. This module operates on the still-STRUCTURED V6 fields (never the flattened blob) to
select only the sentences a human editor would actually keep.

Eight required cases (phase brief "TEST-FIRST - COMPRESSION"), each using realistic, non-
hardcoded-story synthetic V6 fixtures (never the real Google Pay story - that is reserved for the
report's own dedicated BEFORE/AFTER regression, run separately against the real persisted data).
"""
from services.news_telegram_presentation import build_compact_news_body


def _v6(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "A generic placeholder title",
        "opening": "A company announced a new feature for its flagship product on Thursday.",
        "context": "The product has been updated regularly over the past two years.",
        "why_it_matters": "The update could change how millions of users interact with the service daily.",
        "what_changed": "The new feature adds AI-assisted suggestions to the product's core workflow.",
        "what_happens_next": None,
        "conclusion": "The company has not said when the feature will reach all users.",
        "what_remains_unknown": "The company did not disclose which specific capabilities will be included, when exactly they will roll out, or at what scale.",
        "quote": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CASE A - repeated unknowns collapse to at most one material uncertainty statement
# ---------------------------------------------------------------------------


def test_case_a_repeated_unknowns_collapse_to_at_most_one_uncertainty_statement() -> None:
    output = _v6(
        what_remains_unknown=(
            "Компания не уточнила, какие именно функции появятся, когда состоится запуск, "
            "и в каком масштабе он пройдёт."
        ),
        conclusion="Практический эффект станет понятен только после запуска первых инструментов.",
        what_happens_next="Подробности могут появиться позже.",
    )
    body = build_compact_news_body(output)

    uncertainty_markers = ("не уточнил", "неизвестно", "станет понятен", "появятся позже", "появиться позже")
    hits = sum(1 for marker in uncertainty_markers if marker in body.lower())
    assert hits <= 1, f"expected at most one uncertainty statement, found {hits} in: {body!r}"


# ---------------------------------------------------------------------------
# CASE B - a generic, non-material unknown is omitted entirely
# ---------------------------------------------------------------------------


def test_case_b_generic_unknown_omitted_entirely() -> None:
    output = _v6(
        what_remains_unknown="Компания не раскрыла дальнейшие планы по развитию функции.",
        conclusion=None,
        what_happens_next=None,
    )
    body = build_compact_news_body(output)
    assert "не раскрыла" not in body
    assert "дальнейшие планы" not in body


# ---------------------------------------------------------------------------
# CASE C - a genuinely material unknown is preserved as one concise caveat
# ---------------------------------------------------------------------------


def test_case_c_material_unknown_preserved_as_one_caveat() -> None:
    # conclusion/context/why_it_matters/what_changed are never null in real V6 output (only
    # what_happens_next/what_remains_unknown/quote are nullable, per prompts/copywriting/
    # v6.yaml's own schema) - kept as realistic, filler-classified text here so they are filtered
    # out for the reason this test is actually about (filler), not because the fixture itself is
    # an invalid V6 shape.
    output = _v6(
        what_remains_unknown="Неизвестно, вступит ли сделка в силу до конца квартала.",
        conclusion="Дальнейшее развитие покажет истинный масштаб изменений.",
        what_happens_next=None,
    )
    body = build_compact_news_body(output)
    assert "сделк" in body.lower()


def test_case_c_material_unknown_pricing_preserved() -> None:
    output = _v6(
        what_remains_unknown="Компания не назвала цену новой подписки.",
        conclusion="Остаётся следить за развитием ситуации.",
        what_happens_next=None,
    )
    body = build_compact_news_body(output)
    assert "цен" in body.lower()


# ---------------------------------------------------------------------------
# CASE D - repetition across V6 sections collapses to the strongest formulation, kept once
# ---------------------------------------------------------------------------


def test_case_d_repetition_across_sections_kept_once() -> None:
    output = _v6(
        opening="Компания запустила новую функцию ИИ в своём приложении.",
        why_it_matters="Компания запустила функцию ИИ в приложении, и это может затронуть миллионы пользователей.",
        what_changed="Компания запустила новую функцию ИИ в своём приложении.",
    )
    body = build_compact_news_body(output)
    # The near-identical opening/what_changed restatement must not both survive.
    assert body.count("запустила новую функцию ИИ в своём приложении") <= 1


# ---------------------------------------------------------------------------
# CASE E - a short story with only two useful facts stays short, never padded
# ---------------------------------------------------------------------------


def test_case_e_short_story_not_padded() -> None:
    # A short story: the required fields are all present (real V6 constraint - none of these five
    # are ever null), but context/why_it_matters/what_changed are near-restatements of opening
    # (as real V6 output for a genuinely thin story often is) and conclusion is filler - every one
    # of them is correctly filtered, leaving only the single genuine fact.
    output = _v6(
        opening="Компания обновила логотип на своём сайте.",
        context="Компания обновила логотип на своём сайте.",
        why_it_matters="Компания обновила логотип на своём сайте.",
        what_changed="Компания обновила логотип на своём сайте.",
        what_happens_next=None,
        conclusion="Дальнейшее развитие покажет истинный масштаб изменений.",
        what_remains_unknown=None,
    )
    body = build_compact_news_body(output)
    assert len(body) < 200
    assert body.strip() == "Компания обновила логотип на своём сайте."


# ---------------------------------------------------------------------------
# CASE F - a major story with several distinct facts keeps them even past the length guideline
# ---------------------------------------------------------------------------


def test_case_f_major_story_preserves_distinct_facts_within_the_new_ceiling() -> None:
    output = _v6(
        opening="Регулятор оштрафовал крупную технологическую компанию на 2 миллиарда евро за нарушение антимонопольного законодательства.",
        context="Расследование началось три года назад после жалоб конкурентов на злоупотребление рыночным положением.",
        why_it_matters="Это крупнейший штраф в отрасли за последние пять лет и может изменить правила работы всего рынка облачных сервисов.",
        what_changed="Компания обязана изменить условия работы со сторонними разработчиками в течение 90 дней.",
        conclusion="Компания уже заявила о намерении обжаловать решение в суде.",
        what_remains_unknown=None,
        what_happens_next=None,
    )
    # Phase 23.1I Part E "Importance-Aware Brevity V2": MAJOR's own paragraph cap dropped from 6 to
    # 4 and gained a real ~900-character ceiling (services/news_telegram_presentation.py's own
    # `_CHAR_CEILING_BY_TREATMENT`) - "the system MAY use more space if necessary, NOT the system
    # MUST write a long post." With 5 genuinely distinct real V6 sections, MAJOR now keeps the 4
    # highest-priority ones (opening/why_it_matters/what_changed/context - what happened, why it
    # matters, what changed, and the material background) and correctly drops the lowest-priority
    # one (a generic wrap-up "conclusion" sentence) - matching Part D's own explicit "do not force
    # a conclusion/recap" rule directly, not a regression from the previous phase's own test.
    from services.editorial_treatment import MAJOR

    body = build_compact_news_body(output, treatment=MAJOR)
    assert "оштрафовал" in body
    assert "изменить условия работы" in body
    assert "Расследование началось" in body
    assert "обжаловать" not in body  # the lowest-priority fact, correctly dropped under the new ceiling


# ---------------------------------------------------------------------------
# CASE G - no meaningful final observation exists -> the post simply ends, no filler conclusion
# ---------------------------------------------------------------------------


def test_case_g_no_filler_conclusion_generated() -> None:
    filler_conclusions = [
        "Его значение станет понятнее позже.",
        "Практический эффект ещё предстоит оценить.",
        "Остаётся следить за развитием ситуации.",
        "Покажет время.",
        "Подробности появятся позже.",
        "Пока это скорее сигнал, чем подтверждённое обновление.",
        "Дальнейшее развитие покажет истинный масштаб изменений.",
    ]
    for filler in filler_conclusions:
        output = _v6(conclusion=filler, what_happens_next=None, what_remains_unknown=None)
        body = build_compact_news_body(output)
        assert filler.rstrip(".") not in body, f"filler conclusion leaked through: {filler!r} -> {body!r}"


# ---------------------------------------------------------------------------
# CASE H - Fact Safety: a material caveat/attribution survives compression
# ---------------------------------------------------------------------------


def test_case_h_material_caveat_survives_compression() -> None:
    output = _v6(
        what_remains_unknown="Утечка не подтверждена официально, источник информации неизвестен.",
        conclusion="Остаётся следить за развитием ситуации.",
        what_happens_next=None,
    )
    body = build_compact_news_body(output)
    assert "утечк" in body.lower() or "не подтвержд" in body.lower()


# ---------------------------------------------------------------------------
# V4 pass-through (this module must never touch a V4-shaped draft's body)
# ---------------------------------------------------------------------------


def test_v4_shaped_output_passed_through_unchanged() -> None:
    output = {"title": "A V4 title", "body": "A V4 body with its own full text, untouched."}
    body = build_compact_news_body(output)
    assert body == "A V4 body with its own full text, untouched."


def test_missing_required_v6_fields_falls_back_to_body_or_empty() -> None:
    output = {"title": "X", "opening": "Only opening present, not V6-complete."}
    body = build_compact_news_body(output)
    assert isinstance(body, str)  # never raises - a safe, inspectable fallback


# ---------------------------------------------------------------------------
# Phase 23.1G §14 - HEDGE FAMILY COLLAPSING V2: 4-6 sections all express "not confirmed/
# insufficient details" in genuinely different wording -> maximum one caution statement in the
# final text; a genuinely material caveat still survives separately.
# ---------------------------------------------------------------------------


def test_5_sections_all_hedging_in_different_wording_collapse_to_one_caution() -> None:
    """Mirrors the real, live Phase 23.1F virus/bacteria story exactly: opening, why_it_matters,
    what_changed, context, and conclusion ALL independently hedge, each using different specific
    phrasing (different hedge families) - Phase 23.1E's own per-optional-section budget missed
    this because none of these are the SAME lexical restatement and three of the five are "core"
    sections it never capped at all. This is the precise root cause this phase's own hedge
    hardening V2 fixes."""
    output = _v6(
        opening="Заявление указывает на потенциально важное, но пока не подтвержденное направление в биомедицине.",
        why_it_matters="Медицинская ценность подхода реальна, но требует дополнительной проверки со стороны независимых экспертов.",
        what_changed="Представленных данных недостаточно, чтобы установить, идет ли речь о реальном эксперименте или прогнозе.",
        context="Доступные материалы не содержат сведений об авторах, дате или статусе исследования.",
        conclusion="Пока это не подтвержденный научный результат, требующий дополнительной проверки.",
        what_happens_next=None,
        what_remains_unknown=None,
    )
    body = build_compact_news_body(output, treatment="STANDARD")

    hedge_markers = (
        "не подтвержд", "требует дополнительной проверки", "данных недостаточно",
        "не содержат сведений", "требующий дополнительной проверки",
    )
    hits = sum(1 for marker in hedge_markers if marker in body.lower())
    assert hits <= 1, f"expected at most one surviving caution statement, found markers in: {body!r}"


def test_material_caveat_survives_alongside_the_hedge_cap() -> None:
    """The hedge-family cap must not accidentally swallow a genuinely material caveat - it either
    IS the one surviving family, or (if a core section already claimed the budget) is correctly
    omitted, but never silently truncated away by the paragraph-count cap purely because it is
    last in construction order (the real bug found and fixed during this phase's own development,
    see build_compact_news_body()'s own docstring). Uses the base `_v6()` fixture's own default
    core sections (already proven distinct from a pricing caveat by test_case_c_material_unknown_
    pricing_preserved) so this test isolates the paragraph-count-reservation behavior specifically,
    not an unrelated token-overlap false positive from reused vocabulary across custom fixtures."""
    output = _v6(what_remains_unknown="Компания не назвала цену новой подписки.")
    body = build_compact_news_body(output, treatment="STANDARD")
    assert "цен" in body.lower()


# ---------------------------------------------------------------------------
# Phase 23.1G §15 - CROSS-DRAFT ISOLATION: draft A's text can never appear in draft B's rendering.
# ---------------------------------------------------------------------------


def test_two_distinct_drafts_never_leak_into_each_other() -> None:
    """Direct proof at the presentation-function level: build_compact_news_body() is a pure
    function with no shared/global mutable state - two back-to-back calls with distinct,
    recognizable sentinel phrases must never cross-contaminate. The Phase 23.1G investigation's
    own real-data check (docs/phase23_1g_editorial_importance_source_quality_report.md §8) already
    confirmed zero contamination in the real Phase 23.1F persisted data; this is the corresponding
    permanent regression guard."""
    draft_a = _v6(
        opening="SENTINEL-ALPHA-9f3d: a completely unrelated story about a payments company.",
        why_it_matters="SENTINEL-ALPHA-9f3d matters because of its market share.",
        what_changed="SENTINEL-ALPHA-9f3d changed its pricing model this week.",
    )
    draft_b = _v6(
        opening="SENTINEL-BRAVO-7c1e: a completely unrelated story about a robotics lab.",
        why_it_matters="SENTINEL-BRAVO-7c1e matters because of a new research result.",
        what_changed="SENTINEL-BRAVO-7c1e changed its published benchmark this week.",
    )

    body_a = build_compact_news_body(draft_a)
    body_b = build_compact_news_body(draft_b)

    assert "SENTINEL-ALPHA-9f3d" in body_a
    assert "SENTINEL-BRAVO-7c1e" not in body_a
    assert "SENTINEL-BRAVO-7c1e" in body_b
    assert "SENTINEL-ALPHA-9f3d" not in body_b


# ---------------------------------------------------------------------------
# Phase 23.1I Part E "Importance-Aware Brevity V2" (docs/
# phase23_1i_live_editorial_hardening_report.md) - CASE 8/9/13.
#
# CASE 7/10/11 (plain language, abbreviations, omitted low-value technical detail) are addressed
# at the prompt level (prompts/copywriting/v7.yaml) - this module only selects/trims already-
# written V6 sentences, it never rewrites wording, so those cases cannot be unit-tested
# deterministically here. See test_v7_prompt_contains_the_required_plain_language_rules() below
# for the one thing that IS deterministically checkable: that the rule language actually exists in
# the prompt file.
# ---------------------------------------------------------------------------


def test_case_8_major_story_with_only_two_useful_facts_stays_short() -> None:
    """A MAJOR-treatment story whose real content only has two genuinely distinct, non-filler
    facts (what happened + why it matters) must not be padded to reach a longer length - "the
    system MAY use more space if necessary, NOT the system MUST write a long post." `context`/
    `what_changed`/`conclusion` are set to null/near-duplicates of the two real facts here, exactly
    mirroring the phase brief's own "if the complete story can be explained in 400 characters, a
    MAJOR story may still be 400 characters" example."""
    from services.editorial_treatment import MAJOR

    output = _v6(
        opening="Компания Firebird запустила в Армении первую очередь дата-центра для ИИ на технологиях NVIDIA.",
        why_it_matters="Весь проект рассчитан на мощность до 300 МВт и может стать одним из крупнейших центров такого типа в регионе.",
        context="Компания Firebird запустила в Армении первую очередь дата-центра для ИИ.",  # near-duplicate of opening - filtered
        what_changed="Компания Firebird запустила в Армении первую очередь дата-центра для ИИ на технологиях NVIDIA.",  # exact duplicate
        conclusion="Весь проект рассчитан на мощность до 300 МВт.",  # near-duplicate of why_it_matters - filtered
        what_happens_next=None,
        what_remains_unknown=None,
    )

    body = build_compact_news_body(output, treatment=MAJOR)

    assert body.count("\n\n") == 1  # exactly two paragraphs - nothing left to pad with
    assert len(body) < 450  # well under even BRIEF's own ceiling - genuinely short content stays short


def test_case_9_major_rich_story_may_use_additional_length() -> None:
    """The inverse of Case 8: when a MAJOR story genuinely has more than two distinct, important
    facts, they ARE kept (up to the treatment's own paragraph/ceiling budget) - the ceiling governs
    an upper bound, it does not force brevity when real substance exists."""
    from services.editorial_treatment import MAJOR

    output = _v6(
        opening="Крупный производитель чипов представил новый ИИ-ускоритель для дата-центров.",
        why_it_matters="Новый чип обещает вдвое более высокую энергоэффективность по сравнению с предыдущим поколением.",
        what_changed="Поставки начнутся в первом квартале следующего года крупнейшим облачным провайдерам.",
        context="Компания инвестировала более трёх миллиардов долларов в разработку новой архитектуры за четыре года.",
        conclusion="Чип станет доступен разработчикам вместе с обновлённым программным набором инструментов.",
        what_happens_next=None,
        what_remains_unknown=None,
    )

    body = build_compact_news_body(output, treatment=MAJOR)

    assert body.count("\n\n") >= 2  # more than the two-paragraph default - genuine extra substance kept
    assert "энергоэффективность" in body
    assert "трёх миллиардов" in body


def test_case_13_ordinary_standard_news_uses_the_two_paragraph_default() -> None:
    """An ordinary STANDARD story whose third candidate paragraph (context) is itself only
    marginally distinct is still capped by the two-paragraph default plus a genuinely useful third
    only when it exists and fits - here, `context` is deliberately a near-restatement so only two
    paragraphs survive, exactly the phase brief's own "HEADLINE / Paragraph 1: what happened /
    Paragraph 2: why it matters / STOP" default shape."""
    from services.editorial_treatment import STANDARD

    output = _v6(
        opening="Разработчик игр анонсировал дату выхода новой части популярной серии.",
        why_it_matters="Фанаты серии ждали продолжения почти шесть лет, и релиз может стать одним из самых заметных событий года в индустрии.",
        context="Разработчик анонсировал дату выхода новой части серии.",  # near-duplicate of opening
        what_changed="Фанаты серии ждали продолжения почти шесть лет.",  # near-duplicate of why_it_matters
        conclusion="Фанаты серии ждали продолжения почти шесть лет.",  # near-duplicate of why_it_matters
        what_happens_next=None,
        what_remains_unknown=None,
    )

    body = build_compact_news_body(output, treatment=STANDARD)

    assert body.count("\n\n") == 1  # exactly two paragraphs


def test_v7_prompt_contains_the_required_plain_language_rules() -> None:
    """Deterministic, structural check that Part D's plain-language rules actually exist in the
    v7 prompt text (the LLM's own generated wording cannot be unit-tested, but the instruction
    telling it what to do can be)."""
    from pathlib import Path

    prompt_text = Path("prompts/copywriting/v7.yaml").read_text(encoding="utf-8")
    assert "PLAIN LANGUAGE" in prompt_text
    assert "IMPORTANCE DOES NOT IMPLY LENGTH" in prompt_text
    assert "ABBREVIATION RULE" in prompt_text
    assert "TECHNICAL DETAIL RULE" in prompt_text
    # v6 itself must stay completely unmodified (prompt-immutability rule).
    v6_text = Path("prompts/copywriting/v6.yaml").read_text(encoding="utf-8")
    assert "PLAIN LANGUAGE" not in v6_text
