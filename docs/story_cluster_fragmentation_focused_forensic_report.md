# STORY CLUSTER FRAGMENTATION + WEAK FIRST-SOURCE FORENSIC REPORT

Forensic only. No code changed. Reconstructed entirely from real, persisted rows produced during the 2-hour Story Memory shadow bake (`docs/story_memory_shadow_bake_report.md`), against committed HEAD `00618bd35db7c3da7775be2ab6c2de0d67c5ec33`.

## 1. Executive summary

**The central finding of this investigation is not what the brief's own hypothesis list led with.** In both Cluster A and Cluster B, Story Memory's shadow decision **already correctly linked the "weak" first post and the "rich" second post to the same real Story.** Cluster fragmentation, entity extraction, and pairwise scoring are not the primary defect here — the mechanism mostly worked. Two other things are the real story:

1. **Both "weak" first posts (A1, B1) are not a different, earlier, thinner real source — they are the *same underlying publisher article* (3DNews, in both cases) ingested a second time through a Google News RSS wrapper**, whose redirect never resolves (`REDIRECT_UNRESOLVED`, 0 characters extracted). The genuinely rich direct-3DNews RSS entry for the *identical* article was already collected in the same database, within roughly a minute of the wrapper entry, in both clusters. This is a **duplicate-ingestion-via-two-RSS-paths** pattern, not a Story Memory precision defect.
2. **The reason both posts still went out as independent Telegram messages is the shadow bake's own deliberate, safety-required configuration** — `telegram_story_reply_mode="off"` for the entire run. Story Memory's real, correct linkage (Cluster A: `story_update`, 0.75; Cluster B: both events share one real `story_id`) had **zero effect on delivery by design**, exactly as the safety invariant required. This is the "observational reason," and it is sufficient by itself to explain both duplicate deliveries — no further defect is required to explain the observed Telegram behavior.
3. A secondary, correctly-scoped finding: the CONTENT_GENERATION-stage stale-Research-reuse pattern (fixed for Snapdragon/VK earlier this session) **does recur mechanically in both A2 and B2** (sub-30ms reused Research steps, bit-identical to the NEWS_ANALYSIS-stage result) — but **verified harmless in both cases**, because the direct-3DNews RSS excerpt itself already contained the core facts NEWS_ANALYSIS's Research used, unlike Snapdragon's thin excerpt. The user's explicit caution against assuming recurrence was correct to raise and is answered precisely: the mechanism recurs, its *impact* does not.
4. First divergence point for both clusters: **SOURCE CONSOLIDATION** (§13).

## 2. Russian AI values cluster — identifiers and timeline

| | A1 (weak) | A2 (rich) |
|---|---|---|
| Source NewsEvent | `62c66d1a-8aef-413a-9bda-34947248e5e8` | `8a7e2647-592a-4f34-9345-e7e47d8166ea` |
| Source | Google News RU: ИИ (RSS wrapper) | 3DNews (direct feed) |
| Real article URL | `news.google.com/rss/articles/...` (redirect, never resolved) | `https://3dnews.ru/1146777/...` (the real article) |
| `published_at` | 2026-08-13 14:34:00 UTC | 2026-08-13 14:34:00 UTC (**identical** — same real article) |
| `collected_at` | 14:46:41.399 | 14:45:53.113 (**48 seconds earlier**) |
| Acquisition | `REDIRECT_UNRESOLVED`, 0 chars, `error_code=google_news_redirect_unresolved` | `FULL_TEXT`, 8990 chars |
| NEWS_ANALYSIS task created | 14:47:59.635 | 14:47:59.241 (**394ms earlier** — essentially simultaneous) |
| Story Memory shadow decision | `uncertain_match`, score 0.494, → `story_id fc6bdd98` | `story_update`, score 0.75, → **same** `story_id fc6bdd98` |
| CONTENT_GENERATION task created | 15:55:31.658 | 15:55:40.539 |
| Draft | `82fd03d4-...`, title "Российские ИИ-модели планируют проверить на соответствие традиционным ценностям" | `15b9050e-...`, title "Российские ИИ-модели будут проверять на соответствие закону и «традиционным ценностям»" |
| Delivered | Yes (real send, per bake's `_recorded_sends`) | Yes (real send) |

**Was the richer source already available before the first Telegram delivery?** Yes, unambiguously — A2's own NewsEvent was collected 48 seconds *before* A1's, and A2's own acquisition/Research had already completed (NEWS_ANALYSIS Research finished 15:35:45) well before A1's own NEWS_ANALYSIS Research even started (15:41:04). By the time A1's CONTENT_GENERATION draft was created (15:55:31), A2's rich draft was also already mid-creation (15:55:40) — both were selected into the same CONTENT_GENERATION batch, 9 seconds apart, and both delivered.

## 3. Russian AI values — fact propagation

| Fact | A1 source | A2 source | A1 final post | A2 final post |
|---|---|---|---|---|
| Putin approved/signed the law | Not in A1's evidence (Google redirect never resolved) | Present, explicit | Absent — draft says organizer/criteria "не сообщается" | **Present**: "Владимир Путин утвердил закон" |
| Scope: large/fundamental AI models must comply with law + traditional values | Absent | Present | Absent (framed only as "экзамен по духовности", no legal framing) | **Present**, framed as the lead fact |
| Independent testing lab, Ministry (Минцифры) approval | Absent | Present | Absent | **Present** |
| Organizer / who runs it | Absent (correctly flagged as unknown) | Present in the full article (правкомиссия, ФСБ, ФСТЭК) but **not extracted into Research's facts** (Research ran on the RSS excerpt, before full acquisition) | Absent | Absent (this deeper layer never reached Copywriting in *either* post — see §9) |
| Model list | Absent | Absent (not in the RSS excerpt or Research's facts; present only deeper in the full 8990-char article) | Absent | Absent |
| Evaluation criteria/procedure | Absent | Absent ("Критерии проверки... пока не определены" — correctly stated as undetermined, matches the source) | Absent | **Present as an honest gap**: "Критерии проверки и порядок её проведения пока не определены" |

**A2 is: the same underlying event, from the direct publisher source instead of a failed aggregator redirect — enriched, but not fully.** Not a "genuine later UPDATE" in the sense of new real-world developments; the underlying event (the law, already passed in July and signed by Putin) predates *both* posts. A2 simply reached a working copy of the source A1's own source-selection unluckily failed to resolve.

## 4. Twitch/Amazon cluster — identifiers and timeline

| | B1 (weak) | B2 (rich) |
|---|---|---|
| Source NewsEvent | `ec54a4bd-4574-4568-96f7-d3a5b19f85d1` | `405e767a-acef-493e-9ec4-bebb38fe50a8` |
| Source | Google News RU: ИИ (RSS wrapper) | 3DNews (direct feed) |
| Real article URL | `news.google.com/rss/articles/...` (redirect, never resolved) | `https://3dnews.ru/1146774/...` |
| `published_at` | 2026-08-13 14:03:23 UTC | 2026-08-13 14:03:23 UTC (**identical**) |
| `collected_at` | 14:17:29.878 | 14:16:27.641 (**62 seconds earlier**) |
| Acquisition | `REDIRECT_UNRESOLVED`, 0 chars | `FULL_TEXT`, 8167 chars |
| NEWS_ANALYSIS task created | 14:20:44.700 | 14:20:41.032 (**3.7 seconds earlier**) |
| Story Memory shadow decision | `semantic_duplicate`, score 1.0, → `story_id 064f24bb` | `related_story`, score 0.333, → **same** `story_id 064f24bb` |
| CONTENT_GENERATION task created | 15:23:16.420 | 15:23:38.380 |
| Draft | `aca6eef5-...`, "3DNews: Twitch начал обучать ИИ на контенте пользователей, не спрашивая их" | `4175c5f0-...`, "Twitch включил использование контента пользователей для обучения ИИ Amazon" |
| Delivered | Yes | Yes |

Same pattern as Cluster A: the rich direct source was collected roughly a minute before the wrapper, and both events reached NEWS_ANALYSIS within 4 seconds of each other.

## 5. Twitch/Amazon — fact propagation

| Fact | B1 source | B2 source | B1 final post | B2 final post |
|---|---|---|---|---|
| Twitch enables using channel content to train AI | Present (headline only) | Present | **Present** | **Present** |
| Amazon models specifically | Absent from B1's own evidence | Present | Absent — B1's draft doesn't name Amazon | **Present**: "для обучения ИИ Amazon" |
| Opt-in default / no separate consent | Present (headline framing only) | Present, detailed | Present (framing only) | **Present** |
| Opt-out mechanism (manual, account settings) | Absent (explicit gap in Research) | Present | Absent | Absent from the *published* body — draft doesn't mention the mechanism despite it being in the full article (a second-layer detail, same pattern as §3) |
| Community criticism | Present (headline framing) | Present, detailed | Present | **Present**: "Сообщество сервиса резко раскритиковало решение" |
| Mike Minton quote/rationale | Absent | Present, full quote | Absent | **Present**: "«Будь это добровольно, никто бы не согласился»" attributed to Minton |
| Non-exclusive use for other AI features (AutoMod etc.) | Absent | Present | Absent | Absent from the published body (a third-layer detail, never extracted) |

**B1 is a fragmentary source representation of the same event B2 covers; B2 contains genuinely richer detail (the named executive, his quote, the specific rationale) that reached Copywriting via the RSS excerpt itself** — but even B2's own published post did not carry the full article's deepest details (opt-out mechanism, AutoMod carve-out), matching the pattern already seen in Cluster A: the full acquired article is always richer than what NEWS_ANALYSIS-stage Research (built on the RSS excerpt) extracts, because acquisition happens too late in the pipeline to inform that Research call (§9).

## 6. Cluster-level graph analysis

Both real clusters were larger than the two posts each described in the brief — **12 real NewsEvents** for Cluster A (spanning 04:57–15:01 UTC) and **8 real NewsEvents** for Cluster B (spanning 06:27–14:17 UTC), all about the same respective underlying stories, all present in the DB during this bake.

**Cluster A graph** (from the bake's own live-captured candidate scores, §2 of `story_memory_shadow_bake_report.md`'s underlying data): A1's own top-scoring candidate (0.494) and A2's own top-scoring candidate (0.75) are **not each other** — each matched against whichever member of the pre-existing, hours-older 12-event cluster scored highest *for it specifically* at the moment it was processed. Both nonetheless converged on the same `story_id` (`fc6bdd98`), which predates both A1 and A2 (created by an earlier cluster member, published as early as 04:57). **Sequential incremental linking against a growing Story — not a full pairwise clique computation — is what achieved correct consolidation here.**

**Cluster B graph**: same pattern, more pronounced. B1's own top candidate scored a *perfect* 1.0 (near-identical title wording) against a *different* cluster member, not B2. B2's own top candidate scored only 0.281 against yet another different member. Neither scored highly against the other directly — **A ↔ B (indirect, via shared Story) = linked; B1 ↔ B2 (direct pairwise) = weak (0.28, well below any confident threshold)**. This is exactly the "A↔C low, but both connect via B" pattern the brief anticipated (§6's own example), confirmed with real data. **This is a genuine pairwise-scoring limitation, not a missing-evidence problem**: had Story Memory only ever compared B1 and B2 directly against each other (rather than each against the whole growing candidate pool), it would very plausibly have kept them separate.

## 7. Source consolidation timing

**Was the first post published too early?** In both clusters: **the richer source was already fully collected — not merely queued or partially processed — before the weak post's own NEWS_ANALYSIS even began.** Measured delays: Cluster A, 48 seconds (collection) / A2's NEWS_ANALYSIS Research finished 5m19s before A1's own NEWS_ANALYSIS Research even started. Cluster B, 62 seconds (collection) / B2's NEWS_ANALYSIS Research finished 4m32s before B1's own NEWS_ANALYSIS Research started.

Both weak posts' own CONTENT_GENERATION stage ran **after** the rich sibling's article had been fully, successfully acquired elsewhere in the same corpus — the system, in aggregate, already possessed everything needed to write the rich version at the moment it instead wrote the thin one. This is not a "not yet arrived" timing gap; it is a **"arrived, but never consulted"** gap. No delay timer is proposed (per instruction) — the real source was not "about to arrive shortly," it had already arrived.

## 8. Existing enrichment/suppression capabilities

Audited against this session's own accumulated knowledge of the codebase plus direct confirmation this phase:

| Mechanism | State | Relevant here? |
|---|---|---|
| `services/story_duplicate_guard.py::check_duplicate_story_delivery()` | Fully built, fully wired, correctly enforcing for confident match types with a prior root delivery | **Would apply directly to Cluster B if `story_memory_mode=enforce`** — B1 landed `semantic_duplicate` (1.0) against a Story; had that Story already had a delivered root, this guard would have blocked B1 as a duplicate. Not reachable in shadow mode. |
| `services/story_telegram_delivery.py::determine_reply_target()` | Fully built, pure function | **Would apply directly to Cluster A** — A2's `story_update` (0.75) against A1's own Story would route A2 as a reply to A1's root, if `telegram_story_reply_mode=enforce`. Not reachable in shadow mode (deliberately, this bake's own safety invariant). |
| `EvidencePackage.previous_coverage_summary` | Confirmed, again, genuinely unbuilt (Phase 19 M7 Story Timeline digest never implemented) | Would not have helped here even if built — the gap is not "Copywriting doesn't know prior coverage exists," it's "Research never saw the richer sibling's *content* at all," a different, earlier-stage gap. |
| `services/story_context.py::build_story_timeline()` (`story_context_mode`, shadow-only) | Exists, deterministic, evidence-only, but shadow-only and never read by Copywriting | Same limitation as above — even where computed, not consumed. |
| A mechanism to attach a richer second source's evidence to an *already-selected* weak event's own Research/acquisition, before or instead of a failed acquisition | **Does not exist.** No code path cross-references "is there another `NewsEvent` covering the same real article, already successfully acquired, that this event's own failed acquisition could fall back to." | **This is the one genuinely missing capability** — not Story Memory, not suppression, not reply-routing, all three of which already exist and are correctly built. |
| A mechanism to edit/enrich an *already-sent* Telegram root message with a later-arriving richer source | **Does not exist.** | Not evidenced as needed here specifically (both weak posts' hedges were honest, not false — §9), but relevant to any future "enrich the root" remediation option (§14). |

**Direct answer to the brief's own question**: the system already has a way to attach a richer second source to an existing Story *without publishing a second independent root* — `determine_reply_target()` + `check_duplicate_story_delivery()`, both fully built — **but only once `telegram_story_reply_mode`/`story_memory_mode` reach `enforce`.** What the system does *not* have is a way to give the *first* post itself the richer evidence when a redirect-unresolved acquisition fails but a working duplicate-via-different-RSS-path sibling already exists.

## 9. First-source evidence quality

Both A1 and B1 inspected directly (raw acquisition rows, Research input/output, Copywriting input, §2/§4/§3/§5 above):

- **A1**: acquisition `REDIRECT_UNRESOLVED`, 0 characters. Research's own `gaps` field explicitly and correctly states: *"Ссылка на материал присутствует, но текст статьи не предоставлен"* ("a link is present but the article text was not provided"). Copywriting's hedge ("пока не сообщается, кто его организует...") is a direct, honest, correctly-scoped restatement of that gap — not an invented claim, not a contradiction of anything Research knew.
- **B1**: acquisition `REDIRECT_UNRESOLVED`, 0 characters. Research's `gaps`: *"Содержимое статьи доступно только по ссылке; факты из самой статьи в тексте не приведены."* Copywriting's hedge ("В доступном фрагменте не уточняется...") is equally honest and correctly scoped.

**Classification for both A1 and B1: `EVIDENCE-CORRECT BUT SOURCE-WEAK`.** Not evidence loss (nothing was lost — nothing was ever acquired), not Research loss (Research correctly reported zero confidence beyond the bare headline), not Copywriting contradiction (nothing published contradicts the — thin — evidence actually available). The individual posts are honest. The system-level problem is that a working alternative source for the *identical* article already existed in the same corpus and was never consulted.

## 10. Source consolidation timing

(See §7 — combined per the report's own numbering to avoid duplicate content; the measured delays and "already arrived, never consulted" finding stated there apply identically to both clusters.)

## 11. Existing enrichment/suppression capabilities

(See §8.)

## 12. Comparison with Zoom / VK / Microsoft

| | Root mechanism | A/B clusters? |
|---|---|---|
| **VK** | Entity-extraction bug (a leading noun contaminating the entity string) — fixed | **No.** Neither A nor B shows an entity-extraction defect; A2 reached `entity_overlap=1.0` against A1's Story cleanly. |
| **Zoom** | Genuinely same event, near-total *lexical* mismatch (coined nickname, zero title/entity overlap) even with correct extraction | **No.** A1/A2 and B1/B2 share substantial title/entity overlap where compared directly against each other; where scores were low (B1↔B2 direct, §6), it's a graph-connectivity artifact, not a Zoom-style vocabulary gap. |
| **Microsoft Copilot** (shadow bake report, §9/§10) | Real cluster, some pairwise comparisons confident, others near-miss, no single dominant explanation identified | **Partially similar** — the graph-connectivity finding in §6 (B1↔B2 direct = weak, both↔Story = correct) is the same general *family* of behavior: sequential/pairwise matching against a growing pool produces different confidence for different pairs within one real cluster. |
| **A/B clusters' own distinguishing trait** | **A specific, structural, two-RSS-path duplicate-ingestion pattern** (direct feed + Google News wrapper of the identical article), with the weak side's acquisition failing outright (`REDIRECT_UNRESOLVED`), not merely scoring low | **New** — not previously characterized this precisely in any prior forensic report this session. |

**A and B do not belong to the Zoom/Microsoft "lexical mismatch/fragmentation" family as their primary defect.** They belong to a distinct, newly-characterized family: **duplicate ingestion of one real article via two RSS delivery paths, where one path's acquisition structurally cannot succeed (Google News redirect).** The Microsoft-style graph-connectivity nuance is present as a real secondary contributor in Cluster B specifically (§6), not the dominant cause in either cluster.

## 13. First divergence points

**Cluster A: `SOURCE CONSOLIDATION`.** Story Memory itself performed correctly (`story_update`, 0.75, well above `_HIGH_THRESHOLD`) once both events reached matching. The earliest decisive structural boundary is upstream of Story Memory: the same real article was ingested twice via two RSS paths with no cross-referencing, and the failed-acquisition path was processed and published before (or regardless of) the successful path's own richer content.

**Cluster B: `SOURCE CONSOLIDATION`**, with a disclosed secondary contributor at **`PAIRWISE STORY SCORING`** (§6's direct B1↔B2 weak edge) — the primary reason both delivered independently is still the same duplicate-ingestion pattern as Cluster A; the graph-connectivity nuance means that even a hypothetical fix to the ingestion problem alone might not guarantee B1 and B2 specifically score as a confident pair against *each other*, though both would very plausibly still land in the same Story via the existing sequential-linking mechanism, as they already did in this real run.

**`SHADOW-ONLY OBSERVATION` is the decisive reason both posts were actually delivered to Telegram** in both clusters — stated separately, per the brief's own instruction to distinguish the observational reason from the structural one. It is not a "divergence point" in the code-defect sense (this bake intentionally ran in shadow); it is the accurate, complete answer to "why did Telegram send both."

## 14. Minimal remediation options

**Not implemented. For evaluation only. Maximum 3, all reusing existing components.**

### Option 1 — cross-reference acquisition failures against already-collected same-URL-family siblings

**Label: `NARROW DETERMINISTIC FIX`.** Mechanism: when article acquisition returns `REDIRECT_UNRESOLVED` (or another weak-tier status) for a Google News wrapper URL, perform one additional, already-safe lookup — query for another `NewsEvent` published within a short window (minutes, not hours) whose `canonical_url`/resolved acquisition succeeded and whose title is a near-exact match (reusing `token_overlap_ratio()`, already production-safe) — and if found, use *that* event's already-fetched, already-clean text as this event's evidence, exactly as `reused_from_news_event_id` already does for the existing acquisition-reuse-within-window mechanism (`article_acquisition_reuse_window_hours`, §2 of `core/config.py`'s own commentary). **Fixes A? Yes, directly** (A2's acquisition already existed 48s before A1 was even collected). **Fixes B? Yes, directly** (same mechanism, 62s gap). **Helps Zoom/Microsoft? No** — those are not acquisition-failure cases, this option doesn't touch matching/scoring at all. False-suppression risk: low — this only ever *upgrades* evidence quality for an event whose own acquisition already failed, never suppresses or merges a delivery. Latency impact: one bounded, indexed title-similarity query, comparable cost to the existing acquisition-reuse lookup. Cost impact: none (no new LLM call — reuses already-fetched text). Offline golden calibration: **yes**, directly — the exact A1/A2 and B1/B2 pairs are real, ready-made fixture material (§15).

### Option 2 — enable `telegram_story_reply_mode=shadow` (not enforce) alongside the existing story_memory_mode=shadow bake

**Label: `WIRING ONLY`** (a config-mode change, not a code change — already-built machinery, per §8). Mechanism: with `telegram_story_reply_mode=shadow`, the real reply decision (`determine_reply_target()`) is computed and *persisted* (`ContentDraftReplyRoutingProposal`) for every story-linked event, without ever changing an actual send — giving direct, real visibility into exactly which of these duplicate-delivery patterns `enforce` would actually fix, before authorizing `enforce`. Does not fix A or B's *delivery* by itself (shadow never suppresses), but directly measures whether Option 1 is even necessary versus Story Memory/reply-routing alone being sufficient once truly enabled. Helps Zoom/Microsoft evaluation the same way. False-suppression risk: **zero** (shadow never suppresses by construction, confirmed throughout the whole prior bake). Latency/cost: negligible (pure Python, no LLM). Offline calibration: not applicable — this is itself a further data-gathering step, not a fix.

### Option 3 — a narrow, source-type-aware collector-side dedup key for Google-News-wrapper-vs-direct-feed pairs

**Label: `EDITORIAL POLICY` / borderline `NARROW DETERMINISTIC FIX`.** Mechanism: at collection time (before either event reaches NEWS_ANALYSIS), recognize that a Google News RU RSS entry whose *title* exactly or near-exactly matches an already-collected direct-feed entry from a *named* real publisher (3DNews, in both observed cases) within a short window is very likely the same article pre-emptively, and either skip creating a second `NewsEvent` entirely or immediately mark it `reused_from_news_event_id` pointing at the direct one — before any acquisition attempt is even made. **Fixes A and B identically to Option 1**, one layer earlier (collection, not acquisition-failure-recovery). Risk: **materially higher than Option 1** — a title-only pre-collection dedup risks discarding a genuinely distinct story that happens to share a template-driven headline (the exact templated-content risk already flagged in the calibration report, §9 of `story_memory_content_overlap_calibration_report.md`) *before* any of Story Memory's own downstream safeguards ever get a chance to look at it. Not preferred over Option 1, which acts only *after* a real acquisition failure and only as an evidence upgrade, never a suppression.

**Preferred, if authorized: Option 1**, narrowest, safest, most directly reuses an already-proven pattern (`reused_from_news_event_id`), and is calibratable offline against real data already in hand.

## 15. Golden fixture candidates

**Not added this phase.** Proposed, fully evidenced, ready for a future dedicated phase:

1. **`ru_ai_values_wrapper_duplicate`** (Cluster A) — real event IDs, real acquisition rows, real Story Memory shadow decision (`story_update`, 0.75) already in hand from this report. Would pin: (a) the correct Story Memory linkage (already working, must not regress), (b) the missing acquisition-fallback capability (Option 1, once implemented).
2. **`twitch_amazon_wrapper_duplicate`** (Cluster B) — same shape, real data in hand. Would additionally pin the direct-pairwise-vs-cluster-graph nuance (§6): B1↔B2 direct comparison should NOT be asserted as confident even after any Option 1 fix, only the *shared-Story* outcome should be.
3. **A new category**: **`google_news_wrapper_vs_direct_feed_same_article`** as its own labeled pattern in the corpus documentation (distinct from the already-existing plain `google_news_wrapper_unresolved` evidence-acquisition case) — the golden suite's existing case proves the wrapper *fails correctly*; these two new cases would prove the *consequence* of that correct failure (a real duplicate root) is not yet handled.
4. **The one clear false positive from the shadow bake** ("В поиске товаров через ИИ" vs. "70% работодателей внедряют ИИ в найм") — **not reconstructed this phase**; would require its own real entity-signature/candidate-pool pull, out of this investigation's two-cluster scope. Flagged again here for a future dedicated pass, per instruction, rather than fabricated.

## 16. Recommended next action

Both clusters trace to the same real, precisely-characterized, narrow structural gap (duplicate ingestion of one article via two RSS paths, compounded by this bake's own intentional shadow-only observation mode) rather than to Story Memory scoring, entity extraction, or cluster-fragmentation defects, which is why this is not a scoring-calibration question. The fix (Option 1) is narrow, reuses an already-proven mechanism, and is directly calibratable against the real data already gathered — but it is still a real code change to acquisition-failure handling, not something to implement inside a forensic-only phase, and Option 2 (a further shadow-only data-gathering step) is a reasonable, even lower-risk precursor.

### `READY FOR NARROW FIX`

STOP after this report. No production code modified. No scoring changed. No prompts changed. Enforce not enabled. Not committed. Not deployed. No further live bake run. Video and source-pack work not resumed.
