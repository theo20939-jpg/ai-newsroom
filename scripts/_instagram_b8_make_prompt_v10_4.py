"""Autonomous Product Quality Loop, iteration 1: generate prompts/instagram_creative_director_carousel/v10.4.yaml from the (untouched)
v10.3 file. Wording only, no schema/field change:
  - copy length: the hook is 2 to 7 words (about 45 characters), later slides about 60 - the founder reference sets short lines at
    display size; long lines were the reason headlines rendered at caption size;
  - the same limit inside the hook contract;
  - media scale: on a source/generated slide the image is the dominant surface (bleeds off two edges, covers at least half the canvas),
    matching the reference; the renderer's media-scale adapter (services.instagram_media_scale_adapter) remains the guarantee.

Usage: python scripts/_instagram_b8_make_prompt_v10_4.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V103 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.3.yaml"
V104 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.4.yaml"

_SHORT_OLD = ("the hook (slide 1) is ONE strong line (up to about 70 characters) plus at most a tiny supporting phrase; later slides are one to two "
              "short lines.")
_SHORT_NEW = ("the hook (slide 1) is ONE strong line of 2 to 7 words (up to about 45 characters) plus at most a tiny supporting phrase; later slides "
              "are one short line (up to about 60 characters) set at display size - a line that needs three sentences belongs in the caption.")
_HOOK_OLD = "Keep it ONE strong line (up to about 70 characters) in the KAGE voice"
_HOOK_NEW = "Keep it ONE strong line of 2 to 7 words (up to about 45 characters, it is set at display size) in the KAGE voice"
_ASYM_PREFIX = "Design asymmetry deliberately:"
_ASYM_ADDITION = (
    " On a source or generated slide the image is the dominant surface, as in the reference: let it bleed off at least two canvas edges and "
    "cover at least half of the canvas (an immersive field, a full-width band above or below the headline, or a full-height side panel next to "
    "a short headline). A small framed picture floating on an empty surface reads as timid - keep framed fragments for collages."
)


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V103.read_text(encoding="utf-8")))
    doc["version"] = "10.4"
    rules = list(doc["rules"])
    replaced = 0
    for i, rule in enumerate(rules):
        if _SHORT_OLD in rule:
            rules[i], replaced = rule.replace(_SHORT_OLD, _SHORT_NEW, 1), replaced + 1
        elif _HOOK_OLD in rule:
            rules[i], replaced = rule.replace(_HOOK_OLD, _HOOK_NEW, 1), replaced + 1
        elif rule.startswith(_ASYM_PREFIX):
            rules[i], replaced = rule + _ASYM_ADDITION, replaced + 1
    assert replaced == 3, f"v10.3 copy-length/hook/asymmetry rules changed ({replaced} of 3 found)"
    doc["rules"] = rules
    return doc


def main() -> None:
    header = (
        "# Autonomous Product Quality Loop, iteration 1: v10.4 = v10.3 + (1) short display-size copy (hook 2-7 words / ~45 chars, later\n"
        "# slides ~60 chars), (2) the same limit in the hook contract, (3) media-first slides plan the image edge to edge (at least half the\n"
        "# canvas). No schema change. v10.3 stays published and untouched.\n"
    )
    V104.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V104)


if __name__ == "__main__":
    main()
