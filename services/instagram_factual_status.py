"""TARGET STATUS SAFETY for viral carousels (founder task 2026-09-27, after the first paid viral canary). Deterministic - no model call.

The canary's evidence said: OpenAI CONFIRMED access to the Commerce Department and the SEC; the Education Department episode is STILL
UNDER INVESTIGATION. The Director's first version kept that apart; the one editorial correction collapsed it into 'с доступом к трём
ведомствам'. A factual status must survive Director -> correction -> judge -> final copy:

  1. build_status_ledger(evidence): per TARGET (an institution / organisation the evidence names), the claim and its STATUS - CONFIRMED,
     REPORTED (the evidence states it, nobody confirms it), UNDER_INVESTIGATION, ATTEMPTED, FAILED_ATTEMPT, UNCONFIRMED, DISPUTED - with
     the evidence handles (E1.., the handles the Director and the judge see), the qualifier and the assertion strength it allows. When lines
     disagree, the most cautious status wins (a confirmed line never erases an 'under investigation' line for the same target).
  2. status_violations(texts, ledger): a HARD fact-safety check of the generated copy, clause by clause - a qualified target (under
     investigation / attempted / failed / unconfirmed / disputed) inside an unqualified 'accessed' claim, the same thing hidden in a count
     ('доступ к трём ведомствам' when two are confirmed), promotion to 'confirmed', attempt -> completed, failure -> success, uncertain ->
     fact, an intrusion verb ('взломал') the evidence never uses, and a 'today' claim about behaviour the evidence dates earlier.
  3. factual_invariants / non_regression_findings: what the version sent to the one editorial correction already got right (its target
     statuses, chronology markers, the strength of its action verbs); the corrected version may not lose any of it - a correction that
     fixes style by drifting facts is rejected, and the original stays available for diagnosis.
  4. slide_thesis_role: HOOK / EVENT_ACTION / TARGET_STATUS / CHRONOLOGY / COMPANY_RESPONSE / CONSEQUENCE / OPEN_QUESTION / DETAIL, so
     'what the agent did' and 'which parts are confirmed' are never reported as one thesis.
  5. factual_terms: short status-critical wording (target names, 'подтвердила', 'расследование продолжается', dates, numbers, Latin names)
     that the copied-wording rule must not force the Director to paraphrase.
Nothing here names a story: the target lexicon is institutions in general, the statuses are the evidence's own words."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.IGNORECASE)


# --- targets -------------------------------------------------------------------------------------------------------------------------
# government departments by their subject, in Russian (any case of 'Министерство' / the short 'Мин-' forms) and English
_DEPARTMENTS: dict[str, tuple[str, str]] = {  # key -> (Russian subject stem pattern, English subject pattern)
    "commerce": (r"торговл\w*", r"commerce"),
    "education": (r"образовани\w*|просвещени\w*", r"education"),
    "justice": (r"юстици\w*", r"justice"),
    "defense": (r"оборон\w*", r"defen[cs]e"),
    "treasury": (r"финанс\w*|казначейств\w*", r"treasury"),
    "health": (r"здравоохранени\w*", r"health(?: and human services)?"),
    "energy": (r"энергетик\w*", r"energy"),
    "labor": (r"труда", r"labou?r"),
    "transportation": (r"транспорт\w*", r"transportation"),
    "homeland_security": (r"внутренней безопасности", r"homeland security"),
    "agriculture": (r"сельского хозяйства", r"agriculture"),
    "interior": (r"внутренних дел", r"interior"),
}
_SHORT_MINISTRY = {"commerce": r"минторг\w*", "education": r"минобр\w*|минпрос\w*", "justice": r"минюст\w*", "defense": r"минобороны",
                   "treasury": r"минфин\w*", "health": r"минздрав\w*", "energy": r"минэнерго"}
_AGENCIES: dict[str, str] = {  # key -> pattern (acronyms case-sensitive via inline groups below)
    "sec": r"(?-i:\bSEC\b)|\bкомисси\w* по ценным бумагам(?: и биржам)?|\bsecurities and exchange commission\b",
    "fbi": r"(?-i:\bFBI\b|\bФБР\b)",
    "cia": r"(?-i:\bCIA\b|\bЦРУ\b)",
    "nsa": r"(?-i:\bNSA\b|\bАНБ\b)",
    "nasa": r"(?-i:\bNASA\b)|\bнаса\b",
    "ftc": r"(?-i:\bFTC\b)|\bfederal trade commission\b|\bфедеральн\w* торгов\w* комисси\w*",
    "fcc": r"(?-i:\bFCC\b)",
    "irs": r"(?-i:\bIRS\b)|\bналогов\w* служб\w* сша\b",
    "census_bureau": r"\bcensus bureau\b|\bбюро переписи\w*",
    "pentagon": r"\bpentagon\b|\bпентагон\w*",
    "white_house": r"\bwhite house\b|\bбел(?:ый|ого|ом) дом\w*",
    "hugging_face": r"\bhugging ?face\b",
    "github": r"\bgithub\b",
}


def _target_patterns() -> dict[str, re.Pattern[str]]:
    out: dict[str, re.Pattern[str]] = {}
    for key, (ru, en) in _DEPARTMENTS.items():
        parts = [rf"\bминистерств\w*\s+(?:{ru})", rf"\b(?:department|dept\.?)\s+of\s+(?:the\s+)?{en}\b", rf"\b{en}\s+(?:department|dept\b\.?)"]
        if re.fullmatch(r"[a-z]+", en):  # the bare English subject inside Russian copy ('Commerce и SEC') - capitalised only
            parts.append(rf"(?-i:\b{en[0].upper()}{en[1:]}\b)")
        if key in _SHORT_MINISTRY:
            parts.append(rf"\b(?:{_SHORT_MINISTRY[key]})\b")
        out[key] = re.compile("|".join(parts), re.IGNORECASE)
    for key, pattern in _AGENCIES.items():
        out[key] = re.compile(pattern, re.IGNORECASE)
    return out


_TARGETS = _target_patterns()


def mentioned_targets(text: str) -> list[str]:
    return [key for key, pattern in _TARGETS.items() if pattern.search(text or "")]


def target_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for pattern in _TARGETS.values() for m in pattern.finditer(text or "")]


# --- status vocabulary (the evidence's own words, RU / EN) ---------------------------------------------------------------------------
_FAILED = _rx(r"\bне удал\w*", r"\bбезуспешн\w*", r"\bfailed to\b", r"\bunsuccessful\w*", r"\bwas blocked\b", r"\bне смог\w*")
_DISPUTED = _rx(r"\bотрица\w*", r"\bопроверг\w*", r"\bdenie[sd]\b", r"\bdeny\b", r"\bdisput\w*")
_INVESTIGATION = _rx(r"\bрасследу\w*", r"\bрасследовани\w*", r"\bпроверя\w*", r"\bвыясня\w*", r"\bизуча\w*", r"\binvestigat\w*",
                     r"\blooking into\b", r"\bunder review\b", r"\bясности\s+(?:пока\s+)?нет\b", r"\bнет\s+ясности\b")
_UNCONFIRMED = _rx(r"\bне подтвержд\w*", r"\bнеподтвержд\w*", r"\bне подтвердил\w*", r"\bпредположительн\w*", r"\bвозможно\b", r"\bякобы\b", r"\bunconfirmed\b",
                   r"\ballegedly\b", r"\breportedly\b", r"\bpossibly\b", r"\bsupposed\w*")
_ATTEMPT = _rx(r"\bпыта\w*", r"\bпытал\w*", r"\bпопытк\w*", r"\bпробова\w*", r"\btried\b", r"\btries\b", r"\battempt\w*", r"\btrying\b")
_CONFIRMED = _rx(r"(?<!не )\bподтверди\w*", r"(?<!не )\bподтвержд\w*", r"\bconfirm(?:s|ed)?\b", r"\bпризнал\w*", r"\badmit\w*")
# completion of the action on a target (reaching it)
_ACCESS = _rx(r"\bдоступ\w*", r"\bдобрал\w*", r"\bзаш[её]л\w*", r"\bзашл\w*", r"\bпроник\w*", r"\bвзлом\w*", r"\bвломил\w*",
              r"\baccess(?:ed|es|ing)?\b", r"\bgot into\b", r"\blogged in(?:to)?\b", r"\bbreach\w*", r"\binfiltrat\w*", r"\bcompromis\w*",
              r"\bhack(?:ed|s|ing)?\b", r"\bpulled (?:data|information)\b", r"\bзатронут\w*", r"\bпострадал\w*", r"\baffected\b",
              r"\bатаков\w*", r"\battacked\b", r"\btargeted\b")
# action strength: interaction < access < intrusion ('no hack compression': an intrusion verb needs intrusion in the evidence)
_INTERACTION = _rx(r"\bвзаимодейств\w*", r"\bходил\w*", r"\bзаходил\w*", r"\bобращал\w*", r"\binteract\w*", r"\bvisited\b", r"\bengaged with\b")
_INTRUSION = _rx(r"\bвзлом\w*", r"\bвломил\w*", r"\bпроник\w*", r"\bатаков\w*", r"\bhack\w*", r"\bbreach\w*", r"\binfiltrat\w*",
                 r"\bcompromis\w*", r"\battack\w*", r"\bвышл\w* из-под контроля\b", r"\bвзбунтовал\w*", r"\bwent rogue\b", r"\bgone rogue\b")
_COUNT_WORDS = {"два": 2, "две": 2, "двух": 2, "двум": 2, "обоим": 2, "оба": 2, "обе": 2, "три": 3, "трёх": 3, "трех": 3, "трём": 3, "трем": 3,
                "четыре": 4, "четырёх": 4, "четырех": 4, "четырём": 4, "четырем": 4, "пять": 5, "пяти": 5, "шесть": 6, "шести": 6,
                "two": 2, "both": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_GROUP_NOUN = r"(?:ведомств\w*|министерств\w*|агентств\w*|учреждени\w*|госорган\w*|организаци\w*|сайт\w*|ресурс\w*|agenc\w*|departments?|sites?|websites?|institutions?)"
_COUNT = re.compile(rf"(?i)\b(\d+|{'|'.join(sorted(_COUNT_WORDS, key=len, reverse=True))})\s+(?:\w+\s+){{0,2}}{_GROUP_NOUN}")
_ALL_OF = re.compile(rf"(?i)\b(?:все[мх]?|всех|всем|all(?: of)?(?: the)?)\s+(?:\w+\s+){{0,2}}{_GROUP_NOUN}")
_TODAY = _rx(r"\bсегодня\b", r"\bвчера\b", r"\bпрямо сейчас\b", r"\bв эти (?:минуты|часы)\b", r"\btoday\b", r"\byesterday\b", r"\bright now\b")
_UNDERLYING_TIME = _rx(r"\bлет(?:ом|а)\b", r"\bвесной\b", r"\bзимой\b", r"\bосенью\b", r"\bэтим летом\b", r"\bin (?:the )?summer\b",
                       r"\bthis summer\b", r"\bранее\b", r"\bв (?:январ|феврал|март|апрел|ма[ея]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*")
_DISCLOSED = _rx(r"\bраскры\w*", r"\bстало известно\b", r"\bсообщил\w*", r"\bпризнал\w*", r"\bрассказал\w*", r"\bdisclos\w*",
                 r"\brevealed?\b", r"\bподробности\b", r"\b\d{1,2}\s+(?:сентябр|октябр|ноябр|декабр|январ|феврал|март|апрел|ма|июн|июл|август)\w*")

_STATUS_ORDER = ["FAILED_ATTEMPT", "DISPUTED", "UNDER_INVESTIGATION", "UNCONFIRMED", "ATTEMPTED", "CONFIRMED", "REPORTED"]
_ASSERTABLE = {"CONFIRMED", "REPORTED"}
_ALLOWED = {
    "CONFIRMED": "may be stated as confirmed",
    "REPORTED": "may be stated as the evidence states it - never as 'confirmed'",
    "UNDER_INVESTIGATION": "only with its investigation qualifier - never inside an unqualified list or count of reached targets",
    "ATTEMPTED": "only as an attempt - never as completed",
    "FAILED_ATTEMPT": "only as a failed attempt - never as a success",
    "UNCONFIRMED": "only hedged / attributed - never as a fact",
    "DISPUTED": "only with the dispute - never as a fact",
}
# which words in the SAME clause keep a qualified target qualified
_QUALIFIERS = {"UNDER_INVESTIGATION": (_INVESTIGATION, _UNCONFIRMED), "ATTEMPTED": (_ATTEMPT, _FAILED), "FAILED_ATTEMPT": (_FAILED,),
               "UNCONFIRMED": (_UNCONFIRMED, _INVESTIGATION, _DISPUTED), "DISPUTED": (_DISPUTED, _UNCONFIRMED)}


def _clauses(text: str) -> list[str]:
    """Sentences, then the contrastive / list joints inside them (', а ', '; ', ' — ', ', но ', ' but ', ' while ') - a qualifier governs its
    own clause, never a neighbour's."""
    out = []
    for sentence in re.split(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«\"“])", " ".join((text or "").split())):
        out += [c.strip() for c in re.split(r"\s*;\s*|\s+[—–]\s+|,\s+(?:а|но|однако|тогда как)\s+|\s+(?:but|while|whereas)\s+", sentence)
                if c.strip()]
    return out


@dataclass(frozen=True)
class TargetStatus:
    target: str
    claim_type: str  # access / attempt / interaction / mention
    status: str
    evidence_ids: tuple[str, ...]
    qualifier: str  # the evidence clause that sets the status (the most cautious one)
    allowed_assertion_strength: str


def _clause_status(clause: str) -> tuple[str | None, str]:
    for status, pattern in (("FAILED_ATTEMPT", _FAILED), ("DISPUTED", _DISPUTED), ("UNDER_INVESTIGATION", _INVESTIGATION),
                            ("UNCONFIRMED", _UNCONFIRMED), ("ATTEMPTED", _ATTEMPT), ("CONFIRMED", _CONFIRMED)):
        if pattern.search(clause):
            return status, "attempt" if status in ("ATTEMPTED", "FAILED_ATTEMPT") else "access" if _ACCESS.search(clause) else "mention"
    if _ACCESS.search(clause):
        return "REPORTED", "access"
    if _INTERACTION.search(clause):
        return "REPORTED", "interaction"
    return None, "mention"


def build_status_ledger(evidence: list[str]) -> list[TargetStatus]:
    """Per target: every status the evidence gives it, collapsed to the most cautious one. Constraint lines (SOURCE MEDIA / CHRONOLOGY /
    TARGET STATUS) are not evidence of a target's status."""
    seen: dict[str, list[tuple[str, str, str, str]]] = {}
    for index, line in enumerate(evidence, 1):
        if re.match(r"(?i)^\s*(source media|chronology|target status)\s*:", line or ""):
            continue
        for clause in _clauses(line):
            status, claim = _clause_status(clause)
            if status is None:
                continue
            for target in mentioned_targets(clause):
                seen.setdefault(target, []).append((status, claim, f"E{index}", clause))
    ledger = []
    for target, entries in seen.items():
        status = min((e[0] for e in entries), key=_STATUS_ORDER.index)
        chosen = next(e for e in entries if e[0] == status)
        claim = next((e[1] for e in entries if e[1] != "mention"), chosen[1])
        ledger.append(TargetStatus(target=target, claim_type=claim, status=status,
                                   evidence_ids=tuple(dict.fromkeys(e[2] for e in entries)), qualifier=chosen[3][:200],
                                   allowed_assertion_strength=_ALLOWED[status]))
    return sorted(ledger, key=lambda t: (_STATUS_ORDER.index(t.status), t.target))


def ledger_lines(ledger: list[TargetStatus]) -> list[str]:
    return [f"{t.target}: {t.status} ({', '.join(t.evidence_ids)}) - {t.allowed_assertion_strength}" for t in ledger]


def ledger_note(ledger: list[TargetStatus]) -> str:
    """The binding status contract for the Director (initial call and the correction)."""
    if not ledger:
        return ""
    return ("FACTUAL STATUS LEDGER (binding - derived from the evidence): " + "; ".join(ledger_lines(ledger)) + ". Keep every target's "
            "status exactly: never put a confirmed and a not-confirmed target into one claim, list or count ('доступ к трём ведомствам' when "
            "only two are confirmed is false), never call a reported / investigated / attempted item 'confirmed', never turn an attempt into "
            "a completed action, never use a stronger verb than the evidence (interaction or access is not 'взлом'). Short exact status wording "
            "('подтвердила доступ', 'расследование продолжается', names, dates) may stay as it is.")


# --- the gate ------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class StatusViolation:
    target: str
    where: str
    generated_claim: str
    evidence_status: str
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def render(self) -> str:
        ids = f" [{', '.join(self.evidence_ids)}]" if self.evidence_ids else ""
        return (f"target-status violation in {self.where}: '{self.generated_claim}' - {self.target} is {self.evidence_status}{ids}: "
                f"{self.reason}")


def _field_texts(slides: list[Any], caption: str) -> list[tuple[str, str]]:
    def get(slide: Any, name: str) -> str:
        return str((slide.get(name) if isinstance(slide, dict) else getattr(slide, name, None)) or "")

    out = []
    for i, slide in enumerate(slides, 1):
        out += [(f"slide {i} headline", get(slide, "slide_copy")), (f"slide {i} body", get(slide, "slide_body"))]
    out.append(("caption", caption or ""))
    return [(w, t) for w, t in out if t.strip()]


def _qualified(clause: str, status: str) -> bool:
    return any(p.search(clause) for p in _QUALIFIERS.get(status, ()))


def status_violations(slides: list[Any], caption: str, ledger: list[TargetStatus], evidence: list[str]) -> list[StatusViolation]:
    """Every generated clause against the ledger (and the evidence's own action / chronology words)."""
    by_target = {t.target: t for t in ledger}
    corpus = " ".join(e for e in evidence if not re.match(r"(?i)^\s*(chronology|target status)\s*:", e or ""))
    dated_earlier = any(re.match(r"(?i)^\s*chronology\s*:", e or "") for e in evidence)
    found: list[StatusViolation] = []
    for where, text in _field_texts(slides, caption):
        for clause in _clauses(text):
            targets = [by_target[k] for k in mentioned_targets(clause) if k in by_target]
            completes = bool(_ACCESS.search(clause)) and not _ATTEMPT.search(clause)
            asserts_confirmed = bool(_CONFIRMED.search(clause))
            for t in targets:
                if t.status in _QUALIFIERS and completes and not _qualified(clause, t.status):
                    others = [o.target for o in targets if o.status in _ASSERTABLE]
                    reason = (f"grouped with {', '.join(others)} in one unqualified claim of reaching them - "
                              if others else "stated as reached without its qualifier - ")
                    found.append(StatusViolation(t.target, where, clause, t.status, reason + t.allowed_assertion_strength, t.evidence_ids))
                elif asserts_confirmed and t.status != "CONFIRMED" and not _qualified(clause, t.status):
                    found.append(StatusViolation(t.target, where, clause, t.status, "promoted to 'confirmed' - " + t.allowed_assertion_strength,
                                                 t.evidence_ids))
                elif t.status == "ATTEMPTED" and completes:
                    found.append(StatusViolation(t.target, where, clause, t.status, "an attempt stated as completed", t.evidence_ids))
                elif t.status == "FAILED_ATTEMPT" and bool(_ACCESS.search(clause)) and not _FAILED.search(clause):
                    found.append(StatusViolation(t.target, where, clause, t.status, "a failed attempt stated as a success", t.evidence_ids))
            # a COUNT that hides a qualified target: 'доступ к трём ведомствам' when fewer are assertable
            count = _COUNT.search(clause)
            all_of = _ALL_OF.search(clause)
            if (count or all_of) and completes and ledger:
                assertable = [t for t in ledger if t.status in _ASSERTABLE]
                qualified = [t for t in ledger if t.status in _QUALIFIERS]
                raw = count.group(1).lower() if count else ""
                number = int(raw) if raw.isdigit() else _COUNT_WORDS.get(raw, 0)
                if qualified and ((count and number > len(assertable)) or all_of) and not any(_qualified(clause, q.status) for q in qualified):
                    names = ", ".join(q.target for q in qualified)
                    found.append(StatusViolation(names, where, clause, "/".join(sorted({q.status for q in qualified})),
                                                 f"the count includes {names} although only {len(assertable)} target(s) "
                                                 f"({', '.join(t.target for t in assertable) or 'none'}) may be stated as reached",
                                                 tuple(dict.fromkeys(i for q in qualified for i in q.evidence_ids))))
            if _INTRUSION.search(clause) and not _INTRUSION.search(corpus):
                found.append(StatusViolation("(action)", where, clause, "not in evidence",
                                             f"'{_INTRUSION.search(clause).group(0)}' is a stronger action than the evidence states "  # type: ignore[union-attr]
                                             "(no intrusion / attack / 'rogue' wording in the evidence)"))
            if dated_earlier and _TODAY.search(clause) and (_ACCESS.search(clause) or _INTERACTION.search(clause)):
                found.append(StatusViolation("(chronology)", where, clause, "earlier behaviour, new disclosure",
                                             f"'{_TODAY.search(clause).group(0)}' places the behaviour now - only the disclosure is new"))  # type: ignore[union-attr]
    return list({(v.target, v.where, v.generated_claim): v for v in found}.values())


# --- correction non-regression -------------------------------------------------------------------------------------------------------
def _strength(text: str) -> int:
    return 3 if _INTRUSION.search(text) else 2 if _ACCESS.search(text) else 1 if _INTERACTION.search(text) else 0


def factual_invariants(slides: list[Any], caption: str, ledger: list[TargetStatus], evidence: list[str]) -> dict:
    """What a version got right, to hold its correction to: the violations it already had (the correction may not add one), whether it
    kept the chronology (an underlying-time marker and a disclosure marker), and its strongest action verb."""
    texts = " ".join(t for _w, t in _field_texts(slides, caption))
    return {"violations": sorted({(v.target, v.evidence_status, v.reason.split(" - ")[0]) for v in status_violations(slides, caption, ledger, evidence)}),
            "underlying_time": bool(_UNDERLYING_TIME.search(texts)), "disclosure": bool(_DISCLOSED.search(texts)),
            "action_strength": _strength(texts), "ledger": ledger_lines(ledger)}


def non_regression_findings(baseline: dict, slides: list[Any], caption: str, ledger: list[TargetStatus], evidence: list[str]) -> list[str]:
    """The corrected version against the version that was sent to the correction: a NEW status violation, a lost chronology marker or a
    stronger action verb rejects the correction."""
    if not baseline:
        return []
    now = factual_invariants(slides, caption, ledger, evidence)
    before = {tuple(v) for v in baseline.get("violations", [])}
    problems = [f"correction introduced a target-status violation: {v[0]} ({v[1]}) - {v[2]}" for v in now["violations"] if tuple(v) not in before]
    if baseline.get("underlying_time") and not now["underlying_time"]:
        problems.append("correction removed the chronology: the earlier version said WHEN the behaviour happened, the correction does not")
    if baseline.get("disclosure") and not now["disclosure"]:
        problems.append("correction removed the chronology: the earlier version said the facts were disclosed now, the correction does not")
    if now["action_strength"] > int(baseline.get("action_strength", 0)):
        problems.append("correction strengthened the action verb beyond the earlier version (interaction < access < intrusion)")
    return problems


# --- thesis roles --------------------------------------------------------------------------------------------------------------------
DISTINCT_ROLES = frozenset({"TARGET_STATUS", "CHRONOLOGY", "COMPANY_RESPONSE"})
_COMPANY_RESPONSE = _rx(r"\bзаяви\w*", r"\bуведоми\w*", r"\bпредупреди\w*", r"\bсообщи\w*", r"\bответи\w*", r"\bизвини\w*", r"\bпообеща\w*",
                        r"\bsaid\b", r"\bnotified\b", r"\bwarned\b", r"\bresponded\b", r"\bapologi[sz]\w*", r"\bpromised\b")
_CONSEQUENCE = _rx(r"\bпосле этого\b", r"\bв результате\b", r"\bприостанови\w*", r"\bограничи\w*", r"\bpaused\b", r"\bas a result\b")


def slide_thesis_role(slide: Any, index: int) -> str:
    def get(name: str) -> str:
        return str((slide.get(name) if isinstance(slide, dict) else getattr(slide, name, None)) or "")

    head, body = get("slide_copy"), get("slide_body")
    text = f"{head} {body}"
    if index == 1:
        return "HOOK"
    if "?" in head:
        return "OPEN_QUESTION"
    has_target = bool(mentioned_targets(text))
    if has_target and any(p.search(text) for p in (_CONFIRMED, _INVESTIGATION, _UNCONFIRMED, _ATTEMPT, _FAILED, _DISPUTED)):
        return "TARGET_STATUS"
    if re.search(r"(?i)\bподтвержд\w*\s+не\s+вс\w*|\bне всё подтвержд", text):
        return "TARGET_STATUS"
    if _COMPANY_RESPONSE.search(text):
        return "COMPANY_RESPONSE"
    if _CONSEQUENCE.search(text):
        return "CONSEQUENCE"
    if _DISCLOSED.search(text) and _UNDERLYING_TIME.search(text) and not _ACCESS.search(text):
        return "CHRONOLOGY"
    if _ACCESS.search(text) or _INTERACTION.search(text):
        return "EVENT_ACTION"
    return "DETAIL"


def distinct_by_role(prev: Any, cur: Any, prev_index: int) -> bool:
    """A pair whose roles differ and one of them is a status / chronology / company-response role is two theses by construction
    ('what the agent did' vs 'which parts are confirmed'); same-role pairs are still judged on their content."""
    a, b = slide_thesis_role(prev, prev_index), slide_thesis_role(cur, prev_index + 1)
    return a != b and bool({a, b} & DISTINCT_ROLES)


# --- abstract questions --------------------------------------------------------------------------------------------------------------
_GOVERNANCE = _rx(r"\bкто должен\b", r"\bдолжен ли\b", r"\bдолжны ли\b", r"\bкто контролир\w*", r"\bкто отвеча\w*", r"\bгде заканчива\w*",
                  r"\bгде граница\b", r"\bв контуре\b", r"\bэтик\w*", r"\bwho should\b", r"\bshould (?:ai|we|agents)\b", r"\bwhere does .* end\b",
                  r"\bin the loop\b")


def abstract_question_findings(slides: list[Any], caption: str, evidence: list[str]) -> list[str]:
    """A generic ethics / governance question ('Кто должен подтверждать действие агента?', 'Где заканчивается автоматизация?') the
    evidence never raises - a viral slide ends on the story's own grounded point, not an invented debate."""
    corpus = " ".join(evidence)
    problems = []
    for where, text in _field_texts(slides, caption):
        for clause in _clauses(text):
            m = _GOVERNANCE.search(clause)
            if m and ("?" in clause or "?" in text) and not _GOVERNANCE.search(corpus):
                problems.append(f"{where}: abstract question the evidence never raises ('{clause}') - end on a grounded point (a confirmed fact, "
                                "the company's response, the open factual question) instead of an invented debate or poll")
    return list(dict.fromkeys(problems))


# --- factual terms the copied-wording rule must not force out -------------------------------------------------------------------------
_STATUS_TERMS = _rx(r"\bподтверди\w*", r"\bподтвержд\w*", r"\bрасследовани\w*", r"\bрасследу\w*", r"\bпродолжа\w*", r"\bнесанкционированн\w*",
                    r"\bпытал\w*", r"\bпопытк\w*", r"\bотрица\w*", r"\bуведоми\w*", r"\bconfirm\w*", r"\binvestigat\w*", r"\bunauthori[sz]ed\b",
                    r"\battempt\w*", r"\bтакже\b")
_DATE_OR_NUMBER = re.compile(r"(?i)\b\d[\d.,:]*\b|\b\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*")
_LATIN_NAME = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]+\b")


def factual_term_spans(text: str) -> list[tuple[int, int]]:
    """Spans of short status-critical wording: target names, status verbs / nouns, dates, numbers, Latin product / company names."""
    spans = target_spans(text)
    spans += [m.span() for p in (_STATUS_TERMS, _DATE_OR_NUMBER, _LATIN_NAME) for m in p.finditer(text or "")]
    return spans


def mask_factual_terms(text: str, placeholder: str = " ¦ ") -> str:
    """The text with factual terms replaced by a run-breaking placeholder (the copied-wording rule then only sees the prose around them)."""
    out, last = [], 0
    for start, end in sorted(factual_term_spans(text)):
        if start < last:
            last = max(last, end)
            continue
        out.append(text[last:start])
        out.append(placeholder)
        last = end
    out.append(text[last:])
    return "".join(out)


@dataclass
class FactualReview:
    ledger: list[TargetStatus] = field(default_factory=list)
    violations: list[StatusViolation] = field(default_factory=list)
    regression: list[str] = field(default_factory=list)

    @property
    def hard_findings(self) -> list[str]:
        return [v.render() for v in self.violations] + self.regression
