"""Phase 9 M7: cross-cutting regression checkpoint - the Phase 9 analog of Phase 8's own M8
(tests/test_phase8_cross_cutting_regression.py). Re-checks, directly and not merely assumed
safe because M6 already checked it once, that the complete, unmodified boot sequence
(`assemble_ai_integration_layer()`, frozen since Phase 7 M19, never modified by Phase 8 or 9)
resolves all four registered Capabilities - the one check `tests/
test_phase9_capability_registration.py` (M6) does not itself perform, since M6's own tests
construct `build_registry()` directly rather than going through the full boot sequence.
"""
from pathlib import Path

from pydantic import SecretStr
from redis.asyncio import Redis

from capabilities.intelligence_capability import CAPABILITY_NAME as INTELLIGENCE_CAPABILITY_NAME
from capabilities.intelligence_capability import IntelligenceCapability
from capabilities.quality_capability import CAPABILITY_NAME as QUALITY_CAPABILITY_NAME
from capabilities.quality_capability import QualityCapability
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from capabilities.research_capability import ResearchCapability
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from capabilities.scoring_capability import ScoringCapability
from core.config import Settings
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _boot_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "enabled_providers": ["openai"],
        "openai_api_key": SecretStr("sk-test-not-a-real-key-0000000000"),
        "redis_unavailable_policy": "fail_open",
        "verify_capabilities_at_boot": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[call-arg, arg-type]


def test_full_boot_sequence_resolves_all_four_capabilities(redis_client: Redis) -> None:
    layer = assemble_ai_integration_layer(_boot_settings(), _prompt_repository(), redis_client=redis_client)

    scoring_definition, scoring_capability = layer.capability_registry.resolve(SCORING_CAPABILITY_NAME)
    quality_definition, quality_capability = layer.capability_registry.resolve(QUALITY_CAPABILITY_NAME)
    research_definition, research_capability = layer.capability_registry.resolve(RESEARCH_CAPABILITY_NAME)
    intelligence_definition, intelligence_capability = layer.capability_registry.resolve(INTELLIGENCE_CAPABILITY_NAME)

    assert scoring_definition.name == SCORING_CAPABILITY_NAME
    assert isinstance(scoring_capability, ScoringCapability)
    assert quality_definition.name == QUALITY_CAPABILITY_NAME
    assert isinstance(quality_capability, QualityCapability)
    assert research_definition.name == RESEARCH_CAPABILITY_NAME
    assert isinstance(research_capability, ResearchCapability)
    assert intelligence_definition.name == INTELLIGENCE_CAPABILITY_NAME
    assert isinstance(intelligence_capability, IntelligenceCapability)


def test_no_phase9_test_pairs_real_news_analysis_with_completed_status() -> None:
    """Contract §12/§13's explicit binding statement, checked mechanically: no test *added by
    Phase 9* (M0-M7) may assert that the real `WorkflowType.NEWS_ANALYSIS` reaches
    `TaskStatus.COMPLETED` (per the Plan's own M6/M7 wording: "confirms no test added by
    M6/M7 pairs NEWS_ANALYSIS with COMPLETED"). Scoped to this phase's own new `test_phase9_*`
    files, not the whole pre-existing suite - `tests/test_workflow_runner.py` (Phase 5,
    pre-existing) legitimately drives the real NEWS_ANALYSIS definition to COMPLETED using the
    frozen `DeterministicPlaceholderExecutor` (no real Capability involved at all), which is an
    unrelated, already-existing proof of the mechanical Workflow Engine and not a claim this
    Contract prohibits."""
    tests_dir = Path(__file__).resolve().parent
    offending_files = []
    for path in tests_dir.glob("test_phase9_*.py"):
        if path.name == Path(__file__).name:
            continue  # this file's own docstring/text legitimately names both tokens
        text = path.read_text(encoding="utf-8")
        if "NEWS_ANALYSIS" in text and '"COMPLETED"' in text and "status ==" in text:
            if "test_real_news_analysis_still_fails_at_engagement_analysis_step" not in text:
                offending_files.append(path.name)

    assert offending_files == []
