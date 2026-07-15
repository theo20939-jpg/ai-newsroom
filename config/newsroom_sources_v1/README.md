# Newsroom Sources Pack v1.0

Готовый конфигурационный пакет источников для существующего Newsroom Collector.

## Важно

Пакет **не меняет архитектуру проекта**. Он добавляет только:
- конфигурации источников;
- аккаунты для адаптеров X / Telegram / YouTube;
- ключевые слова;
- приоритеты;
- декларативную маршрутизацию в уже существующие стадии.

## Структура

- `sources/official.yaml` — официальные компании и блоги;
- `sources/media.yaml` — СМИ, агрегаторы и русскоязычные издания;
- `sources/github.yaml` — GitHub organisations, releases и trending;
- `sources/reddit.yaml` — сабреддиты через RSS;
- `sources/research.yaml` — arXiv и исследовательские базы;
- `sources/trends.yaml` — Product Hunt, Google Trends, Google News, GDELT, мемы;
- `sources/social.yaml` — конфигурации адаптеров X и Telegram;
- `sources/accounts.yaml` — handles/каналы для социальных адаптеров;
- `sources/keywords.yaml` — ключевые слова;
- `sources/custom.yaml` — пользовательские источники;
- `priorities.yaml` — шкала и поправки скоринга;
- `routing.yaml` — маршруты в существующие стадии;
- `source.schema.json` — JSON Schema записи источника.

## Минимальная интеграция

1. Скопировать папку в репозиторий, например `config/newsroom/`.
2. При старте Collector загрузить все `sources/*.yaml`.
3. Для каждой записи с `enabled: true` выбрать уже существующий адаптер по полю `type` или `adapter`.
4. Нормализовать результат в текущую модель новости.
5. Передать результат в существующий Deduplicator → Analyzer → Scorer.
6. Не создавать отдельные агенты или очереди ради этого пакета.

## Поля источника

- `id`: стабильный уникальный идентификатор;
- `type`: способ получения (`rss`, `atom`, `api`, `web_page` и др.);
- `adapter`: имя адаптера, если общего RSS/API загрузчика недостаточно;
- `priority`: базовый вес 0–100;
- `reliability`: доверие 0–1;
- `fetch_interval`: рекомендуемый интервал;
- `tags`: тематические метки;
- `auth`: имя необходимой переменной окружения;
- `notes`: технические ограничения.

## Рекомендуемые переменные окружения

```env
GITHUB_TOKEN=
YOUTUBE_API_KEY=
X_BEARER_TOKEN=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
PRODUCT_HUNT_TOKEN=
SEMANTIC_SCHOLAR_API_KEY=
```

## Проверка перед включением

Источники с `type: web_page` и `requires_adapter` требуют существующего разрешённого адаптера.
При недоступности URL источник должен отключаться автоматически после заданного количества ошибок, а не останавливать весь Collector.
RSS/Atom URL также следует проверять health-check'ом при деплое, поскольку сайты иногда меняют endpoints.

## Дедупликация

Рекомендуемый порядок:
1. canonical URL;
2. очищенный URL без UTM;
3. hash(normalized_title + source_domain);
4. semantic similarity заголовка/лида;
5. объединение перепечаток с сохранением официального первоисточника.

## Что считать первоисточником

Официальные страницы компаний имеют приоритет над СМИ и агрегаторами.
Google News, Techmeme и другие агрегаторы используются для обнаружения, но в итоговой карточке желательно сохранять ссылку на оригинальную публикацию.
