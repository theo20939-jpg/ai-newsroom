# R2 Shadow Contract

**Status: DESIGN ONLY — no code written under this contract yet.** Isolated worktree
`../ai-newsroom-r212`, branch `feature/r2-shadow-preparation`, based on the R2.11 checkpoint
(`44d5595015ee77b00e1841a477bc481b27333411`). Implementation waits for explicit confirmation.

## 1. What Shadow Mode is

Shadow Mode is a **read-only observation layer** over the existing, already-built EVENT_RECAP
pipeline (`services/event_recap.py`, `services/recap_event.py` — frozen — and
`scripts/_recap_r2_10_readiness_candidate_scanner.py`). It:

- uses the existing `build_event_recap_candidate()` / `scan_story_readiness()` pipeline, unchanged;
- analyzes real Stories (read-only DB access, same discipline as every prior R2 diagnostic script);
- builds real `EventRecapCandidate` objects — anchor, evidence bundle, verified facts, timeline,
  media candidates — from real data;
- MAY, later, optionally run one real synthesis call per Story under `--with-llm --single-attempt`
  (the same guarantee `scripts/_recap_r2_event_shadow.py` already provides) — never a batch, never
  automatic;
- produces structured, human-reviewable output artifacts (JSON/text files) for editorial
  inspection;
- **never publishes anything, anywhere, under any condition.**

Shadow Mode is not a new architecture. It is the disciplined, observable *use* of architecture that
already exists — a scanning/reporting harness, not a new service.

## 2. Hard safety requirements

| Control | State | Enforcement |
|---|---|---|
| Telegram SEND | **OFF, unconditionally** | No import of `bot/`, `worker/`, or any delivery path anywhere in shadow code — same AST guard (`test_no_bot_or_worker_or_telegram_imports_anywhere_in_r2`) already applied to every R2 module, extended to any new shadow module |
| Production channel | **OFF** | Direct consequence of the above — nothing in shadow code can reach a channel, editorial or public |
| Billing | **OFF by default** | Deterministic stage makes zero Gateway calls (proven pattern: `test_deterministic_build_never_touches_llm_gateway`). A LATER, explicitly-opt-in synthesis stage may spend, but only under the existing `--with-llm --single-attempt` contract, one Story at a time, human-triggered |
| Workers / auto-execution | **OFF** | Shadow is a manual CLI script, run by a human, exactly like `scripts/_recap_r2_event_shadow.py` and `scripts/_recap_r2_10_readiness_candidate_scanner.py` already are — never registered with any scheduler/worker/Capability registry |
| Database writes | **OFF at this stage** | Read-only transaction guard (`SET TRANSACTION READ ONLY`, verified via `SHOW transaction_read_only`), `statement_timeout`, rollback in `finally` — the exact pattern already proven in both existing R2 scripts |
| LLM calls (deterministic stage) | **OFF** | No Gateway import at module level; deferred import only inside an explicit, opt-in flag, mirroring `--with-llm`'s own existing discipline |

None of these are new mechanisms — every one is a direct reuse of a guard already implemented,
tested, and production-validated in `scripts/_recap_r2_event_shadow.py` and
`scripts/_recap_r2_10_readiness_candidate_scanner.py`. Shadow Mode's own safety story is "apply the
same guards to more Stories, output more structured data" — not "invent new safety machinery."

## 3. Output data

Three logical sections per Story, mirroring `EventRecapCandidate`'s own existing shape one-to-one —
no new fields invented beyond what's needed for human review scoring (section 5).

### Story

| Field | Source (existing, unchanged) |
|---|---|
| `story_id` | `Story.id` |
| `title` | `Story.title` |
| `source_count` | `EventRecapCandidate.readiness_source_count` (verbatim R1 `count_unique_sources()`) AND `evidence_reference_count` (R2's own canonical-URL-aware count) — both surfaced, never conflated (existing R2.2 precedent) |
| `announcement_count` | `EventRecapCandidate.announcement_count` — **must be labeled with the R2.11 caveat**: raw R1 report-level cluster count, not a development count (see `docs/r2_11_announcement_identity_findings.md`) |
| `readiness_state` | `EventRecapCandidate.readiness_state` / `CandidateScanRow.readiness_state` |
| `integrity_result` | `EventRecapCandidate.story_integrity_eligible` + `.story_integrity_reasons` |
| `rejection_reasons` | `EventRecapBuildResult.rejection_reasons` (when rejected outright) |

### Candidate

| Field | Source (existing, unchanged) |
|---|---|
| `anchor_event` | `EventRecapCandidate.anchor_event_id` (+ `origin_projection_applied` flag) |
| `evidence_bundle` | `render_event_recap_bundle_text(candidate)` — already the exact text a synthesis call would see |
| `verified_facts` | `EventRecapCandidate.verified_facts` (numeric + entity, `MULTI_SOURCE_CONFIRMED`/`FACT_SINGLE_SOURCE_ONLY`) |
| `timeline` | `EventRecapCandidate.timeline` |
| `media_candidates` | `EventRecapCandidate.media_candidates` (image/video refs — see §4 on what "relevance" means today) |

**Visual metadata fields** (observation-only, see §4's own owner correction — plain data, never a
rendering):

| Field | Meaning | How computed |
|---|---|---|
| `media_candidate_count` | image + video count | `len(candidate.media_candidates)` |
| `media_spans_multiple_events` | boolean | `len({m.event_id for m in candidate.media_candidates}) > 1` — surfaces the known, documented anchor-preference gap (R2.10 Night 2 Phase 19) |
| `has_media` | boolean | `bool(candidate.media_candidates)` |
| `visual_checklist` | the fixed reviewer checklist from §5 (mobile / desktop / forwarded / topics / buttons), always emitted as unchecked boxes — shadow cannot check any of them itself | static list, not computed from candidate data |

### Evaluation (new — the one genuinely new piece of this contract)

| Field | Meaning | Precedent reused |
|---|---|---|
| `manual_review_required` | boolean — mirrors `CandidateScanRow.recommended_for_manual_review` exactly (already shipped, R2.10 Night 2) | `scripts/_recap_r2_10_readiness_candidate_scanner.py::CandidateScanRow` |
| `quality_notes` | plain list[str] — deterministic, non-scored notes (e.g. "media_candidates empty", "announcement_count may include duplicate reports — see R2.11", fact-verification flags if a synthesis stage ran) | mirrors `EventRecapCandidate.quality_flags`'s own established shape (plain strings, never a synthetic score — `evaluate_recap_readiness()`'s own "no AI score" discipline, reused, not reinvented) |
| `evaluation_status` | a 3-value, **shadow-local** enum: `OBSERVED` / `NEEDS_REVIEW` / `REJECTED` | **Owner correction (approval round):** deliberately NOT `fact_safety.py`'s `pass`/`review`/`block` vocabulary — shadow observation is a different concern from fact verification and must not silently inherit fact-safety's semantics or thresholds by reusing its words. `TelegraphProposalStatus`'s "deliberately minimal, no broad workflow enum" discipline is still the precedent for keeping this to exactly 3 values, but the vocabulary itself is shadow-local. `REJECTED` maps to `EventRecapBuildResult.rejected is True` (no candidate at all); `NEEDS_REVIEW` maps to `manual_review_required is True` or any non-empty `quality_notes`; `OBSERVED` is the default otherwise — a candidate was successfully built and nothing flagged it |

No DB table for this output. Every existing R2 diagnostic writes JSON + human-readable `.txt` to
disk (`scripts/_recap_r2_event_shadow.py`, `scripts/_recap_r2_10_readiness_candidate_scanner.py`) —
Shadow Mode reuses that exact pattern. A durable persistence layer for shadow results is explicitly
**out of scope** for the first canary (§ risks, execution plan).

## 4. Visual integration

**Owner correction (approval round): visual integration is observation-only.** Shadow Mode must
not extend `services/brand_renderer.py` and must not create a RECAP renderer of any kind, now or
as part of the first canary. Shadow's own visual output is limited to **metadata and checklist
fields** — plain data describing what exists and what a human should check, never a rendering, a
template, or a `RecapVisual` implementation. The `EditorialPresentation`/`RecapVisual` discussion
below exists only so shadow's *field names* stay compatible with that eventual contract — it is
not a plan to build it.

**The existing, approved visual system is `docs/ninja_pulse_visual_system_v2_1.md`** (primary
repo, "Approved Design Direction / Ready for Development," 2026-08-19). Shadow Mode does **not**
invent a new visual approach — it is built to eventually feed exactly this contract:

```python
class EditorialPresentation:
    presentation_type: Literal["NEWS", "BREAKING", "DATA", "QUOTE", "RECAP"]
    render_mode: Literal["LEGACY", "RICH"]
    media_layout: Literal["NONE", "SINGLE", "ALBUM", "VIDEO", "COLLAGE", "SLIDESHOW"]
    caption_position: Literal["ABOVE", "BELOW", "BLOCK_ORDER"]
    primary_source_url: str | None
    recap_visual: RecapVisual | None   # RECAP's own typed slot - not yet implemented in code
```

`RECAP` is already one of the five defined presentation types; `recap_visual: RecapVisual | None`
is already the anticipated slot for EVENT_RECAP's own eventual rendering. **Confirmed by direct
inspection: neither `EditorialPresentation` nor `RecapVisual` exist as code anywhere in this repo
yet** — the visual doc is a specification, not a shipped renderer (`services/brand_renderer.py`
currently only branches on `NEWS`/`BREAKING`/`DATA`/`QUOTE`). Shadow Mode's own job is therefore
**never to render the final branded RECAP post** — that belongs to a future Brand Renderer
extension, out of scope here — but to produce the underlying *data* (evidence, facts, timeline,
takeaways) in a shape that will slot cleanly into `RecapVisual` once it exists, and to flag
anything about that data a human reviewer should know before design work on `RecapVisual` begins.

Constraints already established by the approved spec, carried into every shadow output and into
`render_event_recap_telegram_preview()`'s own future revision (R2.10 Night 2 prototype,
`services/event_recap.py`) rather than re-derived:

- **Telegram-first** — every output must remain plausible as a Telegram message (length, no
  markdown Telegram doesn't support, plain text discipline already established by the existing
  prototype and by `bot/telegraph_shortlist_formatting.py`'s own `SAFE_LIMIT`/fail-loud convention).
- **No text over images** — media and text are separate blocks; caption position is `ABOVE` /
  `BELOW` / `BLOCK_ORDER`, never composited text-on-image.
- **Source button preserved, subscription CTA removed** — the source button is an
  **editorial-chat-only tool** (`[ Источник ↗ ]`, or `[ Смотреть презентацию ↗ ]` for RECAP when
  the primary source is a full event broadcast), used by the editor to verify facts before
  forwarding; it is expected to disappear on forward (not a bug); the `NINJA PULSE. Подписаться 🥷`
  CTA button is fully removed system-wide and must never be added to shadow output either.
- **Single primary source only** — `primary_source_url`, chosen by priority (official primary
  source → original announcement → highest-quality reporting source) — never a row of multiple
  source buttons. Shadow's own `evidence_reference_count`/`source_refs` remain the FULL evidence
  list for editorial diagnostic purposes, but any eventual rendered output picks exactly one.
- **Mobile + desktop, light + dark** — the approved spec's own explicit acceptance criteria
  (desktop real message width, wallpaper visible around messages, mobile checked separately,
  dark/light compatibility) apply to whatever eventually renders `RecapVisual` — Shadow Mode
  cannot verify actual Telegram client rendering itself (no Telegram send occurs), so this becomes
  a **documented reviewer checklist item** (§5), not something shadow code can assert about.

## 5. Visual QA objective

Shadow's own deterministic/text-level checks (code, testable):

**Text**
- Title length bounded (mirrors `render_event_recap_telegram_preview()`'s own
  `EventRecapTelegramPreviewTooLongError`/`_TELEGRAM_SAFE_LIMIT=4096` discipline).
- Structure present: title, lead/summary, key developments, takeaways — reuses the existing
  prototype's own section shape, `services/event_recap.py::render_event_recap_telegram_preview()`.
- No padding/filler — reuses the existing "never pad" discipline already enforced by
  `synthesize_event_recap()` (`key_takeaways[:_MAX_KEY_TAKEAWAYS]`, no forced minimum) and by
  `_detect_internal_vocabulary_leak()` (no internal-pipeline vocabulary leak).
- Readability is NOT independently re-scored by shadow — this duplicates
  `services/fact_safety.py`'s own already-established quality signals; shadow surfaces
  `fact_verification.status` and `quality_flags`, never invents a second scoring system.

**Media** (deterministic, code-checkable)
- `media_candidates` non-empty / empty — surfaced as a `quality_notes` entry either way, never
  silently absent.
- Existing relevance validation already reused unmodified
  (`services.image_persistence.get_editorial_image_candidates()`'s own
  `eligible_for_editorial`/`QualityStatus` machinery) — shadow does not re-validate relevance/
  quality, it surfaces what the existing pipeline already decided.
- Anchor-media preference gap (documented, R2.10 Night 2 Phase 19 finding, still unresolved) is
  called out explicitly per-candidate when `media_candidates` spans more than one member event.

**Telegram rendering** (human-checkable only — shadow makes NO Telegram calls, so nothing here can
be code-verified; this becomes an explicit reviewer checklist, mirroring the visual spec's own
acceptance-criteria list):
- [ ] mobile appearance
- [ ] desktop appearance (real message width, wallpaper visible)
- [ ] forwarded-message appearance (source button correctly absent — expected, not a defect)
- [ ] Telegram topics (if the editorial destination uses forum topics)
- [ ] button behavior in editorial chat vs. after forward

This checklist can only be exercised once a real `RecapVisual` render exists and a human pastes/
previews it in a real Telegram client — genuinely out of shadow's own automatable scope, and
explicitly not attempted here (no Telegram send permitted at all, per §2).

## 6. What Shadow Mode explicitly does NOT do

- Does not change `services/recap_event.py` (frozen R1) or any clustering/readiness threshold.
- Does not implement the R2.11 announcement-identity correction (still DESIGN ONLY, per that
  checkpoint's own conclusion).
- Does not build `EditorialPresentation`/`RecapVisual` rendering — that is a Brand Renderer
  extension, a separate, later piece of work.
- Does not add a new persistence layer, worker, or scheduler.
- Does not send anything to Telegram, ever, under this contract.
