# 1. Общая информация

## Название системы

AI Newsroom

---

## Тип системы

AI-powered Editorial Intelligence Platform.

---

## Архитектурный подход

Система строится на основе:

- Modular Architecture;
- Capability-based Design;
- Event-driven Processing;
- Human-in-the-loop Workflow;
- AI Provider Abstraction.

---

# 2. Главная архитектурная идея

AI Newsroom — это не один большой AI-агент.

Это система специализированных интеллектуальных модулей, которые работают последовательно.

---

Основная схема:

```
                 Data Sources

                      ↓

               Data Collection

                      ↓

              Event Processing

                      ↓

             Editorial Intelligence

                      ↓

              Content Generation

                      ↓

              Quality Control

                      ↓

                 Telegram
```

---

# 3. Архитектурные слои системы

Система разделена на 7 основных слоёв.

---

# Layer 1 — Interface Layer

Отвечает за взаимодействие пользователя.

Компоненты:

- Telegram Bot;
- Admin commands;
- SMM team interface.

---

# Layer 2 — Application Layer

Основная бизнес-логика.

Компоненты:

- Task Manager;
- Workflow Engine;
- Orchestrator;
- Policy Engine.

---

# Layer 3 — Intelligence Layer

AI-логика системы.

Компоненты:

- Research Capability;
- Intelligence Capability;
- Trend Analysis;
- Scoring;
- Copywriting;
- Creative;
- Quality.

---

# Layer 4 — Data Layer

Хранение информации.

Компоненты:

- PostgreSQL;
- Vector Database;
- Object Storage.

---

# Layer 5 — Integration Layer

Внешние подключения:

- Telegram API;
- News APIs;
- AI APIs;
- Social APIs.

---

# Layer 6 — Infrastructure Layer

Запуск системы:

- Server;
- Docker;
- Queue;
- Monitoring.

---

# Layer 7 — Security Layer

Защита:

- API keys;
- Access control;
- Logging;
- Encryption.

---

# 4. High-Level Architecture

Общая схема:

```

                    TELEGRAM

                       |
                       |

                 Telegram Bot API

                       |
                       |

              Backend Application

                       |
       ┌───────────────┼───────────────┐

       |               |               |

 Task Manager    Workflow Engine   Orchestrator

                       |

              Intelligence Layer

       ┌────────┬────────┬────────┬────────┐

    Research Intelligence Trend   Scoring

       └────────┬────────┬────────┬────────┘

              Content Layer

          Copywriting + Creative

                       |

                 Quality Layer

                       |

              Telegram Delivery
```

---

# 5. Backend Architecture

## Рекомендуемый стек

---

# Backend

Основной язык:

## Python

Причины:

- лучший AI ecosystem;
- много библиотек для LLM;
- удобная работа с API;
- быстрый MVP.

---

Framework:

## FastAPI

Используется для:

- API;
- webhook;
- внутренних сервисов.

---

# 6. Project Structure

Предлагаемая структура:

```
ai-newsroom/

│
├── app/
│
│── api/
│
│── core/
│
│── capabilities/
│
│── workflows/
│
│── models/
│
│── database/
│
│── integrations/
│
│── prompts/
│
│── services/
│
│── workers/
│
└── tests/
```

---

# Описание папок

---

## capabilities/

Содержит AI-модули.

Пример:

```
capabilities/

research/

intelligence/

trend/

copywriting/

creative/

quality/
```

---

## workflows/

Сценарии обработки.

Пример:

```
news_analysis_flow.py

daily_digest_flow.py

creative_flow.py
```

---

## prompts/

Центральное хранение промптов.

Пример:

```
research_prompt.md

copywriting_prompt.md

quality_prompt.md
```

---

## integrations/

Внешние сервисы.

Пример:

```
telegram.py

openai.py

anthropic.py

news_api.py
```

---

# 7. AI Provider Architecture

Очень важный принцип:

Мы НЕ привязываемся к одной нейросети.

Создаём слой абстракции.

---

Схема:

```

              AI Provider Interface

          /          |          \

       GPT        Claude      Gemini
```

---

# AI Provider Interface

Все модели должны поддерживать:

```
generate()analyze()summarize()embed()
```

---

# 8. Использование моделей

Разные задачи → разные модели.

---

# Research Capability

Задачи:

- анализ фактов;
- поиск противоречий.

Рекомендуемые модели:

- Claude Sonnet;
- GPT.

---

# Intelligence Capability

Задачи:

- глубокий анализ;
- контекст.

Рекомендуемые:

- Claude Sonnet;
- GPT-5.

---

# Trend Analysis

Задачи:

- классификация;
- оценка сигналов.

Использовать:

- небольшие модели;
- алгоритмы.

Не нужен дорогой LLM.

---

# Scoring Capability

Комбинация:

- алгоритмы;
- ML;
- LLM.

---

# Copywriting

Основная модель:

- GPT;
- Claude.

---

# Creative

Использовать:

текстовая модель:

- Claude/GPT

визуальная:

- Imagen;
- Flux;
- Midjourney.

---

# Quality

Использовать:

- отдельный LLM call;
- правила.

---

# 9. LLM Gateway

Создаём единый слой:

```
LLM Gateway
```

Он отвечает за:

- выбор модели;
- стоимость;
- лимиты;
- fallback.

---

Пример:

```
request:task="summarize_news"gateway:priority=Achoose:ClaudeSonnet
```

---

# 10. Prompt Architecture

Очень важный раздел.

Мы НЕ храним промпты внутри кода.

---

Структура:

```
Prompt

+

Context

+

Task

+

Rules

+

Output Schema
```

---

Пример:

```
SYSTEM:

Ты AI-редактор технологического канала.

CONTEXT:

Аудитория:
18-35

TASK:

Проанализируй новость.

RULES:

Не придумывай факты.

OUTPUT:

JSON Schema
```

---

# 11. Structured Output

Все AI ответы должны быть структурированы.

Не:

```
"Вот мой анализ..."
```

---

А:

```
{
"importance":90,
"reason":"AI market impact",
"confidence":0.87
}
```

---

Причины:

- легче обрабатывать;
- меньше ошибок;
- проще тестировать.

---

# 12. Memory Architecture

Память системы разделяется.

---

## Short-term Memory

Контекст текущей задачи.

Хранение:

Redis.

---

## Long-term Memory

История:

PostgreSQL + Vector DB.

---

# Типы памяти:

---

## Event Memory

Новости.

---

## Editorial Memory

Решения редакции.

---

## Content Memory

Созданные материалы.

---

## Performance Memory

Результаты публикаций.

---

# 13. Vector Database

Используется для:

- поиска похожих событий;
- анализа истории;
- поиска успешных форматов.

---

Рекомендуемые варианты:

- Qdrant;
- Weaviate;
- Pinecone.

---

Для MVP:

## Qdrant

Причины:

- open-source;
- дешёвый;
- простой deployment

---

# 14. Database Architecture

## Назначение

Data Layer отвечает за хранение всех данных системы:

- новостей;
- задач;
- AI-результатов;
- истории решений;
- статистики;
- настроек.

---

# Основная архитектура хранения

Используется комбинация нескольких типов хранилищ.

---

```

                 Application

                     ↓

        ┌────────────┼────────────┐

        ↓                         ↓

 PostgreSQL                 Vector Database

        ↓                         ↓

 Structured Data          AI Memory

                     ↓

              Object Storage

              Images / Files
```

---

# 14.1 PostgreSQL

Основная база данных.

Используется для:

- пользователей;
- задач;
- Workflow;
- новостей;
- результатов анализа;
- настроек.

---

## Основные таблицы

---

# users

Хранит пользователей системы.

```
id

telegram_id

usernamerole

created_at
```

---

# channels

Хранит подключённые Telegram-каналы.

```
id

name

telegram_chat_id

brand_voice_id

settings
```

---

# sources

Источники информации.

```
id

name

type

url

category

reliability_score
```

---

# news_events

Основная сущность новости.

```
id

source_id

title

description

url

category

published_at

status
```

---

# editorial_tasks

Задачи обработки.

```
id

event_id

priority

workflow

status

created_at
```

---

# ai_outputs

Все ответы моделей.

```
id

task_id

capability

model

input_tokens

output_tokens

costresult
```

---

# content_drafts

Созданный контент.

```
id

task_id

type

text

version

status
```

---

# quality_reports

Проверки.

```
id

content_id

score

issues

status
```

---

# performance_metrics

Результаты публикаций.

```
id

content_id

views

likes

shares

comments

engagement_rate
```

---

# 14.2 Vector Database

Используется для AI Memory.

---

Основная задача:

не хранить данные,

а обеспечивать смысловой поиск.

---

Пример:

Запрос:

> "Найди похожие новости про AI-гонку"
> 

Vector DB ищет:

- похожие события;
- похожие посты;
- похожие успешные форматы.

---

# Collections

---

## events_memory

История новостей.

---

## content_memory

История публикаций.

---

## editorial_memory

Решения редакции.

---

## creative_memory

Успешные креативы.

---

# Embedding Pipeline

Схема:

```

Text

↓

Embedding Model

↓

Vector

↓

Vector Database
```

---

# 14.3 Object Storage

Используется для:

- изображений;
- мемов;
- видео;
- файлов.

---

Варианты:

- S3;
- MinIO;
- Cloudflare R2.

---

Для MVP:

Cloudflare R2.

Причины:

- дешёвое хранение;
- простота;
- S3 совместимость.

---

# 15. Task Queue Architecture

## Назначение

AI-задачи не должны выполняться напрямую.

Причины:

- долгие операции;
- ошибки API;
- ограничение нагрузки;
- контроль стоимости.

---

Используем:

## Redis Queue

---

Архитектура:

```

User

 ↓

API

 ↓

Task Queue

 ↓

Workers

 ↓

AI Capability

 ↓

Database
```

---

# Workers

Отдельные процессы:

---

## Research Worker

Обрабатывает сбор информации.

---

## AI Worker

Работа с LLM.

---

## Creative Worker

Генерация визуалов.

---

## Notification Worker

Отправка Telegram сообщений.

---

# 16. Telegram Bot Architecture

## Назначение

Интерфейс взаимодействия команды.

---

# Используем:

Telegram Bot API.

---

Архитектура:

```

Telegram User

      |

      |

 Telegram Bot

      |

 Webhook

      |

 FastAPI Backend

      |

 Workflow Engine
```

---

# Основные функции бота

---

# Команды

```
/news

/trends

/digest

/create

/rewrite

/status

/settings
```

---

# Интерактивные кнопки

Пример:

Новость:

```
🔥 OpenAI released update

Score: 92

[Создать пост]

[Сделать мем]

[Игнорировать]
```

---

# Работа в группе

Бот добавляется:

- в SMM чат;
- в отдельную тему Telegram Topics.

---

Структура:

```
SMM TEAM

├── Новости
├── Аналитика
├── Креативы
├── На публикацию
└── Архив
```

---

# 17. API Architecture

## Назначение

Внутреннее взаимодействие компонентов.

---

# REST API

Основной интерфейс.

---

Примеры:

---

## Create Task

```
POST /tasks
```

---

## Get News

```
GET /news
```

---

## Generate Content

```
POST /content/generate
```

---

## Get Status

```
GET /tasks/{id}
```

---

# Internal API

Capability взаимодействуют через:

```
{
"task_id":"capability":

"input":"context":

}
```

---

# 18. Event Driven Architecture

Система работает через события.

---

Пример:

Появилась новость.

Создаётся событие:

```
{
"type":"NEWS_CREATED",

"id":123
}
```

---

Дальше:

```

NEWS_CREATED

↓

Research

↓

INTELLIGENCE_READY

↓

SCORING_READY

↓

CONTENT_CREATED

↓

QUALITY_COMPLETED
```

---

# 19. AI Cost Control Architecture

Очень важный раздел.

---

Каждый AI вызов проходит через:

```

Capability

↓

LLM Gateway

↓

Budget Manager

↓

AI Provider
```

---

# LLM Gateway отвечает:

- какую модель использовать;
- сколько токенов разрешено;
- можно ли повторить запрос;
- сколько это стоит.

---

# Cost Optimization Rules

---

## Rule 1

Маленькие задачи → маленькие модели.

---

Пример:

Классификация новости:

не GPT-5.

Использовать:

малую модель.

---

## Rule 2

Большие модели только для:

- анализа;
- генерации;
- важных событий.

---

## Rule 3

Кэширование.

Если новость уже анализировалась:

не делать повторный запрос.

---

# 20. Deployment Architecture

## MVP вариант

---

Сервер:

VPS.

Минимально:

```
2-4 CPU

8GB RAM

50GB SSD
```

---

# Docker Architecture

Все сервисы запускаются контейнерами.

---

docker-compose:

```
services:

backend

worker

postgres

redis

qdrant
```

---

# Production Architecture

Будущее:

```
Load Balancer

↓

Backend Cluster

↓

Workers

↓

Database Cluster
```

---

# 21. Security Architecture

---

# API Keys

Хранятся:

- Environment Variables;
- Secret Manager.

---

# Authentication

Telegram User ID whitelist.

---

# Logging

Хранить:

- запросы;
- ошибки;
- AI вызовы;
- расходы.

---

# Data Protection

- HTTPS;
- encryption;
- backup.

---

# 22. AI Runtime Architecture

## Назначение

AI Runtime — это слой, который управляет выполнением AI Capability.

Главная задача:

не дать AI работать хаотично.

Он контролирует:

- какой модуль вызвать;
- какую модель использовать;
- какой контекст передать;
- сколько ресурсов потратить;
- когда остановиться.

---

# Основной принцип

AI Runtime НЕ является самостоятельным агентом.

Это исполнительный слой.

---

Схема:

```

Workflow Engine

        ↓

AI Runtime

        ↓

Capability

        ↓

LLM Gateway

        ↓

AI Model
```

---

# 22.1 Capability Execution Flow

Каждая AI Capability выполняется по одинаковому шаблону.

---

Пример:

Research Capability.

---

## Step 1

Получение задачи.

```
{
task_id:123,

capability:"research"
}
```

---

## Step 2

Загрузка контекста.

Получаем:

- новость;
- источники;
- правила;
- историю.

---

## Step 3

Выбор модели.

LLM Gateway определяет:

```
task:

research

priority:

A

model:

Claude Sonnet
```

---

## Step 4

Формирование Prompt.

---

## Step 5

Вызов модели.

---

## Step 6

Валидация ответа.

---

## Step 7

Сохранение результата.

---

# 22.2 AI Runtime Components

---

# Context Manager

Отвечает за:

- сбор необходимой информации;
- ограничение размера контекста;
- удаление лишних данных.

---

# Prompt Builder

Создаёт итоговый prompt.

---

# Model Selector

Выбирает модель.

---

# Response Validator

Проверяет:

- JSON;
- структуру;
- обязательные поля.

---

# Cost Tracker

Считает:

- токены;
- стоимость;
- время.

---

# Memory Connector

Подключает:

- Vector DB;
- историю.

---

# 23. Prompt Engineering Architecture

## Назначение

Централизованная система управления промптами.

---

# Главный принцип

Промпты — это код.

Они должны:

- храниться;
- версионироваться;
- тестироваться.

---

# Prompt Structure

Каждый prompt состоит из блоков:

```

SYSTEM ROLE

+

CONTEXT

+

TASK

+

RULES

+

OUTPUT FORMAT
```

---

# SYSTEM ROLE

Определяет роль.

Пример:

```
Ты AI-редактор технологического Telegram-канала.
```

---

# CONTEXT

Данные:

- аудитория;
- бренд;
- история.

---

# TASK

Что сделать.

---

# RULES

Ограничения.

Пример:

```
Не придумывай факты.
Используй только подтвержденные данные.
```

---

# OUTPUT FORMAT

Всегда структурированный.

Например:

```
{
summary:"",
confidence:0
}
```

---

# 23.1 Prompt Repository

Структура:

```
prompts/

research/

 └── v1.yaml

intelligence/

 └── v1.yaml

copywriting/

 └── v1.yaml

creative/

 └── v1.yaml

quality/

 └── v1.yaml
```

---

# 23.2 Prompt Versioning

Каждый prompt имеет версию.

Пример:

```
name:

research_prompt

version:

1.2

created:

2026-07-01
```

---

Если новый вариант хуже:

можно откатить.

---

# 24. Model Selection Strategy

## Назначение

Выбирать оптимальную модель под задачу.

---

# Основное правило:

Самая дорогая модель не всегда лучшая.

---

# Model Routing

---

## Simple Tasks

Используются маленькие модели.

Примеры:

- классификация;
- категоризация;
- фильтрация.

---

## Medium Tasks

Средние модели.

Примеры:

- краткое содержание;
- анализ.

---

## Complex Tasks

Большие модели.

Примеры:

- стратегия;
- креатив;
- глубокий анализ.

---

# Пример:

```
task:

summarize_news

priority:

B

model:

small_llm
```

---

```
task:

create_viral_campaign

priority:

S

model:

large_llm
```

---

# 25. Learning Loop Architecture

## Назначение

Система должна улучшаться со временем.

---

# Цикл обучения:

```

Content Created

        ↓

Published

        ↓

Performance Data

        ↓

Memory

        ↓

Future Predictions
```

---

# Какие данные собираем:

---

## Content Performance

- просмотры;
- реакции;
- комментарии;
- репосты.

---

## Human Feedback

Команда оценивает:

- понравилось;
- не понравилось;
- исправлено.

---

## AI Prediction Accuracy

Сравнение:

ожидание vs результат.

---

# Example:

AI прогноз:

```
viral_score:

90
```

---

Факт:

```
engagement:

низкий
```

---

Система сохраняет:

```
prediction_error:

high
```

---

# 26. Testing Architecture

## Назначение

Проверка качества системы.

---

# 26.1 Unit Tests

Проверяют:

- функции;
- API;
- обработчики.

---

# 26.2 Capability Tests

Каждый AI-модуль тестируется отдельно.

---

Пример:

Research Capability:

Вход:

новость.

Ожидание:

структурированный отчёт.

---

# 26.3 Prompt Tests

Проверяем:

- качество ответа;
- формат;
- ошибки.

---

# 26.4 Integration Tests

Проверяем цепочку:

```
News

↓

Research

↓

Content

↓

Quality
```

---

# 27. Development Architecture for Claude Code

Этот раздел нужен непосредственно перед написанием кода.

---

# Главный принцип разработки

Сначала строим фундамент.

Не начинаем с AI.

---

# Этап 1

Backend Foundation

Создать:

- FastAPI;
- Docker;
- PostgreSQL;
- Redis.

---

# Этап 2

Telegram Integration

Создать:

- bot;
- webhook;
- команды.

---

# Этап 3

Source Collector

Создать:

- сбор Telegram каналов;
- RSS;
- хранение новостей.

---

# Этап 4

Workflow Engine

Создать:

- задачи;
- статусы;
- очереди.

---

# Этап 5

AI Layer

Подключить:

- LLM Gateway;
- prompts;
- Research.

---

# Этап 6

Content Generation

Добавить:

- Copywriting;
- Quality.

---

# Этап 7

Memory

Добавить:

- Vector DB;
- embeddings.

---

# Этап 8

Creative

Добавить:

- генерацию изображений;
- мемы.

---

# 28. MVP Technical Stack

Фиксируем:

---

## Backend

Python + FastAPI

---

## Database

PostgreSQL

---

## Queue

Redis

---

## Vector DB

Qdrant

---

## Storage

Cloudflare R2 / S3

---

## Containerization

Docker

---

## AI

LLM Gateway:

OpenAI API

Anthropic API

---

## Telegram

Telegram Bot API

---

## Deployment

VPS Linux

---

# 29. Финальная архитектурная схема

```
                    Telegram Users

                          ↓

                    Telegram Bot

                          ↓

                      FastAPI

                          ↓

              ┌───────────────────┐
              │ Application Core   │
              └───────────────────┘

Task Manager

Workflow Engine

Orchestrator

Budget Manager

                          ↓

              ┌───────────────────┐
              │ AI Runtime         │
              └───────────────────┘

Research

Intelligence

Trend

Scoring

Copywriting

Creative

Quality

                          ↓

             LLM Gateway + Providers

                          ↓

                 Data Layer

PostgreSQL

Redis

Qdrant

Storage
```

---

# 30. Итог документа

AI Newsroom строится как масштабируемая AI-платформа, где каждый интеллектуальный модуль отвечает за отдельную функцию.

Главное архитектурное решение:

не создавать одного "умного бота", а построить систему из контролируемых компонентов.

Это позволяет:

- контролировать стоимость;
- менять AI-модели;
- улучшать отдельные части;
- масштабировать систему;
- постепенно превращать её в автономного AI SMM-редактора.