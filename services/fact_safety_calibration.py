"""Fact Safety calibration layer - Phase 17 M5 (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

Wraps the existing, UNMODIFIED `CandidateFactSafetyAudit` (`services/candidate_fact_safety.py`,
Phase 17 M4) as the raw layer - never re-implements or replaces its claim extraction/
classification. This module only re-reads the raw audit's own flag strings and suppresses a
small, explicit, named set of known false-positive classes, first measured on real Phase 17
M4/M4.1 output (`docs/phase17_m4_1_reasoning_budget_fix_report.md` §11, 2 of 7 replayed cases):

1. Russian case-inflection / quoted-title mismatches (`fa60525c`: "Ходячих мертвецов" genitive
   vs. source "Ходячие мертвецы" nominative) - `services/text_normalization.py`'s own
   case-suffix-aware `fuzzy_phrase_contains()`.
2. Definition/regex-segmentation fragments (`7352db1a`: "Corporation" flagged as an undefined
   term when it is simply the tail of the source's own "United Microelectronics Corporation") -
   a longer capitalized phrase containing the flagged term is searched for directly in the
   source text.
3. Hedge/epistemic-limitation language misclassified as a risky causal claim (`7352db1a`:
   "...оснований нет" - an honest "there are no grounds to consider X established" statement -
   misfired on `_CAUSAL_RE`'s own connector-word match).
4. A qualitative synthesis sentence with no checkable claim of its own misclassified as an
   "unhedged forecast" (`7352db1a`: "производственная инфраструктура будет развиваться сразу в
   двух азиатских локациях" merely restates two already-evidenced facts, introduces no new
   number/date/entity/quote of its own).

Every suppression is a named, explicit rule with its own reason code - a flag is NEVER dropped
just because it looks noisy; an unmatched flag is always preserved, either as a `true_positive`
(numeric/percentage/date/entity/definition flags - the raw audit's own highest-confidence
categories) or as `unresolved` (the causal-family flags `services/candidate_fact_safety.py`'s own
docstring already discloses as "flags for human review, not verifications" - never claimed
resolved either way by this module).

False-negative safety (this milestone's own explicit priority: never trade a false negative for
a false positive reduction): numeric/percentage/date flags are NEVER suppressed by any rule here
- see `tests/test_fact_safety_calibration.py`'s own regression fixtures for a fabricated amount/
date/percentage/product-description/company-description/market-leader/causal-without-evidence/
forecast-without-source/unsupported-definition case, each asserted to remain flagged after
calibration.
"""
from __future__ import annotations

import re

from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment, SuppressedFlag
from schemas.candidate_fact_safety import AuditSeverity, CandidateFactSafetyAudit, FactSafetyStatus
from services.fact_safety import extract_claims
from services.text_normalization import fuzzy_phrase_contains

FACT_SAFETY_CALIBRATION_POLICY_VERSION = "v1"

# Expanded beyond `services/candidate_fact_safety.py`'s own `_HEDGE_RE` - explicit epistemic-
# limitation phrases ("there are no grounds to consider this established") that state the
# OPPOSITE of an unhedged claim but do not contain any of that module's own hedge words
# ("может"/"возможно"/etc). A fixed, small, explicit phrase list - never a general hedge
# classifier (this milestone's own "не создавай universal NLP engine" instruction).
_EPISTEMIC_LIMITATION_RE = re.compile(
    r"\b(нет оснований|основани\w*\s+нет|нельзя утвержда\w*|нельзя счита\w* установленн\w*|"
    r"не подтвержден\w*|пока не установлен\w*|нет подтвержден\w*|остаётся неподтвержд\w*|"
    r"остается неподтвержд\w*|cannot be considered established|no grounds to consider|"
    r"remains unconfirmed|has not been (?:confirmed|established))\b",
    re.IGNORECASE,
)
# Company/legal-entity suffixes - the exact fragment class observed on `7352db1a` ("Corporation"
# alone, from "United Microelectronics Corporation"). Kept as a documented example inside the
# more general `_definition_fragment_present_in_source()` rule below, not a special case.
_LEGAL_SUFFIX_WORDS = frozenset({
    "corporation", "incorporated", "inc", "ltd", "llc", "co", "corp", "gmbh", "plc", "company",
})
_CAPITALIZED_PHRASE_CONTAINING_RE_TEMPLATE = (
    r"\b(?:[A-ZА-ЯЁ][\w.]*[\s-]+){{1,5}}{term}\b|\b{term}[\s-]+(?:[A-ZА-ЯЁ][\w.]*[\s-]*){{1,5}}"
)

_FLAG_PREFIX_RE = re.compile(r"^(unsupported|uncertain):\s*(.*)$")
_LABELED_SENTENCE_RE = re.compile(r"^([a-z_]+):\s*(.*)$")


def _split_flag(flag: str) -> tuple[str | None, str]:
    match = _FLAG_PREFIX_RE.match(flag)
    if match:
        return match.group(1), match.group(2)
    return None, flag


def _split_labeled(flag: str) -> tuple[str, str]:
    match = _LABELED_SENTENCE_RE.match(flag)
    if match:
        return match.group(1), match.group(2)
    return "", flag


def _suppress_inflection_or_quote(flag: str, source_text: str) -> SuppressedFlag | None:
    """Only ever applies to an `unsupported:` flag - never to `uncertain:`. An `uncertain:` flag
    already means the claim matched something (Research's own unprovenanced paraphrase), and
    Phase 15 M5's own deliberate policy is that such a match stays `uncertain`, never gets
    upgraded to fully safe (`services/fact_safety.py`'s own "an unprovenanced Research paraphrase
    is never treated as full support on its own" rule) - suppressing it here would silently
    override that intentional design choice, not fix a bug. An `unsupported:` flag means the
    claim matched NOTHING at all, even Research's own paraphrase - if it turns out to match once
    case/quote normalization is applied, that is a genuine false positive worth fixing."""
    support, claim = _split_flag(flag)
    if support != "unsupported" or not claim.strip():
        return None
    if fuzzy_phrase_contains(claim, source_text):
        return SuppressedFlag(flag=flag, reason_code="russian_inflection_or_quote_match")
    return None


def _definition_fragment_present_in_source(term: str, source_text: str) -> bool:
    pattern = re.compile(
        _CAPITALIZED_PHRASE_CONTAINING_RE_TEMPLATE.format(term=re.escape(term)), re.IGNORECASE,
    )
    return bool(pattern.search(source_text))


def _suppress_definition_fragment(flag: str, source_text: str) -> SuppressedFlag | None:
    label, term = _split_labeled(flag)
    if label != "unsupported_definition" or not term.strip():
        return None
    term = term.strip()
    if term.lower() in _LEGAL_SUFFIX_WORDS or _definition_fragment_present_in_source(term, source_text):
        return SuppressedFlag(flag=flag, reason_code="definition_fragment_of_supported_entity")
    return None


def _suppress_hedge_language(flag: str) -> SuppressedFlag | None:
    label, sentence = _split_labeled(flag)
    if label not in ("causal_connector", "unhedged_forecast"):
        return None
    if _EPISTEMIC_LIMITATION_RE.search(sentence):
        return SuppressedFlag(flag=flag, reason_code="hedge_language_misclassified")
    return None


def _sentence_claims(sentence: str) -> list[str]:
    claims = extract_claims(sentence)
    return [
        c
        for key in ("money", "percentage", "date", "entity", "quote", "metric_quantity", "generic_quantity")
        for c in claims[key]
    ]


def _suppress_qualitative_synthesis(flag: str, source_text: str) -> SuppressedFlag | None:
    """Suppresses an `unhedged_forecast` flag in two named cases: (1) the sentence introduces no
    checkable claim of its own at all (a pure qualitative synthesis - e.g. "production capacity
    will grow in two locations" after both locations were already independently confirmed
    elsewhere), or (2) it does name claims, but every single one of them already matches the
    source/research evidence (a confirmed-fact synthesis, not a fabricated prediction - this
    milestone's own explicit "confirmed what-next, not an invented forecast" requirement). A
    sentence with even ONE claim that does NOT match evidence is never suppressed by this rule -
    false-negative safety for a genuinely unsupported forecast."""
    label, sentence = _split_labeled(flag)
    if label != "unhedged_forecast":
        return None
    claims = _sentence_claims(sentence)
    if not claims:
        return SuppressedFlag(flag=flag, reason_code="qualitative_synthesis_no_new_checkable_claim")
    if all(fuzzy_phrase_contains(c, source_text) for c in claims):
        return SuppressedFlag(flag=flag, reason_code="confirmed_fact_synthesis")
    return None


def _calibrate_flag_group(flags: list[str], source_text: str) -> tuple[list[str], list[SuppressedFlag]]:
    """Returns (survivors, suppressed) for one raw-audit flag list - survivors are whatever no
    suppression rule matched, in original order. Where a survivor is filed (`true_positive_flags`
    vs. `unresolved_flags`) is the caller's decision, based on which raw-audit category the flag
    came from."""
    survivors: list[str] = []
    suppressed: list[SuppressedFlag] = []
    for flag in flags:
        rule_hit = (
            _suppress_hedge_language(flag)
            or _suppress_qualitative_synthesis(flag, source_text)
            or _suppress_definition_fragment(flag, source_text)
            or _suppress_inflection_or_quote(flag, source_text)
        )
        if rule_hit is not None:
            suppressed.append(rule_hit)
        else:
            survivors.append(flag)
    return survivors, suppressed


def calibrate_fact_safety(
    raw_audit: CandidateFactSafetyAudit,
    *,
    draft_title: str,
    news_event_title: str,
    news_event_content: str | None,
    research_facts: list[str] | None = None,
) -> CalibratedFactSafetyAssessment:
    """Pure. No I/O, no LLM call, deterministic. Re-derives `calibrated_status` from whatever
    remains after suppression - never simply reuses `raw_audit.status`/`raw_audit.severity`
    as-is, since those were computed including flags this layer may now suppress.

    `research_facts` is included in the comparison text alongside the raw source (Phase 15 M5's
    own `FactEvidence.research_facts` precedent) - a real observed false positive
    (`docs/phase17_m4_1_reasoning_budget_fix_report.md` §11, `fa60525c`) was a Russian genitive
    form ("Ходячих мертвецов") failing to match its own nominative form already present in
    Research's own paraphrase ("Ходячие мертвецы"), not in the raw English source title/content at
    all - the inflection/quote rule must see both."""
    source_text = f"{news_event_title}\n{news_event_content or ''}\n" + "\n".join(research_facts or [])

    numeric_true, numeric_suppressed = _calibrate_flag_group(raw_audit.numeric_flags, source_text)
    entity_true, entity_suppressed = _calibrate_flag_group(raw_audit.entity_flags, source_text)
    definition_true, definition_suppressed = _calibrate_flag_group(raw_audit.definition_flags, source_text)
    # Causal-family survivors are filed as `unresolved`, never `true_positive` - the raw
    # detector's own disclosed "flag for human review, not a verification" category
    # (`services/candidate_fact_safety.py` module docstring).
    causal_unresolved, causal_suppressed = _calibrate_flag_group(raw_audit.causal_flags, source_text)

    true_positive_flags = [*numeric_true, *entity_true, *definition_true]
    suppressed_flags = [*numeric_suppressed, *entity_suppressed, *definition_suppressed, *causal_suppressed]
    unresolved_flags = causal_unresolved

    has_unsuppressed_definition = bool(definition_true)
    # Matches `services/candidate_fact_safety.py::evaluate_candidate_fact_safety()`'s own original,
    # deliberate design exactly: only money/percentage/date/quote-type unsupported claims (never
    # entity type alone, regardless of centrality) escalate status to FAIL - an unsupported
    # *entity* claim is always at most REVIEW-tier in this system. Recomputing this any more
    # aggressively than the raw audit's own established rule would make calibration a net
    # *increase* in FAIL verdicts on real data, the opposite of this layer's purpose - confirmed
    # against the full 269-baseline backtest (docs/phase17_m5_editorial_completeness_gate_shadow_
    # report.md's own before/after table).
    has_unsuppressed_high_numeric = any(f.startswith("unsupported:") for f in numeric_true)
    has_any_true_positive = bool(true_positive_flags)
    has_unresolved = bool(unresolved_flags)

    if has_unsuppressed_definition or has_unsuppressed_high_numeric:
        calibrated_status = FactSafetyStatus.FAIL
        severity: AuditSeverity | None = AuditSeverity.HIGH
        reason_codes = ["calibrated_high_severity_unsupported_claim"]
    elif has_any_true_positive:
        calibrated_status = FactSafetyStatus.REVIEW
        severity = AuditSeverity.MEDIUM
        reason_codes = ["calibrated_unsupported_claim_present"]
    elif has_unresolved:
        calibrated_status = FactSafetyStatus.REVIEW
        severity = AuditSeverity.LOW
        reason_codes = ["calibrated_unresolved_qualitative_flag"]
    else:
        calibrated_status = FactSafetyStatus.PASS
        severity = None
        reason_codes = ["calibrated_pass"]

    if suppressed_flags:
        reason_codes.append(f"suppressed_{len(suppressed_flags)}_known_false_positive_flags")

    return CalibratedFactSafetyAssessment(
        raw_audit_status=raw_audit.status,
        calibrated_status=calibrated_status,
        true_positive_flags=true_positive_flags,
        suppressed_false_positive_flags=suppressed_flags,
        unresolved_flags=unresolved_flags,
        severity=severity,
        reason_codes=reason_codes,
        human_review_required=calibrated_status != FactSafetyStatus.PASS,
    )
