"""Zero-cost proof of the ONE Director correction pass (founder decision 2026-09-26) on the exact saved outputs - no provider call.

1. the saved failed GTA IV Director output through the CURRENT validation: a structured EditorialCorrectionRequired (every correctable
   finding, including the language-guard hit) instead of an immediate terminal CreativeLanguageError; the correction note it would send;
2. the accepted DeepSeek and Hamster carousels (polished copy) through the same validation: no correction request.
The Director input of the GTA run is rebuilt from the saved request itself (its E1..En evidence lines, the viral note, the media facts).
Usage: python scripts/_instagram_director_correction_replay.py <out dir>
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
GTA = ROOT / "artifacts/instagram_feed_product/viral_editorial_quality_20260926/live"
REQUIRED = {
    "clipped hook": "hook is a clipped fragment",
    "non-prose product list": "list of product names, not Russian prose",
    "slide redundancy": "make the same point",
    "generic filler / weak payoff": "generic filler",
    "unnecessary anglicism": "anglicism 'апгрейд'",
    "language guard (was terminal)": "CreativeLanguageError",
}


def gta_director_input():
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    call = json.loads((GTA / "post/calls/03_director.json").read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    evidence = [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]
    outcome = json.loads((GTA / "outcome.json").read_text(encoding="utf-8"))
    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary=outcome["title"], allowed_evidence=evidence, locale="ru",
        external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=(),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE)


def validate(raw: dict, director_input) -> dict:
    import services.instagram_creative_director as cd
    from services.instagram_viral_format import EditorialCorrectionRequired

    try:
        cd._validate_carousel_output(copy.deepcopy(raw), None, director_input=director_input, archetype="trend_generative")
        return {"result": "PASS"}
    except EditorialCorrectionRequired as exc:
        return {"result": "EditorialCorrectionRequired (correctable -> the ONE correction retry)", "findings": exc.findings,
                "correction_note": exc.correction_note}
    except Exception as exc:  # noqa: BLE001
        return {"result": f"{type(exc).__name__} (terminal): {str(exc)[:600]}"}


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    raw = json.loads((GTA / "post/calls/03_director.json").read_text(encoding="utf-8"))["response"]["structured_output"]
    gta = validate(raw, gta_director_input())
    joined = " ".join(gta.get("findings") or [])
    gta["required_detected"] = {name: marker in joined for name, marker in REQUIRED.items()}
    report = {"provider_calls": 0, "gta_saved_output": gta}

    import scripts._instagram_viral_copy_polish as polish

    for name, cfg in polish.STORIES.items():
        polished = json.loads((ROOT / "artifacts/instagram_feed_product/viral_copy_polish_20260926" / name / "polished_director_output.json")
                              .read_text(encoding="utf-8"))
        report[f"golden_{name}"] = validate(polished, polish._director_input(name, cfg))
    (out / "correction_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
