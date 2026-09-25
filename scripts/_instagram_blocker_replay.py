"""Offline replay (zero-cost) of the 2026-09-25 targeted canary's saved outputs against the three blocker fixes.

  - DeepSeek: the saved Phase A output under the v2 planned-format schema (NEWS origin + trend_rationale for a planned TREND);
  - weekly recap: the saved Phase A output's coverage plan and quotes against the EXACT recap evidence (the saved bundle's
    "[story_k] " labels removed, the story kept as structural metadata) - which quotes ground, which story each belongs to;
  - Kimi / Adobe: the saved Creative Director plans under the visual capability contract (image generation off) - every
    unsupported visual request, and the executable primitive its content maps to instead.
No provider call, no network, no DB. Usage: python scripts/_instagram_blocker_replay.py <canary run dir> <out.json>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.instagram_creative_director as cd  # noqa: E402
from schemas.instagram_creative import InstagramCarouselCreative, InstagramEditorialDecision  # noqa: E402
from services.instagram_media_first import MediaFirstContractError, assert_media_first  # noqa: E402

_LABEL = re.compile(r"^\[(story_\d+)\]\s*")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _phase_a(post_dir: Path) -> dict:
    f = sorted((post_dir / "calls").glob("*phase_a*"))
    return (_load(f[0]) or {}).get("response", {}).get("structured_output") or {} if f else {}


def _maps_to(slide: dict) -> str:
    """The executable primitive the slide's own content maps to (a suggestion for the audit, not a regeneration)."""
    text = " ".join(str(slide.get(k) or "") for k in ("slide_copy", "slide_body"))
    if re.search(r"→|->|\s>\s", text):
        return "flow_diagram (the menu path / sequence as 2-4 flow_steps)"
    if re.search(r"«[^»]+»\s*:|\"[^\"]+\"\s*:|\b\w+\s*:\s*[\w«\"]", text) or text.count(",") >= 2:
        return "poll_cards (the config keys / list items as 2-4 options)"
    if re.search(r"\bШаг\s*\d|\bstep\s*\d", text, re.I):
        return "text: a big step number with the exact UI label / command quoted"
    return "text or a listed source subject"


def _plan_audit(post_dir: Path) -> dict:
    raw = (_load(post_dir / "director_raw_output.json") or {}).get("structured_output") or {}
    director_input = _load(post_dir / "director_input.json") or {}
    available = set(director_input.get("available_media_subjects") or [])
    unsuitable = set(director_input.get("unsuitable_media_subjects") or [])
    unsupported = []
    fillable = available - unsuitable
    counts: dict[str, int] = {}
    for i, slide in enumerate(raw.get("slides", [])):
        regions = slide.get("layout", {}).get("regions", [])
        media = {r.get("content_ref") for r in regions if r.get("kind") == "media"}
        if any(r.get("kind") == "graphic" and r.get("graphic_type") == "ui_frame" for r in regions) and not media & fillable:
            unsupported.append({"slide": i, "role": slide.get("role"), "request": "empty ui_frame (no UI image inside)",
                                "copy": (slide.get("slide_copy") or "")[:80], "executable_instead": _maps_to(slide)})
        generic = next((r.get("graphic_type") for r in regions if r.get("graphic_type") in ("flow_diagram", "poll_cards")), None)
        if generic and not media:
            counts[generic] = counts.get(generic, 0) + 1
    try:
        assert_media_first(list(InstagramCarouselCreative.model_validate(raw).slides), available_subjects=available,
                           unsuitable_subjects=unsuitable, generated_media_available=False)
        verdict = "ACCEPTED"
    except MediaFirstContractError as exc:
        verdict = f"REJECTED before render: {exc}"
    return {"slides": len(raw.get("slides", [])), "generic_primitive_counts": counts, "unsupported_visual_requests": unsupported,
            "capability_contract": verdict}


def main() -> None:
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    deepseek = _phase_a(run / "2026-08-05_2_meme_trend")
    try:
        d = InstagramEditorialDecision.model_validate(deepseek, context={"planned_format": "TREND"})
        deepseek_v2 = f"PASS (origin {d.origin}, angle {d.angle_intent}, trend_rationale present)"
    except Exception as exc:  # noqa: BLE001
        deepseek_v2 = f"FAIL: {type(exc).__name__}"
    try:
        InstagramEditorialDecision.model_validate(deepseek)
        deepseek_v1 = "accepted"
    except Exception:  # noqa: BLE001
        deepseek_v1 = "rejected (v1 rule unchanged)"
    package = _load(run / "2026-08-05_2_meme_trend" / "evidence_package.json") or {}

    recap = _phase_a(run / "weekly_recap")
    bundle = _load(run / "weekly_recap" / "bundle.json") or {}
    exact: dict[str, str] = {}
    for line in bundle.get("evidence", []):
        m = _LABEL.match(line)
        exact[_LABEL.sub("", line, count=1)] = m.group(1) if m else None
    keys = [s["key"] for s in bundle.get("stories", [])]
    quotes = recap.get("evidence_used", [])
    grounded = [q for q in quotes if q in exact]
    ungrounded = [q for q in quotes if q not in exact]
    try:
        cd.assert_recap_coverage(InstagramEditorialDecision.model_validate(recap, context={"planned_format": "WEEKLY_RECAP"}), keys)
        coverage = f"{len(keys)}/{len(keys)}"
    except Exception as exc:  # noqa: BLE001
        coverage = f"FAIL: {exc}"
    report = {
        "deepseek": {"v2_schema": deepseek_v2, "v1_schema": deepseek_v1, "planned_format": "TREND", "evidence": package.get("quality"),
                     "routable_to_director": deepseek_v2.startswith("PASS") and package.get("quality") != "BLOCKING"},
        "weekly_recap": {"coverage_plan": coverage, "quotes": len(quotes), "quotes_grounded_on_exact_text": len(grounded),
                         "quotes_still_ungrounded": ungrounded, "story_of_each_grounded_quote": {q[:70]: exact[q] for q in grounded},
                         "director_reachable": coverage.endswith(f"/{len(keys)}") and not ungrounded},
        "kimi_saved_plan": _plan_audit(run / "2026-08-05_1_ai_hack"),
        "adobe_saved_plan": _plan_audit(run / "2026-08-06_1_ai_hack"),
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
