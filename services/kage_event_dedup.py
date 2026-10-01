"""Conservative, zero-cost same-change collapse within a bounded editorial shortlist.

An organization or device name alone is never enough: both accounts must name the
same multi-word feature/product and describe overlapping change details. This is a
selection-time complement to Story Memory's cross-cycle delivery protection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


_NAMED_PHRASE = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:[ -][A-Z][A-Za-z0-9]+){1,3}\b")
_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_STOP = frozenset({
    "about", "after", "again", "allows", "could", "feature", "from", "have",
    "inside", "launch", "more", "new", "now", "people", "that", "their",
    "there", "this", "today", "users", "what", "when", "where", "which",
    "will", "with", "your", "the", "and", "for", "its", "you", "are",
    "можно", "новая", "новый", "после", "пользователей", "теперь", "чтобы",
})
_SINGLE_PRODUCT_ANCHORS = frozenset({
    "copilot", "chatgpt", "gemini", "claude", "grapheneos", "warzone",
})
_DETAIL_ALIASES = {
    "code": "coding", "codes": "coding", "coding": "coding", "programming": "coding",
    "agent": "agents", "agents": "agents", "automation": "agents",
    "automations": "agents", "autopilot": "agents",
    "apps": "app", "application": "app", "applications": "app",
    "bundles": "bundle", "bundling": "bundle", "combined": "bundle", "combines": "bundle",
}
_GENERIC_DETAILS = frozenset({"app", "new", "update", "launch", "model", "feature", "users"})
_GENERIC_TITLE_CHANGE = frozenset({
    "adds", "adding", "announces", "announced", "finally", "gets", "gives",
    "launches", "launched", "makes", "new", "releases", "released", "rolls",
    "rolling", "unveils", "widely", "google", "meta", "microsoft", "apple",
})
_NON_ENTITY_ACRONYMS = frozenset({"AI", "US", "EU", "API", "CEO", "LLM", "LLMS", "URL"})
_SECURITY_VERBS = re.compile(r"\b(?:hack(?:ed|ers|ing)?|breach(?:ed)?|stolen|exposed)\b", re.IGNORECASE)
_INCIDENT_IMPACTS = {
    "people": re.compile(r"\b(?:employees?|agents?|members?|staff|personnel|workers?)\b", re.IGNORECASE),
    "exposure": re.compile(r"\b(?:exposed|stolen|leaked|data|records?|results?|files?)\b", re.IGNORECASE),
    "systems": re.compile(r"\b(?:servers?|outage|infrastructure|websites?|services?|systems?)\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class EventDuplicate:
    duplicate_order: int
    primary_order: int
    shared_feature: str


def _feature_names(title: str, lead: str) -> set[str]:
    return {" ".join(match.group().casefold().split()) for match in _NAMED_PHRASE.finditer(f"{title} {lead[:600]}")}


def _detail_words(title: str, lead: str, feature: str) -> set[str]:
    text = f"{title} {lead[:600]}".casefold().replace(feature, " ")
    return {word for word in _WORD.findall(text) if len(word) >= 4 and word not in _STOP}


def _title_change_words(title: str, feature: str) -> set[str]:
    """Words naming the headline's change, excluding the shared product/topic."""
    return {
        _DETAIL_ALIASES.get(word, word)
        for word in _detail_words(title, "", feature)
        if word not in _GENERIC_TITLE_CHANGE
    } - _GENERIC_DETAILS


def _single_product_change(a: Mapping[str, object], b: Mapping[str, object]) -> str | None:
    """Catch the same multi-feature product release without merging by company/topic.

    A shared product name alone is insufficient. Two non-generic change details,
    with narrow aliases such as automation/agents, must also be shared.
    """
    title_a, title_b = str(a.get("title") or "").casefold(), str(b.get("title") or "").casefold()
    anchors = (_SINGLE_PRODUCT_ANCHORS & set(_WORD.findall(title_a)) & set(_WORD.findall(title_b)))
    if not anchors:
        return None
    for anchor in sorted(anchors):
        if not (_title_change_words(str(a.get("title") or ""), anchor)
                & _title_change_words(str(b.get("title") or ""), anchor)):
            continue
        details = []
        for row in (a, b):
            words = _detail_words(str(row.get("title") or ""), str(row.get("lead") or ""), anchor)
            details.append({_DETAIL_ALIASES.get(word, word) for word in words} - _GENERIC_DETAILS)
        if len(details[0] & details[1]) >= 2:
            return anchor
    return None


def _same_prompt_game_creation(a: Mapping[str, object], b: Mapping[str, object]) -> str | None:
    """Recognize two accounts of one prompt-based game-tool launch, not just gaming topics.

    This requires a shared maker plus the same concrete creation mechanism and
    mobile/browser surface in *both* accounts. A VR-glasses side announcement in
    one account does not make its overlapping game-tools launch a second event.
    """
    titles = [str(row.get("title") or "") for row in (a, b)]
    makers = [re.match(r"^([A-Z][A-Za-z0-9]+)\b", title) for title in titles]
    if not all(makers) or makers[0].group(1).casefold() != makers[1].group(1).casefold():
        return None
    for row in (a, b):
        title = str(row.get("title") or "").casefold()
        text = f'{title} {row.get("lead") or ""}'.casefold()
        if not (
            re.search(r"\bgames?\b", title)
            and re.search(r"\bai\b", text)
            and re.search(r"\b(?:prompts?|prompt-based)\b", text)
            and re.search(r"\b(?:build|create|develop|make)\b", text)
            and re.search(r"\b(?:mobile|phone|browser|browsers)\b", text)
        ):
            return None
    return "prompt-based game creation"


def _same_security_incident(a: Mapping[str, object], b: Mapping[str, object]) -> str | None:
    """Collapse same-organization breach coverage only with matching harm, not topic alone."""
    title_a, title_b = str(a.get("title") or ""), str(b.get("title") or "")
    if not (_SECURITY_VERBS.search(title_a) and _SECURITY_VERBS.search(title_b)):
        return None
    entities_a = {word for word in re.findall(r"\b[A-Z]{2,6}\b", title_a) if word not in _NON_ENTITY_ACRONYMS}
    entities_b = {word for word in re.findall(r"\b[A-Z]{2,6}\b", title_b) if word not in _NON_ENTITY_ACRONYMS}
    common = entities_a & entities_b
    if not common:
        return None
    impacts = []
    for row in (a, b):
        text = f'{row.get("title") or ""} {row.get("lead") or ""}'
        impacts.append({name for name, pattern in _INCIDENT_IMPACTS.items() if pattern.search(text)})
    if {"people", "exposure"}.issubset(impacts[0] & impacts[1]):
        return f"{sorted(common)[0].lower()} personnel-data breach"
    return None


def same_underlying_change(a: Mapping[str, object], b: Mapping[str, object]) -> str | None:
    """Return the shared named feature only with independent change-detail overlap.

    Different stories about the same company or device stay separate. Different URLs
    and outlets are not treated as evidence of different underlying events.
    """
    title_a, lead_a = str(a.get("title") or ""), str(a.get("lead") or "")
    title_b, lead_b = str(b.get("title") or ""), str(b.get("lead") or "")
    for feature in sorted(_feature_names(title_a, lead_a) & _feature_names(title_b, lead_b), key=len, reverse=True):
        if not (_title_change_words(title_a, feature) & _title_change_words(title_b, feature)):
            continue
        words_a = _detail_words(title_a, lead_a, feature)
        words_b = _detail_words(title_b, lead_b, feature)
        common = words_a & words_b
        if len(common) >= 2 and len(common) / max(1, min(len(words_a), len(words_b))) >= 0.20:
            return feature
    return _single_product_change(a, b) or _same_prompt_game_creation(a, b) or _same_security_incident(a, b)


def collapse_ranked_events(rows: Sequence[Mapping[str, object]]) -> tuple[list[Mapping[str, object]], list[EventDuplicate]]:
    """Keep the first (highest-ranked) account; audit every suppressed account."""
    kept: list[Mapping[str, object]] = []
    merged: list[EventDuplicate] = []
    for row in rows:
        duplicate = next(
            ((prior, feature) for prior in kept if (feature := same_underlying_change(row, prior))),
            None,
        )
        if duplicate is None:
            kept.append(row)
            continue
        primary, feature = duplicate
        merged.append(EventDuplicate(
            duplicate_order=int(row["order"]), primary_order=int(primary["order"]),
            shared_feature=feature,
        ))
    return kept, merged
