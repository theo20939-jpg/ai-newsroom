"""Weekly recap evidence cut (2026-09-26): a stored HTML body is cut along its own paragraphs and only complete sentences become recap
facts. Real failure (2 of 3 live recap runs): the Guardian RSS body opens with an unpunctuated standfirst paragraph; flattened to one line
it was glued onto the lede as ONE item beginning mid-name ("AI Security Institute says ... new type of risk Advanced AI models ..."),
the model quoted it as "UK AI Security Institute says ...", and the strict quote check - correctly, and unchanged - rejected the recap.
No provider, no network, no DB."""
from __future__ import annotations

import pytest

import services.instagram_creative_director as cd
import services.instagram_evidence_package as ep

PREMISE = "OpenAI and Anthropic models went on a hacking spree when tested by the UK's AI research institute"
# the stored body exactly as the Guardian RSS item carries it (local DB event 09a24f87-f34c-4d19-889d-9a211b20a555)
GUARDIAN = (
    "<p>AI Security Institute says tools engaged in potentially harmful activity and incident reveals new type of risk</p>"
    "<p>Advanced AI models developed by OpenAI and Anthropic went rogue during a cybersecurity test and showed a new type of risk posed by "
    "the technology, according to the UK’s AI Security Institute.</p>"
    "<p>AISI described the actions carried out by the agents – the term for AI systems that can perform tasks without human help – as a "
    "“serious incident”. In one example, an agent powered by Anthropic’s Mythos model sent targeted emails to people.</p> "
    '<a href="https://www.theguardian.com/technology/2026/aug/05/openai-anthropic-models-went-rogue-cybersecurity-test-ai-security-institute">'
    "Continue reading...</a>"
)
LEDE = ("Advanced AI models developed by OpenAI and Anthropic went rogue during a cybersecurity test and showed a new type of risk posed by "
        "the technology, according to the UK’s AI Security Institute.")
GLUED = "AI Security Institute says tools engaged in potentially harmful activity and incident reveals new type of risk " + LEDE


async def _facts(body: str) -> list[str]:
    package = await ep.build_recap_story_package(post_id="story_4", premise=PREMISE, headlines=[PREMISE], bodies=[("event:1:body", body)])
    return [item.text for item in package.facts]


def test_the_old_cut_reproduces_the_malformed_item():
    old = ep.assemble_package(post_id="x", fmt="weekly_recap_story", premise=PREMISE,
                              sources=[ep.EvidenceSource(url=None, source_type=ep.STORED_BODY, text=ep.plain_text(GUARDIAN))],
                              media=ep.SourceMedia(status=ep.NOT_AVAILABLE, reason="-"))
    assert GLUED in [item.text for item in old.facts]  # the pre-fix behaviour, kept here as the reproduction


@pytest.mark.asyncio
async def test_the_standfirst_is_never_glued_to_the_lede_and_the_lede_is_its_own_clean_item():
    facts = await _facts(GUARDIAN)
    assert LEDE in facts
    assert not any(f.startswith("AI Security Institute says") or "new type of risk Advanced" in f for f in facts)


@pytest.mark.asyncio
async def test_only_complete_sentences_become_recap_facts():
    body = ("<p>OpenAI and Anthropic models went rogue in a UK cybersecurity test, the AI Security Institute said on Tuesday.</p>"
            "<p>OpenAI and Anthropic models went rogue in the UK test The Guardian</p>"  # a headline with a source label: no sentence end
            "<p>The UK institute said the OpenAI and Anthropic agents sent emails in the test. rozetked.me/news/47613</p>")  # a glued link
    facts = await _facts(body)
    assert facts == ["OpenAI and Anthropic models went rogue in a UK cybersecurity test, the AI Security Institute said on Tuesday."]


def test_paragraphs_come_from_block_markup_only():
    assert ep.recap_paragraphs("<p>One.</p><p>Two.</p>") == ["One.", "Two."]
    assert ep.recap_paragraphs("Line one<br/>Line two") == ["Line one", "Line two"]
    assert ep.recap_paragraphs("A plain body. With two sentences.") == ["A plain body. With two sentences."]  # no markup: one piece


def test_grounding_is_unchanged_the_completed_quote_still_fails_and_the_exact_lede_grounds():
    with pytest.raises(cd.UngroundedEvidenceError):
        cd.assert_evidence_grounded(["UK " + GLUED], [LEDE])
    cd.assert_evidence_grounded([LEDE], [LEDE])
