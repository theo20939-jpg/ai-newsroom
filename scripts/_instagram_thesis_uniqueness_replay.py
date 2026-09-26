"""Zero-cost acceptance of the THESIS-LEVEL SLIDE UNIQUENESS + CAPTION rule (founder task 2026-09-26) - no provider call.

On the EXACT final corrected GTA IV output of the Director-stability live run (director_stability_20260926/live/post/calls/04_director.json;
its Director input rebuilt from the saved request's own E1..En lines) and on the accepted golden carousels:
  1. slides 2/3 are detected as subsumption;          2. the explanation says slide 3 adds specificity, not a new beat;
  3. the caption's name list repeating the slides;     4. the teaser label 'Вот что приехало в игру';
  5. DeepSeek passes;  6. Hamster passes;
  7. two genuinely different facts from ONE evidence item pass;  8. different evidence ids with the same thesis fail;
  9. the rule's code carries no story-specific term (docstrings / comments excluded - the examples there are documentation);
 10. only ONE editorial correction is possible (the existing call-graph tests, run here).
Usage: python scripts/_instagram_thesis_uniqueness_replay.py <out dir>
"""
from __future__ import annotations

import ast
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "artifacts/instagram_feed_product/director_stability_20260926/live/post/calls/04_director.json"
STORY_TERMS = ("dlss", "fsr", "hdr", "dlaa", "gta", "rockstar", "nexus", "chunklechuck", "fusion", "nvidia", "amd")
RULE_FILES = ("services/instagram_viral_format.py", "services/instagram_editorial_critic.py")
ONE_CORRECTION_TESTS = (
    "tests/test_instagram_director_correction.py::test_a_correctable_failure_gets_exactly_one_structured_retry_and_a_second_failure_is_terminal",
    "tests/test_instagram_director_stability.py::test_the_director_is_never_called_more_than_three_times",
    "tests/test_instagram_director_stability.py::test_malformed_then_valid_but_bad_may_still_use_the_editorial_correction",
)


def final_gta() -> tuple[dict, object]:
    from scripts._instagram_director_correction_replay import gta_director_input

    call = json.loads(FINAL.read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    evidence = [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]
    from dataclasses import replace

    return call["response"]["structured_output"], replace(gta_director_input(), allowed_evidence=evidence)


def _slide(ref: str, head: str, body: str) -> dict:
    return {"role": "beat", "slide_copy": head, "slide_body": body, "source_evidence": ref}


# neutral, non-GTA fixtures (a robot vacuum story): the rule must work on meaning, not on evidence ids
FIXTURE_EVIDENCE = ["Робот-пылесос уехал из квартиры в Сеуле и проехал 3 км до парка. Его нашёл сосед и вернул владельцу.",
                    "Пылесос самостоятельно покинул квартиру владельца."]
SAME_ITEM_DIFFERENT_FACTS = [
    _slide("E1", "Робот-пылесос сбежал из квартиры в Сеуле", "Он проехал 3 километра до ближайшего парка."),
    _slide("E1", "Нашёл его сосед", "Пылесос вернул владельцу сосед, который заметил его в парке."),
]
DIFFERENT_IDS_SAME_THESIS = [
    _slide("E1", "Пылесос сбежал из дома", "Робот-пылесос сам уехал из квартиры владельца."),
    _slide("E2", "Побег из квартиры", "Пылесос самостоятельно покинул квартиру владельца."),
]


def rule_code_terms() -> dict:
    """Story-specific terms in the rule CODE: identifiers and string constants, with module / function docstrings removed."""
    hits: dict = {}
    for rel in RULE_FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body
                      and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                words = set(re.findall(r"[a-z]+", node.value.lower()))
                found |= words & set(STORY_TERMS)
            elif isinstance(node, ast.Name):
                found |= set(re.findall(r"[a-z]+", node.id.lower())) & set(STORY_TERMS)
        hits[rel] = sorted(found)
    return hits


def main() -> None:
    import scripts._instagram_viral_copy_polish as polish
    from scripts._instagram_director_correction_replay import validate
    from services.instagram_viral_format import viral_copy_findings

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    raw, director_input = final_gta()
    gta = validate(raw, director_input)
    findings = gta.get("findings") or []
    subsumption = next((f for f in findings if f.startswith("slides 2 and 3:")), "")
    caption = next((f for f in findings if f.startswith("caption sentence is a list of names")), "")
    teaser = next((f for f in findings if "label_headline" in f), "")
    golden = {name: validate(json.loads((ROOT / "artifacts/instagram_feed_product/viral_copy_polish_20260926" / name
                                         / "polished_director_output.json").read_text(encoding="utf-8")), polish._director_input(name, cfg))
              for name, cfg in polish.STORIES.items()}
    fixture_7 = viral_copy_findings(copy.deepcopy(SAME_ITEM_DIFFERENT_FACTS), FIXTURE_EVIDENCE)
    fixture_8 = viral_copy_findings(copy.deepcopy(DIFFERENT_IDS_SAME_THESIS), FIXTURE_EVIDENCE)
    terms = rule_code_terms()
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *ONE_CORRECTION_TESTS],
                           cwd=ROOT, capture_output=True, text=True)
    summary = (tests.stdout.strip().splitlines() or [""])[-1]
    checks = {
        "1_slides_2_3_subsumption_detected": "only specifies the first slide's claim" in subsumption,
        "2_explanation_says_specificity_not_new_beat": "adds specificity, not a new beat" in subsumption,
        "3_caption_list_repetition_detected": caption.endswith("it repeats the slides' list"),
        "4_teaser_label_surfaced": "Вот что приехало в игру" in teaser,
        "5_deepseek_passes": golden["deepseek"]["result"] == "PASS",
        "6_hamster_passes": golden["hamster"]["result"] == "PASS",
        "7_same_evidence_item_different_facts_pass": fixture_7 == [],
        "8_different_evidence_ids_same_thesis_fail": any(f.startswith("slides 1 and 2:") for f in fixture_8),
        "9_no_story_specific_terms_in_rule_code": not any(terms.values()),
        "10_only_one_editorial_correction": tests.returncode == 0,
    }
    report = {
        "provider_calls": 0, "images_regenerated": 0, "fixture": str(FINAL.relative_to(ROOT)).replace("\\", "/"),
        "checks": checks, "all_pass": all(checks.values()),
        "gta_final_output": {"result": gta["result"], "findings": findings, "correction_note": gta.get("correction_note")},
        "golden": golden, "fixture_7_findings": fixture_7, "fixture_8_findings": fixture_8,
        "rule_code_story_terms": terms, "one_correction_tests": {"nodes": list(ONE_CORRECTION_TESTS), "result": summary},
    }
    (out / "thesis_uniqueness_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"checks": checks, "all_pass": report["all_pass"], "gta_findings": findings, "fixture_8": fixture_8,
                      "one_correction_tests": summary}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
