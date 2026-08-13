# 1. Назначение документа

Этот документ определяет стратегию тестирования AI Newsroom MVP.

Цели:

- обеспечить стабильность системы;
- предотвратить критические ошибки;
- контролировать качество AI-ответов;
- снизить риск перерасхода ресурсов;
- подготовить проект к реальному использованию.

---

# 2. Основные принципы тестирования

---

# Principle 1

Каждый новый модуль должен иметь проверку.

---

Нельзя:

создать функцию и сразу использовать её в системе.

---

Правильно:

```
Создание функции

↓

Unit Test

↓

Интеграция

↓

Использование
```

---

# Principle 2

Тестируем не только код.

Также проверяем:

- данные;
- AI-ответы;
- стоимость;
- скорость;
- стабильность.

---

# Principle 3

MVP не требует 100% покрытия.

Приоритет:

критические процессы.

---

# 3. Testing Levels

Система использует 5 уровней проверки.

---

# Level 1

# Unit Testing

## Цель

Проверка отдельных функций.

---

Использовать:

```
pytest
```

---

Проверять:

- расчёт рейтинга;
- обработку данных;
- форматирование сообщений;
- работу сервисов.

---

Пример:

```
deftest_news_score():assertscore>0
```

---

# Обязательные Unit Tests

---

## News Processing

Проверить:

- создание новости;
- очистку текста;
- классификацию.

---

## Scoring System

Проверить:

- расчёт Score;
- приоритеты.

---

## Prompt Formatter

Проверить:

- правильный JSON;
- отсутствие пустых данных.

---

## Cost Tracker

Проверить:

- сохранение токенов;
- расчёт стоимости.

---

# Level 2

# Integration Testing

## Цель

Проверить взаимодействие компонентов.

---

Проверяем:

---

## Telegram → Backend

Сценарий:

```
Пользователь

↓

Команда /news

↓

Backend

↓

Ответ
```

---

## Collector → Database

Сценарий:

```
Источник

↓

Collector

↓

PostgreSQL
```

---

## AI → Database

Сценарий:

```
News

↓

LLM Gateway

↓

AI Result

↓

Database
```

---

# Level 3

# AI Quality Testing

## Цель

Проверять качество работы моделей.

---

AI тестируется отдельно.

---

# Проверяем:

## 1. Accuracy

Насколько правильно AI понял новость.

---

## 2. Structure

Ответ соответствует JSON.

---

## 3. Hallucination

Нет выдуманных фактов.

---

## 4. Style

Текст соответствует SMM-формату.

---

# AI Test Dataset

Создать набор:

```
test_news/
```

---

Содержит:

- реальные новости;
- сложные новости;
- ложные новости;
- дубликаты.

---

Минимум:

50 тестовых новостей.

---

# Level 4

# End-to-End Testing

## Цель

Проверить полный сценарий.

---

Основной сценарий:

```
Источник

↓

Collector

↓

Database

↓

Research

↓

Intelligence

↓

Scoring

↓

Digest

↓

Telegram
```

---

Успех:

пользователь получает готовую подборку.

---

# Level 5

# Production Testing

После запуска.

---

Контролируем:

- ошибки;
- скорость;
- расходы;
- стабильность.

---

# 4. Critical User Scenarios

---

# Scenario 1

## Получение новостей

Проверка:

Бот получает новые источники.

---

Ожидаемый результат:

Новости появляются в базе.

---

# Scenario 2

## Анализ новости

Вход:

новость.

---

Выход:

```
{
"summary":"",
"score":90
}
```

---

# Scenario 3

## Создание дайджеста

Команда:

```
/digest
```

---

Результат:

Telegram сообщение.

---

# Scenario 4

## Генерация поста

Пользователь:

нажимает:

"Создать пост"

---

Результат:

черновик.

---

# Scenario 5

## Ошибка AI

Если модель недоступна:

система:

- делает retry;
- пишет ошибку;
- уведомляет пользователя.

---

# 5. Error Testing

Проверить:

---

## AI API Error

Ситуация:

модель не отвечает.

---

Ожидается:

fallback или сообщение об ошибке.

---

## Database Error

Ситуация:

нет подключения.

---

Ожидается:

логирование.

---

## Telegram Error

Ситуация:

сообщение не отправилось.

---

Ожидается:

retry.

---

# 6. Cost Testing

Очень важный раздел.

---

Цель:

не допустить неконтролируемых расходов.

---

Проверять:

---

## Token Usage

Каждый запрос:

сохраняет:

```
input tokens

output tokens

total cost
```

---

## Daily Limit

Проверка:

если:

```
cost > limit
```

то:

- остановить дорогие операции;
- отправить уведомление.

---

# 7. Performance Testing

Для MVP:

цель:

1000 новостей в день.

---

Проверить:

---

## Collector

Может обработать:

1000 источниковых сообщений.

---

## AI Queue

Не ломается при:

100+ задачах.

---

## Database

Быстрый поиск новостей.

---

# 8. Logging & Monitoring

Каждый важный процесс пишет лог.

---

Формат:

```
TIME

SERVICE

ACTION

STATUS

ERROR
```

---

Пример:

```
12:00

AI_SERVICE

NEWS_ANALYSIS

SUCCESS

cost=0.02$
```

---

# 9. Test Environment

Использовать:

---

Development:

```
local Docker
```

---

Testing:

```
separate database
```

---

Production:

```
VPS
```

---

Нельзя:

тестировать на production базе.

---

# 10. CI Pipeline (MVP)

Минимальная автоматизация:

---

Перед каждым обновлением:

1. Запуск тестов.
2. Проверка ошибок.
3. Проверка форматирования.

---

Pipeline:

```
Git Push

↓

Tests

↓

Build

↓

Deploy
```

---

# 11. Code Quality Rules

Claude Code обязан соблюдать:

---

## Type Checking

Использовать:

```
mypy
```

---

## Formatting

Использовать:

```
black
```

---

## Linting

Использовать:

```
ruff
```

---

# 12. Definition of Test Complete

Функция считается готовой если:

✅ есть тест;

✅ тест проходит;

✅ ошибка обработана;

✅ есть логирование;

✅ документация обновлена.

---

# 13. MVP Release Checklist

Перед запуском проверить:

---

## Infrastructure

☑ Docker работает

☑ База подключена

☑ Redis работает

---

## Telegram

☑ Бот отвечает

☑ Команды работают

☑ Уведомления приходят

---

## News System

☑ Источники подключены

☑ Дубликаты удаляются

☑ Новости сохраняются

---

## AI

☑ Анализ работает

☑ Score считается

☑ Стоимость считается

---

## Content

☑ Создаётся пост

☑ Quality Check работает

---

# 14. Итог документа

AI Newsroom MVP считается качественным не тогда, когда он просто генерирует текст.

Он считается готовым, когда:

- данные корректны;
- AI работает предсказуемо;
- расходы контролируются;
- ошибки обрабатываются;
- команда может использовать систему каждый день.

---

# 15. Bug-to-Regression Rule (Newsroom Stability Harness, added post-Phase-19)

This section codifies the permanent project rule introduced with the Newsroom Stability Harness
(`tests/fixtures/news_golden_cases.json`, `tests/golden/`, `tests/test_news_golden_suite.py`,
`scripts/run_news_golden_suite.py` - see `docs/newsroom_stability_harness_checkpoint.md` for the
full design).

**Rule: every confirmed production/live NEWS defect must produce a permanent regression case
before the fix is considered complete.**

Process for a new defect going forward:

1. Capture real evidence (event/story/draft IDs, exact text, timestamps) from the live system or
   a forensic investigation - never invent evidence for a real-defect case.
2. Minimize/sanitize the evidence into a fixture entry in `tests/fixtures/news_golden_cases.json`
   (no secrets, no signed/private URLs where unnecessary, no unbounded raw dumps).
3. Where practical, confirm the fixture fails against the pre-fix code (proves the case actually
   exercises the defect, not an unrelated path).
4. Implement the narrowest safe fix (this project's `Zero Technical Debt Policy`, §16, and
   `Efficiency by Design`, §22, both apply unchanged).
5. Confirm the fixture passes against the fix.
6. The fixture stays in the corpus permanently - it is never deleted once a real defect is fixed,
   only ever joined by new cases.

A defect that cannot yet be fixed (a genuine known limitation, or one requiring a policy decision
out of the current phase's scope) still gets a fixture - marked `failure_class: "known_limitation"`
in the corpus, asserting the CURRENT, honest behavior. A known limitation must never be encoded as
if it were a passing, fixed case - see the corpus's own `cd_projekt_layoffs_known_limitation` and
`zoom_vulnerability_cross_publisher_same_story` entries for the established pattern (the latter
was itself discovered mid-harness-build: a second, previously-undocumented gap surfaced by simply
running the real scorer against real headline text, and was honestly recorded as a limitation
rather than forced to pass).

**Developer workflow** (replaces relying on a live canary as the first regression signal):

```
unit/integration tests
    ↓
golden NEWS regression suite  (python scripts/run_news_golden_suite.py)
    ↓
shadow/targeted validation (only where the golden suite cannot prove nuanced LLM prose quality)
    ↓
live acceptance
    ↓
deploy
```

Before a significant commit: targeted unit tests, the golden suite, Ruff/mypy/
`scripts/validate_architecture.py`. Before a deploy: the full relevant integration suite, the
golden suite, and the latest targeted/live acceptance status - never the golden suite alone (see
`docs/newsroom_stability_harness_checkpoint.md` §J for what it structurally cannot prove).