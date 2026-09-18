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

_CONTENT_SCAN_CHARS = 800


@dataclass(frozen=True)
class EditorialRelevanceDecision:
    tier: str
    rank_adjustment: int
    major_impact_override: bool
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
    "regulation", "regulatory", "lawsuit", "sues", "sued", "court ruling", "antitrust",
    "criminal probe", "criminal investigation",
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


_VIRAL_TECH_STRONG: tuple[str, ...] = (
    "smartphone", "iphone", "galaxy", "pixel", "laptop", "wearable", "headset", "robot",
    "robotics", "prototype", "gadget", "device", "hardware", "chip", "gpu", "game physics",
    "modding", "developer project", "github project", "ai model", "ai feature",
    "artificial intelligence", "llm", "смартфон", "ноутбук", "гаджет", "устройство",
    "прототип", "робот", "робототехника", "модель ии", "ии-модель", "ии-модели",
    "функция ии", "игровая физика",
    "модификация", "проект разработчика", "сбой сети", "network outage", "outage",
)
_VIRAL_TECH_GENERAL: tuple[str, ...] = (
    "software", "app", "api", "browser", "internet", "technology", "технолог", "приложение",
    "браузер", "интернет", "алгоритм", "нейросет", "искусственный интеллект", "gaming",
    "valheim", "minecraft",
)
_STRONG_SURPRISE: tuple[str, ...] = (
    "year was 2006", "year is 2006", "decided the year", "without downloading a single mod",
    "without a mod", "unexpected", "accidentally", "by mistake", "bizarre", "weird",
    "strange", "absurd", "uncanny", "record-breaking bug", "believed it was", "believes it is",
    "оказался в 2006", "решила, что сейчас", "без единого мода", "без модов", "случайно",
    "неожидан", "странн", "абсурд", "необычн", "перепутал", "считала, что",
)
_MODERATE_SURPRISE: tuple[str, ...] = (
    "prototype", "experiment", "demo", "bug", "glitch", "failure", "outage", "trick",
    "hack", "customize", "color-coded", "creeper", "прототип", "эксперимент", "демо",
    "ошибка", "баг", "сбой", "трюк", "лайфхак", "самодельн",
)
_HUMOR_SIGNALS: tuple[str, ...] = (
    "decided the year", "year was 2006", "without downloading a single mod", "creeper",
    "bizarre", "absurd", "ridiculous", "решила, что сейчас", "без единого мода", "абсурд",
    "нелеп", "смешн",
)
_CREATOR_SHARE_SIGNALS: tuple[str, ...] = (
    "developer project", "github project", "built", "created", "customize", "modding",
    "experiment", "demo", "prototype", "проект разработчика", "создал", "собрал", "мод",
    "эксперимент", "демо", "прототип",
)


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


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
) -> PreGenerationEditorialDecision:
    relevance = classify_editorial_relevance(title, content)
    effective = (
        standard_score + relevance.rank_adjustment if standard_score is not None else None
    )
    standard_eligible = (
        standard_score is not None
        and standard_score >= standard_threshold
        and relevance.tier != OUT_OF_SCOPE
        and effective is not None
        and effective >= standard_threshold
    )
    viral = score_viral_tech(
        title, content, source_reliability=source_reliability, published_at=published_at, now=now,
        has_visual_proof=has_visual_proof, views_count=views_count,
        forwards_count=forwards_count, reactions_count=reactions_count,
        primary_evidence=primary_evidence, credible_confirmations=credible_confirmations,
    )
    viral_eligible = relevance.tier != OUT_OF_SCOPE and viral.eligible
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
        effective_standard_score=effective,
        standard_eligible=standard_eligible,
        viral=viral,
        final_eligible=final_eligible,
        selection_path=path,
        rank_score=rank_score,
        reason=(
            f"{path}: standard={standard_score}, effective={effective}, relevance={relevance.tier}; "
            f"viral={viral.total} ({viral.reason})"
        ),
    )
