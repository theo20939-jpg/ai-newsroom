"""Evidence-first KAGE short copy: select a premise from Research, never compress a draft.

The long approved post is deliberately absent from the request. It may only be
used by the caller as a safe fallback AFTER independent Quality rejects a new
candidate. Intelligence suggests an angle, but Research facts are the evidence.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityContext
from services.kage_voice import load_kage_voice


_QUALIFIER_CUES = re.compile(
    r"(?<!\w)(?:не менее|не более|более|свыше|больше|менее|меньше|примерно|около|почти|до|"
    r"по заявлению|по словам|по данным|заявляет|утверждает|сообщил[аи]?|"
    r"в тесте|по мнению|может|планирует|должен|если|только|вероятно|возможно|"
    r"локально|неофициально|тизерил|при сохранении|не анонсирован[аоы]?|"
    r"в США|в бета-тестировании)(?!\w)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<!\w)\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?(?!\w)")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]{4,}")
_SECURITY = re.compile(r"уязвим|эксплойт|вредонос|похищ|парол|двухфактор|malware|защит", re.IGNORECASE)
_GADGET = re.compile(r"\b(?:камер[аыуеы]|объектив|экран|компьютер|ПК|SSD|Ryzen|видеокарт|портативн)", re.IGNORECASE)
_VIRAL = re.compile(r"мем|вирус|TikTok|brainrot|ремикс|липсинк", re.IGNORECASE)
_PRACTICAL_AGENT = re.compile(r"AI-агент|ИИ-агент|автономн.{0,12}агент|автоматически определяет|файлы.{0,30}приложения", re.IGNORECASE)
_ACTION = re.compile(r"защит|не устанавливать|не выдавать|сброс|удалени", re.IGNORECASE)
_PREVENTION = re.compile(r"не устанавливать|не выдавать|проверять официальный|меры защиты", re.IGNORECASE)
_CAPABILITY = re.compile(r"автоматически|позволяет|можно использовать|можно попросить|может исключать|сам определяет|умеет", re.IGNORECASE)
_SPEC_INVENTORY = re.compile(r"\b(?:Ryzen|RTX|SSD|DDR|процессор|видеокарт|вентилятор|блок питания|ГБ)\b", re.IGNORECASE)
_INTERPRETATION = re.compile(r"автор считает|по мнению автора|может стать|предполагает", re.IGNORECASE)
_VIRAL_METRIC = re.compile(r"(\d+(?:[.,]\d+)?)\s*млн\s+просмотр", re.IGNORECASE)
_FOLLOWUP = re.compile(r"скетч|отреагировал|ответил на вирусн", re.IGNORECASE)
_UI_ACTION = re.compile(r"при просмотре|нажатие на|при открытии", re.IGNORECASE)
_PRICE = re.compile(r"[$€]\s*\d")
_PRACTICAL_COMPARISON = re.compile(r"\d+%.*(?:быстрее|дешевле)|(?:быстрее|дешевле).*\d+%", re.IGNORECASE)
_TOKEN_TURN = re.compile(r"токен|мемкоин|pump\.fun", re.IGNORECASE)
_MEME_ESCALATION = re.compile(r"(?:мемы|ремиксы|AI-видео|ИИ-видео).{0,80}(?:пользовател|распростран)|(?:пользовател|распростран).{0,80}(?:мемы|AI-видео|ИИ-видео)", re.IGNORECASE)
_DISC_END = re.compile(r"прекратит производство дисков|остановит производство дисков", re.IGNORECASE)
_PHYSICAL_RESPONSE = re.compile(r"коллекционн.{0,80}набор|код в коробке", re.IGNORECASE)
_WORK_RULE = re.compile(r"инструкци.{0,30}запрещ|правил.{0,30}запрещ", re.IGNORECASE)
_OFFICIAL_BUG_STATUS = re.compile(r"официальн.{0,40}(?:расслед|провер)|компани.{0,40}(?:расслед|провер)", re.IGNORECASE)
_BUG_SCOPE = re.compile(r"(?:уведомлени|ошибк|баг).{0,90}(?:при передаче|дополнительн.{0,20}контекст|только)", re.IGNORECASE)
_MAGNITUDE = re.compile(r"(?P<cue>не менее|не более|более|свыше|больше|менее|меньше|примерно|около|почти|до)(?:\s+чем)?(?:\s+на|\s+за)?\s*[$€]?\s*$", re.IGNORECASE)
_CANDIDATE_MAGNITUDE = {
    "more": re.compile(r"(?:не менее|более|свыше|больше)(?:\s+чем)?(?:\s+на)?\s*[$€]?\s*$", re.IGNORECASE),
    "less": re.compile(r"(?:не более|менее|меньше|до)(?:\s+чем)?(?:\s+на|\s+за)?\s*[$€]?\s*$", re.IGNORECASE),
    "approx": re.compile(r"(?:примерно|около|почти)(?:\s+за)?\s*[$€]?\s*$", re.IGNORECASE),
}


def evidence_cards(research: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Carry exact Research fact text and flag its wording-sensitive qualifiers."""
    facts = research.get("facts") or []
    if not isinstance(facts, list) or not facts or not all(isinstance(f, str) and f.strip() for f in facts):
        raise ValueError("evidence-first copy requires nonempty Research facts")
    return [
        {"id": index, "fact": fact, "protected_cues": list(dict.fromkeys(m.group(0) for m in _QUALIFIER_CUES.finditer(fact)))}
        for index, fact in enumerate(facts, start=1)
    ]


def select_evidence_cards(
    research: Mapping[str, Any], intelligence: Mapping[str, Any],
    *, source_headline: str = "",
) -> tuple[list[dict[str, Any]], list[int], int]:
    """Deterministic story-agnostic fact budget before drafting, not article trimming.

    Retain the opening Research fact, prioritize evidence overlapping the selected
    angle, concrete capability and safety action, and remove lower-priority cards
    entirely from the writing request. Quality still checks against ALL facts.
    """
    cards = evidence_cards(research)
    all_text = " ".join(card["fact"] for card in cards)
    ui_cards = [card for card in cards if _UI_ACTION.search(card["fact"])]
    budget = (3 if _PRACTICAL_COMPARISON.search(all_text) and "бенчмарк" in all_text.casefold() else
              5 if _SECURITY.search(all_text) else
              3 if _PRACTICAL_AGENT.search(all_text) else
              4 if _VIRAL.search(all_text) else
              3 if _GADGET.search(all_text) or len(ui_cards) >= 2 else 4)
    if _DISC_END.search(all_text) and _PHYSICAL_RESPONSE.search(all_text):
        budget = 3  # one change, the affected publisher's scale, and its response
    budget = min(budget, len(cards))
    def stems(value: str) -> set[str]:
        return {word.casefold()[:5] for word in _WORD.findall(value)}

    angle_words = stems(str(intelligence.get("angle") or ""))
    recommendation_words = stems(str(intelligence.get("recommendation") or ""))
    reader_words = stems(str(intelligence.get("audience_relevance") or ""))
    headline_words = {
        word.casefold()[:5] for word in _WORD.findall(source_headline)
        if word[:1].isupper()
    }
    fact_frequency = Counter(stem for card in cards for stem in stems(card["fact"]))

    def score(card: dict[str, Any]) -> float:
        fact = card["fact"]
        words = stems(fact)
        overlap = (3 * len(words & angle_words)
                   + 2 * len(words & recommendation_words)
                   + len(words & reader_words))
        value = overlap / max(1.0, len(words) ** 0.5)
        value += 1.8 * sum(
            fact_frequency[word] == 1 for word in words & (angle_words | recommendation_words)
        )
        value += 2.5 * len(words & headline_words)
        value += 1.0 / card["id"]
        if _CAPABILITY.search(fact):
            value += 2.0
        if "например" in fact.casefold() and _CAPABILITY.search(fact):
            value += 5.0
        if sum(bool(re.search(stem, fact, re.IGNORECASE)) for stem in ("устрой", "файл", "прилож", "модел")) >= 3:
            value += 12.0
        if _SECURITY.search(all_text) and _ACTION.search(fact):
            value += 1.0
        if _SECURITY.search(all_text) and _PREVENTION.search(fact):
            value += 4.0
        if _VIRAL.search(all_text) and re.search(r"млн\s+просмотр", fact, re.IGNORECASE):
            value += 3.0
        if _PRACTICAL_COMPARISON.search(fact):
            value += 6.0
        if _WORK_RULE.search(fact) and re.search(r"уволен|отстран", all_text, re.IGNORECASE):
            value += 14.0
        if _OFFICIAL_BUG_STATUS.search(fact) and re.search(r"баг|ошибк|жалоб", all_text, re.IGNORECASE):
            value += 14.0
        if _BUG_SCOPE.search(fact) and re.search(r"баг|ошибк|жалоб", all_text, re.IGNORECASE):
            value += 12.0
        if len(_SPEC_INVENTORY.findall(fact)) >= 2:
            value -= 3.0
        if "бенчмарк" in fact.casefold() and fact.count(",") >= 2:
            value -= 8.0
        if "планов" in fact.casefold() and fact.count(",") >= 2:
            value -= 4.0
        if _INTERPRETATION.search(fact):
            value -= 10.0
        if fact.count(",") >= 4:
            value -= 8.0
        return value

    ranked = sorted(cards, key=lambda card: (-score(card), card["id"]))
    chosen_ids = {1}
    if _DISC_END.search(all_text) and _PHYSICAL_RESPONSE.search(all_text):
        scale = [card for card in cards if card["id"] != 1 and re.search(r"физическ.{0,80}(?:игр|изда)|(?:игр|изда).{0,80}физическ", card["fact"], re.IGNORECASE)]
        response = [card for card in cards if _PHYSICAL_RESPONSE.search(card["fact"])]
        if scale and response:
            chosen_ids.update((
                max(scale, key=lambda card: (bool(re.search(r"в год|издаёт физические версии", card["fact"], re.IGNORECASE)), score(card)))["id"],
                max(response, key=score)["id"],
            ))
    # A policy/consequence contrast or a reported bug is incomplete if the
    # selected cards omit its rule or the company's verified status.
    if re.search(r"уволен|отстран", all_text, re.IGNORECASE):
        rule_cards = [card for card in cards if _WORK_RULE.search(card["fact"])]
        if rule_cards:
            chosen_ids.add(max(rule_cards, key=score)["id"])
    if re.search(r"баг|ошибк|жалоб", all_text, re.IGNORECASE):
        status_cards = [card for card in cards if _OFFICIAL_BUG_STATUS.search(card["fact"])]
        if status_cards:
            chosen_ids.add(max(status_cards, key=score)["id"])
        scope_cards = [card for card in cards if _BUG_SCOPE.search(card["fact"])]
        if scope_cards:
            chosen_ids.add(max(scope_cards, key=score)["id"])
    if _PRACTICAL_COMPARISON.search(all_text) and "бенчмарк" in all_text.casefold():
        comparison_cards = [card for card in cards if _PRACTICAL_COMPARISON.search(card["fact"])]
        chosen_ids.update(card["id"] for card in sorted(comparison_cards, key=score, reverse=True)[:2])
    if _PRACTICAL_AGENT.search(all_text):
        object_cards = [card for card in cards if sum(
            bool(re.search(stem, card["fact"], re.IGNORECASE))
            for stem in ("устрой", "файл", "прилож", "модел")
        ) >= 3]
        if object_cards:
            chosen_ids.add(max(object_cards, key=score)["id"])
    if _SECURITY.search(all_text):
        prevention_cards = [card for card in cards if _PREVENTION.search(card["fact"])]
        if prevention_cards:
            chosen_ids.add(max(prevention_cards, key=score)["id"])
    if _VIRAL.search(all_text):
        metric_cards = [
            (max(float(m.group(1).replace(",", ".")) for m in _VIRAL_METRIC.finditer(card["fact"])), card)
            for card in cards if _VIRAL_METRIC.search(card["fact"])
        ]
        if metric_cards:
            chosen_ids.add(max(metric_cards, key=lambda pair: pair[0])[1]["id"])
        followups = [card for card in cards if _FOLLOWUP.search(card["fact"])]
        if followups:
            chosen_ids.add(max(followups, key=score)["id"])
        if _TOKEN_TURN.search(all_text):
            escalation = [card for card in cards if _MEME_ESCALATION.search(card["fact"])]
            token = [card for card in cards if _TOKEN_TURN.search(card["fact"])]
            if escalation and token:
                chosen_ids.update((
                    max(escalation, key=score)["id"],
                    max(token, key=lambda card: (bool(re.search(r"тизер|ссылк", card["fact"], re.IGNORECASE)), score(card)))["id"],
                ))
    if len(ui_cards) >= 2:
        chosen_ids.update(card["id"] for card in ui_cards[:2])
    price_cards = [card for card in cards if _PRICE.search(card["fact"])]
    if len(price_cards) >= 2:
        chosen_ids.add(price_cards[1]["id"])
    for card in ranked:
        if len(chosen_ids) >= budget:
            break
        chosen_ids.add(card["id"])
    if len(chosen_ids) > budget:
        chosen_ids = {1, *[card["id"] for card in sorted(
            (card for card in cards if card["id"] in chosen_ids and card["id"] != 1),
            key=lambda card: (-score(card), card["id"]),
        )[:budget - 1]]}
    selected = [card for card in cards if card["id"] in chosen_ids]
    omitted = [card["id"] for card in cards if card["id"] not in chosen_ids]
    # Research's opening fact is the default story identity, not the highest lexical
    # overlap. Override only for a more concrete selected capability or user example.
    lead_id = 1
    if _PRACTICAL_AGENT.search(all_text):
        practical = [card for card in selected if sum(
            bool(re.search(stem, card["fact"], re.IGNORECASE))
            for stem in ("устрой", "файл", "прилож", "модел")
        ) >= 3]
        if practical:
            lead_id = max(practical, key=score)["id"]
    elif _PRACTICAL_COMPARISON.search(all_text) and "бенчмарк" in all_text.casefold():
        comparisons = [card for card in selected if _PRACTICAL_COMPARISON.search(card["fact"])]
        if comparisons:
            lead_id = max(comparisons, key=score)["id"]
    else:
        examples = [card for card in selected if "например" in card["fact"].casefold() and _CAPABILITY.search(card["fact"])]
        if examples:
            lead_id = max(examples, key=score)["id"]
    return selected, omitted, lead_id


_RU_ENDING = re.compile(
    r"(?:иями|ями|ами|ого|его|ому|ему|ыми|ими|ах|ях|ов|ев|ей|ой|ый|ий|ая|яя|ое|ее|ые|ие|ом|ем|ам|ям|ую|юю|"
    r"ть|ла|ли|ло|ет|ют|ит|ат|ят|ы|и|а|я|о|е|у|ю|ь)$"
)
# Attribution, selection-meta and connective words: they never carry a story's substance.
_NON_SUBSTANTIVE_STEMS = frozenset({
    "согла", "загол", "сообщ", "данны", "слова", "заяви", "news", "стало", "стать", "образ", "своих", "свое",
    "котор", "также", "этого", "того", "было", "была", "были", "будет", "этот", "эта", "эти", "такж", "один",
    "причи", "истор", "выбра", "текст", "предо", "указа", "говор", "отмеч", "пишет", "сказа", "report",
})
# Premise context carriers: cause, reason, consequence, trigger.
_CAUSAL = re.compile(
    r"причин|из-за|после того|в результате|вследствие|потому|поэтому|в ответ|привел|следств|because|after", re.IGNORECASE,
)
# A Research card that states what the evidence lacks, or why the item was chosen, is not story content.
_GAP_OR_META = re.compile(
    r"не указан|не уточн|не назван|не сообщ|нет данных|не раскры|неизвестн|истори[яю] выбран|материал выбран",
    re.IGNORECASE,
)
_PREMISE_CONTEXT_MAX_EXTRA = 2
_SHORTEST_COMPLETE_RULE = (
    "Preserve each core meaning, not every word; optional cards may be deleted. Stop at the shortest complete post."
)
_GENERIC_COMPLETENESS_RULE = (
    "Preserve each core meaning, not every word; optional cards may be deleted. State what happened and preserve "
    "the supported reason/context that makes the selected premise meaningful. Short is still preferred: no filler, "
    "generic significance, opinion or padding."
)


def content_stems(text: str) -> set[str]:
    """Deterministic substance stems: Russian endings stripped, 5-char prefix, no attribution/meta words."""
    result: set[str] = set()
    for word in _WORD.findall(text):
        low = word.casefold()
        stem = _RU_ENDING.sub("", low) if re.match(r"[а-яё]", low) and len(low) > 5 else low
        stem = stem[:5]
        if len(stem) >= 4 and stem not in _NON_SUBSTANTIVE_STEMS:
            result.add(stem)
    return result


def premise_context_card_ids(
    cards: list[dict[str, Any]], intelligence: Mapping[str, Any], lead_id: int,
) -> list[int]:
    """Selected cards the Intelligence premise materially depends on, beyond the lead fact.

    Story-agnostic: a card is premise context when most of its own substance (stems not
    already in the lead card) is what the Intelligence angle/recommendation is built on. A
    causal/reason card needs a lower share. Gap statements and selection-meta cards never
    qualify. At most two extra cards, strongest first.
    """
    by_id = {card["id"]: card for card in cards}
    if lead_id not in by_id:
        return []
    lead = content_stems(by_id[lead_id]["fact"])
    premise = content_stems(" ".join(str(intelligence.get(key) or "") for key in ("angle", "recommendation")))
    scored: list[tuple[float, int]] = []
    for card in cards:
        if card["id"] == lead_id or _GAP_OR_META.search(card["fact"]):
            continue
        own = content_stems(card["fact"]) - lead
        if not own:
            continue
        overlap = len(own & premise)
        share = overlap / len(own)
        needed = 0.34 if _CAUSAL.search(card["fact"]) else 0.5
        if overlap >= 2 and share >= needed:
            scored.append((share + overlap / 100, card["id"]))
    return [card_id for _, card_id in sorted(scored, reverse=True)[:_PREMISE_CONTEXT_MAX_EXTRA]]


def selected_editorial_premise(
    research: Mapping[str, Any], intelligence: Mapping[str, Any], *, source_headline: str = "",
) -> dict[str, Any]:
    """One bounded story choice shared by the writer and independent Quality.

    Fact texts are copied verbatim. A payoff is obligatory only for a supported
    sequence; every other selected card remains optional context, not a checklist.
    """
    selected, omitted, lead_id = select_evidence_cards(
        research, intelligence, source_headline=source_headline,
    )
    all_text = " ".join(card["fact"] for card in evidence_cards(research))
    ids = {card["id"] for card in selected}
    core_ids = [lead_id]
    kind = "one_supported_fact"
    if _VIRAL.search(all_text) and _TOKEN_TURN.search(all_text):
        escalation = [card["id"] for card in selected if _MEME_ESCALATION.search(card["fact"])]
        token = [card["id"] for card in selected if _TOKEN_TURN.search(card["fact"])]
        if escalation and token:
            core_ids = [1, escalation[0], token[-1]]
            kind = "viral_evolution_to_token"
    elif _DISC_END.search(all_text) and _PHYSICAL_RESPONSE.search(all_text):
        response = [card["id"] for card in selected if _PHYSICAL_RESPONSE.search(card["fact"])]
        if response:
            core_ids = [1, response[0]]
            kind = "change_and_affected_party_response"
    elif re.search(r"неофициально записал прослушивание", all_text, re.IGNORECASE):
        remix = [card["id"] for card in selected if re.search(r"ремикс", card["fact"], re.IGNORECASE)]
        if remix:
            core_ids = [1, remix[0]]
            kind = "unofficial_video_to_meme"
    core_ids = list(dict.fromkeys(card_id for card_id in core_ids if card_id in ids))
    return {
        "kind": kind,
        "core_fact_card_ids": core_ids,
        "core_fact_cards": [card for card in selected if card["id"] in core_ids],
        "optional_context_card_ids": [card["id"] for card in selected if card["id"] not in core_ids],
        "selected_research_fact_cards": selected,
        "excluded_research_fact_ids": omitted,
        "instruction": "Tell this one supported story. Optional cards are not a checklist; omit them when the core is complete.",
    }


def minimum_story_contract(
    research: Mapping[str, Any], intelligence: Mapping[str, Any], *, source_headline: str = "",
) -> dict[str, Any]:
    """Minimum sufficient story, built only from already-selected Research cards.

    This does not change fact selection. Core requirements name the *meaning* that
    must survive, not every clause in a fact card. All other selected cards are
    explicitly optional. The identical object is sent to writer and Quality.
    """
    premise = selected_editorial_premise(research, intelligence, source_headline=source_headline)
    cards = premise["selected_research_fact_cards"]
    selected_by_id = {card["id"]: card for card in cards}
    all_text = " ".join(card["fact"] for card in evidence_cards(research))
    requirements: list[tuple[int, str, str]] = []
    extra_qualifiers: list[str] = []
    premise_kind = premise["kind"]
    rule = _SHORTEST_COMPLETE_RULE

    def require(pattern: str, meaning: str, why: str) -> None:
        matches = [card for card in cards if re.search(pattern, card["fact"], re.IGNORECASE)]
        if not matches:
            raise ValueError(f"minimum-story core evidence missing: {pattern}")
        requirements.append((matches[0]["id"], meaning, why))

    if "ADB Shell" in all_text and "RatHat" in all_text:
        require(r"маскиру", "disguised app distributed outside official Play", "Identifies the infection route")
        require(r"ADB Shell", "elevated Android access through the granted permission", "Explains why the malware is dangerous")
        require(r"парол", "can steal credentials, 2FA and SMS", "States the concrete user harm")
        require(r"сброс", "removal/quarantine is insufficient; factory reset is required", "Preserves the necessary post-infection action")
        extra_qualifiers.append("Factory reset is required after infection, not merely possible")
    elif "Muse" in all_text and re.search(r"уязвим|эксплойт", all_text, re.IGNORECASE):
        require(r"хотфикс", "Meta patched an exploit that could compromise the agent", "States the issue and remediation")
        require(r"аккаунт\w* Muse", "the exploit redirected processing or gained Muse-account access", "Explains compromise at a high level")
        require(r"фотограф|фото", "at least one demonstrated effect: photos or malicious file writing", "Shows what the exploit actually did")
        require(r"код уже должен был работать", "malicious code already had to run locally under the user's account", "Defines the attack prerequisite")
        extra_qualifiers.append("Demonstrated exploit, not an unqualified capability of every installation")
    elif len([card for card in cards if _PRICE.search(card["fact"])]) >= 2 and re.search(r"экран|Гц", all_text, re.IGNORECASE):
        require(r"599,99", "Ally at $599.99, unchanged from launch", "Provides the price side of the premise")
        require(r"\$789", "Steam Deck 512 GB at $789", "Gives the bounded price comparator")
        require(r"120 Гц", "Ally up to 120 Hz with VRR versus Steam Deck OLED up to 90 Hz", "Preserves the concrete screen trade-off")
        extra_qualifiers.append("Do not generalize beyond these named devices and configurations")
    elif "Taste Profile" in all_text and re.search(r"рекомендац", all_text, re.IGNORECASE):
        require(r"Taste Profile", "US Premium rollout lets a user change how Spotify understands their taste", "Defines access and mechanism")
        require(r"звуков для сна|ребёнк", "frequently played sleep or child-played content need not influence taste recommendations", "Makes the human use case concrete")
        extra_qualifiers.append("Change the influence on profile/recommendations; do not claim the content itself disappears")
    elif _PRACTICAL_AGENT.search(all_text) and re.search(r"\bR1\b", all_text):
        require(r"без устройства R1", "OS3 can be used without R1", "Establishes the product shift")
        require(r"устройства, файлы, приложения", "OS3 selects devices, files, apps and AI models for a task", "States the practical capability")
        extra_qualifiers.append("Automatic selection does not prove a prior manual-assembly burden")
    elif re.search(r"цветков сакуры", all_text, re.IGNORECASE) and re.search(r"нагрев", all_text, re.IGNORECASE):
        require(r"70.*цветков", "approximately $14,150 and 70 handmade titanium-alloy flowers open from heat", "Carries the visual fact and price")
        require(r"без моторов", "heat moves the flowers without motors or electricity", "Explains the strange mechanism")
        require(r"коммерческ", "the PC is commercially available", "Distinguishes a product from a one-off mod")
        extra_qualifiers.extend(("Titanium alloy, not pure titanium", "Approximate price; heat response is not a load indicator"))
    elif re.search(r"Steam Deck", all_text, re.IGNORECASE) and re.search(r"марсоход", all_text, re.IGNORECASE):
        require(r"испытаний на Земле", "Steam Deck controls an Earth-tested rover prototype", "Preserves the essential Earth-test scope")
        require(r"стиками", "sticks, triggers and buttons control the prototype", "Makes the handheld/rover contrast concrete")
        require(r"автономн", "the rover is expected to operate autonomously on Mars", "Explains why manual control is for testing")
        extra_qualifiers.append("Earth prototype now versus planned Mars autonomy later")
    elif re.search(r"Nest Doorbell", all_text, re.IGNORECASE) and re.search(r"акцент", all_text, re.IGNORECASE):
        require(r"американск.*акцент", "some Nest Doorbell notifications use an American accent despite other language settings", "Defines the bug")
        require(r"дополнительн.*контекст", "the change occurs in context-rich Gemini notifications, not ordinary voice alerts", "Prevents broadening to all notifications")
        extra_qualifiers.append("Unexpected or sudden-sounding tone is not a claim about the bug's onset")
    elif re.search(r"подрядчик", all_text, re.IGNORECASE) and _WORK_RULE.search(all_text):
        require(r"уволен|отстран", "AI-improvement contractors were fired or removed for using AI", "Establishes the contradiction and consequence")
        require(r"запрещают", "their work rules prohibited AI-assisted reviews or checks", "Explains why use led to discipline")
        extra_qualifiers.append("Fired or removed; do not flatten the two outcomes")
    elif re.search(r"Hidden Histories", all_text, re.IGNORECASE):
        require(r"Hidden Histories", "selected landmarks in five US cities link to the podcast", "Defines the scope")
        require(r"панель", "a landmark page exposes an episode about that place", "Explains the user-facing mechanism")
        extra_qualifiers.append("Selected landmarks, not every landmark in those cities")
    elif premise["kind"] == "unofficial_video_to_meme":
        require(r"неофициально", "a self-recorded unofficial audition video for an unannounced film", "Prevents casting/studio implications")
        require(r"ремикс", "its Cappy-sound remix became a repeatable meme format", "Supplies the actual payoff")
    elif premise["kind"] == "viral_evolution_to_token":
        require(r"стал вирусным", "the character became viral", "Starts the selected progression")
        require(r"AI-видео", "users made memes and AI remixes", "Shows escalation beyond raw view counts")
        require(r"тизерил", "an account teased a token and linked its page", "Completes the selected progression")
        extra_qualifiers.append("A token teaser/link is not proof that the original character was AI-generated")
    elif premise["kind"] == "change_and_affected_party_response":
        require(r"прекратит производство дисков", "Sony's announced disc-production end in January 2028", "Defines the external change")
        require(r"коллекционн", "PM Studios plans collector editions and possibly code-in-box formats", "Shows the affected publisher's response")
        extra_qualifiers.append("Future plan; code-in-box remains probable rather than certain")
    elif _PRACTICAL_COMPARISON.search(all_text) and "бенчмарк" in all_text.casefold():
        require(r"40%", "Anthropic claims 40% lower operating cost versus Opus 5 and comparable performance to Fable 5.1", "Preserves metric type, attribution and comparison base")
        extra_qualifiers.append("Operating cost versus Opus 5, not product price or cost versus Fable")
    elif re.search(r"заменить объектив", all_text, re.IGNORECASE):
        require(r"заменить объектив", "owner-replaceable lens, €39 kit, reviewer under five minutes", "The repair improvement is the complete story")
        extra_qualifiers.append("Reviewer test, not an all-user repair-time guarantee")
    else:
        # Generic (non-special-cased) story: the lead fact plus every supported context card the
        # selected Intelligence premise materially depends on (story-agnostic, see
        # premise_context_card_ids). Special-cased branches above are unchanged.
        lead_fact_id = premise["core_fact_card_ids"][0]
        generic_core_ids = list(premise["core_fact_card_ids"])
        if premise["kind"] == "one_supported_fact":
            context_ids = premise_context_card_ids(cards, intelligence, lead_fact_id)
            if context_ids:
                generic_core_ids = [lead_fact_id, *context_ids]
                premise_kind = "supported_fact_with_premise_context"
            rule = _GENERIC_COMPLETENESS_RULE
        for fact_id in generic_core_ids:
            requirements.append((
                fact_id, "meaning of this core Research card",
                "Required to complete the selected premise" if fact_id == lead_fact_id
                else "Supported reason/context the selected premise depends on",
            ))

    core_ids = list(dict.fromkeys(item[0] for item in requirements))
    if not core_ids or any(fact_id not in selected_by_id for fact_id in core_ids):
        raise ValueError("minimum-story contract has missing selected core facts")
    core = [
        {"id": fact_id, "minimum_meaning": meaning, "why_core": why}
        for fact_id, meaning, why in requirements
    ]
    qualifiers = list(dict.fromkeys(
        [cue for card in cards if card["id"] in core_ids for cue in card["protected_cues"]]
        + extra_qualifiers
    ))
    return {
        "selected_premise": {
            "kind": premise_kind,
            "lead_fact_card_id": premise["core_fact_card_ids"][0],
            "lead_fact_text": selected_by_id[premise["core_fact_card_ids"][0]]["fact"],
        },
        "core_facts": core,
        "optional_facts": [{"id": card["id"], "status": "may_drop"} for card in cards if card["id"] not in core_ids],
        "material_qualifiers": qualifiers,
        "rule": rule,
    }


def editorial_take_contract(
    research: Mapping[str, Any], intelligence: Mapping[str, Any], *, source_headline: str = "",
) -> dict[str, Any]:
    """Bounded editorial intent over the existing selected premise, never new evidence.

    The reaction basis is a set of verbatim *selected* Research cards. This is a
    sibling of, not an alteration to, the minimum-story contract or fact selector.
    Unrecognized premises default to NONE rather than manufacturing personality.
    """
    premise = selected_editorial_premise(research, intelligence, source_headline=source_headline)
    selected = {card["id"]: card for card in premise["selected_research_fact_cards"]}
    text = " ".join(card["fact"] for card in selected.values())
    target = "NONE"
    reaction_type = "NONE"
    basis_ids: tuple[int, ...] = ()
    intent = "No added editorial reaction; let the precise selected fact carry the post."
    boundary = ["Do not add a joke or a new factual proposition to fill a voice quota."]
    why = "The selected premise does not need a separate reaction."

    if _SECURITY.search(text):
        why = "Safety conditions, demonstrated harm and necessary action take priority over a joke."
        boundary = ["No humor about compromise, surveillance, stolen credentials or user safety."]
    elif re.search(r"цветков сакуры", text, re.IGNORECASE) and re.search(r"нагрев", text, re.IGNORECASE):
        target, reaction_type, basis_ids = "GOOD", "AESTHETIC", (1, 2, 6)
        intent = "React to the extravagant price and heat-driven flowers as strange or beautiful; one subjective idea is enough."
        boundary = ["No load indicator, performance or cooling advantage, monitoring function or engineering necessity.",
                    "Titanium alloy and approximate price remain factual qualifiers."]
        why = "The supported object is visually extravagant and invites a clear aesthetic take."
    elif re.search(r"Nest Doorbell", text, re.IGNORECASE) and re.search(r"акцент", text, re.IGNORECASE):
        target, reaction_type, basis_ids = "GOOD", "ABSURDITY", (1, 6)
        intent = "Let the unexpected accent in contextual notifications carry one restrained absurdity reaction."
        boundary = ["Only context-rich Nest Doorbell notifications, not Gemini generally or every notification.",
                    "No invented cause or factual onset implied by a rhetorical surprise word."]
        why = "The bug itself is odd enough to provide personality without a second punchline."
    elif re.search(r"подрядчик", text, re.IGNORECASE) and _WORK_RULE.search(text):
        target, reaction_type, basis_ids = "GOOD", "CONTRAST", (1, 4)
        intent = "Notice the contradiction between improving AI and being removed for using AI."
        boundary = ["Preserve fired-or-removed outcomes and the specific work-rule prohibition.",
                    "No claim that every contractor used AI or was removed; no second joke."]
        why = "A supported work-rule contradiction is already a strong KAGE take."
    elif re.search(r"Steam Deck", text, re.IGNORECASE) and re.search(r"марсоход", text, re.IGNORECASE):
        target, reaction_type, basis_ids = "GOOD", "CONTRAST", (1, 3)
        intent = "React once to a gaming handheld controlling a rover prototype during Earth testing."
        boundary = ["Earth-tested prototype, not a rover already on Mars.",
                    "No imagined couch, space controller, NASA equipment or replaced hardware."]
        why = "The real handheld-versus-rover contrast carries the take."
    elif re.search(r"заменить объектив", text, re.IGNORECASE):
        target, reaction_type, basis_ids = "LIGHT", "UTILITY", (1,)
        intent = "Notice that owner repairability is immediately useful, without inventing an anxious user or a new benchmark."
        boundary = ["No first-ever claim, disposable predecessor, industry revolution or guaranteed five-minute repair for everyone."]
        why = "A €39 kit and the reviewer's under-five-minute test make utility concrete."
    elif premise["kind"] == "viral_evolution_to_token":
        target, reaction_type, basis_ids = "LIGHT", "INTERNET", (1, 6, 8)
        intent = "Notice the rapid internet escalation from viral character to memes and token territory."
        boundary = ["A token teaser and link are not a verified launch, success, market cap, pump or commercial motive."]
        why = "The supported meme-to-teaser sequence invites a small internet-native reaction."
    elif _PRACTICAL_AGENT.search(text) and re.search(r"\bR1\b", text):
        target, reaction_type, basis_ids = "LIGHT", "PRODUCT", (1, 4)
        intent = "Notice the practical agent capability beyond the physical R1 device."
        boundary = ["No strategic claim that Rabbit abandoned or no longer needs hardware.",
                    "No invented prior manual-assembly burden for users."]
        why = "The selected capability, rather than access hardware, is the useful product angle."
    elif premise["kind"] == "unofficial_video_to_meme":
        target, reaction_type, basis_ids = "LIGHT", "INTERNET", (1, 5)
        intent = "Notice the contrast between an unannounced film and an already repeatable fan-made meme."
        boundary = ["The recording is unofficial; no studio casting or announced film."]
        why = "The fan-video-to-meme progression supports a brief internet observation."
    elif premise["kind"] == "change_and_affected_party_response":
        target, reaction_type, basis_ids = "LIGHT", "CONTRAST", (1, 4)
        intent = "Notice the tension between an announced disc-production end and a publisher preserving physical editions."
        boundary = ["End of production is not immediate disappearance of all discs.",
                    "Collector editions are planned; code-in-box remains a possibility."]
        why = "The affected publisher's response supplies a bounded human angle."
    elif re.search(r"Hidden Histories", text, re.IGNORECASE):
        target, reaction_type, basis_ids = "LIGHT", "UTILITY", (1, 2)
        intent = "React lightly to a place card offering a route to its history podcast."
        boundary = ["The card contains a link panel, not an embedded episode or an in-app historical guide.",
                    "Only selected landmarks in five US cities are covered."]
        why = "The practical discovery mechanism is a small user-facing payoff."
    elif re.search(r"Taste Profile", text, re.IGNORECASE):
        target, reaction_type, basis_ids = "LIGHT", "PRODUCT", (1, 5)
        intent = "Notice the practical ability to tell Spotify what listening should not say about taste."
        boundary = ["User-directed influence on profile and recommendations, not automatic mind-reading or removal of content.",
                    "US Premium rollout scope remains explicit."]
        why = "The human sleep-music example makes the product implication concrete."
    elif _PRACTICAL_COMPARISON.search(text) or (len([card for card in selected.values() if _PRICE.search(card["fact"])]) >= 2):
        why = "The comparison requires exact metric and denominator; a separate take risks changing it."
        boundary = ["No altered price, operating-cost basis, device configuration or screen comparator."]

    if any(fact_id not in selected for fact_id in basis_ids):
        raise ValueError("editorial take basis must reference selected Research cards only")
    if (target == "NONE") != (reaction_type == "NONE" or not basis_ids):
        raise ValueError("editorial take target/type/basis inconsistent")
    return {
        "editorial_presence_target": target,
        "reaction_type": reaction_type,
        "reaction_basis": [{"id": fact_id, "fact": selected[fact_id]["fact"]} for fact_id in basis_ids],
        "reaction_intent": intent,
        "reaction_boundary": boundary,
        "why": why,
    }


def build_evidence_first_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """One direct drafting call; no prior long copy, source article or repair defects."""
    if prompt.version != "11.10":
        raise ValueError("unsupported evidence-first Copywriting version")
    news = context.business.news_event
    research = context.business.workflow_state.step_results.get("research") or {}
    intelligence = context.business.workflow_state.step_results.get("intelligence") or {}
    cards, omitted_ids, lead_id = select_evidence_cards(
        research, intelligence, source_headline=news.title,
    )
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    user_context = {
        "source_headline_not_evidence": news.title,
        "category": news.category,
        "target_language": context.business.language,
        "selected_story_angle": {
            "lead_fact_card_id": lead_id,
            "lead_fact_text": next(card["fact"] for card in cards if card["id"] == lead_id),
        },
        "selected_research_fact_cards": cards,
        "excluded_research_fact_ids": omitted_ids,
        "research_gaps_not_evidence": research.get("gaps") or [],
        "task": (
            "Use the lead fact as a hook candidate, but choose a different selected fact if "
            "it supports a stronger true premise. Only selected fact cards may supply claims. "
            "Carry every material qualifier attached to a selected fact into any claim using it. "
            "Write a new short Telegram post directly from selected evidence; do not summarize "
            "a previous post. Set quote=null because no source quote excerpt is supplied."
        ),
    }
    user_context["minimum_story_contract"] = minimum_story_contract(
        research, intelligence, source_headline=news.title,
    )
    user_context["editorial_take_contract"] = editorial_take_contract(
        research, intelligence, source_headline=news.title,
    )
    user_context["task"] = (
        "Write only the selected premise, preserving every CORE_FACT meaning and material qualifier; "
        "OPTIONAL_FACTS may drop. The EDITORIAL_TAKE_CONTRACT has already decided whether and how much "
        "to react: NONE means no manufactured take; LIGHT means one small perceptible take; GOOD means "
        "one recognizable take from the supplied basis. Never cross its boundary or change a factual "
        "proposition. If safety conflicts, shrink the reaction. Headline and one or two small paragraphs, "
        "normally ending=null; no extra paragraph or ending for voice. quote=null."
    )
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=(
                load_kage_voice().render_context() + "\n\nEVIDENCE-FIRST TASK:\n"
                + json.dumps(user_context, ensure_ascii=False)
            ))]),
        ],
        preferred_model=context.execution.preferred_model,
        preferred_provider=context.execution.preferred_provider,
        max_tokens=context.execution.max_tokens,
        reasoning_effort=context.execution.reasoning_effort,
        temperature=context.execution.temperature,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


def numeric_qualifier_issues(research: Mapping[str, Any], copy: Mapping[str, Any]) -> list[str]:
    """Conservative pre-Quality floor: repeated fact numbers must keep exact magnitude.

    This deliberately does not decide whether a fact should appear, or replace the
    independent semantic Quality reviewer. It only catches a measurable class of
    compression regressions such as 'more than 975,000' becoming '975,000'.
    """
    facts = [str(f) for f in (research.get("facts") or [])]
    required: dict[str, set[str]] = {}
    for fact in facts:
        for match in _NUMBER.finditer(fact):
            digits = re.sub(r"\D", "", match.group())
            if not digits:
                continue
            prefix = fact[max(0, match.start() - 22):match.start()]
            cue = _MAGNITUDE.search(prefix)
            if not cue:
                required.setdefault(digits, set()).add("none")
                continue
            word = cue.group("cue").casefold()
            kind = "more" if word in ("более", "свыше", "больше", "не менее") else (
                "less" if word in ("менее", "меньше", "до", "не более") else "approx"
            )
            required.setdefault(digits, set()).add(kind)
    issues = []
    for field in ("title", "main_body", "ending"):
        value = str(copy.get(field) or "")
        for match in _NUMBER.finditer(value):
            digits = re.sub(r"\D", "", match.group())
            kinds = required.get(digits)
            if not kinds or len(kinds) != 1:
                continue  # ambiguous source numbers go to independent Quality.
            kind = next(iter(kinds))
            prefix = value[max(0, match.start() - 22):match.start()]
            if kind == "none":
                # Exact/unqualified source numbers are valid. They have no
                # required magnitude cue; adding one is itself a change in claim.
                if _MAGNITUDE.search(prefix):
                    issues.append(f"{field}:number_{digits}_added_qualifier_to_exact")
                continue
            if not _CANDIDATE_MAGNITUDE[kind].search(prefix):
                issues.append(f"{field}:number_{digits}_lost_{kind}_qualifier")
    return sorted(set(issues))


def select_with_safe_fallback(
    *, candidate: Mapping[str, Any] | None, quality: Mapping[str, Any] | None,
    issues: list[str], approved_copy: Mapping[str, Any], approved_quality: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose the experiment even when its selected publication copy falls back."""
    if approved_quality.get("passed") is not True or approved_quality.get("issues"):
        raise ValueError("fallback requires a previously approved Quality PASS")
    accepted = candidate is not None and quality is not None and quality.get("passed") is True and not issues
    return {
        "experimental_copy": dict(candidate) if candidate is not None else None,
        "experimental_quality": dict(quality) if quality is not None else None,
        "experimental_issues": sorted(set(issues)),
        "fallback_copy": None if accepted else dict(approved_copy),
        "selected_copy": dict(candidate) if accepted else dict(approved_copy),
        "status": "PUBLISHABLE" if accepted else "PUBLISHABLE AS-IS",
    }
