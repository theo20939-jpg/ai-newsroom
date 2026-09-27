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
Canary 3 (2026-09-27): Phase A's reasoning explains what NOT to claim ('не воспринимать историю как доказанный «взлом» всех трёх ведомств'),
so a status finding whose action / status word the clause itself DENIES is not a Phase A claim (the downstream Director gate is unchanged
and still sees only audience copy); and creative_direction must be a COMPLETE plan - a string that ends on a continuation mark
(INCOMPLETE_CREATIVE_DIRECTION) never reaches the Director.
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


# double negation that AFFIRMS the possibility ('нельзя исключать, что агент взломал', 'не исключено') - never a denial of the claim
_AFFIRMING = re.compile(r"(?i)\bнельзя\s+исключ\w*|\bне\s+исключ\w*|\bнельзя\s+не\b|\bне\s+может\s+не\b|\bcannot\s+be\s+ruled\s+out\b|"
                        r"\bcan'?t\s+rule\s+out\b|\bnot\s+impossible\b")
# what DENIES an action / status word: a plain negator (affirming idioms excluded) or 'без доказательств / подтверждения' - never a bare 'без'
_ACTION_NEGATOR = re.compile(r"(?i)(?<![\w-])(?:не(?!\s+(?:только|просто|менее|меньше|хуже|удивительно|секрет|случайно))|нет|ни|нельзя(?!\s+не\b)|"
                             r"невозможно|no|not|never|cannot)(?![\w-])|\bбез\s+(?:доказательств\w*|подтвержд\w*|оснований)")
_ACTION_NEGATION_WORDS = 6
# a denial AFTER the claimed word, inside the same clause ('формулировка «взлом» здесь не подтверждена')
_DENIED_AFTER = re.compile(r"(?i)\bотсутству\w*|\bне\s+подтвержд\w*|\bне\s+доказан\w*|\bне\s+является\b|\bнет\s+(?:доказательств|данных|подтвержд\w*)|"
                           r"\bnot\s+(?:confirmed|proven|established)\b|\bunconfirmed\b|\bunproven\b")


def _claim_denied(clause: str, kind: str = "") -> bool:
    """True when every word the VIOLATION is about (the intrusion verb of a stronger-verb finding, the 'confirmed' word of a promotion, the
    reaching verb of a grouping / count / qualifier / attempt finding) is DENIED by that clause itself: a negation in its own scope (the Phase A
    trend guard's clause scope - a complement clause extends it, a contrastive conjunction / sentence / dash ends it) or a denial after it.
    Affirming idioms ('не только', 'не просто', 'неудивительно', 'нельзя исключать', 'не исключено') never deny. A quoted word is not
    safe by itself - only its clause's polarity counts."""
    from services.instagram_creative_director import _SCOPE_BREAK, _negation_scope
    from services.instagram_factual_status import _ACCESS, _CONFIRMED, _INTRUSION

    patterns = {"stronger_verb": (_INTRUSION,), "promoted_confirmed": (_CONFIRMED,)}.get(kind, (_ACCESS, _INTRUSION))
    matches = [m for p in patterns for m in p.finditer(clause)]
    if not matches:
        return False
    for m in matches:
        # the negator must govern THIS word: inside its clause scope and within the last _ACTION_NEGATION_WORDS words before it - a bare 'без'
        # ('без активных инструкций получил доступ') negates something else, never the access
        before = " ".join(_negation_scope(clause, m.start()).split()[-_ACTION_NEGATION_WORDS:])
        after = clause[m.end():]
        boundary = _SCOPE_BREAK.search(after)  # a denial after the word counts only up to the next scope break ('..., хотя ...')
        denied = ((bool(_ACTION_NEGATOR.search(before)) and not _AFFIRMING.search(before))
                  or bool(_DENIED_AFTER.search(after[:boundary.start()] if boundary else after)))
        if not denied:
            return False
    return True


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
            if _claim_denied(v.generated_claim, v.kind):
                continue  # Phase A explains what NOT to claim - a denial is not an assertion (every field stays checked)
            found.append(f"Phase A {field}: " + v.render().split(": ", 1)[1].replace("slide 1 headline", field))
    return list(dict.fromkeys(found))


_CONTINUATION_TAIL = re.compile(r"[,;:]\s*$|\s[—–-]\s*$|[—–]\s*$")


def incomplete_creative_direction(decision: Any) -> str | None:
    """INCOMPLETE_CREATIVE_DIRECTION: the plan visibly stops mid-sentence - it ends on a comma, semicolon, colon or a continuation dash, or
    leaves a quote / bracket open. A normal sentence ending in punctuation or a closing quote passes (no grammar checking beyond that)."""
    text = _get(decision, "creative_direction").rstrip()
    if not text:
        return None
    reasons = []
    if _CONTINUATION_TAIL.search(text):
        reasons.append(f"ends on a continuation mark ({text[-1]!r})")
    if text.count('"') % 2:
        reasons.append("an unclosed quote (\")")
    if text.count("«") > text.count("»"):
        reasons.append("an unclosed quote («)")
    # „…“ (Russian / German: “ closes) and “…” (English: “ opens) share the “ mark: the “ left over after closing every „ opens an English quote
    low, left, right = text.count("„"), text.count("“"), text.count("”")
    if low > left or max(0, left - low) > right:
        reasons.append("an unclosed quote („ / “)")
    for opening, closing in (("(", ")"), ("[", "]")):
        if text.count(opening) > text.count(closing):
            reasons.append(f"an unclosed bracket ({opening})")
    if not reasons:
        return None
    return (f"INCOMPLETE_CREATIVE_DIRECTION: creative_direction {' and '.join(reasons)} - the plan reached the Director cut off "
            f"('...{text[-60:]}'); write a complete plan of at most 650 characters")


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
    tail = incomplete_creative_direction(decision)
    return [*phase_a_status_findings(decision, evidence), *phase_a_visual_findings(decision), *phase_a_finale_findings(decision, evidence),
            *([tail] if tail else [])]


def phase_a_status_note(evidence: list[str]) -> str:
    """The compact factual-status summary Phase A receives (the existing ledger's own rendering); empty when no target has a status."""
    return ledger_note(build_status_ledger(evidence))
