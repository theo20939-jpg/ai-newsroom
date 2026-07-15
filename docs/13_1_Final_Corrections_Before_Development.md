# 1. Назначение документа

Данный документ является финальным дополнением к технической документации проекта.

Цель:

зафиксировать обязательные исправления и уточнения перед началом разработки MVP.

Документ имеет приоритет над предыдущими документами в случае противоречий.

---

# 2. Основное название проекта

## Полное название:

```
AI Newsroom Telegram SMM Assistant
```

---

## Короткое название:

```
AI Newsroom
```

---

Все файлы, директории, переменные и документация должны использовать название:

```
AI Newsroom
```

---

# 3. Разделение Telegram Bot и Telegram Source Collector

В системе существуют два разных Telegram-компонента.

Они не должны смешиваться.

---

# 3.1 Telegram Bot

Назначение:

интерфейс общения с пользователем.

Использует:

```
Telegram Bot API
```

---

Функции:

- получение команд;
- отправка сообщений;
- кнопки;
- уведомления;
- взаимодействие с SMM-командой.

---

Пример:

```
Пользователь

↓

Telegram Bot

↓

AI Newsroom Backend
```

---

# 3.2 Telegram Source Collector

Назначение:

получение информации из Telegram-каналов.

Использует:

```
Telegram Client API
```

Через:

- Telethon;
- Pyrogram.

---

Функции:

- чтение каналов;
- получение постов;
- получение просмотров;
- получение реакций.

---

Пример:

```
Telegram Channel

↓

Telegram Client API

↓

News Collector

↓

Database
```

---

# 4. Финальная MVP архитектура

AI Newsroom MVP строится как единое backend-приложение.

---

Схема:

```
                    Sources

        Telegram Channels / RSS

                    ↓

            News Collector

                    ↓

            PostgreSQL

                    ↓

            Processing Pipeline

                    ↓

 ┌──────────────┬───────────────┐

 ↓              ↓               ↓

Research   Intelligence     Scoring

                    ↓

            Content Generation

                    ↓

             Quality Check

                    ↓

          Human Approval

                    ↓

            Telegram Bot

                    ↓

              SMM Team
```

---

# 5. MVP Database Scope

Документ Database Schema разделяется на две части.

---

# 5.1 MVP Tables

В первой версии создаются только:

---

## users

Хранит:

- Telegram пользователей;
- роли;
- настройки.

---

## sources

Хранит:

- источники новостей;
- тип источника;
- активность.

---

## news_events

Главная таблица новостей.

Хранит:

- название;
- текст;
- источник;
- категорию;
- дату;
- score.

---

## editorial_tasks

Хранит:

- задачи;
- статус обработки;
- workflow.

---

## ai_executions

Хранит:

- модель;
- токены;
- стоимость;
- результат.

---

## content_drafts

Хранит:

- созданный текст;
- статус;
- редакцию.

---

## human_feedback

Хранит:

- решение человека;
- опубликовано/нет;
- оценку результата.

---

# 5.2 Future Tables

Не входят в MVP:

---

## performance_metrics

Для расширенной аналитики.

---

## creative_assets

Для визуального контента.

---

## brand_voice

Для обучения стилю канала.

---

## vector_memory

Для долгосрочной памяти AI.

---

# 6. AI Architecture Correction

В проекте используется термин:

```
Capability
```

---

Не используется:

```
Agent
```

---

Причина:

AI-модули не являются автономными сущностями.

Они выполняют конкретные функции.

---

# MVP Capabilities:

---

## Research Capability

Анализ информации.

---

## Intelligence Capability

Определение значимости.

---

## Scoring Capability

Финальная оценка.

---

## Copywriting Capability

Создание текста.

---

## Quality Capability

Проверка результата.

---

# 7. LLM Gateway Correction

LLM Gateway является внутренним модулем backend.

---

Не является:

- отдельным микросервисом;
- отдельным сервером.

---

Структура:

```
Backend

 └── services/

        └── llm_gateway.py
```

---

Функции:

```
generate()analyze()summarize()
```

---

Все AI-вызовы проходят только через него.

---

# 8. Redis Usage Rules

Redis используется только для MVP задач.

---

Разрешённое использование:

---

## Temporary Storage

Временное хранение данных.

---

## Task Queue

Фоновые задачи.

---

## Rate Limiting

Ограничение запросов.

---

## Process State

Хранение состояния процессов.

---

Не использовать:

- Event Bus;
- сложную распределённую систему.

---

# 9. Cost Control Module

Добавляется внутренний модуль:

```
services/cost_tracker.py
```

---

Ответственность:

- считать токены;
- считать стоимость;
- хранить расходы;
- контролировать лимиты.

---

Каждый AI запрос сохраняет:

```
{
"model":"",
"input_tokens":0,
"output_tokens":0,
"cost":0,
"time":""
}
```

---

# 10. AI Budget Protection

Система должна иметь ограничение расходов.

---

Настройки:

```
MAX_DAILY_AI_COST=
MAX_MONTHLY_AI_COST=
```

---

При превышении:

1. Пользователь получает уведомление.
2. Система снижает использование дорогих моделей.
3. Требуется ручное подтверждение.

---

# 11. Final News Processing Pipeline

Каждая новость проходит строго следующий путь:

---

## Step 1

Collection

Получение новости.

↓

## Step 2

Normalization

Очистка и приведение формата.

↓

## Step 3

Deduplication

Удаление повторов.

↓

## Step 4

Research Capability

Анализ фактов.

↓

## Step 5

Intelligence Capability

Определение ценности.

↓

## Step 6

Engagement Analysis

Оценка реакции аудитории.

↓

## Step 7

Scoring Capability

Финальный рейтинг.

↓

## Step 8

Digest Generation

Формирование подборки.

↓

## Step 9

Copywriting Capability

Создание контента.

↓

## Step 10

Quality Capability

Проверка.

↓

## Step 11

Human Approval

Решение человека.

---

# 12. Human Feedback Purpose

Обратная связь пользователя сохраняется.

---

Используется для:

- оценки качества AI;
- улучшения scoring;
- улучшения промптов.

---

Минимальные данные:

```
{
"news_id":"",
"accepted":true,
"published":true,
"comment":""
}
```

---

# 13. Final MVP Restrictions

Claude Code запрещено создавать:

❌ микросервисы

❌ Kubernetes

❌ автономных AI-агентов

❌ автоматическую публикацию

❌ генерацию мемов

❌ сложную память

❌ обучение моделей

---

---

# 14. Source of Truth

При разработке порядок приоритета документации:

---

## 1 место

Document 13.1

Final Corrections

---

## 2 место

Document 10.1

MVP Constraints

---

## 3 место

Document 10

Claude Code Development Specification

---

## 4 место

Все остальные документы.

---

# 15. Финальная готовность к разработке

Перед началом кодинга проект имеет:

✅ описание продукта

✅ функциональное ТЗ

✅ архитектуру

✅ структуру базы данных

✅ API описание

✅ AI prompts

✅ план разработки

✅ стратегию тестирования

✅ ограничения MVP

---

# Итог

AI Newsroom MVP должен быть реализован как:

> простой, стабильный и расширяемый AI-инструмент для SMM-команды, который автоматизирует поиск, анализ и подготовку технологических новостей.
>