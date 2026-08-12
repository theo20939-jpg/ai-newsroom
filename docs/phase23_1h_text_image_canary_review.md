# Phase 23.1H — Text + Image Live Canary: Human Review Packet

**Run**: 2026-08-09, 22:40–22:47 (≈7.5 minutes wall clock). Route: `chat_id=-1004297182444`,
`message_thread_id=2` (verified programmatically before any send). Stop reason: `nothing_eligible`
after 6 bounded rounds (21 events analyzed, all remaining candidates below the score/treatment
gate). Cost: **$0.118788** (well under the $1.00 cap). **2 of a target 5** posts delivered — the
target was not reached because the currently fresh-eligible pool was thin at the time of the run
(disclosed at preflight, run authorized to proceed anyway) — not because of a defect.

Review each card below against the real Telegram messages sent to the channel (message_id 74 and
75). Verdicts are intentionally left blank for human review.

---

## NEWS #1

**Treatment**: STANDARD (reason: "medium significance (7.0)")

**Original headline**: Крупнейшая в СНГ ИИ-фабрика NVIDIA появится в Армении — Firebird
развернула 15 из 300 МВт

**Source**: 3dnews.ru (`https://3dnews.ru/1146526`), category GADGETS

**Intelligence**: significance 7/10 — "заявленные в заголовке 15 из 300 МВт исследовательскими
фактами не подтверждены, а лидерство объекта не имеет независимой проверки." Recommendation:
publish as a notable infrastructure story, but attribute the "largest in the CIS" claim to NVIDIA
and don't present 15/300 MW as independently confirmed.

**Fact Safety** (shadow mode, advisory only — did **not** block this send): `status=block`,
`highest_risk=high`, 23 claims checked, 17 supported, 6 unsupported (all 6 are named-entity
mentions — "В Армении", "ИИ-ЦОД Firebird" ×2, "В Раздане", "NVIDIA DSX", "TrimCooler" — flagged
`unsupported` rather than any numeric/factual claim). **Flag for review**: this looks like Fact
Safety V1 being oversensitive to proper nouns/entities rather than catching a genuine factual
error — worth a human read of whether these 6 "unsupported" entity findings are false positives.

**Image**: **YES**

**Image source/domain**: `cdn.3dnews.ru` (the original article's own illustration, not a stock/
generic asset) — 800×545, `quality_status=accepted`, `rank=1`, the only eligible candidate out of
3 discovered.

**Final Telegram presentation** (as actually sent, `send_photo`, message_id 74):

> [image: cdn.3dnews.ru site-tour-aerial illustration, 800×545]
>
> 📰 GADGETS · 2026-08-09
> Крупнейшая в СНГ ИИ-фабрика NVIDIA появится в Армении — Firebird развернула 15 из 300 МВт
>
> **В Армении запустили первую очередь ИИ-ЦОД Firebird на платформе NVIDIA**
>
> Американская неооблачная компания Firebird объявила о запуске в Раздане первой очереди
> дата-центра для искусственного интеллекта, построенной за полгода.
>
> Проект показывает, как ИИ-инфраструктура переходит от отдельных серверных комплексов к
> специализированным фабрикам, где плотность размещения GPU, электроснабжение и охлаждение
> проектируются как единая система. Для регионального рынка важен и сам темп строительства:
> первая очередь была готова за шесть месяцев. Однако лидерство объекта в СНГ пока остается
> заявлением NVIDIA, а не результатом независимого сравнения.
>
> Не раскрыты мощность объекта, число установленных GPU, стоимость проекта и практические
> сценарии его использования.
>
> [🔗 Источник]

Caption length: 889 characters (fits Telegram's 1024-code-unit photo-caption limit).

**HUMAN VERDICT:**
[ ] Publishable
[ ] Needs minor edit
[ ] Bad topic
[ ] Bad text
[ ] Bad image
[ ] Other

---

## NEWS #2

**Treatment**: BRIEF (reason: "medium significance (6.0) with weak evidence")

**Original headline**: В Армении открыли один из самых больших дата-центров в Европе - Zerkalo

**Source**: Google News RU aggregator link (original: Zerkalo), category AI

**Intelligence**: significance 6/10 — "пока неясно, какие вычислительные мощности, инвестиции и
проекты за этим стоят." Recommendation: hold for monitoring, publish only a short note after
verifying the datacenter's name, location, size, power, owner, and intended AI workloads — explicitly
do not draw market-impact conclusions without that data.

**Fact Safety** (shadow mode, advisory only — did **not** block this send): `status=block`,
`highest_risk=high`, 2 claims checked, 1 supported, 1 unsupported (the single word "ИИ" flagged as
an unsupported entity). Same disclosed pattern as NEWS #1 — likely an entity-matching
oversensitivity, not a substantive factual problem, but flagged for human read.

**Image**: **NO**

**Image source/domain**: n/a — 2 candidates were discovered, both correctly rejected: a 300×300
Google-hosted generic thumbnail (`lh3.googleusercontent.com`, `relevance_status=ineligible`) and a
second, dimensionless/technically-failed candidate (also `ineligible`). Neither cleared the
existing `eligible_for_editorial` gate, so this card correctly fell back to text-only rather than
attaching a generic aggregator thumbnail.

**Final Telegram presentation** (as actually sent, `send_message`, message_id 75):

> 📰 AI · 2026-08-09
> В Армении открыли один из самых больших дата-центров в Европе - Zerkalo
>
> **В Армении открыли один из крупнейших дата-центров Европы**
>
> Армения заявила об открытии дата-центра, который относят к числу крупнейших в Европе. Однако
> ключевые параметры объекта пока не раскрыты.
>
> Крупный вычислительный объект может усилить региональную инфраструктуру для ИИ, облачных
> сервисов и других цифровых нагрузок. Но без информации о мощности, инвестициях и проектах
> оценивать его влияние на рынок пока преждевременно.
>
> [🔗 Источник]

Text length: 534 characters (fits the 4096-code-unit plain-message limit comfortably; BRIEF
treatment target is ~200-450 visible characters — the body itself is 369 characters, matching the
target, with the header/title lines accounting for the remainder).

**HUMAN VERDICT:**
[ ] Publishable
[ ] Needs minor edit
[ ] Bad topic
[ ] Bad text
[ ] Bad image
[ ] Other

---

## Summary

| # | Treatment | Image | Fact Safety (shadow) | Source button | Chars |
|---|---|---|---|---|---|
| 1 | STANDARD | YES (cdn.3dnews.ru, original) | block (6 entity findings) | ✓ | 889 (caption) |
| 2 | BRIEF | NO (2 candidates, both correctly rejected) | block (1 entity finding) | ✓ | 534 (text) |

**Overall note for review**: both delivered posts were flagged `block` by Fact Safety under
`shadow` mode. Since shadow mode is advisory-only by design, this correctly did not suppress
either send — but the pattern (both blocks driven entirely by named-entity "unsupported" findings,
zero numeric/factual findings) is worth a deliberate human judgment call: is Fact Safety V1 too
aggressive on entity matching, or are these genuine gaps worth tightening evidence requirements
for before considering `fact_safety_mode=enforce`? This is a pre-existing Fact Safety V1
characteristic, not something Phase 23.1H changed — flagged here because this is the first time
this session Fact Safety's real shadow output was reviewed alongside two delivered posts side by
side.
