# KAGE Instagram — selection remediation (viral slot), 2026-09-29

Offline only. No provider call, no image call, no natural canary.

## Why the canary-10 story won (reconstructed from the saved pool)

Pool: 1,184 candidates in 24 h → 455 KAGE candidates → 373 distinct events → only **2** cleared the viral gate:

- "OpenAI, Anthropic CEOs called to appear at Australian AI probe" (the winner)
- "OpenAI agents tried to 'bruteforce' a UN website"

Both were STRONG with STRONG momentum. The procedural story won on the tie-break.

It was STRONG because of words that belong to a **different event**:

- `unexpected_ai_behaviour` matched "…amid fallout from OpenAI **hack** — Company behind Claude **chatbot**…" — the headline's background clause glued to the lead's first words;
- `security_surprise` matched the same "hack … Australian government";
- it was "broad" because the headline names **OpenAI** (a brand) and the lead says "government".

The story's own event — a CEO declining one committee hearing — has no viral mechanism and no consequence for a reader.

**First product divergence:** the viral gate judged the story by an event it only mentions as background, and let a famous name stand in for reader interest.

## Change (services/instagram_viral_story_gate.py only)

1. **Own-event reading.** Background-attribution clauses are removed before mechanisms and interest anchors are read: amid …, in the wake of …, following reports that …, after the revelation that …, на фоне …, после сообщений …
2. **Procedural headlines need a consequence.** When the headline's own action is procedural — hearing, inquiry, committee, testifying, summoned or invited, declining to appear — a brand or institution name alone no longer makes it broad. A real consequence still does: a ban, lawsuit, breach, millions of users, outage or recall.

No topic, company or country names appear in either rule.

## Before / after on the 10 saved canary pools

| Pool | Before | After |
|---|---|---|
| canaries 1–5 | OpenAI's agents targeted and infiltrated US government websites | same |
| canaries 6–8 | Researchers: OpenAI's agents meddled with the US Commerce Dept. and SEC sites | same |
| canaries 9–10 | OpenAI, Anthropic CEOs called to appear at Australian AI probe | **OpenAI agents tried to 'bruteforce' a UN website** |

Why the new canary-9/10 winner is the better KAGE story: an AI agent trying to brute-force a UN website is the event itself. It is strange, it is about what an AI system did, and you can explain it in one sentence without procedure. The old winner needed a paragraph of institutional context before its interesting part, and that part was another story.

**Canary-10 story disposition: valid but deprioritized.** It is still current KAGE news (usable if requested). It fails the viral gate at *3 broad interest* (a procedural event with no real-world consequence) and no longer takes the viral slot. The only other gate changes across all pools are the same inquiry's other procedural headlines ("Australia summons … to appear", "… дать показания", "вызвали на «ковер»"). None of them was eligible before either.

## Not changed — founder decisions needed

- **Product / gadget / major AI news never competes for a daily post.** That is the frozen feed model (`instagram_feed_product`): ordinary AI / gadget news → WEEKLY_NEWS, "never a daily post". In canary 10's pool, 584 items were routed there, for example "Gemini app replacing Gems with skills", a welding robot-spider, and "Dario Amodei gets the SNL treatment". Letting major product or gadget news win a daily slot is a feed-model change, not a ranking tweak.
- **Humour vs coverage within the viral slot.** In canaries 1–5 the memeable "Claude снёс разрабу 48 000 файлов за полторы минуты" was also eligible and STRONG, but lost on momentum to the more widely covered OpenAI government-sites story. Ranking relatable / absurd mechanisms above coverage would change those accepted winners.
- **Memeable stories often fail with a single mechanism.** "AI Agents Secretly Colluded to Count Cards in Blackjack" has only one matched mechanism and a single source, so it never enters the slot. Wider viral recall is a separate change.
