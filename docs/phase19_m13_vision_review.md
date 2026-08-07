# Phase 19 M13 — Final-Candidate Vision Review Foundation

## 1. Scope

The first capability in this codebase to actually construct an image-bearing LLM request.
Reuses the LLM Gateway's already-real, already-wired vision plumbing end to end — confirmed by
inspection (`docs/phase19_m0_audit.md` §5) before writing any of this: `RoutingCriteria.
requires_vision`, `GenerateRequest.modalities`, `ContentPart(type="artifact_ref", mime_type=...)`,
and `openai_adapter.py::_translate_content_part()`'s `input_image` translation are all real,
functioning code with zero changes needed. **No change to the gateway, routing, or provider-
adapter layer at all** — this milestone is entirely capability-level.

## 2. `MediaVisionReviewCapability` (`capabilities/media_vision_review_capability.py`)

Standard capability shape (`__init__(gateway, prompt_repository)` only, one `call_generate()`
call, no retry) — identical to `EditorialPlanningCapability`'s own. Registered in
`capabilities/registry.py` and `capabilities/capability_mapping.py` (→ `AICapability.QUALITY`,
reusing an existing enum value) like every other capability, but never referenced by any live
`WorkflowDefinition` step — the same `meme_concept`/`editorial_planning` precedent.

Output schema (`prompts/media_vision_review/v1.yaml`, strict-schema-compliant, verified by
`tests/test_openai_strict_schema_compliance.py`): `relevant_to_story`, `source_logo_present`,
`watermark_present`, `website_or_social_ui_present`, `advertisement_or_banner_present`,
`readable_quality` (`good`/`acceptable`/`poor`), `recommended_role` (`hero`/`supporting`/
`technical_detail`/`chart_or_diagram`/`reject`).

## 3. Structural "no automatic path" guarantee

Two new, additive, always-`None`-in-production fields on `BusinessContext`
(`schemas/capability.py`): `media_review_image_data_uri`, `media_review_story_summary`. Mirrors
the exact precedent `article_evidence_text` (Phase 19 M1/M2) already established — a narrow,
optional extension to the existing context schema, never read by any other capability.
`capabilities/executor.py::_build_context()` never populates either field — there is no shadow
hook for this milestone at all (`media_vision_review_mode="shadow"` is currently a documented
no-op, reserved for a future deterministic pre-check hook). `MediaVisionReviewCapability.execute()`
itself raises `ValidationCapabilityError` immediately if the image is missing, rather than
degrading silently — this makes "nothing calls this without a real image" a loud, structural
check, not merely a convention.

`tests/test_media_vision_review_isolation.py` mechanically enforces (ast-based, mirrors
`tests/test_source_intelligence_isolation.py`'s own technique) that neither
`capabilities/executor.py` nor `worker/content_cycle.py` imports this capability module, and that
no file outside the manual harness/its own tests/registration does either.

## 4. The manual harness (`scripts/phase19_m13_vision_review_manual.py`)

The **only** real caller of this capability's LLM-backed `execute()`. Mirrors
`scripts/phase19_m3_editorial_plan_comparison.py`'s exact structure: refuses to run unless
`media_vision_review_mode != "off"`, resolves one image candidate for a given `NewsEvent`, reads
its bytes via the existing `services.image_persistence.read_candidate_bytes()`, base64-encodes
into a `data:` URI (never a public URL — no new hosting mechanism), constructs a
`CapabilityContext` directly (bypassing `CapabilityExecutor` entirely, same as the M3 script),
calls the real capability, and persists the result via `services/media_vision_review_persistence.
py` into the new `media_vision_reviews` table (1:many, surrogate PK, FK to `image_candidates.id`;
migration `94fd27f7d129`, written but not applied live).

**This script has NOT been executed against a real provider as part of this implementation** —
making a real call requires its own, separate, explicit paid-call authorization.

## 5. Setting

```python
media_vision_review_mode: Literal["off", "shadow"] = "off"
```

No `"enforce"` value — reaching a real vision call always requires the manual harness,
independent of this setting's value. `"shadow"` is reserved for a possible future deterministic
pre-check hook (e.g. flagging which candidates are queued for review) that does not exist yet in
this milestone; defined now so a later milestone can add that hook without a settings migration.

## 6. Validation performed

- `tests/test_media_vision_review_capability.py` (4 tests, `FakeLLMGateway`): full execute()
  shape, confirms the request actually carries an `artifact_ref` `ContentPart` with
  `modalities=["image"]` (the core proof this milestone's plumbing works), missing-image raises
  without ever calling the gateway, floor-validation failure raises.
- `tests/test_media_vision_review_persistence.py` (1 test): fake-session persistence shape.
- `tests/test_media_vision_review_isolation.py` (3 tests): no automatic/scheduled path imports
  the capability.
- `tests/test_openai_strict_schema_compliance.py`: the new prompt passes strict-mode compliance.
- Disposable Postgres, migrated through `94fd27f7d129`, upgrade/downgrade/re-upgrade all clean.
- Real DB alembic revision unchanged (`31a8d7c95c87`).
- Ruff/Mypy clean.

## 7. What this milestone does NOT do

- Does not make a real provider/vision call — `scripts/phase19_m13_vision_review_manual.py` has
  not been executed.
- Does not enable `media_vision_review_mode` anywhere (defaults `"off"`).
- Does not change the LLM Gateway, routing engine, or any provider adapter.
- Does not wire vision review into any scheduled/automatic worker path.
- Does not apply any migration to the real database.
