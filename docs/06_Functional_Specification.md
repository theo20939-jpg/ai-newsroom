## Назначение

AI Newsroom — это персональный Telegram-бот для SMM-команды, который автоматизирует процесс:

- поиска технологических новостей;
- анализа инфополя;
- оценки интереса аудитории;
- подготовки контента;
- создания креативов;
- передачи готовых материалов команде.

Система предназначена для работы с Telegram-каналом пользователя и используется внутри рабочей SMM-команды.

---

# 2. Основная цель системы

Создать AI-редакцию, которая работает как цифровой SMM-аналитик:

- самостоятельно мониторит источники;
- понимает важность событий;
- анализирует тренды;
- прогнозирует эффективность контента;
- предлагает варианты публикаций;
- создаёт мемы и визуальные идеи;
- помогает команде быстрее реагировать на инфополе.

---

# 3. Основные принципы архитектуры

---

## 3.1 Human-in-the-loop

Система не публикует контент полностью самостоятельно.

Финальное решение принимает человек.

---

## 3.2 Capability-based Architecture

Система строится не вокруг AI-агентов, а вокруг Capability.

Capability — это функциональный модуль.

Пример:

```
Research Capability

↓

Copywriting Capability
```

Модель AI внутри Capability может меняться.

---

## 3.3 Deterministic + AI Layer

Архитектура разделена:

## Deterministic Layer

Отвечает за:

- правила;
- лимиты;
- маршрутизацию;
- бюджет;
- хранение данных.

---

## AI Layer

Отвечает за:

- анализ;
- генерацию;
- понимание контекста;
- создание креативов.

---

# 4. Общая архитектура системы

```
Sources

↓

Collector Layer

↓

Processing Layer

↓

Ranking Engine

↓

Editorial Core

↓

AI Intelligence Layer

↓

Quality Layer

↓

Human Review

↓

Telegram
```

---

# 5. Основные сущности системы

---

# 5.1 Editorial Event

Единица информации.

Представляет собой найденную новость или инфоповод.

Хранит:

- источник;
- дату;
- тему;
- категорию;
- ключевые слова;
- метаданные.

---

# 5.2 Editorial Task

Задача обработки события.

Содержит:

- цель;
- Priority;
- Budget;
- Workflow;
- статус;
- историю изменений.

---

# 5.3 Research Report

Результат исследования новости.

---

# 5.4 Intelligence Report

Аналитическое понимание события.

---

# 5.5 Editorial Score

Прогноз эффективности будущего контента.

---

# 5.6 Draft Content

Созданный текстовый материал.

---

# 5.7 Creative Concept

Концепция визуального контента.

---

# 5.8 Quality Report

Результат проверки.

---

# 5.9 Editorial Memory

История решений и результатов.

---

# 6. Editorial Core

---

# 6.1 Editorial Task Manager

## Назначение

Управление жизненным циклом каждой задачи.

---

## Ответственность

- создание задач;
- хранение состояния;
- отслеживание Workflow;
- сохранение истории.

---

## Не отвечает за

- анализ;
- генерацию;
- публикацию.

---

## States

```
Created

↓

Processing

↓

Review

↓

Approved

↓

Completed

↓

Failed
```

---

# 6.2 Workflow Engine

## Назначение

Управление последовательностью обработки задач.

---

## Ответственность

- запуск Workflow;
- управление шагами;
- передача данных между Capability.

---

## Пример

```
Research

↓

Intelligence

↓

Scoring

↓

Copywriting

↓

Quality
```

---

# 6.3 Orchestrator

## Назначение

Главный исполнитель системы.

---

## Ответственность

- выполнение Workflow;
- вызов Capability;
- контроль состояния;
- обработка ошибок.

---

## Не отвечает за

- бизнес-решения;
- оценку важности.

---

# 6.4 Editorial Policy Engine

## Назначение

Система правил.

---

Определяет:

- что анализировать;
- какие Workflow использовать;
- какие ограничения применять.

---

Пример:

```
Priority A

↓

Research + Copywriting + Quality
```

---

# 6.5 Priority Manager

## Назначение

Определение редакционного приоритета.

---

## Priority Levels

### S — Critical

Максимальный ресурс.

---

### A — High

Полный Workflow.

---

### B — Normal

Ограниченная обработка.

---

### C — Low

Минимальная обработка.

---

## Ответственность

- назначение Priority;
- хранение причины;
- поддержка ручного изменения.

---

# 6.6 Budget Manager

## Назначение

Контроль стоимости AI-операций.

---

## Контролирует

- токены;
- количество вызовов;
- стоимость;
- время обработки;
- количество повторов.

---

## Budget Profile

### Priority S

```
20 AI calls
100k tokens
3 retries
```

---

### Priority A

```
10 AI calls
50k tokens
2 retries
```

---

### Priority B

```
5 AI calls
20k tokens
1 retry
```

---

### Priority C

```
1-2 AI calls
5k tokens
```

---

# 6.7 Retry Manager

## Назначение

Защита от бесконечных циклов.

---

## Контролирует

- повторные обработки;
- ошибки;
- возвраты между Capability.

---

## Ограничение

Максимальное количество циклов:

```
5 workflow cycles
```

---

После превышения:

```
STOP
```

---

# 6.8 Editorial Memory

## Назначение

Долгосрочная память редакции.

---

Хранит:

- новости;
- решения;
- контент;
- результаты публикаций.

---

## Типы памяти

### Event Memory

История событий.

### Editorial Memory

История решений.

### Content Memory

Созданные материалы.

### Performance Memory

Результаты публикаций.

---

# 7. Editorial Intelligence Layer

## Назначение

Editorial Intelligence Layer — это слой AI-возможностей системы.

Он отвечает за интеллектуальную обработку информации:

- понимание событий;
- анализ контекста;
- прогнозирование эффективности;
- генерацию контента;
- создание креативов;
- проверку качества.

---

# Архитектурный принцип

AI Capabilities не принимают глобальные решения.

Они выполняют конкретные функции внутри Workflow.

---

Общая схема:

```
Editorial Core

↓

AI Intelligence Layer

↓

Capabilities

↓

Result

↓

Quality Control
```

---

# 7.1 Research Capability

## Назначение

Исследование события и сбор дополнительной информации.

---

## Главный вопрос

> Что произошло?
> 

---

## Ответственность

Research Capability:

- анализирует источники;
- собирает факты;
- проверяет подтверждения;
- ищет связанные события;
- формирует Research Report.

---

## Источники

Использует:

- официальные сайты компаний;
- блоги;
- документацию;
- Telegram;
- Reddit;
- X;
- СМИ;
- научные публикации.

---

# Research Report

```
researchId:

eventId:

summary:

keyFacts:

sources:

sourceReliability:

timeline:

relatedEvents:

contradictions:

confidenceScore:
```

---

# Confidence Score

Оценивает достоверность информации.

---

Пример:

```
0.9-1.0

Высокая уверенность

0.7-0.9

Средняя

<0.7

Требует проверки
```

---

# Ограничения

Research Capability:

НЕ:

- пишет финальный пост;
- создаёт мемы;
- публикует;
- определяет Priority.

---

---

# 7.2 Intelligence Capability

## Назначение

Анализ значения события.

---

## Главный вопрос

> Почему это важно?
> 

---

## Ответственность

Intelligence Capability:

- анализирует контекст;
- определяет влияние;
- определяет аудиторию;
- создаёт варианты подачи.

---

# Основные функции

---

## Context Analysis

Определяет:

- исторический контекст;
- влияние на рынок;
- связь с конкурентами.

---

## Audience Relevance Analysis

Определяет:

кому интересна новость.

Пример:

```
audience:

developers

AI enthusiasts

investors
```

---

## Content Angle Generation

Создаёт возможные направления подачи.

Пример:

```
Почему это важно?

Что изменится?

Кто выиграет?
```

---

# Intelligence Report

```
intelligenceId:

eventId:

importanceAnalysis:

audienceSegments:

contentAngles:

trendConnections:

marketImpact:

editorialRecommendation:

confidenceScore:
```

---

# Ограничения

Intelligence Capability:

НЕ:

- собирает первичные данные;
- пишет финальный текст;
- создаёт изображения.

---

---

# 7.3 Trend Analysis Capability

## Назначение

Обнаружение и анализ трендов.

---

## Главный вопрос

> Что сейчас начинает становиться популярным?
> 

---

## Основная задача

Находить:

- быстрорастущие темы;
- вирусные события;
- новые инфоповоды.

---

# Trend Lifecycle

---

## Emerging

Тема только появляется.

---

## Rising

Активно растёт.

---

## Peak

Максимальная популярность.

---

## Declining

Интерес снижается.

---

# Trend Score

Формируется из:

```
Growth Rate

+

Engagement Growth

+

Source Spread

+

Audience Expansion

+

Freshness
```

---

# Opportunity Window

Определяет:

сколько времени осталось для реакции.

Пример:

```
trend:

AI video model

window:

3 hours
```

---

# Trend Signal

```
trendId:

topic:

keywords:

stage:

trendScore:

growthRate:

engagementRate:

sourceSpread:

opportunityWindow:
```

---

# Источники

Использует:

- Telegram;
- X;
- Reddit;
- поисковые тренды;
- новостные источники.

---

# Ограничения

Trend Analysis:

НЕ:

- создаёт контент;
- публикует;
- гарантирует вирусность.

---

---

# 7.4 Scoring Capability

## Назначение

Прогнозирование эффективности будущего контента.

---

## Главный вопрос

> Если мы сделаем материал — насколько хорошо он зайдёт?
> 

---

Важно:

Scoring Capability НЕ заменяет Ranking Engine.

---

## Ranking Engine

Оценивает:

"насколько важна новость"

---

## Scoring Capability

Оценивает:

"насколько хорошо зайдёт контент"

---

# Основные оценки

---

# Audience Fit Score

Соответствие аудитории.

---

# Virality Potential Score

Потенциал распространения.

---

# Engagement Prediction Score

Прогноз реакций.

---

# Timeliness Score

Актуальность момента.

---

# Format Match Score

Лучший формат подачи.

---

Пример:

```
post:

70

meme:

90

video:

95
```

---

# Editorial Score

```
scoringId:

audienceFitScore:

viralityScore:

engagementScore:

timelinessScore:

formatScores:

recommendedFormat:

confidence:
```

---

# Ограничения

Scoring:

НЕ:

- публикует;
- создаёт контент;
- гарантирует результат.

---

---

# 7.5 Copywriting Capability

## Назначение

Создание текстового контента.

---

## Главный вопрос

> Как правильно рассказать историю аудитории?
> 

---

# Создаёт

- Telegram-посты;
- заголовки;
- описания;
- короткие версии;
- аналитические материалы;
- CTA.

---

# Форматы

---

## News Post

Новостной формат.

---

## Analytical Post

Глубокий разбор.

---

## Short Update

Быстрая публикация.

---

## Viral Format

Эмоциональная подача.

---

## Comparison

Сравнение.

---

# Variant System

Для экономии бюджета:

---

Priority S/A:

3-5 вариантов.

---

Priority B:

1-3 варианта.

---

Priority C:

1 вариант.

---

# Brand Voice

Каждый канал имеет профиль:

```
tone:

style:

emojiLevel:

formality:

forbiddenWords:

preferredFormats:
```

---

# Draft Content

```
contentId:

format:

title:

body:

hashtags:

cta:

sourceLinks:

variant:
```

---

# Ограничения

Copywriting:

НЕ:

- проверяет факты;
- публикует;
- выбирает тему.

---

# 7.6 Creative Capability

## Назначение

Creative Capability отвечает за создание оригинального визуального и креативного контента на основе:

- технологических событий;
- трендов;
- мем-культуры;
- редакционной стратегии;
- Brand Voice.

---

# Главный вопрос

> Как превратить событие в контент, который люди захотят сохранить и переслать?
> 

---

# Основной принцип

Creative Capability **не копирует существующие мемы**.

Система использует:

- механику тренда;
- эмоциональный паттерн;
- структуру шутки;
- культурный контекст.

Но создаёт новый оригинальный контент.

---

Пример:

Плохо:

```
Вирусный мем

↓

Замена текста

↓

Публикация
```

---

Правильно:

```
Трендовый формат

↓

Анализ механики

↓

Новая идея

↓

Оригинальный визуал
```

---

# Responsibility

Creative Capability отвечает за:

- создание идей мемов;
- генерацию визуальных концепций;
- адаптацию трендов;
- подготовку Image Prompt;
- подготовку Video Prompt;
- создание креативных механик.

---

# Не отвечает за

Creative Capability НЕ:

- выбирает новости;
- проверяет факты;
- публикует контент;
- копирует чужие материалы.

---

# Creative Types

---

## 1. Reaction Meme

Использование эмоции:

- удивление;
- шок;
- радость;
- ирония.

---

## 2. Comparison Meme

Формат:

```
До

↓

После
```

---

Пример:

```
Работа до AI

vs

Работа после AI
```

---

## 3. Industry Meme

Профессиональный юмор.

Пример:

```
Когда CTO сказал:

"AI внедрим за неделю"
```

---

## 4. Trend Adaptation

Использование текущих вирусных механик.

---

## 5. Original Character

Создание фирменных персонажей канала.

---

# Trend Creative Signal

Для быстрого реагирования:

```
trendId:

visualPattern:

emotion:

format:

growthSpeed:

expirationTime:
```

---

Пример:

```
trend:

viral AI image

growth:

+500%

window:

4 hours
```

---

# Originality Check

Каждый креатив проходит проверку.

---

Проверяется:

- сходство с существующими мемами;
- повторение чужих изображений;
- уникальность идеи.

---

# Meme Similarity Score

```
similarityScore:
0-100
```

---

Правила:

```
0-30

Оригинально

30-70

Проверка

70+

Переделать
```

---

# Creative Concept Schema

```
creativeId:

taskId:

format:

idea:

emotion:

visualDescription:

caption:

generationPrompt:

trendReference:

originalityScore:
```

---

# Генерация изображений

Creative Capability создаёт:

не изображение напрямую,

а:

```
ImagePrompt
```

который передаётся в:

- Midjourney;
- DALL-E;
- Imagen;
- Flux;
- Stable Diffusion.

---

# Контроль стоимости

Количество генераций зависит от Priority.

---

Priority S:

5 вариантов.

---

Priority A:

3 варианта.

---

Priority B:

1 вариант.

---

Priority C:

без генерации.

---

# Metrics

- originality_score;
- creative_approval_rate;
- generation_cost;
- meme_performance;
- response_time.

---

# Ограничения

Creative Capability:

НЕ:

- заменяет редактора;
- гарантирует вирусность;
- копирует чужие мемы.

---

---

# 7.7 Quality Capability

## Назначение

Quality Capability является финальным AI-редактором системы.

Он проверяет готовый материал перед передачей SMM-команде.

---

# Главный вопрос

> Можно ли это отдавать в публикацию?
> 

---

# Проверяет

- факты;
- стиль;
- структуру;
- качество;
- креатив;
- риски.

---

# Responsibility

Quality Capability отвечает за:

- фактчекинг;
- проверку соответствия источникам;
- оценку качества текста;
- проверку мемов;
- поиск ошибок;
- создание Quality Report.

---

# Не отвечает за

Quality НЕ:

- пишет материал;
- выбирает тему;
- публикует;
- меняет стратегию.

---

# Quality Pipeline

---

## 1. Fact Check

Проверяет:

соответствие:

```
Research Report

↓

Draft Content
```

---

## 2. Style Check

Проверяет:

- Tone of Voice;
- формат;
- длину;
- стиль.

---

## 3. Engagement Check

Проверяет:

- силу первого экрана;
- наличие Hook;
- понятность.

---

## 4. Creative Check

Для мемов:

- оригинальность;
- понятность;
- соответствие теме.

---

## 5. Risk Check

Проверяет:

- спорные утверждения;
- юридические риски;
- репутационные угрозы.

---

# Quality Score

```
QualityScore =
Fact Accuracy

+

Style Match

+

Audience Fit

+

Creative Quality

+

Risk Score
```

---

# Quality Levels

---

## APPROVED

Можно передавать команде.

```
90+
```

---

## NEEDS_REVIEW

Нужна проверка человеком.

```
70-90
```

---

## REJECTED

Материал отклонён.

```
<70
```

---

# Quality Report

```
qualityId:

taskId:

factScore:

styleScore:

engagementScore:

creativeScore:

riskScore:

overallScore:

issues:

recommendations:

status:
```

---

# Retry Loop

Если качество низкое:

```
Copywriting

↓

Quality

↓

Ошибка

↓

Retry Manager

↓

Повтор
```

---

Ограничение:

```
max_cycles = 3
```

После превышения:

```
STOP
```

---

# Metrics

- approval_rate;
- rejection_rate;
- factual_error_rate;
- average_quality_score;
- human_edit_rate.

---

# Ограничения

Quality Capability:

НЕ:

- заменяет человека;
- публикует;
- меняет редакционную политику.

---

# 8. Telegram Integration Layer

## Назначение

Связь AI Newsroom с рабочим Telegram-пространством.

---

# Основной сценарий использования

Бот добавляется:

- в рабочую группу SMM;
- в отдельную папку/топик Telegram-группы.

---

# Структура работы

Пример:

```
SMM Team Chat

├── Общие обсуждения
│
├── Новости AI Newsroom
│
├── Мемы и креативы
│
├── Одобрено
│
└── Архив
```

---

# Функции Telegram Bot

---

## News Delivery

Бот отправляет:

- подборки новостей;
- аналитические сводки;
- тренды.

---

## Content Draft Delivery

Бот отправляет:

- готовые посты;
- варианты заголовков;
- креативы.

---

## Team Interaction

Команда может:

- одобрить;
- отклонить;
- запросить переделку;
- добавить комментарий.

---

## Commands

Пример:

```
/news

/trends

/top

/create

/rewrite

/status
```

---

# 9. Data Layer

## Назначение

Хранение всех данных системы.

---

# Основные базы

---

## Relational Database

Хранит:

- пользователи;
- задачи;
- Workflow;
- настройки.

---

## Vector Database

Хранит:

- память;
- контекст;
- историю решений.

---

## Object Storage

Хранит:

- изображения;
- видео;
- файлы.

---

# 10. Security Requirements

---

## SR-001

API ключи хранятся безопасно.

---

## SR-002

Доступ к боту ограничен.

---

## SR-003

История действий сохраняется.

---

## SR-004

Все внешние запросы логируются.

---

# 11. MVP Scope

## Назначение

MVP-версия должна проверить главную гипотезу:

> Может ли AI-помощник ускорить работу SMM-команды и находить более интересные технологические инфоповоды быстрее человека?
> 

---

# MVP НЕ должен включать сразу всю архитектуру.

Первая версия должна быть ограниченной по стоимости и сложности.

---

# MVP Functional Scope

---

# 11.1 Source Monitoring

## Реализовать:

- подключение выбранных Telegram-каналов;
- сбор RSS/News источников;
- сбор технологических новостей;
- категоризацию.

---

## Категории:

```
AI

Gadgets

Technology

Startups

Software

Hardware

Cybersecurity
```

---

# 11.2 News Processing

Бот должен:

- получать новости;
- очищать дубликаты;
- объединять похожие события;
- создавать краткую сводку.

---

# 11.3 Basic Ranking

Первая версия рейтинга:

```
Importance

+

Freshness

+

Engagement

+

Source Authority
```

---

# 11.4 AI Analysis

В MVP включить:

## Intelligence Capability

Функции:

- почему новость важна;
- кому интересно;
- варианты подачи.

---

# 11.5 Telegram Delivery

Бот отправляет:

ежедневные подборки:

Пример:

```
🔥 TOP AI NEWS TODAY

1. OpenAI выпустила обновление

Почему важно:

...

Потенциал:

High
```

---

# 11.6 Copywriting MVP

Создание:

- Telegram-поста;
- короткой версии;
- заголовков.

---

# 11.7 Quality Check MVP

Минимальная проверка:

- фактчекинг;
- стиль;
- ошибки.

---

# 11.8 Memory MVP

Сохранять:

- обработанные новости;
- созданные посты;
- реакции команды.

---

# Не входит в MVP

---

## Creative Capability

Полностью откладывается.

Причина:

дорогая генерация;

сложная проверка;

не является критическим ядром.

---

## Автопубликация

Не реализуется.

---

## Полное прогнозирование вирусности

Откладывается.

---

## Сложные агенты

Не используются.

---

# 12. Future Development Roadmap

---

# Phase 1

## AI News Collector

Срок:

MVP.

Функции:

- новости;
- анализ;
- подборки;
- Telegram.

---

# Phase 2

## Editorial Intelligence

Добавить:

- Scoring;
- Memory;
- более глубокий анализ.

---

# Phase 3

## Creative Engine

Добавить:

- мемы;
- визуалы;
- трендовые адаптации.

---

# Phase 4

## Autonomous SMM Assistant

Добавить:

- рекомендации;
- планирование контента;
- аналитику канала.

---

# Phase 5

## Multi-channel System

Поддержка:

- Telegram;
- X;
- Instagram;
- TikTok;
- YouTube.

---

# 13. System Limitations

---

# L-001

AI может ошибаться.

Все важные публикации проходят человека.

---

# L-002

Trend Score не гарантирует вирусность.

---

# L-003

Источники могут содержать недостоверную информацию.

---

# L-004

Стоимость AI зависит от количества обработки.

---

# L-005

Генерация контента требует контроля качества.

---

# 14. Success Metrics

---

# Product Metrics

---

## News Detection Speed

Скорость обнаружения новостей.

Цель:

уменьшить время реакции.

---

## Useful News Rate

Процент действительно полезных новостей.

---

## Human Approval Rate

Количество материалов, которые команда принимает.

---

Цель:

> 70%+ материалов требуют минимальных изменений.
> 

---

# Content Metrics

---

## Engagement Prediction Accuracy

Насколько прогноз совпадает с результатом.

---

## CTR Prediction

Точность прогнозирования интереса.

---

## Post Performance

Отслеживание:

- просмотров;
- реакций;
- репостов;
- комментариев.

---

# Operational Metrics

---

## AI Cost Per Day

Стоимость обработки.

---

## Processing Time

Время от новости до готового материала.

---

## Workflow Efficiency

Количество успешных задач.

---

# 15. Final System Architecture

Итоговая схема:

```
                         SOURCES

                            ↓

                  Source Collector Layer

                            ↓

                 Editorial Event Database

                            ↓

                  Ranking Engine

                            ↓

                Editorial Core Layer

                            ↓

              ┌─────────────────────┐
              │ AI Intelligence     │
              │ Layer               │
              └─────────────────────┘

Research Capability

        ↓

Intelligence Capability

        ↓

Trend Analysis Capability

        ↓

Scoring Capability

        ↓

Copywriting Capability

        ↓

Creative Capability

        ↓

Quality Capability

                            ↓

                    Human Review

                            ↓

                    Telegram Bot

                            ↓

                    SMM Team
```

---

# 16. Основные архитектурные решения

---

## Решение 1

Использовать Capability Architecture вместо набора автономных агентов.

Причина:

- меньше стоимость;
- больше контроль;
- проще разработка.

---

## Решение 2

Все AI-операции проходят через Budget Manager.

Причина:

контроль расходов.

---

## Решение 3

Все циклы имеют ограничение.

Причина:

защита от бесконечной генерации и расхода токенов.

---

## Решение 4

Human-in-the-loop обязателен.

Причина:

качество и безопасность.

---

## Решение 5

Memory является основой долгосрочного обучения.

Причина:

система должна понимать именно конкретный канал.