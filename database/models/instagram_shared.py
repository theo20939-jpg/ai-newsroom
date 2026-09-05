"""Shared enum(s) reused across more than one Instagram model/service - mirrors
database/models/business_context_shared.py's own exact purpose and reasoning: kept in one place so
the semantics can never drift between instagram_audience_memory.py/instagram_hook_memory.py/
instagram_reference_deconstruction_memory.py (and services/instagram_content_brain.py, which
imports this rather than defining its own copy). Each model still maps its own column to its own
named Postgres enum type."""
import enum


class IntelligenceEvidenceStage(str, enum.Enum):
    """INSTAGRAM-GROWTH-3, spec item 3: OBSERVATION -> HYPOTHESIS/POSSIBLE_SIGNAL ->
    REPEATED_PATTERN -> STABLE_WORKING_RULE for QUALITATIVE persisted intelligence (audience
    insights, hook mechanic notes, reference deconstructions) - distinct from
    services/instagram_content_brain.py::EvidenceStage (ANOMALY..STABLE_WORKING_RULE), which stays
    reserved for sample-size/repeatability/recency-driven PerformancePattern evidence and is left
    untouched (no redesign of the accepted architecture)."""

    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN = "repeated_pattern"
    STABLE_WORKING_RULE = "stable_working_rule"
