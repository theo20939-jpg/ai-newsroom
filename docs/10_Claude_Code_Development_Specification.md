# 1. Назначение документа

Данный документ является технической инструкцией для AI-разработчика Claude Code.

Цель:

Создать MVP AI Newsroom — Telegram-бота для личного использования SMM-команды, который:

- собирает новости из выбранных источников;
- анализирует их через AI;
- оценивает потенциал;
- формирует подборки;
- создаёт контент;
- отправляет результаты в Telegram.

---

# 2. Главный принцип разработки

Claude Code должен разрабатывать систему:

## Не как простой Telegram-бот.

А как:

> масштабируемую AI-платформу с модульной архитектурой.
> 

---

Запрещается:

- писать весь код в одном файле;
- смешивать бизнес-логику и API;
- хранить настройки внутри кода;
- создавать прямые зависимости между модулями.

---

# 3. Основные правила Claude Code

---

# Rule 1

Перед написанием кода:

обязательно анализировать архитектуру.

---

# Rule 2

Каждый новый модуль должен иметь:

- отдельную папку;
- описание назначения;
- тесты.

---

# Rule 3

Любое AI-взаимодействие должно идти через:

```
LLM Gateway
```

---

Запрещено:

```
openai.chat.completion()
```

напрямую внутри бизнес-логики.

---

Правильно:

```
llm_gateway.generate()
```

---

# Rule 4

Все данные проходят через:

Database Models.

---

Запрещено:

передавать случайные словари между сервисами.

---

Использовать:

Pydantic schemas.

---

# Rule 5

Все процессы должны иметь:

- логирование;
- обработку ошибок;
- retry.

---

# 4. Технологический стек

---

# Backend

Язык:

```
Python 3.12+
```

---

Framework:

```
FastAPI
```

---

# Telegram

Framework:

```
aiogram 3.x
```

---

# Database

Основная:

```
PostgreSQL
```

ORM:

```
SQLAlchemy 2.x
```

---

# Migration

```
Alembic
```

---

# Queue

```
Redis
```

---

# Background Jobs

```
Celery
```

или

```
APScheduler
```

---

# Vector Database

```
Qdrant
```

---

# Containerization

```
Docker
Docker Compose
```

---

# Testing

```
pytest
```

---

# Environment

```
Linux VPS
```

---

# 5. Project Structure

Claude Code должен создать:

```
ai-newsroom/

├── app/

│
├── api/

│   ├── routes/

│   └── dependencies/

│
├── bot/

│   ├── handlers/

│   ├── keyboards/

│   └── middlewares/

│
├── core/

│   ├── config.py

│   ├── security.py

│   └── logging.py

│
├── database/

│   ├── models/

│   ├── schemas/

│   └── migrations/

│
├── capabilities/

│   ├── research/

│   ├── intelligence/

│   ├── scoring/

│   ├── copywriting/

│   ├── creative/

│   └── quality/

│
├── workflows/

│
├── integrations/

│   ├── telegram/

│   ├── ai/

│   ├── rss/

│   └── storage/

│
├── workers/

│
├── prompts/

│
├── tests/

├── docker-compose.yml

├── Dockerfile

├── requirements.txt

└── README.md
```

---

# 6. Development Order

Очень важно.

Claude Code НЕ должен писать всё сразу.

Разработка идёт этапами.

---

# PHASE 1

# Project Foundation

Цель:

Создать основу.

---

Создать:

- FastAPI проект;
- Docker;
- PostgreSQL;
- Redis;
- конфигурацию;
- logging.

---

После завершения:

Проверить:

```
docker compose up
```

должен запускать систему.

---

# PHASE 2

# Database Layer

Создать:

Models:

- User;
- Channel;
- Source;
- NewsEvent;
- EditorialTask;
- AIExecution;
- ContentDraft.

---

Добавить:

- SQLAlchemy;
- Alembic;
- migrations.

---

Проверка:

создание таблиц.

---

# PHASE 3

# Telegram Bot Foundation

Создать:

- подключение бота;
- webhook;
- команды.

---

Минимальные команды:

```
/start

/news

/digest

/status

/settings
```

---

# PHASE 4

# Source Collector

Создать систему получения новостей.

---

Первый MVP источник:

Telegram channels.

---

Добавить:

- получение сообщений;
- сохранение;
- очистку;
- дедупликацию.

---

# PHASE 5

# Workflow Engine

Создать:

Task Manager.

---

Поддерживаемые процессы:

```
NEWS_ANALYSIS

CONTENT_GENERATION

DAILY_DIGEST
```

---

# PHASE 6

# AI Infrastructure

Создать:

## LLM Gateway

---

Поддержка:

```
OpenAI

Anthropic

Gemini
```

---

Функции:

```
generate()

analyze()

summarize()

embed()
```

---

# PHASE 7

# First AI Capability

Создать:

Research Capability.

---

Задача:

Получить новость:

↓

дать анализ:

↓

вернуть JSON.

---

Формат:

```
{
"summary":"",
"facts":[],
"confidence":0
}
```

---

# PHASE 8

# Intelligence Capability

Добавить:

- важность;
- аудиторию;
- потенциальный интерес.

---

Output:

```
{
"importance":90,

"why":"",

"audience":""
}
```

---

# PHASE 9

# News Ranking

Добавить:

Score Engine.

---

Формула:

```
Final Score =

AI Importance

+

Engagement

+

Source Authority

+

Freshness
```

---

# PHASE 10

# Telegram Digest

Создать:

автоматическую отправку подборки.

---

Формат:

```
🔥 TOP TECHNOLOGY NEWS

1.
Название

Почему важно:

Потенциал:

92/100

[Создать пост]
```

---

# PHASE 11

# Content Generation

Добавить:

Copywriting Capability.

---

Создаёт:

- посты;
- заголовки;
- описания.

---

# PHASE 12

# Quality Control

Добавить:

AI Reviewer.

---

Проверяет:

- факты;
- стиль;
- соответствие бренду.

---

# 7. Coding Standards

---

# Python Style

Использовать:

PEP8.

---

# Type Hinting

Обязательно:

```
defanalyze(news:NewsEvent) ->AnalysisResult:
```

---

# Async

Использовать:

async/await.

---

# Documentation

Каждый модуль:

docstring.

---

# 8. AI Code Rules

---

Claude Code должен:

НЕ создавать:

- автономные циклы AI;
- бесконечные цепочки агентов;
- самоперезапускающиеся процессы.

---

Любой AI Workflow должен иметь:

```
MAX_ITERATIONS
```

---

Например:

```
MAX_AGENT_ROUNDS=3
```

---

# 9. Cost Control Requirements

Каждый AI вызов обязан сохранять:

```
{
"model":"",
"tokens":"",
"cost":"",
"time":""
}
```

---

Все расходы должны быть видимы.

---

# 10. Prompt Management

Промпты:

НЕ внутри Python.

---

Хранятся:

```
prompts/
```

---

Формат:

```
.yaml
```

---

Пример:

```
name:

research_agent

version:

1.0

system:"Ты AI исследователь"

rules:

-"Не придумывай факты"
```

---

# 11. MVP Ограничения

Первая версия НЕ включает:

---

❌ Автоматическую публикацию

---

❌ Полную аналитику соцсетей

---

❌ Генерацию мемов

---

❌ Автономное обучение

---

❌ Multi-channel систему

---

Эти функции добавляются после стабильного MVP.

---

# 12. Первое сообщение Claude Code

При старте проекта использовать:

---

```
Ты являешься senior Python architect.

Создай проект AI Newsroom согласно технической документации.

Перед написанием кода:

1. Проанализируй архитектуру.
2. Создай структуру проекта.
3. Опиши план реализации.
4. Не пиши код до подтверждения.

Используй:
Python 3.12
FastAPI
PostgreSQL
Redis
Docker
SQLAlchemy
aiogram

Главный принцип:
модульная AI архитектура.
```

---

# 13. Definition of Done

Каждый этап считается завершенным только если:

✅ код работает

✅ есть тесты

✅ есть документация

✅ есть обработка ошибок

✅ есть логирование

✅ есть миграции БД

---

# 14. Итоговая цель MVP

После выполнения документа Claude Code должен создать систему, которая:

1. Получает новости.
2. Сохраняет их.
3. Анализирует через AI.
4. Оценивает потенциал.
5. Формирует подборки.
6. Отправляет их в Telegram.
7. Позволяет SMM-команде создавать контент.

---