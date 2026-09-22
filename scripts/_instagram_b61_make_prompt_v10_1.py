"""Phase B.6.1: generate prompts/instagram_creative_director_carousel/v10.1.yaml from the (untouched) v10 file.

v10.1 = v10 (factual safety, evidence handles, media-first policy, generated media, Visual DNA v2 rules, no text-only slides) with ONLY two contract changes exposed by the real B.6
sample: (1) the HOOK contract - the first slide must deliberately create one stated reader reaction (`hook_emotion`), never a descriptive news line; (2) generated visuals need a
story-specific anchor and a concrete visual_direction and must not default to generic AI art.

Usage: python scripts/_instagram_b61_make_prompt_v10_1.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V10 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.yaml"
V101 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.1.yaml"

HOOK_PREFIX = "HOOK (slide 1) is the highest emotional pressure point."
GENERATED_PREFIX = "GENERATED slide contract:"

HOOK_RULE = (
    "HOOK CONTRACT (slide 1). The first slide is the hook and must deliberately create ONE clear reader reaction. State that reaction in hook_emotion (surprise, curiosity, humour, disbelief, "
    "tension, desire, relatable_frustration, usefulness or absurdity) - the reaction you are writing FOR - and set hook_emotion to null on every other slide. The reader should think 'wait, what?', "
    "'that is useful', 'why?', 'seriously?' or 'I need the next slide', without you hiding essential truth. A merely descriptive sentence (a neutral statement of what happened or what the tip is) is NOT a "
    "hook: if you could have written it as a plain news headline or a how-to title, rewrite it. A hook normally does at least TWO of: expose a contradiction; create personal relevance; surface an "
    "absurdity; reveal an unexpected consequence; challenge an intuitive assumption; create a sharp comparison; turn the factual insight into a relatable tension. Keep it ONE strong line (up to about 70 "
    "characters) in the KAGE voice, with the fact immediately identifiable. Set the hook slide's slide_purpose to ONE sentence saying why that emotion fits the supplied fact and which evidence handle "
    "supports it. Archetype direction: ai_hack - relief, surprise, usefulness or relatable frustration around the pain the hack removes, not an instruction ('how to ...'); news_insight - turn the insight "
    "into tension or personal relevance for the reader; news_recap - the opening must NOT read like a weekly newspaper digest ('главные новости', 'эта неделя', 'неделя, когда ...'): synthesise the week's "
    "strongest emotional pattern into one sharp line; trend_generative - one of the boldest formats: surprise, absurdity, internet-culture tension or an unexpected contrast. Hook strength never authorises "
    "exaggeration: never invent impact, certainty, market consequences, user behaviour, performance, future dominance, scarcity or urgency - the emotion is an interpretation of SUPPORTED facts only. "
    "Avoid dull news openers such as 'Компания X представила...', 'Новая модель получила...', '5 функций нового...', 'Главные новости недели...', 'Вот что произошло...'."
)

GENERATED_RULE = (
    "GENERATED slide contract: media_source 'generated', a `generation_brief` (a concrete description of what the picture SHOWS: the subject, the scene or visual metaphor, perspective and mood, in one or two "
    "sentences), a `story_anchor` and a layout with a media region whose content_ref is `generated` (crop_mode cover for immersive, object_contain on a media_ground stage for a hero object, or fragments for "
    "a collage). The story_anchor is the ONE concrete thing, action or relationship, taken from the supplied evidence or the slide's purpose, that makes this image belong to THIS story; if the picture could be "
    "reused unchanged for ten unrelated AI posts, replan it. The slide's visual_direction (English, two or three sentences) must answer: what is physically visible; what the story-specific subject is; what "
    "relationship or action is shown; why this visual supports this slide. 'Futuristic AI visual', 'abstract technology scene' and 'dynamic AI composition' are not directions. Do NOT default to glowing "
    "cubes, floating spheres or random geometry, generic AI brains, anonymous robots, holograms, cyberpunk cities, abstract monoliths or neon circuitry unless the supplied evidence is literally about that "
    "object; prefer a recognisable concrete object, place, gesture, comparison or before/after tied to the story, and for a NEWS_RECAP story depict that story's own subject. The image contains NO text, "
    "letters, logos, watermarks, fake UI or third-party branding and never depicts an unsupported product appearance or fact; the renderer adds the exact Russian copy and the canonical logo. Generated "
    "images are portrait (4:5 framing) and may carry a calm low-detail area; on_media text is still only placed in a calm zone and the renderer relocates it deterministically if needed. Non-generated "
    "slides set story_anchor to null."
)


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V10.read_text(encoding="utf-8")))
    doc["version"] = "10.1"
    rules = list(doc["rules"])
    replaced = 0
    for i, rule in enumerate(rules):
        if rule.startswith(HOOK_PREFIX):
            rules[i], replaced = HOOK_RULE, replaced + 1
        elif rule.startswith(GENERATED_PREFIX):
            rules[i], replaced = GENERATED_RULE, replaced + 1
    assert replaced == 2, f"v10 hook / generated rules changed ({replaced} of 2 found)"
    doc["rules"] = rules
    slide = doc["output_schema"]["properties"]["slides"]["items"]
    props = slide["properties"]
    props["hook_emotion"] = {"type": ["string", "null"], "enum": ["surprise", "curiosity", "humour", "disbelief", "tension", "desire", "relatable_frustration", "usefulness", "absurdity", None]}
    props["story_anchor"] = {"type": ["string", "null"], "maxLength": 240}
    slide["required"] = list(props)
    return doc


def main() -> None:
    header = (
        "# Phase B.6.1: v10.1 = v10 + (1) the HOOK contract (the first slide deliberately creates ONE stated reader reaction: hook_emotion) and (2) generated visuals need a story-specific\n"
        "# anchor and a concrete visual_direction, with no generic AI-art defaults. Everything else (evidence handles, media-first policy, Visual DNA v2, calm-zone / collage execution)\n"
        "# is inherited from v10 verbatim. v10 stays published and untouched.\n"
    )
    V101.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V101)


if __name__ == "__main__":
    main()
