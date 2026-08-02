# Phase 17 M6 — Human Acceptance Packet

12 representative cases from the real, deterministic M6 integrated-validation backtest
(`scripts/phase17_m6_integrated_validation_backtest.py`, `scripts/_phase17_m6_backtest_results.json`)
— **all automated/deterministic**, zero LLM calls, zero human review performed as part of
generating this packet. Every quality judgment (GOOD/ACCEPTABLE/preference) referenced below is
**quoted verbatim from M3's/M4's own already-completed real manual review**
(`scripts/_phase17_m3_manual_ab_evaluation.json` / `scripts/_phase17_m4_manual_abc_evaluation.json`)
— never a new opinion invented for this packet. This document is for a human editor's own final
read before any cutover decision — not a substitute for one.

No secrets, no full raw source dumps — candidate titles and decision metadata only.

| draft_id | M4 candidate title | overall_decision | channel_fit | completeness | fact_safety | source | delivery | blocking / review reasons |
|---|---|---|---|---|---|---|---|---|
| `fa60525c` | Netflix заплатила $500 млн за права на «Ходячих мертвецов» | **REJECT_RECOMMENDED** | REJECT | REVIEW | review | partial | photo_caption | `channel_relevance_reject` — the Netflix/Walking Dead regression case M2 already flagged REJECT on relevance grounds (off-topic for an AI/tech channel); quality itself is GOOD per M3's own manual note, but relevance and quality are separate dimensions and must not be conflated |
| `8ef14299` | Сведения об ИИ-инструменте исчезли после запроса журналистов | REVIEW_REQUIRED | ACCEPT | REVIEW | pass | partial | unknown | `completeness_review` only — Fact Safety clean |
| `dfca74b1` | CEO Nvidia убеждает: ИИ не уничтожает рабочие места | REVIEW_REQUIRED | ACCEPT | REVIEW | review | partial | unknown | `fact_safety_review`, `completeness_review` |
| `cc5dcb84` | В школах Татарстана откроются бесплатные кружки по ИИ | REVIEW_REQUIRED | REVIEW | REVIEW | review | partial | unknown | `channel_relevance_review`, `fact_safety_review`, `completeness_review` — three independent REVIEW signals stacking, worth a closer human look |
| `44381b14` | ЕС усиливает давление на TikTok из-за безопасности несовершеннолетних | REVIEW_REQUIRED | REVIEW | REVIEW | review | partial | unknown | same three-signal REVIEW stack as `cc5dcb84` |
| `7352db1a` | UMC расширит мощности в Сингапуре и на Тайване | REVIEW_REQUIRED | ACCEPT | REVIEW | **pass** | sufficient | unknown | `completeness_review` only — one of M4.1's own 2 disclosed Fact Safety false positives, confirmed fixed here (calibrated `pass`, was raw `fail`) |
| `5c856b45` | Situational Awareness продал основную часть портфеля Citadel | REVIEW_REQUIRED | ACCEPT | REVIEW | review | sufficient | unknown | `fact_safety_review`, `completeness_review` |
| `7bca7a5b` | Дуров попал в перечень Росфинмониторинга | REVIEW_REQUIRED | REVIEW | **NOT_READY** | review | partial | unknown | `completeness_not_ready` (main-fact coverage miss, §23 of the M5 report's own disclosed matching gap) — a real, sensitive-topic case (real named individual, single-source claim) worth explicit human attention regardless of the automated verdict |
| `b9eb8450` | Вычисления могут подорожать более чем в 10 раз | REVIEW_REQUIRED | ACCEPT | REVIEW | pass | sufficient | unknown | `completeness_review` — the one case M4's own report (§23) already disclosed as `M3_BEST` (M4 candidate less thorough than M3 here); the automated gate independently flags the same missing-uncertainty-item gap |
| `d9c0b32c` | Мужчина требует миллионы после выстрела полиции в деле о swatting | **INSUFFICIENT_SOURCE** | REVIEW | INSUFFICIENT_SOURCE | review | headline_only | unknown | `insufficient_source_honestly_handled` — thin/headline-only source, candidate handled it honestly (M4.1's own manual review confirmed no fabrication) |
| `073437a9` | Непроверенное утверждение о прототипе OpenAI | **INSUFFICIENT_SOURCE** | REVIEW | INSUFFICIENT_SOURCE | review | headline_only | unknown | same pattern — explicitly framed as an unverified claim in its own title |
| `b0d0f1f3` | Безопасность Tile может облегчать сталкинг — но деталей пока нет | **INSUFFICIENT_SOURCE** | REVIEW | INSUFFICIENT_SOURCE | pass | headline_only | unknown | one of M0's own originally-disclosed headline-rewrite baseline cases — the M4 candidate instead routes to INSUFFICIENT_SOURCE, not a hidden rewrite defect |

## Reading notes for the human editor

- **Zero `READY_FOR_EDITOR` verdicts appear anywhere in the full 333-case backtest** (269 baseline
  + 32 M3 + 32 M4), not just this 12-case sample — see
  `docs/phase17_m6_integrated_editorial_validation_report.md` §9/§17 for the full, honest
  breakdown and root-cause analysis. Every case in this packet is `REVIEW_REQUIRED`,
  `INSUFFICIENT_SOURCE`, or `REJECT_RECOMMENDED` — this reflects the gate being deliberately
  conservative (inherited from M5's own disclosed tuning gap), not that every candidate is
  actually bad; `dfca74b1`/`5c856b45`/`7352db1a` etc. were independently rated GOOD quality by
  M3's/M4's own real manual review.
- `delivery_mode: unknown` for most rows reflects `image_intelligence_mode` being off by default
  in production for these historical drafts — a real data-availability gap, not a formatting
  defect (caption-fit itself is 100% correct among the cases where image state *is* known, §9).
- `fa60525c` is the one case in this packet requiring explicit confirmation that REJECT is
  correct human judgment too — the automated relevance REJECT should be spot-checked once before
  any cutover that could act on it (M6 has no enforcement of its own; this is advisory only).
