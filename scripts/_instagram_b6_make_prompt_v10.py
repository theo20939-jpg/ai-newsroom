"""Phase B.6: generate prompts/instagram_creative_director_carousel/v10.yaml from the (untouched) v9.1 file.

v10 = v9.1 (evidence handles, Visual DNA v2 families, bounded roles, meta-language guard, calm-zone / collage execution contract) PLUS the MEDIA-FIRST contract
(every slide names its visual source; generated media is first-class; no typographic-only slides; a suitable-source policy) and the Instagram adaptation of the shared
KAGE voice (the voice itself is supplied in the input from docs/brand/kage_voice_v1.md and is never copied here).

Usage: python scripts/_instagram_b6_make_prompt_v10.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V91 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v9.1.yaml"
V10 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.yaml"

_SYSTEM_OLD_HEAD = "You are NINJA's Instagram Creative Director for a carousel post."
_SYSTEM_NEW_HEAD = ("You are the Instagram Creative Director and copywriter for the KAGE account, making a carousel post. The shared KAGE VOICE is part of your input: you write in it, "
                    "adapted only by the Instagram rules below.")
_SYSTEM_TAIL_OLD = "and you never fake media."
_SYSTEM_TAIL_NEW = ("and you never fake media. Instagram is MEDIA-FIRST: every slide has a real visual idea (a suitable real image, a GENERATED contextual image, or a substantive graphic) - "
                    "text is part of the composition, never the whole slide.")

# v9.1 rules replaced by index (prefix-checked so a drift in v9.1 fails loudly)
_REPLACE_PREFIX = {
    13: "Every slide_copy must be a COMPLETE Russian thought",
    17: "Every slide sets `visual_family` to exactly one of those six ids",
    21: "FAMILY MECHANICS - dark_type_number_statement",
    27: "MEDIA AVAILABLE FOR THIS POST lists",
    28: "Plan for the CONTENT ARCHETYPE given in the input",
    30: "generated_media is not available",
}

R13 = ("Instagram copy is SHORT. slide_copy is a COMPLETE Russian thought that fits its regions, never a cut-off fragment - and it is deliberately brief: the hook (slide 1) is ONE strong line "
       "(up to about 70 characters) plus at most a tiny supporting phrase; later slides are one to two short lines. Rough capacity: a DISPLAY headline up to 60 characters, HEADLINE_L up to 90, "
       "HEADLINE_M up to 130. Long explanation belongs in the caption, not on the image. Never put a paragraph on a slide.")

R17 = ("Every slide sets `visual_family` to exactly one of the six ids and `visual_family_reason` (one short English sentence naming the content, purpose or media fit). Choose from the content, the "
       "slide's purpose, the media, the evidence type, the archetype and the slide's place in the story. Families are guidance, never a quota: do not rotate them mechanically and do not default to "
       "one. Every family now sits ON a visual: immersive_image_field, hero_object_stage and internet_culture_collage use a real subject or the slide's own GENERATED image; dark_type_number_statement, "
       "interface_cards and light_utility_editorial are typographic LAYOUT vocabularies that must be combined with a meaningful visual component - never used as a bare surface.")

R21 = ("FAMILY MECHANICS - dark_type_number_statement: background ink or graphite; a giant number (content_ref number, scale_token NUMERAL, tone accent) and/or a very short headline at DISPLAY, MEGA or "
       "HEADLINE_XL, ALWAYS beside or over-lapping a meaningful visual: a generated or real media region (framed, cut out, bleeding off an edge, or object_contain on a stage) - the number and text alone "
       "on an empty surface are NOT acceptable. FAMILY MECHANICS - interface_cards: background ink or graphite; a graphic poll_cards region (then slide_copy must have the shape 'Question? Option A | Option B | "
       "Option C' with two to four options separated by |, and the layout also needs a text region with copy_lead) or ui_frame or flow_diagram (flow_diagram needs a visual_direction whose steps are joined by an "
       "arrow); a large heading; a media fragment when it helps. FAMILY MECHANICS - light_utility_editorial: background paper or soft; a heavy headline with short supporting text or a step, one accent "
       "(numeral or rule) AND a clear visual (a generated or real image, framed or bleeding, or a substantive graphic); calm and explanatory; never the default answer and never a bare white slide.")

R27 = ("MEDIA AVAILABLE FOR THIS POST lists the real subject keys and, for each, SOURCE_AVAILABLE and SOURCE_SUITABLE_FOR_FINAL_VISUAL, the families the image can honestly support and its calm text zones. "
       "A media region may use a listed key OR the reserved key `generated` (the slide's own generated image, only when that slide's media_source is 'generated'). Set media_subject to the key the slide's "
       "main media uses (for a NEWS_RECAP slide about one story: that story's key, also when the slide is generated) and media_function to what the media is for (hero, detail, evidence_photo, ui_screenshot, "
       "result, before_after, concept, none). The same real key may appear on several slides, or several times on one slide with different crops, when it is genuinely the same subject; never use a listed "
       "image for a different factual subject. When a slide needs a screenshot, a result, a before/after or a concept visual and none is listed, use a GENERATED visual or a substantive graphic.")

R28 = ("Plan for the CONTENT ARCHETYPE given in the input and echo it exactly as content_archetype. ai_hack: instructional progression - a numbered step (start a step slide with 'Шаг N.' and a big number) "
       "sitting on a real visual per step: a generated scene or object that shows the situation, a substantive ui_frame / flow_diagram / poll_cards, a before/after or result visual; a clear result or takeaway "
       "that SHOWS the outcome. news_insight: story-led - the strongest real image staged at deliberately different scales (immersive, hero or collage only where it supports them) and GENERATED contextual "
       "visuals for the ideas no photo carries (a metaphor or scene of the specific insight); never image / text card / image / text card as a default rhythm. news_recap: a short opening with its own "
       "visual, one `story` slide per story with THAT story's real image when suitable, otherwise a GENERATED image specific to that story (media_subject = the story key), and a closing slide with a visual; "
       "never one story's image for another and never a shared filler. trend_generative: the most visual archetype - generated, collage, culture-native or immersive media carry the idea; the topic is "
       "expressed visually from the facts, and a text-heavy source card is never the centrepiece.")

R30 = ("GENERATED media is FIRST-CLASS. Every slide sets `media_source`: 'source' (a listed real subject that is SOURCE_SUITABLE_FOR_FINAL_VISUAL), 'generated' (a contextual image made for this slide) or "
       "'graphic' (a substantive graphic composition). There is no typographic-only slide: a rule, a scribble, a numeral or a headline on an empty surface is not a visual. Set media_strategy to "
       "'generated_media' when any slide is generated, else 'source_media' when any slide is source, else 'graphic'. Decision order per slide: (1) strong suitable real media, (2) a GENERATED contextual "
       "visual when real media is missing, weak, irrelevant, a text/article/screenshot card, unable to support the intended family, or simply inferior to a generated visual, (3) a graphic when the content itself "
       "is UI, a workflow, a comparison, a poll or a diagram. Generate per slide - different scene, object, metaphor or perspective, coherent as one post - never one image reused blindly. At most 6 slides "
       "of a post may be generated.")

NEW_RULES = [
    ("GENERATED slide contract: media_source 'generated', a `generation_brief` (a concrete description of what the picture SHOWS: the subject, the scene or visual metaphor, perspective and mood, in one or two "
     "sentences) and a layout with a media region whose content_ref is `generated` (crop_mode cover for immersive, object_contain on a media_ground stage for a hero object, or fragments for a collage). "
     "The generation_brief must depict THIS story's concrete idea so the picture communicates the story before the text is read - never a generic AI brain, glowing robot, random cyberpunk city, laptop, "
     "hologram or stock technology art unless the story is literally about it. The image contains NO text, letters, logos, watermarks, fake UI or third-party branding and never depicts an unsupported product "
     "appearance or fact; the renderer adds the exact Russian copy and the canonical logo. Generated images are portrait (4:5 framing) and may carry a calm low-detail area; on_media text is still only "
     "placed in a calm zone and the renderer relocates it deterministically if needed."),
    ("SOURCE policy: a listed image with SOURCE_SUITABLE_FOR_FINAL_VISUAL: NO (an article preview, headline card, social card or text-dominated screenshot) is evidence only. Never use it as a hero, an immersive "
     "field or the primary image; plan a GENERATED visual for that subject instead. It may appear as a small supporting collage fragment only when that genuinely helps. Never use a listed image for a slide "
     "unless it really is that slide's subject."),
    ("GRAPHIC policy: media_source 'graphic' requires a substantive graphic region in the layout - ui_frame, flow_diagram or poll_cards - that carries real information (an interface, a workflow, a comparison, "
     "a poll). A red rule, a scribble, an arrow or a giant numeral with text is NOT a graphic slide."),
    ("HOOK (slide 1) is the highest emotional pressure point. Write it so the reader feels at least one real reaction the story supports - surprise, curiosity, humour, disbelief, tension, desire, relatable "
     "frustration, 'that is useful' or 'what the hell' - and thinks 'I need the next slide', WITHOUT withholding facts artificially. Emotion first, the fact immediately identifiable, minimal copy. Prefer "
     "contrast, a provocation, an unexpected consequence, a relatable pain, absurdity, a specific surprise, a sharp question or a sharp observation. Avoid dull news openers such as 'Компания X представила...', "
     "'Новая модель получила...', '5 функций нового...', 'Главные новости недели...', 'Вот что произошло...' whenever a stronger supported angle exists. Set the hook slide's slide_purpose to 'REACTION: <the target "
     "reaction> - <which evidence handle supports the framing>'. The hook must still be factually safe and one strong line."),
    ("BOLD, NOT DISHONEST: emotion may be stronger than a Telegram headline; facts may not. Never use 'ты обязан', 'все делают неправильно', 'это уничтожит', 'интернет умер', 'всё изменилось' or a similar "
     "absolute unless the supplied evidence literally says it. Do not invent a cost, threat, failure or 'everyone' the evidence does not state."),
    ("Slides after the hook pay it off: explain, show the evidence and advance the story - do not make every slide equally loud. final_caption is finished KAGE-voice Russian copy that ADDS something (context, a "
     "short editorial observation, the practical implication) and does not repeat slide 1; avoid empty engagement bait ('Что думаете?', 'Согласны?', 'Листай карусель') unless it is genuinely useful."),
    ("The shared KAGE VOICE block in the input is the source of truth for tone: use it, do not restate or quote it, and never mention it or the brand voice in audience-facing copy. Instagram adaptation: "
     "same personality as everywhere, but shorter, sharper, more contrast-driven and more immediate on the image, with facts unchanged."),
    ("Typography stays large and part of the identity: two to four words deserve a very large scale token. It must interact with the image, object, graphic, collage or generated scene instead of floating alone "
     "on an empty canvas."),
]


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V91.read_text(encoding="utf-8")))
    doc["version"] = "10"
    system = doc["system"]
    assert _SYSTEM_OLD_HEAD in system and _SYSTEM_TAIL_OLD in system, "v9.1 system text changed"
    doc["system"] = system.replace(_SYSTEM_OLD_HEAD, _SYSTEM_NEW_HEAD, 1).replace(_SYSTEM_TAIL_OLD, _SYSTEM_TAIL_NEW, 1)
    rules = list(doc["rules"])
    replacements = {13: R13, 17: R17, 21: R21, 27: R27, 28: R28, 30: R30}
    for index, prefix in _REPLACE_PREFIX.items():
        assert rules[index].startswith(prefix), f"v9.1 rule {index} changed: {rules[index][:60]!r}"
        rules[index] = replacements[index]
    # rule 26 (asymmetry) and 18-20 stay; the family-availability sentence of rule 17 is replaced above.
    doc["rules"] = rules + NEW_RULES

    slide = doc["output_schema"]["properties"]["slides"]["items"]
    props = slide["properties"]
    props["media_source"] = {"type": "string", "enum": ["source", "generated", "graphic"]}
    props["generation_brief"] = {"type": ["string", "null"], "maxLength": 420}
    slide["required"] = list(props)
    plan = doc["output_schema"]["properties"]["creative_execution_plan"]
    if isinstance(plan, dict) and "properties" in plan:
        ms = plan["properties"]["media_strategy"]
        ms["enum"] = ["source_media", "generated_media", "graphic"]
    else:  # nullable-object shape
        for variant in plan.get("anyOf", []):
            if isinstance(variant, dict) and "properties" in variant:
                variant["properties"]["media_strategy"]["enum"] = ["source_media", "generated_media", "graphic"]
    return doc


def main() -> None:
    header = (
        "# Phase B.6: v10 = v9.1 + the MEDIA-FIRST contract (per-slide media_source, generated media first-class, no typographic-only slides, suitable-source policy) + the Instagram\n"
        "# adaptation of the shared KAGE voice (hook = highest emotional pressure, shorter copy, KAGE caption). The KAGE voice text itself is supplied in the input from\n"
        "# docs/brand/kage_voice_v1.md and is never copied here. v9.1 stays published and untouched.\n"
    )
    V10.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V10)


if __name__ == "__main__":
    main()
