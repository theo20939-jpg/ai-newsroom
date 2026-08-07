"""Phase 19 M3: proves scripts.phase19_m3_editorial_plan_comparison.run_comparison_for_event()
refuses to run outside editorial_planning_mode == "comparison" - the concrete enforcement of "no
paid comparison run without separate authorization," not just a docstring claim. No real network/
LLM/DB call is exercised by this test - it must fail before reaching any of them.
"""
from uuid import uuid4

import pytest

from core.config import settings
from scripts.phase19_m3_editorial_plan_comparison import (
    ComparisonModeNotEnabledError,
    run_comparison_for_event,
)


@pytest.mark.asyncio
async def test_refuses_to_run_when_mode_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_planning_mode", "off")
    with pytest.raises(ComparisonModeNotEnabledError):
        await run_comparison_for_event(uuid4())


@pytest.mark.asyncio
async def test_refuses_to_run_when_mode_is_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_planning_mode", "shadow")
    with pytest.raises(ComparisonModeNotEnabledError):
        await run_comparison_for_event(uuid4())
