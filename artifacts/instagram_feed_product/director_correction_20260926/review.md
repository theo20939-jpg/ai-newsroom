# ONE Director correction pass - founder review

## 1. Original Director output (saved GTA IV run, verbatim)

| # | headline | body |
|---|---|---|
| 1 | GTA IV: «лесенки» — всё, через 18 лет | Полноценное сглаживание появилось благодаря моддеру, а не Rockstar Games. |
| 2 | Апгрейд пришёл не от Rockstar | ПК-версия Grand Theft Auto IV наконец получила полноценное сглаживание — но не благодаря усилиям Rockstar Games. |
| 3 | DLSS-IV принёс сразу четыре технологии | Nvidia DLSS 4 · AMD FSR 3 · DLAA · HDR |
| 4 | Мод называется DLSS-IV | Его можно скачать на Nexus Mods. Классика получила апгрейд от сообщества — спустя почти два десятилетия. |

Caption: ПК-версия Grand Theft Auto IV спустя почти два десятилетия получила поддержку Nvidia DLSS 4, AMD FSR 3, DLAA и HDR. Мод DLSS-IV сделал ChunkLeChuck — и он доступен на Nexus Mods. Rockstar Games к этому апгрейду отношения не имеет.

## 2. Exact validation findings (zero-cost replay of that output - one structured correction, no longer terminal)

1. CreativeLanguageError: clearly English audience-facing field for locale=ru
2. slide 1 hook is a clipped fragment, not natural Russian: 'GTA IV: «лесенки» — всё, через 18 лет' - state the strongest concrete fact as a complete phrase
3. slide 3 body is a list of product names, not Russian prose: 'Nvidia DLSS 4 · AMD FSR 3 · DLAA · HDR' - say it as a sentence
4. slide 4 body: generic filler with no new fact: 'Классика получила апгрейд от сообщества — спустя почти два десятилетия.' - end on the real fact or its plain irony
5. anglicism 'Апгрейд' where Russian has a natural word (обновление / улучшение): 'Апгрейд пришёл не от Rockstar'
6. anglicism 'апгрейд' where Russian has a natural word (обновление / улучшение): 'Его можно скачать на Nexus Mods. Классика получила апгрейд от сообщества — спуст'
7. anglicism 'апгрейду' where Russian has a natural word (обновление / улучшение): 'ПК-версия Grand Theft Auto IV спустя почти два десятилетия получила поддержку Nv'
8. slides 1 and 2 make the same point (both state the same claim about games, iv, rockstar: благ, полн, сгла) - merge them or give the second a new fact

Correction note that the ONE retry would send:

```
EDITORIAL CORRECTION (your one correction attempt). The previous version was rejected by the editorial review. Rewrite the copy so that EVERY finding below is fixed. You may merge, reorder or drop slides to remove repetition (4-7 slides, each a distinct grounded beat) - never keep a slide only to preserve the count. Keep product and company names as they are; turn a list of names into a natural Russian sentence. Do not add any fact the evidence does not contain, and do not replace a finding with a new slogan.
1. CreativeLanguageError: clearly English audience-facing field for locale=ru
2. slide 1 hook is a clipped fragment, not natural Russian: 'GTA IV: «лесенки» — всё, через 18 лет' - state the strongest concrete fact as a complete phrase
3. slide 3 body is a list of product names, not Russian prose: 'Nvidia DLSS 4 · AMD FSR 3 · DLAA · HDR' - say it as a sentence
4. slide 4 body: generic filler with no new fact: 'Классика получила апгрейд от сообщества — спустя почти два десятилетия.' - end on the real fact or its plain irony
5. anglicism 'Апгрейд' where Russian has a natural word (обновление / улучшение): 'Апгрейд пришёл не от Rockstar'
6. anglicism 'апгрейд' where Russian has a natural word (обновление / улучшение): 'Его можно скачать на Nexus Mods. Классика получила апгрейд от сообщества — спуст'
7. anglicism 'апгрейду' where Russian has a natural word (обновление / улучшение): 'ПК-версия Grand Theft Auto IV спустя почти два десятилетия получила поддержку Nv'
8. slides 1 and 2 make the same point (both state the same claim about games, iv, rockstar: благ, полн, сгла) - merge them or give the second a new fact
```

Golden regression: DeepSeek PASS, Hamster PASS.

## 3. Live retest (same GTA IV story, same fresh 3DNews event)

- Phase A: **single** (MEME) -> viral rule -> carousel (path A)
- PHASE_A: OK, finish_reason=stop, output_tokens=727, $0.006807
- VISION: OK, finish_reason=stop, output_tokens=338, $0.002898
- DIRECTOR: OK, finish_reason=length, output_tokens=16000, $0.108821
- result: `creative_director_failed:CreativeDirectorUnavailableError`

**First divergence:** the INITIAL Director generation degenerated: valid JSON began (`{"editorial_decision":{"strongest_true_thing":"GTA IV получила полноценное сглаживание спустя 18 лет — не от Rockstar, а благодаря моддеру.","evidence":"E1 и E2 подтвержд`) and then, inside a string right after «лё», emitted 76,112 characters of tabs/spaces until max_tokens=16000 (finish_reason=length). The truncated output is correctly refused (CreativeDirectorUnavailableError, terminal). The correction pass never ran: there was no complete output to validate.

## 4. Corrected Director output / rendered carousel

None - the live run stopped before any validated output. No second live attempt (founder rule).

