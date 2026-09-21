"""Phase B.5.1: generate prompts/instagram_creative_director_carousel/v9.yaml from the (untouched) v8 file. v9 inherits v8's system text and every
factual / evidence-safety rule verbatim, and replaces the stale visual rules (light-only surfaces, 'no dark', 'nothing over an image', no families).

Usage: python scripts/_instagram_b51_make_prompt_v9.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V8 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v8.yaml"
V9 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v9.yaml"

FAMILIES = ["immersive_image_field", "hero_object_stage", "internet_culture_collage", "dark_type_number_statement", "interface_cards", "light_utility_editorial"]
ROLES = ["hook", "context", "step", "evidence", "comparison", "story", "result", "takeaway", "cta", "closing"]

# v8 rules that are replaced (matched by prefix) - everything else is inherited verbatim
_DROP_PREFIXES = (
    "Produce at least 2 slides, in narrative order",
    "Build narrative progression",
    "A VISUAL DNA block is part of your input",
    "Every slide has a layout:",
    "You never choose fonts, hex colours",
    "Design asymmetry deliberately",
    "Plan for the CONTENT ARCHETYPE given in the input",
    "Surfaces are light editorial paper",
    "Images are only cropped and placed into their own region",
    "generated_media is not available",
    "Avoid recent visual repetition",
    "MEDIA AVAILABLE FOR THIS POST lists",
)

NEW_RULES = [
    "Produce at least 2 slides in narrative order. Every slide's role is exactly one of: " + ", ".join(ROLES) + ". The first slide is `hook`. The LAST slide must be a conclusion: `result`, `takeaway`, `cta` or `closing` - never hook, context, step, evidence, comparison or story. Use `story` for one NEWS_RECAP story per slide and `closing` for a recap's last slide; use `result` when a how-to ends by showing its outcome; use `takeaway` (or `cta`) to end an editorial carousel. There is no `caption` role.",
    "Build narrative progression, not one paragraph cut into pieces. Every slide needs a distinct slide_purpose and must advance the idea.",
    "A VISUAL DNA v2 block is part of your input: global invariants and a library of six visual FAMILIES read sample by sample from the founder reference (" + ", ".join(FAMILIES) + "). Learn their MECHANICS: surface behaviour, typography, media behaviour, density, accent system. Never copy the reference's wording, imagery, subjects, memes, a composition or a fixed slide sequence.",
    "Every slide sets `visual_family` to exactly one of those six ids and `visual_family_reason` (one short English sentence naming the content, purpose or media fit). Choose from the content, the slide's purpose, the media listed, the evidence type, the archetype, the slide's place in the story and the fatigue note. The family mix is guidance, never a quota: do not rotate families mechanically, do not default to one family, and do NOT fall back to light_utility_editorial when unsure. A carousel should feel coherent: the same family on several slides is fine when deliberate, and compatible families may be mixed. A family that needs media (immersive_image_field, hero_object_stage, internet_culture_collage) is allowed only when MEDIA AVAILABLE lists a subject that supports it; otherwise choose another family. Never assume, invent or fake media.",
    "FAMILY MECHANICS - immersive_image_field: arrangement standard, background ink; ONE media region covering the whole canvas (x=0, y=0, w=1, h=1, crop_mode cover, focus_x and focus_y exactly as in the listed crop option); headline text regions with on_media=true placed INSIDE the listed calm text zone box for that crop (use the listed x, y, w, h; split it into a larger lead region and a smaller supporting region when the copy has two parts; use copy_lead and copy_rest); large scale tokens (HEADLINE_XL, DISPLAY or MEGA for short copy); optionally a short accent rule_h just above the text. Nothing else sits over the image. Use it only for a subject whose MEDIA AVAILABLE entry lists a calm text zone.",
    "FAMILY MECHANICS - hero_object_stage: arrangement stage; first a surface region x=0, y=0, w=1, h=1 with surface media_ground and content_ref = the subject (only when the subject is listed as hero-ready, i.e. an isolated object on a uniform ground), then ONE media region with crop_mode object_contain (whole object, region may be larger than the canvas so the object crosses the frame) or object_cover (object cropped at the region edge, for a panel). A media region on a stage may extend past the canvas by at most 0.4 (negative x or y, or x+w or y+h above 1); make the object clearly larger than the type. Text regions must not overlap the media region unless on_media=true and completely inside it; set short copy in a corner or column, a giant NUMERAL, or a small caption. Use a graphite or ink panel (a surface region) beside or above the photo panel for mixed grounds. Dark objects use background ink; light product shots use background paper.",
    "FAMILY MECHANICS - internet_culture_collage: arrangement collage; 3 to 6 media regions (crops of one subject at different focus and scale are allowed) with UNEQUAL areas (the largest at least 1.5x the second and 2.5x the smallest); every media region has a distinct z (1 to 6) and a small tilt_deg between -12 and 12 (null or 0 for the anchor); vary frame per fragment (none, torn, paper, die_cut - die_cut only for a real transparent cut-out); fragments may overlap (each may hide at most half of a smaller one) and may run off an edge by at most 0.1. Add one to three graphic marks that serve the reading order (arrow_scribble, circle_scribble, box_scribble, underline_scribble, a highlight behind a headline, at most one burst) with tone accent or accent2; use palette culture on dark and brand on light. Type sits in clear space - never over a fragment - with a large punchline anchor. Do NOT reuse the same device set, the same skeleton (big image on top, fragments in the middle, headline low) or the same reaction image in every collage: reaction/punchline, poll or choice UI, screenshot chaos, editorial evidence and mixed social pieces are different behaviours.",
    "FAMILY MECHANICS - dark_type_number_statement: usually no media; background ink or graphite; a giant number (content_ref number, scale_token NUMERAL, tone accent) and/or a very short headline at DISPLAY, MEGA or HEADLINE_XL in a narrow column; small supporting text; one accent stroke at most. FAMILY MECHANICS - interface_cards: background ink or graphite; a graphic poll_cards region (then slide_copy must have the shape 'Question? Option A | Option B | Option C' with two to four options separated by |, and the layout also needs a text region with copy_lead) or ui_frame or flow_diagram (flow_diagram needs a visual_direction whose steps are joined by an arrow); a large heading; a photo only as a small supporting fragment. FAMILY MECHANICS - light_utility_editorial: background paper or soft; a heavy headline with short supporting text or a step, one accent (numeral or rule); calm and explanatory; never the default answer for a whole carousel.",
    "Every slide has a layout: a declarative composition in normalized canvas space (x, y from the top-left). Region kinds: surface (a filled panel; surface is paper, soft, red, ink, graphite, accent, accent2, or media_ground = the uniform ground colour of a listed hero-ready subject), media (a real listed subject; crop_mode cover, contain, cutout, cutout_contain, object_contain or object_cover; focus_x/focus_y; frame none, hairline, accent, paper, torn or die_cut; optional tilt_deg), text (content_ref is one of copy, copy_lead, copy_rest, number, copy_no_number - all derived from this slide's own slide_copy, you never write new text inside a layout; scale_token MEGA, NUMERAL, DISPLAY, HEADLINE_XL, HEADLINE_L, HEADLINE_M, HEADLINE_S, BODY or CAPTION; align; valign; max_lines; tone primary, accent, accent2 or muted; on_media), accent (rule_h, rule_v or block; tone) and graphic (ui_frame, flow_diagram, poll_cards, badge, scribble, arrow_scribble, circle_scribble, box_scribble, underline_scribble, highlight, burst; tone). z orders overlapping regions.",
    "Hard layout limits, checked by a validator that rejects an unsafe slide layout: every text region is at least 0.16 wide and 0.045 tall, inside x 0.04 to 0.96 and y 0.03 to 0.97; text regions never overlap each other; a text region never overlaps a media region unless it has on_media=true and lies completely inside that media region; keep the logo corner clear (bottom-right x 0.83 to 0.94, y 0.82 to 0.93 by default; set logo_position BOTTOM_LEFT to use the bottom-left corner x 0.05 to 0.17 instead); a media region is at least 0.08 x 0.08 and only a listed subject key may be used; the layout must present the slide's whole copy (one copy region, or copy_lead plus copy_rest, or number plus copy_no_number, or poll_cards plus copy_lead); a rule_h is at least 0.05 wide and at most 0.05 tall, a rule_v the reverse; a graphic is at least 0.15 x 0.10 except badge, scribbles, highlight and burst which may be 0.05 wide or tall.",
    "Bounded controls you may set per slide: background (paper, soft, ink, graphite), palette (brand = NINJA red only; culture = social/meme collage accents; neo = futuristic imagery accents), logo_position (BOTTOM_RIGHT or BOTTOM_LEFT), arrangement (standard, stage, collage), density (LOW, MEDIUM, HIGH), media_dominance (NONE, SUPPORTING, BALANCED, DOMINANT), visual_weight (TEXT, MEDIA, MIXED, GRAPHIC). You never choose fonts, hex colours, pixel sizes, logo coordinates, code, CSS or SVG: the renderer owns every brand token, the canonical logo, the safe zones and all collision and clipping handling.",
    "Surfaces and images: solid dark surfaces (background ink or graphite) are allowed and often exactly right for this brand; light surfaces (paper, soft) are one option, never the safe default. Images are only cropped, scaled and positioned (collage fragments may also be tilted within 12 degrees); NO overlay, scrim, dimming, tint, blur, gradient readability field or translucent wash of any colour is ever used on an image. Readability comes from the surface you choose, from placement, or from a listed calm zone with on_media text.",
    "Design asymmetry deliberately: an object can bleed off an edge, a headline can be huge next to a small image or small next to a huge image, negative space is allowed when intentional. Do not reduce every slide to the same image-on-top, text-below split, do not repeat one layout across the carousel unless the repetition is deliberate, and do not shrink short headlines: two to four words deserve a very large scale token.",
    "MEDIA AVAILABLE FOR THIS POST lists the real subject keys, what each may be used for and, for each real image, which families it can honestly support (with the calm text zones per crop). Use a media region only with a listed key. The same key may appear on several slides, or several times on one slide with different crops, when it is genuinely the same subject; never use a listed image for a different factual subject. Set media_subject to the key the slide's main media uses (or null) and media_function to what the media is for (hero, detail, evidence_photo, ui_screenshot, result, before_after, concept, none). When a slide needs a screenshot, a result, a before/after or a concept visual and none is listed, plan a graphic layout instead of forcing a photo. Not every slide needs an image. If the requested family cannot be supported by the media, choose another family.",
    "Plan for the CONTENT ARCHETYPE given in the input and echo it exactly as content_archetype. ai_hack: instructional progression - a numbered step (start a step slide with 'Шаг N.' and give it a big number), interface_cards or a listed screenshot for interface moments, dark_type_number_statement for a punchy number, a clear result or takeaway; do not force photography into a tutorial. news_insight: story-led - the real source image staged in different ways at deliberately different scales (immersive, hero or collage crops only where the media supports them), plus a number, a comparison or a typographic statement; never the same image cropped five similar ways. news_recap: a short opening, one `story` slide per story that uses that story's own key as media_subject with must_match_story=true and the family its own media supports, and a short `closing` slide; never give one story's image to another story. trend_generative: social-native and media-first - internet_culture_collage, immersive or hero when the media supports it, minimal copy and a strong visual idea; when no real image is listed, short dark typographic statements.",
    "Audience-facing fields (slide_copy, final_cta, final_caption) are finished Russian copy for readers. They must NEVER mention or paraphrase implementation or design instructions: the visual reference, the visual DNA, families, layouts, renderers, archetypes, roles, captions, placeholders, quiet zones, overlays, or what NOT to do (for example never 'не подпись и не кадры референса'). Put design reasoning only in visual_direction and visual_family_reason, never in slide_copy.",
    "generated_media is not available: set media_strategy to source_media when any real image is listed, otherwise typographic.",
    "Avoid recent visual repetition (see the CREATIVE FATIGUE NOTE, which counts POSTS, not slides) when another content-fit treatment is stronger; fatigue is advisory, content fit always wins, and you must never rotate families or layouts mechanically.",
]


def build() -> dict:
    v8 = yaml.safe_load(V8.read_text(encoding="utf-8"))
    doc = copy.deepcopy(v8)
    doc["version"] = "9"
    doc["rules"] = [r for r in v8["rules"] if not r.startswith(_DROP_PREFIXES)] + NEW_RULES
    doc["system"] = v8["system"].rstrip() + (
        " You plan every slide in one of six accepted visual families learned from a founder reference (a Visual DNA block is part of your input), "
        "against the REAL media that exists, and you never fake media."
    ) + "\n\n  "

    schema = doc["output_schema"]
    schema["properties"]["content_archetype"] = {"type": "string", "enum": ["ai_hack", "news_insight", "news_recap", "trend_generative"]}
    slide = schema["properties"]["slides"]["items"]
    slide["properties"]["role"] = {"type": "string", "enum": ROLES}
    slide["properties"]["visual_family"] = {"type": "string", "enum": FAMILIES}
    slide["properties"]["visual_family_reason"] = {"type": ["string", "null"], "maxLength": 240}
    slide["required"] = list(slide["properties"])

    layout = slide["properties"]["layout"]
    lp = layout["properties"]
    lp["background"] = {"type": "string", "enum": ["paper", "soft", "ink", "graphite"]}
    lp["palette"] = {"type": "string", "enum": ["brand", "culture", "neo"]}
    lp["logo_position"] = {"type": "string", "enum": ["BOTTOM_RIGHT", "BOTTOM_LEFT"]}
    lp["arrangement"] = {"type": "string", "enum": ["standard", "collage", "stage"]}
    lp["regions"]["maxItems"] = 14
    rp = lp["regions"]["items"]["properties"]
    rp["x"] = {"type": "number", "minimum": -0.5, "maximum": 1.5}
    rp["y"] = {"type": "number", "minimum": -0.5, "maximum": 1.5}
    rp["w"] = {"type": "number", "minimum": 0.0, "maximum": 1.6}
    rp["h"] = {"type": "number", "minimum": 0.0, "maximum": 1.6}
    rp["scale_token"] = {"type": ["string", "null"], "enum": ["MEGA", "NUMERAL", "DISPLAY", "HEADLINE_XL", "HEADLINE_L", "HEADLINE_M", "HEADLINE_S", "BODY", "CAPTION", None]}
    rp["surface"] = {"type": ["string", "null"], "enum": ["paper", "soft", "red", "ink", "graphite", "accent", "accent2", "media_ground", None]}
    rp["crop_mode"] = {"type": ["string", "null"], "enum": ["cover", "contain", "cutout", "cutout_contain", "object_contain", "object_cover", None]}
    rp["frame"] = {"type": ["string", "null"], "enum": ["none", "hairline", "accent", "paper", "torn", "die_cut", None]}
    rp["graphic_type"] = {"type": ["string", "null"], "enum": ["ui_frame", "flow_diagram", "poll_cards", "badge", "scribble", "arrow_scribble", "circle_scribble", "box_scribble", "underline_scribble", "highlight", "burst", None]}
    rp["tone"] = {"type": ["string", "null"], "enum": ["primary", "accent", "accent2", "muted", None]}
    rp["on_media"] = {"type": ["boolean", "null"]}
    rp["tilt_deg"] = {"type": ["number", "null"], "minimum": -12, "maximum": 12}
    lp["regions"]["items"]["required"] = list(rp)
    layout["required"] = list(lp)
    return doc


def main() -> None:
    header = (
        "# Phase B.5.1: v9. Replaces v8's stale visual rules (light-only surfaces, 'do not plan black or dark surfaces', 'nothing is ever placed over an image', no\n"
        "# families) with Visual DNA v2: six accepted visual FAMILIES chosen per slide (bounded enum), solid dark surfaces allowed, overlay/scrim/dimming still forbidden,\n"
        "# the accepted declarative controls (ink/graphite, palettes, stage/collage arrangements, object staging, on_media in listed calm zones), a bounded role\n"
        "# vocabulary with a conclusion-only terminal role, and a meta-language rule. v8 stays published and untouched; every factual/evidence rule is inherited verbatim.\n"
    )
    V9.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V9)


if __name__ == "__main__":
    main()
