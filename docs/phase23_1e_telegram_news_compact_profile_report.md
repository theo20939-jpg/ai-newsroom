# PHASE 23.1E — TELEGRAM NEWS COMPACT EDITORIAL PROFILE + SOURCE BUTTON

**Status: implemented and tested. No live canary run this phase.** Branch `feature/phase19-
editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb` (unchanged, no commit
made). `.env` untouched. No worker started, no real Telegram message sent, no paid LLM call made
(the Google Pay BEFORE/AFTER regression in §15 reuses the real draft already persisted in Phase
23.1D — nothing was regenerated).

## 1. Root cause of excessive length

Phase 23.1C's `services/content_draft_service.py::_extract_title_and_body()` concatenates **all**
of V6's narrative sections (`opening`, `context`, `why_it_matters`, `what_changed`,
`what_happens_next`, `conclusion`, `what_remains_unknown`) into one flat `ContentDraft.body`
string, joined with blank lines. This is the *correct* representation for persistence and Fact
Safety — Fact Safety must see every claim in every section to check it — but it is also exactly
what Phase 23.1D's real Telegram send delivered verbatim: 7 sections, none dropped, none
condensed. The length problem is not a V6 generation defect (each individual section, read on its
own, is reasonably concise) and not a `ContentDraftService` defect (persisting the complete text
is its correct job) — it is a **missing presentation step**: nothing between `ContentDraft.body`
and `bot.send_message()` ever asked "which of these sections does a NEWS reader actually need."

## 2. Root cause of repeated unknowns

The same flattening is responsible: V6's own prompt rules (`prompts/copywriting/v6.yaml`)
correctly instruct the model to name material gaps in several *different* fields when relevant
(a `why_it_matters` caveat, a `conclusion` hedge, and a dedicated `what_remains_unknown` field can
all legitimately mention that something is unknown, from different editorial angles). Read
individually, each mention is reasonable. Concatenated without deduplication, they read as the
same "we don't know much" message repeated three or four times — confirmed exactly in the real,
live Google Pay draft (Phase 23.1D): `opening` ("но пока не раскрыла, что именно изменится"),
`why_it_matters` ("вопросы... остаются открытыми"), `conclusion` ("это скорее сигнал..."), and
`what_remains_unknown` (a four-item enumeration) all separately signaled uncertainty.

## 3. Chosen architectural layer

**The Telegram NEWS presentation layer — a new, separate, destination-scoped module — not V6, not
`ContentDraftService`.** Per the phase's own core principle:

```
V6 structured output -> Fact Safety -> ContentDraft/editorial evidence -> [NEW: NEWS presentation] -> compact Telegram NEWS card
```

New module: `services/news_telegram_presentation.py::build_compact_news_body()`. It reads the
**still-structured** V6 fields (the raw `copywriting_output` dict, not the already-flattened
`ContentDraft.body`) and selects only the sections a human editor would keep. This required
threading the raw structured output from generation through to delivery without touching
`ContentDraft`'s own schema: `scripts/run_content_generation.py::ContentGenerationOutcome` gained
one new, additive field (`copywriting_output: dict[str, Any] | None`), populated via a small,
duplicated lookup (`_copywriting_output_for_outcome()`, mirroring this file's own existing
`_fact_safety_status()` precedent) — `ContentDraft`/`ContentDraftService` themselves are
completely unaware this field exists.

Applied **only** inside `worker/content_cycle.py`'s router branch (`editorial_delivery_mode ==
"router"`), which is itself already hardcoded to `EditorialDestination.NEWS` only (Phase 23.1A's
own structural guarantee, re-verified unchanged this phase). MEME/TELEGRAPH/INSTAGRAM/REELS have
no code path to this module at all.

## 4. Why V6 itself was or was not changed

**Not changed, and could not have safely solved this alone.** `prompts/copywriting/v6.yaml` is
byte-for-byte untouched. The phase brief explicitly forbids "do not modify V6 just to satisfy
Telegram," and investigation confirmed V6 doesn't need to change: each section it produces is
individually well-formed and useful (for Fact Safety, for a future Telegraph long-form article,
for Story Memory reasoning) — the redundancy only exists in the *combination*, which is a
presentation concern, not a generation defect. Fixing this in V6 would also have coupled V6's
prompt to Telegram's own UX preferences, contradicting the phase's own "one rich editorial
representation + destination-specific presentation" goal — a future Telegraph article needs the
full material this fix leaves completely intact.

## 5. Telegram NEWS compact profile

`build_compact_news_body(copywriting_output)` selects, in order, only sections that survive both a
redundancy check and (for `context`/`what_happens_next`/`conclusion`/the unknown-caveat) an
"unknown budget" check:

1. `opening` — always included (V6's own prompt already guarantees it's a strong, concrete hook).
2. `why_it_matters` and `what_changed` — each checked **independently** for distinctness against
   what's already selected (not against each other) — a thin story where both restate the same
   development collapses to one; a rich story where they carry separate facts keeps both (see §15
   test case F).
3. `context` — included only if genuinely distinct (a stricter bar than the two above — it's
   explicitly optional per the brief's own §3).
4. `what_happens_next`, `conclusion` — included only if not filler (§9) and distinct.
5. A single material caveat extracted from `what_remains_unknown` (§7).

No length target is *enforced* — sections are used verbatim or omitted, never rewritten or
truncated to hit a number. Telegram's own hard 4096-UTF-16-unit ceiling remains `bot/
formatting.py::render_editorial_card()`'s own, completely unmodified responsibility (the compact
body is simply shorter input to the exact same, already-proven renderer).

## 6. Length policy

Implemented as a *consequence* of selective inclusion, never as a target the algorithm optimizes
toward — matching the brief's own explicit "guideline, not truncation rule" framing. No code
anywhere checks "is this body 500-900 characters" and pads or cuts to fit. Verified directly: Case
E (§16 below) produces a 43-character single-sentence body without any padding logic even being
consulted; Case F preserves five distinct facts regardless of resulting length.

## 7. Unknown-information policy

Two independent, deterministic signals, both required to jointly implement "default 0, at most 1"
(phase brief §5/§6):

- **Materiality** (`_extract_material_caveat()`): a `what_remains_unknown` sentence is treated as
  material only when it is (a) a single, focused clause — not an enumeration of several different
  unknowns (detected via a connector-word split: "а также"/"и"/"либo"/";" — more than one segment
  means "few details are known," the generic, non-material pattern, regardless of which words
  appear inside it) — and (b) contains a strong, unambiguous material keyword (price/cost,
  deal/closing status, rumor/leak sourcing, disputed/unverified claims). Deliberately narrow and
  conservative, matching the brief's own explicit "default: 0" bias — generic timing/scale/
  functionality-unknown mentions never qualify, even when a material-sounding word (e.g.
  "безопасность") appears buried inside a multi-item enumeration (the real, live Google Pay case
  — see §15).
- **Budget** (`uncertainty_budget_spent`, tracked across the whole selection pass): the *first*
  selected paragraph that is itself an "epistemic hedge" statement (`_is_hedge_statement()` — a
  small, fixed marker-phrase list: "не раскрыл", "не уточнен", "не содержат сведений", etc.) spends
  the budget; every later hedge-flavored *optional* section (`context`/`what_happens_next`/
  `conclusion`/the caveat) is then dropped outright, regardless of wording. This budget is tracked
  starting from `opening` itself, since real V6 output frequently already states a hedge there.

## 8. Anti-repetition implementation

Two layers, both deterministic, both reusing existing code rather than adding new similarity
logic:
1. **Lexical**: `services/text_normalization.py::symmetric_token_overlap()` (Phase 20's own
   already-calibrated Dice-coefficient signal, reused exactly as-is, per the brief's own "reuse
   existing... utilities" instruction) — a candidate paragraph is dropped if its overlap with any
   already-selected paragraph exceeds a threshold (0.5 for the three core sections, a stricter 0.3
   for the explicitly-optional ones).
2. **Semantic-adjacent** (the hedge-marker budget, §7 above) — added specifically because the
   lexical check alone was measured, directly against the real Google Pay draft, to score
   0.0-0.04 overlap between two paragraphs that were both fundamentally "we don't know much"
   statements using almost entirely different vocabulary. Disclosed honestly, not smoothed over:
   this combination catches the real cases this phase specifically had evidence for; it is not a
   claim of general semantic deduplication (§16).

## 9. No-forced-conclusion behavior

`_is_filler()` checks `conclusion`/`what_happens_next` against a fixed, normalized-substring
blocklist built directly from the phase brief's own verbatim BAD examples ("станет понятнее",
"предстоит оценить", "покажет время", "появятся позже", "это скорее сигнал", "покажет
дальнейшее"/"развитие покажет", etc.). A filler-matched `conclusion` is dropped entirely — the
compact body simply ends after the last genuine paragraph, exactly matching §7's "if there is
nothing new to add: END THE POST." Verified directly: all seven of the brief's own example filler
phrases are individually confirmed dropped (test case G, §16).

## 10. Source-button implementation/reuse

**Reused, not rebuilt**, per the brief's own explicit instruction. `bot/keyboards/
image_preview.py::build_source_only_keyboard()` (Phase 16, already shipped, already tested) was
found during investigation and extended with one new, optional, backward-compatible parameter:
`label: str = "🔗 Open source"`. Every pre-existing caller (`services/image_preview_notifier.py`)
is byte-for-byte unaffected (confirmed by a dedicated regression test, §17). `worker/
content_cycle.py`'s router branch is the one new caller, passing `label="🔗 Источник"` — matching
the Russian-language editorial card it accompanies. `services/telegram_routing.py::
send_to_editorial_destination()` gained a matching additive `reply_markup: InlineKeyboardMarkup |
None = None` parameter, threaded straight to `bot.send_message()` — it does not build or interpret
the keyboard itself.

## 11. Source URL behavior

The button URL is `NewsEvent.url` — the exact same field `services/image_preview_notifier.py`
already uses for its own source button, and the exact field the real, live Google Pay draft
already had populated (a Google News RSS URL, per the phase brief's own explicit allowance: "If
the only available URL is a Google News RSS URL: use that real URL"). No new URL-resolution
subsystem was built. No shortener, redirect service, or fabricated link — a structural test
(`test_case_c_no_url_shortener_or_fabricated_link_is_ever_introduced`) confirms `bot/keyboards/
image_preview.py` imports no such client, and a direct-equality test confirms the button URL is
always exactly the input, character-for-character.

## 12. Files changed

**Modified**:
- `services/content_draft_service.py`: **not changed this phase** (confirmed — the compact profile
  lives entirely downstream of persistence).
- `scripts/run_content_generation.py`: `ContentGenerationOutcome` gained one additive field
  (`copywriting_output`); one new, non-raising local helper
  (`_copywriting_output_for_outcome()`).
- `worker/content_cycle.py`: the router branch now builds the compact body (when structured output
  is available), renders with `include_url=False`, and attaches a source-button `reply_markup` —
  falls back to the unmodified full-body/URL-in-body/no-keyboard behavior when structured output
  isn't available (a disclosed, safe degradation).
- `bot/keyboards/image_preview.py`: `build_source_only_keyboard()` gained one additive, default-
  unchanged `label` parameter.
- `services/telegram_routing.py`: `send_to_editorial_destination()` gained one additive, default-
  `None` `reply_markup` parameter.
- `tests/test_telegram_editorial_routing.py`: one existing exact-call assertion updated to include
  the new `reply_markup=None` default (mechanical, not a behavior change).

**Created**:
- `services/news_telegram_presentation.py` — the compact-body selection logic (§5-9).
- `tests/test_news_telegram_presentation.py` — 11 tests (compression cases A-H + V4 pass-through).
- `tests/test_news_source_button.py` — 10 tests (source-button cases B/C/D/H + `reply_markup`
  passthrough).
- One new integration test appended to `tests/test_editorial_delivery_mode.py` (cases A/E
  end-to-end).
- `docs/phase23_1e_telegram_news_compact_profile_report.md` — this report.

No migration created or applied (zero schema change). No `.env`/prompt file edit.

## 13. Tests added

Test-first discipline verified directly for the compression module: `tests/
test_news_telegram_presentation.py` was run against the not-yet-created module and failed with
`ModuleNotFoundError`, then implemented and iterated to green — including two genuine design bugs
caught and fixed *during* test-first development, not hidden:
1. An initial "pick only one of `why_it_matters`/`what_changed`" rule was too aggressive for
   genuinely rich stories (Case F) — fixed to check each independently against the growing
   selection.
2. The lexical-only redundancy check missed a real, measured case (context vs. what_changed in the
   live Google Pay draft, 0.0-0.04 overlap despite both being hedge statements) — fixed by adding
   the independent hedge-marker budget (§7/§8).

21 new tests total, all passing:
- 11 in `tests/test_news_telegram_presentation.py` (all 8 required compression cases A-H, plus V4
  pass-through and an unsupported-shape fallback check).
- 10 in `tests/test_news_source_button.py` (cases B/C/D/H directly; `reply_markup` passthrough and
  its backward-compatible default).
- 1 full end-to-end integration test in `tests/test_editorial_delivery_mode.py` combining cases
  A/E/B/C: a real V6 draft flows through the real pipeline (nothing patched except the outer
  `bot`), and the recorded `bot.send_message()` call is asserted to have no raw URL in the visible
  text, the exact real canary `chat_id`/`message_thread_id`, and a correctly-labeled button with
  the exact real source URL.

Cases E/F/G from §17 (router-mode chat/thread preserved, legacy unaffected, non-NEWS destinations
unchanged) are covered by re-running Phase 23.1A's own existing test suite unmodified (§14) rather
than new tests, since those guarantees are structural properties of code this phase did not touch
(the router branch's own hardcoded `EditorialDestination.NEWS`, the `editorial_delivery_mode`
default).

## 14. Regression results

```
python -m pytest tests/ -k "telegram or content_draft or copywriting or fact_safety or
  quality_capability or story_memory or story_delta or story_suppression or editorial_content_type
  or story_identity or human_reviewed_calibration or routing or whereami or bot_router or
  news_source or news_telegram_presentation or delivery_mode" -q
682 passed, 6 skipped, 2428 deselected, 6 failed, 6 errors
```

Every failure/error was confirmed, via a proper `git stash push -u` of every Phase 23.1E file
(including the untracked new ones — an initial stash attempt without `-u` silently failed to
revert the untracked files, caught and corrected before drawing any conclusion), to reproduce
identically on genuinely unmodified code: `test_content_draft_service.py` (1),
`test_fact_safety.py` (2), `test_run_content_generation.py` (7, confirmed via a dedicated, direct
before/after comparison, §14 note below), plus the familiar teardown-only `test_content_cycle_
story_delivery.py`/`test_editorial_delivery_mode.py` ERRORs already disclosed in every phase since
21. **Net new regressions: zero.**

Honest note on `test_run_content_generation.py`: this file's own failure *count* varies between
3 and 7 depending on how much other test activity already ran against the shared local Postgres
instance beforehand (the same accumulating-pollution pattern disclosed in every prior phase's own
report) — confirmed by running it twice in a row against unmodified code and observing the same 7
failures both times, ruling out a Phase 23.1E-caused regression specifically.

Ruff (all 5 modified/created source files + 4 test files): all checks passed. Mypy (all 5 modified/
created source files): Success, no issues found.

## 15. Google Pay BEFORE/AFTER

Reused the real, already-persisted Phase 23.1D `ContentDraft`/`EditorialTask.workflow` rows
directly from the database — **no regeneration, no LLM call**.

**BEFORE** (1371 UTF-16 characters, 7 paragraphs, raw URL visible in the header):
```
📰 AI  ·  2026-08-09
Google в Индии внедряет ИИ в Google Pay - PLUSworld
https://news.google.com/rss/articles/CBMiTEFVX3lxTE9YU19Bd2JTYjBFdUhkanotRFlBSi0zOThzbVNKNXdt...

Google внедряет ИИ в Google Pay в Индии

Google заявила о внедрении искусственного интеллекта в Google Pay в Индии, но пока не раскрыла,
что именно изменится для пользователей платёжного сервиса.

Доступные данные подтверждают сам факт внедрения ИИ, однако не содержат сведений о дате запуска,
конкретных функциях, масштабе проекта или его текущем статусе.

Для финтеха это может стать заметным шагом: использование ИИ в платёжном приложении способно
повлиять на пользовательский опыт и обработку операций. Но без информации о функциях нельзя
оценить практическую пользу, а вопросы безопасности и конфиденциальности платежей остаются
открытыми.

Новым заявленным развитием стало подключение ИИ к Google Pay на индийском рынке. Подробности
реализации и охват пользователей пока не уточнены.

Пока это скорее сигнал о направлении развития Google Pay, чем подтверждённое крупное обновление
сервиса. Его значение станет понятнее после публикации деталей запуска и функций ИИ.

Неизвестно, какие функции ИИ будут доступны, когда и в каком масштабе они появятся, а также как
внедрение повлияет на безопасность и конфиденциальность платежей.
```

**AFTER** (715 UTF-16 characters — a 48% reduction, 3 paragraphs, no raw URL, source button):
```
📰 AI  ·  2026-08-09
Google в Индии внедряет ИИ в Google Pay - PLUSworld

Google внедряет ИИ в Google Pay в Индии

Google заявила о внедрении искусственного интеллекта в Google Pay в Индии, но пока не раскрыла,
что именно изменится для пользователей платёжного сервиса.

Для финтеха это может стать заметным шагом: использование ИИ в платёжном приложении способно
повлиять на пользовательский опыт и обработку операций. Но без информации о функциях нельзя
оценить практическую пользу, а вопросы безопасности и конфиденциальности платежей остаются
открытыми.

Новым заявленным развитием стало подключение ИИ к Google Pay на индийском рынке. Подробности
реализации и охват пользователей пока не уточнены.

[ 🔗 Источник ]  (url: the real Google News RSS URL, verified byte-identical to NewsEvent.url)
```

Verification against the phase's own explicit checklist:
- **Materially shorter**: yes, 1371 → 715 characters (-48%).
- **No semantic repetition**: the filler `conclusion` ("Пока это скорее сигнал...") is gone; the
  four-item `what_remains_unknown` enumeration is gone (correctly classified as the generic
  "few details known" pattern, not material, despite mentioning "безопасность" as one of its four
  items).
- **No repeated unknowns**: exactly one uncertainty-flavored clause survives, inside `opening`
  ("но пока не раскрыла...") — the budget is correctly spent there, so `context`'s own
  hedge-flavored restatement ("не содержат сведений о дате запуска...") is correctly dropped.
- **No filler conclusion**: confirmed above.
- **No raw URL**: confirmed — `include_url=False` removes the URL line from the header entirely.
- **Source button exists**: confirmed, with the exact real URL and the `"🔗 Источник"` label.

**Honest comparison against the human's own reference example** (phase brief §2): the reference
was 2 paragraphs; this result is 3 (`why_it_matters` and `what_changed` both survived as
genuinely distinct, non-hedge, non-redundant content under lexical + hedge-marker checking). This
module can *select and trim* real V6 sentences; it cannot *rewrite or merge* them into fresh
prose (no LLM call, per the phase's own explicit constraint) — the human reference's own 2-
paragraph version appears to lightly reword content across sections in a way pure selection
cannot reproduce. Disclosed as a real, expected limitation of a deterministic-only approach, not
hidden (§16).

## 16. Remaining limitations

1. **Selection, not rewriting**: this module cannot merge or paraphrase two related sentences
   into one shorter one — only choose whether to include a section verbatim or drop it entirely.
   A human editor doing this by hand would likely produce a tighter result than this module can
   (§15's own honest 3-vs-2-paragraph comparison).
2. **Semantic redundancy detection is heuristic, not general**: the lexical similarity check
   (Dice-coefficient token overlap) catches near-verbatim restatement reliably but not paraphrase-
   level redundancy; the added hedge-marker budget catches the specific "multiple differently-
   worded uncertainty statements" pattern this phase had real evidence for, not every possible
   form of semantic overlap. A future story with a genuinely novel repetition pattern not covered
   by either signal could still show some redundancy.
3. **Materiality keyword list is deliberately narrow** (§7) — biased toward under-inclusion (per
   the brief's own explicit "default: 0" instruction), meaning some genuinely material
   uncertainties outside the current keyword set (price/deal/rumor/safety-privacy-disputed) could
   be omitted. Expanding this list is a natural, low-risk future refinement once more real
   examples exist.
4. **V4-shaped drafts get the new URL-hiding/button treatment too, but not the compact-body
   selection** (V4 has no separable sections to select from — its single `body` field is passed
   through unchanged). This is a deliberate, disclosed scope choice, not an oversight: the
   phase's own mission was specifically the V6 verbosity problem.
5. **No length-guideline enforcement/warning**: the module never checks whether its own output
   landed inside the "500-900 character" guideline range and never logs when it doesn't — matching
   the brief's own "guideline, not truncation rule," but means there is currently no automated
   signal if real-world output routinely falls far outside that range in either direction.
6. **This fix has not yet been exercised in a real, live canary run** — proven against real,
   already-persisted data (§15) and a comprehensive test suite, but the actual live Telegram
   rendering (emoji rendering, button tap behavior, message threading) has not been visually
   confirmed in the real NINJA NEWSROOM group this phase.

## 17. Recommendation for next live canary

Per the phase's own explicit STOP condition, **PHASE 23.1F — 5-NEWS EDITORIAL CANARY** is the
recommended next step, evaluating together (as the brief itself specifies): topic relevance,
compactness, information density, absence of repetitive unknowns, absence of filler conclusions,
source-button UX, V6 quality, Fact Safety, and Telegram presentation — this phase's own compact
profile is ready for that live evaluation, having been proven against real data (§15) but not yet
seen rendered live.

---

**STOP condition met.** Implementation, tests, and report complete. No live canary run this
phase. Waiting for human review before Phase 23.1F.
