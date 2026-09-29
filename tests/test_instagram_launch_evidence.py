"""Launch-story evidence contract (founder task 2026-09-29, after the final natural canary 36b25f9).

The natural canary's #1 (a gadget launch) and #2 (an AI model launch) stopped at the viral evidence preflight although their fetched
articles supported them: the gadget's battery sentence fell behind the 6-fact cap while a glued 'related articles' line was kept, and the
model's 'replacing ... with' / 'презентовала новую модель' wording was not read as the hook's 'выпустила'. The primary proof uses the
EXACT saved sources (artifacts/instagram_launch_evidence/saved_sources.jsonl); the negatives prove no plan / rumour / unsupported
quantity / missing date can pass.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.instagram_evidence_package import (
    FACT,
    NOT_AVAILABLE,
    ORIGINAL_ARTICLE,
    STORED_BODY,
    EvidenceItem,
    EvidenceSource,
    SourceMedia,
    assemble_package,
    article_dateline,
    number_values,
    premise_quantities,
    recap_paragraphs,
)
from services.instagram_viral_nomination import evidence_preflight, launch_established

SAVED = Path(__file__).resolve().parent.parent / "artifacts/instagram_launch_evidence/saved_sources.jsonl"
NOW = datetime(2026, 9, 29, 11, 46, 25, tzinfo=UTC)  # the natural canary's clock
CURRENT = SimpleNamespace(type="CURRENT_EVENT")
# the nominated events' own hooks, exactly as the canary's nomination read them (attempt_1 / attempt_2 outcome.json)
GADGET_HOOK = ("Батарея на 11 000 мА·ч, прошлогодний Snapdragon и камера на 200 Мп: Honor представила геймерский смартфон Magic 9 "
               "Super")
MODEL_HOOK = "Anthropic выпустила нейросеть Claude Sonnet 5.5"
FILLER = ("The company described the product in detail during the event, including its design, pricing and the markets where it is sold. "
          "Reviewers noted the build quality and the software support policy, and several analysts compared it with rival products. "
          "Independent testers published first impressions covering speed, battery behaviour and how the interface feels in daily use. "
          "Retail partners listed the colour options and bundles, while forums discussed accessories and the included warranty terms.")


def _saved() -> dict[str, dict]:
    return {d["event_id"][:8]: d for d in (json.loads(line) for line in SAVED.read_text(encoding="utf-8").splitlines() if line.strip())}


def _package(saved: dict):
    stored = saved["content"] or saved["summary"]
    sources = [EvidenceSource(url=None, source_type=STORED_BODY, text=p) for p in recap_paragraphs(stored)] if stored else []
    sources.append(EvidenceSource(url=saved["canonical_url"], source_type=ORIGINAL_ARTICLE, text=saved["raw"], status=saved["status"]))
    return assemble_package(post_id=saved["event_id"], fmt="meme_trend", premise=saved["title"], sources=sources,
                            media=SourceMedia(status=NOT_AVAILABLE, reason="test"))


def _check(hook: str, lines: list[str], headlines: list[str] = ()):
    return evidence_preflight(hook, lines, actuality=CURRENT, now=NOW, headlines=list(headlines))


# --- the saved natural-canary sources -------------------------------------------------------------------------------------------------

def test_saved_gadget_launch_keeps_its_material_facts_and_passes():
    saved = _saved()["da549220"]
    package = _package(saved)
    facts = [f.exact_text for f in package.facts]
    assert any("11 000 мА·ч" in f for f in facts), "the battery sentence the story is about must survive packaging"
    assert any("200-Мп" in f for f in facts)
    assert not any(f.startswith("Обзор HONOR Pad") for f in facts), "the glued related-articles line is no longer kept over it"
    assert len(facts) == 6
    assert package.dateline == "28.09.2026"
    assert "28.09.2026" not in package.director_evidence()  # chronology evidence for the preflight only - never a Director fact
    result = _check(GADGET_HOOK, package.preflight_lines(), [saved["title"]])
    assert result.status == "PASS", result.checks
    assert result.checks["quantity"] == "SUPPORTED" and result.checks["chronology"] == "SUPPORTED"


def test_saved_model_launch_passes_on_its_first_copy():
    saved = _saved()["c728f8d6"]
    package = _package(saved)
    result = _check(MODEL_HOOK, package.preflight_lines(), [saved["title"]])
    assert result.status == "PASS", result.checks
    assert result.checks["action"] == "SUPPORTED"


def test_saved_russian_copy_reads_the_launch_but_still_needs_a_date():
    """'презентовала новую модель' supports 'выпустила'; this copy states no date at all, so it still fails - on chronology only."""
    saved = _saved()["10906658"]
    package = _package(saved)
    assert package.dateline is None
    result = _check(MODEL_HOOK, package.preflight_lines(), [saved["title"]])
    assert result.checks["action"] == "SUPPORTED"
    assert result.status == "FAIL" and result.checks["chronology"] == "UNSUPPORTED"


def test_saved_gadget_body_does_not_carry_a_different_battery():
    package = _package(_saved()["da549220"])
    result = _check(GADGET_HOOK.replace("11 000", "12 000"), package.preflight_lines())
    assert result.status == "FAIL" and result.checks["quantity"] == "UNSUPPORTED"  # '12' (12 Гбайт) + '000' elsewhere is not 12 000


def test_saved_gadget_body_without_its_dateline_has_no_chronology():
    package = _package(_saved()["da549220"])
    lines = [f.exact_text for f in (*package.steps, *package.facts, *package.limitations)]
    assert _check(GADGET_HOOK, lines).checks["chronology"] == "UNSUPPORTED"


# --- launch semantics: ordinary wording counts, plans / rumours never do ------------------------------------------------------------

@pytest.mark.parametrize("sentence", [
    "Nimbus released Model X today, replacing the previous Model W.",
    "Nimbus has launched Model X for all users on September 28.",
    "Nimbus introduced Model X at its event on September 28.",
    "Nimbus unveiled Model X on September 28.",
    "Model X is now available in the app since September 28.",
    "Nimbus is replacing Model W with Model X as its default model, starting September 28.",
    "Nimbus представила Model X 28 сентября.",
    "Nimbus презентовала новую модель Model X 28 сентября.",
    "Model X уже доступна для предзаказа с 28 сентября.",
])
def test_ordinary_launch_wording_supports_a_release_hook(sentence):
    result = _check("Nimbus выпустила Model X", [sentence + " " + FILLER])
    assert result.checks["action"] == "SUPPORTED", sentence
    assert result.status == "PASS", result.checks


@pytest.mark.parametrize("sentence", [
    "Nimbus plans to release Model X next month.",
    "Rumours suggest Model X may launch on September 28.",
    "A leaked roadmap mentions Model X as a future model.",
    "Nimbus is considering a new product called Model X.",
    "Nimbus will launch Model X on September 28.",
    "Nimbus is expected to unveil Model X on September 28.",
    "Nimbus has not released Model X yet, as of September 28.",
    "Nimbus cancelled the release of Model X on September 28.",
    "Nimbus teased Model X on September 28, with a release coming soon.",
    "Nimbus планирует выпустить Model X в следующем месяце.",
    "По слухам, Nimbus представит Model X 28 сентября.",
    "Nimbus отменила выпуск Model X 28 сентября.",
    "Nimbus готовит Model X, анонс ожидается 28 сентября.",
])
def test_plans_rumours_and_denials_never_support_a_release_hook(sentence):
    result = _check("Nimbus выпустила Model X", [sentence + " " + FILLER])
    assert result.checks["action"] == "UNSUPPORTED", sentence
    assert result.status == "FAIL"


def test_a_release_of_a_different_product_does_not_support_the_hook():
    result = _check("Nimbus выпустила Model X", ["Nimbus released Model Q on September 28. " + FILLER])
    assert result.checks["action"] == "UNSUPPORTED"


def test_an_earlier_version_of_the_model_does_not_support_the_new_one():
    result = _check("Nimbus выпустила Model X 5.5", ["Nimbus released Model X 5 on September 28 for every user. " + FILLER])
    assert result.checks["action"] == "UNSUPPORTED"


def test_a_leak_of_unannounced_features_is_not_a_launch():
    body = ["Leaked code reveals new Nimbus Fold features not yet announced, dated September 28. " + FILLER]
    assert _check("Nimbus выпустила Nimbus Fold", body).checks["action"] == "UNSUPPORTED"


def test_the_launch_sentence_must_itself_be_realised():
    """A realised launch elsewhere does not rescue a plan about the hook's product."""
    assert not launch_established("Nimbus выпустила Model X", ["Nimbus plans to release Model X next month."])
    assert launch_established("Nimbus выпустила Model X", ["Nimbus plans more.", "Nimbus released Model X today."])


def test_future_and_absent_launch_dates_do_not_support_chronology():
    base = "Nimbus released Model X. " + FILLER
    assert _check("Nimbus выпустила Model X", [base]).checks["chronology"] == "UNSUPPORTED"
    assert _check("Nimbus выпустила Model X", [base, "01.12.2026"]).checks["chronology"] == "UNSUPPORTED"  # after the clock: a plan
    assert _check("Nimbus выпустила Model X", [base, "28.09.2026"]).checks["chronology"] == "SUPPORTED"


# --- quantities: whole numbers only ---------------------------------------------------------------------------------------------------

def test_number_values_reads_grouped_numbers_as_one_number():
    assert number_values("11 000 мА·ч") == {"11000"}
    assert number_values("11\u00a0000 and 11,000 and 11000") == {"11000"}
    assert number_values("4,6 ГГц, 5.5, 70,6%") == {"4.6", "5.5", "70.6"}


def test_unsupported_quantities_still_fail():
    body = ["Nimbus released the X1 phone on September 28 with a 10 000 mAh battery and 12 GB of memory. " + FILLER]
    assert _check("Nimbus выпустила X1 с батареей на 12 000 мА·ч", body).checks["quantity"] == "UNSUPPORTED"
    assert _check("Nimbus выпустила X1 с батареей на 10 000 мА·ч", body).checks["quantity"] == "SUPPORTED"
    assert _check("Nimbus выпустила X1 с батареей на 1 000 мА·ч", body).checks["quantity"] == "UNSUPPORTED"


# --- the package: premise facts survive, nothing changes for small packages ------------------------------------------------------

def _items(texts):
    return [EvidenceSource(url="https://example.test/a", source_type=ORIGINAL_ARTICLE, text="\n".join(texts))]


def test_premise_quantities_skip_years_and_model_digits():
    assert premise_quantities("Battery of 11 000 mAh and a 200 MP camera: Magic 9 in 2026") == ["11000", "200"]


def test_small_packages_are_unchanged():
    title = "Nimbus X1 phone gets a 10 000 mAh battery"
    lines = [title, "Nimbus has introduced the X1 phone with a very large battery for gamers this week.",
             "The phone relies on a 10 000 mAh battery made with a new silicon-carbon chemistry and fast charging.",
             "Related reading The best phones of the year Our picks for gaming phones Source: Nimbus"]
    package = assemble_package(post_id="p", fmt="meme_trend", premise=title, sources=_items(lines),
                               media=SourceMedia(status=NOT_AVAILABLE))
    assert [f.exact_text for f in package.facts] == lines[1:]  # 3 candidates <= 6: every one kept, in order, as before


def test_premise_fact_beats_unpunctuated_run_but_keeps_source_order():
    title = "Nimbus X1 phone gets a 10 000 mAh battery"
    prose = ["The display uses a bright flexible OLED panel with thin bezels around every edge.",
             "Its processor comes from last year's flagship line and runs at a high clock speed.",
             "The camera module includes a wide lens, an ultrawide lens and a periscope telephoto.",
             "Cooling relies on a vapour chamber that the company says keeps games smooth for hours.",
             "Four colour finishes are offered, including a matte green and a glossy white option.",
             "Storage configurations range from a modest base model up to a very large top tier.",
             "Wireless charging and reverse charging are both supported by the charging circuit."]
    glued = "Related reading The best phones of the year Our picks for gaming phones Source images:"
    battery = "The phone relies on a 10 000 mAh battery made with a new silicon-carbon chemistry."
    lines = [title, prose[0], prose[1], glued, *prose[2:], battery]
    package = assemble_package(post_id="p", fmt="meme_trend", premise=title, sources=_items(lines),
                               media=SourceMedia(status=NOT_AVAILABLE))
    facts = [f.exact_text for f in package.facts]
    assert battery in facts and glued not in facts and len(facts) == 6
    assert facts == sorted(facts, key=lines.index)  # the accepted order is kept


def test_dateline_is_read_only_under_the_articles_own_title():
    title = "Nimbus X1 phone gets a 10 000 mAh battery"
    body = "\n".join(["Сегодня 29.09.2026", "Menu", title, "28.09.2026", "[17:02], Author Name",
                      "Nimbus has introduced the X1 phone with a very large battery for gamers this week."])
    assert article_dateline(body, title) == "28.09.2026"
    no_dateline = "\n".join(["Сегодня 29.09.2026", title, "Nimbus has introduced the X1 phone with a very large battery for gamers."])
    assert article_dateline(no_dateline, title) is None  # the site header's date is above the title - never read


def test_fact_item_kind_is_unchanged():
    item = EvidenceItem(kind=FACT, text="x", source_url=None, source_type=ORIGINAL_ARTICLE)
    assert item.exact_text == "x"


# --- the worker reads the dateline --------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_worker_preflight_reads_the_packages_dateline(monkeypatch: pytest.MonkeyPatch):
    """worker.content_cycle._viral_evidence_copy gives the preflight the package's items AND its dateline (chronology evidence)."""
    from uuid import UUID

    import worker.content_cycle as cc

    seen: list[list[str]] = []

    def fake_preflight(event, *, title, body_lines, published_at=None, now=None):
        seen.append(list(body_lines))
        return SimpleNamespace(status="PASS")

    async def package(session, event_id, row, slot_format):
        return SimpleNamespace(steps=(), facts=(SimpleNamespace(exact_text="Nimbus released Model X."),), limitations=(),
                               dateline="28.09.2026")

    class Session:
        async def get(self, model, ident):
            return None

    monkeypatch.setattr(cc, "_feed_evidence_package", package)
    monkeypatch.setattr(cc, "viral_evidence_preflight", fake_preflight)
    row = SimpleNamespace(title="Nimbus X", url="https://example.org/x", published_at=None)
    await cc._viral_evidence_copy(Session(), None, UUID(int=1), row, slot_format=None, now=NOW)
    assert seen == [["Nimbus released Model X.", "28.09.2026"]]
