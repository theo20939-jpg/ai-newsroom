# Phase 23.1I — Live Editorial Hardening: Human Review Packet

**Run**: 2026-08-10, ~00:09–00:13 (≈4.3 minutes wall clock, `automation_worker` paused for the
duration per the Story Memory live-shadow plan documented in the technical report). Route:
`chat_id=-1004297182444`, `message_thread_id=2` (verified programmatically before any send).
Settings: `copywriting_prompt_version=7` (plain-language rules), `story_memory_mode=shadow`,
`editorial_delivery_mode=router`. Stop reason: `nothing_eligible` — the fresh pool that cleared
the pre-existing score gate was exhausted after round 1. Cost: **$0.032776** (well under the
$1.00 cap). **1 of a target 5** posts delivered — thin fresh-eligible pool at run time (confirmed
before and after the run: 0 of 44 pending candidates clear the score≥65 gate), not a defect. The
brief explicitly authorizes stopping with fewer than 5 rather than lowering thresholds to
manufacture volume.

---

## NEWS #1

**Treatment**: MAJOR (reason: "high significance (8.6), evidence not weak")

**Original headline**: Доказательство заняло 30 минут, проверка — 5 дней. Как ИИ закрыл задачу
теории связи (source: habr.com)

**Story**: no NewsEventStoryLink — Story Memory did not classify this event against any prior
story this run (the pending backlog at run time did not include a genuine second source for the
same event; see technical report §5 for why Story Memory shadow, though correctly wired this run,
observed zero real triage activity).

**Previous Story delivery**: n/a (no Story link at all).

**Intelligence**: significance 8.6/10 — the recommendation explicitly frames this as a story about
the *verification gap* (30 minutes to generate a proof candidate vs. 5 days for a human to check
it), not as "AI solved an open problem," and flags that the exact role of the two models named
in the source is unclear.

**Fact Safety** (shadow mode, advisory only — did **not** block this send): `status=block`,
`highest_risk=high`, 12 claims checked, 9 supported, 3 unsupported — all 3 unsupported findings
are the **same word, "ИИ"**, flagged three separate times. This is the same entity-matching
pattern flagged in Phase 23.1H (though a different specific bug from the two already fixed this
phase — see technical report §9/§10) — disclosed as a known, recurring, not-yet-fixed limitation,
not a new regression.

**Image**: NO (no eligible candidate attached this send — text-only).

**Final Telegram card** (as actually sent, `send_message`, message_id 79):

> 📰 AI · 2026-08-09
> Доказательство заняло 30 минут, проверка — 5 дней. Как ИИ закрыл задачу теории связи
>
> **Доказательство заняло 30 минут, проверка — пять дней: ИИ взялся за задачу теории связи**
>
> GPT выдала первое доказательство задачи, остававшейся открытой с 2001 года, примерно за 30
> минут. Но на превращение ответа модели в текст, который человек смог бы проверить построчно,
> ушло пять дней.
>
> История показывает важное ограничение применения ИИ в науке: найти возможную идею или
> доказательство модель может намного быстрее, чем исследователь способен подтвердить его
> корректность. Поэтому узким местом становится не только поиск решения, но и его формализация,
> разбор и проверка.
>
> По словам Папаилиопулоса, модели помогли закрыть давний открытый вопрос теории связи. При этом
> доступные сведения не показывают, какую именно роль сыграла Claude Fable 5 и выдала ли она
> самостоятельное доказательство. Главный практический результат пока связан не со скоростью
> получения ответа, а с разрывом между генерацией и проверкой: около 30 минут против пяти дней
> или примерно недели.
>
> [🔗 Источник]

Body length: 879 characters, 3 paragraphs (MAJOR's own "may reach ~900 only when the additional
information is genuinely important" — this piece uses 3 distinct facts: what happened, the
verification-gap significance, and the material uncertainty about which model actually did the
work, each earning its place).

**HUMAN VERDICT:**
[ ] Publishable as-is
[ ] Good topic, too long
[ ] Good topic, too technical
[ ] Duplicate
[ ] Bad topic
[ ] Bad image
[ ] Fact issue
[ ] Other

---

## Summary

| # | Treatment | Story | Duplicate blocked? | Image | Fact Safety (shadow) | Chars | Paragraphs |
|---|---|---|---|---|---|---|---|
| 1 | MAJOR | none (no link) | No | NO | block (3× "ИИ" entity false positive) | 879 | 3 |

**Only 1 of 5 targeted posts delivered this run** — disclosed honestly per the phase brief's own
explicit instruction not to lower thresholds to manufacture volume. See
`docs/phase23_1i_live_editorial_hardening_report.md` for the full analysis of why the pool was
thin (§14), why Story Memory shadow still observed zero real activity despite being correctly
wired this run (§5), and the two prior Phase 23.1H posts' worth of additional real evidence this
phase's fixes were validated against offline (§8/§13, Armenia pair + 5 Phase 23.1F/H stories).
