# Semantic uniqueness judge + caption finality - founder review

## Offline

- zero-cost acceptance (stub judge): 6/6 - cost_bound_under_a_fifth_of_director_worst, deterministic_fixtures, gta_stub_findings_reach_one_combined_correction, golden_pass_with_empty_verdict, fail_closed, hard_failure_never_judged
- worst-case judge call: {'input_chars': 12468, 'input_tokens_worst': 6234, 'output_tokens_cap': 1500, 'worst_case_usd': 0.015234}
- judge-only calibration with the real model (prompt v4): 11/11; v1-v3 rounds kept in offline/

## Live - same GTA IV story (event 30740b23), commit e9ccbb3

- PHASE_A: OK, finish=stop, out=848/8000, $0.007546
- DIRECTOR: OK, finish=stop, out=7130/10737, $0.055676
- SEMANTIC_JUDGE: OK, finish=stop, out=774/1500, $0.006307
- DIRECTOR: OK, finish=stop, out=7016/10737, $0.055447
- SEMANTIC_JUDGE: OK, finish=stop, out=322/1500, $0.003531
- result: **creative_director_failed:EditorialCorrectionRequired** (no render, no image, no art gate)

## Call 1 - initial Director

| # | ev | headline | body |
|---|---|---|---|
| 1 | E1 | GTA IV ждала сглаживания 18 лет | И дождалась — но не от Rockstar Games. |
| 2 | E2 | «Лесенки» наконец убрали | Речь о ПК-версии Grand Theft Auto IV и полноценном сглаживании — спустя почти два десятка лет после выхода игры. |
| 3 | E5 | Мод добавил сразу четыре технологии | В списке — Nvidia DLSS 4, AMD FSR 3, DLAA и HDR. |
| 4 | E6 | Мод называется DLSS-IV | Его сделал ChunkLeChuck. Скачать мод можно на Nexus Mods. |
| 5 | E7 | Без Fusion Fix не заработает | Для работы DLSS-IV требуется глобальная техническая модификация Fusion Fix. |
| 6 | E5 | 18 лет спустя — моддер, а не Rockstar | GTA IV получила сглаживание, DLSS 4, FSR 3, DLAA и HDR через DLSS-IV. У игровой классики наконец появился графический апдейт, которого от неё уже почти перестали ждать. |

Caption: Спустя почти 18 лет ПК-версия GTA IV получила то, чего ей не хватало с самого начала: полноценное сглаживание. Мод DLSS-IV от ChunkLeChuck добавляет DLSS 4, FSR 3, DLAA и HDR, но для работы ему нужен Fusion Fix. Не Rockstar Games — моддер.

Deterministic findings:
- slide 3 body is a list of product names, not Russian prose: 'В списке — Nvidia DLSS 4, AMD FSR 3, DLAA и HDR.' - say it as a sentence
- slide 6 body: generic filler with no new fact: 'У игровой классики наконец появился графический апдейт, которого от неё уже почти перестали ждать.' - end on the real fact or its plain irony
- slide 5 body copies the source's wording verbatim ('требуется глобальная техническая модификация fusion fix') - say it in plain natural Russian

Semantic findings:
- semantic review: slides 1 and 2 make the same point in different words (Both slides claim that GTA IV finally received full anti-aliasing after 18 years from a modder rather than Rockstar Games) - merge them into one slide, then use the freed slide for another distinct grounded fact or make the carousel shorter
- semantic review: unsupported interpretation in slide 6 body ('У игровой классики наконец появился графический апдейт, которого от неё уже почти перестали ждать.': The evidence states the update arrived after 18 years but does not state that people had almost stopped expecting it) - say only what the evidence supports
- semantic review: unsupported interpretation in caption ('Спустя почти 18 лет ПК-версия GTA IV получила то, чего ей не хватало с самого начала: полноценное сглаживание.': The evidence supports the long-standing lack of anti-aliasing but does not state that it had been missing from the very beginning) - say only what the evidence supports

## Call 2 - the one editorial correction

| # | ev | headline | body |
|---|---|---|---|
| 1 | E1 | 18 лет — и GTA IV наконец без «лесенок» | Полноценное сглаживание добавил моддер, а не Rockstar Games. |
| 2 | E5 | Мод добавил больше, чем сглаживание | ChunkLeChuck снабдил GTA IV поддержкой Nvidia DLSS 4, AMD FSR 3, DLAA и HDR. |
| 3 | E6 | Мод называется DLSS-IV | Он доступен для скачивания на Nexus Mods. |
| 4 | E7 | Но для работы нужен Fusion Fix | Это обязательная техническая модификация для запуска DLSS-IV. |
| 5 | E6 | Если ставить — ищи связку DLSS-IV + Fusion Fix | DLSS-IV доступен на Nexus Mods, а для его работы нужен Fusion Fix. |

Caption: Спустя 18 лет в ПК-версии GTA IV появилось полноценное сглаживание — не благодаря Rockstar Games, а благодаря моддеру ChunkLeChuck. Мод DLSS-IV добавляет DLSS 4, FSR 3, DLAA и HDR. Найти его можно на Nexus Mods, но для работы потребуется Fusion Fix.

Final validation (terminal - no second correction):
- caption sentence is a list of names, not a sentence that adds context: 'Мод DLSS-IV добавляет DLSS 4, FSR 3, DLAA и HDR.' - it repeats the slides' list
- semantic review: slides 4 and 5 make the same point in different words (Both slides state that DLSS-IV requires Fusion Fix to work) - merge them into one slide, then use the freed slide for another distinct grounded fact or make the carousel shorter

## First remaining divergence: the editorial correction

The correction fixed every initial finding (slide 1/2 thesis merged, list slide rewritten, filler and lifted wording gone, no caption moral), but kept 5 slides and refilled the freed slide with a restatement: slide 5 «Если ставить — ищи связку DLSS-IV + Fusion Fix» repeats slide 4's Fusion Fix requirement and slide 3's Nexus Mods. The caption re-lists slide 2's four technologies. The judge detected the new pair on the final pass; with one correction maximum the post is terminal. The story has about five distinct grounded beats; the Director did not take the 'make the carousel shorter' option.

Stopped per task: no second judge, no second rewrite retry, no rerun.
