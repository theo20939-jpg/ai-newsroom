"""Shared canonical Research output shape - Phase 9 M4.

`tests/test_research_capability.py`'s own happy-path test asserts
`ResearchCapability.execute()`'s `structured_output` matches this exact constant's shape.
`tests/test_intelligence_capability.py` (M5) imports and reuses this same constant to seed
`step_results["research"]`, so a future change to Research's real output shape that breaks
Intelligence's assumption shows up as a test failure in M5's own suite the moment this
constant changes, not only once M7's full integration proof eventually runs it for real
(docs/phase9_implementation_planning_audit.md MINOR finding 2)."""

CANONICAL_RESEARCH_OUTPUT: dict[str, object] = {
    "facts": ["<example fact 1>", "<example fact 2>"],
    "confidence": 0.8,
    "gaps": [],
}
