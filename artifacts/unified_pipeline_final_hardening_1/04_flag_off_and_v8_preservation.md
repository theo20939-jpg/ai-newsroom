# Flag-Off Preservation & V8 Zero-Diff (§17)

## Flag-off / architectural boundaries — re-verified against this phase's own base (`9e73053...`)

```
$ git diff --stat 9e73053...HEAD -- \
    worker/content_cycle.py \
    services/story_memory.py services/story_identity_guard.py services/story_delta_engine.py \
    services/story_duplicate_guard.py database/models/story*.py \
    services/instagram_publish_adapter.py services/instagram_content_package.py \
    services/editorial_pipeline/platforms/instagram.py \
    core/config.py

(no output - zero-byte diff on every file, including worker/content_cycle.py itself)
```

`worker/content_cycle.py` is **completely untouched** by this hardening phase (§18's own explicit
instruction: "Do not put media classification logic in worker/content_cycle.py... the worker may
call the unified integration boundary only"). The full change set for this phase is exactly 2
modified files (`services/editorial_pipeline/recovery_service.py`,
`services/editorial_pipeline/telegram_integration.py`), 2 modified tests (updated for the new,
correct `AMBIGUOUS_TRANSPORT_RESULT` semantics), and 4 new files (the classifier module + 3 new
test files) — see `02_CHANGED_FILES.txt`-equivalent in the report's own §A for the exact list.

`core/config.py` is untouched — `unified_editorial_pipeline_enabled` remains `False` by default,
unmodified by this phase (it was already unmodified by the prior cutover phase too).

`LEGACY_FALLTHROUGH_FOUND = false`, `TEXT_ONLY_VISUAL_DEMOTION_FOUND = false`,
`TRANSPORT_EDITORIAL_AUTHORITY = false` — all re-proven true-as-safe by the fact that the code
paths establishing these properties (`worker/content_cycle.py`'s own `if/else` gate,
`services/telegram_routing.py`'s dumb transport functions) are byte-for-byte unchanged; nothing in
this phase could have regressed them since nothing in this phase touches them.

## Telegram V8

```
$ git diff --stat 9e73053...HEAD -- \
    services/brand_renderer.py services/nnj_master_news_overlay.py \
    services/news_telegram_presentation.py services/presentation_director.py \
    services/data_source_classification.py

(no output - zero-byte diff)
```

`TELEGRAM_V8_CHANGED = false`. This phase's only new code
(`services/editorial_pipeline/subject_match.py`) contains no PIL/Pillow import and calls no
renderer function at all — it only ever produces a `SubjectMatchValidation` verdict that feeds the
EXISTING, unmodified `services/media_candidate_scoring.py` ranking policy.

## Instagram

```
$ git diff --stat 9e73053...HEAD -- services/instagram_publish_adapter.py \
    services/instagram_content_package.py services/editorial_pipeline/platforms/instagram.py

(no output - zero-byte diff)
```

`INSTAGRAM_PUBLICATION_ENABLED = false` (unchanged, `core/config.py` untouched).
