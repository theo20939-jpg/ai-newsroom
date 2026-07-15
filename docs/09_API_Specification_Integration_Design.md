# 1. Общая информация

## Назначение документа

Документ описывает:

- внутренние API;
- внешние интеграции;
- Telegram Bot интерфейс;
- форматы сообщений;
- события системы;
- взаимодействие AI-модулей.

---

# 2. API Architecture Overview

AI Newsroom использует гибридную архитектуру:

- REST API;
- Webhooks;
- Event Bus;
- Internal Service Communication.

---

Общая схема:

```
                 External Sources

                       ↓

                Collector Service

                       ↓

                  Event Bus

                       ↓

               Backend API

                       ↓

        ┌──────────────┼──────────────┐

        ↓             ↓              ↓

 Workflow        AI Runtime     Telegram

 Engine             |             Bot

                    ↓

              AI Providers
```

---

# 3. API Principles

---

# 3.1 REST First

Основное взаимодействие через REST API.

---

# 3.2 Async Processing

Все долгие задачи выполняются через очередь.

Например:

Не:

```
POST /generate
(wait 2 minutes)
response
```

---

А:

```
POST /tasks

↓

task_id

↓

background processing

↓

GET /tasks/{id}
```

---

# 3.3 JSON Everywhere

Все внутренние сообщения:

JSON.

---

# 3.4 Versioning

Все API имеют версию:

```
/api/v1/
```

---

# 4. Authentication

---

## Internal API

Использует:

- API Key;
- Service Token.

---

## Telegram Users

Авторизация:

через Telegram ID.

---

## Example

```
{
"user_id":12345,

"telegram_id":998877
}
```

---

# 5. Core API Endpoints

---

# 5.1 Task API

Управление задачами.

---

## Create Task

Создать задачу.

```
POST

/api/v1/tasks
```

---

Request:

```
{
"type":"NEWS_ANALYSIS",

"event_id":"123",

"priority":"A"
}
```

---

Response:

```
{
"task_id":"abc123",

"status":"CREATED"
}
```

---

# Get Task Status

```
GET

/api/v1/tasks/{task_id}
```

---

Response:

```
{
"id":"abc123",

"status":"RUNNING",

"current_step":"research"
}
```

---

# Cancel Task

```
POST

/api/v1/tasks/{id}/cancel
```

---

# 5.2 News API

---

## Get News Feed

```
GET

/api/v1/news
```

---

Parameters:

```
category=AI

limit=20

status=NEW
```

---

Response:

```
[
{
"title":"New AI Model",

"source":"OpenAI",

"score":87
}
]
```

---

# Get News Details

```
GET

/api/v1/news/{id}
```

---

# 5.3 Analysis API

---

Запуск AI анализа.

---

```
POST

/api/v1/analyze
```

---

Request:

```
{
"news_id":123,

"capabilities":

["research","intelligence"
]
}
```

---

Response:

```
{
"task_id":456
}
```

---

# 5.4 Content Generation API

---

Создание поста.

```
POST

/api/v1/content/generate
```

---

Request:

```
{
"task_id":456,

"format":"telegram_post",

"variants":3
}
```

---

Response:

```
{
"content_id":789
}
```

---

# 5.5 Quality API

---

Проверка контента.

```
POST

/api/v1/content/{id}/quality
```

---

Response:

```
{
"score":92,

"status":"APPROVED"
}
```

---

# 6. Capability Internal API

Все AI-модули используют единый интерфейс.

---

# Capability Request

```
{
"task_id":123,

"capability":"research",

"context":

{}

}
```

---

# Capability Response

```
{
"status":"success",

"result":{}

}
```

---

# 7. Workflow API

Управление процессами.

---

# Start Workflow

```
POST

/api/v1/workflows/start
```

---

Request:

```
{
"type":"daily_digest",

"priority":"A"
}
```

---

Response:

```
{
"workflow_id":555
}
```

---

# Workflow Status

```
GET

/api/v1/workflows/{id}
```

---

Response:

```
{
"status":"running",

"step":"copywriting"
}
```

---

# 8. Telegram Bot API Integration

## Назначение

Telegram является основным пользовательским интерфейсом.

---

# Telegram Flow

```
User

↓

Telegram

↓

Bot API

↓

Webhook

↓

FastAPI

↓

Workflow

↓

Response
```

---

# 9. Telegram Webhook

---

Endpoint:

```
POST

/api/v1/telegram/webhook
```

---

Telegram отправляет:

```
{
"update_id":12345,

"message":

{}

}
```

---

Backend:

1. проверяет пользователя;
2. определяет команду;
3. создаёт задачу;
4. отправляет ответ.

---

# 10. Telegram Commands

---

# /news

Получить последние новости.

Ответ:

```
🔥 TOP TECHNOLOGY NEWS

1. OpenAI release

Importance: 92

Why:

...

[Create Post]
```

---

# /digest

Создать дневную подборку.

---

# /trends

Показать тренды.

---

# /create

Создать контент.

---

Пример:

```
/create 123 meme
```

---

# /rewrite

Переделать текст.

---

# /status

Статус обработки.

---

# /settings

Настройки.

---

# 11. Telegram Interactive Actions

Используем Inline Buttons.

---

Пример:

```
🔥 AI NEWS

OpenAI released model

Score: 95

[Создать пост]

[Сделать мем]

[Игнорировать]

[Подробнее]
```

---

Actions:

```
CREATE_CONTENT

CREATE_MEME

IGNORE

DETAILS

APPROVE
```

---

# 12. News Source Integrations

---

# Telegram Sources

Получение:

- сообщений;
- просмотров;
- реакций.

---

Данные:

```
{
"channel":"example",

"views":50000,

"reactions":3000
}
```

---

# RSS

Используется для:

- сайтов;
- блогов;
- новостей.

---

# Web Sources

Используются:

- официальные сайты;
- документация.

---

# Social Sources

Будущее:

- X;
- Reddit.

---

# 13. AI Provider Integration

---

Используется:

LLM Gateway.

---

Не:

```
Backend → OpenAI
```

---

А:

```
Backend

↓

LLM Gateway

↓

OpenAI / Claude / Gemini
```

---

# AI Request

```
{
"model":"claude-sonnet",

"prompt":"...",

"max_tokens":2000
}
```

---

# AI Response

```
{
"text":"...",

"tokens":1500,

"cost":0.03
}
```

---

# 14. Event Bus Architecture

Система использует события.

---

# Event Format

```
{
"event":"NEWS_CREATED",

"id":123,

"time":"2026-07-13"
}
```

---

# Основные события:

---

## NEWS_CREATED

Новая новость.

---

## RESEARCH_COMPLETED

Завершён анализ.

---

## SCORE_CREATED

Получена оценка.

---

## CONTENT_CREATED

Создан контент.

---

## QUALITY_COMPLETED

Проверка завершена.

---

## CONTENT_PUBLISHED

Пост опубликован.

---

# 15. Notification System

Отправка уведомлений.

---

Типы:

---

## New Important News

```
🔥 Found important news
Score 95
```

---

## Content Ready

```
✅ Draft ready
```

---

## Error

```
⚠️ AI processing failed
```

---

# 16. Error Handling

Все API ошибки имеют единый формат.

---

Response:

```
{
"error":"AI_TIMEOUT",

"message":"Model unavailable",

"retry":true
}
```

---

# Error Types

```
AI_ERROR

DATABASE_ERROR

TELEGRAM_ERROR

TIMEOUT

RATE_LIMIT

VALIDATION_ERROR
```

---

# 17. Logging API

Все действия логируются.

---

Хранится:

- пользователь;
- запрос;
- результат;
- стоимость;
- ошибка.

---

Example:

```
{
"action":"generate_content",

"model":"claude",

"cost":0.05
}
```

---

# 18. API Rate Limits

Защита от перерасхода.

---

Telegram:

ограничения Telegram API.

---

AI:

лимиты бюджета.

---

Internal:

пример:

```
100 requests/minute
```

---

# 19.1 Configuration Principle

Запрещено:

хранить ключи внутри исходного кода.

---

Неправильно:

```
OPENAI_KEY="sk-xxxx"
```

---

Правильно:

```
OPENAI_KEY=os.getenv("OPENAI_KEY")
```

---

# 19.2 Environment Variables

Основной файл:

```
.env
```

---

Пример структуры:

```
# Application

APP_ENV=production

APP_PORT=8000

# Database

DATABASE_URL=

POSTGRES_USER=

POSTGRES_PASSWORD=

# Redis

REDIS_URL=

# Vector Database

QDRANT_URL=

QDRANT_API_KEY=

# Telegram

TELEGRAM_BOT_TOKEN=

TELEGRAM_WEBHOOK_URL=

# AI Providers

OPENAI_API_KEY=

ANTHROPIC_API_KEY=

GOOGLE_AI_KEY=

# Storage

S3_ENDPOINT=

S3_ACCESS_KEY=

S3_SECRET_KEY=

S3_BUCKET=
```

---

# 20. Telegram Integration Details

## Назначение

Telegram является основным каналом взаимодействия.

---

# 20.1 Bot Architecture

Используется:

Webhook Mode.

---

Почему не polling:

- хуже масштабируется;
- больше задержка;
- сложнее production.

---

Архитектура:

```

Telegram Server

        ↓

Webhook Request

        ↓

FastAPI Endpoint

        ↓

Command Handler

        ↓

Workflow Engine
```

---

# 20.2 Telegram Update Processing

Каждое сообщение проходит:

---

## Step 1

Получение update.

---

## Step 2

Проверка пользователя.

---

## Step 3

Определение действия.

---

## Step 4

Создание Task.

---

## Step 5

Запуск Workflow.

---

## Step 6

Ответ пользователю.

---

# 20.3 User Permission System

Доступ ограничивается через whitelist.

---

Таблица:

`users`

Поле:

```
permissions
```

---

Пример:

```
{
"news":true,

"generate":true,

"admin":false
}
```

---

# 21. News Sources Integration

## Назначение

Получение информации из внешних источников.

---

# 21.1 Source Collector Service

Отдельный сервис.

---

Функции:

- подключение источников;
- получение данных;
- нормализация;
- создание News Event.

---

Схема:

```

Source

↓

Collector

↓

Parser

↓

Normalizer

↓

News Event
```

---

# 21.2 Source Adapter Pattern

Каждый источник имеет свой адаптер.

---

Структура:

```
integrations/

    telegram_source.py

    rss_source.py

    web_source.py
```

---

Все используют интерфейс:

```
classSourceAdapter:fetch()parse()normalize()
```

---

# 21.3 Telegram Source Adapter

Получает:

- название канала;
- пост;
- дату;
- просмотры;
- реакции.

---

Пример:

```
{
"source":"TechChannel",

"text":"New AI model",

"views":70000,

"reactions":5000
}
```

---

# 21.4 RSS Adapter

Получает:

- заголовок;
- описание;
- ссылку;
- дату.

---

Пример:

```
{
"title":"New GPU announced",

"url":"https://..."
}
```

---

# 22. Social Engagement Analysis

Очень важная часть проекта.

---

## Цель

Определять не только:

"о чём говорят"

но:

"что реально вызывает реакцию".

---

# Engagement Pipeline

```

Source Data

↓

Metrics Collector

↓

Engagement Analyzer

↓

Ranking Engine
```

---

# Сбор данных:

- просмотры;
- лайки;
- комментарии;
- репосты;
- рост подписчиков.

---

# Engagement Score

Формула:

```
Engagement Score =

(View Quality)

+

(Reactions)

+

(Comment Rate)

+

(Share Rate)

+

(Channel Authority)
```

---

# Пример:

Новость А:

Источник:

1 млн подписчиков.

Просмотры:

50 000.

---

Новость Б:

Источник:

100 тыс подписчиков.

Просмотры:

80 000.

---

AI понимает:

Новость Б имеет более высокий потенциал.

---

# 23. AI Provider Integration

## Назначение

Единая точка работы с нейросетями.

---

# LLM Gateway Structure

```

Capability

↓

LLM Gateway

↓

Model Router

↓

Provider API
```

---

# 23.1 Model Router

Принимает решение:

какую модель вызвать.

---

Учитывает:

- задачу;
- Priority;
- стоимость;
- лимит.

---

Пример:

```
{
"task":"news_summary",

"priority":"B",

"selected_model":"small_llm"
}
```

---

# 23.2 Fallback System

Если модель недоступна:

---

Основная:

Claude Sonnet

↓

Ошибка

↓

GPT

↓

Ошибка

↓

Gemini

---

---

# 24. Internal Service Communication

Даже если сейчас MVP монолитный, архитектура должна поддерживать разделение.

---

Компоненты:

```
API Service

Worker Service

AI Service

Collector Service

Notification Service
```

---

# Communication Methods

---

Для MVP:

Internal Python Calls.

---

Для масштабирования:

REST / Message Queue.

---

# 25. Message Queue Design

Используется Redis Queue.

---

# Queue Types

---

## High Priority Queue

Новости уровня S.

---

## Normal Queue

Обычный анализ.

---

## Background Queue

Архивирование, embedding.

---

Пример:

```
{
"queue":"high",

"task":"research",

"priority":"S"
}
```

---

# 26. Scheduler System

## Назначение

Автоматические задачи.

---

Используется:

Celery Beat / APScheduler.

---

# Scheduled Jobs

---

## Daily Digest

Каждый день:

08:00

---

## Source Update

Каждые:

15 минут.

---

## Performance Analysis

Каждый день:

ночью.

---

## Memory Optimization

Раз в неделю.

---

# 27. MVP API Scope

В первой версии НЕ нужно реализовывать всё.

---

# Обязательные API:

---

## Telegram

```
POST /telegram/webhook
```

---

## News

```
GET /news
GET /news/{id}
```

---

## Tasks

```
POST /tasks

GET /tasks/{id}
```

---

## Content

```
POST /content/generate

GET /content/{id}
```

---

## Quality

```
POST /quality/check
```

---

# Не входит в MVP:

---

## Advanced Analytics API

Откладывается.

---

## Multi-channel API

Откладывается.

---

## Autonomous Publishing API

Откладывается.

---

# 28. API Security

---

# Authentication

Методы:

- Telegram ID verification;
- API keys.

---

# Authorization

Роли:

```
OWNER

ADMIN

MEMBER

VIEWER
```

---

# Input Validation

Все входные данные проходят:

- schema validation;
- sanitization.

---

# Rate Limiting

Защита:

- от спама;
- от случайных циклов;
- от перерасхода AI.

---

# 29. Final Integration Architecture

Итоговая схема:

```

                  NEWS SOURCES

 Telegram / RSS / Web / Social

                    ↓

              Collector Layer

                    ↓

              News Database

                    ↓

             Workflow Engine

                    ↓

              AI Runtime

        ┌───────────┼───────────┐

        ↓           ↓           ↓

   Research    Intelligence   Scoring

        ↓           ↓           ↓

        Copywriting + Creative

                    ↓

              Quality Layer

                    ↓

              Telegram Bot

                    ↓

              SMM TEAM
```

---

# 30. Итог документа

API Architecture AI Newsroom строится вокруг принципов:

- модульность;
- масштабируемость;
- контроль стоимости;
- независимость от AI-провайдера;
- безопасное взаимодействие;
- возможность постепенного расширения.

---