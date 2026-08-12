# Phase 23.1J.1 — Copywriting V8.1 / Final Simplified NEWS Format: Human Review

**Method**: offline golden replay only — the real V8.1 Copywriting capability was called directly
against the same 5 real, already-triaged NewsEvent rows used in Phase 23.1J (reusing their real,
already-persisted Research/Intelligence output), with `copywriting_prompt_version=8.1` set
in-process only. **No Telegram sends, no live canary, no workers started.** Cost: **$0.020424**
(5 Copywriting calls only). `v6`/`v7`/`v8` prompt files are untouched and unmodified.

## What changed from V8

- Removed the `expandable_details` concept entirely from V8.1's own schema — the final structure
  is HEADLINE + exactly ONE main-body paragraph + OPTIONAL ending, nothing else. (V8's own
  expandable-blockquote machinery is kept, untouched, for a possible future format — never invoked
  for V8.1 output.)
- `main_body` is enforced as exactly one paragraph both by the prompt ("ABSOLUTE rule") and, as a
  safety net, by the presentation layer (`_collapse_to_one_paragraph()` — collapses any accidental
  internal paragraph break the model might still produce; never drops content, never truncates).
- Tighter soft/absolute ceilings: BRIEF 150–250/350, STANDARD 250–400/500, MAJOR 350–600/750
  (headline excluded from all counts).
- The NINJA PULSE footer is built but **disabled by default** — `render_v81_news_card_html()`'s
  `include_ninja_pulse_footer` parameter defaults to `False` this phase.
- One infrastructure fix needed to even create the file: `prompts/copywriting/v8.1.yaml`'s literal
  filename would have crashed the entire prompt-loading system at boot (the existing version
  parser only accepted plain integers). Extended `integrations/prompts/file_repository.py` to
  support one optional minor-version level ("8.1"), test-first, with zero behavior change for
  every existing integer-versioned prompt (v4–v8), verified against the real `prompts/` directory.

---

## 1. Armenia / Firebird / NVIDIA datacenter

**ORIGINAL SOURCE TITLE**: Крупнейшая в СНГ ИИ-фабрика NVIDIA появится в Армении — Firebird
развернула 15 из 300 МВт

**TREATMENT**: STANDARD

**FINAL TELEGRAM REPRESENTATION:**

> **В Армении запустили первую очередь ИИ-центра Firebird на платформе NVIDIA**
>
> Американская компания Firebird запустила в Раздане, Армения, первую очередь ИИ-центра обработки
> данных, построенную за полгода. Объект работает на платформе NVIDIA DSX AI Factory и использует
> серверы Dell, а энергетическую инфраструктуру и охлаждение предоставили Schneider Electric и
> Vertiv. По утверждению NVIDIA, центр позиционируется как крупнейшая ИИ-фабрика в СНГ, а сама
> платформа позволяет разместить до 40% больше GPU на той же площади.
>
> [🔗 Источник]

Character count: 445. Paragraphs: 1 (single, as required). No ending (the model folded the
uncertainty into an ending field that the presentation layer then evaluated - see note below).

**⚠️ Flag for reviewer — the main finding of this replay**: without an `expandable_details` field
to offload optional technical detail into, the model packed "NVIDIA DSX AI Factory," "серверы
Dell," "Schneider Electric и Vertiv," and "40% больше GPU" all directly into the single main-body
paragraph — noticeably more technical/dense than V8's own version of this same story, which kept
main_body to 373 characters by routing exactly this content into its (now-removed) expandable
block. 445 characters is within STANDARD's 500 absolute ceiling, but above the 400 normal target,
and arguably violates the "DELETE BEFORE EXPLAINING" rule (vendor names like Schneider
Electric/Vertiv do not change why this story matters to the target reader). This is disclosed
prominently, not hidden — a real product tension between "no overflow bucket for detail" and
"delete detail that isn't essential" that the prompt's own wording did not fully resolve this run.

**HUMAN VERDICT:**
[ ] Perfect
[ ] Good
[ ] Still too long
[ ] Too short / lost important information
[ ] Too technical
[ ] Bad ending
[ ] Other

---

## 2. Google Pay AI

**ORIGINAL SOURCE TITLE**: Google в Индии внедряет ИИ в Google Pay - PLUSworld

**TREATMENT**: STANDARD

**FINAL TELEGRAM REPRESENTATION:**

> **Google внедряет ИИ в Google Pay в Индии**
>
> Google внедряет искусственный интеллект в Google Pay в Индии. Какие функции получат
> пользователи, когда начнётся запуск и насколько широким он будет, пока не уточняется.
>
> [🔗 Источник]

Character count: 169. Paragraphs: 1. No ending.

Concise and appropriately honest about the story's own thinness (a single sentence stating the
one real caveat, folded directly into the main paragraph rather than as a separate ending this
time) - reads cleanly as one coherent thought.

**HUMAN VERDICT:**
[ ] Perfect
[ ] Good
[ ] Still too long
[ ] Too short / lost important information
[ ] Too technical
[ ] Bad ending
[ ] Other

---

## 3. "Ghost particles" AI story

**ORIGINAL SOURCE TITLE**: Учёные научат искусственный интеллект искать «призрачные частицы»
глубоко под землёй - New-Science.ru

**TREATMENT**: STANDARD (structural comparison only — real Editorial Treatment, unchanged this
phase, classifies this **SKIP** given weak `HEADLINE_ONLY` evidence; would not be delivered in
production regardless of text quality.)

**FINAL TELEGRAM REPRESENTATION:**

> **Учёные обучат ИИ искать «призрачные частицы» глубоко под землёй**
>
> Учёные планируют обучить ИИ искать «призрачные частицы» глубоко под землёй — алгоритмы могут
> помочь находить редкие сигналы в подземных экспериментах. Пока не уточняется, о каких именно
> частицах идёт речь, кто ведёт работу и на какой стадии находится проект.
>
> [🔗 Источник]

Character count: 258. Paragraphs: 1.

**HUMAN VERDICT:**
[ ] Perfect
[ ] Good
[ ] Still too long
[ ] Too short / lost important information
[ ] Too technical
[ ] Bad ending
[ ] Other

---

## 4. AI-created viruses / drug-resistant bacteria

**ORIGINAL SOURCE TITLE**: Искусственный интеллект создает новые вирусы для уничтожения устойчивых
к лекарствам бактерий. - Vietnam.vn

**TREATMENT**: STANDARD (structural comparison only — real Editorial Treatment, unchanged this
phase, classifies this **SKIP**: weak evidence + explicit negative Intelligence recommendation.)

**FINAL TELEGRAM REPRESENTATION:**

> **ИИ якобы создает вирусы против устойчивых к лекарствам бактерий**
>
> Vietnam.vn сообщает о создании с помощью искусственного интеллекта новых вирусов, которые должны
> уничтожать бактерии, устойчивые к лекарствам. Однако подробностей об исследовании, методах и
> результатах нет, поэтому это утверждение пока нельзя считать подтвержденной новостью.
>
> [🔗 Источник]

Character count: 275. Paragraphs: 1.

**HUMAN VERDICT:**
[ ] Perfect
[ ] Good
[ ] Still too long
[ ] Too short / lost important information
[ ] Too technical
[ ] Bad ending
[ ] Other

---

## 5. Stack Overflow read-only mode

**ORIGINAL SOURCE TITLE**: Форум для разработчиков Stack Overflow перевели в режим «только для
чтения» на фоне падения трафика из-за ИИ.

**TREATMENT**: MAJOR

**FINAL TELEGRAM REPRESENTATION:**

> **Stack Overflow перевели в режим «только для чтения» на фоне падения активности**
>
> Форум для разработчиков Stack Overflow перевели в режим «только для чтения»: число новых
> вопросов, по данным источника, сократилось на 98,5% — со 109 тысяч в месяц в ноябре 2022 года до
> 1624 в месяц в 2025 году. Этот спад связывают с распространением ИИ, который меняет способы
> поиска технических ответов и снижает потребность обращаться к форумам.
>
> Связь падения активности именно с ИИ заявлена источником, но не подтверждена отдельной
> методикой.
>
> [🔗 Источник]

Character count: 447 (main body 353 + ending 92). Paragraphs: 2 (one main body + one ending — the
ending correctly survived because it states a genuinely distinct caveat, not a repeat of the main
body's own causal claim).

**HUMAN VERDICT:**
[ ] Perfect
[ ] Good
[ ] Still too long
[ ] Too short / lost important information
[ ] Too technical
[ ] Bad ending
[ ] Other

---

## Summary — V8 vs. V8.1

| # | Story | Treatment | V8 chars/paragraphs | V8.1 chars/paragraphs |
|---|---|---|---|---|
| 1 | Armenia/Firebird | STANDARD | 373 / 2 (+expandable) | 445 / 1 |
| 2 | Google Pay | STANDARD | 250 / 2 | 169 / 1 |
| 3 | Ghost particles | STANDARD* | 356 / 2 | 258 / 1 |
| 4 | AI virus/bacteria | STANDARD* | 283 / 1 | 275 / 1 |
| 5 | Stack Overflow | MAJOR | 391 / 2 | 447 / 2 |

\* Structural comparison only — real Editorial Treatment (unchanged) classifies these two SKIP.

Every V8.1 body is a genuinely single paragraph (the core product requirement of this phase),
confirmed structurally, not just visually. 3 of 5 stories are shorter than their V8 equivalents;
2 (Armenia, Stack Overflow) are modestly longer, both explainable: Armenia because the removed
expandable-details bucket pushed its content into the single main paragraph instead (flagged
above as the primary open question for review), Stack Overflow because its genuinely distinct
ending (methodology caveat) simply adds real length on top of an already-substantive main body.
All 5 stay within their treatment's own absolute ceiling (STANDARD 500, MAJOR 750).
