"""TELEGRAPH editorial channel split: deterministic classification of a Story into one of two
editorial directions (`schemas.editorial.EditorialChannel`) - NINJA_AI or NINJA_PULSE.

Deliberately no LLM call anywhere in this module (the task's own explicit "на первом этапе НЕ
использовать LLM" requirement) - cheaper, testable, predictable, and it runs at shortlist-
creation time, before any human has approved anything, so a paid call here would be spent on
Stories that may never even be shown to an operator.

Pure function over `services.telegraph_topic_candidates.StoryEvidenceSummary` - the same compact,
already-computed aggregate Checkpoint 1's own `evaluate_story_topic_candidate()` scores from, so
this classifier adds zero new database queries of its own (the caller already has this object in
hand). Scores against `story_title` + `representative_recommendation` (Intelligence's own already-
computed judgement text, if any) - the only free text `StoryEvidenceSummary` carries; `story_
category`/`topic_bucket` are deliberately NOT used as additional, undisclosed scoring inputs (that
would be exactly the "скрытую магию" this module's own brief forbids) - every point awarded traces
to one of the ten named, keyword-list-based signals below, nothing else.

All keyword lists and point weights are named module-level constants, matching the exact rubric
given (5 signals per channel, fixed weights) - reasoned starting points, not fit to any real
classification-outcome data yet, matching this codebase's own established "reasoned default,
refine later" convention (e.g. services/telegraph_topic_candidates.py's own thresholds).
"""
from __future__ import annotations

from dataclasses import dataclass

from schemas.editorial import EditorialChannel
from services.telegraph_topic_candidates import StoryEvidenceSummary
from services.text_normalization import fuzzy_phrase_contains

# ---------------------------------------------------------------------------------------------
# NINJA_AI signals - "помочь пользователю лучше использовать наш AI сервис" (educational/
# practical AI-usage content: tools, prompts, tutorials, new AI capabilities).
# ---------------------------------------------------------------------------------------------

NINJA_AI_KEYWORDS_WEIGHT = 20
NINJA_AI_TUTORIAL_SIGNAL_WEIGHT = 25
NINJA_AI_PRACTICAL_USE_CASE_WEIGHT = 20
NINJA_AI_PROMPT_SIGNAL_WEIGHT = 20
NINJA_AI_NEW_FEATURE_WEIGHT = 15

NINJA_AI_KEYWORDS: tuple[str, ...] = (
    "ai", "искусственный интеллект", "ии", "chatgpt", "gpt", "claude", "gemini", "midjourney",
    "runway", "llm", "нейросеть", "нейросети", "copilot", "языковая модель", "openai", "anthropic",
    # Versioned model names contain a hyphen, which services.text_normalization's own word
    # tokenizer (`_WORD_RE = r"[\w-]+"`) keeps glued to the token ("gpt-5" stays one token, never
    # splits into "gpt"+"5") - the bare "gpt"/"claude"/"gemini" entries above never match these on
    # their own, so current model-version strings are listed explicitly. A disclosed, known-
    # incomplete list (new model versions will need their own future addition here), matching
    # every other reasoned keyword list in this codebase (e.g. services/story_memory.py's own
    # _TOPIC_KEYWORDS) - never silently "fuzzy" beyond exact, transparent entries.
    "gpt-3", "gpt-4", "gpt-4o", "gpt-5", "gpt-6", "claude-3", "claude-4",
)
NINJA_AI_TUTORIAL_SIGNALS: tuple[str, ...] = (
    "как использовать", "как пользоваться", "инструкция", "руководство", "how to", "tutorial",
    "guide", "гайд", "пошаговая инструкция",
)
NINJA_AI_PRACTICAL_USE_CASE_SIGNALS: tuple[str, ...] = (
    "кейс", "use case", "применение", "practical", "пример использования", "на практике",
    "автоматизировать", "автоматизация", "automate", "automation", "workflow",
)
NINJA_AI_PROMPT_SIGNALS: tuple[str, ...] = (
    "промт", "промты", "промтов", "промпт", "промпты", "промптов", "prompt", "prompts",
)
NINJA_AI_NEW_FEATURE_SIGNALS: tuple[str, ...] = (
    "новая функция", "новые функции", "new feature", "новая модель", "релиз модели",
    "обновление модели", "model update",
)

# ---------------------------------------------------------------------------------------------
# NINJA_PULSE signals - "быть технологическим медиа" (gadgets, hardware, industry news).
# ---------------------------------------------------------------------------------------------

NINJA_PULSE_GADGET_WEIGHT = 25
NINJA_PULSE_HARDWARE_COMPANY_WEIGHT = 20
NINJA_PULSE_DEVICE_WEIGHT = 20
NINJA_PULSE_MARKET_INDUSTRY_WEIGHT = 20
NINJA_PULSE_TECH_EVENT_WEIGHT = 15

NINJA_PULSE_GADGET_KEYWORDS: tuple[str, ...] = (
    "гаджет", "смартфон", "ноутбук", "iphone", "device", "gadget", "phone", "laptop", "планшет",
    "смарт-часы", "наушники",
)
NINJA_PULSE_HARDWARE_COMPANY_KEYWORDS: tuple[str, ...] = (
    "apple", "samsung", "google", "nvidia", "qualcomm", "intel", "amd", "xiaomi", "huawei", "sony",
)
NINJA_PULSE_DEVICE_KEYWORDS: tuple[str, ...] = (
    "устройство", "процессор", "чип", "chip", "processor", "видеокарта", "gpu", "cpu", "батарея",
    "дисплей", "rtx", "geforce", "radeon", "snapdragon", "exynos",
)
NINJA_PULSE_MARKET_INDUSTRY_KEYWORDS: tuple[str, ...] = (
    "рынок", "индустрия", "market", "industry", "поставки", "продажи",
)
NINJA_PULSE_TECH_EVENT_KEYWORDS: tuple[str, ...] = (
    "презентация", "launch", "анонс", "анонсировала", "announced", "unveiled", "представила",
    "представили", "выпустила", "запустила",
)

# The task's own explicit tie-break rule: "если разница меньше 10, ставить NINJA_PULSE, потому
# что это основной технологический канал."
_TIE_BREAK_MARGIN = 10
_DEFAULT_CHANNEL = EditorialChannel.NINJA_PULSE


@dataclass(frozen=True)
class EditorialChannelDecision:
    """Every component that fed the decision, plus the deterministic rationale text - never a
    black box (mirrors services/telegraph_topic_candidates.py::TopicCandidateSignals's own
    always-explain convention)."""

    channel: EditorialChannel
    ninja_ai_score: int
    ninja_pulse_score: int
    matched_ninja_ai_signals: tuple[str, ...]
    matched_ninja_pulse_signals: tuple[str, ...]
    rationale: str


def _matches_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(fuzzy_phrase_contains(phrase, text) for phrase in phrases)


def _score_ninja_ai(text: str) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    if _matches_any(text, NINJA_AI_KEYWORDS):
        score += NINJA_AI_KEYWORDS_WEIGHT
        matched.append("AI keywords")
    if _matches_any(text, NINJA_AI_TUTORIAL_SIGNALS):
        score += NINJA_AI_TUTORIAL_SIGNAL_WEIGHT
        matched.append("tutorial/instruction signal")
    if _matches_any(text, NINJA_AI_PRACTICAL_USE_CASE_SIGNALS):
        score += NINJA_AI_PRACTICAL_USE_CASE_WEIGHT
        matched.append("practical use-case")
    if _matches_any(text, NINJA_AI_PROMPT_SIGNALS):
        score += NINJA_AI_PROMPT_SIGNAL_WEIGHT
        matched.append("prompt/use case")
    if _matches_any(text, NINJA_AI_NEW_FEATURE_SIGNALS):
        score += NINJA_AI_NEW_FEATURE_WEIGHT
        matched.append("new AI feature")
    return score, matched


def _score_ninja_pulse(text: str) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    if _matches_any(text, NINJA_PULSE_GADGET_KEYWORDS):
        score += NINJA_PULSE_GADGET_WEIGHT
        matched.append("gadget")
    if _matches_any(text, NINJA_PULSE_HARDWARE_COMPANY_KEYWORDS):
        score += NINJA_PULSE_HARDWARE_COMPANY_WEIGHT
        matched.append("hardware company")
    if _matches_any(text, NINJA_PULSE_DEVICE_KEYWORDS):
        score += NINJA_PULSE_DEVICE_WEIGHT
        matched.append("device")
    if _matches_any(text, NINJA_PULSE_MARKET_INDUSTRY_KEYWORDS):
        score += NINJA_PULSE_MARKET_INDUSTRY_WEIGHT
        matched.append("market/industry")
    if _matches_any(text, NINJA_PULSE_TECH_EVENT_KEYWORDS):
        score += NINJA_PULSE_TECH_EVENT_WEIGHT
        matched.append("technology event")
    return score, matched


def _render_rationale(
    channel: EditorialChannel, matched_ai: list[str], matched_pulse: list[str],
    ai_score: int, pulse_score: int, *, tie_break_applied: bool,
) -> str:
    label = "NINJA_AI" if channel == EditorialChannel.NINJA_AI else "NINJA_PULSE"
    reasons = matched_ai if channel == EditorialChannel.NINJA_AI else matched_pulse
    reasons_text = ", ".join(reasons) if reasons else "сигналы не найдены"
    tie_break_note = (
        f" Разница в счёте меньше {_TIE_BREAK_MARGIN} — применён запасной выбор в пользу "
        "основного технологического канала."
        if tie_break_applied else ""
    )
    return (
        f"Канал: {label}. Причины: {reasons_text}.{tie_break_note} "
        f"(ninja_ai_score={ai_score}, ninja_pulse_score={pulse_score})"
    )


def classify_editorial_channel(summary: StoryEvidenceSummary) -> EditorialChannelDecision:
    """Pure, deterministic, no I/O, no LLM call. Scores `summary.story_title` +
    `summary.representative_recommendation` against the ten named signal lists above, then
    applies the fixed tie-break rule: NINJA_PULSE wins whenever the two scores differ by less
    than `_TIE_BREAK_MARGIN`, including a full 0-0 tie (no signals matched at all) - the task's
    own explicit "NINJA_PULSE is the primary technology channel" default."""
    text = f"{summary.story_title} {summary.representative_recommendation or ''}"

    ai_score, matched_ai = _score_ninja_ai(text)
    pulse_score, matched_pulse = _score_ninja_pulse(text)

    tie_break_applied = abs(ai_score - pulse_score) < _TIE_BREAK_MARGIN
    if tie_break_applied:
        channel = _DEFAULT_CHANNEL
    elif ai_score > pulse_score:
        channel = EditorialChannel.NINJA_AI
    else:
        channel = EditorialChannel.NINJA_PULSE

    rationale = _render_rationale(
        channel, matched_ai, matched_pulse, ai_score, pulse_score, tie_break_applied=tie_break_applied,
    )
    return EditorialChannelDecision(
        channel=channel, ninja_ai_score=ai_score, ninja_pulse_score=pulse_score,
        matched_ninja_ai_signals=tuple(matched_ai), matched_ninja_pulse_signals=tuple(matched_pulse),
        rationale=rationale,
    )
