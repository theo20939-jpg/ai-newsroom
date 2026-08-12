# Phase 23.1M Final Polish — Golden Set Review (V8.3 vs V8.4)

Offline only — no Telegram sends. Full raw text: `scripts/_phase23_1m_v83_vs_v84_comparison.txt`.
All 8 golden-set outputs independently verified structurally sound: exactly 1 main-body paragraph
each, no `expandable_details` key present in any output.

---

## CASE 1 — Anti-recognition patterns (Flock-type)

**SOURCE FACTS:** A security specialist created patterns; the source's own headline quotes them
as claimed to be "invisible" to recognition cameras; usable on clothing/car paint; no mechanism,
test results, or independent verification given.

**V8.3:**
> **Специалист по безопасности создал узоры, заявленные как «невидимые» для камер с распознаванием**
>
> Специалист по безопасности разработал узоры, которые должны быть незаметны для камер с системами распознавания. Их можно использовать в одежде или наносить на автомобили, чтобы затруднить распознавание.

**NEW (V8.4):**
> **Специалист по безопасности создал узоры, которые должны мешать распознаванию камер**
>
> Специалист по безопасности разработал узоры, которые должны затруднять работу камер с системами распознавания. Их можно использовать в одежде и для окраски автомобилей.
>
> Принцип работы и результаты испытаний не раскрыты, поэтому эффективность разработки пока оценить нельзя.

Natural Russian: PASS | Headline semantic precision: **PASS (fixed)** | Body semantic precision: PASS | Calque: NO | Corporate filler: NO | Unnecessary phrase to delete: NO | Main body paragraphs: 1 | Chars: 202 → 168 (shorter)

**The specific residual defect flagged in the prior report — "«невидимые»" in the headline — is gone.** The headline now states the supported purpose/effect ("мешать распознаванию") instead of the disputed outcome-word, exactly matching the acceptance target's own direction without hardcoding that sentence.

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 2 — Intel $15B financing

**SOURCE FACTS:** Intel announced a $15B stock offering; proceeds go to "general corporate
purposes" including "maintaining a strong balance sheet"; INTC fell >3%; price/count/timing
undisclosed.

**V8.3:**
> **Intel объявила о размещении акций на $15 млрд**
>
> Intel объявила о размещении обыкновенных акций на $15 млрд. Компания направит привлечённые средства на общие корпоративные цели, в том числе на поддержание финансовой устойчивости. На фоне новости акции Intel подешевели более чем на 3%.

**NEW (V8.4):**
> **Intel объявила о размещении акций на $15 млрд**
>
> Intel объявила о размещении обыкновенных акций на $15 млрд. Компания направит выручку на общие корпоративные цели, в том числе на поддержание финансовой устойчивости. После объявления акции Intel подешевели более чем на 3%.
>
> Цена размещения, число акций и сроки сделки пока не уточняются.

Natural Russian: PASS | Headline semantic precision: PASS | Body semantic precision: PASS | Calque: **YES (residual)** | Corporate filler: **YES (residual)** | Unnecessary phrase to delete: YES — "общие корпоративные цели" still present | Main body paragraphs: 1 | Chars: 236 → 223 (shorter)

**Honest disclosure: this specific defect was NOT eliminated**, despite the new CORPORATE
ABSTRACT-NOUN FILTER rule directly targeting this exact pattern. "общие корпоративные цели"
survives verbatim from V8.3. A new, useful ending was added this time (disclosing the undisclosed
price/count/timing) which V8.3 did not have — a real improvement on completeness, but not the
targeted fix. This is the one remaining narrow, reproducible defect class this phase's own
recommendation names.

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 3 — Google Play / Venmo

**V8.3:**
> **Google Play добавил оплату через Venmo**
>
> Теперь покупки в Google Play можно оплачивать с баланса Venmo или со счетов, привязанных к этому сервису. Функция пригодится пользователям Venmo, которые покупают приложения и цифровой контент в Google Play.

**NEW (V8.4):**
> **В Google Play добавили оплату через Venmo**
>
> Покупки в Google Play теперь можно оплачивать балансом Venmo или счетами, привязанными к этому сервису. Функция упрощает оплату приложений и цифрового контента для пользователей Venmo.

Natural Russian: PASS | Headline semantic precision: PASS | Body semantic precision: PASS | Calque: NO | Corporate filler: NO | Unnecessary phrase: NO | Main body paragraphs: 1 | Chars: 207 → 184 (shorter)

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 4 — Armenia / Firebird

**V8.3:**
> **В Армении запустили первую очередь ИИ-центра Firebird, который NVIDIA называет крупнейшим в СНГ**
>
> Американская компания Firebird объявила о запуске в Раздане первой очереди дата-центра для ИИ, построенной за полгода на платформе NVIDIA. Объект рассчитан на размещение серверов для ИИ и дальнейшее масштабирование проекта.
>
> NVIDIA называет его крупнейшей ИИ-фабрикой в СНГ, однако независимого подтверждения этого заявления нет.

**NEW (V8.4):**
> **В Армении запустили первую очередь ИИ-центра Firebird**
>
> Американская компания Firebird объявила о запуске центра обработки данных для ИИ в Раздане. По словам NVIDIA, объект претендует на статус крупнейшей ИИ-фабрики в СНГ, а первую очередь построили за полгода.
>
> Независимого подтверждения этого лидерства нет, а мощность и число чипов в центре не раскрыты.

Natural Russian: PASS | Headline semantic precision: PASS (simpler, factual, unverified claim moved out of the headline into the body/ending where it's properly hedged with "по словам NVIDIA"/"независимого подтверждения... нет") | Body semantic precision: PASS | Calque: NO | Corporate filler: NO | Unnecessary phrase: NO | Main body paragraphs: 1 | Chars: 223 → 205 (shorter)

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 5 — Stack Overflow

**V8.3:**
> **Stack Overflow перевели в режим «только для чтения» на фоне падения трафика из-за ИИ**
>
> Форум для разработчиков Stack Overflow перевели в режим «только для чтения». В источнике это связывают с падением интереса к платформе из-за ИИ: число новых вопросов сократилось на 98,5% — со 109 тысяч в месяц в ноябре 2022 года до 1624 в месяц в 2025 году.

**NEW (V8.4):**
> **Stack Overflow перевели в режим «только для чтения» на фоне обвала числа вопросов**
>
> Число новых вопросов на Stack Overflow, по данным источника, сократилось на 98,5%: с 109 тысяч в месяц в ноябре 2022 года до 1624 в месяц в 2025 году. На этом фоне форум для разработчиков перевели в режим «только для чтения».
>
> Источник связывает падение активности с распространением ИИ, но причинная связь отдельно не подтверждена.

Natural Russian: PASS | Headline semantic precision: PASS | Body semantic precision: PASS (causal claim about AI moved to a properly-hedged ending instead of stated as fact in the body) | Calque: NO | Corporate filler: NO | Unnecessary phrase: NO | Main body paragraphs: 1 | Chars: 257 → 225 (shorter)

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 6 — Long March 7A (new, V8.4 only)

> **Китайская ракета Long March 7A взорвалась через 80 секунд после старта**
>
> Ракета Long March 7A взорвалась примерно через 80 секунд после старта с космодрома Вэньчан. Причина аварии пока неизвестна; среди возможных версий — проблема с одним из основных двигателей, которая при подтверждении может повлиять и на другие запуски Китая.

Natural Russian: PASS | Headline semantic precision: PASS | Body semantic precision: PASS | Calque: NO | Corporate filler: NO | Unnecessary phrase: NO | Main body paragraphs: 1 | Chars: 257

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 7 — Anthropic IPO (new, V8.4 only)

> **Anthropic готовит IPO, которое может стать крупнейшим в истории**
>
> Anthropic привлекает инвесторов перед возможным выходом на биржу этой осенью и подчёркивает быстрый рост. Компания также планирует ответить на усиливающуюся общественную критику ИИ. На встречах инвесторы спрашивали о китайских конкурентах, напряжённости эпохи Трампа и буме инфраструктуры для ИИ.
>
> Оценка компании, объём размещения и точные сроки IPO пока не раскрыты.

Natural Russian: PASS | Headline semantic precision: PASS ("может стать" preserves the planned/uncertain status, does not overstate) | Body semantic precision: PASS | Calque: NO | Corporate filler: NO | Unnecessary phrase: NO | Main body paragraphs: 1 | Chars: 296

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable

---

## CASE 8 — Visa/Mastercard warning (new, V8.4 only)

> **НСПК предупредила о возможных проблемах с онлайн-оплатой через Visa и Mastercard**
>
> НСПК сообщила, что при оплате в интернете картами Visa и Mastercard могут возникнуть сложности. Зарубежные браузеры из-за перехода на российские сертификаты безопасности могут показывать предупреждение о незащищённом соединении, однако сроки и масштаб проблемы пока не определены.

Natural Russian: PASS | Headline semantic precision: PASS | Body semantic precision: PASS | Calque: NO | Corporate filler: NO | Unnecessary phrase: NO | Main body paragraphs: 1 | Chars: 280

**HUMAN VERDICT:** [ ] Natural [ ] Awkward [ ] Precise [ ] Semantic drift [ ] Too long [ ] Publishable
