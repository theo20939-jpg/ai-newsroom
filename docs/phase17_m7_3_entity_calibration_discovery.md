# Phase 17 M7.3 — Entity Calibration Discovery

**Discovery only. No code was changed to produce this document. No LLM call was made — every
claim below was verified by reading `services/fact_safety.py`'s entity extraction/matching code
and running it directly, read-only, against the three known examples plus the taxonomy examples
named in the authorizing message.**

## Current behavior

Entity extraction (`_extract_entities()`, `services/fact_safety.py`) is a two-stage process:

1. `_ENTITY_RUN_PATTERN` finds runs of 1-4 consecutive capitalized words (Title-Case or ALL-CAPS),
   optionally trailed by a legal suffix (`Inc`/`ООО`/etc).
2. For each run: a **multi-word run (2+ tokens) is kept unconditionally** — `if token_count >= 2:
   candidates.append(value)`. A **lone single-word run** is kept only if it independently passes
   `_is_strong_single_token_entity()`: ALL-CAPS (`NASA`), an internal capital past the first letter
   (`OpenAI`, `iPhone`), or a hand-curated alias match (`China`/`Китай`). A lone ordinary
   Title-Case word (just a capitalized first letter, no other signal) is discarded — this is the
   *existing*, already-correct safeguard against every sentence-initial word being flagged.

Matching (`_claim_matches_any`, `claim_type == "entity"`) requires **exact equality** of
`_normalize_entity()` output between the draft claim and an evidence claim — never substring,
never fuzzy, never decomposed into sub-words. `_normalize_entity()` strips legal
prefixes/suffixes, one hyphen-attached generic-noun suffix (`-система`/`-платформа`/`-модель`/
etc.), a trailing possessive, and resolves a short hand-curated alias list (`ИИ`↔`искусственный
интеллект`, `Китай`↔`China`) — but does **not** decompose a multi-word phrase into its component
words for matching purposes.

Severity (`_entity_severity`): `uncertain` is always LOW; `unsupported` is HIGH only if the entity
string is a literal substring of the draft's own title (`_normalize_text()` comparison,
"centrality"), otherwise MEDIUM.

## Real examples — verified, classified

| Example | Extracted as | Why | Classification |
|---|---|---|---|
| `Автономный ИИ-агент` | `"Автономный ИИ-агент"` (whole 2-word run) | Both words capitalized — "Автономный" only because it opens the sentence, "ИИ-агент" is one hyphenated token with an internal capital ("И") that happens to also start the run | **Generic phrase** (bundled adjective + technology descriptor) — not a real entity at all |
| `Агент Saul` | `"Агент Saul"` (whole 2-word run) | "Агент" capitalized only from sentence position; "Saul" is the one genuine proper noun | **Generic phrase bundled with a real named entity** — the role noun should not be part of the claim |
| `Китайская ИИ-модель Kimi K3` | `"Китайская ИИ-модель Kimi K3"` (whole 4-word run) | All four words capitalized (first three from sentence-initial position + internal capitals in "ИИ-модель"; "Kimi K3" is the genuine product name) | **Generic phrase (nationality adjective + technology descriptor) bundled with a real product/model name** |

Per the requested 4-way taxonomy, tested directly:

| Category | Example | Currently extracted alone? |
|---|---|---|
| 1. Real named entity (multi-word) | `Kimi K3` | **Yes, correctly** — 2-word run, no descriptor involved |
| 1. Real named entity (single word, strong signal) | `OpenAI` | **Yes, correctly** — internal capital ("penAI") |
| 1. Real named entity (single word, ordinary capitalization) | `Google`, `Samsung`, `Saul` | **No — false negative**, verified live (see below) |
| 2. Product/model name | `Kimi K3`, `GPT-5.6 Sol` | Partial — `Kimi K3` works; `GPT-5.6 Sol` only extracts `"GPT-5"` (the `.6` breaks the run, `Sol` is lost entirely) — a separate, minor extraction-fragility issue, not part of this milestone's core question |
| 3. Technology descriptor, standing alone | `ИИ-агент`, `автономная система`, `языковая модель` | **No — correctly excluded already** (verified live: none of these extract when not preceded by another capitalized word) |
| 4. Generic phrase, standing alone | `Компания представила разработку` | **No — correctly excluded already** |

**The bug is narrower than "entities are miscategorized" — it is specifically: a technology
descriptor or generic phrase that is *already correctly excluded on its own* becomes a false
positive only when an adjective/role-noun immediately before it is ALSO capitalized (almost always
because it opens the sentence) and the multi-word-run rule's `token_count >= 2` branch trusts any
2+-word capitalized run unconditionally, with no per-word signal check the way the single-token
path already has.**

## False positives (confirmed root cause)

All three known examples share the identical mechanism: `_extract_entities()`'s multi-word branch
never asks "does *any* word in this run carry independent proper-noun signal, or is the whole run
just capitalized because it's sentence-initial?" — a question the single-token branch already
asks and answers correctly. Verified: stripping the first word from each example and testing the
remainder against the EXISTING `_is_strong_single_token_entity()` check shows the remainder would
correctly fail for the pure-descriptor cases (`ИИ-агент` — no internal capital past its own first
letter in a way the pattern recognizes) and correctly succeed for the real multi-word product name
(`Kimi K3` — already 2 tokens, no check needed) — confirming the fix belongs in extraction, not in
matching or severity.

## False negative risks

Two distinct, verified risks — one pre-existing (independent of any fix here), one a potential
side effect of the most obvious fix:

1. **Pre-existing, independent of this milestone**: `Google`, `Samsung`, and `Saul` are **not
   extracted at all** when they appear as an ordinary capitalized word with no internal capital,
   no ALL-CAPS styling, and no legal suffix — verified live for all three. This means a fabricated
   claim naming any of these (or hundreds of other real single-word brand/person names) in
   isolation currently receives **zero entity-safety scrutiny**. This is not caused by anything
   M7.2 or this discovery introduces — it is the existing single-token rule's own conservatism,
   simply surfaced because the user's own proposed "named entity" example list (`OpenAI`, `Google`,
   `Samsung`, `Kimi K3`, `Saul`) happens to contain two names (`Google`, `Samsung`) and one bare
   name (`Saul`) that the current code cannot see at all. Today, `Saul` is only ever detected as
   part of the very bundle (`Агент Saul`) that is also the false positive — meaning the two
   problems currently offset each other by accident, not by design: fixing the false positive
   without addressing this risks making `Saul` (and names like it) invisible in *every* case,
   not just the falsely-bundled one.
2. **A direct consequence of the most obvious prefix-stripping fix (see Design below)**: if a
   generic first word is simply *stripped and discarded* rather than the remainder being
   re-examined with a broadened rule, `"Агент Saul"` → strip `"Агент"` → remainder `"Saul"` → still
   fails the existing single-token check → the claim disappears entirely, rather than becoming a
   correctly-scoped `"Saul"` entity claim. This does not make anything *less safe than today*
   (the bundled form never actually matched differently-phrased evidence anyway — verified in M7
   discovery: real Research evidence phrased Saul's name three different ways, none matching
   `"Агент Saul"` literally), but it also does not close risk #1. A more complete fix (Option B
   below) would re-examine the remainder with a narrowly broadened rule instead of discarding it —
   itself carrying a small, disclosed risk of reopening some sentence-initial noise if not scoped
   carefully.

## Proposed implementation plan (not implemented — discovery only)

**Minimal, scoped to `_extract_entities()` only — no change to `_normalize_entity()`,
`_claim_matches_any()`, `_entity_severity()`, or any severity table.**

Add a new, narrow, hand-curated list, `_ENTITY_GENERIC_PREFIX_WORDS` — nationality/generic
adjectives (`Автономный`/`Автономная`/`Автономное`, `Китайский`/`Китайская`, `Российский`/
`Российская`, `Американский`/`Американская` — exactly enough to cover the 3 known examples plus
close analogues, not an open-ended list) and role/category nouns (`Агент`, `Компания`, `Модель`,
`Платформа`, `Стартап`, `Разработчик`, `Производитель`). Note: `services/candidate_fact_safety.py`'s
own `_DESCRIPTIVE_NOUN_RE` (line 48) already hand-curates a very similar role-noun list
(`стартап`/`производитель`/`компания`/`разработчик`/`платформа`/...) for a *different* purpose
(flagging an explained-but-unlisted term) — worth reusing or at least keeping in sync rather than
maintaining two independently-drifting lists.

In `_extract_entities()`, before the `token_count >= 2` branch accepts a multi-word run
unconditionally: iteratively strip *leading* words that are in `_ENTITY_GENERIC_PREFIX_WORDS`.

- If the remainder still has 2+ words → keep the **remainder** (not the original full run) as the
  candidate — correctly extracts `"Kimi K3"` alone out of `"Китайская ИИ-модель Kimi K3"`.
- If the remainder is exactly 1 word → two sub-options, both disclosed:
  - **Option A (minimal, safe default)**: apply the *existing, unchanged* single-token strong
    check to the remainder. Fixes all 3 known false positives. Does not address false-negative
    risk #1 (bare `Saul`/`Google`/`Samsung` remain invisible) — but does not make it any worse
    than today either, since the bundled form never had real matching value in practice.
  - **Option B (more complete, larger)**: apply a *narrowly broadened* rule to the remainder only
    — since we already know this position was flagged as a capitalized-run candidate and a generic
    prefix was just stripped from it, treat the remainder as a valid single-entity candidate if it
    is 3+ letters and not itself a common word (reusing the same kind of short stopword exclusion
    M7.2 already introduced for a different claim type). This would let `"Saul"` survive as its own
    entity claim after `"Агент"` is stripped, giving it a real chance to match evidence that
    mentions `"Saul"` elsewhere in different phrasing. Larger surface, needs its own dedicated
    false-positive regression sweep (a bare, ordinary word remaining after a stripped prefix is a
    new pattern this codebase hasn't tested before) before shipping.
- If the remainder is empty (the entire run was generic words, e.g. a hypothetical `"Автономная
  система"` with no product name attached) → discard entirely, matching current behavior for a
  bare descriptor phrase.

**Recommendation**: implement Option A first (matches "do not redesign architecture," fixes the
three confirmed false positives with the smallest possible diff), explicitly flag risk #1 as
carried forward and undecided, and treat Option B as a distinct, separately-authorized follow-up
if fuller single-name detection is wanted later — mirroring exactly how M7 discovery separated the
low-risk calibration-wiring fix from the larger money-classification fix.

**A disclosed tension worth a human decision, not resolved here**: nationality adjectives
(`Китайская`, `Российская`, `Американская`) are *both* a common source of this false-positive
bundling *and* a common, genuine part of official proper names (e.g. "Российская Федерация" /
"Russian Federation" — where the adjective IS part of the real name, not a generic modifier). A
blanket strip-list cannot distinguish these two cases from word-shape alone. Given the three known
examples specifically require nationality-adjective stripping (`Китайская ИИ-модель`), this
milestone would need to either accept the small risk of also stripping a genuine adjective-noun
official name (rare in this pipeline's own real content, per the M5.3 report's own China/КНР
alias precedent already handling that specific country name separately), or scope the nationality
list even more narrowly (e.g. only strip a nationality adjective when the word immediately
following it is *also* a recognized technology-descriptor word, not just any capitalized word) —
a design choice for the implementer, not decided by this discovery document.

## Required tests (for the future implementation milestone — not written here)

1. Regression: `"Автономный ИИ-агент"` → not extracted as an entity at all (fixed false positive).
2. Regression: `"Агент Saul"` → not extracted as the bundled 2-word phrase (Option A) — or
   extracted as `"Saul"` alone (Option B), matching whichever option is chosen.
3. Regression: `"Китайская ИИ-модель Kimi K3"` → extracted as exactly `"Kimi K3"`, not the full
   4-word phrase.
4. False-negative safety: a genuine 2-word product/company name with NO generic prefix (`"Kimi
   K3"`, `"Trip.com Group"`, `"Tesla Inc"`) must still extract exactly as today — zero regression
   on the existing `test_extract_claims_entity_catches_multiword_and_acronym_and_camelcase` case.
5. False-negative safety: a genuinely fabricated entity using a generic-prefix word plus a real
   name that does NOT match evidence must still be flagged (e.g. `"Агент Marcus"` when evidence
   only ever mentions `"Saul"`) — under Option A this still requires the remainder to independently
   pass the single-token check, so this specific pin only becomes meaningful if Option B ships;
   under Option A, document explicitly that this case would NOT be flagged (a known, accepted gap).
6. Nationality-adjective tension test: a hypothetical or real "Adjective + Noun" official-name
   case (if one exists in real production data) should be checked against the final strip-list
   scope before shipping, to confirm it is not incorrectly stripped.
7. Regression: every existing entity test in `tests/test_fact_safety.py` (`test_entity_
   normalization_strips_legal_suffix_and_case`, `test_extract_claims_entity_ignores_lone_sentence_
   initial_word`, `test_extract_claims_entity_catches_multiword_and_acronym_and_camelcase`,
   `test_extract_claims_entity_never_spans_a_newline_boundary`, `test_7_supported_named_company_
   and_person`, `test_8_unsupported_secondary_investor_is_medium_not_high`, `test_8b_unsupported_
   entity_central_to_story_is_high`, `test_8c_alias_canonicalization_does_not_break_centrality_
   for_a_still_genuinely_unsupported_entity`) must continue passing unchanged.
8. Backtest: the same 281-draft real-production backtest discipline M7.1/M7.2 used, before/after,
   confirming zero drafts move toward a less-cautious verdict.

## Status

**Discovery only — no code, test, or schema file was changed.** `git status` before and after this
document confirms zero tracked-file changes beyond this new doc.
