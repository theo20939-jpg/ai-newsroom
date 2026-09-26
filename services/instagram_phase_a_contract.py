"""PHASE A CONTRACT for the KAGE feed product (founder task 2026-09-27, after the second paid viral canary). Deterministic - no model call.

The second canary died at Phase A, and the same Phase A output would have seeded the Creative Director with three problems the downstream
gates were built to reject: a summary that collapsed target statuses ('получил доступ к сайтам Министерства торговли, Министерства
образования и SEC' - Education is still under investigation), a creative direction asking for 'интерфейс государственного сайта' (a
fabricated official interface), and a planned debate finale about 'where the boundary of AI autonomy should be' that the evidence never
raises. Phase A is now held to what the Director is held to, BEFORE the Director:
  1. target-specific factual status - the EXISTING ledger and gate (services.instagram_factual_status), run over Phase A's own prose;
  2. visual safety - no fabricated official material (government / agency / official interfaces, fake screenshots, fake documents or
     evidence); real source photos, abstract infrastructure imagery, non-literal digital imagery and typographic compositions are fine;
  3. a grounded finale - DEBATE stays a valid angle, but the planned final question / poll may not invent governance, ethics, 'who should
     decide' or responsibility framing the evidence does not raise; an unresolved fact, the company's response, a consequence or a factual
     takeaway are fine.
Chronology and trend truth are the Phase A prompt's own rules and the (negation-aware) trend-rationale guard.
Phase A has no retry: a violation is an EditorialDecisionContractError (terminal) - the prompt carries the same contract, so the model is
told before it is checked."""
from __future__ import annotations

import re
from typing import Any

from services.instagram_factual_status import build_status_ledger, ledger_note, status_violations

# Phase A prose that can seed the Director (the product / trend fields are checked by their own guards)
_PROSE_FIELDS = ("source_summary", "why_now", "audience_value", "angle", "topic", "format_reason", "creative_direction")
_PLAN_FIELDS = ("angle", "format_reason", "creative_direction")

_OFFICIAL = (r"(?:государственн\w*|правительствен\w*|официальн\w*|министерств\w*|ведомств\w*|госсайт\w*|госпортал\w*|government|official|"
             r"agency|federal|ministry|department)")
_FAKE_UI = re.compile(
    rf"(?i)(?:интерфейс\w*|скриншот\w*|скрин\b|макет\w*\s+сайт\w*|страниц\w*\s+входа|окн\w*\s+входа|форм\w*\s+входа|\bui\b|interface|"
    rf"screenshot|mock-?up|login (?:page|screen))[^.;]{{0,40}}{_OFFICIAL}"
    rf"|{_OFFICIAL}[^.;]{{0,30}}(?:интерфейс\w*|скриншот\w*|\bui\b|interface|screenshot|login (?:page|screen))"
    r"|(?:фейков\w*|поддельн\w*|сфабрикован\w*|имитаци\w*|fake|fabricated|mock)[^.;]{0,30}"
    r"(?:документ\w*|скриншот\w*|интерфейс\w*|доказательств\w*|переписк\w*|document|screenshot|interface|evidence)"
    r"|(?:документ\w*|письм\w*|приказ\w*|бланк\w*)\s+(?:с\s+печатью|с\s+гербом|ведомства|министерства|правительства)")
_FINALE = re.compile(r"(?i)(?:финал\w*|в\s+конце|заверш\w*|последн\w*\s+слайд\w*|закрыва\w*|вынести|итогов\w*\s+слайд\w*|final\s+slide|ends?\s+with)"
                     r"[^.;]{0,90}(?:вопрос\w*|опрос\w*|обсужден\w*|дискусси\w*|дебат\w*|poll|question|debate)"
                     r"|(?:вопрос\w*|опрос\w*|poll|question)[^.;]{0,40}(?:на\s+обсуждение|в\s+финал\w*|в\s+конце|for\s+discussion)")
# framing that turns a story into an invented governance / ethics debate (evidence-grounded only when the evidence itself raises it)
_GOVERNANCE_TERMS = ("границ", "кто должен", "должна проходить", "должен ли", "должны ли", "контрол", "ответствен", "этик", "регулир",
                     "допустим", "кто решает", "кто должен решать", "человек или агент", "who should", "responsib", "ethic", "regulat", "boundar")


def _negated(text: str, start: int, end: int) -> bool:
    from services.instagram_creative_director import _trend_mention_negated

    return _trend_mention_negated(text, start, end)


def _get(decision: Any, name: str) -> str:
    value = decision.get(name) if isinstance(decision, dict) else getattr(decision, name, None)
    return str(value or "")


def phase_a_status_findings(decision: Any, evidence: list[str]) -> list[str]:
    ledger = build_status_ledger(evidence)
    if not ledger:
        return []
    found = []
    for field in _PROSE_FIELDS:
        text = _get(decision, field)
        if not text.strip():
            continue
        for v in status_violations([{"slide_copy": text}], "", ledger, evidence):
            found.append(f"Phase A {field}: " + v.render().split(": ", 1)[1].replace("slide 1 headline", field))
    return list(dict.fromkeys(found))


def phase_a_visual_findings(decision: Any) -> list[str]:
    found = []
    for field in ("creative_direction", "supplementary_story_idea"):
        text = _get(decision, field)
        for m in _FAKE_UI.finditer(text):
            if not _negated(text, m.start(), m.end()):
                found.append(f"Phase A {field}: fabricated official material ('{m.group(0).strip()}') - use the real source photo, abstract "
                             "infrastructure imagery, non-literal digital imagery or a typographic composition; never an imitation official "
                             "interface, a fake screenshot, document or evidence")
    return list(dict.fromkeys(found))


def phase_a_finale_findings(decision: Any, evidence: list[str]) -> list[str]:
    corpus = " ".join(evidence).lower()
    found = []
    for field in _PLAN_FIELDS:
        text = _get(decision, field)
        for sentence in re.split(r"(?<=[.!?])\s+|;\s*", text):
            m = _FINALE.search(sentence)
            if not m or _negated(sentence, m.start(), m.end()):
                continue
            invented = [t for t in _GOVERNANCE_TERMS if t in sentence.lower() and t not in corpus]
            if invented:
                found.append(f"Phase A {field}: the planned final question / poll invents governance framing the evidence does not raise "
                             f"({', '.join(invented)}: '{sentence.strip()[:160]}') - plan a grounded final slide: an unresolved fact, the "
                             "company's response, a consequence or a factual takeaway")
    return list(dict.fromkeys(found))


def phase_a_contract_findings(decision: Any, evidence: list[str]) -> list[str]:
    return [*phase_a_status_findings(decision, evidence), *phase_a_visual_findings(decision), *phase_a_finale_findings(decision, evidence)]


def phase_a_status_note(evidence: list[str]) -> str:
    """The compact factual-status summary Phase A receives (the existing ledger's own rendering); empty when no target has a status."""
    return ledger_note(build_status_ledger(evidence))
