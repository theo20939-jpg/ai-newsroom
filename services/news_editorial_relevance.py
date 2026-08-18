"""Deterministic, LLM-free editorial-relevance tiering for CONTENT_GENERATION candidate
selection (topic-skew fix: too many funding/valuation/economy stories reaching drafting,
too many stories where "AI" is only mentioned as context rather than being the actual subject).

Pure functions only - no DB write, no new LLM call, no persisted taxonomy, no migration.
Classifies a candidate's editorial priority from its title/content alone, using the same
word-boundary phrase-matching discipline already established by services/channel_relevance.py
and services/editorial_content_type.py (bilingual EN/RU keyword families, first-match-wins /
earliest-position-wins - never a generative classifier). `services/channel_relevance.py`'s own
`ArticleTopic` taxonomy (Phase 17 M2) was investigated as a candidate reuse target and rejected
for this specific purpose: it answers a different question ("does this fit channel X's editorial
policy") and its bare "ai"-keyword match alone is enough to set `primary_topic=AI` even for a
finance-subject story that only mentions AI in passing (e.g. "Norway wealth fund warns of AI
stock market bubble") - exactly the AI-as-context false positive this module exists to avoid.

Subject-awareness ("AI is mentioned" != "AI is the story"): CORE is triggered only by
product/tech ACTION phrases (launches, releases, adds a feature, ships a chip...) - the bare
word "AI" is deliberately never a keyword here, so a story about AI-driven stock market fears
never earns CORE just because "AI" appears in it. When a title contains keyword hits from more
than one family, whichever phrase starts earliest decides the subject - this cheaply
approximates "what is this headline actually about" without any NLP (ordinary EN/RU headline
structure puts the subject/main verb near the front) and is the only thing that correctly
separates "OpenAI launches GPT-X after raising $10B" (CORE) from "OpenAI raises $10B to fund
GPT-X development" (PERIPHERAL).

ACTION VERB != PRODUCT SUBJECT: a generic action verb (launches/releases/announces/introduces/
RU equivalents, and the equally generic bare "update") is deliberately never CORE-triggering on
its own ("Israel Launches National AI Action Plan" is not a product story) - it only counts once
a `_PRODUCT_OBJECT_PHRASES` noun (model/API/app/smartphone/chip/...) is also present somewhere
in the same scanned text (`_core_match_start()`). A handful of already-specific multi-word
phrases ("new feature", "security update", device/chip nouns...) stay self-sufficient and need
no paired verb, since they already name a concrete product/tech object by themselves.
`_PRODUCT_OBJECT_PHRASES` is a confirmation signal only - it never grants CORE by itself without
a paired generic verb (a bare "GPT" mention in a funding headline must not become CORE).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CORE = "CORE"
ADJACENT = "ADJACENT"
PERIPHERAL = "PERIPHERAL"
OUT_OF_SCOPE = "OUT_OF_SCOPE"

_CORE_RANK_ADJUSTMENT = 10
_ADJACENT_RANK_ADJUSTMENT = 3
_NEUTRAL_RANK_ADJUSTMENT = 0
_PERIPHERAL_RANK_ADJUSTMENT = -12
_MAJOR_IMPACT_OVERRIDE_RANK_ADJUSTMENT = 5
_OUT_OF_SCOPE_RANK_ADJUSTMENT = -1000

_CONTENT_SCAN_CHARS = 800


@dataclass(frozen=True)
class EditorialRelevanceDecision:
    tier: str
    rank_adjustment: int
    major_impact_override: bool
    reason: str


_CORE_SELF_SUFFICIENT_PHRASES: tuple[str, ...] = (
    # already-specific multi-word phrases - these already name a concrete product/tech object,
    # so (unlike the generic verbs below) they need no paired _PRODUCT_OBJECT_PHRASES match.
    "new feature", "new features", "adds support", "gains support",
    "новая функция", "новую функцию", "добавила функцию", "добавил функцию",
    "new model", "model update", "new api", "api update", "new sdk", "sdk update",
    "новая модель", "обновление модели", "новый api", "новый sdk",
    # devices - singular RU forms only (deliberately no plural/case forms here: a bare plural
    # "chips"/"chipsets" mention is common in chip-industry finance/valuation stories too, e.g.
    # "Chip maker CXMT becomes China's most valuable company" - see _PRODUCT_OBJECT_PHRASES for
    # the gated plural/case forms, which require a paired action verb, never self-sufficient).
    "smartphone", "laptop", "tablet", "smartwatch", "headset", "earbuds", "wearable",
    "смартфон", "ноутбук", "планшет", "умные часы", "наушники", "гарнитура",
    # chips
    "gpu", "cpu", "chip", "chipset", "processor", "видеокарта", "процессор", "чип", "чипсет",
    # security / outage / product change
    "vulnerability", "exploit", "zero-day", "security update", "actively exploited",
    "is down", "outage", "went down", "service disruption",
    "уязвимость", "эксплойт", "сбой", "авария", "недоступен",
)

_GENERIC_ACTION_VERB_PHRASES: tuple[str, ...] = (
    # generic action verbs - CORE only when a _PRODUCT_OBJECT_PHRASES noun is also present
    # somewhere in the same text (see _core_match_start()); on their own, these describe a
    # "launch"/"release"/"update" of anything at all, tech or not.
    "releases", "released", "launches", "launched", "launch", "announces", "announced",
    "unveils", "unveiled", "introduces", "introduced", "debuts", "debuted", "ships",
    "rolls out", "roll out", "adds", "adding", "update", "updates", "updated",
    "выпустил", "выпустила", "выпустили", "анонсировал", "анонсировала", "анонсировали",
    "представил", "представила", "представили", "запустил", "запустила", "запустили",
    "запустило", "добавил", "добавила", "добавили", "обновил", "обновила", "обновление",
)

_PRODUCT_OBJECT_PHRASES: tuple[str, ...] = (
    # confirms a generic action verb's object is a product/tech thing, not policy/finance/legal -
    # a bare match here never grants CORE by itself (see _core_match_start()'s own docstring).
    "model", "llm", "gpt", "claude", "gemini", "copilot", "chatgpt", "sora", "grok",
    "model version", "reasoning mode",
    "feature", "function", "mode", "app", "application", "platform", "browser",
    "operating system", "ios", "android", "windows", "macos", "api", "sdk", "plugin", "agent",
    "smartphone", "phone", "iphone", "galaxy", "pixel", "xiaomi", "laptop", "tablet", "watch",
    "headset", "gpu", "cpu", "chip", "processor", "graphics card", "device", "rtx", "geforce",
    "radeon",
    "модель", "функция", "режим", "приложение", "платформа", "браузер",
    "операционная система", "api", "sdk", "агент", "смартфон", "телефон", "айфон", "ноутбук",
    "ноутбука", "ноутбуки", "ноутбуков", "планшет", "часы", "гарнитура", "видеокарта",
    "процессор", "процессора", "процессоров", "чип", "чипы", "чипов", "устройство",
)

_ADJACENT_PHRASES: tuple[str, ...] = (
    "robot", "robotics", "humanoid robot", "робот", "робототехника",
    "space telescope", "rocket launch", "satellite", "spacecraft",
    "ракета-носитель", "спутник", "космический аппарат",
    "data center", "datacenter", "дата-центр", "дата-центра", "цод",
    "semiconductor manufacturing", "chip fab", "foundry",
    "полупроводниковое производство", "infrastructure technology",
)

_PERIPHERAL_PHRASES: tuple[str, ...] = (
    # funding
    "raises", "raised", "raising", "funding round", "series a", "series b", "series c",
    "invests", "invest", "investing", "investment", "investor", "investors",
    "привлек", "привлекла", "привлекли", "раунд финансирования", "инвестирует",
    "инвестиции", "инвестор", "инвесторы", "инвестиционный", "инвестиционная",
    "инвестиционное", "инвестиционного", "инвестиционную", "инвестиционный фонд",
    # valuation / ipo / market
    "valuation", "ipo", "initial public offering", "stock market", "share price", "shares",
    "market crash", "market bubble", "bubble", "wealth fund",
    "оценка компании", "акции", "фондовый рынок", "пузырь", "фонд благосостояния",
    # revenue / earnings
    "revenue", "quarterly earnings", "earnings report", "profit",
    "выручка", "прибыль", "квартальная отчетность", "квартальные результаты",
    # employment
    "layoffs", "hiring freeze", "job cuts", "jobs report",
    "увольнения", "заморозка найма", "сокращения",
    # financing
    "financing", "лендер", "lenders", "loan", "финансирование", "кредиторы",
    # acquisition (finance-first)
    "acquires", "acquired", "acquisition", "to acquire", "приобрела", "поглощение", "купит",
    # regulation / legal
    "regulation", "regulatory", "lawsuit", "sues", "sued", "court ruling", "antitrust",
    "legal battle", "регулирование", "регулирования", "регулированию", "иск",
    "антимонопольное", "антимонопольный", "антимонопольного", "антимонопольным",
    "судебное разбирательство",
    # trade / policy
    "tariff", "tariffs", "export restrictions", "export controls", "sanctions",
    "тариф", "экспортные ограничения", "санкции",
    # housing / wealth economic context
    "housing frenzy", "housing market", "housing prices",
)

_MAJOR_IMPACT_PHRASES: tuple[str, ...] = (
    "landmark antitrust", "landmark ruling", "landmark court ruling", "antitrust ruling",
    "forced to change", "forced to divest", "force divestiture", "could force",
    "ordered to divest", "must divest", "to divest", "breakup", "break up",
    "blocked by regulators", "regulators block", "court orders", "export ban", "chip ban",
    "banned from selling", "export restrictions on",
    "историческое антимонопольное", "обязали разделить", "запрет на экспорт",
    "заблокировали сделку",
)

_MAJOR_IMPACT_COMPANIES: tuple[str, ...] = (
    "meta", "apple", "google", "alphabet", "amazon", "microsoft", "openai", "nvidia",
    "amd", "asml", "anthropic", "instagram", "whatsapp",
)

_OUT_OF_SCOPE_PHRASES: tuple[str, ...] = (
    "has died", "dies at", "death of", "умер", "скончал",
    "universal health coverage", "health coverage", "healthcare spending",
    "medicaid", "medicare", "здравоохранение",
    "shareholder dispute", "boardroom dispute", "boardroom row",
)


def _compile(phrases: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(phrase) for phrase in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternation})\b")


_CORE_SELF_SUFFICIENT_PATTERN = _compile(_CORE_SELF_SUFFICIENT_PHRASES)
_GENERIC_ACTION_VERB_PATTERN = _compile(_GENERIC_ACTION_VERB_PHRASES)
_PRODUCT_OBJECT_PATTERN = _compile(_PRODUCT_OBJECT_PHRASES)
_ADJACENT_PATTERN = _compile(_ADJACENT_PHRASES)
_PERIPHERAL_PATTERN = _compile(_PERIPHERAL_PHRASES)
_MAJOR_IMPACT_PATTERN = _compile(_MAJOR_IMPACT_PHRASES)
_MAJOR_IMPACT_COMPANY_PATTERN = _compile(_MAJOR_IMPACT_COMPANIES)
_OUT_OF_SCOPE_PATTERN = _compile(_OUT_OF_SCOPE_PHRASES)


def _normalize(text: str) -> str:
    # Real backtest data (Databricks funding story, RU variant) showed "ё" vs "е" spelling
    # variance defeating exact keyword matches ("привлёк" vs the keyword list's "привлек") -
    # both spellings are common in real RU sources, so both must resolve identically.
    normalized = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    return " ".join(normalized.split())


def _earliest_match_start(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return match.start() if match else None


def _core_match_start(text: str) -> int | None:
    """Earliest CORE-justifying position in `text`, or None. A self-sufficient phrase (already
    names a concrete product/tech object, e.g. "security update") always counts. A generic
    action verb (launches/releases/...) only counts when `_PRODUCT_OBJECT_PHRASES` also matches
    somewhere in `text` - the object confirms the verb's subject is a product/tech thing, never
    the reverse (a bare object match with no verb never grants CORE by itself)."""
    self_sufficient = _earliest_match_start(_CORE_SELF_SUFFICIENT_PATTERN, text)
    verb_match = _GENERIC_ACTION_VERB_PATTERN.search(text)
    generic = (
        verb_match.start()
        if verb_match is not None and _PRODUCT_OBJECT_PATTERN.search(text) is not None
        else None
    )
    candidates = [position for position in (self_sufficient, generic) if position is not None]
    return min(candidates) if candidates else None


def _subject_family(text: str) -> str | None:
    positions = {
        CORE: _core_match_start(text),
        ADJACENT: _earliest_match_start(_ADJACENT_PATTERN, text),
        PERIPHERAL: _earliest_match_start(_PERIPHERAL_PATTERN, text),
    }
    found = {family: position for family, position in positions.items() if position is not None}
    if not found:
        return None
    return min(found, key=lambda family: found[family])


def _has_major_impact_signal(text: str) -> bool:
    if _MAJOR_IMPACT_PATTERN.search(text) is None:
        return False
    return _MAJOR_IMPACT_COMPANY_PATTERN.search(text) is not None


def classify_editorial_relevance(title: str, content: str | None = None) -> EditorialRelevanceDecision:
    """Pure, deterministic. Identical (title, content) always produces an identical decision.

    `content` is only consulted (first `_CONTENT_SCAN_CHARS` characters) when the title alone
    carries no keyword evidence - the title is the primary subject signal for every headline-
    style example this module was calibrated against."""
    normalized_title = _normalize(title)
    normalized_content = _normalize(content[:_CONTENT_SCAN_CHARS]) if content else ""
    combined = f"{normalized_title} {normalized_content}".strip()

    out_of_scope_hit = _OUT_OF_SCOPE_PATTERN.search(combined) is not None
    major_impact = _has_major_impact_signal(combined)
    family = _subject_family(normalized_title) or _subject_family(normalized_content)

    if out_of_scope_hit and family is None and not major_impact:
        return EditorialRelevanceDecision(
            tier=OUT_OF_SCOPE,
            rank_adjustment=_OUT_OF_SCOPE_RANK_ADJUSTMENT,
            major_impact_override=False,
            reason="unambiguous non-tech topic, no product/tech/economic-tech evidence found",
        )

    if major_impact:
        return EditorialRelevanceDecision(
            tier=PERIPHERAL,
            rank_adjustment=_MAJOR_IMPACT_OVERRIDE_RANK_ADJUSTMENT,
            major_impact_override=True,
            reason="major-impact legal/regulatory signal against a major tech company",
        )

    if family == CORE:
        return EditorialRelevanceDecision(
            tier=CORE, rank_adjustment=_CORE_RANK_ADJUSTMENT, major_impact_override=False,
            reason="product/tech action phrase is the earliest subject signal",
        )
    if family == ADJACENT:
        return EditorialRelevanceDecision(
            tier=ADJACENT, rank_adjustment=_ADJACENT_RANK_ADJUSTMENT, major_impact_override=False,
            reason="adjacent tech-relevant subject signal (robotics/space/data center/semiconductor)",
        )
    if family == PERIPHERAL:
        return EditorialRelevanceDecision(
            tier=PERIPHERAL, rank_adjustment=_PERIPHERAL_RANK_ADJUSTMENT, major_impact_override=False,
            reason="funding/economic/regulatory subject signal, no stronger product/tech action phrase present",
        )

    return EditorialRelevanceDecision(
        tier=ADJACENT, rank_adjustment=_NEUTRAL_RANK_ADJUSTMENT, major_impact_override=False,
        reason="no editorial-relevance keyword evidence - neutral default",
    )
