# Phase 18.8 M3 — Isolated Meme Shadow Validation

Status: complete. **Production `meme_opportunity_mode`/`meme_safety_gate_mode` were never touched
- both remain `"off"`.** This is a re-run of Phase 18.5's own existing, unmodified, read-only
`scripts/phase18_5_shadow_collection.py` tool against the current full corpus (13,520 real events,
up from 12,430 at Phase 18.5's original run - the 1,090 fresh events M2 just ingested, plus other
real growth since) - zero new code, zero calibration-rule changes (the brief's own explicit
restriction), zero database writes, zero LLM calls, zero Telegram sends, zero image generation.

Verified directly (not just claimed): real `NewsEvent` row count identical before/after
(13,520 → 13,520), and zero `EditorialTask` rows reference `meme_opportunity` in their `workflow`
JSON (still 0, same check Phase 18.5 M0 first established) - confirms this ran entirely outside the
live pipeline, exactly as `services/meme_shadow_analytics.py`'s own module docstring guarantees.

## 1. Candidate count / decision distribution

| Label | Count | Share |
|---|---|---|
| HIGH (`MEME_READY`) | 0 | 0.00% |
| MEDIUM (`REVIEW`) | 151 | 1.12% |
| LOW (`NOT_SUITABLE`/`INSUFFICIENT_SOURCE`) | 13,165 | 97.37% |
| BLOCKED (`SENSITIVE_BLOCK`) | 204 | 1.51% |

Opportunity rate (HIGH+MEDIUM/total) is now **1.12%**, up from Phase 18.5's original 0.44% - driven
by the freshly-ingested batch (96 of the 151 real `MEDIUM` records were created in the last 15
minutes, i.e. from M2's own collection run), which skews far more AI/arXiv-heavy than the
historical corpus (M2 §5: 42.4% AI in the fresh batch vs 26.0% historically). Still, **zero events
have ever reached `HIGH`** - consistent with every prior phase's own finding; the composite-score
ceiling problem Phase 18.5/18.7 already documented persists unchanged (v1 thresholds/scoring were
not touched in this phase, per this phase's own explicit restriction).

## 2. Safety blocks

**1.51%** of all 13,520 events (204) hard-blocked, consistent with Phase 18.5's original 1.46%:

| Category | Count |
|---|---|
| legal_jeopardy_or_accusation | 56 |
| death_or_tragedy | 47 |
| war | 40 |
| disaster | 32 |
| crime_with_victim | 27 |
| harassment_or_stalking | 5 |
| protected_characteristics | 3 |
| minors_safety | 2 |

## 3. Categories (among potential-meme records)

| Category | Share |
|---|---|
| AI | 92.7% |
| GADGETS | 2.6% |
| STARTUPS | 2.6% |
| UNKNOWN | 1.3% |
| SOFTWARE | 0.7% |

Even more AI-concentrated than Phase 18.5's original 89.1% - directly explained by the fresh
batch's own heavy AI/arXiv skew (§1).

## 4. Examples and suspicious false positives (from the fresh, real 15-minute batch specifically)

**MEDIUM (96 fresh records) - overwhelmingly the same arXiv/academic-abstract pattern Phase
18.5 M4 and Phase 18.7 already documented and built a (still-off, `v1`-default) v2 fix for**: the
large majority of the 96 fresh `MEDIUM` items are arXiv-style paper abstracts scoring 37-43,
triggered by `contrast_connector` + `topic_fit_prior:AI` (e.g. *"Time series anomaly detection
(TSAD) underpins applications in predictive mainte…"*, *"Chain-of-Thought (CoT) reasoning offers a
promising window into model monitoring…"*). This is real, live, ongoing confirmation of the exact
pattern Phase 18.7's `services/meme_calibration_rules.py` v2 layer already targets - not a new
finding, but real evidence the v2 fix (still `"v1"`/inactive) would matter in live traffic today.

**BLOCKED (22 fresh records) - the exact same game-title "war" false positive recurring live,
repeatedly, on brand-new data:**
- *"Dave Bautista reportedly 'in talks' to take over the role of Kratos…"* → `war:war`
- *"Play Gears of War: E-Day Before Others With Xbox Game Pass"* → `war:war`
- *"Дэйв Батиста может сыграть Кратоса в сериале по God of War"* → `war:war`
- *"Amazon нашла нового кандидата на роль Кратоса в сериале God of War…"* → `war:war`
- *"WoW will let some WeakAura-style mods function in its next major patch…"* → `war:war` (matched
  inside "WoW", i.e. World of Warcraft abbreviation context)

This is the identical class Phase 18.7 M3 already fixed in its (still-inactive) v2 layer, now
observed recurring **four separate times in a single 15-minute real collection window** - strong,
fresh evidence for how frequently this specific false positive actually fires in live traffic.

**Also recurring: the "died"/"killed" tech/product-metaphor false positive** (also already
addressed by Phase 18.7's v2 `died`/`killed` context exceptions):
- *"Rockstar's great Midnight Club racing series was killed off for one simple reason…"* →
  `death_or_tragedy:killed` (a discontinued game franchise, not a real death)
- *"Фронтенд умер? Нет, но AI уже держит лопату"* ("Is frontend dead? No, but AI already has the
  shovel") → `death_or_tragedy:умер` - the same figurative-"death" pattern Phase 18.5 M3 first
  flagged with the "graveyard of smart devices" example
- *"Stochastic single shooting trajectory optimization methods…"* → `crime_with_victim:shooting` -
  the exact literal phrase ("shooting trajectory") Phase 18.7's v2 `shooting` context exception was
  built to catch, recurring live

**One genuinely new false-positive pattern, not previously identified in any prior phase:**
- *"⚠️ Telegram удалили из App Store из-за атаки вымогателя"* ("Telegram was removed from the App
  Store due to a ransomware attack") → blocked on `legal_jeopardy_or_accusation:перечень
  террористов` ("terrorist registry"). The story is about a ransomware/extortion attack causing an
  App Store removal - not a terrorism-registry matter. The exact substring match location within
  the full article text wasn't inspected further (out of scope - no lexicon changes are authorized
  in this phase), but this is flagged here as a new, real candidate for a future calibration
  finding, not fabricated or assumed.

**Two examples that are likely correct, defensible blocks, not false positives** (included for
balance, not every BLOCKED item found here is a bug): *"OpenAI pays $3.2m to settle claims it
discriminated against US workers"* and *"Apple sued over alleged lack of age checks…"* both
matched `legal_jeopardy_or_accusation:alleged` - both are genuine legal-jeopardy stories about real
companies; the block is arguably correct even if "alleged" is a broad trigger word.

## 5. Relationship to Phase 18.7's v2 calibration layer

Every recurring false-positive class found here in fresh, live data (`war`+game-title,
`died`/`killed`+metaphor, `shooting`+technical-context) is one Phase 18.7 already built a fix for
in `services/meme_calibration_rules.py` - still inactive (`meme_opportunity_calibration_version`/
`meme_safety_calibration_version` both `"v1"`, not wired into any live call site). This phase does
**not** activate it (explicitly out of scope - "DO NOT... modify calibration rules" and no
production-mode activation was authorized here) but the fresh evidence gathered in this run is a
real, additional data point supporting that a future, separately-authorized activation decision has
real, current, recurring problems to fix, not just historical ones.

## 6. Summary

| Check | Result |
|---|---|
| Shadow evaluation ran read-only, offline | ✅ (verified: NewsEvent count unchanged, zero `meme_opportunity` EditorialTask rows) |
| No LLM calls | ✅ (`assess_meme_opportunity()` is a pure deterministic function, no LLM Gateway import) |
| No Telegram sends | ✅ (no `bot.` import anywhere in the executed code path) |
| No image generation | ✅ (no image-generation import anywhere in the executed code path) |
| No calibration-rule changes | ✅ (v1 classifier only; `services/meme_calibration_rules.py` untouched) |
| Production shadow modes activated | ❌ — correctly, both remain `"off"` |
