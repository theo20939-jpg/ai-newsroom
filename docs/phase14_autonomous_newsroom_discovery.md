# Phase 14 — Autonomous Newsroom Loop: Discovery Lite

Только исследование. Код не менялся, миграции не создавались, новых архитектурных решений не
принималось. Все находки ниже основаны на прямом чтении текущего исходного кода (не на
предположениях и не на более ранних отчётах Phase 12/13, хотя они совпадают).

## 1. Current architecture map

```
Sources
  ↓
worker/main.py (worker/cycle.py) — Phase 12, отдельный контейнер automation_worker
  → services/collector.py → NewsEvent (status=NEW)
  → services/triage_orchestrator.py → EditorialTask(NEWS_ANALYSIS, CREATED)
  ↓
worker/analysis_main.py (worker/analysis_cycle.py) — Phase 13, отдельный контейнер news_analysis_worker
  → _select_eligible_task_ids() — SQL-запрос: CREATED + NEWS_ANALYSIS + свежесть ≤48ч
  → WorkflowRunner.run() — атомарный claim, затем 4 шага:
       research → intelligence → engagement_analysis → scoring
  → EditorialTask(NEWS_ANALYSIS, COMPLETED)
  ↓
  ??? — ЗДЕСЬ ЦЕПОЧКА ОБРЫВАЕТСЯ. Никакой код репозитория не читает
        EditorialTask(NEWS_ANALYSIS, COMPLETED) для последующего действия.
  ↓
scripts/run_content_generation.py — существует, но вызывается ТОЛЬКО вручную человеком
  (python -m scripts.run_content_generation <event_id>), никогда автоматически
  → workflow_service.create_task(CONTENT_GENERATION, CREATED)
  → WorkflowRunner.run() — research → intelligence → copywriting → quality
  → ContentDraftService.create_from_result() → ContentDraft(status="draft")
  ↓
bot/handlers/news.py (/news, только по запросу пользователя)
  → services/editorial_inbox_service.py::get_latest_editorial_cards()
  → SELECT ContentDraft JOIN EditorialTask WHERE status=COMPLETED, ORDER BY created_at DESC LIMIT 5
  → bot/formatting.py::render_editorial_card() → message.answer(html)
```

**Ключевое наблюдение**: три отдельных, уже работающих, независимых конвейера (Collector→Triage,
NEWS_ANALYSIS-worker, CONTENT_GENERATION-скрипт) существуют и по отдельности исправны. Между ними
нет ни одного автоматического перехода — каждая стрелка "?" на схеме выше требует либо человека
(`/news`, `python -m scripts.run_content_generation`), либо просто отсутствует.

## 2. Missing connections

Ровно два разрыва, оба подтверждены прямым чтением кода:

### 2.1. `NEWS_ANALYSIS COMPLETED` → `CONTENT_GENERATION` (создание задачи)

Не существует НИКАКОГО кода, который читает `EditorialTask.workflow["workflow_name"] ==
"NEWS_ANALYSIS"` и `status == COMPLETED` для последующего действия. `worker/analysis_cycle.py`
после `run_result.status == "COMPLETED"` только инкрементирует счётчик (`result.completed += 1`)
и переходит к следующей задаче в батче — это тупиковая ветка, без вызова, без записи, без
события.

`scripts/run_content_generation.py::run_content_generation_for_event(event_id, ...)` — уже
существующая, уже полностью рабочая функция, которая делает ВСЁ, что нужно после
`NEWS_ANALYSIS COMPLETED`: создаёт `CONTENT_GENERATION`-задачу, запускает `WorkflowRunner`,
создаёт `ContentDraft` — **в одном синхронном вызове**. Единственная проблема — её сейчас **некому
вызвать автоматически**. Это не архитектурный разрыв внутри `CONTENT_GENERATION`-инфраструктуры,
это разрыв **вызывающей стороны**.

### 2.2. `ContentDraft создан` → `Telegram-сообщение отправлено`

`ContentDraft` сейчас читается только `/news` — по запросу пользователя, в момент, когда
пользователь сам решил спросить. Никакого проактивного (push) отправителя не существует.

`bot/loader.py::create_bot()` — уже существующая, лёгкая, не требующая контекста `Message`
фабрика `Bot`. Её можно вызвать из любого процесса (в том числе из воркера) и получить рабочий
`Bot`-объект для `bot.send_message(chat_id, html)`. `bot/formatting.py::render_editorial_card()`
— чистая функция без зависимости от aiogram-типов, уже производит корректный HTML из
`EditorialInboxCard`. Обе части реиспользуемы без изменений.

**Чего действительно не хватает**: `chat_id` — куда слать. В `core/config.py` и `.env.example`
нет ни одного поля вида `telegram_chat_id`/`telegram_admin_chat_id`. Это не техническое
ограничение, а простое отсутствие одной строки конфигурации.

## 3. Recommended MVP implementation

### 3.1. CONTENT_GENERATION — переиспользовать без изменений

**Ответ на прямой вопрос "можно ли переиспользовать существующий код без изменения
архитектуры?" — да, полностью.** `run_content_generation_for_event(event_id)` уже принимает ровно
то, что есть после `NEWS_ANALYSIS COMPLETED` (`event_id`), и уже делает create+run+draft одним
вызовом. Менять `scripts/run_content_generation.py`, `services/content_draft_service.py` или
`workflows/definitions/content_generation.py` не требуется вообще.

**Минимальная точка входа**: прямой вызов `run_content_generation_for_event(event.id)` из нового
кода — не через CLI/subprocess, а как обычный `await` внутри нового воркера (та же функция уже
принимает `capability_registry`/`session_factory` как DI-параметры именно для такого
переиспользования — это уже предусмотрено, не изобретается заново).

### 3.2. Триггер после NEWS_ANALYSIS COMPLETED — не hook, не event bus, а отдельный polling-воркер

Прямая проверка кода (§2.1) показала: hook/event-точки в `WorkflowRunner`/`worker/analysis_
cycle.py` не существует, и добавлять её (сигналы, callback-и, event bus) — уже больше, чем
"простой надёжный вариант", который просил пользователь.

**Рекомендация**: НЕ встраивать вызов `run_content_generation_for_event()` прямо в `worker/
analysis_cycle.py` (это удвоило бы стоимость и время каждого цикла анализа и смешало бы две
ранее независимые ответственности — анализ и генерацию контента — в одном процессе, нарушая уже
установленный в Phase 12/13 принцип "один воркер — одна стадия"). Вместо этого — третий,
отдельный, аналогичный по конструкции воркер (см. §3.3), работающий тем же уже дважды
проверенным паттерном: SQL eligibility-запрос → атомарный claim → выполнение.

**Важный нюанс, которого нет в исходном вопросе пользователя**: `EditorialTask.status ==
COMPLETED` — состояние **постоянное**, не одноразовое событие. Если просто polling'ом искать
"`NEWS_ANALYSIS` задачи со `status=COMPLETED`", один и тот же результат будет находиться заново
**каждый цикл**, бесконечно, и `run_content_generation_for_event()` будет вызываться повторно для
уже обработанного события — реальный риск дублей (см. §5). Прямая проверка `_find_active_task()`
(services/workflow_service.py:89-106) подтвердила: защита от дублей там проверяет только
`CREATED`/`RUNNING` — статус `COMPLETED` НЕ защищён от повторного создания новой задачи для того
же `event_id`.

**Решение без новой таблицы/колонки** (соответствует ограничению "не создавать новую таблицу без
крайней необходимости"): eligibility-запрос нового воркера должен выбирать `NEWS_ANALYSIS`
задачи со `status=COMPLETED`, у которых **ещё нет** ни одной `EditorialTask` с
`workflow_name=CONTENT_GENERATION` для того же `event_id` (`NOT EXISTS`-подзапрос по уже
существующей связи `event_id`, без новых колонок и без новой таблицы) — тот же принцип, что уже
использует `_find_active_task()`, только проверка "существует ли ЛЮБАЯ, а не только активная"
задача.

### 3.3. Новый воркер — да, аналог `worker/analysis_main.py` возможен и рекомендован

```
worker/
    content_main.py      # аналог analysis_main.py: enabled/disabled loop, сигналы
    content_cycle.py      # аналог analysis_cycle.py: eligibility-запрос + цикл
```

`content_cycle.py` не переизобретает `WorkflowRunner`/`CapabilityExecutor` — он делает ровно то
же, что уже делает `run_content_generation_for_event()`, просто вызывая её в цикле по списку
`event_id`, найденных eligibility-запросом (§3.2), вместо того чтобы получать один `event_id` из
аргумента командной строки. Это **не новая архитектура** — переиспользование уже существующей
функции с новым источником входных данных.

**Почему именно так, а не полный аналог `worker/analysis_cycle.py::_select_eligible_task_ids()`
+ claim самой `EditorialTask`**: `run_content_generation_for_event()` уже сама атомарно создаёт
и обрабатывает `CONTENT_GENERATION`-задачу целиком (создание — это и есть момент "захвата" в
данном случае, т.к. `create_task()` — это `INSERT`, а не update существующей строки). Отдельный
`claim`-шаг для несуществующей ещё задачи не нужен — нужен только `event_id`-eligibility запрос,
описанный в §3.2.

### 3.4. Telegram-уведомление — новый маленький сервис, переиспользующий существующий рендер

```
services/
    telegram_notifier.py   # новый: send_editorial_card(bot, chat_id, draft, event)
```

Один новый файл. Внутри — переиспользование `bot/formatting.py::render_editorial_card()` и
`EditorialInboxCard` (та же сборка полей, что уже делает `editorial_inbox_service._to_card()`) +
`bot.send_message(chat_id, html, parse_mode=ParseMode.HTML)`. `Bot` создаётся через уже
существующий `bot/loader.py::create_bot()`, вызывается из `content_cycle.py` сразу после
успешного создания `ContentDraft` — без polling, без второго воркера, без очереди "к отправке":
отправка — последний шаг того же самого цикла, что создал черновик.

**Новая конфигурация** (`core/config.py`, без миграции — обычное поле `Settings`):
`telegram_notification_chat_id: int | None = None` — куда слать. Без него уведомление некуда
адресовать; отсутствует полностью на сегодняшний день (§2.2).

### 3.5. Итоговый минимальный список изменений

| Файл | Статус | Зачем |
|---|---|---|
| `worker/content_main.py` | новый | enabled/disabled loop, аналог `analysis_main.py` |
| `worker/content_cycle.py` | новый | eligibility-запрос (§3.2) + вызов `run_content_generation_for_event()` + вызов уведомления |
| `services/telegram_notifier.py` | новый | переиспользует `render_editorial_card`/`create_bot`, один новый вызов `send_message` |
| `core/config.py` | точечное изменение | 4-5 новых полей `Settings` (`content_generation_enabled`, poll interval, `telegram_notification_chat_id`, порог качества) — тот же паттерн, что уже 2 раза применялся в Phase 12/13 |
| `docker-compose.yml` | точечное изменение | один новый сервис `content_worker`, тот же паттерн, что `news_analysis_worker` |

Ничего в `workflows/`, `capabilities/`, `services/content_draft_service.py`,
`services/workflow_service.py`, `bot/formatting.py`, `bot/loader.py` менять не требуется.

## 4. Data flow after Phase 14

```
Sources
  ↓ (automation_worker, Phase 12, без изменений)
NewsEvent
  ↓ (Triage, без изменений)
EditorialTask(NEWS_ANALYSIS, CREATED)
  ↓ (news_analysis_worker, Phase 13, без изменений)
EditorialTask(NEWS_ANALYSIS, COMPLETED)  ← quality-сигнал уже здесь: step_results["scoring"]["score"]
  ↓
  [НОВОЕ] content_worker: eligibility-запрос
    WHERE workflow=NEWS_ANALYSIS AND status=COMPLETED
      AND score >= порог (config)
      AND NOT EXISTS(CONTENT_GENERATION задача для этого event_id)
  ↓
  [НОВОЕ] run_content_generation_for_event(event_id) — без изменений внутри
EditorialTask(CONTENT_GENERATION, CREATED → RUNNING → COMPLETED)
  ↓
ContentDraft(status="draft")
  ↓
  [НОВОЕ] services/telegram_notifier.py → bot.send_message(telegram_notification_chat_id, html)
Личный/рабочий чат получает готовую карточку без команды /news
```

`/news` продолжает работать как раньше (не меняется) — теперь просто показывает то же самое, что
уже было отправлено проактивно, плюс историю.

## 5. Risks

**Дубли**: без `NOT EXISTS`-проверки (§3.2) один и тот же `event_id` получит новую
`CONTENT_GENERATION`-задачу и новое Telegram-уведомление на каждом polling-цикле, бесконечно —
реальный, легко воспроизводимый риск, не гипотетический (прямо подтверждён отсутствием защиты в
`_find_active_task()`). Без этой проверки MVP нельзя считать безопасным для запуска.

**Повторный запуск workflow**: `run_content_generation_for_event()` сама по себе безопасна при
одиночном вызове (одна атомарная `create_task()` + один `WorkflowRunner.run()`), но если
content-воркер вызовет её дважды параллельно для одного и того же `event_id` (два независимых
цикла запроса в overlapping-режиме — маловероятно при последовательной обработке, но не
исключено при перезапуске процесса ровно в момент обработки), возможна гонка на уровне
`create_task()` → `_find_active_task()`, которая **не** защищена атомарным `UPDATE` (в отличие от
`WorkflowRunner.run()`'s собственного claim-механизма из Phase 13 M2) — это `SELECT`, затем
`INSERT`, не атомарно. При одном content-воркере, работающем последовательно (аналогично
`worker/analysis_cycle.py`'s собственному "no asyncio.gather" дизайну), риск практически нулевой,
но при нескольких одновременных экземплярах воркера — реальный.

**Стоимость AI**: каждая полная цепочка теперь — до 4 (NEWS_ANALYSIS) + до 4 (CONTENT_GENERATION,
research/intelligence/copywriting/quality) = до 8 реальных вызовов на одно событие, вместо 4.
Порог качества (`score >= X`) — единственный механизм ограничения того, сколько событий вообще
доходит до второй, более дорогой половины цепочки; без порога (или с порогом = 0) КАЖДОЕ
`NEWS_ANALYSIS COMPLETED` немедленно удваивает свою собственную AI-стоимость.

**Накопление очереди**: `NEWS_ANALYSIS COMPLETED` уже накапливается (подтверждено в Phase 13 M7 —
тысячи задач). Если content-воркер выключен дольше, чем `NEWS_ANALYSIS`-воркер работает,
"готовых к контент-генерации" `COMPLETED`-задач накопится столько же — при первом запуске
content-воркера eligibility-запрос без `LIMIT`/`batch_size`-подобного ограничения попытается
обработать их все разом. Тот же `batch_size`-паттерн, что уже есть в Phase 13
(`news_analysis_batch_size`), нужен и здесь.

**Telegram-flood/лимиты**: при первом включении, если накопилась очередь COMPLETED-задач с
высоким score, `content_worker` может попытаться отправить много сообщений подряд — Telegram
Bot API имеет собственные rate-limit'ы, не учтённые нигде в текущем коде (`bot/formatting.py`
решает только длину сообщения, не частоту отправки).

## 6. Explicitly NOT included

Ниже — то, что **сознательно** не входит в Phase 14 MVP и не рассматривалось как часть его
реализации:

- ❌ approval workflow (одобрение человеком перед генерацией/отправкой);
- ❌ кнопки approve/reject в Telegram;
- ❌ автопостинг в публичный канал — только личный/рабочий чат, только уже готовая новость;
- ❌ мемы;
- ❌ генерация изображений;
- ❌ новая таблица БД (используется только уже существующая связь через `event_id`);
- ❌ изменение существующих workflow-контрактов (`NEWS_ANALYSIS`, `CONTENT_GENERATION` — обе
  `WorkflowDefinition` остаются байт-в-байт неизменными);
- ❌ event bus / message queue / pub-sub система любого рода — только прямой вызов уже
  существующей функции внутри нового polling-цикла;
- ❌ атомарная гонка-защита для параллельных content-воркеров (см. Risk выше) — приемлема только
  при ОДНОМ работающем экземпляре `content_worker`, как и у `analysis_worker`/`automation_worker`
  сегодня;
- ❌ настройка порога качества "по умолчанию хорошо" — точное значение порога `score >= X` не
  определено этим документом, требует отдельного решения человека.

---

PHASE 14 DISCOVERY LITE COMPLETE — READY FOR REVIEW
