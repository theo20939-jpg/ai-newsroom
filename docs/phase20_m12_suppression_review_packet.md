# Phase 20 M12 - Suppression Human-Review Packet (Checkpoint 5)

Stratified sample of 73 cases drawn from the Checkpoint 4 same-dataset replay (2026-08-04 to 2026-08-07, 3,774 real events, disposable Postgres) - not all 173 `would_suppress=True` cases, per instruction. **Suppression is NOT enabled anywhere.** Every HUMAN VERDICT checkbox below is blank and must stay that way until a person reviews it - this script never auto-fills them. No suppression precision/recall number should be computed until every verdict below has been filled in.

## SUPPORTING_SOURCE cases (1 cases)

### Case 1

**NEW EVENT**
- event_id: `173417e5-19ee-429b-b707-9b23d9a4719a`
- title: 3 Magnificent Artificial Intelligence (AI) Stocks to Buy Right Now and Hold for the Next Decade - The Motley Fool
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-04T17:00:00+00:00
- short evidence summary: near-identical title (overlap=0.87) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `a49eb0f7-631c-4052-8675-b27e84434966`
- root title: 3 Genius Artificial Intelligence (AI) Stocks to Buy Right Now - The Motley Fool
- previous linked event titles: 3 Genius Artificial Intelligence (AI) Stocks to Buy Right Now - The Motley Fool (Google News: Artificial Intelligence); 3 Magnificent Artificial Intelligence (AI) Stocks to Buy Right Now and Hold for the Next Decade - Yahoo Finance (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: supporting_source
- match_score: 0.688
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: supporting_source + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Remaining CONFIRMATION_ONLY cases (0 cases)

_0 found - every one of the 173 `would_suppress=True` cases is now `delta_classification=no_new_facts`. This fully confirms the Checkpoint 4 delta-engine fix: no case reaches suppression eligibility via the CONFIRMATION_ONLY path anymore in this replay._

## Cases with some distinctive keyword difference (extra scrutiny) (0 cases)

_0 found - structurally guaranteed: `NO_NEW_FACTS` (the only delta classification present in the would_suppress set - see above) requires zero new keywords by definition. No residual 'quiet mismatch' cases (like the Checkpoint 4 romance-walkthrough finding) remain in this replay's suppression-eligible set._

## SEMANTIC_DUPLICATE cases (10 cases)

### Case 2

**NEW EVENT**
- event_id: `b28fcdc9-2229-401c-a894-2dc5f5e838d3`
- title: GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ
- source: Habr: Artificial Intelligence
- category: SOFTWARE
- published_at: 2026-08-04T08:08:46+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `8ce9217b-89de-461f-839a-2f4e2296bba1`
- root title: GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ
- previous linked event titles: GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ (Habr: Machine Learning)
- source list: Habr: Machine Learning
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 3

**NEW EVENT**
- event_id: `dd45d3d3-38d6-4c33-82b0-e70fd1ec3518`
- title: Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-04T09:34:53+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `2a8789b0-e33d-4cbe-b06a-3de6d162d2ac`
- root title: Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле
- previous linked event titles: Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 4

**NEW EVENT**
- event_id: `c402df65-446a-41b2-9c17-3ae302784c87`
- title: Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-04T10:19:49+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `4582496d-f1a9-4e4f-8879-7e8689da590c`
- root title: Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99
- previous linked event titles: Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99 (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 5

**NEW EVENT**
- event_id: `3f78b564-7b07-458d-bf53-e16533f12067`
- title: 460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина
- source: Habr: Artificial Intelligence
- category: SOFTWARE
- published_at: 2026-08-04T11:34:55+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `049b2072-1dc0-4cf0-9a76-bb7b1a45290b`
- root title: 460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина
- previous linked event titles: 460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина (Habr: Machine Learning)
- source list: Habr: Machine Learning
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 6

**NEW EVENT**
- event_id: `e253f772-4c3d-4c98-a5b9-46c6aadabae4`
- title: Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-04T12:59:15+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `a7cd847c-a9bf-4ead-ae56-fca2b52c4d75`
- root title: Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки
- previous linked event titles: Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 7

**NEW EVENT**
- event_id: `7ef97b8a-c78d-4c34-a660-a8d064184394`
- title: The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of
- source: arXiv cs.CV
- category: AI
- published_at: 2026-08-04T13:08:03+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `e029278c-fe6f-4c4b-b201-4a5d45b5398b`
- root title: The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of
- previous linked event titles: The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of (arXiv cs.CL)
- source list: arXiv cs.CL
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 8

**NEW EVENT**
- event_id: `de5f5d78-41a1-4081-ab50-17212428a31e`
- title: Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases
- source: arXiv cs.CL
- category: AI
- published_at: 2026-08-04T14:25:47+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `92d623e4-83f6-4a46-81d1-b37e165219d9`
- root title: Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases
- previous linked event titles: Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 9

**NEW EVENT**
- event_id: `9a070bb8-2260-4575-a3fa-886da4a5d39a`
- title: Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T14:36:44+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `8c562af6-b17c-493f-be09-be7d5852d7d0`
- root title: Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and
- previous linked event titles: Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 10

**NEW EVENT**
- event_id: `8f7d8cc5-d55f-4335-abae-6100e934d8e1`
- title: Chain-of-Thought (CoT) reasoning offers a promising window into model monitoring. However, monitoring relies on
- source: arXiv cs.CL
- category: AI
- published_at: 2026-08-04T14:38:06+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5b2c3325-a6ad-47f3-9d0f-f2f3fff3e833`
- root title: Chain-of-Thought (CoT) reasoning offers a promising window into model monitoring. However, monitoring relies on
- previous linked event titles: Chain-of-Thought (CoT) reasoning offers a promising window into model monitoring. However, monitoring relies on (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 11

**NEW EVENT**
- event_id: `7063c69d-3b81-47db-88e2-d7e80af33f2c`
- title: Masked diffusion language models (MDLMs) enable parallel generation and bidirectional context modeling, but their
- source: arXiv cs.CL
- category: AI
- published_at: 2026-08-04T14:54:14+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `b789b4a5-3277-4fe0-9f73-8ddd3965c408`
- root title: Masked diffusion language models (MDLMs) enable parallel generation and bidirectional context modeling, but their
- previous linked event titles: Masked diffusion language models (MDLMs) enable parallel generation and bidirectional context modeling, but their (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Highest-confidence suppressions (8 cases)

### Case 12

**NEW EVENT**
- event_id: `e54e4a3d-d50d-4e24-aa5c-4004de0c86a2`
- title: Explaining the predictions of neural networks is a central challenge in trustworthy AI. Existing explanation methods,
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T14:57:06+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `c5788c59-79a1-4267-9734-f15292603096`
- root title: Explaining the predictions of neural networks is a central challenge in trustworthy AI. Existing explanation methods,
- previous linked event titles: Explaining the predictions of neural networks is a central challenge in trustworthy AI. Existing explanation methods, (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 13

**NEW EVENT**
- event_id: `79573653-5e56-48c8-89a4-c46e962aa7e5`
- title: Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints,
- source: arXiv cs.CL
- category: AI
- published_at: 2026-08-04T15:11:45+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `35bd41d8-d270-41ff-8eee-079a5c9ef7f9`
- root title: Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints,
- previous linked event titles: Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints, (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 14

**NEW EVENT**
- event_id: `62ba1d86-780e-48cf-ab68-7a3160815c96`
- title: Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints,
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T15:11:45+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `35bd41d8-d270-41ff-8eee-079a5c9ef7f9`
- root title: Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints,
- previous linked event titles: Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints, (arXiv cs.AI); Small language models are often the only option for deployment under tight latency, cost, and on-premises constraints, (arXiv cs.CL)
- source list: arXiv cs.AI, arXiv cs.CL
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 15

**NEW EVENT**
- event_id: `28025417-dc11-43fc-aa64-02ac7cc0e20c`
- title: Developing robust flood assessment models requires high-quality paired satellite imagery, yet such data remain scarce
- source: arXiv cs.AI
- category: AI
- published_at: 2026-08-04T15:30:35+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `206b3c42-ee40-411f-9e72-5de961584db1`
- root title: Developing robust flood assessment models requires high-quality paired satellite imagery, yet such data remain scarce
- previous linked event titles: Developing robust flood assessment models requires high-quality paired satellite imagery, yet such data remain scarce (arXiv cs.CV)
- source list: arXiv cs.CV
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 16

**NEW EVENT**
- event_id: `6481815d-b80a-4f16-b31c-ef5af199433c`
- title: Geospatial and urban applications increasingly require models to compare heterogeneous evidence across street-view
- source: arXiv cs.CV
- category: AI
- published_at: 2026-08-04T15:36:17+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `b68bcea4-712f-4bb0-a689-5e54279aeefb`
- root title: Geospatial and urban applications increasingly require models to compare heterogeneous evidence across street-view
- previous linked event titles: Geospatial and urban applications increasingly require models to compare heterogeneous evidence across street-view (arXiv cs.LG)
- source list: arXiv cs.LG
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 17

**NEW EVENT**
- event_id: `8f96adc0-c8da-4e11-abca-555ad21f56c0`
- title: When a language model fails on surface-perturbed input (typos, OCR noise, homophones), "which layer is responsible" has
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T15:48:55+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `47c40af3-83a5-426e-83d5-6eeb28151368`
- root title: When a language model fails on surface-perturbed input (typos, OCR noise, homophones), "which layer is responsible" has
- previous linked event titles: When a language model fails on surface-perturbed input (typos, OCR noise, homophones), "which layer is responsible" has (arXiv cs.CL)
- source list: arXiv cs.CL
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 18

**NEW EVENT**
- event_id: `575ac062-9b63-4516-96c8-df6f930df7a8`
- title: Causal Discovery (CD) from observational data faces two fundamental challenges. First, purely statistical methods often
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T16:09:01+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `b333649a-d9d6-4ae5-af27-0c080068dfae`
- root title: Causal Discovery (CD) from observational data faces two fundamental challenges. First, purely statistical methods often
- previous linked event titles: Causal Discovery (CD) from observational data faces two fundamental challenges. First, purely statistical methods often (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 19

**NEW EVENT**
- event_id: `91c4dce3-5b13-4a2a-9e15-48976d29ba2c`
- title: Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it
- source: arXiv cs.CL
- category: AI
- published_at: 2026-08-04T16:15:02+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `1613693c-d163-47d8-988c-d046e8e97ed5`
- root title: Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it
- previous linked event titles: Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Threshold-edge suppressions (closest to 0.65) (8 cases)

### Case 20

**NEW EVENT**
- event_id: `9e7c3af3-7cd0-4622-99cc-0e7fc85c5f03`
- title: Introducing Web Search on Amazon Bedrock for foundation model grounding
- source: AWS Machine Learning Blog
- category: AI
- published_at: 2026-08-04T18:39:14+00:00
- short evidence summary: near-identical title (overlap=0.90) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `0945f6f2-415e-4c5a-91a1-77e5cf31c8e3`
- root title: Introducing Web Search on Amazon Bedrock for foundation model grounding - Amazon Web Services (AWS)
- previous linked event titles: Introducing Web Search on Amazon Bedrock for foundation model grounding - Amazon Web Services (AWS) (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.760
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 21

**NEW EVENT**
- event_id: `23484b0e-2c6b-4ff9-923d-6e486dbd07ad`
- title: AI-generated stories rated better quality than human-written ones, study finds
- source: The Guardian Technology
- category: AI
- published_at: 2026-08-04T23:01:03+00:00
- short evidence summary: near-identical title (overlap=0.91) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `fdf33a25-3306-4857-b67e-3faa6f74d6f4`
- root title: AI-generated stories rated better quality than human-written ones, study finds - The Guardian
- previous linked event titles: AI-generated stories rated better quality than human-written ones, study finds - The Guardian (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.764
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 22

**NEW EVENT**
- event_id: `b40cb9f1-ab38-4a0c-8c68-2c81e2843681`
- title: Suno объявила о планах по борьбе с музыкальным ИИ-спамом
- source: 3DNews
- category: GADGETS
- published_at: 2026-08-07T13:00:00+00:00
- short evidence summary: near-identical title (overlap=0.92) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `ab0a36cd-8e1a-4170-abd6-30c074eae8f9`
- root title: Suno объявила о планах по борьбе с музыкальным ИИ-спамом - 3DNews
- previous linked event titles: Suno объявила о планах по борьбе с музыкальным ИИ-спамом - 3DNews (Google News RU: ИИ)
- source list: Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.819
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 23

**NEW EVENT**
- event_id: `03116b1d-75ff-4ed5-bf9c-af15c416a120`
- title: Microsoft призвала инженеров не злоупотреблять использованием ИИ — это дорого - 3DNews
- source: Google News RU: ИИ
- category: AI
- published_at: 2026-08-05T13:37:00+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `6f575e05-8815-4ccb-a835-7f5ef189ea8c`
- root title: Microsoft призвала инженеров не злоупотреблять использованием ИИ — это дорого
- previous linked event titles: Microsoft призвала инженеров не злоупотреблять использованием ИИ — это дорого (3DNews); Microsoft призвала инженеров не злоупотреблять использованием ИИ — это дорого - 3DNews (Google News RU: ИИ)
- source list: 3DNews, Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.823
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 24

**NEW EVENT**
- event_id: `9c68c894-07b0-480c-b224-f5b5e323674a`
- title: За сутки ИИ выявил несколько сотен уязвимостей в экосистеме биткоина - 3DNews
- source: Google News RU: ИИ
- category: AI
- published_at: 2026-08-07T14:50:00+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `d7cf9446-924f-4040-8bc9-929ee11a0dd5`
- root title: За сутки ИИ выявил несколько сотен уязвимостей в экосистеме биткоина
- previous linked event titles: За сутки ИИ выявил несколько сотен уязвимостей в экосистеме биткоина (3DNews); За сутки ИИ выявил несколько сотен уязвимостей в экосистеме биткоина - 3DNews (Google News RU: ИИ)
- source list: 3DNews, Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.823
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 25

**NEW EVENT**
- event_id: `6ef90bdb-5776-4a9d-9358-05737a52adab`
- title: Google открыла исходный код ИИ-модели, которая предупреждает об ураганах - 3DNews
- source: Google News RU: ИИ
- category: AI
- published_at: 2026-08-07T17:00:38+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `471e7e44-b05c-4d5c-a398-35d7b1fed14a`
- root title: Google открыла исходный код ИИ-модели, которая предупреждает об ураганах
- previous linked event titles: Google открыла исходный код ИИ-модели, которая предупреждает об ураганах (3DNews); Google открыла исходный код ИИ-модели, которая предупреждает об ураганах - 3DNews (Google News RU: ИИ)
- source list: 3DNews, Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.826
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 26

**NEW EVENT**
- event_id: `39a892b8-3b37-4d8a-b376-00636041a3ab`
- title: ИИ Google раскрыл неанонсированного персонажа игры, которого разработчик хранил в тайне в «Google Документах» - 3DNews
- source: Google News RU: ИИ
- category: AI
- published_at: 2026-08-07T14:30:00+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5f04e648-2745-40a2-80f2-c5c5043ba6a5`
- root title: ИИ Google раскрыл неанонсированного персонажа игры, которого разработчик хранил в тайне в «Google Документах»
- previous linked event titles: ИИ Google раскрыл неанонсированного персонажа игры, которого разработчик хранил в тайне в «Google Документах» (3DNews); ИИ Google раскрыл неанонсированного персонажа игры, которого разработчик хранил в тайне в «Google Документах» - 3DNews (Google News RU: ИИ)
- source list: 3DNews, Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.831
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 27

**NEW EVENT**
- event_id: `f394c014-f14b-44e0-957f-3abf20cdec58`
- title: Резать косты с помощью ИИ-агентов невозмо… Хотя, подождите
- source: Habr: Artificial Intelligence
- category: SOFTWARE
- published_at: 2026-08-06T09:21:34+00:00
- short evidence summary: near-identical title (overlap=0.93) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `8ac79265-7014-4847-a37a-3ecec1362de3`
- root title: Резать косты с помощью ИИ-агентов невозмо… Хотя, подождите - Хабр
- previous linked event titles: Резать косты с помощью ИИ-агентов невозмо… Хотя, подождите - Хабр (Google News RU: ИИ)
- source list: Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.873
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Cross-source cases (8 cases)

### Case 28

**NEW EVENT**
- event_id: `0e6dc4a7-24c3-4bcc-8392-4c385e286f89`
- title: Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T16:15:02+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `1613693c-d163-47d8-988c-d046e8e97ed5`
- root title: Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it
- previous linked event titles: Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it (arXiv cs.AI); Modern agent frameworks equip large language models with external skill libraries to solve complex tasks. However, it (arXiv cs.CL)
- source list: arXiv cs.AI, arXiv cs.CL
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 29

**NEW EVENT**
- event_id: `3abaf0ed-428a-4f43-b305-80a6ad018788`
- title: In-the-wild Bengali scene text recognition is largely unmeasured: existing resources target handwritten documents or
- source: arXiv cs.CL
- category: AI
- published_at: 2026-08-04T16:20:53+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `cbaec9c3-e1ca-40d1-9e74-c720217f5a0f`
- root title: In-the-wild Bengali scene text recognition is largely unmeasured: existing resources target handwritten documents or
- previous linked event titles: In-the-wild Bengali scene text recognition is largely unmeasured: existing resources target handwritten documents or (arXiv cs.CV)
- source list: arXiv cs.CV
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 30

**NEW EVENT**
- event_id: `82774a72-8275-4fce-b832-653fe6389adc`
- title: A clinically useful chest X-ray system must go beyond fluent report generation: it should classify findings with
- source: arXiv cs.CV
- category: AI
- published_at: 2026-08-04T16:23:39+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5a36fc19-9183-4087-a0c6-752d4b1649e2`
- root title: A clinically useful chest X-ray system must go beyond fluent report generation: it should classify findings with
- previous linked event titles: A clinically useful chest X-ray system must go beyond fluent report generation: it should classify findings with (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 31

**NEW EVENT**
- event_id: `1c59d32d-54ed-4137-ab80-622330d617ee`
- title: As AI systems are deployed across increasingly diverse social contexts, alignment can no longer be framed as the
- source: arXiv cs.AI
- category: AI
- published_at: 2026-08-04T16:37:09+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `0686a9c9-8f20-40a6-af13-679d54c80990`
- root title: As AI systems are deployed across increasingly diverse social contexts, alignment can no longer be framed as the
- previous linked event titles: As AI systems are deployed across increasingly diverse social contexts, alignment can no longer be framed as the (arXiv cs.LG)
- source list: arXiv cs.LG
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 32

**NEW EVENT**
- event_id: `ab6e608f-98e7-481b-8eab-3070e0a36b71`
- title: Trajectory inference is a fundamental problem in many scientific domains: given a collection of unpaired snapshots of
- source: arXiv stat.ML
- category: AI
- published_at: 2026-08-04T16:42:04+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `27edf65d-8af3-427d-8524-bf15d033e481`
- root title: Trajectory inference is a fundamental problem in many scientific domains: given a collection of unpaired snapshots of
- previous linked event titles: Trajectory inference is a fundamental problem in many scientific domains: given a collection of unpaired snapshots of (arXiv cs.LG)
- source list: arXiv cs.LG
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 33

**NEW EVENT**
- event_id: `47345a19-7092-4ae9-a817-b7af4485d4e1`
- title: Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing,
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T16:59:28+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5fdc368b-37d8-4652-a095-ce93487c782c`
- root title: Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing,
- previous linked event titles: Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing, (arXiv cs.AI)
- source list: arXiv cs.AI
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 34

**NEW EVENT**
- event_id: `ace30df6-0b0e-4352-8bdc-5d0a0c73ec1e`
- title: Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing,
- source: arXiv cs.CV
- category: AI
- published_at: 2026-08-04T16:59:28+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5fdc368b-37d8-4652-a095-ce93487c782c`
- root title: Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing,
- previous linked event titles: Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing, (arXiv cs.AI); Time series anomaly detection (TSAD) underpins applications in predictive maintenance, finance, and cloud computing, (arXiv cs.LG)
- source list: arXiv cs.AI, arXiv cs.LG
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 35

**NEW EVENT**
- event_id: `08e72bc6-bb2f-4eb5-b148-da7094bb0f14`
- title: Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing
- source: arXiv cs.LG
- category: AI
- published_at: 2026-08-04T16:59:58+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `969ffe3f-5cd3-4139-9d1d-d3ee565772c7`
- root title: Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing
- previous linked event titles: Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing (arXiv stat.ML)
- source list: arXiv stat.ML
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Cross-category cases (8 cases)

### Case 36

**NEW EVENT**
- event_id: `f5a08d58-e71b-467c-96c5-5d129a8965ed`
- title: OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-04T17:36:51+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `652fa896-e48b-4075-92e7-7269efbeac2f`
- root title: OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах
- previous linked event titles: OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах (Habr: Artificial Intelligence); OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 37

**NEW EVENT**
- event_id: `a21c2687-1546-4ba1-978f-2a0f9447e587`
- title: «Смесь котят»: как Cursor создал открытое ядро, ускоряющее обучение ИИ до 2.4 раз
- source: Habr: Artificial Intelligence
- category: SOFTWARE
- published_at: 2026-08-04T19:03:03+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `e8bce708-9cac-45d7-b55b-e88422ad9dad`
- root title: «Смесь котят»: как Cursor создал открытое ядро, ускоряющее обучение ИИ до 2.4 раз
- previous linked event titles: «Смесь котят»: как Cursor создал открытое ядро, ускоряющее обучение ИИ до 2.4 раз (Habr: Machine Learning)
- source list: Habr: Machine Learning
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 38

**NEW EVENT**
- event_id: `60e5af02-9891-4aaf-b009-297a04bf4b1c`
- title: Почему в ChatGPT упоминание бренда важнее ссылки: 92,8% диалогов заканчиваются без клика
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-04T21:13:29+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `033714f5-1ef5-4f42-a292-8bb91fac3656`
- root title: Почему в ChatGPT упоминание бренда важнее ссылки: 92,8% диалогов заканчиваются без клика
- previous linked event titles: Почему в ChatGPT упоминание бренда важнее ссылки: 92,8% диалогов заканчиваются без клика (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 39

**NEW EVENT**
- event_id: `1ec1063e-2aec-461f-8634-c7188bba298a`
- title: Age of Autoresearch: я лёг спать, а за ночь проверилось 40 гипотез — а что мне делать и как дальше работать?
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-05T05:26:27+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `8177988a-7ba4-451e-b300-e8bea17b642b`
- root title: Age of Autoresearch: я лёг спать, а за ночь проверилось 40 гипотез — а что мне делать и как дальше работать?
- previous linked event titles: Age of Autoresearch: я лёг спать, а за ночь проверилось 40 гипотез — а что мне делать и как дальше работать? (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 40

**NEW EVENT**
- event_id: `e6c4098c-4c81-49e6-b224-bd67008f7378`
- title: Агенты Anthropic и OpenAI атаковали реальных людей на тестах AISI. И помогали друг другу через GitHub
- source: Habr: Artificial Intelligence
- category: SOFTWARE
- published_at: 2026-08-05T07:58:28+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `53ab8c32-70b2-4f69-a4c5-63876c1e74a2`
- root title: Агенты Anthropic и OpenAI атаковали реальных людей на тестах AISI. И помогали друг другу через GitHub
- previous linked event titles: Агенты Anthropic и OpenAI атаковали реальных людей на тестах AISI. И помогали друг другу через GitHub (Habr: Machine Learning)
- source list: Habr: Machine Learning
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 41

**NEW EVENT**
- event_id: `d95bc9b0-2c7e-4627-b90e-6fce2a7ff516`
- title: Компилятор, который галлюцинирует
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-05T08:00:10+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `64e93713-3942-432d-8580-d480ae306f26`
- root title: Компилятор, который галлюцинирует
- previous linked event titles: Компилятор, который галлюцинирует (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 42

**NEW EVENT**
- event_id: `c3a5f25e-81e4-4b72-9300-6680356068fc`
- title: Что будет если загрузить в «симулятор общества» чистый lorem ipsum? Большое исследование MiroFish, часть 1
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-05T08:46:36+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `9138020f-0891-48bb-86d9-ef4df7d3eec1`
- root title: Что будет если загрузить в «симулятор общества» чистый lorem ipsum? Большое исследование MiroFish, часть 1
- previous linked event titles: Что будет если загрузить в «симулятор общества» чистый lorem ipsum? Большое исследование MiroFish, часть 1 (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 43

**NEW EVENT**
- event_id: `9ca80016-3a89-4e67-ab8c-f9c175650f78`
- title: Я убил все RAG‑системы и понял, как делать AGI. Или просто заменил RAG правилом в шесть строк
- source: Habr: Machine Learning
- category: AI
- published_at: 2026-08-05T09:01:31+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `7850f65b-5dc0-4029-9df6-3bae23e9c508`
- root title: Я убил все RAG‑системы и понял, как делать AGI. Или просто заменил RAG правилом в шесть строк
- previous linked event titles: Я убил все RAG‑системы и понял, как делать AGI. Или просто заменил RAG правилом в шесть строк (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Same-source repeated pages (8 cases)

### Case 44

**NEW EVENT**
- event_id: `d647ced8-bc77-4e2d-859d-7a7d128a8f5e`
- title: Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing
- source: arXiv stat.ML
- category: AI
- published_at: 2026-08-04T16:59:58+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `969ffe3f-5cd3-4139-9d1d-d3ee565772c7`
- root title: Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing
- previous linked event titles: Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing (arXiv stat.ML); Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing (arXiv cs.LG)
- source list: arXiv cs.LG, arXiv stat.ML
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 45

**NEW EVENT**
- event_id: `170fa662-d3a5-4a2d-975a-d503bffeba0f`
- title: OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах
- source: Habr: Artificial Intelligence
- category: SOFTWARE
- published_at: 2026-08-04T17:36:51+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `652fa896-e48b-4075-92e7-7269efbeac2f`
- root title: OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах
- previous linked event titles: OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах (Habr: Artificial Intelligence)
- source list: Habr: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 46

**NEW EVENT**
- event_id: `2271a787-1a2b-4583-a452-c682f25bb81e`
- title: Artificial Intelligence Is the Weapon and the Target, CrowdStrike Report Finds - ASIS International
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-04T19:07:30+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `7687039b-7bc9-412e-a908-e6661582df35`
- root title: Artificial Intelligence Is the Weapon and the Target, CrowdStrike Report Finds - ASIS International
- previous linked event titles: Artificial Intelligence Is the Weapon and the Target, CrowdStrike Report Finds - ASIS International (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 47

**NEW EVENT**
- event_id: `11be3a07-4845-40ba-b6ed-c75f70547bf3`
- title: Diembassy CEO Dr. Linda Pajoel Delivers Keynote on Artificial Intelligence at Executive Leadership Retreat in Tanzania
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-05T01:00:04+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `049527a2-2d9b-4522-9b92-dac4970b71b3`
- root title: Diembassy CEO Dr. Linda Pajoel Delivers Keynote on Artificial Intelligence at Executive Leadership Retreat in Tanzania
- previous linked event titles: Diembassy CEO Dr. Linda Pajoel Delivers Keynote on Artificial Intelligence at Executive Leadership Retreat in Tanzania (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 48

**NEW EVENT**
- event_id: `986eecdc-bafd-4d43-9e5c-07a29bfde6bb`
- title: Filtering combines model predictions with measurements to estimate the probability density function (PDF) of a system
- source: arXiv stat.ML
- category: AI
- published_at: 2026-08-05T04:21:22+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `9382e39e-021d-437c-8a23-02e9b62e169e`
- root title: Filtering combines model predictions with measurements to estimate the probability density function (PDF) of a system
- previous linked event titles: Filtering combines model predictions with measurements to estimate the probability density function (PDF) of a system (arXiv stat.ML)
- source list: arXiv stat.ML
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 49

**NEW EVENT**
- event_id: `04465db7-feb8-48ba-9ff0-1ca10b02fb1b`
- title: CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-05T15:34:00+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `3c6d5e20-980b-4b44-9745-479145d3ffab`
- root title: CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN
- previous linked event titles: CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 50

**NEW EVENT**
- event_id: `3601bde1-c79e-480c-91c4-d06964587e27`
- title: CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-05T17:00:24+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `3c6d5e20-980b-4b44-9745-479145d3ffab`
- root title: CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN
- previous linked event titles: CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN (Google News: Artificial Intelligence); CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 51

**NEW EVENT**
- event_id: `4ee76889-7692-4a56-a8cd-206e09495e1a`
- title: FAMU-FSU College of Engineering researchers create artificial intelligence tool to manage modern power grid -
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-06T00:07:05+00:00
- short evidence summary: near-identical title (overlap=0.96) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `7b696945-72e5-44c4-993a-178a8b3bc4cf`
- root title: FAMU-FSU College of Engineering researchers create artificial intelligence tool to manage modern power grid | Newswise
- previous linked event titles: FAMU-FSU College of Engineering researchers create artificial intelligence tool to manage modern power grid | Newswise (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 0.884
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Repeated aggregator coverage (Google News-style, both sides) (6 cases)

### Case 52

**NEW EVENT**
- event_id: `5d44b3cf-9133-47da-b4ba-e76736814132`
- title: Ученые предупредили о рисках чрезмерного доверия ИИ-чатам в сфере женского здоровья - Vademec.ru
- source: Google News RU: ИИ
- category: AI
- published_at: 2026-08-07T08:45:19+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `c687346c-7cee-4c20-b269-726a9bcdd7e1`
- root title: Ученые предупредили о рисках чрезмерного доверия ИИ-чатам в сфере женского здоровья - Vademec.ru
- previous linked event titles: Ученые предупредили о рисках чрезмерного доверия ИИ-чатам в сфере женского здоровья - Vademec.ru (Google News RU: ИИ)
- source list: Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 53

**NEW EVENT**
- event_id: `ef4965c5-53f5-42c0-9fe5-9bf3725a0ff2`
- title: Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. -
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-07T13:20:00+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `b047f4f6-9463-446d-b8a3-2c6a310467ce`
- root title: Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. -
- previous linked event titles: Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. - (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 54

**NEW EVENT**
- event_id: `a738886a-33ca-4daa-b31e-dc208d49e131`
- title: Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. - The
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-07T13:23:56+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `b047f4f6-9463-446d-b8a3-2c6a310467ce`
- root title: Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. -
- previous linked event titles: Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. - (Google News: Artificial Intelligence); Not Micron, Not Nvidia. This Artificial Intelligence (AI) Giant Could Be the Ultimate Winner of the AI Arms Race. - (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 55

**NEW EVENT**
- event_id: `2857295f-332f-4332-8928-2838548f22fe`
- title: Школьная сборная России третий год подряд стала абсолютным чемпионом на Международной олимпиаде по искусственному
- source: Google News RU: ИИ
- category: AI
- published_at: 2026-08-07T15:06:53+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `2252893e-0b4a-4fdc-a347-cf5119409898`
- root title: Школьная сборная России третий год подряд стала абсолютным чемпионом на Международной олимпиаде по искусственному
- previous linked event titles: Школьная сборная России третий год подряд стала абсолютным чемпионом на Международной олимпиаде по искусственному (Google News RU: ИИ); Россия третий год подряд стала абсолютным чемпионом на Международной олимпиаде по ИИ - Наука РФ (Google News RU: ИИ); Школьная сборная РФ стала абсолютным чемпионом на Международной олимпиаде по ИИ - Интерфакс (Google News RU: ИИ)
- source list: Google News RU: ИИ
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 56

**NEW EVENT**
- event_id: `a3feeac5-e786-4d23-a0b5-d97f288f45dd`
- title: Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-07T16:06:55+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5c0fce42-414e-42c6-914b-c9f941d9ba96`
- root title: Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in
- previous linked event titles: Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Case 57

**NEW EVENT**
- event_id: `b640f752-ea00-42d0-a908-1fbce85d0e6f`
- title: Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in
- source: Google News: Artificial Intelligence
- category: AI
- published_at: 2026-08-07T16:06:55+00:00
- short evidence summary: near-identical title (overlap=1.00) and no new keywords or claims (new keywords: (none); new material claims: (none))

**MATCHED STORY**
- story_id: `5c0fce42-414e-42c6-914b-c9f941d9ba96`
- root title: Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in
- previous linked event titles: Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in (Google News: Artificial Intelligence); Ai4 2026 Sets New Records With 50% Attendance Growth as More Than 12,000 Global AI Leaders from 100 Countries Gather in (Google News: Artificial Intelligence)
- source list: Google News: Artificial Intelligence
- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)

**DECISION**
- match_type: semantic_duplicate
- match_score: 1.000
- confidence band: high
- delta classification: no_new_facts
- would_suppress: True
- reason: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Non-suppress controls (8 cases)

Obvious non-suppress cases (would_suppress=False) - sanity check that the policy correctly stays silent here.

### Control 58

**NEW EVENT**
- event_id: `84eabab4-34a0-4e34-981b-6218b0027159`
- title: Beast of Reincarnation review – a taxing reflection of human-made damage
- source: The Guardian Technology
- category: AI
- published_at: 2026-08-04T00:00:06+00:00
- short evidence summary: a small number of new distinctive keywords, no material claim (['damage', 'human-made', 'reflection', 'taxing'])

**MATCHED STORY**
- story_id: `a3b1cf2b-3638-4331-962c-1eac1daec389`
- root title: Beast of Reincarnation review

**DECISION**
- match_type: supporting_source
- match_score: 0.890
- confidence band: high
- delta classification: minor_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 59

**NEW EVENT**
- event_id: `616ec7c8-ec2b-4ef7-be8e-74f16ab6f5b3`
- title: This paper presents purely convex programs for passively safe impulsive rendezvous and proximity operations in cislunar
- source: arXiv cs.RO
- category: AI
- published_at: 2026-08-04T03:22:15+00:00
- short evidence summary: neither a confident rewording (overlap=0.15) nor a clear material claim nor a small bounded keyword delta (13 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `8cf7f8dd-bdc3-4054-8675-cc73931f0f5a`
- root title: This paper addresses the challenge of providing kinesthetic feedback in bilateral teleoperation by designing a

**DECISION**
- match_type: story_update
- match_score: 0.762
- confidence band: high
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 60

**NEW EVENT**
- event_id: `bbe32ca6-c0f3-46a0-91d9-ecee0ca3d5b0`
- title: If you hate parrying, projectiles in Beast of Reincarnation are ridiculously overpowered if you focus on leveling them
- source: PC Gamer
- category: HARDWARE
- published_at: 2026-08-04T03:46:52+00:00
- short evidence summary: neither a confident rewording (overlap=0.27) nor a clear material claim nor a small bounded keyword delta (10 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `a3b1cf2b-3638-4331-962c-1eac1daec389`
- root title: Beast of Reincarnation review

**DECISION**
- match_type: uncertain_match
- match_score: 0.607
- confidence band: medium
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 61

**NEW EVENT**
- event_id: `fabbcb30-a4b7-40b6-8acc-37c8310334e9`
- title: Пока мы спали, Telegram удалили из App Store по всему миру
- source: Rozetked
- category: UNKNOWN
- published_at: 2026-08-04T04:30:01+00:00
- short evidence summary: neither a confident rewording (overlap=0.29) nor a clear material claim nor a small bounded keyword delta (5 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `853d0c52-9803-479d-bfe0-336985e6bfc9`
- root title: Telegram briefly pulled from the App Store over child sexual abuse material availability [U]

**DECISION**
- match_type: uncertain_match
- match_score: 0.564
- confidence band: medium
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 62

**NEW EVENT**
- event_id: `44cd5eb9-28c1-490b-9ac7-183f4ff66d02`
- title: Wildberries сообщил об атаке беспилотников на склад в Красном бору (Ленинградская область). На месте работают пожарные.
- source: vc.ru
- category: UNKNOWN
- published_at: 2026-08-04T05:03:15+00:00
- short evidence summary: neither a confident rewording (overlap=0.53) nor a clear material claim nor a small bounded keyword delta (7 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `e13593bc-9908-4ef1-8889-7cc8179ab317`
- root title: Wildberries сообщил об атаке беспилотников на склад в Ленинградской области

**DECISION**
- match_type: uncertain_match
- match_score: 0.561
- confidence band: medium
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 63

**NEW EVENT**
- event_id: `93192928-caa7-4e13-b716-1e455568cc1c`
- title: This research proposes a constrained motion planning framework for robot manipulators in human-robot interaction (HRI).
- source: arXiv cs.RO
- category: AI
- published_at: 2026-08-04T05:47:25+00:00
- short evidence summary: neither a confident rewording (overlap=0.14) nor a clear material claim nor a small bounded keyword delta (11 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `8cf7f8dd-bdc3-4054-8675-cc73931f0f5a`
- root title: This paper addresses the challenge of providing kinesthetic feedback in bilateral teleoperation by designing a

**DECISION**
- match_type: uncertain_match
- match_score: 0.433
- confidence band: medium
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 64

**NEW EVENT**
- event_id: `b3825457-00cc-4b89-9b23-90fd5640cf51`
- title: OpenAI rebuts Apple trade secrets allegations in new response with receipts
- source: 9to5Mac
- category: GADGETS
- published_at: 2026-08-04T06:05:15+00:00
- short evidence summary: neither a confident rewording (overlap=0.21) nor a clear material claim nor a small bounded keyword delta (8 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `caae2d7a-4ba2-4471-86b6-6e8b06cbb57f`
- root title: Russia escalates dispute with Apple over mandatory app preinstallation

**DECISION**
- match_type: uncertain_match
- match_score: 0.384
- confidence band: medium
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 65

**NEW EVENT**
- event_id: `112ac4f0-905f-46c8-8a02-55ef42a5bc9d`
- title: Apple пообещала открыть для Windows доступ к буферу обмена iPhone
- source: 3DNews
- category: GADGETS
- published_at: 2026-08-04T06:40:00+00:00
- short evidence summary: neither a confident rewording (overlap=0.35) nor a clear material claim nor a small bounded keyword delta (6 new keywords) - ambiguous

**MATCHED STORY**
- story_id: `3abbfdf2-809d-47d8-aa67-c22008b888c6`
- root title: Apple plans to open iPhone clipboard access to Windows PCs

**DECISION**
- match_type: uncertain_match
- match_score: 0.541
- confidence band: medium
- delta classification: uncertain_delta
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## MATERIAL_UPDATE controls (8 cases)

Cases classified MATERIAL_UPDATE - these must NEVER be suppressed (the suppression policy already guarantees this structurally). Included so a reviewer can confirm these genuinely look like real updates worth publishing, not just verify the boolean.

### Control 66

**NEW EVENT**
- event_id: `ad7ec6ba-1144-4cd8-a4bb-91dbd532f329`
- title: Apple сообщила, что в ночь на 4 августа 2026 года временно удаляла Telegram из App Store из-за нарушения правил
- source: vc.ru
- category: UNKNOWN
- published_at: 2026-08-04T04:37:13+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['4 августа 2026']

**MATCHED STORY**
- story_id: `853d0c52-9803-479d-bfe0-336985e6bfc9`
- root title: Telegram briefly pulled from the App Store over child sexual abuse material availability [U]

**DECISION**
- match_type: uncertain_match
- match_score: 0.536
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 67

**NEW EVENT**
- event_id: `67bc0c67-5e3f-4b0b-8b5d-e8049dd25bfc`
- title: Apple синхронизирует буфер обмена с Windows к осени 2027 года — пользователи смогут скопировать контент на iPhone и
- source: vc.ru
- category: UNKNOWN
- published_at: 2026-08-04T08:13:38+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['2027']

**MATCHED STORY**
- story_id: `3abbfdf2-809d-47d8-aa67-c22008b888c6`
- root title: Apple plans to open iPhone clipboard access to Windows PCs

**DECISION**
- match_type: uncertain_match
- match_score: 0.464
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 68

**NEW EVENT**
- event_id: `8a5c85e7-ffd6-49e1-b260-588a16afc093`
- title: Путин утвердил штрафы до 500 тысяч рублей за нарушения работы маркетплейсов и сервисов доставки с партнёрами
- source: vc.ru AI
- category: STARTUPS
- published_at: 2026-08-04T18:21:00+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['500 тысяч рублей']

**MATCHED STORY**
- story_id: `39ea0172-2fe7-48e6-a5c1-5f7551ed35b8`
- root title: Путин подписал закон о регулировании криптовалют в России

**DECISION**
- match_type: uncertain_match
- match_score: 0.444
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 69

**NEW EVENT**
- event_id: `61da5a38-31d6-4033-87e8-da7d4dadc186`
- title: Anthropic signs $10B deal with AI cloud startup Volta
- source: TechCrunch AI
- category: STARTUPS
- published_at: 2026-08-04T19:48:40+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['$10B']

**MATCHED STORY**
- story_id: `b865390d-9d71-4b67-8de4-818e29c4b77f`
- root title: AI cloud startup Volta valued at $2.4 billion, announces $10 billion AI partnership - Reuters

**DECISION**
- match_type: uncertain_match
- match_score: 0.450
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 70

**NEW EVENT**
- event_id: `05b49ceb-fc5f-4ca2-aa3a-0d4a6fcca3ee`
- title: SpaceX's first public earnings statement shows the financials of an AI company in 2026
- source: Engadget
- category: GADGETS
- published_at: 2026-08-04T21:42:08+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['2026']

**MATCHED STORY**
- story_id: `63ed1714-4b1d-48bd-9e61-e197aa4f145b`
- root title: SpaceX made more revenue as an AI company than a space company

**DECISION**
- match_type: story_update
- match_score: 0.747
- confidence band: high
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 71

**NEW EVENT**
- event_id: `32b108fc-9ab5-4f7d-b683-85775696ee82`
- title: 9to5Mac Daily: August 4, 2026 – The latest Apple vs OpenAI drama
- source: 9to5Mac
- category: GADGETS
- published_at: 2026-08-04T22:42:37+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['August 4, 2026']

**MATCHED STORY**
- story_id: `45981490-9411-4dbf-a881-f0fb2d61e42f`
- root title: Apple @ Work Podcast: The state of digital signage on Apple TV in 2026

**DECISION**
- match_type: uncertain_match
- match_score: 0.413
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 72

**NEW EVENT**
- event_id: `b6251581-658c-4f74-a51a-df8e0d60579c`
- title: iPhone 20 Pro and Pro Max Might Get Bigger Screens in 2027
- source: CNET
- category: GADGETS
- published_at: 2026-08-04T23:24:33+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['2027']

**MATCHED STORY**
- story_id: `71895379-b59f-44c7-bc8f-850d6bec34ac`
- root title: iPhone 18 Pro will have three upgrades that have been rumored for years

**DECISION**
- match_type: uncertain_match
- match_score: 0.580
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

### Control 73

**NEW EVENT**
- event_id: `9e9debd8-eee4-4e24-b1bc-37b5764e4dc1`
- title: День 1624: число ликвидаций компаний по экономическим причинам в 2026 году впервые превысило число регистраций новых
- source: vc.ru AI
- category: STARTUPS
- published_at: 2026-08-05T05:42:17+00:00
- short evidence summary: genuinely new material claim(s) not present in any prior title: ['2026']

**MATCHED STORY**
- story_id: `fa860f45-86c2-472e-a42e-efae3e099702`
- root title: День 1623: Ozon начал вывозить часть «дорогостоящих» товаров со своих складов в пункты выдачи заказов

**DECISION**
- match_type: uncertain_match
- match_score: 0.431
- confidence band: medium
- delta classification: material_update
- would_suppress: False

**HUMAN VERDICT**:
[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN

## Reviewer instructions

For each case: read the NEW EVENT and MATCHED STORY facts and the DECISION already computed, then check exactly one HUMAN VERDICT box - CORRECT_SUPPRESS (genuinely the same story, nothing new), SHOULD_UPDATE (same story but with real new information), FALSE_MATCH (a real, distinct story that scored highly), or UNCERTAIN (genuinely unclear from the titles alone). For the two control sections, the question is simply whether the policy's own non-suppression / material-update judgment looks correct.
