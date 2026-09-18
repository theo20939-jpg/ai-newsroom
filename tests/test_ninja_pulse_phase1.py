from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from core.config import Settings
from services.news_editorial_relevance import (
    ViralTechBreakdown,
    evaluate_pre_generation_candidate,
    score_viral_tech,
)

NOW = datetime(2026, 9, 18, 1, 0, tzinfo=UTC)


def decide(title: str, *, score: int = 70, content: str = "", reliability: float = 0.8):
    return evaluate_pre_generation_candidate(
        title=title,
        content=content,
        standard_score=score,
        standard_threshold=70,
        source_reliability=reliability,
        published_at=NOW - timedelta(minutes=20),
        now=NOW,
    )


def test_high_score_funding_does_not_automatically_dominate() -> None:
    result = decide(
        "Crusoe raises $3.9B in Series F at a $30.9B valuation",
        score=91,
        content="The financing round was led by investors and will fund data centers.",
    )
    assert result.effective_standard_score == 66
    assert result.standard_eligible is False
    assert result.viral.eligible is False
    assert result.final_eligible is False


def test_exceptional_financial_event_can_still_survive() -> None:
    result = decide(
        "Apple acquisition could force divestiture of a major product",
        score=82,
        content="The ruling could force Apple to change the product used by millions.",
    )
    assert result.standard_eligible is True
    assert result.selection_path == "STANDARD"


@pytest.mark.parametrize(
    "title",
    [
        "Apple launches a smartphone with a new satellite feature",
        "OpenAI launches a new model with a useful reasoning mode",
        "A robotics lab demonstrates a new humanoid robot",
    ],
)
def test_positive_pulse_fit_preserves_standard_news(title: str) -> None:
    result = decide(title, score=70)
    assert result.standard_eligible is True
    assert result.final_eligible is True


def test_valheim_creator_trick_can_survive_via_viral_tech() -> None:
    result = decide(
        "You can customize Valheim sign text for color-coded storage without downloading a single mod",
        score=18,
    )
    assert result.standard_eligible is False
    assert result.viral.total >= 68
    assert result.viral.eligible is True
    assert result.selection_path == "VIRAL_TECH"


def test_telstra_2006_outage_is_standard_and_viral_overlap() -> None:
    result = decide(
        "Telstra outage: the night a network decided the year was 2006",
        score=72,
    )
    assert result.standard_eligible is True
    assert result.viral.eligible is True
    assert result.selection_path == "BOTH"


def test_funny_non_tech_meme_cannot_survive() -> None:
    result = decide("A funny cat meme went viral again", score=15)
    assert result.viral.breakdown.tech_relevance == 0
    assert result.viral.eligible is False
    assert result.final_eligible is False


def test_body_only_surprise_words_do_not_rescue_niche_enterprise_case_study() -> None:
    result = decide(
        "Как мы научили ИИ-модель понимать документы и ускорили оформление сотрудников",
        score=35,
        content=(
            "Внутри проекта возник неожиданный сбой, затем команда провела эксперимент и "
            "собрала демонстрацию внутреннего workflow."
        ),
    )
    assert result.viral.breakdown.tech_relevance == 20
    assert result.viral.breakdown.surprise_weirdness == 0
    assert result.viral.breakdown.humor_meme_potential == 0
    assert result.viral.eligible is False
    assert result.final_eligible is False


def test_missing_engagement_does_not_fabricate_velocity() -> None:
    result = score_viral_tech(
        "A bizarre robot prototype unexpectedly behaves without a mod",
        source_reliability=0.9,
        published_at=NOW,
        now=NOW,
    )
    assert result.breakdown.velocity_spread == 0


def test_low_verification_blocks_viral_eligibility() -> None:
    result = decide(
        "Bizarre robot prototype unexpectedly starts gaming without a mod",
        score=20,
        reliability=0.2,
    )
    assert result.viral.total >= 60
    assert result.viral.breakdown.verifiability < 6
    assert result.viral.eligible is False


def test_stale_viral_story_is_blocked() -> None:
    result = score_viral_tech(
        "Telstra network decided the year was 2006",
        source_reliability=0.9,
        published_at=NOW - timedelta(days=3),
        now=NOW,
    )
    assert result.stale is True
    assert result.breakdown.freshness_penalty == -25
    assert result.eligible is False


def test_component_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        ViralTechBreakdown(21, 0, 0, 0, 0, 0, 0)
    valid = ViralTechBreakdown(20, 20, 15, 15, 10, 10, 10)
    assert valid.total == 100


def test_threshold_and_hard_minimums_are_exact() -> None:
    at_threshold = ViralTechBreakdown(10, 20, 10, 12, 5, 5, 6)
    assert at_threshold.total == 68
    decision = score_viral_tech(
        "A weird technology prototype demo unexpectedly behaves without a mod",
        source_reliability=0.6,
        published_at=NOW,
        now=NOW,
        has_visual_proof=True,
    )
    assert decision.breakdown.tech_relevance >= 10
    assert decision.breakdown.verifiability == 6


def test_fast_lane_requires_primary_or_two_confirmations() -> None:
    kwargs = {
        "title": "A bizarre robot prototype demo unexpectedly behaves without a mod",
        "source_reliability": 0.9,
        "published_at": NOW,
        "now": NOW,
        "has_visual_proof": True,
        "views_count": 2000,
    }
    no_evidence = score_viral_tech(**kwargs)
    primary = score_viral_tech(**kwargs, primary_evidence=True)
    confirmations = score_viral_tech(**kwargs, credible_confirmations=2)
    assert no_evidence.total >= 80 and no_evidence.fast_lane is False
    assert primary.fast_lane is True
    assert confirmations.fast_lane is True


def test_global_threshold_and_director_gate_defaults_unchanged() -> None:
    assert Settings.model_fields["content_generation_min_score"].default == 70
    assert Settings.model_fields["telegram_editorial_gate_enabled"].default is False


def test_copywriting_v87_clarity_and_social_contract() -> None:
    path = Path("prompts/copywriting/v8.7.yaml")
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed["name"] == "copywriting"
    assert parsed["version"] == "8.7"
    rules = "\n".join(parsed["rules"])
    assert "SPECIALIST TERMS (V8.7)" in rules
    assert "one short natural phrase" in rules
    assert "Never add a glossary" in rules
    assert "вычислительные шейдеры WebGPU" in rules
    assert "CVIA and ISO brightness" in rules
    assert "Что думаете?" in rules and "Never use generic engagement bait" in rules
    assert "Never expose labels such as CTA" in rules
    assert "most posts should have NO ending at all" in rules


def test_copywriting_v87_keeps_russian_and_evidence_boundaries() -> None:
    raw = Path("prompts/copywriting/v8.7.yaml").read_text(encoding="utf-8")
    assert "Always write title, main_body, and ending" in raw
    assert "SEMANTIC PRECISION IS NON-NEGOTIABLE" in raw
    assert "must never add outside knowledge" in raw


def test_news_url_and_no_migration() -> None:
    presentation = Path("services/news_telegram_presentation.py").read_text(encoding="utf-8")
    assert 'https://t.me/ninja_pulse' in presentation
    assert not list(Path("database/migrations/versions").glob("*ninja*pulse*phase1*"))
