# Flag-off flow (`unified_editorial_pipeline_enabled = False`, the shipped default)

Byte-identical to before this phase — the new `if (...): ... else:` gate at
`worker/content_cycle.py`'s router-mode branch always evaluates its condition to `False` when the
flag is off, so execution falls straight into the `else:` branch, which is the exact,
untouched-except-for-reindentation legacy decision tree.

```mermaid
flowchart TD
    A[run_content_cycle per event] --> B[run_content_generation_for_event]
    B --> C{editorial_delivery_mode == router?}
    C -- no --> Z1[legacy card/image-preview path, unchanged]
    C -- yes --> D{unified_editorial_pipeline_enabled\nAND is_unified_router_eligible?}
    D -- False, flag off --> E[legacy decision tree: decide_presentation,\nmedia candidate resolution, render_branded_media,\ncaption budget drop-image, _hold_for_visual_recovery,\nsend_photo/send_media_group/send_video/send_message]
    E --> F[record_delivery / cycle bookkeeping]
```

No new module in this phase (`services/editorial_pipeline/*`, `services/telegram_routing.py`'s
additive `ambiguous` field) is reachable from this path. Proven, not merely argued:
`tests/test_unified_pipeline_shadow_wiring.py::test_flag_off_never_reaches_the_unified_pipeline`
and the full `tests/test_router_media_integration.py` + `tests/test_visual_fallback_hold_repair_1.py`
+ `tests/test_content_worker_cycle.py` suites, re-run unmodified against this branch with
`NEW_FAILURES=0` (the 2 pre-existing failures in `test_router_media_integration.py` are proven
pre-existing via `git stash` against the unmodified base — see the main report §N).
