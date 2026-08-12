# Phase 23.1M — Russian Editorial Naturalness + Semantic Precision — Final Report

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged all session, nothing committed). All frozen systems listed in the phase brief (V8.2
structure, Editorial Treatment, scoring thresholds, Intelligence, Story Memory, duplicate
handling, Fact Safety, image discovery/ranking, source button, Telegram router, runtime isolation,
hard delivery cap, test DB isolation) were **not modified** — confirmed by diff scope (only new
files plus targeted `core/config.py`/`capabilities/copywriting_capability.py` version-registration
edits, identical in shape to every prior copywriting-version addition this session).

## 1. Root cause

Traced precisely against real persisted data (Research/Intelligence/Copywriting step_results for
the exact 3 events that produced the human-cited examples), not assumed. The clearest, most
severe case (Intel): **Research's own English-to-Russian fact-extraction step already produces
near-literal calques of the source's financial jargon** — "maintaining a strong balance sheet" →
"поддержание сильного баланса", "general corporate purposes" → "общие корпоративные цели",
"taking advantage of renewed interest in its business prospects" → "воспользовавшись
возобновившимся интересом к перспективам бизнеса" (a word-for-word structural mirror of the
English sentence). Intelligence's own "angle" field then reproduces the same calques almost
verbatim, and Copywriting (V8.2) only lightly rephrases what it received rather than re-deriving
natural Russian from the underlying fact. The Flock case showed a related, distinct pattern:
Copywriting's own MAIN BODY text already demonstrated it *can* write precisely ("призванные
скрывать" instead of "невидимые"), but its HEADLINE separately reused Intelligence's own
less-precise phrasing verbatim — an internal inconsistency, not a uniform failure.

## 2-3. Language defect taxonomy, by layer

| Category | Example (real, evidenced) | Layer responsible |
|---|---|---|
| English financial/business calque | "поддержание сильного баланса", "общекорпоративные цели" | **C→B→A**: originates in Research's own fact-extraction translation, reproduced by Intelligence, only lightly touched by Copywriting |
| Overloaded participial/gerund chain | "...воспользовавшись возобновившимся интересом к перспективам бизнеса" | C→B→A, same chain as above |
| Bureaucratic/corporate-PR phrasing | "Новая возможность расширяет выбор способов оплаты, но особенно актуальна для..." | **B**: near-direct lift of Intelligence's own "angle" summary ("...что расширяет доступные способы оплаты...") into Copywriting's body |
| Headline/body inconsistency in precision | Flock: body says "призванные скрывать" (hedged), headline says "заявлены как «невидимые»" (also hedged, but a more visually loaded word) | **A**: Copywriting itself, not applying the same naturalness discipline uniformly across fields |
| Unearned interpretive addition | Flock: "...что делает разработку потенциально интересной для защиты приватности" (not stated by Research's own facts) | **A**: Copywriting's own editorializing, loosely grounded in Intelligence's broader "angle" theme but stated with more confidence than Intelligence itself used |
| Presentation-layer artifact | none found | **D ruled out** for all 3 investigated cases — `render_v81_news_card_html()`/`build_v81_news_body()` only reshape paragraphs/length, never reword text; every awkward sentence was already present verbatim in the raw `copywriting_output` |
| Factual ambiguity | Venmo's "в США" qualifier (real-world true, not explicitly evidenced in the shown Research facts) | **E**: a minor, defensible common-knowledge inference, not a clear error |

The other taxonomy categories the brief asks about (passive voice, abstract noun chains, fake
analytical importance, unclear referents, semantic overstatement, unnatural word order) are all
real, recurring patterns visible across the wider Phase 23.1K/23.1L output set, consistent with
the same root cause: **Copywriting was not instructed to treat upstream Research/Intelligence text
as working notes to understand rather than prose to lightly edit.**

## 4. New prompt-version changes

`prompts/copywriting/v8.3.yaml` (frozen after this phase; v6/v7/v8/v8.1/v8.2 untouched, verified
by `tests/test_copywriting_v83_naturalness_cases.py`'s own frozen-file guard). Same output schema
as v8.1/v8.2 (`title/main_body/ending/quote`) — zero code changes needed anywhere (the same
schema-based compatibility already proven twice for v8.1 and v8.2). New system-prompt paragraph
states the core principle directly: Research's facts/Intelligence's angle are working notes to
*understand*, not prose to *lightly rephrase* — first understand the fact, then restate it as a
Russian editor would, never carrying over an upstream sentence's own word choices merely because
they are already there. New rules added (rules already in v8.2 — structure, brevity, delete-
before-explaining, vendor/supplier, plain language, uncertainty, quote handling — carried forward
unchanged): NATURAL RUSSIAN (explicitly applies to headline and body equally, with the exact
"strong balance sheet"/"сильный баланс"/"крепкое финансовое положение" example), SIMPLE SENTENCES,
ACTIVE VOICE (with an explicit no-invented-actor guard), AVOID BUREAUCRATIC AND CORPORATE-PR
PHRASING (a concrete banned-phrase list, "unless they carry specific factual meaning"), SEMANTIC
PRECISION IS NON-NEGOTIABLE (the evade-detection-vs-invisible example, and the general
evidence-over-elegance tie-break rule).

## 5. Why no extra LLM layer was needed

Not investigated as necessary — the root-cause investigation (§1) showed the defect is a
*generation-discipline* problem within Copywriting's own prompt (reusing upstream phrasing
instead of re-deriving it), not a limitation the Copywriting capability is structurally incapable
of addressing. The golden replay (§7-10) confirms a single frozen prompt-version change,
inside the existing single-LLM-call Copywriting step, produced a measurable, concrete improvement
on every one of the 3 known problem cases without adding cost or latency. No second Russian-editor
LLM pass was built, matching the brief's explicit "double latency/cost just to polish Russian" veto.

## 6. Golden dataset

10 real events, `scripts/_phase23_1m_golden_replay.py`: the 5 known problem-source events from
Phase 23.1K's own live canary (Flock/anti-recognition patterns, Google Play/Venmo, Intel $15B,
plus Armenia/Firebird and Stack Overflow) and all 5 genuine posts from Phase 23.1L's final local
acceptance canary (OpenAI $7B tender offer, OpenAI cyber model, Flock cameras/NYT, X/Twitter ad
revenue, Sakhalin AI course). All real, persisted, already-triaged events — no synthetic stories.
Cost: $0.0489, all 10 succeeded.

## 7. V8.2 vs new version comparison

Full text: `scripts/_phase23_1m_v82_vs_v83_comparison.txt`. Summary for the 3 direct-comparison
cases (identical Research/Intelligence input, only Copywriting version changed):

| Case | V8.2 defect | V8.3 result |
|---|---|---|
| Flock | Passive headline; "заявлены как «невидимые»" | Active headline ("...создал..."); body drops the unearned interpretive clause. Headline still retains "«невидимые»" in quotes (a hedged, attributed choice, not a full fix) |
| Venmo | "Новая возможность расширяет выбор способов оплаты, но особенно актуальна для..." | "Функция пригодится пользователям Venmo, которые покупают..." — concrete, natural, no bureaucratic filler |
| Intel | "поддержание сильного баланса"; "воспользовавшись возобновившимся интересом к перспективам бизнеса" | "поддержание финансовой устойчивости" (natural meaning, calque removed); the dense participial chain removed entirely, replaced with a clean sentence about the stock-price reaction |

## 8. Semantic-preservation results

Checked explicitly for all 3 direct-comparison cases (actor/action/object/status/certainty/
numbers/geography/causal claim/attribution) — no drift found:
- **Intel**: actor (Intel), action (stock offering), amount ($15B), stock-price reaction (>3% drop)
  all preserved exactly. One real fact (the "renewed interest" framing) was *omitted*, not
  distorted — a disclosed editorial trade-off under the existing delete-before-explaining/
  conciseness discipline, not a semantic-precision violation (omission of a non-essential fact is
  explicitly different from misstating a claim).
- **Venmo**: actor (Google Play users), action (pay with Venmo balance/linked account), scope
  unchanged; the undocumented "США" qualifier was dropped rather than asserted without evidence —
  a *more* disciplined outcome than V8.2, not a semantic loss.
- **Flock**: the hedged/quoted nature of the "invisible" claim is preserved in both versions
  (neither asserts literal invisibility as fact) — no certainty-level drift.

All 10 golden-replay outputs independently re-checked structurally: exactly 1 main-body paragraph
each, no `expandable_details` key present in any output.

## 9. Naturalness results

Qualitative, evidence-grounded assessment against the human-style rubric
(`docs/phase23_1m_human_naturalness_rubric.md`): the Intel and Venmo rewrites show a clear,
concrete naturalness improvement (calque removed/reduced, bureaucratic filler removed, denser
sentences simplified into either one clean sentence or two). The Flock headline shows partial
improvement (active voice) but does not fully match the human-suggested direction (still contains
a quoted "«невидимые»"). All 3 live-canary posts (§13) read naturally on inspection: active voice
throughout (НСПК предупредила..., Anthropic привлекает..., ракета взорвалась...), no bureaucratic
filler, no repeated uncertainty, concrete verbs. Final human verdicts are left blank in
`docs/phase23_1m_russian_editorial_naturalness_review.md` for actual editorial review, per the
brief's own instruction not to self-grade naturalness.

## 10. Length comparison

Not longer — shorter in every one of the 3 direct comparisons: Flock 245→202 chars, Venmo
245→207 chars, Intel 275→236 chars (all measured on `main_body` alone). Matches the explicit
acceptance target ("do NOT make posts longer").

## 11. Tests

`tests/test_copywriting_v83_naturalness_cases.py`, 11/11 pass — the 10 required Part H cases
(financial calque rule+example present; corporate-PR/bureaucratic-filler rule present; active-
voice rule present; no-invented-actor rule present; semantic-precision rule + evade/invisible
example present; simple-sentence rule present; numbers untouched by the presentation layer;
uncertainty-ceiling rule carried forward; one-main-paragraph schema-generic proof; headline-
naturalness-no-exception rule present) plus a frozen-prompt-immutability guard (v6/v7/v8/v8.1/v8.2
byte-unmodified).

## 12. Regression

Run only against the isolated `ai_newsroom_test` database established in Phase 23.1L (never the
dev/live DB, per the brief's explicit instruction). Full suite: **3216 passed, 21 failed, 21
skipped, 35 errors** — an exact, evidence-confirmed *subset* of Phase 23.1L's own already-disclosed
22-failure baseline (one fewer: a timing-sensitive worker-loop test not present this particular
run, consistent with known run-to-run variance for that test class, not a regression). All 35
errors match the same 4 previously-documented FK-teardown constraint patterns. Zero new failures.
Ruff (full repo): clean except the same 6 pre-existing, untouched scratch-script issues. Mypy
(the 2 modified production files): clean.

## 13. Live canary

Bounded, chat `-1004297182444`/topic 2 only, `copywriting_prompt_version=8.3`,
`editorial_delivery_mode=router` (in-process only), `fact_safety_mode=shadow`,
`story_memory_mode=off` (preserved, not touched). Stop reason: `hard_delivery_cap_exhausted`.
5 events analyzed (well under the 30 cap), 3 delivered (message IDs 97-99): a Long March 7A rocket
explosion, Anthropic's IPO courting, and a Visa/Mastercard online-payment warning — all genuine
real news, all read naturally on inspection, all exactly one main-body paragraph, all with source
buttons, 2 of 3 with attached images. A 4th candidate (China AI social-modeling system) was fully
content-generated but its Telegram send was correctly refused by the hard delivery cap
(`DeliveryCapExhaustedError`, gracefully handled, recorded as `notification_failed`, cycle did not
crash) — direct, live proof the Phase 23.1L hard-cap fix holds under this phase's own new prompt
version too. No duplicate tripwire firing.

## 14. Cost

Golden replay: $0.0489 (10 events). Live canary: $0.0464 (5 analyzed, 3 delivered). Total this
phase: **$0.0953**, far under both the golden-replay "minimal" expectation and the live canary's
$0.50 cap.

## 15. Fact Safety observations

`fact_safety_mode=shadow` throughout, never suppressed a send. All 3 live posts were flagged by
the same already-known, already-disclosed legacy `passed`/`issues` completeness check ("Body
указан как None" — a schema-recognition gap unrelated to this phase's own changes, first
disclosed in Phase 23.1L's own report). The structured `fact_safety` sub-check found all 3 posts
`status=pass` this run (a more favorable outcome than Phase 23.1L's own live sample, though not
attributable to V8.3 specifically — different underlying stories).

## 16. Remaining language defects

Disclosed honestly, not hidden: the Flock headline still contains "«невидимые»" in quotes
(a hedged, source-attributed choice, defensible but not the fully-reworded direction the human
example suggested) — a genuine, narrow, generalizable residual case, not a blocking regression.
"общие корпоративные цели" (Intel) remains a mild calque of "general corporate purposes",
softened but not eliminated. Both are consistent with a single prompt-wording pass improving but
not perfecting every construction — expected, and disclosed rather than overclaimed.

## 17. Recommendation: **B — ONE SMALL LANGUAGE FIX REMAINS**

The core naturalness/semantic-precision goal was achieved on the clearest, most severe case
(Intel's financial calque and overloaded sentence — both substantially fixed) and on Venmo
(bureaucratic filler fully replaced with natural, concrete phrasing), with zero semantic drift,
zero length regression, and a clean live canary proving both the language change and the Phase
23.1L runtime protections (hard cap, isolation) hold together. The one remaining narrow,
generalizable issue — headline-level hedged claims (like Flock's "«невидимые»") not always being
reworded as thoroughly as body text, and a residual mild calque in the Intel case's "corporate
purposes" phrasing — did not block delivery, cause factual drift, or require an architecture
change, and is exactly the kind of "one small language fix" this decision option describes. It
does not, on its own, justify a further prompt iteration before VPS preparation, but is worth
naming precisely rather than glossing over.

## STOP

Per the phase brief: investigation, new immutable prompt version, golden replay, tests, bounded
live canary, and both reports are complete. No VPS deployment, no permanent workers, no new
content formats (Meme/Telegraph/Instagram/Reels), no enforce modes enabled. Awaiting human review.
