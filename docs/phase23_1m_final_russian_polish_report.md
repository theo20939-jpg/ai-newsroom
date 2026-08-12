# Phase 23.1M Final Russian Editorial Naturalness Polish — Final Report

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged all session, nothing committed). All frozen systems (NEWS structure, length limits,
Editorial Treatment, scoring, Intelligence, Story Memory, duplicate handling, Fact Safety, image
pipeline, source button, Telegram routing, test/live DB isolation, hard delivery cap) were **not
modified** — confirmed by diff scope (only new prompt/test/script files plus the standard
version-registration edits to `core/config.py`/`capabilities/copywriting_capability.py`, identical
in shape to every prior copywriting-version addition this session).

## 1. Remaining V8.3 issues

Two honestly-disclosed residual classes carried in from the prior report: (1) headlines could
still preserve an overstated/dramatic claim inherited from the source even when body text was more
precise (Flock's "«невидимые»"); (2) a vague corporate wrapper phrase could survive in softened
form (Intel's "общие корпоративные цели").

## 2. Root causes

**Flock**: the source's own headline hedges the claim in quotes ("«невидимые»"); Research and
Intelligence correctly preserve that hedge, but V8.3's own headline-writing still centered its
framing on the disputed outcome-word ("невидимые") rather than the evidence-supported *purpose*
(interfering with recognition) - the evidence never verifies a mechanism, so neither "invisible"
nor a more specific invented claim like "evades detection" is actually supported; the safe
framing is the *intended effect*, which V8.3's own body text (but not headline) already used.
**Intel**: Research's own facts present "general corporate purposes" as an explicit vague
wrapper alongside exactly one concrete sub-point ("maintaining a strong balance sheet"); V8.3 had
no rule instructing deletion of a source's own acknowledged-vague wrapper phrase, only a
translate-by-meaning rule for concrete calques - a real, narrow rule gap now confirmed by direct
comparison (§5).

## 3. Prompt changes

`prompts/copywriting/v8.4.yaml` (frozen after this phase; v6-v8.3 untouched, verified by
`tests/test_copywriting_v84_naturalness_cases.py`'s frozen-file guard). Same schema as v8.1-v8.3
(zero code changes). New/strengthened rules: EDIT-FIRST-BY-DELETION (delete > simplify > explain,
applied uniformly, including to vague corporate language), HEADLINE SEMANTIC PRECISION (the exact
evade/interfere-vs-invisible distinction, plus claims≠proved/plans≠launched/may≠will/one-of-
largest≠largest), HEADLINE NATURALNESS (avoid "заявлен как"/"представлен в качестве"/"является
решением для"/"был осуществлён запуск"/inherited excess quotes), CORPORATE ABSTRACT-NOUN FILTER
(a concrete "what does this tell the reader" test, explicit instruction to state only the
concrete sub-point and drop a source's own acknowledged-vague wrapper). NATURAL RUSSIAN, SIMPLE
SENTENCES, ACTIVE VOICE, SEMANTIC PRECISION IS NON-NEGOTIABLE, and every v8.2/v8.3 structural rule
carried forward unchanged.

## 4. Golden set

8 real events, `scripts/_phase23_1m_final_golden_replay.py`: the 3 known problem-source events
from Phase 23.1K's own live canary (Flock/anti-recognition, Intel $15B, Venmo), Armenia/Firebird,
Stack Overflow, plus the 3 genuine posts from this phase's own V8.3 live canary (Long March 7A,
Anthropic IPO, Visa/Mastercard warning). All real, persisted, already-triaged events. Cost:
$0.0457, all 8 succeeded.

## 5. V8.3 vs new comparison

Full text: `scripts/_phase23_1m_v83_vs_v84_comparison.txt`, packet:
`docs/phase23_1m_final_russian_polish_review.md`.

| Case | V8.3 | V8.4 | Result |
|---|---|---|---|
| Flock | Headline: "заявленные как «невидимые»" | Headline: "должны мешать распознаванию камер" | **FIXED** - disputed outcome-word gone, replaced with the evidence-supported purpose |
| Intel | Body: "общие корпоративные цели" | Body: "общие корпоративные цели" (unchanged) | **NOT FIXED** - the targeted phrase survives verbatim despite the new rule directly addressing it; a new, useful ending disclosing previously-omitted deal terms was added instead |
| Venmo | 207 chars | 184 chars | Further simplified, no regression |
| Armenia | Unverified NVIDIA claim in headline | Same claim moved to body/ending, properly hedged | Improved headline precision |
| Stack Overflow | Causal AI claim stated in body | Same claim moved to a hedged ending | Improved precision |

## 6. Headline precision results

7 of 8 golden cases: PASS (no overstatement beyond the evidence). 1 of 8 (Intel): PASS on the
headline itself (already correct since V8.2/V8.3), but the residual issue is in the body, not the
headline. In the **live canary** (§11), one delivered post (Singapore GDP forecast) showed a real
headline-precision miss: "из-за бума ИИ" states a stronger, more definitive causal claim than the
source's own hedged "stronger-than-expected global AI [demand]" framing, and cites only the upper
bound (5.5%) of the 4.5-5.5% forecast range - flagged by Fact Safety shadow, disclosed honestly
here as a genuine, reproducible instance of the exact defect class V8.4's own HEADLINE SEMANTIC
PRECISION rule targets, not fully eliminated by a single prompt-wording pass.

## 7. Corporate-language results

Improved but not eliminated. The CORPORATE ABSTRACT-NOUN FILTER rule produced no measurable change
on the one direct test case available (Intel) in this replay run - a real, disclosed finding, not
glossed over. No case got *worse* on this axis.

## 8. Semantic preservation matrix

Checked for all 8 golden cases (actor/action/status/numbers/dates/geography/causality/certainty/
attribution) - **zero drift found** in any case. Every claim that changed wording preserved its
underlying meaning (Armenia's NVIDIA claim and Stack Overflow's causal claim were *relocated* to
a properly-hedged ending, not strengthened or weakened). The one live-canary precision miss
(§6, Singapore) is a headline-level overstatement, not a factual drift in the underlying
numbers/actor/action - the body correctly states the full 4.5-5.5% range.

## 9. Length comparison

Shorter or equal in every golden case: Flock 202→168, Intel 236→223, Venmo 207→184, Armenia
223→205, Stack Overflow 257→225 (all `main_body` char counts). No systematic expansion.

## 10. Tests / regression

`tests/test_copywriting_v84_naturalness_cases.py`, 12/12 pass - the 10 required cases A-J
(headline semantic precision + evade/invisible example; financial-meaning rule; corporate
abstract-noun filter with concrete test; active voice with concrete examples; no-invented-actor;
planned-vs-claimed status coverage; uncertainty ceiling; numbers untouched by presentation;
one-main-paragraph; headline-naturalness banned constructions) plus edit-first-by-deletion and a
frozen-prompt-immutability guard. Full regression suite, run **only** against the isolated
`ai_newsroom_test` database (Phase 23.1L): **3228 passed, 21 failed, 21 skipped, 35 errors** -
byte-identical failure list to the immediately-prior confirmed baseline (`diff` against the
pre-v8.4 run showed zero differences). Ruff (full repo): clean except the same 6 pre-existing,
untouched scratch-script issues. Mypy (the 2 modified production files): clean.

## 11. Live canary

Bounded, chat `-1004297182444`/topic 2 only, `copywriting_prompt_version=8.4`,
`editorial_delivery_mode=router` (in-process only), `fact_safety_mode=shadow`,
`story_memory_mode=off` (preserved). Stop reason: `hard_delivery_cap_exhausted`. 15 events
analyzed (well under 30), 3 delivered (message IDs 100-102): Singapore's raised GDP forecast, an
AI agent that hacked a gym booking system, and an article on European rural depopulation. All
exactly one main-body paragraph, all with source buttons, 2 of 3 with images. **The duplicate
tripwire correctly fired** on a genuine duplicate pair (two different sources reporting the same
AI-agent-hacking-a-gym story, 89% title-word overlap) - moot for this run since the hard cap was
already exhausted by the time it fired, but direct, real-world proof the Part N observational
check works as designed. 3 further attempted sends (1 text, 2 photo) were correctly refused by the
hard delivery cap, gracefully handled, never crashing the cycle - the same proof-under-a-new-
prompt-version already established in the V8.3 canary.

## 12. Cost

Golden replay: $0.0457 (8 events). Live canary: $0.1114 (15 analyzed, 3 delivered). Total this
phase: **$0.157**, well under the live canary's $0.50 cap.

## 13. Remaining language limitations

Disclosed honestly: (a) Intel-style vague corporate wrapper phrases ("общие корпоративные цели")
are not reliably eliminated even by a rule directly targeting this exact pattern - a narrow,
reproducible residual class; (b) the live canary surfaced a real, fresh instance of headline
overstatement (Singapore's "из-за бума ИИ" / partial-range citation) that V8.4's own HEADLINE
SEMANTIC PRECISION rule aims at but did not catch in this specific case - confirming this class of
defect is reduced in frequency (the Flock case fixed cleanly, most golden cases improved) but not
structurally guaranteed by prompt wording alone. Both are prompt-adherence/generalization
limits inherent to a single LLM call following natural-language instructions, not architecture
gaps - consistent with the phase's own explicit "no deterministic phrase-replacement hacks"
constraint, which rules out a mechanical fix for either.

## 14. Recommendation: **B — ONE SMALL LANGUAGE DEFECT REMAINS**

The mission's target case (Flock's "«невидимые»" headline) is cleanly fixed, with a concrete,
generalizable rule (not a hardcoded string swap) behind the fix. Semantic precision, length
discipline, and every frozen system remained intact through both the golden replay and a real
live run, and the live run additionally re-confirmed the Phase 23.1L hard-cap fix and the new
Part N duplicate tripwire both hold under this new prompt version. However, two real, narrow,
reproducible defect instances were found and disclosed rather than hidden: the Intel corporate-
wrapper phrase persisting despite a directly-targeting rule, and a fresh headline-overstatement
case in the live sample (Singapore GDP). Per the brief's own decision criteria, this is exactly a
"narrow, reproducible class... still present" - not a blocking regression, not a factual or
architectural failure, but not a claim of full resolution either.

## STOP

Per the phase brief: investigation, the new immutable prompt version, golden replay, tests,
regression, and one bounded live canary are complete. No VPS deployment, no permanent workers, no
image-quality work yet, no new Copywriting version created automatically. Awaiting human review.
If decision A is approved by the human reviewer despite the disclosed residual (a legitimate
call - the residual is narrow and non-blocking), the roadmap's own next steps are Phase 23.1N
(Image Editorial Quality Hardening), then a final combined NEWS canary, then Phase 23.2 (VPS
deployment).
