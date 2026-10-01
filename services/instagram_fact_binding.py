"""FACT BINDING - a supported phrase is not enough when the relation between its parts changes (founder task 2026-10-01).

The controlled Sonnet 5.5 acceptance (3f213cb) passed every check with two factual errors: the evidence's 'replacing Sonnet 5 from June with
Sonnet 5.5' (June is WHEN THE OLD MODEL CAME) became 'с июня Sonnet 5.5 заменит Sonnet 5' (June became WHEN THE NEW ONE ARRIVES), and
'cybersecurity capabilities comparable to Opus 5' became 'защита ..., сопоставимая с Opus 5' (the comparison moved from the capabilities to
the safeguards). Each word was supported; the RELATION was not.

Deterministic, conservative and general - no product, company, month or topic is named in a rule. The copy is Russian, the evidence is
usually English, so relations are compared through what survives translation: Latin-script names with their versions, month names, numbers,
and a small bilingual vocabulary of PRODUCT PROPERTIES. A relation is checked only when both sides are recognised; anything else is silent:
  - DATE -> OWNER: a month the evidence only ever attaches to a named thing ('X from June', 'June's X', 'X, вышедшая в июне') must stay
    attached to that thing in the copy - never become the time of the event, never move to another name;
  - COMPARISON -> PROPERTY: a comparison with a named thing ('comparable to X', 'on par with X', 'на уровне X') must compare the same
    property the evidence compares (capabilities are not safeguards);
  - RELATIVE QUANTITY -> METRIC: a percentage or multiplier must describe the metric the evidence gives it (30% faster is not 30% fewer
    tokens).
Each finding is correctable wording (the one editorial correction receives it); after that one correction it stops the post, like every
other copy finding.
"""
from __future__ import annotations

import re
from typing import Any

# --- vocabulary ------------------------------------------------------------------------------------------------------------------------

_MONTHS = (  # (English, Russian stem) - the Russian stem matches every case and the adjective ('июньская')
    ("january", "январ"), ("february", "феврал"), ("march", "март"), ("april", "апрел"), ("may", "ма[йяюе]"), ("june", "июн"),
    ("july", "июл"), ("august", "август"), ("september", "сентябр"), ("october", "октябр"), ("november", "ноябр"),
    ("december", "декабр"),
)
# a named thing: a Latin-script name, optionally more capitalised words, optionally a version number ('Sonnet 5', 'Galaxy S25 Ultra')
_NAME = r"[A-Z][A-Za-z0-9+\-]*(?:\s+[A-Z][A-Za-z0-9+\-]*)*(?:\s+\d+(?:\.\d+)?)?"
# a property of a product, as a reader names it - bilingual stems; a word can belong to one property only
_PROPERTIES = {
    "CAPABILITY": r"capabilit|abilit|skill|способност|возможност|умени|навык",
    "SAFEGUARD": r"safeguard|protection|protect|fallback|guardrail|защит|резервн|мер[аыу]? безопасн|предохранител",
    "SPEED": r"faster|fastest|speed|slower|latency|быстр|скорост|медленн|задержк",
    "PRICE": r"cheaper|cheap|cost|price|pricing|expensive|дешев|дешёв|дорож|дорог|цен[аеуы]|стоим",
    "TOKENS": r"token|токен",
    "BATTERY": r"battery|mah|аккумулятор|батаре|автономн",
    "CAMERA": r"camera|камер",
    "DISPLAY": r"display|screen|дисплей|экран",
    "PERFORMANCE": r"performance|benchmark|производительн",
    "MEMORY": r"\bram\b|memory|storage|памят|накопител",
}
_COMPARE_EN = r"(?:comparable|similar|equal|equivalent|close|identical)\s+(?:to|with)|on par with|matching|as good as"
_COMPARE_RU = (r"(?:сопоставим\w*|сравним\w*|аналогичн\w*|похож\w*|равн\w*|идентичн\w*)\s+(?:с|со)|на уровне|как у|не хуже|"
               r"наравне с")
_RELATIVE = re.compile(r"(\d+(?:[.,]\d+)?)\s?(?:%|процент\w*|x\b|×|раз[а]?\b|times\b)", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"\s*(?:[,;:—–]|\band\b|\bи\b|\bа\b|\bно\b|\bbut\b)\s*", re.IGNORECASE)


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


def _properties(text: str) -> set[str]:
    low = (text or "").lower()
    return {prop for prop, pattern in _PROPERTIES.items() if re.search(pattern, low)}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text or "") if s.strip()]


# --- DATE -> OWNER ----------------------------------------------------------------------------------------------------------------------

def _evidence_month_owners(evidence: list[str], english: str) -> tuple[set[str], bool]:
    """(the names the evidence attaches this month to, whether it ALSO uses the month as the time of an event)."""
    owners: set[str] = set()
    free = False
    month = rf"\b{english}\b"
    for line in evidence:
        for m in re.finditer(month, line, re.IGNORECASE):
            before, after = line[: m.start()], line[m.end():]
            bound = re.search(rf"({_NAME})\s+(?:from|of|since|released in|launched in|introduced in|announced in|out in)\s+$", before)
            possessive = re.match(rf"\s*['’]s\s+({_NAME})", after)
            if bound:
                owners.add(_norm_name(bound.group(1)))
            elif possessive:
                owners.add(_norm_name(possessive.group(1)))
            else:
                free = True
    return owners, free


def _month_words(stem: str) -> re.Pattern[str]:
    """A WHOLE Russian month word - its noun cases ('июнь', 'июня', 'июне') or its adjective ('июньская', 'мартовскую'); never a stem
    inside another word ('смартфон', 'маяк')."""
    return re.compile(rf"(?<![а-яё])(?:{stem})(?:ь|я|е|ю|ем|ём|а|у|ом)?(?P<adjective>(?:ов|ь)?ск\w*)?(?![а-яё])", re.IGNORECASE)


def _copy_month_owner(sentence: str, start: int, end: int, *, adjective: bool) -> str | None:
    """The name the copy attaches this month mention to, or None when it is the time of the sentence's event."""
    before, after = sentence[:start], sentence[end:]
    if adjective:  # an adjective of the month ('июньская X', 'мартовская X'): it describes the name that follows
        following = re.match(rf"\s*({_NAME})", after)
        return _norm_name(following.group(1)) if following else None
    bound = re.search(rf"({_NAME})\s*,?\s*(?:вышедш\w*|выпущенн\w*|представленн\w*|появивш\w*|запущенн\w*|релиза|из|от)?\s*(?:в|с|из|от)?\s*$",
                      before)
    if bound and re.search(r"(?:вышедш|выпущенн|представленн|появивш|запущенн|релиза|\bиз\b|\bот\b)", before[bound.start(1):]):
        return _norm_name(bound.group(1))
    en = re.search(rf"({_NAME})\s+(?:from|of|since|released in|launched in|introduced in)\s+$", before)
    return _norm_name(en.group(1)) if en else None


def date_binding_findings(texts: list[tuple[str, str]], evidence: list[str]) -> list[str]:
    problems = []
    for english, stem in _MONTHS:
        owners, free = _evidence_month_owners(evidence, english)
        if not owners or free:
            continue  # the evidence never ties this month to a named thing only - nothing to keep attached
        for where, text in texts:
            for sentence in _sentences(text):
                for m in _month_words(stem).finditer(sentence):
                    owner = _copy_month_owner(sentence, m.start(), m.end(), adjective=bool(m.group("adjective")))
                    if owner in owners:
                        continue
                    whose = ", ".join(sorted(owners))
                    problems.append(
                        f"fact binding ({where}): the month in {sentence!r} belongs to {whose} in the evidence (the date describes that "
                        f"product, not the event) - the copy turns it into "
                        + (f"a date of {owner}" if owner else "the time of the event")
                        + "; keep the date attached to what it describes, or drop it")
                    break
    return list(dict.fromkeys(problems))


# --- COMPARISON -> PROPERTY ---------------------------------------------------------------------------------------------------------------

def _evidence_comparisons(evidence: list[str]) -> dict[str, set[str]]:
    """name -> the properties the evidence compares with it."""
    out: dict[str, set[str]] = {}
    for line in evidence:
        for sentence in _sentences(line):
            for m in re.finditer(rf"({_COMPARE_EN})\s+({_NAME})", sentence, re.IGNORECASE):
                before = sentence[: m.start()]
                clause = re.split(r"[,;:]|\bwhich\b|\bthat\b", before)[-1]
                props = _properties(" ".join(clause.split()[-6:]))
                if props:
                    out.setdefault(_norm_name(m.group(2)), set()).update(props)
    return out


def comparison_binding_findings(texts: list[tuple[str, str]], evidence: list[str]) -> list[str]:
    compared = _evidence_comparisons(evidence)
    problems = []
    for where, text in texts:
        for sentence in _sentences(text):
            for m in re.finditer(rf"({_COMPARE_RU}|{_COMPARE_EN})\s+({_NAME})", sentence, re.IGNORECASE):
                name = _norm_name(m.group(2))
                if name not in compared:
                    continue
                clause = re.split(r"[;:—–]|\.", sentence[: m.start()])[-1]
                props = _properties(" ".join(clause.split()[-6:]))
                wrong = props - compared[name]
                if props and wrong:
                    problems.append(
                        f"fact binding ({where}): {sentence!r} compares {', '.join(sorted(p.lower() for p in wrong))} with {m.group(2)}, but "
                        f"the evidence compares {', '.join(sorted(p.lower() for p in compared[name]))} with it - keep the comparison on the "
                        "property the evidence names")
    return list(dict.fromkeys(problems))


# --- RELATIVE QUANTITY -> METRIC --------------------------------------------------------------------------------------------------------

def _quantity_metrics(text: str) -> dict[str, set[str]]:
    """value -> the metrics its own clause names ('more than 30% faster' -> {'30': {SPEED}})."""
    out: dict[str, set[str]] = {}
    for sentence in _sentences(text):
        for clause in _CLAUSE_SPLIT.split(sentence):
            props = _properties(clause)
            for m in _RELATIVE.finditer(clause):
                if props:
                    out.setdefault(m.group(1).replace(",", "."), set()).update(props)
    return out


def quantity_binding_findings(texts: list[tuple[str, str]], evidence: list[str]) -> list[str]:
    supported: dict[str, set[str]] = {}
    for line in evidence:
        for value, props in _quantity_metrics(line).items():
            supported.setdefault(value, set()).update(props)
    problems = []
    for where, text in texts:
        for value, props in _quantity_metrics(text).items():
            if value in supported and props - supported[value]:
                problems.append(
                    f"fact binding ({where}): {value} is given to {', '.join(sorted(p.lower() for p in props - supported[value]))}, but the "
                    f"evidence gives {value} to {', '.join(sorted(p.lower() for p in supported[value]))} - keep each number on its own metric")
    return list(dict.fromkeys(problems))


def fact_binding_findings(slides: list[Any], evidence: list[str], *, caption: str = "") -> list[str]:
    def get(slide: Any, name: str) -> str:
        return str((slide.get(name) if isinstance(slide, dict) else getattr(slide, name, None)) or "")

    texts = [*((f"slide {i} headline", get(s, "slide_copy")) for i, s in enumerate(slides, 1)),
             *((f"slide {i} body", get(s, "slide_body")) for i, s in enumerate(slides, 1)), ("caption", caption or "")]
    texts = [(where, text) for where, text in texts if text]
    return [*date_binding_findings(texts, evidence), *comparison_binding_findings(texts, evidence),
            *quantity_binding_findings(texts, evidence)]
