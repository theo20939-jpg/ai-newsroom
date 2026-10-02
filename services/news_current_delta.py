"""Deterministic current-delta gate for daily NEWS candidates and rendered copy.

Article publication time is a transport/source timestamp, not proof that the underlying event is
new.  This module distinguishes a genuinely current event from an old event that is merely being
acknowledged or republished, while preserving old-event stories that contain a material new
development.  It is deliberately provider-free and evidence-conservative: only wording present
in the supplied title/body/context can satisfy the material-delta rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

FRESH_CURRENT_EVENT = "FRESH_CURRENT_EVENT"
OLD_EVENT_MATERIAL_NEW_DEVELOPMENT = "OLD_EVENT_MATERIAL_NEW_DEVELOPMENT"
OLD_EVENT_WEAK_DISCLOSURE = "OLD_EVENT_WEAK_DISCLOSURE"
OLD_EVENT_NO_MATERIAL_DELTA = "OLD_EVENT_NO_MATERIAL_DELTA"


@dataclass(frozen=True)
class CurrentDeltaDecision:
    classification: str
    eligible: bool
    underlying_old_event: bool
    weak_disclosure: bool
    material_current_delta: bool
    headline_foregrounds_delta: bool
    body_explains_delta: bool
    reason: str


_EVENT = re.compile(
    r"\b(?:attack|attacked|hack|hacked|breach|breached|incident|intrusion|compromise|"
    r"leak|outage|failure|exploit(?:ed|ation)?|vulnerability|lawsuit|investigation|"
    r"launch(?:ed)?|release(?:d)?|occurred|happened|"
    r"атак\w*|взлом\w*|инцидент\w*|утечк\w*|сбо[йя]\w*|уязвим\w*|эксплойт\w*|"
    r"произош\w*|случил\w*|запуст\w*|выпуст\w*)\b",
    re.I,
)

_AGE = re.compile(
    r"\b(?:days? ago|weeks? ago|months? ago|years? ago|last year|earlier this year|previously|back in|"
    r"дн(?:я|ей)? назад|недел(?:ю|и|ь) назад|несколько месяцев назад|месяц(?:а|ев)? назад|"
    r"год(?:а|ов)? назад|в прошлом году|ранее)\b",
    re.I,
)

_MONTHS: dict[str, int] = {
    "january": 1, "jan": 1, "январ": 1,
    "february": 2, "feb": 2, "феврал": 2,
    "march": 3, "mar": 3, "март": 3,
    "april": 4, "apr": 4, "апрел": 4,
    "may": 5, "мае": 5, "май": 5,
    "june": 6, "jun": 6, "июн": 6,
    "july": 7, "jul": 7, "июл": 7,
    "august": 8, "aug": 8, "август": 8,
    "september": 9, "sep": 9, "sept": 9, "сентябр": 9,
    "october": 10, "oct": 10, "октябр": 10,
    "november": 11, "nov": 11, "ноябр": 11,
    "december": 12, "dec": 12, "декабр": 12,
}

_BODY_SCAN_CHARS = 2_000

_WEAK_DISCLOSURE = re.compile(
    r"\b(?:learned|learns|became aware|was informed|acknowledged|acknowledges|"
    r"only now (?:said|says|reported|reports)|republication|republished|retold|"
    r"узнал\w*|стало известно|признал\w*|подтвердил\w*|лишь сейчас сообщил\w*|"
    r"повторно опубликовал\w*|пересказал\w*)\b",
    re.I,
)

_MATERIAL_STANDALONE = re.compile(
    r"\b(?:actively exploited|active exploitation|ongoing attack|current incident|"
    r"identified (?:the )?attacker|attributed (?:the )?(?:attack|breach)|"
    r"charged|indicted|arrested|fine[sd]?|lawsuit filed|regulator(?:y)? order|"
    r"investigative subpoena|issued (?:an? )?subpoena|patched|fixed|remediated|"
    r"revoked (?:the )?(?:keys?|tokens?|access)|forced password reset|"
    r"активно эксплуатир\w*|текущ\w+ атак\w*|установил\w+ атакующ\w*|"
    r"атрибутировал\w*|предъявил\w+ обвинен\w*|арестовал\w*|оштрафовал\w*|"
    r"подал\w+ иск|выдал\w+ повестк\w*|исправил\w*|выпустил\w+ патч|"
    r"отозвал\w+ ключ\w*|сбросил\w+ парол\w*)\b",
    re.I,
)

_REVEAL = re.compile(
    r"\b(?:newly|new |now |today|this week|revealed|reveals|disclosed|discloses|"
    r"identif(?:y|ies|ied)|confirmed|confirms|found|finds|investigation (?:found|revealed|shows)|"
    r"report (?:found|reveals|shows)|"
    r"нов\w*|сегодня|на этой неделе|раскрыл\w*|выявил\w*|установил\w*|"
    r"подтвердил\w*|расследован\w+ показал\w*|отчет\w+ показал\w*)\b",
    re.I,
)

_SUBSTANTIVE = re.compile(
    r"\b(?:\d[\d,.]*\s*(?:million|billion|thousand|млн|млрд|тыс)|"
    r"records?|users?|customers?|organizations?|systems?|servers?|accounts?|victims?|"
    r"stolen|exfiltrat\w*|compromised|encrypted|deleted|damage|loss(?:es)?|"
    r"sql injection|remote code execution|rce|authentication bypass|privilege escalation|"
    r"cve-\d{4}-\d+|zero-day|malware|ransomware|backdoor|initial access|"
    r"apt\d+|state-sponsored|threat actor|attacker identity|"
    r"запис\w*|пользовател\w*|клиент\w*|организац\w*|систем\w*|сервер\w*|"
    r"аккаунт\w*|жертв\w*|украл\w*|похитил\w*|скомпрометир\w*|зашифровал\w*|"
    r"ущерб\w*|потер\w*|sql-инъекц\w*|удален\w+ выполнен\w+ код\w*|"
    r"обход\w+ аутентификац\w*|повышен\w+ привилег\w*|cve-\d{4}-\d+|"
    r"zero-day|вредонос\w+ по|вымогател\w*|бэкдор\w*|apt\d+|госхакер\w*)\b",
    re.I,
)


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("ё", "е")).strip().lower()


def _mentions_prior_month(text: str, now: datetime) -> bool:
    for stem, month in _MONTHS.items():
        if month == now.month:
            continue
        if re.search(rf"\b(?:in|during|since|в|с)\s+{re.escape(stem)}\w*\b", text, re.I):
            return True
        adjacent_event = rf"\b{re.escape(stem)}\w*\s+(?:attack|breach|incident|hack|атак\w*|взлом\w*|инцидент\w*)\b"
        if re.search(adjacent_event, text, re.I):
            return True
        if len(stem) >= 4 and stem != "may" and re.search(rf"\b{re.escape(stem)}\w*\b", text, re.I):
            return True
    return False


def _has_old_event(text: str, now: datetime) -> bool:
    if _EVENT.search(text) is None:
        return False
    prior_year = any(int(year) < now.year for year in re.findall(r"\b(20\d{2})\b", text))
    return _AGE.search(text) is not None or _mentions_prior_month(text, now) or prior_year


def _has_material_delta(text: str) -> bool:
    if _MATERIAL_STANDALONE.search(text):
        return True
    reveal = _REVEAL.search(text)
    substantive = _SUBSTANTIVE.search(text)
    return bool(reveal and substantive and abs(reveal.start() - substantive.start()) <= 240)


def evaluate_current_delta(
    *,
    title: str,
    content: str | None = None,
    old_event_context: str | None = None,
    now: datetime | None = None,
    require_headline_delta: bool = False,
    require_body_delta: bool = False,
) -> CurrentDeltaDecision:
    """Classify whether a candidate has a meaningful reason to be daily NEWS now.

    ``old_event_context`` participates only in deciding whether the underlying event is old; it
    cannot manufacture a material delta for the rendered title/body.  This lets the pre-send gate
    use evidence cards to detect stale framing while still requiring the reader-visible copy to
    foreground and explain the real new development.
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    normalized_title = _normalize(title)
    normalized_body = _normalize(content)[:_BODY_SCAN_CHARS]
    normalized_context = _normalize(old_event_context)
    combined = " ".join(part for part in (normalized_title, normalized_body, normalized_context) if part)

    old_event = _has_old_event(combined, current)
    weak_disclosure = _WEAK_DISCLOSURE.search(combined) is not None
    headline_material = _has_material_delta(normalized_title)
    body_material = _has_material_delta(normalized_body)
    material = _has_material_delta(" ".join((normalized_title, normalized_body)).strip())

    if not old_event:
        return CurrentDeltaDecision(
            classification=FRESH_CURRENT_EVENT, eligible=True,
            underlying_old_event=False, weak_disclosure=weak_disclosure,
            material_current_delta=material, headline_foregrounds_delta=headline_material,
            body_explains_delta=body_material, reason="no_old_underlying_event_detected",
        )

    if not material:
        classification = OLD_EVENT_WEAK_DISCLOSURE if weak_disclosure else OLD_EVENT_NO_MATERIAL_DELTA
        reason = (
            "old_event_weak_disclosure_no_material_current_delta"
            if weak_disclosure else "old_event_no_material_current_delta"
        )
        return CurrentDeltaDecision(
            classification=classification, eligible=False,
            underlying_old_event=True, weak_disclosure=weak_disclosure,
            material_current_delta=False, headline_foregrounds_delta=False,
            body_explains_delta=False, reason=reason,
        )

    if require_headline_delta and not headline_material:
        return CurrentDeltaDecision(
            classification=OLD_EVENT_MATERIAL_NEW_DEVELOPMENT, eligible=False,
            underlying_old_event=True, weak_disclosure=weak_disclosure,
            material_current_delta=True, headline_foregrounds_delta=False,
            body_explains_delta=body_material,
            reason="material_current_delta_not_foregrounded_in_headline",
        )
    if require_body_delta and not body_material:
        return CurrentDeltaDecision(
            classification=OLD_EVENT_MATERIAL_NEW_DEVELOPMENT, eligible=False,
            underlying_old_event=True, weak_disclosure=weak_disclosure,
            material_current_delta=True, headline_foregrounds_delta=headline_material,
            body_explains_delta=False,
            reason="body_does_not_explain_material_current_delta",
        )
    return CurrentDeltaDecision(
        classification=OLD_EVENT_MATERIAL_NEW_DEVELOPMENT, eligible=True,
        underlying_old_event=True, weak_disclosure=weak_disclosure,
        material_current_delta=True, headline_foregrounds_delta=headline_material,
        body_explains_delta=body_material, reason="old_event_has_material_current_delta",
    )
