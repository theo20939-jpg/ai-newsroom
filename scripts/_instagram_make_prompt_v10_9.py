"""Creative Director judgment reset: generate prompts/instagram_creative_director_carousel/v10.9.yaml from the (untouched) v10.8 file.

v10.8 was not accepted: 0/4 first-pass outputs were product-strong. Diagnosis from the two paid runs (v10.7, v10.8) and the founder
reference - the failures came from CONFLICTING and PILED-UP instructions, not missing ones:
  - NEWS_RECAP led with the Sol error claim although its own angle list called Luna (~1% of the cost) the most forwardable: rule 35
    told a recap hook to "synthesise the week's strongest emotional pattern" while rule 49 said "open with the single strongest fact";
    the model compromised on story 1's first claim. Listing candidates is not committing to one.
  - NEWS_INSIGHT repeated one thesis four times: rule 3 ("never state a fact not in the evidence") read as a ban on any advice, so with
    two facts the model padded instead of giving the reader a method.
  - AI_HACK's hook described the mechanism ("Два шага - и чек-лист"): nothing asked what the READER gets.
  - TREND_GENERATIVE refused the story: "you MUST NOT name, imply, or hint at the product" / "do not name the product or its brand" never
    said WHICH product; a gadget story reads as "the product". v10.8's "an editorial reviewer rejects ..." pushed it further to caution.
  - Russian errors recurred despite a long prohibition list at rule 55 of 57.
v10.9 REMOVES 21 overlapping copy/hook/compliance rules and replaces them with 6 short editorial ones; rewrites the product rule so it is
about OUR OWN product only (the news subject is always named); drops the reviewer sentence; and makes the model write one compact
editorial_decision FIRST - the strongest true thing, why a reader cares, what must survive, what each card adds - and then build the post
on it. Layout, family, media and visual rules are unchanged.

Usage: python scripts/_instagram_make_prompt_v10_9.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V108 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.8.yaml"
V109 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.9.yaml"

_SYSTEM = (
    "You are the senior social editor and Creative Director of KAGE on Instagram, making one carousel. You write in the shared KAGE VOICE"
    " (part of your input). Work in this order:\n"
    "1. What is the strongest TRUE thing in this evidence - the number, price, contrast or consequence a person would forward to a friend?\n"
    "2. Why should a person care about it?\n"
    "3. What would make them keep reading?\n"
    "4. Which useful or surprising detail must not be lost (a number, a prompt, a method, a comparison)?\n"
    "5. How do I say it naturally, in modern Russian with KAGE attitude?\n"
    "6. Only then: check facts and format.\n"
    "Write that decision down first in editorial_decision, then build the carousel ON it: the hook is the strongest true thing, not a safer"
    " neighbour of it. Safety shapes a strong story; it never replaces the story.\n"
    "Facts: every factual claim (fact, number, quote, capability) comes from the EVIDENCE list, cited by its handle (E1, E2, ...) in"
    " evidence_used. Practical advice that follows directly from the evidence ('посчитай, во что задача обходится на разных моделях') is"
    " welcome - it adds no new fact.\n"
    "Names: the NEWS SUBJECT - the companies, products, people and numbers the evidence is about - is the story; name it normally."
    " PRODUCT_MENTION_ALLOWED and restricted claims are about OUR OWN brand's product only (the one in CURRENT PRODUCT TRUTH): when it is"
    " false, do not promote or mention OUR product. It never limits naming the news subject.\n"
    "Instagram is MEDIA-FIRST: every slide has a real visual idea (a suitable real image, a GENERATED contextual image or a substantive"
    " graphic), planned in one of the accepted visual families from the Visual DNA block, against the real media listed for this post."
)

_REMOVED_PREFIXES = (
    "If product_mention_allowed is false",          # 6: replaced by the scoped product rule in the system text
    "INFORMATION FIRST.",                            # 13
    "HOOK CONTRACT (slide 1).",                      # 35
    "BOLD, NOT DISHONEST:",                          # 36
    "Slides after the hook pay it off",              # 37
    "The shared KAGE VOICE block",                   # 38
    "Typography stays large",                        # 39
    "EDITORIAL ANGLE FIRST.",                        # 40
    "HOOKS ARE NOT SUMMARIES.",                      # 41
    "DIRECT ADDRESS is a KAGE tool",                 # 42
    "HONEST, NEVER CLICKBAIT.",                      # 43
    "ONE EXPERIENCE, WITH MOMENTUM.",                # 44
    "NO EMPTY CLEVERNESS.",                          # 45
    "VALUE: SAVE, SEND, REMEMBER.",                  # 46
    "ANGLE SELECTION IS A COMPARISON",               # 49
    "HOOK: frame the FACT strongly",                 # 50
    "USABLE CONTENT SURVIVES VERBATIM.",             # 51
    "EVERY CARD ADDS NEW VALUE.",                    # 52
    "HEADLINE AND BODY DIVIDE THE WORK",             # 53
    "FACT FIDELITY.",                                # 54
    "RUSSIAN EDITING.",                              # 55
)

_ARCHETYPE_OLD = ("news_recap: a short opening with its own visual (a GENERATED image that synthesises the week, or a clearly different"
                  " crop and scale of one story's image - never the same picture framed the same way as the story slide that follows),")
_ARCHETYPE_NEW = ("news_recap: the opening card leads with the week's single strongest fact (whichever story it comes from), with its own"
                  " visual (a GENERATED image, or a clearly different crop and scale of one story's image - never the same picture framed"
                  " the same way as the story slide that follows),")

_NEW_RULES = [
    "THE HOOK is slide 1: the strongest true thing from editorial_decision, stated so a person stops scrolling - a concrete fact plus the"
    " reason it is interesting (tension, contrast, an extreme number, an unexpected price, a challenged assumption, practical relevance,"
    " 'где подвох?'). It is never a topic label or a description of a mechanism; say what the reader GETS or what is surprising. Bold,"
    " direct, cheeky when the fact earns it - no bolted-on 'Серьёзно?'. At most 60 characters (display type); one sentence of context may go"
    " in its slide_body. Set hook_emotion and hook_mechanic to what the line actually does.",
    "EACH CARD is a headline (slide_copy: what happened) plus, when needed, a slide_body of 1-3 short sentences (why it matters, what else,"
    " what to do). The body develops the headline - it never repeats it. Every card after the hook adds something new: a fact, a"
    " consequence, a comparison, a limitation, the answer to the hook, or a method the reader can use. Never restate an earlier card in"
    " other words; if the story has three strong cards, make three. The post must make sense without the caption.",
    "KEEP WHAT A READER WOULD SAVE: exact prompts, commands, settings and methods from the evidence appear verbatim in «...» on the card"
    " where they are used; if the evidence says to ask the model something, the card says to ask the model. How-to and insight posts end"
    " with something the reader can do.",
    "KEEP FACTS EXACT: tense and status as in the evidence (done stays done, planned stays planned), attribution as in the evidence"
    " ('OpenAI заявляет', 'утверждается'), chronology intact, no conclusion broader than the evidence ('ИИ стал ...'). A strong hook still"
    " has to be paid off by the cards that follow.",
    "WRITE LIKE A RUSSIAN EDITOR, not a translator: modern, natural, conversational ('выкатили', 'где подвох?', 'ты бы взял?' are fine),"
    " never formal for safety. Direct address ('ты', 'если ты...') when it makes the story closer, not on every card. Examples of the"
    " difference: 'Неделя, где ИИ стал...' -> 'Неделя, когда ...'; 'Claude Code принял стандарт AGENTS.md' -> 'Claude Code теперь понимает"
    " AGENTS.md'; 'при стоимости около 1% от его стоимости' -> 'примерно за 1% его цены'; 'Xiaomi заявила, что Pro якобы ...' ->"
    " 'Утверждается, что Pro ...'; 'Он сменил сам принцип выбора' (says nothing) -> the concrete change itself. final_caption adds"
    " context; it never carries what the slides failed to say.",
    "SHAPE: 2 to 10 slides; at most 6 with media_source 'generated' (in a recap with more stories, use a story's own suitable image or a"
    " substantive graphic for the rest); the last slide is result, takeaway, cta or closing.",
]


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V108.read_text(encoding="utf-8")))
    doc["version"] = "10.9"
    doc["system"] = _SYSTEM
    kept = []
    removed = []
    for rule in doc["rules"]:
        if rule.startswith(_REMOVED_PREFIXES):
            removed.append(rule)
            continue
        if rule.startswith("OUTPUT BOUNDS"):  # folded into SHAPE
            removed.append(rule)
            continue
        kept.append(rule.replace(_ARCHETYPE_OLD, _ARCHETYPE_NEW) if _ARCHETYPE_OLD in rule else rule)
    assert len(removed) == len(_REMOVED_PREFIXES) + 1, f"v10.8 wording changed: removed {len(removed)}"
    assert any(_ARCHETYPE_NEW in r for r in kept)
    doc["rules"] = kept + _NEW_RULES

    schema = doc["output_schema"]
    props = dict(schema["properties"])
    props.pop("angle_candidates", None)
    props.pop("editorial_angle", None)
    decision = {
        "type": "object", "additionalProperties": False,
        "required": ["strongest_true_thing", "evidence", "why_a_reader_cares", "must_survive", "card_plan"],
        "properties": {
            "strongest_true_thing": {"type": "string", "maxLength": 300},
            "evidence": {"type": "string", "maxLength": 60},
            "why_a_reader_cares": {"type": "string", "maxLength": 300},
            "must_survive": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 160}},
            "card_plan": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": "string", "maxLength": 160}},
        },
    }
    schema["properties"] = {"editorial_decision": decision, **props}
    schema["required"] = ["editorial_decision", *[r for r in schema["required"] if r not in ("angle_candidates", "editorial_angle")]]
    return doc


def main() -> None:
    header = (
        "# Creative Director judgment reset: v10.9 = v10.8 minus 22 overlapping copy/hook/compliance rules, plus an editor-first system text,\n"
        "# a product rule scoped to OUR product (the news subject is always named), editorial_decision written first, and 6 short editorial rules.\n"
    )
    V109.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V109)


if __name__ == "__main__":
    main()
