# 1. Общая информация

## Назначение документа

Документ описывает структуру хранения данных AI Newsroom.

Основные задачи:

- определить сущности системы;
- определить связи между сущностями;
- определить формат данных;
- подготовить основу для PostgreSQL;
- определить структуру AI Memory.

---

# 2. Database Architecture

AI Newsroom использует гибридную архитектуру хранения данных.

---

## Основные хранилища:

```

                Application

                    ↓

        ┌───────────┼───────────┐

        ↓                       ↓

 PostgreSQL              Vector Database

        ↓                       ↓

Business Data          AI Memory

                    ↓

              Object Storage

            Images / Files
```

---

# 3. Database Responsibilities

---

# PostgreSQL

Используется для:

- пользователей;
- каналов;
- новостей;
- задач;
- Workflow;
- AI результатов;
- настроек;
- статистики.

---

# Vector Database

Используется для:

- семантической памяти;
- поиска похожих событий;
- анализа истории;
- обучения предпочтений.

---

# Object Storage

Используется для:

- изображений;
- мемов;
- видео;
- файлов.

---

# 4. Основные сущности системы

Общая схема:

```

User

 |

Channel

 |

Editorial Task

 |

News Event

 |

AI Processing

 |

Content

 |

Publication

 |

Performance
```

---

# 5. User Model

## Назначение

Хранение пользователей системы.

---

## Table:

`users`

---

## Fields

| Поле | Тип | Описание |
| --- | --- | --- |
| id | UUID | Уникальный ID |
| telegram_id | BIGINT | Telegram ID |
| username | VARCHAR | Имя пользователя |
| role | ENUM | Роль |
| permissions | JSON | Права |
| created_at | TIMESTAMP | Дата создания |

---

# Roles

```
OWNER

ADMIN

SMM_MEMBER

VIEWER
```

---

# Example

```
{
"id":"123",

"telegram_id":555555,

"role":"ADMIN"
}
```

---

# 6. Channel Model

## Назначение

Хранение информации о канале, для которого работает AI Newsroom.

---

## Table:

`channels`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| telegram_chat_id | BIGINT |
| name | VARCHAR |
| description | TEXT |
| brand_voice_id | UUID |
| settings | JSON |
| created_at | TIMESTAMP |

---

# Settings Example

```
{
"language":"ru",

"emoji_level":"medium",

"tone":"expert",

"posting_frequency":"daily"
}
```

---

# 7. Source Model

## Назначение

Источники информации.

---

## Table:

`sources`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| name | VARCHAR |
| type | ENUM |
| url | TEXT |
| category | VARCHAR |
| reliability_score | FLOAT |
| active | BOOLEAN |

---

# Source Types

```
TELEGRAM

RSS

NEWS_API

WEB

SOCIAL
```

---

# Example

```
{
"name":"The Verge",

"type":"RSS",

"reliability_score":0.85
}
```

---

# 8. News Event Model

## Главная сущность системы

Каждая найденная новость становится объектом Event.

---

## Table:

`news_events`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| source_id | UUID |
| title | TEXT |
| summary | TEXT |
| content | TEXT |
| url | TEXT |
| category | ENUM |
| published_at | TIMESTAMP |
| collected_at | TIMESTAMP |
| hash | VARCHAR |
| status | ENUM |

---

# Categories

```
AI

GADGETS

TECH

STARTUPS

SOFTWARE

HARDWARE

CYBERSECURITY
```

---

# Status

```
NEW

PROCESSING

ANALYZED

REJECTED

ARCHIVED
```

---

# Example

```
{
"title":"OpenAI released new model",

"category":"AI",

"status":"ANALYZED"
}
```

---

# 9. Source Engagement Model

## Важная часть проекта

Мы добавляем аналитику активности источников.

Причина:

Одна и та же новость может иметь разный потенциал в зависимости от канала.

---

## Table:

`source_metrics`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| source_id | UUID |
| subscribers | INTEGER |
| avg_views | INTEGER |
| avg_reactions | INTEGER |
| avg_comments | INTEGER |
| engagement_rate | FLOAT |
| collected_at | TIMESTAMP |

---

# Engagement Rate

Формула:

```
(reactions + comments + shares)
/ views
```

---

# Example:

Канал А:

```
1 000 000 подписчиков

50 000 просмотров

ER 5%
```

---

Канал B:

```
100 000 подписчиков

30 000 просмотров

ER 30%
```

---

Система понимает:

Канал B имеет большее влияние.

---

# 10. Editorial Task Model

## Назначение

Центральная сущность Workflow.

---

## Table:

`editorial_tasks`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| event_id | UUID |
| priority | ENUM |
| workflow | JSON |
| status | ENUM |
| retry_count | INTEGER |
| created_at | TIMESTAMP |

---

# Priority

```
S

A

B

C
```

---

# Status

```
CREATED

RUNNING

WAITING

COMPLETED

FAILED
```

---

# Workflow Example

```
{
"steps":

["research","intelligence","copywriting","quality"
]
}
```

---

# 11. AI Execution Model

## Назначение

Хранение каждого вызова AI.

---

## Table:

`ai_executions`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| task_id | UUID |
| capability | ENUM |
| model | VARCHAR |
| prompt_version | VARCHAR |
| input_tokens | INTEGER |
| output_tokens | INTEGER |
| cost | FLOAT |
| response | JSON |
| created_at | TIMESTAMP |

---

# Capability

```
RESEARCH

INTELLIGENCE

TREND

SCORING

COPYWRITING

CREATIVE

QUALITY
```

---

# 12. Research Report Model

## Table:

`research_reports`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| task_id | UUID |
| facts | JSON |
| sources | JSON |
| contradictions | JSON |
| confidence_score | FLOAT |
| created_at | TIMESTAMP |

---

# 13. Intelligence Report Model

## Table:

`intelligence_reports`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| task_id | UUID |
| importance | INTEGER |
| audience | JSON |
| angles | JSON |
| recommendation | TEXT |
| confidence | FLOAT |

---

# 14. Scoring Model

## Table:

`content_scores`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| task_id | UUID |
| audience_fit | INTEGER |
| virality_score | INTEGER |
| engagement_prediction | INTEGER |
| timeliness_score | INTEGER |
| recommended_format | VARCHAR |

---

# 15. Content Draft Model

## Table:

`content_drafts`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| task_id | UUID |
| type | ENUM |
| title | TEXT |
| body | TEXT |
| hashtags | JSON |
| version | INTEGER |
| status | ENUM |

---

# Content Types

```
POST

SHORT

ANALYSIS

MEME

VIDEO_SCRIPT
```

# 16. Creative Model

## Назначение

Хранение всех созданных AI креативов.

Используется для:

- мемов;
- изображений;
- визуальных концепций;
- видео-идей.

---

## Table:

`creative_assets`

---

## Fields

| Поле | Тип | Описание |
| --- | --- | --- |
| id | UUID | ID креатива |
| task_id | UUID | Связь с задачей |
| type | ENUM | Тип контента |
| concept | TEXT | Идея |
| prompt | TEXT | Prompt для генерации |
| asset_url | TEXT | Ссылка на файл |
| originality_score | FLOAT | Уникальность |
| trend_reference | JSON | Использованный тренд |
| status | ENUM | Статус |

---

# Creative Types

```
MEME

IMAGE

VIDEO

CAROUSEL

INFOGRAPHIC
```

---

# Status

```
IDEA

GENERATING

READY

APPROVED

REJECTED
```

---

# Example

```
{
"type":"MEME",

"concept":"AI заменяет рутинную работу",

"originality_score":92
}
```

---

# 17. Quality Report Model

## Назначение

Хранение результатов AI-проверки.

---

## Table:

`quality_reports`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| content_id | UUID |
| fact_score | INTEGER |
| style_score | INTEGER |
| engagement_score | INTEGER |
| creative_score | INTEGER |
| risk_score | INTEGER |
| overall_score | INTEGER |
| issues | JSON |
| recommendations | JSON |
| status | ENUM |

---

# Status

```
APPROVED

NEEDS_REVIEW

REJECTED
```

---

# Example

```
{
"overall_score":87,

"status":"NEEDS_REVIEW",

"issues":

["Possible exaggeration"
]
}
```

---

# 18. Publication Model

## Назначение

Хранение факта публикации.

---

## Table:

`publications`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| content_id | UUID |
| channel_id | UUID |
| telegram_message_id | BIGINT |
| published_at | TIMESTAMP |
| status | ENUM |

---

# Status

```
SCHEDULED

PUBLISHED

DELETED

FAILED
```

---

# 19. Performance Analytics Model

## Назначение

Сбор результата после публикации.

Это основа будущего обучения системы.

---

## Table:

`content_performance`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| publication_id | UUID |
| views | INTEGER |
| reactions | INTEGER |
| comments | INTEGER |
| shares | INTEGER |
| saves | INTEGER |
| engagement_rate | FLOAT |
| collected_at | TIMESTAMP |

---

# Engagement Formula

```
(reactions + comments + shares + saves)

/

views
```

---

# Example

```
{
"views":50000,

"engagement_rate":0.12
}
```

---

# 20. Editorial Feedback Model

## Назначение

Хранение оценки человека.

Очень важная таблица для улучшения AI.

---

## Table:

`human_feedback`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| content_id | UUID |
| user_id | UUID |
| action | ENUM |
| comment | TEXT |
| created_at | TIMESTAMP |

---

# Actions

```
APPROVED

EDITED

REJECTED

REQUEST_REWRITE
```

---

# Example

```
{
"action":"EDITED",

"comment":"Сделать меньше технических терминов"
}
```

---

# 21. Brand Voice Model

## Назначение

Хранение стиля канала.

---

## Table:

`brand_voice_profiles`

---

## Fields

| Поле | Тип |
| --- | --- |
| id | UUID |
| channel_id | UUID |
| tone | VARCHAR |
| style_rules | JSON |
| forbidden_words | JSON |
| preferred_formats | JSON |
| emoji_rules | JSON |

---

# Example

```
{
"tone":"expert but friendly",

"emoji_rules":"medium",

"forbidden_words":

["сенсация","шок"
]
}
```

---

# 22. AI Memory Architecture

Теперь самая важная часть.

Память AI разделяется на несколько уровней.

---

# 22.1 Event Memory

## Назначение

Память о событиях.

---

Хранит:

- новости;
- темы;
- связи;
- похожие события.

---

Хранится:

PostgreSQL + Vector DB.

---

Пример:

Запрос:

> "Что было похожее на запуск ChatGPT?"
> 

---

AI получает:

- предыдущие AI-релизы;
- реакцию аудитории;
- успешные публикации.

---

# 22.2 Editorial Memory

## Назначение

Память редакционных решений.

---

Хранит:

- какие новости выбирали;
- какие отклоняли;
- почему.

---

Пример:

```
{
"topic":"AI hardware",

"decision":"ignored",

"reason":"low audience interest"
}
```

---

# 22.3 Content Memory

## Назначение

Память созданного контента.

---

Хранит:

- тексты;
- форматы;
- заголовки;
- результаты.

---

Используется для:

- поиска успешных форматов.

---

# 22.4 Performance Memory

## Назначение

Память о результатах.

---

Пример:

AI знает:

```
Формат:

"сравнение"

↓

ER:

+35%
```

---

В будущем:

AI будет рекомендовать:

"Использовать формат сравнения".

---

# 23. Vector Database Schema

Используем:

## Qdrant

---

# Collections

---

# events_collection

Новости.

Payload:

```
{
"type":"news",

"category":"AI",

"importance":85
}
```

---

# content_collection

Посты.

Payload:

```
{
"format":"telegram_post",

"engagement":0.15
}
```

---

# creative_collection

Мемы.

Payload:

```
{
"type":"meme",

"performance":"high"
}
```

---

# editorial_collection

Решения.

Payload:

```
{
"decision":"approved",

"reason":"high relevance"
}
```

---

# 24. Database Relationships

Основные связи:

---

```

User

 |

 | 1:N

 ↓

Channel

 |

 | 1:N

 ↓

News Event

 |

 | 1:N

 ↓

Editorial Task

 |

 | 1:N

 ↓

AI Execution

 |

 | 1:1

 ↓

Research Report

 |

 | 1:1

 ↓

Content Draft

 |

 | 1:N

 ↓

Creative Asset

 |

 | 1:1

 ↓

Quality Report

 |

 | 1:1

 ↓

Publication

 |

 | 1:1

 ↓

Performance
```

---

# 25. Index Strategy

Для производительности.

---

## news_events

Индексы:

```
category

published_at

status

source_id
```

---

## editorial_tasks

Индексы:

```
priority

status

created_at
```

---

## content_performance

Индексы:

```
publication_id

engagement_rate
```

---

# 26. Data Retention Policy

---

## Новости

Хранить:

12 месяцев.

---

## AI ответы

Хранить:

6 месяцев.

---

## Публикации

Бессрочно.

---

## Метрики

Бессрочно.

---

## Логи

30-90 дней.

---

# 27. Backup Strategy

---

PostgreSQL:

ежедневный backup.

---

Vector DB:

еженедельный snapshot.

---

Object Storage:

версионирование файлов.

---

# 28. Итоговая структура базы

```

                PostgreSQL

Users

Channels

Sources

News Events

Source Metrics

Editorial Tasks

AI Executions

Reports

Content

Creative Assets

Quality Reports

Publications

Performance

Feedback

Brand Voice

                Vector DB

Events Memory

Editorial Memory

Content Memory

Creative Memory

Performance Memory

                Storage

Images

Videos

Files
```