"""Zero-cost fail-closed handoff checks for the opt-in KAGE product loop.

These checks do not rewrite copy or turn a missing fact into an absence claim. They
only stop an unsupported/point-losing draft before it can be treated as publishable.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_PRACTICAL_ACTION = re.compile(
    r"автоматическ|позволя|может|умеет|определя|подбира|выбира|созда|генерир|"
    r"выполня|анализир|редактир|управля|автоматизир", re.IGNORECASE,
)
_CAPABILITY_OBJECTS = (
    "устрой", "файл", "прилож", "модел", "задач", "код", "изображ", "видео",
    "документ", "браузер", "сайт", "письм", "сообщен", "календар", "таблиц",
)
_ABSENCE = re.compile(
    r"\b(?:нет|не было|не указа\w*|не назв\w*|не подтвержд\w*|не объявл\w*|"
    r"не доступ\w*|отсутств\w*|не существует|не привел\w*|не предостав\w*|"
    r"не раскрыва\w*|не сообща\w*|не публикова\w*)\b",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b(?:через|спустя)\s+(?:\d+|несколько|пару)\s+(?:час\w*|дн\w*|недел\w*)\b", re.IGNORECASE)
_NAMED = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)+\b")
_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_STOP = frozenset({"нет", "не", "пока", "это", "для", "что", "как", "при", "или", "его", "еще", "уже", "будет"})


def _stems(text: str) -> set[str]:
    return {word[:5] for word in _WORD.findall(text.casefold()) if len(word) >= 5 and word not in _STOP}


def practical_capability_fact(research: Mapping[str, Any], lane: str) -> str | None:
    """Find a concrete multi-object AI action, not a mere availability statement."""
    if lane != "PRACTICAL_AI":
        return None
    facts = research.get("facts") or []
    candidates: list[tuple[int, str]] = []
    for fact in facts:
        if not isinstance(fact, str) or not _PRACTICAL_ACTION.search(fact):
            continue
        objects = [stem for stem in _CAPABILITY_OBJECTS if stem in fact.casefold()]
        if len(objects) >= 3:
            candidates.append((len(objects) + (2 if "задач" in fact.casefold() else 0), fact))
    return max(candidates, default=(0, None))[1]


def _missing_capability_objects(fact: str, text: str) -> bool:
    objects = [stem for stem in _CAPABILITY_OBJECTS if stem in fact.casefold()]
    present = sum(stem in text.casefold() for stem in objects)
    return present < max(2, (len(objects) * 3 + 3) // 4)


def pre_copy_issues(
    research: Mapping[str, Any], intelligence: Mapping[str, Any], *, lane: str,
) -> list[str]:
    issues: list[str] = []
    recommendation = str(intelligence.get("recommendation") or "").strip().upper()
    if not recommendation.startswith("PUBLISH"):
        issues.append("intelligence_did_not_recommend_publication")
    capability = practical_capability_fact(research, lane)
    if capability and _missing_capability_objects(capability, str(intelligence.get("angle") or "")):
        issues.append("practical_capability_missing_from_intelligence_angle")
    return issues


def _absence_clauses(text: str) -> list[str]:
    return [clause.strip() for clause in re.split(r"[.!?;\n]", text) if _ABSENCE.search(clause)]


def _supported_absence(clause: str, facts: list[str]) -> bool:
    subject = _stems(_ABSENCE.sub(" ", clause))
    return any(
        _ABSENCE.search(fact) and len(subject & _stems(_ABSENCE.sub(" ", fact))) >= 2
        for fact in facts
    )


def unsupported_absence_clauses(research: Mapping[str, Any], text: str) -> list[str]:
    """Return negative claims not explicitly established by Research FACTS (never GAPS)."""
    facts = [fact for fact in research.get("facts", []) if isinstance(fact, str)]
    return [clause for clause in _absence_clauses(text) if not _supported_absence(clause, facts)]


def draft_issues(
    research: Mapping[str, Any], intelligence: Mapping[str, Any], copy: Mapping[str, Any], *, lane: str,
) -> list[str]:
    """Reject unsupported absence and cross-surface timing before final Quality.

    This is deliberately conservative: explicit negative Research FACTS may support an
    absence; Research GAPS never do. Quality still owns broader semantic judgment.
    """
    issues = pre_copy_issues(research, intelligence, lane=lane)
    facts = [fact for fact in research.get("facts", []) if isinstance(fact, str)]
    draft = "\n".join(str(copy.get(key) or "") for key in ("title", "main_body", "ending"))
    if unsupported_absence_clauses(research, draft):
        issues.append("absence_claim_without_explicit_research_fact")
    capability = practical_capability_fact(research, lane)
    if capability and _missing_capability_objects(capability, draft):
        issues.append("practical_capability_missing_from_finished_copy")
    for sentence in re.split(r"[.!?\n]", draft):
        if not _TIME.search(sentence):
            continue
        named = {name.casefold() for name in _NAMED.findall(sentence)}
        if named and not all(
            any(name in fact.casefold() and _TIME.search(fact) for fact in facts)
            for name in named
        ):
            issues.append("timed_effect_extended_to_unverified_surface")
    return sorted(set(issues))
