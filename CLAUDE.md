# CLAUDE.md

Этот файл — инструкция для Claude Code (claude.ai/code) по работе с этим репозиторием.

## Обзор

Отдельный микросервис-сокращатель ссылок. Принимает полную ссылку → отдаёт короткую
(`https://s.kybyshka-dev.ru/QfSaj`); по короткой делает **302**-редирект на исходную и считает клики.
Построен для подмены длинных трекинговых ссылок (напр. `t.leads.tech/click/...`) в VK-кампаниях/рассылках.

Это самостоятельный сервис, не часть основного бэкенда vktest2. Общается с внешним миром только по HTTP.

## Стек

FastAPI (Python 3.12) + SQLAlchemy 2 + PostgreSQL · Docker Compose · nginx (короткий домен).
Схема БД создаётся на старте через `Base.metadata.create_all()` — **Alembic намеренно не используется** (одна таблица).

## Структура

```
shortener/
├── app/
│   ├── main.py        # FastAPI-приложение, все 3 эндпоинта, lifespan (create_all)
│   ├── config.py      # Settings из переменных окружения (объект `settings`)
│   ├── database.py    # engine, SessionLocal, get_db(), Base
│   ├── models.py      # модель ShortLink + helper utcnow()
│   ├── schemas.py     # Pydantic ShortenRequest / ShortenResponse
│   ├── slug.py        # generate_slug() + множество RESERVED
│   └── auth.py        # require_api_key() — проверка заголовка X-API-Key
├── Dockerfile
├── docker-compose.yml # сервис shortener (порт 8080:8000) + своя Postgres
├── .env.example
├── deploy/nginx.short.conf  # server-блок короткого домена
└── README.md
```

## Эндпоинты (контракт API)

| Метод | Путь        | Auth         | Назначение |
|-------|-------------|--------------|------------|
| POST  | `/shorten`  | `X-API-Key`  | Создать/получить короткую ссылку (дедуп по hash). Тело `{full_link}`, ответ `ShortenResponse`. |
| GET   | `/{slug}`   | — (публично) | 302-редирект на `full_link` + инкремент `click_count`. 404 если слаг не найден. |
| GET   | `/health`   | —            | `{"status":"ok"}` для healthcheck. |
| GET   | `/docs`     | —            | Авто-Swagger (можно слать запросы из браузера, кнопка Authorize). |

`ShortenResponse`: `{ slug, short_url, full_link, click_count, created }`.
`created=true` — создана новая; `created=false` — вернули существующую (дедуп сработал).

## Функции (что где живёт)

- **`app/main.py`**
  - `lifespan(app)` — на старте создаёт таблицы (`create_all`).
  - `health()` — пинг.
  - `shorten(payload, db)` — считает `sha256(full_link)`, ищет дубль по `full_link_hash`; если нет — в цикле (до 10 попыток) генерит слаг и `INSERT`, ловит `IntegrityError` (коллизия слага ИЛИ гонка по hash) и ретраит. Защищён `Depends(require_api_key)`.
  - `redirect(slug, db)` — находит ссылку, **атомарным** `UPDATE ... click_count = click_count + 1` инкрементит счётчик, возвращает `RedirectResponse(status_code=settings.REDIRECT_STATUS)`.
  - `_response(link, created)` — собирает `ShortenResponse`, склеивает `short_url` из `SHORT_BASE_URL + slug`.
- **`app/slug.py`** — `generate_slug()`: `secrets.choice` по `SLUG_ALPHABET`, длина `SLUG_LENGTH`. `RESERVED` — имена, занятые явными роутами (`health`, `shorten`, `docs`, …), их нельзя выдавать как слаг.
- **`app/auth.py`** — `require_api_key()`: сравнивает заголовок `X-API-Key` с `settings.API_KEY` через `secrets.compare_digest` (constant-time). 500 если ключ не сконфигурирован, 401 если не совпал.
- **`app/models.py`** — `ShortLink` (таблица `short_links`), `utcnow()` (timezone-aware UTC).
- **`app/config.py`** — синглтон `settings`, все параметры из env.
- **`app/database.py`** — `get_db()` (FastAPI-зависимость, закрывает сессию в `finally`).

## Модель данных

Таблица `short_links`:
- `id` BigInteger PK
- `slug` String(32) **UNIQUE, indexed** — код в URL
- `full_link` Text — **полная ссылка целиком** (без разбора на маркеры)
- `full_link_hash` String(64) **UNIQUE, indexed** — `sha256(full_link)`, для дедупа (индекс по хешу быстрее, чем по TEXT)
- `click_count` BigInteger default 0
- `created_at` / `last_clicked_at` — timezone-aware UTC

## Команды

```bash
# Запуск (Docker)
cp .env.example .env        # вписать API_KEY и SHORT_BASE_URL
docker compose up -d --build

# Логи
docker compose logs -f shortener

# Доступ к БД
docker compose exec postgres psql -U shortener -d shortener

# Проверка синтаксиса
python3 -m py_compile app/*.py

# Локальный смоук-тест
curl -X POST http://127.0.0.1:8080/shorten \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"full_link":"https://example.com/long?a=1"}'
curl -sI http://127.0.0.1:8080/<slug>   # → 302 + Location
```

## Переменные окружения (`config.py`)

| Переменная        | По умолчанию                | Назначение |
|-------------------|-----------------------------|------------|
| `DATABASE_URL`    | `postgresql://shortener:shortener@postgres:5432/shortener` | Подключение к БД |
| `API_KEY`         | `""` (обязательно задать)   | Секрет для `POST /shorten`. Без него `/shorten` отдаёт 500 |
| `SHORT_BASE_URL`  | `http://localhost:8080`     | Базовый URL короткого домена, склеивается в `short_url` |
| `SLUG_LENGTH`     | `5`                         | Длина слага (52⁵ ≈ 380 млн комбинаций) |
| `SLUG_ALPHABET`   | `A–Z a–z`                   | Алфавит слага — **`[A-Za-z]`**, НЕ `[A-z]` (между Z и a в ASCII лежит мусор) |
| `REDIRECT_STATUS` | `302`                       | `302` — клики считаются и назначение можно менять; `301` кэшируется браузером (счётчик слепнет) |

## Ключевые решения и грабли

- **Полная ссылка хранится целиком**, не разбирается на маркеры (web_id/offer_id/sub*). Любой новый `sub8` проходит без правки схемы. Дедуп — по `sha256` от полной строки.
- **Дедуп идемпотентен и потокобезопасен.** Сначала lookup по `full_link_hash`; если параллельный запрос успел вставить — `IntegrityError` ловится, и из БД достаётся уже существующая строка.
- **Слаги** не могут совпасть с системными путями — список `RESERVED` в `slug.py`. При добавлении нового явного роута добавь его имя туда же.
- **`/{slug}` — catch-all в корне.** Явные роуты (`/health`, `/shorten`, `/docs`, `/openapi.json`) FastAPI регистрирует раньше и матчит первыми, поэтому коллизии нет. Любой неизвестный путь → 404 из `redirect()`.
- **302 vs 301.** По умолчанию 302, чтобы каждый клик проходил через сервис (счётчик + возможность сменить назначение). 301 браузер кэширует намертво.
- **Время — UTC** (timezone-aware), в отличие от основного проекта vktest2, где всё в МСК. Здесь сознательно UTC как стандарт для standalone-сервиса.
- **Миграций нет.** Меняешь модель → схема НЕ обновится сама на существующей БД (`create_all` создаёт только отсутствующие таблицы). Для изменения колонок — `ALTER` вручную или подключить Alembic.

## Деплой короткого домена

1. A/CNAME запись `s.kybyshka-dev.ru` → этот сервер.
2. `deploy/nginx.short.conf` → `/etc/nginx/conf.d/`, `nginx -t && systemctl reload nginx` (проксирует на `127.0.0.1:8080`).
3. TLS: `certbot --nginx -d s.kybyshka-dev.ru`.

## Интеграция с основным бэкендом (vktest2)

Основной бэкенд зовёт `POST /shorten` (внутренним адресом docker-сети `http://shortener:8000/shorten`
либо публичным `https://s.kybyshka-dev.ru/shorten`) с заголовком `X-API-Key`, забирает `short_url`.
Пример вызова — в `README.md`.
