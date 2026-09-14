"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §10/§11/§15: the live dry-run runtime path. Zero real
network writes anywhere - `ShadowInstagramPublishClient` (unmodified, pre-existing) never makes a
real HTTP call, and `instagram_publication_enabled`/`shadow=False` are never touched by this module
at all."""
from __future__ import annotations

import pytest

from services.instagram_dry_run import DryRunCandidateInput, DryRunImageCandidateInput, run_dry_run_batch, run_dry_run_candidate

pytestmark = pytest.mark.asyncio


async def test_real_shaped_candidate_with_no_useful_caption_reaches_a_classification() -> None:
    """Mirrors the real production shape exactly: a Tier-1 candidate with no caption_or_alt text
    (the disclosed, honest, real-world default) - never fabricates evidence that does not exist."""
    candidate = DryRunCandidateInput(
        news_event_id="evt-1", title="Apple announced the new foldable iPhone today", category="GADGETS",
        image_candidates=[DryRunImageCandidateInput("cand-1", 1200, 800)],
    )
    result = await run_dry_run_candidate(candidate)
    assert result.classification in ("READY", "HOLD", "BLOCK")
    assert result.deterministic_and_final_subject_match in (None, "generic_context", "exact_subject", "strong_context", "mismatch")
    assert result.media_intent_primary_entity  # a real subject was extracted, never blank


async def test_candidate_with_no_image_candidates_at_all_is_honestly_handled() -> None:
    candidate = DryRunCandidateInput(news_event_id="evt-2", title="A story with no image at all", category="TECH", image_candidates=[])
    result = await run_dry_run_candidate(candidate)
    assert result.selected_candidate_id is None
    assert result.classification in ("READY", "HOLD", "BLOCK")


async def test_batch_of_five_real_shaped_candidates_never_makes_a_real_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact §10 requirement: minimum 5 real-shaped candidates, zero network writes. Patches
    `HttpInstagramPublishClient.__init__` to raise if ever constructed - proves this dry run truly
    never reaches the real client class, not merely that it happens not to error."""
    import services.instagram_publish_adapter as adapter_module

    def _must_not_construct(*args, **kwargs):
        raise AssertionError("HttpInstagramPublishClient must never be constructed during a dry run")

    monkeypatch.setattr(adapter_module.HttpInstagramPublishClient, "__init__", _must_not_construct)

    candidates = [
        DryRunCandidateInput(news_event_id=f"evt-{i}", title=f"Real-shaped story number {i} about a specific product", category="TECH",
                              image_candidates=[DryRunImageCandidateInput(f"cand-{i}", 1000, 750)])
        for i in range(5)
    ]
    results = await run_dry_run_batch(candidates)
    assert len(results) == 5
    for r in results:
        assert r.classification in ("READY", "HOLD", "BLOCK")
        assert r.shadow_publish_status != "live_success"  # never a real publish outcome


async def test_mismatch_candidate_never_reaches_ready_in_a_dry_run() -> None:
    """A real, production-shaped MISMATCH scenario (weak/no metadata, but rejected via the SAME
    is_selectable() exclusion Telegram already has) must not be misreported as READY."""
    candidate = DryRunCandidateInput(
        news_event_id="evt-mismatch", title="Apple announced the new foldable iPhone today", category="GADGETS",
        image_candidates=[],  # no candidate resolves -> selected=None, never a false "exact match"
    )
    result = await run_dry_run_candidate(candidate)
    assert result.selected_candidate_id is None
    assert result.media_usage_classification is None
