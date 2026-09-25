"""Offline replay (zero-cost) of the 2026-09-25 paid micro-canary against the final pre-render contract:
  - Adobe: the saved Phase A evidence_used under contiguous source-span grounding (was UngroundedEvidenceError), plus the material-change
    probes that must still fail;
  - weekly recap: both saved Creative Director plans (calls 04 / 05) under the executable-plan contract with the 60% share removed -
    executable or not, the design-repetition diagnostics, and any other hard failure. The media offered = the saved vision verdicts.
No provider call, no network, no DB. It judges executability only - never how the carousel looks (that needs a real render).
Usage: python scripts/_instagram_prerender_contract_replay.py <micro canary run dir> <out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.instagram_creative_director as cd  # noqa: E402
from schemas.instagram_creative import InstagramCarouselCreative  # noqa: E402
from services.instagram_automatic_trigger import _WEEKLY_RECAP  # noqa: E402
from services.instagram_media_first import MediaFirstContractError, assert_media_first, visual_repetition_report  # noqa: E402


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _grounds(quotes: list[str], allowed: list[str]) -> str:
    try:
        cd.assert_evidence_grounded(quotes, allowed)
        return "PASS"
    except cd.UngroundedEvidenceError as exc:
        return f"FAIL: {str(exc)[:200]}"


def main() -> None:
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    adobe = run / "2026-08-06_1_ai_hack"
    decision = _load(adobe / "calls/01_phase_a.json")["response"]["structured_output"]
    package = _load(adobe / "evidence_package.json")
    allowed = [package["premise"], *(i["text"] for k in ("steps", "facts", "limitations") for i in package[k])]
    quotes = decision["evidence_used"]
    span_only = [q for q in quotes if q not in allowed]
    quote = next(q for q in quotes if q.startswith("Drawing on more than 70"))
    probes = {
        "number changed (70 -> 80)": quote.replace("70", "80"),
        "qualifier removed (more than 70 -> 70)": quote.replace("more than 70", "70"),
        "qualifier cut off the front": quote.removeprefix("Drawing on more than "),
        "two non-contiguous spans joined": quote.split(" the Adobe plugin")[0] + " Adobe said in the release.",
    }
    adobe_report = {
        "saved_phase_a_grounding": _grounds(quotes, allowed),
        "quotes": len(quotes), "grounded_by_whole_item_equality": len(quotes) - len(span_only),
        "grounded_only_as_contiguous_source_span": span_only,
        "material_change_probes": {name: _grounds([q], allowed) for name, q in probes.items()},
    }

    recap = run / "weekly_recap"
    verdicts = _load(recap / "vision_verdicts.json")
    available = {v["subject_key"] for v in verdicts}
    unsuitable = {v["subject_key"] for v in verdicts if not v["suitable"]}
    bundle = _load(recap / "bundle.json")
    director_input = cd.CreativeDirectorInput(
        objective="saves", format="carousel", opportunity_summary="", allowed_evidence=list(bundle["evidence"]), locale="ru",
        external_news_entities_allowed=True, is_recap_bundle=True, recap_subjects=list(bundle["subjects"]), media_first=True,
        planned_format="WEEKLY_RECAP", planned_archetype=_WEEKLY_RECAP[1],
        recap_required_subjects=list(bundle["subjects"]), generated_media_available=False,
        available_media_subjects=tuple(sorted(available)), unsuitable_media_subjects=tuple(sorted(unsuitable)))
    attempts = {}
    for n, name in enumerate(("04_director.json", "05_director.json"), start=1):
        raw = _load(recap / "calls" / name)["response"]["structured_output"]
        slides = list(InstagramCarouselCreative.model_validate(raw).slides)
        try:
            assert_media_first(slides, available_subjects=available, unsuitable_subjects=unsuitable, generated_media_available=False)
            executable, other = "YES", "NONE"
        except MediaFirstContractError as exc:
            executable, other = "NO", str(exc)
        report = visual_repetition_report(slides)
        try:  # every post-Director check the paid run never reached (reconstructed input; the canary's request text was not saved)
            cd._validate_carousel_output(raw, None, director_input=director_input, archetype=director_input.planned_archetype)
            full = "PASS"
        except Exception as exc:  # noqa: BLE001
            full = f"{type(exc).__name__}: {str(exc)[:300]}"
        attempts[f"attempt_{n}"] = {
            "slides": len(slides), "EXECUTABLE": executable,
            "DESIGN_REPETITION_WARNING": "YES" if report["design_repetition_warning"] else "NO",
            "OTHER_HARD_FAILURE": other, "full_post_director_validation": full, "repetition": report,
            "story_coverage": sorted({str(s.media_subject) for s in slides if str(s.media_subject or "").startswith("story_")}),
        }
    result = {"adobe": adobe_report, "recap_media_offered": {"available": sorted(available), "unsuitable": sorted(unsuitable)},
              "recap": attempts, "note": "executability only - how the carousel looks needs a real render"}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
