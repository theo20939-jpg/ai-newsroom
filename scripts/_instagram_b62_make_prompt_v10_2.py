"""Phase B.6.2: generate prompts/instagram_creative_director_carousel/v10.2.yaml from the (untouched) v10.1 file.

v10.2 = v10.1 (hook_emotion, media-first contract, generated media, evidence handles, Visual DNA v2) plus:
  - structured `flow_steps` for graphic_type="flow_diagram" (replaces reliance on free-form visual_direction parsing);
  - a grounding rule for every concrete object/entity in a generated scene (evidence-supported or an obvious non-factual metaphor);
  - `hook_mechanic`, a second bounded hook-planning field the hook copy must visibly instantiate.

Usage: python scripts/_instagram_b62_make_prompt_v10_2.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V101 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.1.yaml"
V102 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.2.yaml"

HOOK_MECHANICS = ["personal_stake", "contradiction", "unexpected_consequence", "relatable_pain", "specific_surprise", "absurdity", "sharp_comparison"]

_REGION_KINDS_PREFIX = "Every slide has a layout: a declarative composition in normalized canvas space"
_GENERATED_PREFIX = "GENERATED slide contract:"
_GRAPHIC_PREFIX = "GRAPHIC policy:"
_HOOK_PREFIX = "HOOK CONTRACT (slide 1)."

REGION_KINDS_RULE = (
    "Every slide has a layout: a declarative composition in normalized canvas space (x, y from the top-left). Region kinds: surface (a filled panel; surface is paper, soft, red, ink, "
    "graphite, accent, accent2, or media_ground = the uniform ground colour of a listed hero-ready subject), media (a real listed subject, or the reserved key `generated` on a generated "
    "slide; crop_mode cover, contain, cutout, cutout_contain, object_contain or object_cover; focus_x/focus_y; frame none, hairline, accent, paper, torn or die_cut; optional tilt_deg), text "
    "(content_ref is one of copy, copy_lead, copy_rest, number, copy_no_number - all derived from this slide's own slide_copy, you never write new text inside a layout; scale_token MEGA, "
    "NUMERAL, DISPLAY, HEADLINE_XL, HEADLINE_L, HEADLINE_M, HEADLINE_S, BODY or CAPTION; align; valign; max_lines; tone primary, accent, accent2 or muted; on_media), accent (rule_h, rule_v or "
    "block; tone) and graphic (ui_frame, flow_diagram, poll_cards, badge, scribble, arrow_scribble, circle_scribble, box_scribble, underline_scribble, highlight, burst; tone; a flow_diagram "
    "region ALSO sets flow_steps, 2 to 4 short node labels up to 22 characters each, e.g. ['ВВОД', 'ДЕЙСТВИЕ', 'РЕЗУЛЬТАТ'] - the renderer draws exactly these nodes, never visual_direction "
    "prose). z orders overlapping regions."
)

GENERATED_RULE = (
    "GENERATED slide contract: media_source 'generated', a `generation_brief` (a concrete description of what the picture SHOWS: the subject, the scene or visual metaphor, perspective and "
    "mood, in one or two sentences), a `story_anchor` and a layout with a media region whose content_ref is `generated` (crop_mode cover for immersive, object_contain on a media_ground stage "
    "for a hero object, or fragments for a collage). The story_anchor is the ONE concrete thing, action or relationship, taken from the supplied evidence or the slide's purpose, that makes "
    "this image belong to THIS story; if the picture could be reused unchanged for ten unrelated AI posts, replan it. GROUNDING: every concrete object or entity you place in the scene must be "
    "either (a) present in the supplied evidence, or (b) an obviously non-factual visual metaphor that implies no new story fact (a scale, a size contrast, a physical journey, a "
    "before/after) - when in doubt, use a story-supported object, action or relationship instead of inventing one. The slide's visual_direction (English, two or three sentences) must answer: "
    "what is physically visible; what the story-specific subject is; what relationship or action is shown; why this visual supports this slide. 'Futuristic AI visual', 'abstract technology "
    "scene' and 'dynamic AI composition' are not directions. Do NOT default to glowing cubes, floating spheres or random geometry, generic AI brains, anonymous robots, holograms, cyberpunk "
    "cities, abstract monoliths or neon circuitry just because the subject is AI - use them only when the supplied evidence is literally about that object; prefer a recognisable concrete "
    "object, place, gesture, comparison or before/after tied to the story, and for a NEWS_RECAP story depict that story's own subject. The image contains NO text, letters, logos, watermarks, "
    "fake UI or third-party branding and never depicts an unsupported product appearance or fact; the renderer adds the exact Russian copy and the canonical logo. Generated images are portrait "
    "(4:5 framing) and may carry a calm low-detail area; on_media text is still only placed in a calm zone and the renderer relocates it deterministically if needed. Non-generated slides set "
    "story_anchor to null."
)

GRAPHIC_RULE = (
    "GRAPHIC policy: media_source 'graphic' requires a substantive graphic region in the layout - ui_frame, poll_cards, or flow_diagram WITH flow_steps (2 to 4 short node labels; a "
    "flow_diagram region without flow_steps is not substantive) - that carries real information (an interface, a workflow, a comparison, a poll). A red rule, a scribble, an arrow or a giant "
    "numeral with text is NOT a graphic slide."
)

HOOK_RULE = (
    "HOOK CONTRACT (slide 1). The first slide is the hook and must deliberately create ONE clear reader reaction. State that reaction in hook_emotion (surprise, curiosity, humour, disbelief, "
    "tension, desire, relatable_frustration, usefulness or absurdity), and HOW you create it in hook_mechanic (personal_stake, contradiction, unexpected_consequence, relatable_pain, "
    "specific_surprise, absurdity or sharp_comparison) - set both to null on every other slide. The hook copy must visibly INSTANTIATE the chosen mechanic: a hook_mechanic of 'contradiction' "
    "needs a copy that actually states two things in tension, not a neutral description labelled as a contradiction; a 'sharp_comparison' needs the two compared things visible in the line "
    "itself. The reader should think 'wait, what?', 'that is useful', 'why?', 'seriously?' or 'I need the next slide', without you hiding essential truth. A merely descriptive sentence (a "
    "neutral statement of what happened or what the tip is) is NOT a hook: if you could have written it as a plain news headline or a how-to title, rewrite it. Prefer personal stake, a sharp "
    "contradiction, a specific surprise, an unexpected consequence, relatable pain or genuine absurdity over abstract editorial phrasing. Keep it ONE strong line (up to about 70 characters) in "
    "the KAGE voice, with the fact immediately identifiable. Set the hook slide's slide_purpose to ONE sentence saying why that emotion and mechanic fit the supplied fact and which evidence "
    "handle supports it. Archetype direction: ai_hack - relief, surprise, usefulness or relatable frustration around the pain the hack removes, not an instruction ('how to ...'); news_insight "
    "- turn the insight into tension or personal relevance for the reader; news_recap - synthesise the week's strongest emotional pattern into one sharp line with a real stake or contrast in "
    "it; trend_generative - one of the boldest formats: surprise, absurdity, internet-culture tension or an unexpected contrast. Hook strength never authorises exaggeration: never invent "
    "impact, certainty, market consequences, user behaviour, performance, future dominance, scarcity or urgency - the emotion is an interpretation of SUPPORTED facts only. Forms such as "
    "'Главные новости...', 'На этой неделе...', 'X становится...' or 'X - не всегда Y' are not globally forbidden, but reject them whenever a sharper, more personal or more contradictory "
    "framing is available from the same evidence - they read as a summary of the angle, not a reaction to it."
)


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V101.read_text(encoding="utf-8")))
    doc["version"] = "10.2"
    rules = list(doc["rules"])
    replaced = 0
    for i, rule in enumerate(rules):
        if rule.startswith(_REGION_KINDS_PREFIX):
            rules[i], replaced = REGION_KINDS_RULE, replaced + 1
        elif rule.startswith(_GENERATED_PREFIX):
            rules[i], replaced = GENERATED_RULE, replaced + 1
        elif rule.startswith(_GRAPHIC_PREFIX):
            rules[i], replaced = GRAPHIC_RULE, replaced + 1
        elif rule.startswith(_HOOK_PREFIX):
            rules[i], replaced = HOOK_RULE, replaced + 1
    assert replaced == 4, f"v10.1 region/generated/graphic/hook rules changed ({replaced} of 4 found)"
    doc["rules"] = rules

    slide = doc["output_schema"]["properties"]["slides"]["items"]
    props = slide["properties"]
    props["hook_mechanic"] = {"type": ["string", "null"], "enum": [*HOOK_MECHANICS, None]}
    slide["required"] = list(props)

    layout = props["layout"]
    layout_obj = layout if "properties" in layout else next(v for v in layout.get("anyOf", []) if "properties" in v)
    region = layout_obj["properties"]["regions"]["items"]
    region["properties"]["flow_steps"] = {
        "type": ["array", "null"], "items": {"type": "string", "maxLength": 22}, "minItems": 2, "maxItems": 4,
    }
    region["required"] = list(region["properties"])
    return doc


def main() -> None:
    header = (
        "# Phase B.6.2: v10.2 = v10.1 + structured flow_steps (graphic_type=flow_diagram no longer depends on parsing free-form visual_direction text), a\n"
        "# grounding rule for generated-scene objects/entities, and hook_mechanic (the hook must visibly instantiate its stated mechanic, not just declare hook_emotion). v10.1 stays\n"
        "# published and untouched.\n"
    )
    V102.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V102)


if __name__ == "__main__":
    main()
