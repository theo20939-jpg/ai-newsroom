"""Zero-model OFFLINE REPLAY of the launch-substance fix (founder task 2026-09-30) on the SAVED final natural acceptance run (Claude Sonnet
5.5, HEAD 4046376). No provider / LLM / image call, no network, no database, no Telegram.

  1. the saved sources rebuilt into the evidence package BEFORE (page order) and AFTER (launch substance, the event's own ai_launch reading),
     each through the real evidence preflight with the event's own hook;
  2. an information-poor launch - the same saved article cut where its substance begins - is held (BLOCKING), never a lineup explainer;
  3. the saved shallow product-lineup carousel (after 79fa42c: 4 slides) through the real Director validation path against the NEW
     evidence: the lines it cites must still be supplied evidence.
Usage: python scripts/_instagram_launch_substance_replay.py <out dir>
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = json.loads((ROOT / "tests/fixtures/instagram_launch_substance/saved_packages.json").read_text(encoding="utf-8"))
RUN = json.loads((ROOT / "tests/fixtures/instagram_sonnet55_acceptance/saved_run.json").read_text(encoding="utf-8"))


def build(sources: list[dict], launch: bool | None):
    from services.instagram_evidence_package import NOT_AVAILABLE, EvidenceSource, SourceMedia, assemble_package

    saved = PACKAGES["sonnet_en"]
    return assemble_package(post_id="sonnet_en", fmt=saved["format"], premise=saved["premise"], launch=launch,
                            sources=[EvidenceSource(**s) for s in sources], media=SourceMedia(status=NOT_AVAILABLE, reason="replay"))


def report(pkg) -> dict:
    from services.instagram_evidence_package import launch_substance
    from services.instagram_viral_nomination import evidence_preflight

    saved = PACKAGES["sonnet_en"]
    lines = [item.exact_text for item in (*pkg.steps, *pkg.facts, *pkg.limitations)] + ([pkg.dateline] if pkg.dateline else [])
    pre = evidence_preflight(saved["event_verdict"]["hook"], lines, actuality=SimpleNamespace(type="CURRENT_EVENT"),
                             now=datetime.fromisoformat(saved["now"]), headlines=[saved["premise"]])
    lede = pkg.facts[0].text if pkg.facts else ""
    return {"quality": pkg.quality, "why": pkg.why, "preflight": pre.status, "preflight_checks": pre.checks,
            "facts": [{"text": f.text, "launch_substance": launch_substance(f.text, pkg.premise, lede)} for f in pkg.facts]}


async def shallow_carousel_against(new_evidence: list[str]) -> dict:
    import services.instagram_creative_director as cd
    from services.instagram_creative_director import CreativeDirectorInput

    old = RUN["director_input"]["allowed_evidence"]

    def as_text(ref):
        m = re.fullmatch(r"E(\d+)", str(ref or "").strip())
        return old[int(m.group(1)) - 1] if m else ref

    raw = copy.deepcopy(RUN["corrected_output"])
    raw["slides"] = raw["slides"][:4]  # the accepted 79fa42c result: the padded slide 5 dropped,
    raw["slides"][-1]["role"] = "takeaway"  # slide 4 carries the conclusion role
    for slide in raw["slides"]:
        slide["source_evidence"] = as_text(slide.get("source_evidence"))  # the exact line each slide cited in its own run
    raw["evidence_used"] = [as_text(ref) for ref in raw.get("evidence_used", [])]
    known = {f.name for f in dataclasses.fields(CreativeDirectorInput)}
    di = CreativeDirectorInput(**{**{k: v for k, v in RUN["director_input"].items() if k in known}, "allowed_evidence": new_evidence,
                                  "media_first": True, "generated_media_available": True, "planned_format": "TREND",
                                  "available_media_subjects": ("source",), "unsuitable_media_subjects": ("source",)})
    real_emit = cd._emit_diagnostic
    cd._emit_diagnostic = lambda *_a: None
    try:
        await cd._validate_viral_carousel(None, None, raw, None, director_input=di, archetype=raw.get("content_archetype"))
        return {"result": "ACCEPTED", "cited": [s["source_evidence"] for s in raw["slides"]]}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        return {"result": type(exc).__name__, "detail": str(exc)[:600],
                "cited_lines_still_supplied": {s["source_evidence"][:90]: s["source_evidence"] in new_evidence for s in raw["slides"]}}
    finally:
        cd._emit_diagnostic = real_emit


def main(out: Path) -> dict:
    sources = PACKAGES["sonnet_en"]["sources"]
    truncated = [dict(s, text=s["text"].split("Introducing Claude Sonnet 5.5")[0]) if s["source_type"] == "ORIGINAL_ARTICLE" else s
                 for s in sources]
    after = build(sources, True)
    evidence = after.director_evidence()
    evidence[-1] = RUN["director_input"]["allowed_evidence"][-1]  # the saved run's media line (the replay has no image discovery)
    result = {
        "run": PACKAGES["sonnet_en"]["source_file"], "provider_calls": 0, "image_calls": 0,
        "event_verdict": PACKAGES["sonnet_en"]["event_verdict"],
        "before": report(build(sources, False)),
        "after": report(after),
        "information_poor_launch": report(build(truncated, True)),
        "shallow_lineup_carousel_against_new_evidence": asyncio.run(shallow_carousel_against(evidence)),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "launch_substance_replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts/instagram_feed_product/final_natural_acceptance_20260929/launch_substance_replay"
    print(json.dumps(main(target), ensure_ascii=False, indent=1))
