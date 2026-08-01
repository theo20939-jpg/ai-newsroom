"""Channel/Topic Relevance (Phase 17 M2): deterministic, shadow-only article-level topic
classification and channel-fit assessment (docs/phase17_m2_channel_topic_relevance_shadow_report.md).

Root cause this addresses (docs/phase17_m0_output_quality_discovery_report.md §11/§12): `NewsEvent.
category` is assigned once, deterministically, from the *source's* static config tags
(`services/event_category.py::categorize_from_tags()`) - never from an individual article's own
content. The canonical failure this produces is the Netflix/Walking Dead case: Engadget is tagged
`[gadgets, consumer-tech, ai]`, so a streaming-rights story about "The Walking Dead" inherits
`GADGETS` regardless of its actual subject. This module never changes `NewsEvent.category` - it
computes a separate, article-level `ArticleTopicAssessment`/`ChannelFitAssessment` and persists
them purely additively, for future (M3+) use.

LLM/cost boundary (M2's own explicit requirement - zero new production API cost): everything here
is a deterministic function of already-available text (`NewsEvent.title`/`.content`, `research.
facts`) plus a curated, versioned keyword lexicon and a versioned `ChannelProfile`
(`services/channel_profiles.py`) - no LLM Gateway call, no provider SDK import, no network call.
`source_sufficiency` is obtained by calling `services.editorial_brief.classify_source_sufficiency()`
directly (a pure function) - this module does NOT depend on `editorial_brief_mode` being
`"shadow"`; M2 works whether or not M1's own shadow flag happens to be on.

Lexicon design principle (M2's own "false reject is worse than false review" priority, and its
explicit false-friend examples): topic keywords are chosen to avoid ambiguous single-meaning
collisions wherever possible (e.g. no bare company name like "Netflix"/"Apple" is ever scored as
a topic keyword on its own - see `_ENTITY_HINTS`, evidence-only, never scored) rather than trying
to special-case every ambiguous phrase after the fact. Company names are still surfaced in
`ArticleTopicAssessment.detected_entities` for human review, but never drive a decision alone.

Split, mirroring `services/fact_safety.py`'s/`services/editorial_brief.py`'s own established
shape: pure classification/assembly functions (no I/O), plus one thin `apply_channel_relevance_
shadow()` integration function that is the only piece `capabilities/executor.py` calls.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from core.config import settings
from database.models.news_event import EventCategory
from schemas.article_relevance import (
    ArticleTopicAssessment,
    ChannelFitAssessment,
    FitDecision,
    RelevanceConfidence,
    ShadowEditorialDecision,
)
from schemas.channel_profile import ChannelProfile
from schemas.topic_taxonomy import NON_TECH_TOPICS, TECH_TOPICS, ArticleTopic
from services.channel_profiles import CHANNEL_PROFILES, DEFAULT_CHANNEL_PROFILE_ID
from services.editorial_brief import SourceSufficiency, classify_source_sufficiency

CLASSIFIER_VERSION = "v1"

# ---------------------------------------------------------------------------
# Topic keyword lexicon - curated, versioned alongside this module (never hardcoded inside a
# ChannelProfile, which describes editorial *policy* over topics, not how to *detect* them).
# English + Russian, matching this project's real bilingual corpus (docs/
# phase17_m0_output_quality_discovery_report.md §3's own RU/EN source-type breakdown).
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS: dict[ArticleTopic, frozenset[str]] = {
    ArticleTopic.AI: frozenset({
        "ai", "ии", "artificial intelligence",
        # Russian noun-phrase case declension is not otherwise handled (this module's own "no
        # general NLP parser/stemmer" discipline, mirroring services/fact_safety.py) - the
        # 5 grammatical cases below are explicitly, hand-curated, matching real headline usage
        # (e.g. "закон о поддержке ... искусственного интеллекта" - genitive), calibrated
        # against a real false-reject found in this milestone's own 269-case backtest.
        "искусственный интеллект", "искусственного интеллекта", "искусственному интеллекту",
        "искусственным интеллектом", "искусственном интеллекте",
        "machine learning", "машинное обучение", "машинного обучения", "машинному обучению",
        "машинным обучением", "машинном обучении",
        "deep learning", "глубокое обучение", "neural network", "нейросеть", "нейросети",
        "нейросетевой", "нейросетевые", "нейросетевых", "llm", "chatgpt", "openai", "anthropic",
        "claude", "gemini", "generative ai", "генеративный ии", "genai", "language model",
        "language models", "языковая модель", "computer vision", "компьютерное зрение",
        "ai agent", "ии-агент", "chatbot", "чат-бот", "ai model", "ии-модель",
        "superintelligence", "сверхинтеллект", "deepfake", "deepfakes", "дипфейк",
        "дипфейки", "дипфейков",
    }),
    ArticleTopic.GADGETS: frozenset({
        "smartphone", "смартфон", "iphone", "ipad", "smartwatch", "умные часы", "wearable",
        "gadget", "гаджет", "гаджеты", "laptop", "ноутбук", "tablet", "планшет", "earbuds",
        "наушники", "handset", "flagship phone",
    }),
    ArticleTopic.CONSUMER_TECH: frozenset({
        "consumer electronics", "бытовая электроника", "smart home", "умный дом", "monitor",
        "smart speaker", "умная колонка", "e-reader", "электронная книга",
    }),
    ArticleTopic.SOFTWARE: frozenset({
        "software", "программное обеспечение", "software update", "обновление по", "app store",
        "application", "приложение", "browser", "браузер", "operating system",
        "операционная система", "open source", "открытый исходный код", "api", "framework",
    }),
    ArticleTopic.BIG_TECH: frozenset({
        "tech giant", "technology company", "технологическая компания", "big tech",
        "quarterly earnings", "earnings report", "квартальная отчетность", "revenue grew",
        "выручка выросла",
    }),
    ArticleTopic.CHIPS: frozenset({
        "chip", "чип", "чипа", "чипы", "чипов", "чипу", "microchip", "gpu", "видеокарта",
        "cpu", "processor", "процессор", "semiconductor", "полупроводник", "полупроводников",
        "foundry", "chip fab", "nvidia", "tsmc", "intel", "wafer",
    }),
    ArticleTopic.CYBERSECURITY: frozenset({
        "vulnerability", "уязвимость", "уязвимости", "уязвимостей", "exploit", "malware",
        "вредоносное", "вредоносный", "вредоносного", "вредоносную", "вредоносным",
        "data breach", "утечка данных", "hacked", "взлом", "ransomware", "phishing",
        "фишинг", "cyberattack", "кибератака", "кибератаки", "кибератаку", "кибератак",
        "security flaw",
    }),
    ArticleTopic.GAMING_TECH: frozenset({
        "gaming laptop", "игровой ноутбук", "gaming pc", "игровой пк", "steam deck",
        "graphics card", "gaming hardware", "игровое железо", "console hardware",
    }),
    ArticleTopic.SCIENCE_TECH: frozenset({
        "arxiv", "research paper", "научная статья", "study finds", "исследование показало",
        "preprint", "препринт", "researchers", "исследователи",
    }),
    ArticleTopic.BUSINESS_TECH: frozenset({
        "funding round", "раунд финансирования", "series a", "series b", "series c",
        "venture capital", "венчурн", "startup", "стартап", "valuation", "оценка компании",
        "acquisition", "поглощение", "acquired", "приобрела", "raised $", "привлек",
        "привлекла", "investors", "инвесторы",
    }),
    ArticleTopic.REGULATION_TECH: frozenset({
        "antitrust", "антимонопольное", "антимонопольный", "антимонопольного",
        "антимонопольным", "regulation", "регулирование", "регулирования", "регулированию",
        "регулированием", "gdpr", "eu commission", "европейская комиссия", "lawsuit against",
        "иск против", "regulatory fine", "data protection authority", "doj",
        "министерство юстиции",
        # Platform-accountability regulation (a real, currently-live category of tech-platform
        # regulatory action - e.g. an EU child-safety finding against a social platform) -
        # deliberately phrase-based, not a bare platform company name (module docstring's own
        # "no bare company name scores a topic" rule).
        "minors' safety", "child safety", "protect minors", "защита несовершеннолетних",
        "platform accountability",
    }),
    ArticleTopic.ENTERTAINMENT: frozenset({
        "streaming rights", "права на трансляцию", "tv series", "телесериал", "сериал",
        "spin-off", "спин-офф", "movie", "фильм", "box office", "кассовые сборы", "actress",
        "актриса", "actor", "актер", "актёр", "celebrity", "знаменитость", "знаменитости",
        "знаменитостей", "season finale", "tv show", "телешоу", "season premiere",
    }),
    ArticleTopic.GAMING_CONTENT: frozenset({
        "game trailer", "трейлер игры", "gameplay", "геймплей", "dlc", "game review",
        "обзор игры", "video game", "video games", "видеоигра", "game launch",
    }),
    ArticleTopic.POLITICS: frozenset({
        "election", "выборы", "president", "президент", "parliament", "парламент", "congress",
        "конгресс", "senator", "сенатор",
    }),
    ArticleTopic.SPORTS: frozenset({
        "tournament", "турнир", "championship", "чемпионат", "football match", "футбольный матч",
        "basketball game", "олимпиад", "olympic games",
    }),
    ArticleTopic.LIFESTYLE: frozenset({
        "recipe", "рецепт", "fashion week", "неделя моды", "diet plan", "диета", "travel tips",
        "wellness tips",
    }),
    ArticleTopic.CRIME: frozenset({
        "murder", "убийство", "robbery", "ограбление", "arrested", "арестован", "shooting",
        "стрельба",
    }),
}

# Evidence-only entity hints - deliberately never used as a topic-scoring signal on their own
# (module docstring): a bare company name is not proof of tech relevance for *this* article.
_ENTITY_HINTS: tuple[str, ...] = (
    "Apple", "Google", "Microsoft", "Meta", "Amazon", "Netflix", "Samsung", "Nvidia", "TSMC",
    "Intel", "AMD", "OpenAI", "Anthropic", "Tesla", "SpaceX", "Sony", "Valve", "Steam", "Xbox",
    "PlayStation", "Qualcomm", "ByteDance", "TikTok",
)

_TOPIC_TO_EVENT_CATEGORY: dict[ArticleTopic, EventCategory] = {
    ArticleTopic.AI: EventCategory.AI,
    ArticleTopic.GADGETS: EventCategory.GADGETS,
    ArticleTopic.CONSUMER_TECH: EventCategory.GADGETS,
    ArticleTopic.SOFTWARE: EventCategory.SOFTWARE,
    ArticleTopic.CHIPS: EventCategory.HARDWARE,
    ArticleTopic.CYBERSECURITY: EventCategory.CYBERSECURITY,
    ArticleTopic.BUSINESS_TECH: EventCategory.STARTUPS,
    ArticleTopic.BIG_TECH: EventCategory.TECH,
    ArticleTopic.SCIENCE_TECH: EventCategory.TECH,
    ArticleTopic.GAMING_TECH: EventCategory.TECH,
    ArticleTopic.REGULATION_TECH: EventCategory.TECH,
    # ENTERTAINMENT/GAMING_CONTENT/POLITICS/SPORTS/LIFESTYLE/CRIME/OTHER/UNKNOWN -> no
    # EventCategory equivalent (None) - deliberately: none of these topics has ever been a real
    # EventCategory value, so "matching" one would be meaningless.
}

_THIN_SUFFICIENCY = {
    SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY,
    SourceSufficiency.CONFLICTING, SourceSufficiency.UNKNOWN,
}


def _pluralize(word: str) -> str | None:
    """Cheap, explicit, non-general pluralization for a single ASCII keyword only - never a real
    stemmer/morphology engine (this module's own "no general NLP parser" discipline, mirroring
    `services/fact_safety.py`'s identical constraint). Multi-word phrases and non-ASCII (Cyrillic)
    words are never touched - Russian inflection is a known, documented lexicon limitation
    (docs/phase17_m2_channel_topic_relevance_shadow_report.md §24), not solved here."""
    if not word.isascii() or " " in word:
        return None
    if word.endswith(("ch", "sh", "ss", "x", "z")):
        return word + "es"
    if word.endswith("s"):
        return None
    if len(word) >= 2 and word[-1] == "y" and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _compile_topic_patterns() -> dict[ArticleTopic, re.Pattern[str]]:
    patterns: dict[ArticleTopic, re.Pattern[str]] = {}
    for topic, phrases in _TOPIC_KEYWORDS.items():
        expanded: set[str] = set(phrases)
        for phrase in phrases:
            plural = _pluralize(phrase)
            if plural:
                expanded.add(plural)
        alternation = "|".join(re.escape(phrase) for phrase in sorted(expanded, key=len, reverse=True))
        patterns[topic] = re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)
    return patterns


_TOPIC_PATTERNS = _compile_topic_patterns()
_ENTITY_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(name)}\b" for name in _ENTITY_HINTS), re.IGNORECASE
)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _match_topic_keywords(text: str) -> dict[ArticleTopic, list[str]]:
    matches: dict[ArticleTopic, list[str]] = {}
    for topic, pattern in _TOPIC_PATTERNS.items():
        found = sorted({m.group(0).lower() for m in pattern.finditer(text)})
        if found:
            matches[topic] = found
    return matches


def _detect_entities(text: str) -> list[str]:
    seen: dict[str, str] = {}
    for match in _ENTITY_PATTERN.finditer(text):
        canonical = next(name for name in _ENTITY_HINTS if name.lower() == match.group(0).lower())
        seen[canonical.lower()] = canonical
    return sorted(seen.values())


def _topic_confidence(
    scores: dict[ArticleTopic, int], tech_scores: dict[ArticleTopic, int], nontech_scores: dict[ArticleTopic, int],
) -> RelevanceConfidence:
    """A tie between two *tech* topics (e.g. CHIPS and AI both scoring strongly for the same
    Nvidia article) is a sign of strong, unambiguous tech relevance, not ambiguity - so
    confidence is driven by *total* evidence strength within whichever pool (tech or non-tech)
    actually has matches, not by how that evidence happens to split across individual topics
    within the same pool. A tie *across* the tech/non-tech boundary is the genuinely ambiguous
    case, already handled separately above (always LOW, forcing REVIEW downstream)."""
    if not scores:
        return RelevanceConfidence.LOW
    if tech_scores and nontech_scores:
        return RelevanceConfidence.LOW  # mixed signal - never high/medium, forces downstream REVIEW
    pool = tech_scores if tech_scores else nontech_scores
    total_evidence = sum(pool.values())
    if total_evidence >= 2:
        return RelevanceConfidence.HIGH
    return RelevanceConfidence.MEDIUM


def classify_article_topic(
    title: str, content: str | None, research_facts: list[str], source_category: EventCategory,
) -> ArticleTopicAssessment:
    """Pure, deterministic. Never invents a topic beyond what its own keyword evidence
    supports (`topic_evidence` always traces every scored topic back to the exact matched
    phrases) - a topic with zero matched keywords never appears as `primary_topic` unless
    nothing else exists (`UNKNOWN`)."""
    text = _normalize(f"{title} {content or ''} {' '.join(research_facts)}")
    topic_matches = _match_topic_keywords(text)
    entities = _detect_entities(f"{title} {content or ''}")

    scores = {topic: len(keywords) for topic, keywords in topic_matches.items()}
    tech_scores = {t: s for t, s in scores.items() if t in TECH_TOPICS}
    nontech_scores = {t: s for t, s in scores.items() if t in NON_TECH_TOPICS}

    reason_codes: list[str] = []
    secondary: list[ArticleTopic]
    if not scores:
        primary = ArticleTopic.UNKNOWN
        secondary = []
        reason_codes.append("no_topic_keywords_matched")
    else:
        ranked_pool = tech_scores if tech_scores else nontech_scores
        primary = max(ranked_pool, key=lambda t: (ranked_pool[t], t.value))
        secondary = sorted(
            (t for t in scores if t != primary), key=lambda t: (-scores[t], t.value),
        )[:4]
        if tech_scores and nontech_scores:
            reason_codes.append("mixed_tech_and_nontech_signals")

    normalized_category = _TOPIC_TO_EVENT_CATEGORY.get(primary)
    category_match = normalized_category is not None and normalized_category == source_category
    if primary == ArticleTopic.UNKNOWN:
        reason_codes.append("primary_topic_unknown")
    elif not category_match:
        reason_codes.append(
            "category_mismatch" if normalized_category is not None else "no_event_category_equivalent"
        )

    confidence = _topic_confidence(scores, tech_scores, nontech_scores)

    return ArticleTopicAssessment(
        primary_topic=primary,
        secondary_topics=secondary,
        normalized_category=normalized_category,
        detected_entities=entities,
        topic_evidence={topic.value: keywords for topic, keywords in topic_matches.items()},
        source_category=source_category,
        category_match=category_match,
        confidence=confidence,
        reason_codes=reason_codes,
    )


def assess_channel_fit(
    topic_assessment: ArticleTopicAssessment, profile: ChannelProfile, source_sufficiency: SourceSufficiency,
) -> ChannelFitAssessment:
    """Pure, deterministic. Implements this milestone's own priority ("a false REJECT is more
    dangerous than a false REVIEW" - never auto-decide on a single ambiguous signal; prefer
    REVIEW whenever signals conflict or evidence is thin)."""
    candidate_topics = [topic_assessment.primary_topic, *topic_assessment.secondary_topics]
    matched_topics = [
        t for t in candidate_topics
        if t in profile.primary_topics or t in profile.secondary_topics or t in profile.allowed_adjacent_topics
    ]
    excluded_matches = [t for t in candidate_topics if t in profile.excluded_topics]
    conditional_matches = [t for t in candidate_topics if t in profile.conditional_topics]

    tech_evidence_strength = sum(len(topic_assessment.topic_evidence.get(t.value, [])) for t in matched_topics)
    excluded_evidence_strength = sum(len(topic_assessment.topic_evidence.get(t.value, [])) for t in excluded_matches)

    evidence: list[str] = []
    for topic in [*matched_topics, *excluded_matches, *conditional_matches]:
        for keyword in topic_assessment.topic_evidence.get(topic.value, [])[:3]:
            evidence.append(f"{topic.value}:{keyword}")

    reason_codes = list(topic_assessment.reason_codes)
    thin_source = source_sufficiency in _THIN_SUFFICIENCY
    confidence = topic_assessment.confidence
    human_review_required: bool

    if not matched_topics and not excluded_matches and not conditional_matches:
        decision = FitDecision.REVIEW
        reason_codes.append("no_topic_evidence_review_default")
        fit_score = 0.3
        human_review_required = True

    elif excluded_evidence_strength > 0 and tech_evidence_strength == 0:
        # Dominant excluded topic, zero independent tech evidence - source category alone is
        # never sufficient (ChannelProfile's own "excluded_topic_requires_independent_tech_
        # evidence_to_avoid_reject" required_relationship - the Netflix/Walking Dead discipline).
        decision = FitDecision.REJECT
        reason_codes.append(
            "dominant_excluded_topic_headline_only" if thin_source else "dominant_excluded_topic_no_tech_evidence"
        )
        fit_score = 0.05
        confidence = RelevanceConfidence.MEDIUM if thin_source else RelevanceConfidence.HIGH
        human_review_required = False

    elif excluded_evidence_strength > 0 and tech_evidence_strength > 0:
        # Mixed signal ("AI actor" style ambiguity, or a real tech story with an incidental
        # excluded-topic mention) - never auto-decide either way.
        decision = FitDecision.REVIEW
        reason_codes.append("mixed_topic_tech_and_excluded_evidence")
        fit_score = 0.5
        confidence = RelevanceConfidence.LOW
        human_review_required = True

    elif conditional_matches and not matched_topics:
        # "conditional_topic_requires_tech_centrality" - a conditional topic (e.g.
        # GAMING_CONTENT) needs independent primary/secondary/allowed-adjacent evidence to
        # co-occur; on its own it is never auto-ACCEPT.
        decision = FitDecision.REVIEW
        reason_codes.append("conditional_topic_without_tech_centrality")
        fit_score = 0.45
        confidence = RelevanceConfidence.LOW
        human_review_required = True

    elif matched_topics:
        if source_sufficiency == SourceSufficiency.HEADLINE_ONLY:
            # "не давать высокую уверенность без сильного явного сигнала; чаще REVIEW"
            decision = FitDecision.REVIEW
            reason_codes.append("headline_only_capped_to_review")
            fit_score = 0.6
            confidence = RelevanceConfidence.MEDIUM if confidence == RelevanceConfidence.HIGH else confidence
            human_review_required = True
        elif thin_source:
            decision = FitDecision.REVIEW
            reason_codes.append("thin_source_capped_to_review")
            fit_score = 0.55
            human_review_required = True
        elif confidence == RelevanceConfidence.HIGH:
            decision = FitDecision.ACCEPT
            fit_score = 0.9
            human_review_required = False
        else:
            decision = FitDecision.REVIEW
            reason_codes.append("matched_topic_but_confidence_not_high")
            fit_score = 0.65
            human_review_required = True

    else:
        decision = FitDecision.REVIEW
        reason_codes.append("no_conclusive_signal")
        fit_score = 0.4
        human_review_required = True

    return ChannelFitAssessment(
        channel_profile_id=profile.profile_id,
        fit_decision=decision,
        fit_score=fit_score,
        confidence=confidence,
        matched_topics=matched_topics,
        excluded_topics=excluded_matches,
        conditional_matches=conditional_matches,
        evidence=evidence,
        reason_codes=reason_codes,
        human_review_required=human_review_required,
    )


def decide_shadow_editorial(fit: ChannelFitAssessment) -> ShadowEditorialDecision:
    """A thin, purely-derived summary of `fit` - never an independent decision path. Kept as a
    separate schema/function (rather than just reading `ChannelFitAssessment.fit_decision`
    directly) because M2's own task brief asks for a distinct `ShadowEditorialDecision` shape
    that other future consumers (e.g. a human review queue) can depend on without coupling to
    the full topic/fit assessment internals."""
    return ShadowEditorialDecision(
        decision=fit.fit_decision,
        reason_codes=list(fit.reason_codes),
        confidence=fit.confidence,
        classifier_version=CLASSIFIER_VERSION,
    )


def assess_channel_relevance(
    news_event_title: str,
    news_event_content: str | None,
    news_event_category: EventCategory,
    research_output: dict[str, Any],
    profile_id: str = DEFAULT_CHANNEL_PROFILE_ID,
) -> tuple[ArticleTopicAssessment, ChannelFitAssessment, ShadowEditorialDecision]:
    profile = CHANNEL_PROFILES[profile_id]
    research_facts = (
        [f for f in research_output.get("facts", []) if isinstance(f, str)]
        if isinstance(research_output.get("facts"), list) else []
    )
    research_gaps = (
        [g for g in research_output.get("gaps", []) if isinstance(g, str)]
        if isinstance(research_output.get("gaps"), list) else []
    )

    topic_assessment = classify_article_topic(
        news_event_title, news_event_content, research_facts, news_event_category,
    )
    sufficiency_assessment = classify_source_sufficiency(
        news_event_title, news_event_content, research_facts, research_gaps,
    )
    fit_assessment = assess_channel_fit(topic_assessment, profile, sufficiency_assessment.sufficiency)
    decision = decide_shadow_editorial(fit_assessment)
    return topic_assessment, fit_assessment, decision


def apply_channel_relevance_shadow(
    news_event_title: str,
    news_event_content: str | None,
    news_event_category: EventCategory,
    research_output: dict[str, Any],
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "intelligence" step, only after
    IntelligenceCapability's own call (or a reused prior result) already succeeded. Returns
    `structured_output` completely unchanged when `channel_relevance_mode == "off"` (the default,
    byte-identical-to-pre-M2 rollback path). Mirrors `services.editorial_brief.
    apply_editorial_brief_shadow()`'s own established merge convention exactly - purely additive,
    a single `"channel_relevance"` key holding all three assessments."""
    if settings.channel_relevance_mode == "off":
        return structured_output

    topic_assessment, fit_assessment, decision = assess_channel_relevance(
        news_event_title, news_event_content, news_event_category, research_output,
    )
    return {
        **structured_output,
        "channel_relevance": {
            "article_topic_assessment": topic_assessment.model_dump(mode="json"),
            "channel_fit_assessment": fit_assessment.model_dump(mode="json"),
            "shadow_decision": decision.model_dump(mode="json"),
        },
    }
