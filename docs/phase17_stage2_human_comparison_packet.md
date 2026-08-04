# Phase 17 Stage 2 — Human Comparison Packet

**Source of truth: `scripts/_phase17_stage2_candidate_results.json` (this session's real live run,
2026-08-04) and a deterministic (zero-LLM-call) `EditorialCompletenessAssessment` recompute
(`scripts/_phase17_stage2_completeness_check.json`) run against the same baseline/candidate texts.**
Baseline and candidate text below are reproduced verbatim, byte-for-byte from those artifacts —
nothing paraphrased, nothing summarized. No `ContentDraft` was modified to produce this packet; the
candidate text was generated separately and stored only in the local artifact above.

4 unique Stage 1 cases, matching `docs/phase17_stage1_human_acceptance_result.md`. The duplicate
delivery (`17389223`, same underlying story as `847618cd`) is excluded, per your own selection of
`847618cd` as the kept case.

One important disclosed limitation before you read further: the completeness scores below were
recomputed **without** the M5 calibrated Fact-Safety criterion folded in (`calibrated_fact_safety`
passed as `None` — that pipeline needs inputs this script doesn't build), so `unsupported_claims_absent`
shows as `UNKNOWN` (score 0.5) in every completeness assessment rather than a real pass/fail. **The
authoritative fact-safety signal for this packet is the `CandidateFactSafetyAudit` comparison in
section D/E** (the same deterministic, zero-LLM audit M4/M4.1 already use) — not the completeness
score's own placeholder criterion.

---

## Case 1 — `2d35bad8` (AI — NOT_READY at Stage 1)

### A. Source evidence summary
Google made it possible, for one day, to spoof satellite imagery (per an NYT article, RSS-fed via
Google News — the RSS payload is only the headline/attribution, no body text). No detail is
available on the mechanism, timeframe, or how Google resolved it. Source sufficiency: partial
(`below_sufficient_threshold`).

### B. Baseline text (production, unchanged)
> **Google на один день упростил подделку спутниковых снимков**
>
> Как сообщает The New York Times, кратковременная уязвимость или функция Google позволила легко
> создавать поддельные спутниковые изображения. Ситуация вновь поднимает вопросы доверия к
> визуальным доказательствам и рисков дезинформации. Детали механизма и масштаба требуют
> дополнительной проверки.

(35 words)

### C. Candidate text (Stage 2, never sent, never written to ContentDraft)
> **Google на один день упростил создание поддельных спутниковых снимков**
>
> The New York Times сообщает, что в течение одного дня Google сделал простым создание поддельных
> спутниковых изображений. Это единственный подтверждённый факт в предоставленных материалах: не
> уточняется, как именно работал механизм и какие инструменты или функции были задействованы.
>
> История поднимает вопросы о доверии к визуальным доказательствам, информационной безопасности и
> риске дезинформации. При этом неизвестны точные временные рамки, масштаб проблемы, число
> затронутых пользователей и то, как Google мог её устранить. Для оценки события нужны
> дополнительные сведения и реакция компании.

(77 words)

### D. Baseline assessments
- Completeness (deterministic recompute): **NOT_READY**, score 0.500, 3 required criteria FAIL
  (`headline_fact_covered`, `what_next_covered`, `uncertainty_covered`) — matches Stage 1's own
  documented failing set exactly.
- Headline-rewrite risk: **low**. Filler: none detected. Repetition: none detected.
- CandidateFactSafetyAudit: **pass**, 1 supported claim, 0 flags.

### E. Candidate assessments
- Completeness (deterministic recompute): **REVIEW**, score 0.682, 1 required criterion FAIL
  (`what_next_covered`) — `headline_fact_covered` and `uncertainty_covered` now PASS.
- Headline-rewrite risk: **low**. Filler: none detected. Repetition: none detected.
- CandidateFactSafetyAudit: **pass**, 1 supported claim, 0 flags — same clean result as baseline.

### F. Cost
1 call, `gpt-5.6-luna`, reasoning_effort=low, 1729 input / 316 output (134 reasoning) tokens,
finish_reason=`stop` (no truncation), **$0.003625**.

### G. Human review form

Editorial preference:
[ ] Baseline
[ ] Candidate
[ ] Tie

Factual accuracy:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Completeness:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Clarity:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Headline strength vs evidence:
[ ] Safe
[ ] Too strong
[ ] Too weak

Candidate decision:
[ ] Approve
[ ] Minor edit
[ ] Major rewrite
[ ] Reject

Failure reasons:
[ ] Fabrication
[ ] Unsupported explanation
[ ] Lost key fact
[ ] Too vague
[ ] Too long
[ ] Too short
[ ] Repetitive
[ ] Overconfident headline
[ ] Other

Human notes:
____________________________

---

## Case 2 — `12ce8e52` (STARTUPS — INSUFFICIENT_SOURCE at Stage 1)

### A. Source evidence summary
The entire source content **is** the headline: "EU rules on AI models become enforceable. What's
going to change?" (`event_content == event_title`, no body text at all). No details on which
rules, timing, affected models, or practical impact. Source sufficiency: `headline_only`.

### B. Baseline text (production, unchanged)
> **Правила ЕС для моделей ИИ становятся обязательными**
>
> Нормы ЕС для моделей искусственного интеллекта переходят от требований к обязательному
> исполнению. Для AI-стартапов это может повлиять на запуск продуктов и соблюдение требований, но
> детали о сроках, затронутых моделях и последствиях пока не уточнены.

(34 words)

### C. Candidate text (Stage 2, never sent, never written to ContentDraft)
> **Правила ЕС для моделей ИИ становятся обязательными**
>
> Правила ЕС, касающиеся моделей искусственного интеллекта, переходят к обязательному исполнению.
> Для стартапов масштаб изменений пока определить нельзя: не уточнены содержание норм, сроки
> применения, круг затронутых моделей и возможные санкции. Это предварительное обновление; перед
> полноценным разбором нужно уточнить эти детали и практические последствия для компаний.

(44 words — same headline as baseline, unchanged)

### D. Baseline assessments
- Completeness (deterministic recompute): **INSUFFICIENT_SOURCE**, score 0.500, 3 required
  criteria FAIL (`why_it_matters_covered`, `what_next_covered`, `uncertainty_covered`) — matches
  Stage 1's own documented failing set.
- Headline-rewrite risk: **not_applicable** (thin-source cases are never scored on rewrite risk,
  by design). Filler: none detected. Repetition: none detected.
- CandidateFactSafetyAudit: **review**, 1 supported claim, 3 flags (`uncertain:Правила ЕС`,
  `unsupported:Нормы ЕС`, `unsupported:Для AI-стартапов`), severity medium.

### E. Candidate assessments
- Completeness (deterministic recompute): **INSUFFICIENT_SOURCE**, score 0.800, **0 required
  criteria FAIL** — all 3 baseline failures now pass or partial.
- Headline-rewrite risk: **not_applicable**. Filler: none detected. Repetition: none detected.
- CandidateFactSafetyAudit: **review**, 1 supported claim, 2 flags (both
  `uncertain:Правила ЕС`), severity **low** (down from baseline's medium) — fewer and lower-severity
  flags than baseline.

### F. Cost
1 call, `gpt-5.6-luna`, reasoning_effort=low, 1597 input / 223 output (106 reasoning) tokens,
finish_reason=`stop` (no truncation), **$0.002935**.

### G. Human review form

Editorial preference:
[ ] Baseline
[ ] Candidate
[ ] Tie

Factual accuracy:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Completeness:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Clarity:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Headline strength vs evidence:
[ ] Safe
[ ] Too strong
[ ] Too weak

Candidate decision:
[ ] Approve
[ ] Minor edit
[ ] Major rewrite
[ ] Reject

Failure reasons:
[ ] Fabrication
[ ] Unsupported explanation
[ ] Lost key fact
[ ] Too vague
[ ] Too long
[ ] Too short
[ ] Repetitive
[ ] Overconfident headline
[ ] Other

Human notes:
____________________________

---

## Case 3 — `847618cd` (SOFTWARE — REVIEW at Stage 1; the kept case from the duplicate-story pair)

### A. Source evidence summary
Bottleneck Labs gave an autonomous agent ("Saul", on "GPT-5.6 Sol") real business infrastructure
(a live iOS app, a real bank account, a computer with full access) for 24 hours. In that time:
320.7M input tokens, 1,129 tool calls, 5 new users acquired, $0 revenue, $99.50 spent (balance
$350→$250.50), estimated business value down $447. The source article itself questions whether the
agent or the experiment's own design is really what "failed." Source sufficiency: sufficient.

### B. Baseline text (production, unchanged)
> **Автономный ИИ-агент протестировал реальный бизнес — и ушёл в минус**
>
> В эксперименте Bottleneck Labs агент Saul получил на 24 часа доступ к iOS-приложению,
> банковскому счёту и бизнес-инфраструктуре. Он привлёк пять пользователей, но не заработал денег:
> со счёта ушло $99,50, а оценка бизнеса снизилась на $447. Заявления о лжи и спаме пока не
> подтверждены представленными данными.

(45 words)

### C. Candidate text (Stage 2, never sent, never written to ContentDraft)
> **Автономный ИИ-агент за сутки привлек пять пользователей, но не заработал денег**
>
> В конце июля исследовательская команда Bottleneck Labs опубликовала отчет об эксперименте с
> автономным ИИ-агентом. Агент Saul работал на модели GPT-5.6 Sol и получил на 24 часа доступ к
> настоящему бизнесу: действующему iOS-приложению, банковскому счету с реальными деньгами и
> компьютеру с полным доступом.
>
> За время теста Saul привлек пять новых пользователей, но не заработал денег. Он использовал
> 320,7 млн входных токенов и выполнил 1129 вызовов инструментов. Со счета ушло $99,50: баланс
> снизился с $350 до $250,50. Кроме того, общая стоимость бизнеса уменьшилась на $447. Эти
> результаты указывают на ограниченную практическую эффективность агента в данном эксперименте:
> привлеченные пользователи не привели к зафиксированному заработку, а расходы сопровождались
> снижением оценки бизнеса.
>
> При этом представленный фрагмент не подтверждает конкретные утверждения о лжи или спаме,
> вынесенные в заголовок. Также не раскрыты методика расчета общей стоимости бизнеса, причины ее
> снижения и то, были ли пять новых пользователей активными или платящими. Поэтому по этим данным
> нельзя однозначно утверждать, что именно потерпело неудачу — агент или сам эксперимент. Для
> оценки надежности и безопасности таких систем нужны уточнения о действиях Saul и методике
> измерений.

(174 words — the longest candidate of the 4, closest to the ideal 220–320-word `explainer` range,
though still below it)

### D. Baseline assessments
- Completeness (deterministic recompute): **REVIEW**, score 0.591, 2 required criteria FAIL
  (`what_next_covered`, `structure_adequate`).
- Headline-rewrite risk: **low**. Filler: none detected. Repetition: none detected.
- CandidateFactSafetyAudit: **review**, 3 supported claims, 1 flag
  (`unsupported:Автономный ИИ-агент`), severity **medium**.

### E. Candidate assessments — ⚠ the one case with a real flagged concern
- Completeness (deterministic recompute): **REVIEW**, score 0.773 (higher than baseline), 1
  required criterion FAIL (`what_next_covered`) — `structure_adequate` now passes (3 paragraphs,
  matching the `explainer` format's target).
- Headline-rewrite risk: **low**. Filler: none detected. Repetition: none detected.
- **CandidateFactSafetyAudit: status escalates to FAIL, severity HIGH** (up from baseline's
  review/medium), 6 supported claims but **3 unsupported-claim flags**:
  `unsupported:320,7 млн` (a **numeric** flag — the "320.7M input tokens" figure, which *is*
  present in the source article per section A above, so this may be the same literal-text-matching
  gap already disclosed in the M5 report rather than a true fabrication — **this needs your read,
  not an automated one**), `unsupported:Автономный ИИ-агент` and `unsupported:Агент Saul` (entity
  flags, same pattern as baseline's own flag), plus a `causal_connector` flag on the candidate's
  own final-paragraph sentence weighing "did the agent or the experiment fail." **This is the
  single most important row in this packet — do not approve this candidate without personally
  checking whether the 320.7M-token figure and the two entity flags are genuine unsupported claims
  or matcher artifacts.**

### F. Cost
1 call, `gpt-5.6-luna`, reasoning_effort=low, 2148 input / 472 output (98 reasoning) tokens,
finish_reason=`stop` (no truncation), **$0.00498**.

### G. Human review form

Editorial preference:
[ ] Baseline
[ ] Candidate
[ ] Tie

Factual accuracy:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Completeness:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Clarity:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Headline strength vs evidence:
[ ] Safe
[ ] Too strong
[ ] Too weak

Candidate decision:
[ ] Approve
[ ] Minor edit
[ ] Major rewrite
[ ] Reject

Failure reasons:
[ ] Fabrication
[ ] Unsupported explanation
[ ] Lost key fact
[ ] Too vague
[ ] Too long
[ ] Too short
[ ] Repetitive
[ ] Overconfident headline
[ ] Other

Human notes:
____________________________

---

## Case 4 — `ac1f1ff5` (AI — REVIEW at Stage 1)

### A. Source evidence summary
A Chinese AI model, "Kimi K3" (claimed 2.8 trillion parameters), had its weights published in open
access. The headline itself claims the model's cost is one-third that of top competitors — no
pricing, competitor names, benchmarks, or license terms are given. Source sufficiency: partial
(`below_sufficient_threshold`).

### B. Baseline text (production, unchanged)
> **Kimi K3: 2,8 трлн параметров и открытые веса**
>
> Китайская ИИ-модель Kimi K3 стала доступна в открытом доступе с опубликованными весами.
> Источник заявляет, что её стоимость втрое ниже, чем у топовых конкурентов. Данные о цене,
> производительности, лицензии и условиях использования требуют проверки.

(33 words)

### C. Candidate text (Stage 2, never sent, never written to ContentDraft)
> **Kimi K3 с 2,8 трлн параметров вышла в открытый доступ**
>
> Китайская модель искусственного интеллекта Kimi K3 стала доступна в открытом доступе: для неё
> опубликованы «веса». В материалах также заявлено, что модель содержит 2,8 трлн параметров, а её
> стоимость втрое ниже стоимости топовых конкурентов. Источником этой информации указан ixbt.com.
>
> Открытая публикация весов и заявленный масштаб могут усилить конкуренцию на рынке ИИ и расширить
> доступ к крупной модели. Но пока это именно заявления источника: не раскрыты методика расчёта
> стоимости, конкретные конкуренты, характеристики модели, условия доступа, происхождение весов и
> лицензия. Также неизвестна дата публикации. Перед более широкими выводами стоит проверить эти
> данные, а также производительность Kimi K3 и корректность сравнения цены.

(98 words)

### D. Baseline assessments
- Completeness (deterministic recompute): **REVIEW**, score 0.636, 1 required criterion FAIL
  (`uncertainty_covered`).
- Headline-rewrite risk: **medium** (the one baseline case above low, per Stage 1's own packet).
  Filler: none detected. Repetition: none detected.
- CandidateFactSafetyAudit: **review**, 1 supported claim, 1 flag
  (`unsupported:Китайская ИИ-модель Kimi K3`), severity medium.

### E. Candidate assessments
- Completeness (deterministic recompute): **REVIEW**, score 0.818 (highest of the 4 candidates),
  **0 required criteria FAIL**.
- Headline-rewrite risk: **low** (down from baseline's medium — the candidate explicitly attributes
  the claims to the source and adds real caveats, reducing rewrite risk).
- CandidateFactSafetyAudit: **review**, 3 supported claims (up from baseline's 1), 1 flag
  (`uncertain:ИИ` — a much softer, lower-specificity flag than baseline's own), severity **low**
  (down from baseline's medium).

### F. Cost
1 call, `gpt-5.6-luna`, reasoning_effort=low, 1908 input / 342 output (110 reasoning) tokens,
finish_reason=`stop` (no truncation), **$0.00396**.

### G. Human review form

Editorial preference:
[ ] Baseline
[ ] Candidate
[ ] Tie

Factual accuracy:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Completeness:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Clarity:
[ ] Baseline better
[ ] Candidate better
[ ] Equal

Headline strength vs evidence:
[ ] Safe
[ ] Too strong
[ ] Too weak

Candidate decision:
[ ] Approve
[ ] Minor edit
[ ] Major rewrite
[ ] Reject

Failure reasons:
[ ] Fabrication
[ ] Unsupported explanation
[ ] Lost key fact
[ ] Too vague
[ ] Too long
[ ] Too short
[ ] Repetitive
[ ] Overconfident headline
[ ] Other

Human notes:
____________________________

---

## Summary table

| Case | Category | Baseline words | Candidate words | Baseline completeness | Candidate completeness | Baseline Fact Safety | Candidate Fact Safety | Cost |
|---|---|---|---|---|---|---|---|---|
| `2d35bad8` | AI | 35 | 77 | NOT_READY (0.500) | REVIEW (0.682) | pass | pass | $0.003625 |
| `12ce8e52` | STARTUPS | 34 | 44 | INSUFFICIENT_SOURCE (0.500) | INSUFFICIENT_SOURCE (0.800) | review (medium) | review (low) | $0.002935 |
| `847618cd` | SOFTWARE | 45 | 174 | REVIEW (0.591) | REVIEW (0.773) | review (medium) | **fail (high)** ⚠ | $0.00498 |
| `ac1f1ff5` | AI | 33 | 98 | REVIEW (0.636) | REVIEW (0.818) | review (medium) | review (low) | $0.00396 |

**Read `847618cd` first** — it's the only case where the candidate's deterministic Fact Safety
status is worse than baseline's, and the only one where "approve as-is" would need your explicit
factual sign-off on the flagged 320.7M-token figure and the two entity-phrase flags before any
`editorial_preference` is recorded. `editorial_preference` for all 4 cases is currently
`not_yet_reviewed` — nothing here is a recommendation, only a comparison.
