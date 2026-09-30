"""Zero-model OFFLINE REPLAY of the final natural acceptance run (2026-09-29, HEAD 4046376, Claude Sonnet 5.5) - founder task 2026-09-30:
the ONE correction refilled a slide blocked for 'no new information' with another restatement, and the corrected carousel was accepted.
No provider / LLM / image call, no database write, no Telegram call. Judge v5 is NOT called: each round replays the SAVED verdict of that
round of the acceptance run through the real role guard (the correction round's verdict was CLEAN on 5 slides; the replay judges a subset).

  1. the saved INITIAL output through the real path (services.instagram_creative_director._validate_viral_carousel): the one correction is
     required, and its findings now name slide 5 as a restatement of earlier slides;
  2. the saved CORRECTED output through the real path in correction mode: the refilled slide 5 is dropped (no model call, no new copy),
     the remaining 4 slides pass every deterministic check, the factual gate and non-regression, and the replayed judge verdict.
Usage: python scripts/_instagram_correction_padding_replay.py <out dir>
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "artifacts/instagram_feed_product/final_natural_acceptance_20260929/attempt_2/post"
# the tracked copy of the saved run's Director input, both outputs, both SAVED judge verdicts and the correction's baseline invariants
SAVED = json.loads((ROOT / "tests/fixtures/instagram_sonnet55_acceptance/saved_run.json").read_text(encoding="utf-8"))


def director_input(*, note: str = "", invariants: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput

    saved = SAVED["director_input"]
    known = {f.name for f in dataclasses.fields(CreativeDirectorInput)}
    fields = {k: (tuple(v) if isinstance(v, list) and k in {"recap_subjects"} else v) for k, v in saved.items() if k in known}
    return CreativeDirectorInput(**{**fields, "media_first": True, "generated_media_available": True, "planned_format": "TREND",
                                    "available_media_subjects": ("source",), "unsuitable_media_subjects": ("source",),
                                    "contract_retry_note": note, "factual_invariants": dict(invariants or {})})


async def real_path(raw: dict, di, saved_verdict: dict) -> dict:
    import services.instagram_creative_director as cd
    import services.instagram_viral_editorial_judge as judge_mod

    judged: list[int] = []
    diagnostics: dict = {}

    async def saved(_gateway, _repo, *, slides, caption, allowed_evidence):  # the SAVED verdict of this round - no provider call
        judged.append(len(slides))
        return judge_mod.apply_role_guard(judge_mod.parse_verdict(saved_verdict, len(slides)), slides)

    real_judge, real_emit = judge_mod.judge_viral_copy, cd._emit_diagnostic
    judge_mod.judge_viral_copy = saved
    cd._emit_diagnostic = lambda name, payload: diagnostics.__setitem__(name, payload)
    try:
        outcome = await cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di,
                                                     archetype=raw.get("content_archetype"))
        slides = outcome.carousel.slides
        return {"result": "PASS", "final_slide_count": len(slides),
                "final_slides": [{"headline": s.slide_copy, "body": s.slide_body} for s in slides],
                "final_caption": outcome.carousel.final_caption, "judge_replayed_on_slides": judged,
                "padding_dropped": diagnostics.get("correction_padding_dropped")}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        return {"result": type(exc).__name__, "detail": str(exc)[:2500], "findings": list(getattr(exc, "findings", []) or []),
                "judge_replayed_on_slides": judged, "padding_dropped": diagnostics.get("correction_padding_dropped")}
    finally:
        judge_mod.judge_viral_copy, cd._emit_diagnostic = real_judge, real_emit  # never leak the stubs


async def main(out: Path) -> dict:
    first = await real_path(SAVED["initial_output"], director_input(), SAVED["initial_verdict"])
    second = await real_path(SAVED["corrected_output"],
                             director_input(note="EDITORIAL CORRECTION (replay)", invariants=SAVED["correction_baseline_invariants"]),
                             SAVED["correction_verdict"])
    report = {
        "run": SAVED["source"], "provider_calls": 0, "image_calls": 0,
        "initial_round": {"result": first["result"],
                          "padding_findings": [f for f in first.get("findings", []) if "restates earlier slides" in f],
                          "all_findings": first.get("findings", [])},
        "correction_round": second,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "correction_padding_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else RUN.parent / "correction_padding_replay"
    print(json.dumps(asyncio.run(main(target)), ensure_ascii=False, indent=1))
