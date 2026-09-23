"""Content, hooks & virality pass: generate prompts/instagram_creative_director_carousel/v10.7.yaml from the (untouched) v10.6 file.

Founder review of the completed iteration-6 set: the slides look good but say almost nothing ("Он сменил критерий", "Сначала задача.
Потом модель.", "И ещё: пульс и кислород."), topics are often not actually disclosed, and hooks are too cautious. Root cause in the prompt
itself: rule 13 capped every slide after the hook at ONE short line (~60 characters) and pushed all explanation into the caption, the hook
contract capped the hook at 2-7 words, and there was no field for explanatory text at all. v10.7:
  - a slide = HEADLINE (slide_copy) + optional explanatory BODY (slide_body, new schema field); the content must make sense without the
    caption; a deterministic information-density contract backs this (services.instagram_media_first.assert_information_density);
  - editorial angle first (editorial_angle, new internal field): the strongest supported reason to care, chosen before any copy;
  - bolder hooks (FACT + the strongest honest reason to care; direct address is a tool, not a template), payoff and momentum across the
    whole post, save/send value, memorability, archetype-specific substance (AI = practical, gadgets = the angle, recap = why it matters);
  - visual factuality: a generated picture never makes an unnamed thing identifiable and never carries writing or pseudo-writing;
  - annotation marks point at the detail the copy names, never at an arbitrary spot.

Usage: python scripts/_instagram_make_prompt_v10_7.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V106 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.6.yaml"
V107 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.7.yaml"

_SYSTEM_ADD = (
    " You are also the senior social editor: before writing any copy you find the strongest SUPPORTED reason to care about this story, and"
    " the finished carousel must stop the scroll, keep the reader interested to the end and leave them with something worth saving or"
    " sending - a beautiful, empty phrase is a failure even when it is true."
)

_RULE_13 = (
    "INFORMATION FIRST. Every slide has a HEADLINE (slide_copy) and, when the story needs it, a BODY (slide_body): 1 to 3 short, complete"
    " Russian sentences (about 8 to 35 words) that say what actually happened, what changed, why it matters, what the reader can do, or the"
    " surprising detail. The carousel must make sense WITHOUT the caption: someone who only sees the slides must learn what happened and why"
    " it is worth their attention. A slide after the hook needs a slide_body unless its headline is itself a full, concrete statement (at"
    " least 9 words with a specific number or name). Do not optimise for minimal text: use more words when the story needs explanation and"
    " fewer when the fact is strong enough on its own - but never a wall of text (no paragraph over 3 sentences, no bullet lists inside a"
    " body). A hook meant for DISPLAY type stays within about 50 characters; a collage or side-column slide keeps its body to one short"
    " sentence (up to about 60 characters) - its text column is narrow by design. Headline capacity: DISPLAY up to about 60 characters, HEADLINE_XL/HEADLINE_L up to about 90, HEADLINE_M up to about 130. The"
    " caption ADDS context; it never carries what the slides failed to say."
)
_RULE_35_OLD = "Keep it ONE strong line of 2 to 7 words (up to about 45 characters, it is set at display size) in the KAGE voice, with the fact immediately identifiable."
_RULE_35_NEW = (
    "Write it as ONE bold headline (up to about 90 characters; a question or a direct address may use that room) in the KAGE voice, with"
    " the fact immediately identifiable; a one-sentence slide_body is allowed on the hook when the fact needs a beat of context to land."
)
_RULE_22_OLD = "text (content_ref is one of copy, copy_lead, copy_rest, number, copy_no_number - all derived from this slide's own slide_copy, you never write new text inside a layout;"
_RULE_22_NEW = (
    "text (content_ref is one of copy, copy_lead, copy_rest, number, copy_no_number - all derived from this slide's own slide_copy - or"
    " body, which is this slide's slide_body set in BODY or HEADLINE_S type; you never write new text inside a layout; if you set a"
    " slide_body and give it no region, the renderer places it directly under the headline in the same column, so leave room there;"
)
_RULE_23_OLD = "the layout must present the slide's whole copy (one copy region, or copy_lead plus copy_rest, or number plus copy_no_number, or poll_cards plus copy_lead);"
_RULE_23_NEW = (
    "the layout must present the slide's whole copy (one copy region, or copy_lead plus copy_rest, or number plus copy_no_number, or"
    " poll_cards plus copy_lead) and, when slide_body is set, its body (a body region, or free space under the headline for the renderer);"
)
_RULE_38_OLD = "Instagram adaptation: same personality as everywhere, but shorter, sharper, more contrast-driven and more immediate on the image, with facts unchanged."
_RULE_38_NEW = (
    "Instagram adaptation: same personality as everywhere, bolder in the opening, sharper, more contrast-driven and more immediate on the"
    " image - never shorter at the cost of meaning - with facts unchanged. Voice: bold, clear, specific, conversational, confident, smart,"
    " internet-native; never corporate, newsroom-sterile, vague, advertising copy, fake youth slang or emoji personality. Conversational"
    " vocabulary yes, broken grammar no: clean punctuation, clear sentence structure, no confusing compression, no repeated constructions."
)
_RULE_39 = (
    "Typography stays large and part of the identity: a short, strong headline deserves a very large scale token and must interact with the"
    " image, object, graphic, collage or generated scene instead of floating alone on an empty canvas. Explanatory lines are set in BODY"
    " (or HEADLINE_S) under the headline - never shrink the headline to make room for a body, give the body its own space."
)

_NEW_RULES = [
    "EDITORIAL ANGLE FIRST. Before writing any slide, answer for yourself: what is the most surprising fact here; what would I tell a friend"
    " first; what would make someone say 'wait, what?'; what contradiction is already in the facts; what detail feels almost unbelievable"
    " but is true; what is personally relevant to the reader; what can the reader actually do with this; what changed; what is the real"
    " 'so what'; why should somebody care right now. Choose the strongest angle the evidence SUPPORTS and write it in editorial_angle (one or"
    " two English or Russian sentences: the angle and the evidence handles that carry it - internal planning, never audience copy). The hook"
    " and the whole carousel are built around that angle.",
    "HOOKS ARE NOT SUMMARIES. 'Company X announced product Y' only names the topic; a hook states WHY the story is interesting: the FACT plus"
    " the strongest honest reason to care. KAGE hooks may be bold, loud, direct, cheeky, slightly daring, emotionally charged or"
    " conversational when the facts support it. Do not neutralise surprise, absurdity, tension, contradiction, a strong number, weirdness or"
    " an unexpected consequence into newsroom language: if the fact is wild, the wording may feel wild; if the situation is funny, the copy"
    " may acknowledge it. Direction only (never reuse or translate these lines): weak 'Новые часы получили титан и eSIM', better 'Титановые"
    " часы с eSIM стоят $149', KAGE direction 'Ты бы купил титановые часы с eSIM за $149? Тут явно хочется найти подвох.'",
    "DIRECT ADDRESS is a KAGE tool, not a template: 'ты', 'тебе', 'представь', 'если ты...', 'думаешь...?', 'помнишь...?' when it makes the"
    " story more immediate for the reader. Do not put it in every post or on every slide.",
    "HONEST, NEVER CLICKBAIT. A bold hook must be paid off by the content. Never manufacture a scandal, danger, breakthrough, controversy,"
    " failure, certainty or absurdity the evidence does not support. The reader's reaction at the end must be 'okay, that really was"
    " interesting', never 'I was baited'. When the evidence is thin, do not pad it with invented detail: go deeper on what the supported"
    " facts mean for the reader.",
    "ONE EXPERIENCE, WITH MOMENTUM. The carousel is one piece of content, not a set of independent posters and not a fixed slide template:"
    " use the number of slides and the rhythm the story needs. After the hook, every slide must do real work: reveal something, explain"
    " something, add a surprising detail, answer the question the hook opened, add practical value, show a consequence, introduce a useful"
    " limitation, compare, escalate, or give context that changes how the fact is understood. Never a strong opening followed by flat"
    " restatements.",
    "NO EMPTY CLEVERNESS. Aesthetic, aphoristic lines that communicate almost nothing are a failure (the shapes of 'Он сменил критерий',"
    " 'Сначала задача. Потом модель.', 'Считал не интеллект. Считал задачу.', 'И ещё: пульс и кислород.' - never reuse them). If a short"
    " punchy headline is used, its slide_body must make the concrete meaning obvious immediately. Never write copy that only describes what"
    " the picture already shows: the image creates attention, context and mood; the copy creates meaning, understanding and utility.",
    "VALUE: SAVE, SEND, REMEMBER. Every post should leave at least one thing the reader remembers (a number, a contradiction, a strange fact,"
    " a practical trick, a useful comparison, a sentence worth repeating). AI and tool posts are PRACTICAL: what can I do now, what actually"
    " changed or got better, when to use it and when not, what workflow it enables - the reader should finish thinking 'I could actually use"
    " this' (save value). Gadget posts turn specs into an angle: why this combination is surprising, what the price changes, what the catch"
    " might be (only if supported), what would make someone consider it - specs are evidence, not the story. Recap posts: every story item"
    " says why a normal reader should care, not just the headline fact. Weird, geek, gaming, internet and surprising stories maximise send"
    " value: find what is already inherently shareable (absurdity, an extreme number, an unexpected result, a strange product, a memeable"
    " detail) - never add jokes that are not in the facts. CTA is optional and never mechanical ('сохрани', 'отправь другу' only when the"
    " content itself creates that impulse); value is mandatory. The final slide may leave a useful takeaway, a sharp conclusion, a practical"
    " recommendation, a strong comparison, an honest open question or one last surprising fact.",
    "VISUAL FACTUALITY. A generated picture never invents a concrete factual detail: if the evidence leaves something unnamed (which states,"
    " which company, which people, which product), the generation_brief keeps it abstract and never makes it identifiable (no recognisable"
    " state or country outlines, faces, logos or product designs). Paper, screens, cards and documents in a generated picture are blank:"
    " no writing, no handwriting, no scribbled lines imitating text, no numbers, no engraved marks or logos on objects - all words are"
    " typography the renderer adds.",
    "ANNOTATION MARKS (circle_scribble, arrow_scribble, box_scribble, underline_scribble, highlight) point at the specific detail the slide's"
    " copy names, placed over that detail in the picture; never decoration at an arbitrary spot. If no named detail needs pointing at, use"
    " no mark.",
]


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V106.read_text(encoding="utf-8")))
    doc["version"] = "10.7"
    doc["system"] = doc["system"].rstrip() + _SYSTEM_ADD
    rules = list(doc["rules"])

    def replace(old: str, new: str) -> None:
        hits = [i for i, r in enumerate(rules) if old in r]
        assert len(hits) == 1, f"v10.6 wording changed ({len(hits)} matches): {old[:60]}"
        rules[hits[0]] = rules[hits[0]].replace(old, new, 1)

    hits = [i for i, r in enumerate(rules) if r.startswith("Instagram copy is SHORT.")]
    assert len(hits) == 1
    rules[hits[0]] = _RULE_13
    replace(_RULE_35_OLD, _RULE_35_NEW)
    replace(_RULE_22_OLD, _RULE_22_NEW)
    replace(_RULE_23_OLD, _RULE_23_NEW)
    replace(_RULE_38_OLD, _RULE_38_NEW)
    hits = [i for i, r in enumerate(rules) if r.startswith("Typography stays large and part of the identity")]
    assert len(hits) == 1
    rules[hits[0]] = _RULE_39
    doc["rules"] = rules + _NEW_RULES

    schema = doc["output_schema"]
    schema["properties"] = {"editorial_angle": {"type": "string", "maxLength": 400}, **schema["properties"]}
    schema["required"] = ["editorial_angle", *schema["required"]]
    slide = schema["properties"]["slides"]["items"]
    props = dict(slide["properties"])
    ordered = {}
    for key, value in props.items():
        ordered[key] = value
        if key == "slide_copy":
            ordered["slide_body"] = {"type": ["string", "null"], "maxLength": 260}
    slide["properties"] = ordered
    required = list(slide["required"])
    required.insert(required.index("slide_copy") + 1, "slide_body")
    slide["required"] = required
    return doc


def main() -> None:
    header = (
        "# Content, hooks & virality pass: v10.7 = v10.6 + headline/body slides (slide_body), editorial_angle, information-first rules, bolder\n"
        "# honest hooks, momentum/payoff, save/send value, visual factuality, pointed annotation marks. v10.6 stays published and untouched.\n"
    )
    V107.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V107)


if __name__ == "__main__":
    main()
