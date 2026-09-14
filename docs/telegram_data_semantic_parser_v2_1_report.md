# TELEGRAM-DATA-SEMANTIC-PARSER-V2-1

A second, independently-discovered instance of the DATA-hero unit/label-corruption defect class:
a real Telegram DATA card (title "NASA и IBM представили открытую ИИ-модель для поиска льда на
Луне") built by the **old, pre-ASML-hotfix, actually-deployed-to-production** code escaped with
value "20" correct, but a comparison clause absorbed into the unit ("% ТОЧНЕЕ СПЕЦИА...") and a
sentence-fragment label ("ПОКАЗАТЕЛЬ МОДЕЛЬ СПОСОБНА ВЫЯВЛЯТЬ..."). Confirmed via clarification
with the Founder: `feature/telegram-data-semantic-overflow-hotfix-1` (commit `45de6d4`) was **never
deployed to production** — the NASA card is a second, independent discovery of the same defect
*class*, not a post-45de6d4 regression. This phase generalizes the fix the ASML hotfix's own brief
explicitly deferred: a bounded comparator/direction vocabulary that never enters `unit`, comparator-
driven metric-kind derivation, and two independent, final semantic-safety validators.

Branch: `feature/telegram-data-semantic-parser-v2-1`
Base: `45de6d4` (`feature/telegram-data-semantic-overflow-hotfix-1`)

**No production deploy in this phase** (per its own explicit scope) — code, tests, visual artifacts,
report, pushed branch only.

---

## A. Real NASA production regression

The delivered card is a real Telegram post built by the code actually live in production at the
time (pre-45de6d4). Reproduced through the real production entrypoint,
`build_structured_data_content()`, loaded directly from git commit `39f764b` (the actual pre-ASML-
hotfix production code, not hand-simulated) — see `artifacts/telegram_data_semantic_parser_v2_1/
BEFORE_NASA.jpg`, rendered by the real, unmodified old `render_data_hero_card()`.

```
PRE_FIX_VALUE       = "20"
PRE_FIX_UNIT        = "% точнее специализированных моделей, обу"     (40-char arbitrary scan)
PRE_FIX_LABEL       = "Показатель Модель способна выявлять водяной лёд более чем на точнее специализированных моде"
PRE_FIX_SUBJECT     = "Модель способна выявлять водяной лёд более чем на точнее специализированных моде"
```

`BEFORE_NASA.jpg` visually reproduces every symptom named in the brief: giant red comparison-clause
text overflowing the canvas edge, and a malformed white label reading as a sentence fragment.

`NASA_PRE_FIX_REPRODUCED = true`

## B. Current-head reproduction

Reproduced the SAME NASA fact against the CURRENT (post-ASML-hotfix, pre-this-phase) code at HEAD
`45de6d4` — the ASML hotfix's already-general "change unit never absorbs trailing prose" fix
already prevents the unit-overflow for this case too:

```
value  = "20"
unit   = "%"                (already correct - no overflow)
label  = "Показатель"        (safe, but the comparison "точнее" is simply discarded - no metric-kind signal)
subject = ""
```

So at `45de6d4`, the NASA card would already render safely, just uninformatively (no comparator/
metric-kind captured at all). This phase's actual gap to close: comparator extraction, comparator-
driven metric-kind derivation, and adding independent semantic-safety validators as defense-in-
depth (the ASML hotfix's brief explicitly deferred exactly this generalization).

## C. Root cause

Traced the full production path (`evidence fact -> _find_data_candidate (legacy grounding) ->
build_structured_data_content -> value/unit/subject/metric_kind/label -> render_data_hero_card ->
RenderEvidence -> quality.py -> Telegram delivery`):

- At the OLD (pre-45de6d4) code: `_extract_full_unit_text()`'s 40-character arbitrary scan and
  `_extract_subject_from_title() or legacy.label`'s sentence fallback (the SAME two root causes the
  ASML hotfix fixed generically) reproduce identically for NASA.
- At the CURRENT (`45de6d4`) code: no remaining leak point exists for *unit* or *label* prose (the
  ASML fix is already general enough) — but there was no representation for a **comparison**
  (точнее/быстрее/etc.) at all: it was simply invisible to the metric-kind classifier, so the label
  fell back to the fully generic "Показатель" with no evidence-supported specificity, and there was
  no independent, FINAL safety check verifying that whatever `metric_unit`/`metric_label` ended up
  being was actually safe (correct-by-construction only, no defense-in-depth).

`services/brand_renderer.py` and `services/render_evidence.py` needed no changes for the NASA case
itself — the ASML hotfix's fail-closed geometry guard and truthful `RenderEvidence` already cover
any residual overflow (proven in §L below with a synthetic pathological case).

## D. Semantic model

Kept intentionally small (per the brief's own "do not create a broad framework" instruction) —
extended `services/editorial_pipeline/content.py`'s existing procedural pipeline rather than
introducing a new dataclass/module:

- `value`/`unit`/`subject`/`label` — unchanged shape from the ASML hotfix.
- `comparator` — NEW: a bounded, closed-vocabulary extraction (`_extract_comparator()`), stored in
  `StructuredDataContent.comparison` — a field that **already existed** in `contracts.py` (declared,
  always `None` before this phase, never consumed downstream) — populating it is the smallest
  possible extension of the existing contract, not a schema change.
- `metric_kind` — extended (`_classify_metric_kind()`) with a comparator-driven branch, checked
  LAST (after every more specific evidence-word signal), so a comparator only ever fills in a kind
  when nothing more specific already grounded one.
- Two NEW, independent, FINAL safety validators (`_is_unit_safe()`, `_is_label_safe()`) gate
  `build_structured_data_content()`'s own return value.

## E. Unit grammar

`_extract_full_unit_text()` is **unchanged** from the ASML hotfix (already correct: a change unit
like `%` never scans past the bare token at all). What's NEW is the independent, FINAL invariant
check, `_is_unit_safe()`:

```python
_UNIT_SAFE_RE = re.compile(rf"^(?:{_MAGNITUDE_UNIT})(?:\s+{_EXTENDED_CURRENCY_WORD})?$", re.IGNORECASE)

def _is_unit_safe(unit: str) -> bool:
    if unit in ("", "раза"):
        return True
    if _is_change_unit(unit):
        return True
    return bool(_UNIT_SAFE_RE.match(unit.strip()))
```

Built from the SAME bounded magnitude/currency grammar that can legitimately produce a unit (reused
from `presentation_director._MAGNITUDE_UNIT` and this module's own `_EXTENDED_CURRENCY_WORD`) —
never a second, independently-drifting vocabulary — so it can never reject a unit the system itself
can legitimately construct, only a string that could not have come from this module's own
construction logic. Verified directly:

```
_is_unit_safe("%")                                    -> True
_is_unit_safe("тыс юаней")                              -> True
_is_unit_safe("млрд долларов")                          -> True
_is_unit_safe("")                                       -> True
_is_unit_safe("раза")                                    -> True
_is_unit_safe("% рынка литографических сканеров")        -> False
_is_unit_safe("точнее специализированных моделей")       -> False
```

`PERCENT_UNIT_CAN_CONTAIN_TRAILING_PROSE = false`
`UNKNOWN_UNIT_CAN_BECOME_ARBITRARY_TEXT = false` (an unrecognized unit word is never even captured
as a `(value, unit)` pair by the legacy `_NUMBER_UNIT_RE` in the first place — proven in §M/K: no
DATA candidate is produced at all for a genuinely unknown unit, never an arbitrary-text unit)

## F. Comparator grammar

```python
_COMPARATOR_WORDS = ("точнее", "быстрее", "медленнее", "эффективнее", "дороже", "дешевле",
                      "выше", "ниже", "больше", "меньше", "рост", "падение")
_COMPARATOR_KIND = {
    "точнее": "Точность", "быстрее": "Скорость", "медленнее": "Скорость",
    "эффективнее": "Эффективность", "дороже": "Цена", "дешевле": "Цена",
    "рост": "Рост", "падение": "Снижение",
}

def _extract_comparator(fact_lower: str) -> str | None:
    for word in _COMPARATOR_WORDS:
        if word in fact_lower:
            return word
    return None
```

`_extract_comparator()` is bounded and deterministic — only ever returns one of the 12 closed-
vocabulary words, or `None`. `выше/ниже/больше/меньше` are deliberately EXCLUDED from
`_COMPARATOR_KIND` — they are recognized/preserved as `comparison` (never lost, never leaked into
`unit`) but are too generic alone to safely name WHAT changed (could be price, users, revenue...),
so they never override the generic "Показатель" fallback on their own (§9's own "only when evidence
supports them" discipline). The comparator branch in `_classify_metric_kind()` is checked LAST, so
a fact like "цена автомобиля стала на 10% дороже" still classifies as "Цена" (the price-word branch,
checked first), never "Цена" via the comparator path with a different, redundant instance.

`COMPARATOR_CAN_ENTER_UNIT = false` (structurally impossible: the comparator extraction and the
unit extraction are two entirely separate code paths that never write to each other's output;
verified directly for every comparative regression case in §M)

## G. Subject extraction

**Unchanged** from the ASML hotfix — the model-name-shape tier, then the cross-verified (title AND
fact) bounded acronym tier, `None` otherwise. For NASA: "NASA"/"IBM" both appear in the title but
NEITHER appears in the fact text itself (the fact only says "Модель...", never naming the
organizations) — so no cross-verified subject is found, `subject=""`, exactly matching the brief's
own explicit allowance ("If no safe concise subject exists: subject = null. Do NOT substitute
`legacy.label`").

`SENTENCE_CAN_BECOME_SUBJECT = false` (unchanged guarantee from the ASML hotfix, re-verified in §M)

## H. Metric-kind derivation

`_classify_metric_kind(fact_lower, unit, comparator)` — gained one new parameter and one new,
LAST-checked branch (the comparator-kind lookup in §F). Every pre-existing kind (Стартовая цена,
Цена, Запас хода, Время зарядки, Доля рынка) is unchanged and still checked first. For NASA:
`comparator="точнее"` -> `_COMPARATOR_KIND["точнее"] = "Точность"`.

## I. Metric-label construction

**Unchanged pattern** from the ASML hotfix: `metric_label = f"{kind} {subject}" if subject else
kind`. For NASA, `subject=""` so `metric_label = "Точность"` alone — the safest of the three
acceptable forms the brief itself names ("another concise, evidence-supported bounded metric
label"), deliberately NOT attempting the harder, riskier "ТОЧНОСТЬ ОБНАРУЖЕНИЯ ЛЬДА"
(would require inferring "detection of ice" from context words like "выявлять"/"лёд" — exactly the
kind of "broad framework"/free-text inference the brief explicitly warns against) or fabricating
"ТОЧНОСТЬ МОДЕЛИ" (would require injecting the literal word "модели" outside the existing
`kind [+ subject]` construction pattern, a third ad-hoc case this phase deliberately avoids).

`SENTENCE_CAN_BECOME_METRIC_LABEL = false`

## J. Semantic validators

`_is_label_safe()` (NEW) — bounded, OBJECTIVE signals only (≤40 chars, ≤5 words, no terminal
sentence punctuation), deliberately never a fuzzy verb/grammar parser (the brief's own explicit "do
not make the validator so aggressive that normal approved labels fail" instruction). Verified every
existing approved label passes ("Стартовая цена Maxus 9", "Доля рынка ASML", "Показатель",
"Точность") and a real sentence fragment is rejected:

```
_is_label_safe("Показатель")                              -> True
_is_label_safe("Доля рынка ASML")                          -> True
_is_label_safe("Точность")                                  -> True
_is_label_safe("Модель способна выявлять водяной лёд...")   -> False
```

`_is_unit_safe()` — see §E.

Both gate `build_structured_data_content()`'s own return value directly (§K).

## K. Fail-closed behavior

```python
if not _is_unit_safe(full_unit) or not _is_label_safe(metric_label):
    return None
```

Reuses `build_structured_data_content()`'s own EXISTING, already-tested "nothing safely grounded ->
`None` -> the unified pipeline's already-existing `RENDER_FAILED` -> HOLD/recovery path" contract
(traced end-to-end: `orchestrator.py`'s `structured_content = None` -> `composition.py`'s
`decide_data_composition_strategy()` falls through to `DATA_TYPOGRAPHIC` -> `telegram_integration.py`'s
`_build_data_candidate()` never runs (`structured_content is None`) -> `render_branded_media()`
raises `"DATA presentation requested with no data_candidate"` -> caught -> `success=False` ->
`RENDER_FAILED` -> HOLD) — **zero new plumbing**, per the brief's own explicit "do not introduce a
new recovery system" instruction. Directly proven via monkeypatching a corrupted legacy grounding
result (`test_build_structured_data_content_fails_closed_when_legacy_grounding_is_corrupted`).

In practice, because unit/label construction is already correct-by-construction (§E-I), this gate
essentially never fires today — it is deliberate defense-in-depth against a FUTURE regression in the
construction logic above it, not a primary mechanism.

`SEMANTICALLY_UNSAFE_DATA_CAN_RENDER = false`
`SEMANTICALLY_UNSAFE_DATA_CAN_SEND = false`

## L. Geometry / RenderEvidence

The pre-existing (ASML hotfix) fail-closed geometry guard in `render_data_hero_card()` and the
truthful `RenderEvidence` in `render_evidence.py` are **untouched** by this phase — both files have
ZERO diff in this branch (confirmed: `git diff 45de6d4..HEAD --stat` touches only `content.py` +
tests/docs/artifacts). Proven they still hold together with the NEW semantic layer via a
semantically-safe-but-geometrically-impossible synthetic case (`value="999999999999999999"`,
`unit="%"`, `label="Точность"` — passes both `_is_unit_safe`/`_is_label_safe`, still raises at
render and still reports `text_clipped=True`):

```
_is_unit_safe("%")        -> True
_is_label_safe("Точность") -> True
render_data_hero_card(...) -> raises ValueError("...does not fit...")
RenderEvidence.text_clipped -> True
```

`GEOMETRIC_OVERFLOW_CAN_SEND = false`
`RENDER_EVIDENCE_FALSE_PASS_FOUND = false`

### A real, separately-disclosed geometry finding: Maxus's own unit does not fit today

While proving §L, rendering the REAL Maxus 9 fixture end-to-end through `render_data_hero_card()`
(something no prior test in this codebase had ever actually done - the ASML hotfix's own Maxus
regression test only checked `build_structured_data_content()`'s structured fields, never rendered
them) surfaced a genuine, PRE-EXISTING geometry limitation, unrelated to this phase's semantic work:
`unit="тыс юаней"` (9 characters) measures 830px against the DATA hero's 449px inner column at its
own minimum computed unit font size (162px - itself driven by the SHORT value "290" getting a very
large, near-maximum value font, which in turn forces a large *minimum* unit font via the existing
`unit_over_value=0.75` value-relative scaling). The existing fail-closed guard correctly rejects it
(no corrupted image can reach Telegram) but this means a real Maxus-shaped card (short value + long
magnitude+currency unit) HOLDs today rather than delivering.

This is a real DATA-typography/geometry issue - explicitly OUT OF SCOPE for this phase ("do not
redesign DATA", "do not change typography/spacing"). Documented in full, with exact measurements,
at `artifacts/telegram_data_semantic_parser_v2_1/MAXUS_HERO_GEOMETRY_GAP_evidence.json` and
disclosed here for Founder awareness and a possible, separately-authorized, narrowly-scoped
follow-up (length-aware unit font sizing). **Not fixed by this phase.** The semantic extraction
layer itself is unaffected and unchanged (`metric_unit="тыс юаней"` is correct and passes
`_is_unit_safe`) - only the renderer's own pre-existing font-scaling constants are implicated.

## M. Regression matrix

All 19 tests in `tests/test_telegram_data_semantic_parser_v2_1.py`, plus the 4 pre-existing suites,
pass:

| Item | Requirement | Result |
|---|---|---|
| A | NASA: `value=20`, `unit=%`, `comparator=точнее`, concise label, fits render | PASS |
| B | ASML: unchanged, byte-identical render | PASS |
| C | Maxus: `value=290`, `unit` contains тыс+юан, label unchanged | PASS (structured content; render geometry gap disclosed in §L, unrelated) |
| D | Generic percent: `unit=%`, never `% пользователей` | PASS |
| E | "40% быстрее": `comparator=быстрее`, no prose in unit | PASS |
| F | "15% ниже": `comparator=ниже`, no prose in unit | PASS |
| G | "30% эффективнее": `comparator=эффективнее`, `kind=Эффективность` | PASS |
| H | "3,2 млрд долларов": bounded, `_is_unit_safe=True` | PASS |
| I | Pathological trailing prose: validator rejects; monkeypatched corrupted grounding -> `None` | PASS |
| J | Sentence-label attack: validator rejects; structural proof `legacy.label` never referenced in code | PASS |
| K | Unknown unit ("очков"/points): no candidate produced at all | PASS |
| L | Semantically-safe/geometrically-impossible: still fails closed, RenderEvidence stays truthful | PASS |

## N. BEFORE/AFTER artifacts

`artifacts/telegram_data_semantic_parser_v2_1/`:

- `BEFORE_NASA.jpg` — rendered with the actual PRE-ASML-HOTFIX code (loaded from git `39f764b`).
  Reproduces every symptom: giant red comparison-clause overflow, malformed label.
- `AFTER_NASA.jpg` — rendered with this phase's code. Shows `20` / `%` / "ТОЧНОСТЬ", evidence copy
  below, no overflow, no malformed label.
- `AFTER_ASML.jpg` — rendered with this phase's code. **Byte-identical** to the ASML hotfix's own
  approved `AFTER_ASML.jpg` (`cmp` confirms zero diff) — proves zero regression.
- `STRUCTURED_CONTENT.txt` — exact title/fact/body inputs and resulting structured fields for all
  three cases (NASA/ASML/Maxus).
- `geometry_evidence.json` — real `RenderEvidence` for NASA/ASML (`text_clipped: false` for both).
- `MAXUS_HERO_GEOMETRY_GAP_evidence.json` — the disclosed, out-of-scope geometry finding (§L).

No secrets in any artifact.

## O. Approved fixture non-regression

ASML: proven byte-identical (§N). Maxus: structured-content fields byte-identical to the ASML
hotfix's own output (`metric_value="290"`, `metric_unit` contains "тыс"+"юан",
`metric_label="Стартовая цена Maxus 9"`) — the render-geometry gap found in §L is pre-existing and
orthogonal to this phase's changes (proven: nothing in this phase's diff touches
`brand_renderer.py`/`render_evidence.py`, and the SAME Maxus unit text would measure the SAME
830px regardless of which phase's `content.py` produced it).

## P. Full test / lint / typecheck

Targeted: `tests/test_editorial_pipeline_data_content.py`, `tests/test_editorial_pipeline_language_qa.py`,
`tests/test_founder_visual_board_alignment_1.py`, `tests/test_render_evidence_parity.py`,
`tests/test_design_spec_enforcement.py`, `tests/test_unified_pipeline_subject_extraction.py`,
`tests/test_telegram_data_semantic_overflow_hotfix_1.py`, `tests/test_telegram_data_semantic_parser_v2_1.py`,
`tests/test_brand_renderer.py` — **195 passed, 0 failed**.

`ruff check` and `mypy` both clean on `services/editorial_pipeline/content.py` and the new test file.

**Blast-radius sweep** (this phase's diff touches exactly ONE production file,
`services/editorial_pipeline/content.py` — confirmed no other production file has any diff, §Q):
every file that imports it, directly or transitively through its real consumers, was identified by
grep (`orchestrator.py`, `telegram_integration.py`, and their own test suites, plus
`composition.py`/`quality.py`'s test coverage) and run together with the full DATA suite above:

```
tests/test_editorial_pipeline_composition_quality.py
tests/test_editorial_pipeline_orchestrator.py
tests/test_unified_pipeline_orchestrator_cutover.py
tests/test_unified_pipeline_same_asset_invariant.py
```

**224 passed, 0 failed** (the 195 above plus these 29).

Also confirmed: `StructuredDataContent.comparison` (the field this phase populates, previously
always `None`) has no other reader anywhere in the codebase (`grep -rn "\.comparison\b"` across
`services/`, `tests/`, `worker/`, `bot/` returns only this phase's own new test file and the
explanatory comment in `content.py`) — populating it cannot regress any existing consumer because
none exists.

**Whole-repository full-suite run**: attempted (matching the ASML hotfix's own precedent), but the
harness killed the process at ~69% completion ("system is running low on memory") before it could
finish. The visible partial output (scattered `F` markers at roughly the same density and
distribution as the ASML hotfix's own 52-failure full run, none clustered around any DATA/content-
related test file) showed no evidence of a new failure class, but this is disclosed as **partial,
not conclusive** evidence — the full run was not completed and is not claimed as such. Given (a)
the diff is a single file, (b) that file's only three real consumers are fully covered and green in
the blast-radius sweep above, and (c) the ASML hotfix's own prior full run already established that
this repository's full suite carries ~48 pre-existing, environment-caused (shared local Postgres
test-DB cross-test isolation) failures unrelated to any DATA/content code, the blast-radius sweep is
treated as sufficient evidence for this phase's own verdict; a from-scratch whole-repository run
remains available as a follow-up if the harness's memory constraint is resolved.

`NEW_FAILURES = 0` (within the fully-covered blast radius; whole-repository run incomplete - see above)

## Q. Diff audit

`git diff 45de6d4..HEAD --stat`:

```
services/editorial_pipeline/content.py                                   | ~120 ++++--
tests/test_telegram_data_semantic_parser_v2_1.py (new)                   | ~330 ++
docs/telegram_data_semantic_parser_v2_1_report.md (new)
artifacts/telegram_data_semantic_parser_v2_1/* (new, 6 files)
```

**Exactly one production file touched**: `services/editorial_pipeline/content.py`. Confirmed by
explicit diff inspection: `services/brand_renderer.py`, `services/render_evidence.py`,
`services/presentation_director.py`, Story Memory, arXiv guard, media truthfulness, vision gate,
recovery architecture, Telegram transport, Instagram — all have ZERO diff from `45de6d4`.

## R. Production impact

**None this phase.** `content_worker` in production is still running `unified-vision-77a105f` (the
ASML hotfix was never deployed either — see the separate, still-paused
`docs/telegram_data_semantic_overflow_production_deploy_1_report.md`). No production host action
was taken during this phase.

## S. Rollback considerations

Not applicable — no deployment occurred. When a future, combined deployment is authorized, rollback
follows the same already-documented pattern (the exact previous `content_worker` image tag remains
present and immutably tagged on the host).

---

## Final metrics

```
BASE_HEAD=45de6d40cfa2eb6d5612fc0f4d28731d1eea9ce7
FINAL_HEAD=132abb0eae276e47e96ada3137671a0e695441d1

NASA_PRE_FIX_REPRODUCED=true
NASA_POST_FIX_VALUE=20
NASA_POST_FIX_UNIT=%
NASA_POST_FIX_COMPARATOR=точнее
NASA_POST_FIX_LABEL=Точность

ASML_VALUE=94
ASML_UNIT=%
ASML_LABEL=Доля рынка ASML

MAXUS_VALUE=290
MAXUS_UNIT=тыс юаней
MAXUS_ZERO_DIFF=true

PERCENT_UNIT_CAN_CONTAIN_TRAILING_PROSE=false
COMPARATOR_CAN_ENTER_UNIT=false
SENTENCE_CAN_BECOME_SUBJECT=false
SENTENCE_CAN_BECOME_METRIC_LABEL=false
UNKNOWN_UNIT_CAN_BECOME_ARBITRARY_TEXT=false

SEMANTICALLY_UNSAFE_DATA_CAN_RENDER=false
SEMANTICALLY_UNSAFE_DATA_CAN_SEND=false
GEOMETRIC_OVERFLOW_CAN_SEND=false

RENDER_EVIDENCE_FALSE_PASS_FOUND=false

NASA_REGRESSION_FIXED=true
ASML_REGRESSION_FIXED=true
MAXUS_REGRESSION_PRESERVED=true

TELEGRAM_V8_DESIGN_CHANGED=false
STORY_MEMORY_CHANGED=false
ARXIV_CHANGED=false
VISION_GATE_CHANGED=false
TRANSPORT_CHANGED=false
INSTAGRAM_CHANGED=false

NEW_FAILURES=0
```

`NEW_FAILURES=0` is scoped to the 224-test blast-radius sweep (§P) — the single production file
this phase touches, its full real consumer chain, and every DATA-related test suite, all green. The
whole-repository run was killed by the harness for memory before completion (§P); it is not being
claimed as a completed zero-failure result.

## Final verdict

**TELEGRAM_DATA_SEMANTIC_PARSER_V2_READY_FOR_FOUNDER_REVIEW**

Disclosed, out-of-scope, separate finding: the Maxus DATA-hero-card render geometry gap in §L
requires its own, separately-authorized follow-up (not a blocker for this phase's own semantic
work, which is complete and correct).
