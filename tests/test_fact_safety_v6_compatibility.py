"""Phase 21 - V6 Copywriting / Fact Safety compatibility.

Written test-first (docs/phase21_v6_fact_safety_report.md's own baseline section records the
exact pre-fix failures these cases produced): before this milestone, `apply_fact_safety()` reads
`copywriting_output["title"]`/`["body"]` only (V4's own schema) and silently returns
`structured_output` completely unchanged - no "fact_safety" key, no log, no error - whenever
`body` is absent, which is true for every V6 draft (`prompts/copywriting/v6.yaml`'s real
`output_schema` has no `body` key: `title, opening, context, why_it_matters, what_changed,
what_happens_next, conclusion, what_remains_unknown, quote`).

Four cases, exactly as specified:
- CASE 1: V4 `{title, body}` -> Fact Safety runs normally (unchanged behavior, regression guard).
- CASE 2: V6 `{title, opening, context, why_it_matters, what_changed, what_happens_next,
  conclusion, what_remains_unknown, quote}` -> Fact Safety runs normally (the actual fix).
- CASE 3: a genuinely unsupported Copywriting schema -> explicit, logged failure/fallback -
  never a silent pass, never a silent no-op.
- CASE 4: a Story Memory prior-coverage update scenario (old story facts already known, new V6
  draft states a materially new fact not in the old facts) -> Fact Safety receives the *complete*
  V6 draft text (every section, not just one field) and correctly classifies the new fact against
  the supplied evidence.

Real V6 schema fields are used throughout (verified directly against `prompts/copywriting/
v6.yaml`, not assumed from any paraphrase) - `what_changed`/`what_happens_next`/
`what_remains_unknown`, not "details".
"""
from core.config import settings
from services.fact_safety import apply_fact_safety


def _v6_output(**overrides: object) -> dict[str, object]:
    """A realistic, fully-populated V6 Copywriting output - every non-null field a real V6 draft
    produces, per `prompts/copywriting/v6.yaml`'s own `required` list (only `what_happens_next`/
    `what_remains_unknown`/`quote` are genuinely nullable)."""
    base: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "opening": "OpenAI released a new flagship model on Thursday.",
        "context": "The company has shipped a major model roughly every year since 2023.",
        "why_it_matters": "The release raises the bar for reasoning benchmarks industry-wide.",
        "what_changed": "The new model scores 92% on the industry's standard reasoning benchmark.",
        "what_happens_next": None,
        "conclusion": "The model is available to developers starting today.",
        "what_remains_unknown": None,
        "quote": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CASE 1 - V4 {title, body} still runs normally (regression guard, unchanged behavior)
# ---------------------------------------------------------------------------


def test_case_1_v4_body_schema_runs_fact_safety_normally(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = {"title": "X", "body": "OpenAI released a new model"}
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday.",
        None, {}, copywriting_output, quality_output,
    )
    assert "fact_safety" in out
    assert out["fact_safety"]["status"] in ("pass", "review", "block")
    assert out["fact_safety"]["version"] == "v1"


# ---------------------------------------------------------------------------
# CASE 2 - V6 {opening, context, why_it_matters, what_changed, conclusion, ...} runs normally
# ---------------------------------------------------------------------------


def test_case_2_v6_schema_runs_fact_safety_normally(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = _v6_output()
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday, scoring 92% on the benchmark.",
        None, {}, copywriting_output, quality_output,
    )
    assert "fact_safety" in out, "V6 output must no longer silently no-op"
    assert out["fact_safety"]["status"] in ("pass", "review", "block")
    assert out["fact_safety"]["version"] == "v1"
    # The 92% benchmark claim lives only in `what_changed` - proves the full V6 draft (not just
    # one field) was actually concatenated and checked, not merely `title` alone.
    assert out["fact_safety"]["claims_checked"] >= 1


def test_case_2_v6_schema_checks_claims_from_every_section_not_just_one_field(monkeypatch) -> None:
    """A fabricated claim placed only in `conclusion` (a section with no analogue in V4's single
    `body` field) must still be caught - proves the fix concatenates the whole draft, not just
    title+one-field."""
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = _v6_output(
        conclusion="The deal was worth $4.2 billion, the largest in the company's history.",
    )
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday.",
        None, {}, copywriting_output, quality_output,
    )
    findings = out["fact_safety"]["findings"]
    assert any(f["type"] == "money" for f in findings), (
        f"expected the unsupported $4.2 billion claim in `conclusion` to be found; got {findings}"
    )
    assert out["fact_safety"]["status"] in ("review", "block")


# ---------------------------------------------------------------------------
# CASE 3 - a genuinely unsupported schema fails explicitly, never silently passes
# ---------------------------------------------------------------------------


def test_case_3_unsupported_schema_never_silently_passes(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    # Neither V4's `body` nor V6's required text fields are present - a hypothetical future/
    # malformed schema this code has never been taught to understand.
    copywriting_output = {"title": "X", "summary_blob": "OpenAI released a new model"}
    quality_output = {"passed": True, "issues": []}
    with caplog.at_level("WARNING"):
        out = apply_fact_safety(
            "OpenAI announces new model", "OpenAI announced a new model on Thursday.",
            None, {}, copywriting_output, quality_output,
        )
    assert "fact_safety" in out, "must never silently omit the key - that is indistinguishable from success"
    assert out["fact_safety"]["status"] == "skipped"
    assert out["fact_safety"]["reason"] == "unsupported_copywriting_schema"
    assert any("unsupported" in record.message.lower() for record in caplog.records), (
        "an unsupported schema must be logged, never silent"
    )
    # Quality's own original fields must still be preserved (this function must never break the
    # step even when it cannot validate the draft).
    assert out["passed"] is True


def test_case_3_unsupported_schema_missing_title_also_fails_explicitly(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = {"body": "OpenAI released a new model"}  # no title at all
    quality_output = {"passed": True, "issues": []}
    with caplog.at_level("WARNING"):
        out = apply_fact_safety(
            "OpenAI announces new model", "OpenAI announced a new model on Thursday.",
            None, {}, copywriting_output, quality_output,
        )
    assert out["fact_safety"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# CASE 4 - Story Memory update context: old facts + new V6 draft -> Fact Safety sees the whole text
# ---------------------------------------------------------------------------


def test_case_4_story_memory_update_context_v6_draft_checked_against_prior_facts(monkeypatch) -> None:
    """Simulates a real story-update scenario: Research's `research_output["facts"]` already
    contains a fact from the *prior* coverage of this story (as Story Memory's own prior-coverage
    context would surface); the new V6 draft's `what_changed` section states a genuinely new,
    unsupported number that appears in neither the prior facts nor the source. Fact Safety must
    receive the complete V6 draft text (not just `title`) and correctly flag the new, unsupported
    claim - proving the V6 compatibility fix also works end-to-end with Story Memory's own
    upstream context, not just in isolation."""
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    research_output = {"facts": ["OpenAI released its previous flagship model in late 2025."]}
    copywriting_output = _v6_output(
        opening="OpenAI has expanded its flagship model lineup with a new release.",
        what_changed="The new model was trained on a $9.3 million compute budget, the company said.",
    )
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday, its second this year.",
        None, research_output, copywriting_output, quality_output,
    )
    assert "fact_safety" in out
    findings = out["fact_safety"]["findings"]
    assert any(f["type"] == "money" and f["support"] == "unsupported" for f in findings), (
        f"the new $9.3 million claim (in what_changed, absent from source/research) must be "
        f"flagged unsupported; got {findings}"
    )
