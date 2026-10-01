"""Zero-model OFFLINE REPLAY of the controlled Sonnet 5.5 acceptance (3f213cb) after the fact-binding + judge-stability fix (founder task
2026-10-01). No provider / LLM / image call. Each semantic-judge round replays that round's SAVED verdict through the real role guard.

  1. round 1 - the recovered Director output through the real path (services.instagram_creative_director._validate_viral_carousel) with
     the saved first verdict: the one correction is required and now names the date / comparison misbindings next to the English words,
     and carries what the first judge read;
  2. round 2 - the saved corrected output (the correction that did NOT know about the misbindings) with the saved final verdict and the
     round-1 reading: still terminal, now for the misbindings (a real content reason); the final judge's caption finding - byte-identical
     text the first judge passed - is classified as a contradicting verdict (advisory), not as the reason the post stops.
Usage: python scripts/_instagram_fact_binding_replay.py [out dir]
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SAVED = json.loads((ROOT / "tests/fixtures/instagram_sonnet55_fact_binding/saved_run.json").read_text(encoding="utf-8"))


def director_input(*, note: str = "", invariants: dict | None = None, first: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary=SAVED["premise"], allowed_evidence=list(SAVED["director_facts"]),
        locale="ru", external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=("source",),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note=note, factual_invariants=dict(invariants or {}),
        first_judgement=dict(first or {}))


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
        return {"result": "PASS", "slides": len(outcome.carousel.slides), "editorial_advisories": list(outcome.editorial_advisories),
                "judge_rounds": judged, "diagnostics": diagnostics}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        return {"result": type(exc).__name__, "findings": list(getattr(exc, "findings", []) or []), "judge_rounds": judged,
                "first_judgement": getattr(exc, "first_judgement", None), "factual_invariants": getattr(exc, "factual_invariants", None),
                "diagnostics": diagnostics}
    finally:
        judge_mod.judge_viral_copy, cd._emit_diagnostic = real_judge, real_emit


async def main(out: Path | None) -> dict:
    first = await real_path(SAVED["initial_output"], director_input(), SAVED["initial_verdict"])
    second = await real_path(SAVED["corrected_output"],
                             director_input(note="EDITORIAL CORRECTION (replay)", invariants=first.get("factual_invariants"),
                                            first=first.get("first_judgement")), SAVED["correction_verdict"])
    judged = second["diagnostics"].get("semantic_judge_correction", {})
    report = {
        "run": SAVED["source"], "provider_calls": 0, "image_calls": 0,
        "round_1": {"result": first["result"], "findings": first["findings"], "carries_first_judgement": bool(first.get("first_judgement"))},
        "round_2": {"result": second["result"], "terminal_findings": second.get("findings"),
                    "contradicting_unchanged_text": judged.get("contradicting_unchanged_text"),
                    "semantic_findings_kept": judged.get("semantic_findings")},
    }
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "fact_binding_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts/instagram_feed_product/sonnet_editorial_acceptance_20260930/fact_binding_replay"
    print(json.dumps(asyncio.run(main(target)), ensure_ascii=False, indent=1))
