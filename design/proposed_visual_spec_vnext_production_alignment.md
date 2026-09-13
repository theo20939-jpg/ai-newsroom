# vNEXT visual specs — production-alignment CANDIDATE set (not promoted)

Status: **CANDIDATE only.** Created via the canonical registry lifecycle
(`create_candidate_spec()`), never `promote_candidate()`. Dev control-plane DB only; production
untouched. Origin: `VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1`, after the Founder resolved the
remaining visual decisions (adaptive logo placement; DATA hero-metric; QUOTE composition;
BREAKING native text colour).

## The truthful candidate set

| scope | version | parameters | why |
|---|---|---|---|
| `telegram_news` | **v3 CANDIDATE** | `safe_margin_frac 0.019, scrim_treatment none, source_image_treatment preserve` | **no `logo_zone`** — `select_master_news_branding()` chooses one canonical NNJ mark among four bounded safe corners per photo (LOWER_RIGHT → LOWER_LEFT → UPPER_RIGHT → UPPER_LEFT). A constant `logo_zone` would be a falsification; `logo_zone` is an optional field and `_zone_check()` skips the comparison when it is absent, so omitting it is the truthful, schema-supported "adaptive safe placement" statement. RenderEvidence still reports the actual chosen zone. |
| `telegram_breaking` | **v3 CANDIDATE** | same as news v3 | same (adaptive); band/wordmark stay retired |
| `telegram_data` | **v3 CANDIDATE** | `font_size_max 200, font_size_min 88, max_line_count 2, safe_margin_frac 0.019` | **no `placement_zone` / `logo_zone` / `scrim_treatment`** — DATA is source-dependent: the generated **hero card** (metric `upper_left`, fixed `lower_right` mark, no scrim) and the source-preserving **MINIMAL** mode (adaptive bottom signature `lower_right`/`lower_left`, an occasional guaranteed-branding fallback `strong` scrim, may crop a non-16:9 source) genuinely differ on exactly those fields. Declaring hero-only values would lie about the infographic render. The kept fields are true for **both** modes (MINIMAL skips the font check, draws 0 label lines, respects the margin). The single-NNJ invariant (`logo_count > 1` → hard BLOCK, always on) and the SOURCE_PRESERVATION dimension still govern the infographic path. `EXISTING_INFOGRAPHIC` is **never** forced into hero mode. |
| `telegram_quote` | **v2 CANDIDATE** | `safe_margin_frac 0.019, logo_zone lower_right, scrim_treatment none, source_image_treatment preserve` | QUOTE places its one mark **deterministically** at `lower_right` (`_paste_svg_mark`, not adaptive) → `logo_zone: lower_right` is truthful. Parameters are byte-identical to v1; the QUOTE change is compositional (red quote-mark motif, author name red, author role grey, no baked `PULSE`/`NP`). |

Rejected (never deleted): `telegram_data` v2 and v4 — both carried the hero-only
`placement_zone: upper_left` + `logo_zone: lower_right` + `scrim_treatment: none` that lie about
the MINIMAL infographic render.

## Local replay verdict (`scripts/_visual_spec_vnext_replay.py`)

Evaluated with each candidate's params treated as ACTIVE (§17: real CANDIDATE rows never change
acceptance):

| render | actual mark zone | SPEC_MATCH | merged Art |
|---|---|---|---|
| NEWS clean | lower_right | **PASS** | pass_with_notes |
| NEWS busy-bottom (adaptive) | upper_right | **PASS** | pass_with_notes |
| BREAKING clean | lower_right | **PASS** | pass_with_notes |
| BREAKING busy-bottom (adaptive) | upper_right | **PASS** | pass_with_notes |
| DATA generated hero | lower_right | **PASS** | pass_with_notes |
| DATA existing infographic (MINIMAL) | lower_right | **PASS** | pass_with_notes |
| QUOTE full-role | lower_right | **PASS** | pass_with_notes |
| QUOTE missing-role fallback | lower_right | **PASS** | pass_with_notes |

No SPEC_MATCH FAIL, no hard failure, no Art BLOCK. **No soft REWORK remains** from evaluating an
adaptive render against a fixed zone. `VISUAL_SPEC_SCHEMA_GAP = false` — no schema change, no
migration.

Non-16:9 source note: a NEWS/BREAKING render of a non-16:9 photo produces a truthful
`source_image_treatment=crop` (a mechanical centre-crop-to-canvas, classified **soft**, never a
`recompose`). This is pre-existing, Founder-approved behaviour (`preserve` means "no AI
recompose/regeneration"), unchanged by this candidate set.

## How to apply (Founder, later — NOT this phase)

`scripts/propose_visual_spec_adaptive_candidates.py` (idempotent) materialises the candidates;
`scripts/activate_visual_spec_vnext.py` (idempotent, `--dry-run`, STOP guards, `--print-rollback`)
promotes them after a Founder confirm + a production DB backup. Target production lifecycle:

```
telegram_news v3     ACTIVE   (v2, v1 -> SUPERSEDED)
telegram_breaking v3 ACTIVE   (v2, v1 -> SUPERSEDED)
telegram_data v3     ACTIVE   (v1 -> SUPERSEDED)
telegram_quote v2    ACTIVE   (v1 -> SUPERSEDED)   [or no-op: v2 params == v1]
```
