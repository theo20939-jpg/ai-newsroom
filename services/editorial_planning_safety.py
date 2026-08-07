"""Phase 19 M3: deterministic post-generation safety checks for an Editorial Plan
(prompts/editorial_planning/v1.yaml's output) - never trusted on the model's own word alone,
mirroring services/content_quality_gates.py's own established "LLM output, then a deterministic
gate" pattern.

The five required safety properties, each enforced by its own small, independently-testable
function: no unsupported facts, no invented context, no speculative competitive claims, no
fabricated implications, and the quote-must-exist-in-evidence hard check. Reuses
services/text_normalization.py exactly as services/quote_verification.py already does - no new
NLP machinery.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.content_quality_gates import _UNSUPPORTED_SUPERLATIVES
from services.quote_verification import verify_quote
from services.text_normalization import token_overlap_ratio

# Grounding check: a plan field claiming to be evidence-derived must show at least some lexical
# overlap with the evidence text it was supposedly grounded in - a low-cost, narrow, deterministic
# approximation of "is this actually grounded," never a semantic/LLM-based fact-check (this
# module's own established "no new NLP machinery" discipline). Deliberately permissive (a low
# threshold) - this is a coarse safety net against wholesale fabrication, not a precision grader.
_MIN_GROUNDING_OVERLAP = 0.05

# Phrases indicating an unsupported "competitive"/comparative claim not itself covered by
# content_quality_gates.py's own superlative lexicon (narrower, editorial-planning-specific).
_COMPETITIVE_CLAIM_PHRASES = (
    "outperforms", "beats the competition", "no other company", "unlike its rivals",
    "превосходит конкурентов", "лучше, чем у конкурентов",
)


@dataclass(frozen=True)
class PlanSafetyReport:
    grounding_supported: bool = True
    no_competitive_claims: bool = True
    quote_exists_in_evidence: bool = True
    what_remains_unknown_present: bool = True
    failed_checks: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failed_checks


def check_grounding_supported(plan: dict, evidence_text: str) -> bool:
    """Coarse, deterministic approximation: central_fact must show at least some lexical overlap
    with the evidence it claims to summarize - never a semantic fact-check, only a guard against
    a central_fact that shares essentially no vocabulary with the source at all (the cheapest,
    most reliable signal of wholesale fabrication available without a new NLP dependency)."""
    central_fact = plan.get("central_fact")
    if not isinstance(central_fact, str) or not central_fact.strip():
        return False
    if not evidence_text.strip():
        return True  # nothing to ground against (e.g. HEADLINE_ONLY) - not this check's job to fail
    return token_overlap_ratio(central_fact, evidence_text) >= _MIN_GROUNDING_OVERLAP


def check_no_competitive_claims(plan: dict) -> bool:
    """Reuses content_quality_gates.py's own superlative lexicon plus a narrow, editorial-
    planning-specific competitive-claim phrase list - never a second, divergent implementation of
    the shared superlative check."""
    text_fields = [
        plan.get("central_fact"), plan.get("what_is_new"), plan.get("why_it_matters"),
        plan.get("headline_emphasis"), plan.get("opening_emphasis"),
    ]
    combined = " ".join(f for f in text_fields if isinstance(f, str)).lower()
    if any(phrase in combined for phrase in _UNSUPPORTED_SUPERLATIVES):
        return False
    return not any(phrase in combined for phrase in _COMPETITIVE_CLAIM_PHRASES)


def check_quote_exists_in_evidence(plan: dict, quote_candidates: list[str], evidence_text: str) -> bool:
    """Hard check: verified_quote_text may not enter the plan unless it is actually present,
    verbatim, in the supplied evidence - reuses services/quote_verification.py::verify_quote()
    exactly, never a second, divergent quote-verification implementation."""
    quote_text = plan.get("verified_quote_text")
    if quote_text is None:
        return True
    if not isinstance(quote_text, str):
        return False
    if quote_candidates and any(verify_quote(quote_text, candidate) for candidate in quote_candidates):
        return True
    return verify_quote(quote_text, evidence_text)


def check_what_remains_unknown_present(plan: dict) -> bool:
    """what_remains_unknown may legitimately be null (evidence genuinely complete) - this check
    only guards against the field being entirely absent from a well-formed plan, mirroring
    content_quality_gates.py::check_why_it_matters_present()'s own "field must exist, may be
    null" convention."""
    return "what_remains_unknown" in plan


def evaluate_plan_safety(
    plan: dict, *, evidence_text: str, quote_candidates: list[str] | None = None
) -> PlanSafetyReport:
    """Pure. Combines every individual check above into one report - never blocks by itself; the
    caller (capabilities/executor.py's shadow-mode hook, or the offline comparison script) decides
    what to do with a failing report (drop the quote field, log, route to review)."""
    candidates = quote_candidates or []
    checks = {
        "grounding_supported": check_grounding_supported(plan, evidence_text),
        "no_competitive_claims": check_no_competitive_claims(plan),
        "quote_exists_in_evidence": check_quote_exists_in_evidence(plan, candidates, evidence_text),
        "what_remains_unknown_present": check_what_remains_unknown_present(plan),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return PlanSafetyReport(
        grounding_supported=checks["grounding_supported"],
        no_competitive_claims=checks["no_competitive_claims"],
        quote_exists_in_evidence=checks["quote_exists_in_evidence"],
        what_remains_unknown_present=checks["what_remains_unknown_present"],
        failed_checks=failed,
    )
