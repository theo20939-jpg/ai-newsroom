"""DIRECTOR-CONTROL-PLANE-1 §8-13: real Editorial Gate shadow orchestration - assembles an
`EditorialGateInput` from whatever real signals are already available at worker/content_cycle.py's
own presentation-decision call site (mirrors services/telegram_channel_director_shadow.py's own
exact "advisory visibility only, no runtime effect" precedent) and logs the resulting
`GateOutcome`.

HONEST SCOPE LIMITATION (this phase's own final report explains this in full): this call site sits
AFTER Story selection/research/copywriting has already run (the same point Channel Director shadow
already occupies), not before - a true pre-generation gate that actually withholds DROP/HOLD
candidates from ever reaching copywriting (spec §36's own cost-reduction goal) would require
restructuring worker/content_cycle.py's own earlier candidate-selection loop, out of scope for a
safe change to an already-`enforce`-mode production hot path in this phase. `settings.telegram_
editorial_gate_enabled` therefore currently gates nothing observable yet (shadow only, matching
spec §12's own "When OFF: shadow decision only" - this phase never reaches the "When ON" branch);
`services/director_editorial_gate.py`'s own real decision logic, persistence, HOLD queue, and
Founder override are all real and tested, ready for a future phase to wire earlier in the pipeline.

Novelty/duplication signals are NOT independently computed here (no real Story-level novelty
model exists in this codebase yet) - `is_duplicate_of_recent`/`novelty_score` use the same
conservative defaults `services/telegram_channel_director_shadow.py` already accepted for
campaign relevance ("advisory visibility only, never fabricated certainty")."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.director_editorial_gate import EditorialGateInput, GateOutcome, evaluate_editorial_gate
from services.strategic_directive_service import list_active_directives

logger = logging.getLogger(__name__)


async def run_editorial_gate_shadow(
    session: AsyncSession, *, story_id: str, event_id: str, platform: str, category: str,
    has_sufficient_facts: bool, source_confidence: float, now: datetime,
) -> GateOutcome | None:
    """Returns None (no-op) when `telegram_editorial_gate_enabled` is False - the default. Never
    raises past this point; the caller in worker/content_cycle.py additionally wraps this in its
    own try/except as defense in depth, matching run_channel_director_shadow()'s own identical
    precedent."""
    if not settings.telegram_editorial_gate_enabled:
        return None

    active_directives = await list_active_directives(session, now=now)
    gate_input = EditorialGateInput(
        story_id=story_id, event_id=event_id, platform=platform, category=category,
        topic_keywords=[category], story_facts_summary="", has_sufficient_facts=has_sufficient_facts,
        source_confidence=source_confidence,
        # Conservative, honest defaults - no real novelty/duplication model is wired at this call
        # site yet (module docstring). novelty_score=0.5 is neutral (neither low nor high novelty
        # gates ever trigger from this default alone); is_duplicate_of_recent=False never causes a
        # false DROP.
        novelty_score=0.5, is_duplicate_of_recent=False, recency_hours=0.0,
        active_directives=list(active_directives), active_campaign_relevant=False,
    )
    outcome = evaluate_editorial_gate(gate_input)
    logger.info(
        "director_editorial_gate_shadow decision=%s priority=%d reasons=%s (shadow only - no runtime effect)",
        outcome.decision.value, outcome.priority, [c.value for c in outcome.reason_codes],
    )
    return outcome
