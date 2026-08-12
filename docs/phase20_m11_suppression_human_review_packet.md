# Phase 20 Checkpoint 4 - Suppression Human-Review Packet

Deterministic sample drawn from all 173 `would_suppress=True` cases produced by the Checkpoint 4 same-dataset historical replay (2026-08-04 to 2026-08-07, 3,774 real events, disposable Postgres, post precision-hardening). **Suppression is NOT enabled anywhere** - this packet exists to let a human reviewer sample-check the policy's real output before any activation decision. No suppression precision/recall number should be reported until every HUMAN VERDICT blank below has actually been filled in by a person - this script never auto-fills them. All match_score values are >= 0.65, confirming every sampled case genuinely cleared the HIGH confidence band as the policy requires.

## Highest-confidence suppressions

Top match_score - the cases the policy is most sure about.

- **New event**: `GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T08:08:46+00:00
- **Matched Story root**: `GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T09:34:53+00:00
- **Matched Story root**: `Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T10:19:49+00:00
- **Matched Story root**: `Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T11:34:55+00:00
- **Matched Story root**: `460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T12:59:15+00:00
- **Matched Story root**: `Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of`
  - Source: arXiv cs.CV | Category: AI | Published: 2026-08-04T13:08:03+00:00
- **Matched Story root**: `The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of`
  - Source: arXiv cs.CL | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases`
  - Source: arXiv cs.CL | Category: AI | Published: 2026-08-04T14:25:47+00:00
- **Matched Story root**: `Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases`
  - Source: arXiv cs.AI | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and`
  - Source: arXiv cs.LG | Category: AI | Published: 2026-08-04T14:36:44+00:00
- **Matched Story root**: `Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and`
  - Source: arXiv cs.AI | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)


## Threshold-edge suppressions

Closest to the HIGH confidence-band boundary (0.65) from above - the cases most likely to flip bands under any future recalibration.

- **New event**: `3 Magnificent Artificial Intelligence (AI) Stocks to Buy Right Now and Hold for the Next Decade - The Motley Fool`
  - Source: Google News: Artificial Intelligence | Category: AI | Published: 2026-08-04T17:00:00+00:00
- **Matched Story root**: `3 Genius Artificial Intelligence (AI) Stocks to Buy Right Now - The Motley Fool`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: supporting_source (score=0.688, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=0.87) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: supporting_source + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Introducing Web Search on Amazon Bedrock for foundation model grounding`
  - Source: AWS Machine Learning Blog | Category: AI | Published: 2026-08-04T18:39:14+00:00
- **Matched Story root**: `Introducing Web Search on Amazon Bedrock for foundation model grounding - Amazon Web Services (AWS)`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.760, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=0.90) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `AI-generated stories rated better quality than human-written ones, study finds`
  - Source: The Guardian Technology | Category: AI | Published: 2026-08-04T23:01:03+00:00
- **Matched Story root**: `AI-generated stories rated better quality than human-written ones, study finds - The Guardian`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.764, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=0.91) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Suno объявила о планах по борьбе с музыкальным ИИ-спамом`
  - Source: 3DNews | Category: GADGETS | Published: 2026-08-07T13:00:00+00:00
- **Matched Story root**: `Suno объявила о планах по борьбе с музыкальным ИИ-спамом - 3DNews`
  - Source: Google News RU: ИИ | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.819, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=0.92) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Microsoft призвала инженеров не злоупотреблять использованием ИИ — это дорого - 3DNews`
  - Source: Google News RU: ИИ | Category: AI | Published: 2026-08-05T13:37:00+00:00
- **Matched Story root**: `Microsoft призвала инженеров не злоупотреблять использованием ИИ — это дорого`
  - Source: 3DNews | Category: GADGETS
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.823, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `За сутки ИИ выявил несколько сотен уязвимостей в экосистеме биткоина - 3DNews`
  - Source: Google News RU: ИИ | Category: AI | Published: 2026-08-07T14:50:00+00:00
- **Matched Story root**: `За сутки ИИ выявил несколько сотен уязвимостей в экосистеме биткоина`
  - Source: 3DNews | Category: GADGETS
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.823, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Google открыла исходный код ИИ-модели, которая предупреждает об ураганах - 3DNews`
  - Source: Google News RU: ИИ | Category: AI | Published: 2026-08-07T17:00:38+00:00
- **Matched Story root**: `Google открыла исходный код ИИ-модели, которая предупреждает об ураганах`
  - Source: 3DNews | Category: GADGETS
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.826, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `ИИ Google раскрыл неанонсированного персонажа игры, которого разработчик хранил в тайне в «Google Документах» - 3DNews`
  - Source: Google News RU: ИИ | Category: AI | Published: 2026-08-07T14:30:00+00:00
- **Matched Story root**: `ИИ Google раскрыл неанонсированного персонажа игры, которого разработчик хранил в тайне в «Google Документах»`
  - Source: 3DNews | Category: GADGETS
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=0.831, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)


## Cross-source cases

New event's source differs from the matched story's own root source (155/173 total) - the classic 'two outlets, one story' pattern this policy is meant to catch.

- **New event**: `GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T08:08:46+00:00
- **Matched Story root**: `GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T09:34:53+00:00
- **Matched Story root**: `Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T10:19:49+00:00
- **Matched Story root**: `Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T11:34:55+00:00
- **Matched Story root**: `460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T12:59:15+00:00
- **Matched Story root**: `Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of`
  - Source: arXiv cs.CV | Category: AI | Published: 2026-08-04T13:08:03+00:00
- **Matched Story root**: `The personal archive of Konstantin Tsiolkovsky (1857-1935) is held as fond 555 of the Archive of the Russian Academy of`
  - Source: arXiv cs.CL | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases`
  - Source: arXiv cs.CL | Category: AI | Published: 2026-08-04T14:25:47+00:00
- **Matched Story root**: `Automated Knowledge Base Construction (AKBC) is a core NLP task, and recent work proposes generating knowledge bases`
  - Source: arXiv cs.AI | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and`
  - Source: arXiv cs.LG | Category: AI | Published: 2026-08-04T14:36:44+00:00
- **Matched Story root**: `Terminal User Interfaces (TUIs) combine the stateful, screen-oriented behaviour of GUIs with terminal deployment and`
  - Source: arXiv cs.AI | Category: AI
- Category match: SAME | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)


## Same-source repetitions

New event's source is the SAME as the matched story's root source (18/173 total) - worth extra scrutiny, since a single source rarely republishes its own article verbatim; may indicate a feed artifact or a genuine same-source follow-up.

- **New event**: `Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing`
  - Source: arXiv stat.ML | Category: AI | Published: 2026-08-04T16:59:58+00:00
- **Matched Story root**: `Tensor cross-concentrated sampling (t-CCS) bridges entrywise sampling and t-CUR slice-wise sampling by observing`
  - Source: arXiv stat.ML | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `3 Magnificent Artificial Intelligence (AI) Stocks to Buy Right Now and Hold for the Next Decade - The Motley Fool`
  - Source: Google News: Artificial Intelligence | Category: AI | Published: 2026-08-04T17:00:00+00:00
- **Matched Story root**: `3 Genius Artificial Intelligence (AI) Stocks to Buy Right Now - The Motley Fool`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: supporting_source (score=0.688, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=0.87) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: supporting_source + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T17:36:51+00:00
- **Matched Story root**: `OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Artificial Intelligence Is the Weapon and the Target, CrowdStrike Report Finds - ASIS International`
  - Source: Google News: Artificial Intelligence | Category: AI | Published: 2026-08-04T19:07:30+00:00
- **Matched Story root**: `Artificial Intelligence Is the Weapon and the Target, CrowdStrike Report Finds - ASIS International`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Diembassy CEO Dr. Linda Pajoel Delivers Keynote on Artificial Intelligence at Executive Leadership Retreat in Tanzania`
  - Source: Google News: Artificial Intelligence | Category: AI | Published: 2026-08-05T01:00:04+00:00
- **Matched Story root**: `Diembassy CEO Dr. Linda Pajoel Delivers Keynote on Artificial Intelligence at Executive Leadership Retreat in Tanzania`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Filtering combines model predictions with measurements to estimate the probability density function (PDF) of a system`
  - Source: arXiv stat.ML | Category: AI | Published: 2026-08-05T04:21:22+00:00
- **Matched Story root**: `Filtering combines model predictions with measurements to estimate the probability density function (PDF) of a system`
  - Source: arXiv stat.ML | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN`
  - Source: Google News: Artificial Intelligence | Category: AI | Published: 2026-08-05T15:34:00+00:00
- **Matched Story root**: `CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN`
  - Source: Google News: Artificial Intelligence | Category: AI | Published: 2026-08-05T17:00:24+00:00
- **Matched Story root**: `CertiProf Expands International Training Program for ISO/IEC 42001 Artificial Intelligence Governance Standard - EIN`
  - Source: Google News: Artificial Intelligence | Category: AI
- Category match: SAME | Source match: SAME
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)


## Cross-category cases

New event's NewsEvent.category differs from the matched story's own category (48/173 total) - exercises the post-M3 soft category bonus rather than a hard filter.

- **New event**: `GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T08:08:46+00:00
- **Matched Story root**: `GPT-5.6 Sol атакует Hugging Face, OpenAI закрывает Atlas, Grok Build попался на сливе данных: главные события июля в ИИ`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T09:34:53+00:00
- **Matched Story root**: `Миллион токенов за 1 ₽ или за 20 726 ₽: одна RTX 5090, и почему API все равно дешевле`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T10:19:49+00:00
- **Matched Story root**: `Как деградирует продовый LLM-инференс: KV-cache, OOM и хвост p99`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T11:34:55+00:00
- **Matched Story root**: `460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T12:59:15+00:00
- **Matched Story root**: `Я ошибался: бенчмарк 23 ASR-нейросетей для русской айтишной диктовки`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T17:36:51+00:00
- **Matched Story root**: `OWASP LLM10: Unbounded Consumption. Тестируем современные языковые модели на ресурсоёмких промптах`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `«Смесь котят»: как Cursor создал открытое ядро, ускоряющее обучение ИИ до 2.4 раз`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE | Published: 2026-08-04T19:03:03+00:00
- **Matched Story root**: `«Смесь котят»: как Cursor создал открытое ядро, ускоряющее обучение ИИ до 2.4 раз`
  - Source: Habr: Machine Learning | Category: AI
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)

- **New event**: `Почему в ChatGPT упоминание бренда важнее ссылки: 92,8% диалогов заканчиваются без клика`
  - Source: Habr: Machine Learning | Category: AI | Published: 2026-08-04T21:13:29+00:00
- **Matched Story root**: `Почему в ChatGPT упоминание бренда важнее ссылки: 92,8% диалогов заканчиваются без клика`
  - Source: Habr: Artificial Intelligence | Category: SOFTWARE
- Category match: DIFFERENT | Source match: DIFFERENT
- **Relationship outcome**: semantic_duplicate (score=1.000, confidence=high)
- **Delta outcome**: no_new_facts - near-identical title (overlap=1.00) and no new keywords or claims
  - New material claims found: (none)
  - New keywords found: (none)
- **Suppression reason**: semantic_duplicate + confidence_band=high + delta=no_new_facts (no material delta) -> would_suppress
- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)


## Different-company/product controls

No case among the 173 real `would_suppress=True` flags resembles a different-company/product false positive (all require a HIGH-confidence combined score, which in this codebase's scoring model requires substantial genuine entity/title overlap - a different-company pair reaching that combination would itself be a scoring bug worth escalating, and none was observed). This control category is instead covered by the permanent synthetic regression suite (tests/test_story_memory_v2.py::test_synthetic_entity_overlap_traps_never_same_story_merge, now 6 parametrized cases including the two Checkpoint 4 hard controls - same_company_two_launches and same_named_event_different_year - all passing) - those cases are constructed specifically to test this failure mode and are re-run on every commit, not just once here.

## Reviewer instructions

For each sampled pair above: read the New event and Matched Story root facts, the relationship/delta outcomes already computed, and judge whether this is genuinely the same real-world story with nothing new to say (CORRECT_SUPPRESS), the same story but with a real update worth publishing (SHOULD_UPDATE), a real, distinct story that happens to score highly (FALSE_MATCH), or genuinely unclear from the titles alone (UNCERTAIN). Fill in each blank HUMAN VERDICT line directly in this file. This packet does not pre-judge any case - every verdict field starts blank and must stay that way until a person reviews it.
