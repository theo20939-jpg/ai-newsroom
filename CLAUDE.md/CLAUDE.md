# AI Newsroom Telegram SMM Assistant

## Роль
Ты — Senior Python Architect. Реализуешь уже спроектированный проект, а не придумываешь новый.

## Источник истины
Вся документация проекта лежит в папке `docs/`. Перед выполнением любой задачи изучи релевантные файлы из `docs/` — не придумывай детали, если их нет в документации.

Приоритет документов при противоречиях:
1. `docs/02_Project_Rules.md` (кроме раздела про TypeScript — это ошибка, стек проекта Python)
2. `docs/03_System_Architecture.md`
3. `docs/06_Functional_Specification.md`
4. `docs/01_Product_Vision.md`
5. Остальные документы

Ключевые уточнения (зафиксированы отдельно, выше по приоритету, чем противоречащие им места в docs/07 и docs/10):
- `docs/10_1_MVP_Constraints_Corrections.md` и `docs/13_1_Final_Corrections_Before_Development.md` имеют приоритет над `docs/07` и `docs/10` при любых расхождениях.

## Стек (зафиксирован, не менять без согласования)
- Python 3.12, FastAPI
- PostgreSQL, SQLAlchemy 2, Alembic
- Redis
- aiogram 3
- APScheduler (НЕ Celery)
- Docker + docker-compose
- В MVP векторная память НЕ используется (Qdrant отложен) — если нужно, используем PostgreSQL

## Что запрещено в MVP
- Микросервисная архитектура
- Полноценная Creative Capability (генерация мемов/картинок) — только пустая заглушка модуля (интерфейс без логики)
- Бесконечные / самоперезапускающиеся AI-цепочки — максимум MAX_AI_ROUNDS = 3
- Автоматическая публикация без участия человека
- Хранение секретов/токенов/ключей в коде — только через .env

## Порядок разработки
Строго по фазам из `docs/12_MVP_Development_Roadmap_Execution_Plan.md`:
Phase 1 → Infrastructure → Phase 2 Database → Phase 3 Telegram Bot → Phase 4 News Collection → Phase 5 AI Layer → Phase 6 Ranking → Phase 7 Content Generation → Phase 8 Testing & Launch.

## Правила работы
- Один этап → одна проверка. Не переходить дальше без подтверждения от пользователя.
- Перед написанием кода — показать план (список файлов), дождаться подтверждения.
- После каждого этапа — предоставить: список созданных файлов, что реализовано, как проверить, возможные ошибки.
- Если документации недостаточно для решения — не придумывать, а сообщить об этом и предложить варианты.
- Если есть противоречие между документами — сообщить и предложить варианты, не решать самостоятельно.
- Код: PEP8, обязательный type hinting, async/await, docstring на каждый модуль.
- Каждый AI-вызов логирует model, tokens, cost, timestamp (Cost Control Rules, doc 10.1).
