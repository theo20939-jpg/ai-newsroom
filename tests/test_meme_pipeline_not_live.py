"""Phase 18.10 M8/M10: defense-in-depth regression guarding the meme-pipeline audit's own
finding (docs/phase18_10_meme_pipeline_audit.md) - no live worker/orchestrator code path may
create a MEME_GENERATION EditorialTask. This does not test the meme pipeline's own correctness
(that's covered by its existing, isolated unit/integration tests) - it only guarantees the single
property this phase's M10 requires: "no accidental MEME_GENERATION activation exists." A source-
text scan, mirroring the established pattern in
tests/test_api_cost_optimization_checklist.py::test_collector_module_has_no_llm_gateway_or_budget_dependency
- fast, no DB/network, and it fails loudly the moment anyone adds a live trigger without updating
this test deliberately.
"""
from pathlib import Path

# Every module that is actually reachable from a running container in this project (worker
# entrypoints, the orchestrator that creates real EditorialTasks, and the live content-generation
# script) - deliberately NOT capabilities/workflows/services modules that implement the meme
# pipeline itself, since those are expected and allowed to mention MEME_GENERATION; this test
# only cares whether any *live trigger* exists.
_LIVE_ENTRYPOINT_MODULES = (
    "worker/analysis_main.py",
    "worker/analysis_cycle.py",
    "worker/content_main.py",
    "worker/content_cycle.py",
    "services/triage_orchestrator.py",
    "scripts/run_content_generation.py",
)


def test_no_live_entrypoint_creates_a_meme_generation_task() -> None:
    for relative_path in _LIVE_ENTRYPOINT_MODULES:
        source_text = Path(relative_path).read_text(encoding="utf-8")
        assert "MEME_GENERATION" not in source_text, (
            f"{relative_path} references MEME_GENERATION - this would mean a live code path can "
            "create a MEME_GENERATION task, contradicting docs/phase18_10_meme_pipeline_audit.md's "
            "own finding and this phase's explicit 'no accidental activation' requirement. If this "
            "changed intentionally, meme_opportunity_mode/meme_safety_gate_mode's live-mode "
            "consequences must be re-reviewed before this assertion is relaxed."
        )


def test_bot_meme_preview_handler_does_not_trigger_generation() -> None:
    """The one meme-adjacent module reachable from the live Telegram bot - confirms its own
    documented behavior (admin-facing decision buttons only, no generation re-run) directly,
    rather than relying solely on its docstring."""
    source_text = Path("bot/handlers/meme_preview.py").read_text(encoding="utf-8")
    assert "create_task" not in source_text
    assert "MEME_GENERATION" not in source_text or "no live MEME_GENERATION" in source_text
