# KAGE Instagram — daily story selection, 2026-09-29

Offline only. No provider call, no image call, no natural canary. Replayed on the 10 saved read-only production pools (canaries 1–10).
Full data: `daily_selection_after.json`.

## What changed

The daily story slot is nominated from the WHOLE candidate pool. That was already true in production (`open_slots`), but only the
narrow "viral mechanism" family could pass the gate. Now:

- **Four families compete**:
  - viral / meme events, including AI feats — cracking, solving, a record;
  - AI launches — a named model or product; plans, roadmaps, deals and generic "a new X model" don't count;
  - gadgets and devices — a launch or leak, or an unusual device someone built;
  - large serious incidents.
- **Weekly recap is no longer a sink.** An item the old read called "weekly news" takes the daily slot when its story is strong.
- **One strong idea is enough.** A relatable or absurd event or a real launch weighs 2; an institutional signal 1; a concrete magnitude adds 1–2.
- **Shareability can beat coverage.** Ranking is strength band → the story's own points → momentum → visual. Coverage breaks ties only.
- **Historical context is not an old event.** "A transmission from 85 years ago" dates the object, not the event.
- **Enterprise is judged on what launched.** A named or versioned launch is strong for any audience; a generic release is weak for any audience.
- **Kept:**
  - relevance, freshness (72-hour window, the single-undated-source safeguard) and the procedural fix (953e77d);
  - famous names never rescue a weak story;
  - roundups and "there are no X" opinions have no hook.

## Before → after winners

| Pools | Before (953e77d) | After | Why |
|---|---|---|---|
| 1–5 | OpenAI's agents targeted and infiltrated US government websites | **Claude снёс разрабу 48 000 файлов за полторы минуты** | An AI agent wiping 48,000 files in 90 seconds is instantly understood, relatable to anyone who has used an assistant, and made to be sent to a friend. The OpenAI story had more coverage, but coverage now only breaks ties. |
| 6–8 | Researchers: OpenAI's agents meddled with the US Commerce Dept. and SEC sites | same | Still the strongest: a big, current AI-security story. A gadget (Red Dead Redemption 2 on iPhone 18 Pro) is now #2. |
| 9–10 | OpenAI agents tried to 'bruteforce' a UN website | same | An AI agent itself did the strange thing. The robot-spider and the SNL sketch now compete behind it. |

What each pool now offers over the following days (publish the winner, take the next):

- **Canaries 1–4:** Claude's 48,000 files → OpenAI's agents infiltrating government sites → agents leaking 53 ChatGPT images → **GPT-6 Astra cracking the 1941 Enigma message** → OpenAI pausing training.
- **Canaries 6–8:** OpenAI's agents on US government sites → **Red Dead Redemption 2 running on iPhone 18 Pro** → an AI hacking a government site → OpenAI pausing training → **Dario Amodei on SNL**.
- **Canary 10:** the UN brute-force → an AI life-detector fooled 100% in 150 mutations → **a welding robot-spider that crawls on ceilings** → OpenAI pausing training → SNL → **Starlink mobile**.

That is a strange AI failure, a serious incident, an AI feat, a gadget and pop culture, picked by strength and not by a quota.

**No fresh major AI launch exists in these pools.** GPT-6 Sol/Luna and Claude Opus 5.5 were published more than 72 hours before canary 2, and freshness rejects them correctly. AI launches are proven on real headlines in `tests/test_instagram_daily_story_selection.py`: a flagship model release wins its day against a one-idea pop-culture story.

## The named stories

| Story | Fresh | Daily | Standing | Why |
|---|---|---|---|---|
| Claude deleted 48,000 files in 90 s | current | eligible | **wins** (1–5) | An AI failure with a huge, concrete number. |
| AI agents colluded to count cards in blackjack | undated | not yet | strong, held by freshness | One strong idea is now enough, but it is a single undated source. It competes as soon as a second outlet or a date appears. |
| Teenager hacks Microsoft DB, 17 trillion rows | undated | not yet | strong, held by freshness | Same as above: strong on scale, single undated source. |
| Gemini app replacing Gems with skills | undated | no | weak | A routine product update — nothing a reader stops for. |
| Welding robot-spider | undated, but strong momentum | eligible | competitive (#3, canary 10) | An unusual device doing something visual. |
| Dario Amodei gets the SNL treatment | current | eligible | competitive (#4–6) | A tech figure in mass pop culture. |
| OpenAI agents brute-force a UN website | current | eligible | **wins** (9–10) | The AI itself did the strange thing. |
| ChatGPT-6 Astra cracks 1941 Enigma message | current (was wrongly OLD) | eligible | competitive (#3–4, canaries 1–4) | An astonishing AI feat. The 1941 date is the message's age, not the event's. |
| Anthropic / Australian Senate (canary 10) | current | no | deprioritized | A procedural event with no real-world consequence. |
