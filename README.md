# AI Newsroom Telegram SMM Assistant

AI-платформа для сбора, анализа и подготовки контента на основе новостей.
Полная документация проекта находится в [`docs/`](./docs).

## Статус

Реализована **Phase 1 — Project Foundation**: FastAPI-приложение, Docker-окружение,
конфигурация, логирование, асинхронное подключение к PostgreSQL и Redis, инфраструктура Alembic.

Модели базы данных, Telegram-бот, сбор новостей и AI-слой будут добавлены на следующих фазах
(см. `docs/12_MVP_Development_Roadmap_Execution_Plan.md`).

## Технологический стек (Phase 1)

- Python 3.12
- FastAPI + Uvicorn
- PostgreSQL + SQLAlchemy 2 (async, asyncpg)
- Alembic
- Redis
- Docker / Docker Compose
- pydantic-settings

## Запуск через Docker

1. Скопировать файл окружения:

   ```
   cp .env.example .env
   ```

2. Запустить систему:

   ```
   docker compose up --build
   ```

3. Проверить работу приложения:

   ```
   curl http://localhost:8000/
   ```

   Ожидаемый ответ:

   ```json
   {"status": "Application running"}
   ```

## Локальный запуск без Docker

Требуется локально запущенный PostgreSQL и Redis (либо `docker compose up postgres redis`).

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload
```

## Telegram Bot credentials

`bot/` использует только Telegram **Bot API** (`aiogram`) через одну переменную:

- `TELEGRAM_BOT_TOKEN` — получить у [@BotFather](https://t.me/BotFather) в Telegram (`/newbot`).

Токен читается исключительно из `.env` через `core.config.settings.telegram_bot_token`
(`bot/loader.py::create_bot()`) — нигде в коде не захардкожен. Если переменная не задана,
`create_bot()` явно падает с `RuntimeError` **при запуске**, а не при импорте модуля.

## Запуск Telegram-бота (Phase 3, polling)

Требуется заполненный `TELEGRAM_BOT_TOKEN` в `.env`. Единственный поддерживаемый способ запуска:

```bash
python -m bot.main
```

Запуск файла напрямую (`python bot/main.py`) не поддерживается — при таком вызове абсолютные
импорты пакета `bot` не резолвятся корректно.

Команды: `/start`, `/news`, `/digest`, `/status`, `/settings` — каждая отвечает заглушкой
"This functionality will be implemented in the next development phases." (см. `bot/handlers/`).

## Telegram Client credentials

`integrations/sources/telegram_source.py` (Source Collector) использует только Telegram
**Client API** (Telethon) — полностью отдельно от Bot API выше, три переменные:

- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — получить на https://my.telegram.org ("API development tools"),
  вписать в `.env` **до** следующего шага.
- `TELEGRAM_SESSION_STRING` — генерируется **один раз вручную**, локально, интерактивным логином:

  ```bash
  python -m scripts.create_telegram_session
  ```

  Скрипт спросит номер телефона, код из Telegram и (если включена двухфакторная аутентификация)
  пароль 2FA, затем выведет строку сессии в консоль. Скопируйте её в `TELEGRAM_SESSION_STRING`
  вручную — скрипт **не** пишет в `.env` сам и **не** создаёт файл `.session`: сессия существует
  только в памяти процесса как `StringSession`, коллектор никогда не генерирует её автоматически.

## Collector startup (Phase 4)

Один проход сбора новостей по всем активным источникам (`sources.active = true`):

```bash
python -m scripts.run_collector
```

Скрипт — тонкая обёртка; вся логика в `services/collector.py`.

## Importing production sources

Источники **не захардкожены** — загружаются из JSON-файла, который вы готовите отдельно:

```bash
python -m scripts.import_sources path/to/sources.json
```

Формат:
```json
{"sources": [{"name": "...", "type": "TELEGRAM", "url": "@channel", "category": "AI", "reliability_score": 0.8, "active": true}]}
```
Обязательные поля: `name`, `type`, `url`. Опциональные: `category`, `reliability_score`, `active`.

Импорт идемпотентен (upsert по `url`) — безопасно запускать повторно на обновлённом файле.
Итог выводится в лог: `created / updated / skipped / invalid` (см. `services/source_importer.py`,
`schemas/source_import.py`).

## Importing the newsroom_sources_v1 pack (Phase 4.1+)

Помимо ручного JSON выше, есть готовый пакет источников в `config/newsroom_sources_v1/`
(RSS/Atom, GitHub, Hacker News, arXiv и другие — часть из них пока `pending_adapter`,
см. `services/adapter_keys.py`):

```bash
python -m scripts.import_source_pack
```

Загружает и валидирует пакет через `services/source_registry.py` (Universal Source
Registry), затем импортирует только источники с реализованным адаптером через
`services/source_pack_importer.py`. Источники без адаптера не попадают в `sources` —
это ожидаемо, не ошибка. Итог: `submitted / pending_adapter / disabled / auth_excluded /
created / updated / skipped` в логе.

## Environment variables

| Переменная | Компонент | Обязательна для |
|---|---|---|
| `APP_NAME`, `APP_ENV`, `DEBUG`, `LOG_LEVEL` | `core/config.py` | всегда (есть дефолты) |
| `POSTGRES_HOST/PORT/USER/PASSWORD/DB` | `database/session.py` | БД, Alembic |
| `REDIS_HOST/PORT/DB` | `core/redis.py` | Redis-клиент |
| `TELEGRAM_BOT_TOKEN` | `bot/loader.py` | `python -m bot.main` |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING` | `integrations/sources/telegram_source.py` | `python -m scripts.run_collector` |
| `GITHUB_TOKEN` | `integrations/sources/github_source.py` | опционально — без него `github_api`-источники остаются `auth_excluded` при импорте пакета; сам GitHub API работает и без токена, но с лимитом 60 запросов/час вместо 5000 |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MAX_DAILY_AI_COST`, `MAX_MONTHLY_AI_COST` | зарезервировано | будущая AI-фаза, сейчас не используется |

Полный шаблон со всеми переменными и комментариями — `.env.example`.

## Структура проекта

```
app/                    # FastAPI приложение
bot/                     # Telegram-бот (aiogram 3, Bot API, polling), Phase 3
core/                    # Конфигурация, логирование, Redis-клиент
database/                # SQLAlchemy engine/session, Alembic миграции, ORM-модели
integrations/sources/    # Адаптеры источников новостей (Telegram Client API), Phase 4
services/                # collector.py, cleaning.py, deduplication.py, source_importer.py
schemas/                 # Pydantic-схемы на границах системы (адаптеры, импорт)
scripts/                 # CLI-точки входа (run_collector, import_sources)
docs/                    # Проектная документация (источник истины)
```

Остальные директории (`capabilities/`, `tests/`, `utils/`) зарезервированы под следующие
фазы разработки и пока не содержат кода.

## Известные ограничения Phase 1

- Модели базы данных отсутствуют, миграций пока нет (`alembic revision` создаст первую
  миграцию, когда появятся модели в Phase 2).
- Telegram-бот, сбор новостей и AI-слой не реализованы.
- API ограничен единственным health-check эндпоинтом `GET /`.
