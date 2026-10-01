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
from datetime import UTC, datetime, timedelta

CORE = "CORE"
ADJACENT = "ADJACENT"
PERIPHERAL = "PERIPHERAL"
OUT_OF_SCOPE = "OUT_OF_SCOPE"

_CORE_RANK_ADJUSTMENT = 10
_ADJACENT_RANK_ADJUSTMENT = 3
_NEUTRAL_RANK_ADJUSTMENT = 0
_PERIPHERAL_RANK_ADJUSTMENT = -25
_MAJOR_IMPACT_OVERRIDE_RANK_ADJUSTMENT = 5
_OUT_OF_SCOPE_RANK_ADJUSTMENT = -1000

# STANDARD remains anchored to the configured global threshold. A narrowly positive Pulse-fit
# classification may rescue a candidate by at most the existing ADJACENT +3 adjustment. This is
# enough for the observed 68 -> 78 CORE gadget/AI case, lets a genuinely positive ADJACENT signal
# affect eligibility, and prevents CORE's larger +10 bonus from pulling weak raw scores into
# STANDARD. PERIPHERAL major-impact overrides deliberately do not use this rescue path.
_STANDARD_EDITORIAL_RESCUE_MAX_DEFICIT = _ADJACENT_RANK_ADJUSTMENT

_CONTENT_SCAN_CHARS = 800


@dataclass(frozen=True)
class EditorialRelevanceDecision:
    tier: str
    rank_adjustment: int
    major_impact_override: bool
    reason: str


@dataclass(frozen=True)
class ProductQualityDecision:
    """KAGE product-taste signal, separate from generic newsworthiness.

    This remains deterministic and evidence-conservative: it only classifies wording already
    present in the title/lead. It does not invent an angle, infer a capability, or impose category
    quotas. The signal answers whether the candidate exposes a concrete user-facing change,
    practical AI use, gaming/geek premise, or genuinely shareable internet-tech premise.
    """

    lane: str
    rank_adjustment: int
    target_profile: bool
    business_noise: bool
    interesting_change: bool
    reason: str


@dataclass(frozen=True)
class ViralTechBreakdown:
    tech_relevance: int
    surprise_weirdness: int
    humor_meme_potential: int
    shareability: int
    visual_proof: int
    velocity_spread: int
    verifiability: int
    freshness_penalty: int = 0

    def __post_init__(self) -> None:
        bounds = {
            "tech_relevance": (self.tech_relevance, 20),
            "surprise_weirdness": (self.surprise_weirdness, 20),
            "humor_meme_potential": (self.humor_meme_potential, 15),
            "shareability": (self.shareability, 15),
            "visual_proof": (self.visual_proof, 10),
            "velocity_spread": (self.velocity_spread, 10),
            "verifiability": (self.verifiability, 10),
        }
        for name, (value, maximum) in bounds.items():
            if not 0 <= value <= maximum:
                raise ValueError(f"{name} must be between 0 and {maximum}")
        if self.freshness_penalty not in (0, -25):
            raise ValueError("freshness_penalty must be 0 or -25")

    @property
    def total(self) -> int:
        return max(0, min(100, (
            self.tech_relevance + self.surprise_weirdness + self.humor_meme_potential
            + self.shareability + self.visual_proof + self.velocity_spread
            + self.verifiability + self.freshness_penalty
        )))


@dataclass(frozen=True)
class ViralTechDecision:
    breakdown: ViralTechBreakdown
    eligible: bool
    fast_lane: bool
    stale: bool
    reason: str

    @property
    def total(self) -> int:
        return self.breakdown.total


@dataclass(frozen=True)
class PreGenerationEditorialDecision:
    standard_score: int | None
    editorial_relevance: EditorialRelevanceDecision
    product_quality: ProductQualityDecision
    effective_standard_score: int | None
    standard_eligible: bool
    viral: ViralTechDecision
    final_eligible: bool
    selection_path: str
    rank_score: int
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
    "layoffs", "hiring freeze", "job cuts", "jobs report", "workers to strike",
    "collective bargaining", "labour dispute", "labor dispute",
    "увольнения", "заморозка найма", "сокращения",
    # financing
    "financing", "лендер", "lenders", "loan", "финансирование", "кредиторы",
    # acquisition (finance-first)
    "acquires", "acquired", "acquisition", "to acquire", "приобрела", "поглощение", "купит",
    # regulation / legal
    "regulation", "regulatory", "regulator", "regulators", "regulatory framework",
    "lawsuit", "sues", "sued", "court ruling", "antitrust",
    "criminal probe", "criminal investigation",
    "legal battle", "регулирование", "регулирования", "регулированию", "регулятор",
    "settlement", "lawsuit settlement", "submit claims", "claim for a payout",
    "unit sales", "sales rose", "sales increased", "market share",
    "регуляторы", "иск",
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

_AI_SUBJECT_PHRASES: tuple[str, ...] = (
    "ai", "artificial intelligence", "llm", "chatgpt", "claude", "gemini", "copilot",
    "sora", "grok", "openai", "anthropic", "нейросет*", "искусственный интеллект",
    "ии-модель", "модель ии", "алиса ai",
)
_PRACTICAL_AI_PHRASES: tuple[str, ...] = (
    "can now", "lets you", "allows users", "available to try", "try it", "workflow",
    "don't need", "without its hardware", "operates locally", "use natural language",
    "generates", "image generation", "video generation", "image editing", "video editing",
    "code generation", "voice mode", "live translation", "reasoning mode", "open weights",
    "можно попробовать", "можно использовать", "позвол*", "умеет", "агент", "агенты",
    "генерац*", "редактир*", "перевод", "голосовой режим", "открыла веса", "открыл веса",
    "открытые веса", "рабочий процесс",
)
_GADGET_PHRASES: tuple[str, ...] = (
    "smartphone", "phone", "iphone", "galaxy", "pixel", "xiaomi", "laptop", "tablet",
    "smartwatch", "watch", "earbuds", "headset", "console", "camera", "drone", "wearable",
    "смартфон", "телефон", "айфон", "ноутбук", "планшет", "часы", "наушники",
    "гарнитура", "консоль", "камера", "дрон", "гаджет",
)
_MATERIAL_CHANGE_PHRASES: tuple[str, ...] = (
    "new feature", "adds support", "gains support", "first test", "hands-on", "hands on",
    "review", "after 30 days", "what i learned after",
    "firmware", "security update", "fixes", "battery", "camera", "foldable", "rollable",
    "dual-screen", "form factor", "limitation", "upgrade", "now supports", "can now",
    "новая функция", "добавила функцию", "добавил функцию", "поддержк*", "первый тест",
    "обзор", "прошивк*", "исправ*", "батаре*", "камер*", "складн*", "форм-фактор",
    "ограничен*", "обновлен*", "теперь умеет", "теперь можно",
)
_GAMING_GEEK_PHRASES: tuple[str, ...] = (
    "game", "games", "gaming", "gta", "steam", "playstation", "xbox", "nintendo",
    "console", "mods", "modding", "speedrun", "game developer", "comic", "sci-fi",
    "science fiction", "adaptation", "anime", "manga", "fantasy", "minecraft", "valheim",
    "cs2", "counter-strike", "league of legends", "riot", "halo", "resident evil",
    "игр*", "steam", "playstation", "xbox", "nintendo", "консол*", "моды", "моддинг", "спидран*",
    "комикс*", "фантаст*", "экранизац*", "аниме", "манга",
)
_USER_SOFTWARE_PRODUCT_PHRASES: tuple[str, ...] = (
    "app", "apps", "android", "ios", "windows", "macos", "browser", "chrome", "firefox",
    "maps", "messenger", "whatsapp", "telegram", "discord", "spotify", "youtube",
    "приложен*", "android", "ios", "windows", "браузер", "карты", "мессенджер",
)
_USER_SOFTWARE_CHANGE_PHRASES: tuple[str, ...] = (
    "adds", "added", "gets", "got", "brings", "links", "removes", "drops", "fixes",
    "gives you", "giving you", "lets you", "reshape", "summarizes", "summary",
    "now supports", "can now", "rolls out", "добавил*", "получил*", "убрал*", "удалил*",
    "исправил*", "теперь поддерживает", "теперь можно",
)
_VIRAL_INTERNET_PHRASES: tuple[str, ...] = (
    "bizarre", "weird", "absurd", "ridiculous", "glitch", "bug", "accidentally",
    "by mistake", "refuses to", "won't die", "still going", "internet saga", "meme",
    "strange gadget", "unexpected behavior", "what the hell", "goes viral", "went viral",
    "remixed", "phonk", "exploit", "zero-day", "hijack", "accent, no matter", "fired for using ai",
    "actually made by humans", "случайн*", "странн*",
    "абсурд*", "нелеп*", "смешн*", "баг", "глюк", "отказывается", "до сих пор",
    "интернет-саг", "мем", "неожиданное поведение",
)
_GENERIC_ANNOUNCEMENT_PHRASES: tuple[str, ...] = (
    "will release", "plans to release", "coming next year", "expected next year", "unveil",
    "unveils", "announce", "announces", "launch", "launches", "анонсировала", "анонсировал",
    "представит", "выйдет в следующем году", "планирует выпустить",
)
_CONCRETE_LEAD_PHRASES: tuple[str, ...] = (
    "replaceable", "battery", "lens", "lenses", "support", "available", "can now",
    "lets you", "allows", "fixes", "bug", "notification", "download", "locally",
    "tested", "test", "feature", "сменн*", "батаре*", "можно", "исправ*", "баг",
)
_DETAIL_PROMISE_PHRASES: tuple[str, ...] = (
    "review", "after 30 days", "what i learned", "picks", "pros and cons",
    "best games", "how to", "where can", "details surface", "new details",
    "обзор", "лучшие игры", "плюсы и минусы",
)
_EDITORIAL_PROMO_PHRASES: tuple[str, ...] = (
    "tickets", "save up to", "register by", "second pass", "agenda revealed",
    "conference", "summit", "promo code", "on sale", "deal", "deals", "discount",
    "off deal", "% off", "upgrade your", "скидк* на билет", "распродаж*",
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


def classify_product_quality(
    title: str, content: str | None = None, *, product_loop: bool = False,
) -> ProductQualityDecision:
    """Classify KAGE product fit without manufacturing facts or enforcing category quotas."""
    normalized_title = _normalize(title)
    normalized_lead = _normalize((content or "")[:_CONTENT_SCAN_CHARS])
    combined = f"{normalized_title} {normalized_lead}".strip()

    relevance = classify_editorial_relevance(title, content)
    # The product lane must be visible in the headline itself. Feed summaries often contain
    # navigation/related-story boilerplate; letting an incidental body token decide the lane
    # recreated the exact generic-feed problem this layer is meant to solve. Once the headline
    # establishes AI/gadget subject, the short lead may still confirm its practical change.
    ai_as_context = re.search(
        r"\b(?:to combat|against|amid|because of|due to)\s+ai(?:\b|-)", normalized_title
    ) is not None
    is_ai = _has_any(normalized_title, _AI_SUBJECT_PHRASES) and not ai_as_context
    model_launch = is_ai and _has_any(normalized_title, _GENERIC_ANNOUNCEMENT_PHRASES)
    headline_user_action = _has_any(
        normalized_title,
        ("can now", "lets you", "allows users", "you can", "try", "edit", "generate",
         "create", "build", "don't need", "doesn't need", "no longer needs"),
    )
    practical_ai = (
        is_ai and _has_any(combined, _PRACTICAL_AI_PHRASES)
        and (not model_launch or headline_user_action)
    )
    ai_capability = model_launch and _has_any(
        normalized_lead,
        ("faster", "more accurate", "lower latency", "coding", "computer use",
         "image editing", "video generation", "local inference", "longer context"),
    )
    title_gadget = _has_any(normalized_title, _GADGET_PHRASES)
    material_change = _has_any(normalized_title, _MATERIAL_CHANGE_PHRASES)
    gadget = title_gadget or (
        material_change and _has_any(normalized_lead, _GADGET_PHRASES)
    )
    user_software_change = (
        _has_any(normalized_title, _USER_SOFTWARE_PRODUCT_PHRASES)
        and _has_any(normalized_title, _USER_SOFTWARE_CHANGE_PHRASES)
    )
    thin_future_software = (
        product_loop and user_software_change
        and _has_any(normalized_title, ("will soon", "upcoming update", "coming soon", "появится скоро"))
        and len(re.findall(r"\w+", normalized_lead)) < 22
    )
    gaming_geek = _has_any(normalized_title, _GAMING_GEEK_PHRASES)
    viral_internet = _has_any(normalized_title, _VIRAL_INTERNET_PHRASES)
    peripheral_match = _PERIPHERAL_PATTERN.search(combined)
    action_match = _GENERIC_ACTION_VERB_PATTERN.search(normalized_title)
    product_action_leads = (
        action_match is not None
        and _PRODUCT_OBJECT_PATTERN.search(normalized_title) is not None
        and (
            peripheral_match is None
            or action_match.start() < peripheral_match.start()
        )
    )
    business_noise = (
        not relevance.major_impact_override
        and peripheral_match is not None
        and not product_action_leads
        and not material_change
        and not viral_internet
    )
    if product_loop:
        # The opt-in product loop judges the *change*, not merely the topic. A gaming
        # noun or a meme is not a publication reason; conversely a serious space or
        # product milestone is not weak just because it is neither playful nor viral.
        def verdict(lane: str, adjustment: int, reason: str, *, target: bool = False,
                    noise: bool = False) -> ProductQualityDecision:
            return ProductQualityDecision(
                lane=lane, rank_adjustment=adjustment, target_profile=target,
                business_noise=noise, interesting_change=target, reason=reason,
            )

        if _has_any(normalized_title, _EDITORIAL_PROMO_PHRASES) or _has_any(
            normalized_lead, ("save up to", "second pass", "ticket discount", "promo code")
        ) or re.search(r"\bsave\s+\$\d|\brecord[- ]low\b|\bdrops? below\s+\$", normalized_title):
            return verdict("PROMOTION", -35, "discount or event promotion is the payoff", noise=True)
        if _has_any(normalized_title, ("podcast:", "daily:", "the macrumors show:", "show:", "interview:")):
            return verdict("COMMENTARY", -28, "interview or show recap is not itself a technology change")
        # A forecast in the headline can coexist with a real launch in the
        # source lead. Judge the evidenced product event before rejecting the
        # executive comparison; do not let a bare aspiration pass this guard.
        evidenced_product_launch = (
            _has_any(normalized_lead, (
                "is officially unveiling it today", "has launched", "launched today",
                "has released", "released today", "is rolling out", "rolls out",
                "now available", "available today",
            ))
            and _has_any(normalized_lead, (
                "app", "feature", "product", "device", "model", "software",
            ))
        )
        if _has_any(normalized_title, ("thinks its", "believes its", "will be as influential", "could be as influential")) and not evidenced_product_launch:
            return verdict("CORPORATE_CLAIM", -25, "company expectation rather than an evidenced product change")
        if _has_any(normalized_title, (
            "wishlist", "wish list", "most anticipated games", "gaming show", "show lineup",
            "returns december", "returns november", "event lineup", "staff picks",
        )):
            return verdict("THIN_GAMING", -30, "staff list or future show lineup without a game change")
        if thin_future_software:
            return verdict("THIN_SOFTWARE", -22, "future software promise lacks a concrete current change")
        if _has_any(normalized_title, (
            "leaked", "per leak", "upcoming", "may soon", "could", "rumor", "working on",
            "will release", "next year", "plans to release",
        )) and not _has_any(
            normalized_title, ("already available", "now available", "released", "rolling out")
        ):
            return verdict("UNRELEASED_PRODUCT", -22, "unreleased or speculative product detail")
        if relevance.major_impact_override:
            return verdict("MAJOR_IMPACT", 18, "exceptional legal or business action with material technology impact", target=True)
        if business_noise:
            return verdict("BUSINESS_NOISE", -35, "routine financial, legal or corporate premise", noise=True)

        space_subject = _has_any(normalized_title, (
            "spacex", "starship", "rocket", "spacecraft", "satellite", "orbital", "space telescope",
            "mars rover", "rover", "ракета", "космический аппарат", "спутник",
        ))
        completed_milestone = _has_any(normalized_title, (
            "successful", "successfully", "completed", "first orbital", "flight test",
            "launch rehearsal", "landed", "launched", "reached orbit", "first flight",
            "turned", "built", "tested", "успешн*", "завершил*", "первый полет", "вышел на орбиту",
        ))
        if space_subject and completed_milestone:
            return verdict("MAJOR_TECH_MILESTONE", 22, "concrete space or hardware milestone", target=True)

        product_incident = _has_any(normalized_title, (
            "bug", "cellular issues", "connectivity issues", "unable to", "preventing users",
            "not working", "outage", "service disruption",
        )) and _has_any(normalized_title, (
            "google photos", "iphone", "android", "app", "browser", "windows", "network",
            "phone", "pixel", "service", "приложение", "телефон",
        ))
        if product_incident:
            return verdict("PRODUCT_INCIDENT", 18, "concrete user-facing product breakage", target=True)

        explicit_tech = (
            is_ai or gadget or gaming_geek or user_software_change or space_subject
            or _has_any(normalized_title, (
                "software", "app", "browser", "internet", "algorithm", "robot", "chip",
                "hack", "breach", "network", "platform", "device", "hardware", "google photos",
                "приложение", "браузер", "интернет", "робот", "чип", "устройств*",
            ))
        )
        if viral_internet and explicit_tech:
            return verdict("VIRAL_TECH", 17, "shareable event has an explicit technology subject", target=True)
        if viral_internet and not explicit_tech:
            return verdict("NON_TECH_VIRAL", -35, "viral or political reaction has no technology event")

        if is_ai and _has_any(normalized_title, (
            "cheat", "collusion", "collude", "pretends", "actually humans",
            "made by humans", "fired for using ai", "unexpected behavior",
        )):
            return verdict("UNUSUAL_AI", 17, "concrete surprising AI behavior with an explicit tech subject", target=True)

        ai_subject = is_ai or _has_any(normalized_title, ("llms", "language models")) or (
            _has_any(normalized_lead, ("ai chatbot", "ai assistant", "ai model"))
            and len(set(re.findall(r"[a-z]{4,}", normalized_title)) &
                    set(re.findall(r"[a-z]{4,}", normalized_lead))) >= 2
        )
        ai_feature = ai_subject and _has_any(normalized_title, (
            "adds", "added", "introduces", "introduced", "rolls out", "gets", "gains",
            "launches", "can now", "new", "brings", "offers", "ships", "release",
            "gives", "makes", "let you", "lets you", "unveils",
        )) and _has_any(normalized_title, (
            "agent", "agents", "avatar", "avatars", "coding", "code", "image", "video",
            "voice", "search", "memory", "integration", "workflow", "feature", "mode",
            "chat", "app", "model", "llm", "filesystem", "game tools", "games", "tools",
            "генерац*", "агент*", "функци*",
        ))
        named_model_release = ai_subject and _has_any(normalized_title, (
            "launches", "released", "releases", "debuts", "rolls out", "представил*",
        )) and re.search(r"\b(?:gpt|gemini|claude|grok|llama|qwen|deepseek)[ -]?[0-9]+(?:\.[0-9]+)?\b", normalized_title) is not None
        if ai_feature or named_model_release or practical_ai or ai_capability:
            return verdict("AI_PRODUCT", 18, "concrete AI model, feature or workflow change", target=True)

        product_subject = gadget or user_software_change or _has_any(normalized_title, (
            "smart glasses", "ai glasses", "glasses", "google messages", "pixel weather",
            "widget", "grapheneos", "phone", "wearable", "headphones", "earbuds",
            "gaming pc", "handheld", "steam deck", "smart lock", "google photos",
        ))
        product_change = material_change or user_software_change or _has_any(normalized_title, (
            "supports", "support for", "confirmed to support", "new", "rolls out",
            "redesign", "versus", " vs.", " vs ", "compare", "comparison", "launches",
            "released", "available", "adds", "gets", "update", "upgrades", "brings",
            "releases", "unfurl", "changes shape", "opens as", "expands when",
            "issues", "not working", "preventing", "first uwb",
        ))
        if product_subject and product_change:
            return verdict("CONSUMER_PRODUCT", 19, "concrete device or user-software change", target=True)

        gaming_subject = gaming_geek or _has_any(normalized_title, (
            "call of duty", "warzone", "arc raiders", "gameplay", "players", "game", "games",
        ))
        gaming_change = _has_any(normalized_title, (
            "adds", "adding", "gets", "launches", "released", "releases", "update",
            "patch", "new mode", "new feature", "button to", "players can", "giving players",
            "lets players", "changes", "fixes", "available to play", "removes",
            "unveils", "game tools", "build games",
        ))
        if gaming_subject and gaming_change:
            return verdict("GAMING_CHANGE", 19, "specific playable game or gaming-product change", target=True)
        if gaming_subject:
            return verdict("GAMING_CONTEXT", -18, "gaming subject without a specific newsworthy change")

        if _has_any(normalized_title, (
            "hack", "hacked", "breach", "outage", "zero-day", "0-day",
            "vulnerability", "compromised", "cyberattack",
        )) and _has_any(
            normalized_title, (
                "software", "system", "data", "network", "app", "fbi", "service",
                "database", "accounts", "assistant", "agent", "platform", "hacking",
            )
        ):
            return verdict("MAJOR_TECH_EVENT", 16, "concrete cybersecurity or service event", target=True)
        if is_ai:
            return verdict("GENERAL_AI", -12, "AI mention without a concrete model or product change")
        return verdict("GENERAL_TECH", -15, "no concrete KAGE technology change established")
    if _has_any(normalized_title, _EDITORIAL_PROMO_PHRASES) or _has_any(
        normalized_lead, ("save up to", "second pass", "ticket discount", "promo code")
    ):
        return ProductQualityDecision(
            lane="PROMOTION", rank_adjustment=-35, target_profile=False,
            business_noise=True, interesting_change=False,
            reason="event or ticket promotion is the payoff, not a user-facing technology story",
        )
    if business_noise:
        return ProductQualityDecision(
            lane="BUSINESS_NOISE", rank_adjustment=-35, target_profile=False,
            business_noise=True, interesting_change=False,
            reason="finance/regulation/corporate subject without exceptional user impact",
        )

    if thin_future_software:
        return ProductQualityDecision(
            lane="THIN_SOFTWARE", rank_adjustment=-22, target_profile=False,
            business_noise=False, interesting_change=False,
            reason="future software change has only a headline-level behavior, not enough substance to reward opening",
        )

    if _has_any(normalized_title, ("release candidate", "release candidates", "rcs", "rc 1")):
        return ProductQualityDecision(
            lane="GENERIC_TECH", rank_adjustment=-20, target_profile=False,
            business_noise=False, interesting_change=False,
            reason="pre-release build without a concrete user-facing change",
        )

    if viral_internet and (is_ai or gadget or gaming_geek or relevance.tier in (CORE, ADJACENT)):
        return ProductQualityDecision(
            lane="VIRAL_INTERNET", rank_adjustment=16, target_profile=True,
            business_noise=False, interesting_change=True,
            reason="supported weird/shareable technology premise is explicit in the candidate",
        )
    if gaming_geek:
        return ProductQualityDecision(
            lane="GAMING_GEEK", rank_adjustment=14, target_profile=True,
            business_noise=False, interesting_change=True,
            reason="gaming/geek subject is explicit in the candidate",
        )
    if practical_ai:
        return ProductQualityDecision(
            lane="PRACTICAL_AI", rank_adjustment=14, target_profile=True,
            business_noise=False, interesting_change=True,
            reason="concrete AI capability or user workflow is explicit in the candidate",
        )
    if ai_capability:
        return ProductQualityDecision(
            lane="AI_CAPABILITY", rank_adjustment=6, target_profile=True,
            business_noise=False, interesting_change=True,
            reason="model launch includes a concrete speed, creation or workflow capability",
        )
    if gadget and material_change:
        return ProductQualityDecision(
            lane="GADGETS", rank_adjustment=12, target_profile=True,
            business_noise=False, interesting_change=True,
            reason="gadget story exposes a concrete feature, test, limitation or usage change",
        )
    if user_software_change:
        return ProductQualityDecision(
            lane="GADGETS", rank_adjustment=12, target_profile=True,
            business_noise=False, interesting_change=True,
            reason="user-facing software story exposes a concrete product behavior change",
        )
    if gadget and _has_any(normalized_title, _GENERIC_ANNOUNCEMENT_PHRASES):
        return ProductQualityDecision(
            lane="GENERIC_TECH", rank_adjustment=-20, target_profile=False,
            business_noise=False, interesting_change=False,
            reason="generic future product announcement without an explicit interesting change",
        )
    if is_ai:
        return ProductQualityDecision(
            lane="GENERAL_AI", rank_adjustment=-15, target_profile=False,
            business_noise=False, interesting_change=False,
            reason="AI is the subject but no practical capability or user use case is explicit",
        )
    return ProductQualityDecision(
        lane="GENERAL_TECH", rank_adjustment=-15, target_profile=False,
        business_noise=False, interesting_change=material_change,
        reason="technology candidate without a strong KAGE product-profile signal",
    )


_VIRAL_TECH_STRONG: tuple[str, ...] = (
    "smartphone", "iphone", "galaxy", "pixel", "laptop", "wearable", "headset", "robot",
    "robotics", "prototype", "gadget", "device", "hardware", "chip", "gpu", "game physics",
    "modding", "developer project", "github project", "ai model", "ai feature",
    "artificial intelligence", "llm", "смартфон", "ноутбук", "гаджет", "устройство",
    "прототип", "робот", "робототехника", "модель ии", "ии-модель", "ии-модели",
    "функция ии", "игровая физика",
    "модификация", "проект разработчика", "сбой сети", "network outage", "outage",
    "steam", "playstation", "xbox", "nintendo", "console", "speedrun", "game developer",
    "консоль", "спидран", "разработчик игры",
)
_VIRAL_TECH_GENERAL: tuple[str, ...] = (
    "software", "app", "api", "browser", "internet", "technology", "технолог*", "приложение",
    "браузер", "интернет", "алгоритм", "нейросет*", "искусственный интеллект", "gaming",
    "valheim", "minecraft",
)
_STRONG_SURPRISE: tuple[str, ...] = (
    "year was 2006", "year is 2006", "decided the year", "without downloading a single mod",
    "without a mod", "unexpected", "accidentally", "by mistake", "bizarre", "weird",
    "strange", "absurd", "uncanny", "record-breaking bug", "believed it was", "believes it is",
    "оказался в 2006", "решила, что сейчас", "без единого мода", "без модов", "случайно",
    "неожидан*", "странн*", "абсурд*", "необычн*", "перепутал", "считала, что",
    "won't die", "still going", "internet saga", "refuses to", "what the hell",
    "до сих пор", "интернет-сага", "отказывается",
)
_MODERATE_SURPRISE: tuple[str, ...] = (
    "prototype", "experiment", "demo", "bug", "glitch", "failure", "outage", "trick",
    "hack", "customize", "color-coded", "creeper", "прототип", "эксперимент", "демо",
    "ошибка", "баг", "сбой", "трюк", "лайфхак", "самодельн*", "glitch",
    "unexpected behavior", "глюк", "неожиданное поведение",
)
_HUMOR_SIGNALS: tuple[str, ...] = (
    "decided the year", "year was 2006", "without downloading a single mod", "creeper",
    "bizarre", "absurd", "ridiculous", "решила, что сейчас", "без единого мода", "абсурд",
    "нелеп*", "смешн*", "internet saga", "what the hell", "интернет-сага",
)
_CREATOR_SHARE_SIGNALS: tuple[str, ...] = (
    "developer project", "github project", "built", "created", "customize", "modding",
    "experiment", "demo", "prototype", "проект разработчика", "создал", "собрал", "мод",
    "эксперимент", "демо", "прототип",
)


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    """Token/phrase-aware signal matching; `stem*` means a word-prefix match.

    Plain substring matching made `ai` match inside unrelated English words and short Russian
    stems match arbitrary surrounding text. Product-taste signals must be explicit, not lexical
    accidents.
    """
    for phrase in phrases:
        if phrase.endswith("*"):
            pattern = rf"(?<!\w){re.escape(phrase[:-1])}\w*"
        else:
            pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
        if re.search(pattern, text):
            return True
    return False


def source_has_publishable_detail(title: str, content: str | None) -> bool:
    """Reject RSS teasers that cannot support the promised post without further acquisition."""
    headline = _normalize(title)
    lead = _normalize((content or "")[:_CONTENT_SCAN_CHARS])
    if not lead or lead == headline:
        return False
    words = re.findall(r"\w+", lead)
    if len(words) < 5:
        return False
    if lead.startswith(('"', '“', '«')) and len(words) < 55:
        # An isolated reaction quote is not evidence for the event described by the headline.
        return False
    if _has_any(headline, _DETAIL_PROMISE_PHRASES) and not _has_any(
        lead, _CONCRETE_LEAD_PHRASES
    ):
        return False
    if len(words) < 16:
        title_terms = {
            word for word in re.findall(r"[a-zа-я0-9]+", headline)
            if len(word) >= 4 and word not in {"with", "from", "that", "this", "into", "other", "more"}
        }
        lead_terms = set(re.findall(r"[a-zа-я0-9]+", lead))
        if len(title_terms.intersection(lead_terms)) < 2 and not _has_any(
            lead, _CONCRETE_LEAD_PHRASES
        ):
            return False
    return True


def _bounded_reliability_score(source_reliability: float | None, *, primary_evidence: bool,
                               credible_confirmations: int) -> int:
    score = round(max(0.0, min(1.0, source_reliability or 0.0)) * 10)
    if primary_evidence:
        score = max(score, 9)
    elif credible_confirmations >= 2:
        score = max(score, 8)
    return min(10, score)


def score_viral_tech(
    title: str,
    content: str | None = None,
    *,
    source_reliability: float | None = None,
    published_at: datetime | None = None,
    now: datetime | None = None,
    has_visual_proof: bool = False,
    views_count: int | None = None,
    forwards_count: int | None = None,
    reactions_count: int | None = None,
    primary_evidence: bool = False,
    credible_confirmations: int = 0,
) -> ViralTechDecision:
    """Deterministic VIRAL_TECH signal evaluated before final generation.

    This deliberately uses only evidence already present on NewsEvent/NewsSource. Missing visual,
    spread or provenance evidence earns zero rather than being guessed. It is an additional
    selector signal, never a replacement for normal Scoring, Research or Quality.
    """
    normalized_title = _normalize(title)
    # Technical subject evidence may come from the short lead when a headline is terse, but the
    # social-value dimensions must be visible in the headline itself. Real Habr backtesting showed
    # that scanning a long article body for words such as "unexpected" falsely promoted ordinary
    # enterprise case studies as viral stories. A body-level incidental adjective is not a
    # stop-scroll premise and must not manufacture surprise/humor/shareability.
    tech_context = _normalize(f"{title} {(content or '')[:_CONTENT_SCAN_CHARS]}")
    strong_tech = _has_any(tech_context, _VIRAL_TECH_STRONG)
    general_tech = _has_any(tech_context, _VIRAL_TECH_GENERAL)
    gaming_creator = any(
        phrase in normalized_title
        for phrase in ("valheim", "minecraft", "modding", "color-coded", "игров")
    )
    tech = 20 if strong_tech else (16 if gaming_creator else (10 if general_tech else 0))

    strong_surprise = _has_any(normalized_title, _STRONG_SURPRISE)
    moderate_surprise = _has_any(normalized_title, _MODERATE_SURPRISE)
    surprise = 20 if strong_surprise else (10 if moderate_surprise else 0)
    humor = 10 if _has_any(normalized_title, _HUMOR_SIGNALS) else (5 if strong_surprise else 0)
    creator_signal = _has_any(normalized_title, _CREATOR_SHARE_SIGNALS)
    shareability = 15 if tech >= 10 and surprise >= 15 else (10 if tech >= 10 and creator_signal else 0)
    visual = 10 if has_visual_proof else 0

    observed_engagement = sum(v or 0 for v in (views_count, forwards_count, reactions_count))
    current = now or datetime.now(UTC)
    if observed_engagement >= 1000:
        velocity = 10
    elif observed_engagement >= 100:
        velocity = 7
    else:
        # Freshness is a separate stale-content safety gate, not evidence of velocity/spread.
        # Sources that expose no engagement metrics earn zero here rather than a fabricated boost.
        velocity = 0

    verifiability = _bounded_reliability_score(
        source_reliability, primary_evidence=primary_evidence,
        credible_confirmations=credible_confirmations,
    )
    stale = published_at is not None and current - published_at > timedelta(hours=24)
    breakdown = ViralTechBreakdown(
        tech_relevance=tech,
        surprise_weirdness=surprise,
        humor_meme_potential=humor,
        shareability=shareability,
        visual_proof=visual,
        velocity_spread=velocity,
        verifiability=verifiability,
        freshness_penalty=-25 if stale else 0,
    )
    eligible = (
        not stale and breakdown.total >= 68 and tech >= 10 and verifiability >= 6
    )
    evidence_gate = primary_evidence or credible_confirmations >= 2
    fast_lane = eligible and breakdown.total >= 80 and evidence_gate
    if stale:
        reason = "stale viral candidate blocked"
    elif tech < 10:
        reason = "viral gate failed: tech relevance below 10"
    elif verifiability < 6:
        reason = "viral gate failed: verifiability below 6"
    elif breakdown.total < 68:
        reason = "viral gate failed: total below 68"
    elif fast_lane:
        reason = "viral eligible and fast-lane evidence condition met"
    else:
        reason = "viral eligible; normal Research/Quality still required"
    return ViralTechDecision(
        breakdown=breakdown, eligible=eligible, fast_lane=fast_lane, stale=stale, reason=reason,
    )


def evaluate_pre_generation_candidate(
    *,
    title: str,
    content: str | None,
    standard_score: int | None,
    standard_threshold: int,
    source_reliability: float | None = None,
    published_at: datetime | None = None,
    now: datetime | None = None,
    has_visual_proof: bool = False,
    views_count: int | None = None,
    forwards_count: int | None = None,
    reactions_count: int | None = None,
    primary_evidence: bool = False,
    credible_confirmations: int = 0,
    require_source_detail: bool = True,
    product_loop: bool = False,
) -> PreGenerationEditorialDecision:
    relevance = classify_editorial_relevance(title, content)
    product_quality = classify_product_quality(title, content, product_loop=product_loop)
    # Existing enforced article acquisition may rescue a thin RSS teaser before Research.
    # RSS-only mode must fail closed before buying provider calls for an empty shell.
    evidence_ready = not require_source_detail or source_has_publishable_detail(title, content)
    effective = (
        standard_score + relevance.rank_adjustment + product_quality.rank_adjustment
        if standard_score is not None else None
    )
    rescue_deficit = (
        10 if product_quality.target_profile else _STANDARD_EDITORIAL_RESCUE_MAX_DEFICIT
    )
    rescue_floor = max(0, standard_threshold - rescue_deficit)
    positive_editorial_rescue = (
        standard_score is not None
        and standard_score >= rescue_floor
        and not product_quality.business_noise
        and evidence_ready
        and product_quality.rank_adjustment >= 0
        and (
            product_quality.target_profile
            or (relevance.tier in (CORE, ADJACENT) and relevance.rank_adjustment > 0)
        )
    )
    standard_eligible = (
        standard_score is not None
        and relevance.tier != OUT_OF_SCOPE
        and not product_quality.business_noise
        and evidence_ready
        and effective is not None
        and effective >= standard_threshold
        and (standard_score >= standard_threshold or positive_editorial_rescue)
    )
    viral = score_viral_tech(
        title, content, source_reliability=source_reliability, published_at=published_at, now=now,
        has_visual_proof=has_visual_proof, views_count=views_count,
        forwards_count=forwards_count, reactions_count=reactions_count,
        primary_evidence=primary_evidence, credible_confirmations=credible_confirmations,
    )
    viral_eligible = evidence_ready and relevance.tier != OUT_OF_SCOPE and viral.eligible
    final_eligible = standard_eligible or viral_eligible
    if standard_eligible and viral_eligible:
        path = "BOTH"
    elif standard_eligible:
        path = "STANDARD"
    elif viral_eligible:
        path = "VIRAL_TECH"
    else:
        path = "REJECT"
    standard_rank = effective if standard_eligible and effective is not None else -1000
    viral_rank = viral.total + (5 if viral.fast_lane else 0) if viral_eligible else -1000
    rank_score = max(standard_rank, viral_rank)
    return PreGenerationEditorialDecision(
        standard_score=standard_score,
        editorial_relevance=relevance,
        product_quality=product_quality,
        effective_standard_score=effective,
        standard_eligible=standard_eligible,
        viral=viral,
        final_eligible=final_eligible,
        selection_path=path,
        rank_score=rank_score,
        reason=(
            f"{path}: standard={standard_score}, effective={effective}, relevance={relevance.tier}, "
            f"product_lane={product_quality.lane}; evidence_ready={evidence_ready}; "
            f"viral={viral.total} ({viral.reason})"
        ),
    )
