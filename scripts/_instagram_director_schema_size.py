"""Director output-size analysis for the output-token cap (founder task 2026-09-26: derive the cap from the schema, not an arbitrary number).

For each active Director prompt (carousel 10.11, single 7, reel 8) it walks the output JSON schema and reports:
  - the schema-constrained worst case per slide / for the top level (every string at its maxLength, every array at its maxItems);
  - the fields the schema leaves UNBOUNDED (no maxLength / maxItems) - they make a pure schema bound infinite;
and measures the REAL size of every saved successful Director response (JSON characters, output and reasoning tokens).
Usage: python scripts/_instagram_director_schema_size.py <out json>
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = {"carousel": ("instagram_creative_director_carousel", "10.11"), "single": ("instagram_creative_director_single", "7"),
           "reel": ("instagram_creative_director_reel", "8")}
KEY_OVERHEAD = 8  # quotes, colon, comma and indentation around a key


def _worst(schema: dict, path: str, unbounded: list[str], defs: dict) -> int:
    if "$ref" in schema:
        return _worst(defs[schema["$ref"].split("/")[-1]], path, unbounded, defs)
    for combo in ("anyOf", "oneOf"):
        if combo in schema:
            return max(_worst(s, path, unbounded, defs) for s in schema[combo])
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "string":
        if "enum" in schema:
            return max(len(str(v)) for v in schema["enum"]) + 2
        if "maxLength" not in schema:
            unbounded.append(path)
            return 0
        return int(schema["maxLength"]) * 2 + 2  # a Cyrillic / escaped character can cost 2 JSON bytes in the worst case
    if kind == "array":
        items = schema.get("items", {})
        if "maxItems" not in schema:
            unbounded.append(path + "[]")
            return _worst(items, path + "[]", unbounded, defs) * int(schema.get("minItems", 1)) + 2
        return _worst(items, path + "[]", unbounded, defs) * int(schema["maxItems"]) + int(schema["maxItems"]) + 2
    if kind == "object":
        return sum(_worst(s, f"{path}.{k}", unbounded, defs) + len(k) + KEY_OVERHEAD for k, s in (schema.get("properties") or {}).items()) + 2
    return 12  # number / boolean / null


def main() -> None:
    report: dict = {}
    for name, (prompt, version) in PROMPTS.items():
        spec = yaml.safe_load((ROOT / "prompts" / prompt / f"v{version}.yaml").read_text(encoding="utf-8"))
        schema = spec["output_schema"]
        defs = schema.get("$defs") or schema.get("definitions") or {}
        unbounded: list[str] = []
        top = _worst(schema, "$", unbounded, defs)
        slide_schema = (schema.get("properties") or {}).get("slides", {}).get("items") if name == "carousel" else None
        per_slide_unbounded: list[str] = []
        per_slide = _worst(slide_schema, "slide", per_slide_unbounded, defs) if slide_schema else None
        report[name] = {"prompt": f"{prompt} v{version}", "schema_worst_case_json_chars_if_bounded": top,
                        "schema_per_slide_worst_case_json_chars": per_slide, "unbounded_fields": sorted(set(unbounded)),
                        "slides_max_items": (schema.get("properties") or {}).get("slides", {}).get("maxItems") if name == "carousel" else None}
    observed = []
    for path in glob.glob(str(ROOT / "artifacts/**/calls/*director*.json"), recursive=True):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        record, response = data.get("record") or {}, data.get("response") or {}
        output = response.get("structured_output")
        if record.get("finish_reason") != "stop" or not isinstance(output, dict):
            continue
        slides = len(output.get("slides") or []) or None
        chars = len(json.dumps(output, ensure_ascii=False))
        observed.append({"slides": slides, "json_chars": chars, "output_tokens": record.get("output_tokens"),
                         "reasoning_tokens": record.get("reasoning_tokens") or 0,
                         "chars_per_json_token": round(chars / max(1, (record.get("output_tokens") or 0) - (record.get("reasoning_tokens") or 0)), 2)})
    unique = {json.dumps(o, sort_keys=True): o for o in observed}
    observed = list(unique.values())
    carousels = [o for o in observed if o["slides"]]
    per_slide_tokens = max((o["output_tokens"] - o["reasoning_tokens"]) / o["slides"] for o in carousels)
    report["observed"] = {
        "distinct_successful_responses": len(observed), "carousels": len(carousels),
        "max_slides": max(o["slides"] for o in carousels), "max_output_tokens": max(o["output_tokens"] for o in observed),
        "max_reasoning_tokens": max(o["reasoning_tokens"] for o in observed),
        "max_json_tokens_per_slide": round(per_slide_tokens, 1),
        "min_chars_per_json_token": min(o["chars_per_json_token"] for o in carousels),
        "single_reel_max_output_tokens": max((o["output_tokens"] for o in observed if not o["slides"]), default=None),
    }
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
