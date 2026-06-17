# CLAUDE.md

Этот файл — инструкция для Claude Code (claude.ai/code) по работе с этим репозиторием.

## Обзор

Отдельный микросервис-сокращатель ссылок. Принимает полную ссылку → отдаёт короткую
(`https://go.kybyshka-dev.ru/QfSaj`); по короткой делает **302**-редирект на исходную и считает клики.
Построен для подмены длинных трекинговых ссылок (напр. `t.leads.tech/click/...`) в VK-кампаниях/рассылках.

**Мультидоменный** (несколько коротких доменов, каждый — независимый шортенер; домен берётся
из заголовка `Host`) и **прокидывает query**: per-user `sub`-параметры из короткой ссылки
вливаются в целевой URL при редиректе (главный сценарий — bothunter подставляет данные в query).

Это самостоятельный сервис, не часть основного бэкенда vktest2. Общается с внешним миром только по HTTP.

## Стек

FastAPI (Python 3.12) + SQLAlchemy 2 + PostgreSQL · Docker Compose · nginx (короткий домен).
Схема БД создаётся на старте через `Base.metadata.create_all()` — **Alembic намеренно не используется** (одна таблица).

## Структура

```
shortener/
├── app/
│   ├── main.py        # FastAPI-приложение, эндпоинты shorten/redirect/health, lifespan (create_all+сид), SessionMiddleware
│   ├── admin.py       # APIRouter /admin: управление доменами + статистика (Jinja2), логин
│   ├── templates/     # Jinja2-шаблоны админки (base/login/dashboard/domain_detail) + inline-CSS
│   ├── config.py      # Settings из переменных окружения (объект `settings`) + normalize_domain()
│   ├── database.py    # engine, SessionLocal, get_db(), Base
│   ├── models.py      # модели ShortLink, Domain + helper utcnow()
│   ├── schemas.py     # Pydantic ShortenRequest / ShortenResponse
│   ├── slug.py        # generate_slug() + множество RESERVED
│   └── auth.py        # require_api_key() — проверка заголовка X-API-Key
├── Dockerfile
├── docker-compose.yml # сервис shortener (порт 8080:8000) + своя Postgres
├── .env.example
├── deploy/nginx.short.conf  # server-блок коротких доменов (мультидомен, список server_name)
└── README.md
```

## Эндпоинты (контракт API)

| Метод | Путь        | Auth         | Назначение |
|-------|-------------|--------------|------------|
| POST  | `/shorten`  | `X-API-Key`  | Создать/получить короткую ссылку. Домен — из `Host`, дедуп по `(domain, hash)`. 400 если домен не активен в allowlist (БД). Тело `{full_link}`, ответ `ShortenResponse`. |
| GET   | `/{slug}`   | — (публично) | 302-редирект на `full_link` (с **влитым query** запроса) + инкремент `click_count`. Ищет по `(domain из Host, slug)`. 404 если слаг/домен не найден. |
| —     | `/admin`    | сессия       | Веб-админка (Jinja2): домены + статистика. Логин по `ADMIN_USERNAME`/`ADMIN_PASSWORD`, см. `app/admin.py`. |
| GET   | `/health`   | —            | `{"status":"ok"}` для healthcheck (доменно-независим). |
| GET   | `/docs`     | —            | Авто-Swagger (можно слать запросы из браузера, кнопка Authorize). |

`ShortenResponse`: `{ slug, short_url, full_link, click_count, created }`.
`created=true` — создана новая; `created=false` — вернули существующую (дедуп сработал).

## Функции (что где живёт)

- **`app/main.py`**
  - `lifespan(app)` — на старте `create_all` + `_seed_domains()` (сид allowlist из env, если таблица `domains` пуста).
  - подключает `SessionMiddleware` (кука админки) и `admin.router` (ДО catch-all `/{slug}`).
  - `health()` — пинг (доменно-независим).
  - `resolve_domain(request)` — нормализованный домен из заголовка `Host` (без проверки allowlist — её делают эндпоинты).
  - `_active_domain(db, domain)` — домен зарегистрирован в `domains` и `is_active` (используется в `shorten`).
  - `merge_query(stored_url, incoming_query)` — накладывает query короткой ссылки на целевой URL: входящие ключи перекрывают сохранённые, остальные (включая пустые `subN=`) остаются, новые добавляются (`urllib.parse`, `keep_blank_values=True`).
  - `shorten(payload, request, db)` — домен через `resolve_domain`; **гейт `_active_domain` (нет/неактивен → 400)**; дедуп по `(domain, full_link_hash)`; цикл (до 10 попыток) генерит слаг и `INSERT` с `domain`, ловит `IntegrityError` и ретраит. Защищён `Depends(require_api_key)`.
  - `redirect(slug, request, db)` — домен через `resolve_domain`; находит по `(domain, slug)` (неизвестный/неактивный домен → нет строк → 404, **без доп. запроса** — hot-path не нагружен); **атомарный** инкремент; редирект на `merge_query(full_link, request.url.query)`.
  - `_response(link, created)` — собирает `ShortenResponse`, склеивает `short_url` из `SHORT_URL_SCHEME://link.domain/link.slug`.
- **`app/admin.py`** — `APIRouter(prefix="/admin")`: `require_admin` (нет сессии → 303 на логин), `check_credentials` (constant-time), логин/логаут, дашборд (агрегаты по доменам), add/activate/deactivate/delete домена, страница домена со ссылками. Шаблоны — `app/templates/`.
- **`app/slug.py`** — `generate_slug()`: `secrets.choice` по `SLUG_ALPHABET`, длина `SLUG_LENGTH`. `RESERVED` — имена, занятые явными роутами (`health`, `shorten`, `admin`, `docs`, …), их нельзя выдавать как слаг.
- **`app/auth.py`** — `require_api_key()`: сравнивает заголовок `X-API-Key` с `settings.API_KEY` через `secrets.compare_digest` (constant-time). 500 если ключ не сконфигурирован, 401 если не совпал.
- **`app/models.py`** — `ShortLink` (таблица `short_links`), `Domain` (таблица `domains` — allowlist), `utcnow()` (timezone-aware UTC).
- **`app/config.py`** — синглтон `settings` (все параметры из env) + `normalize_domain()` (канон домена: lower-case, без схемы/пути/порта; общий для `ALLOWED_DOMAINS` и `Host`).
- **`app/database.py`** — `get_db()` (FastAPI-зависимость, закрывает сессию в `finally`).

## Модель данных

Таблица `short_links`:
- `id` BigInteger PK
- `domain` String(255) — короткий домен ссылки (из `Host`)
- `slug` String(32) — код в URL, **уникален в пределах домена**
- `full_link` Text — **полная ссылка целиком** (без разбора на маркеры)
- `full_link_hash` String(64) — `sha256(full_link)`, для дедупа, **уникален в пределах домена**
- `click_count` BigInteger default 0
- `created_at` / `last_clicked_at` — timezone-aware UTC

Составные `UniqueConstraint`: `uq_short_links_domain_slug (domain, slug)` и
`uq_short_links_domain_hash (domain, full_link_hash)`. Отдельные индексы на `slug`/`hash`
не нужны — составной UNIQUE с ведущей `domain` покрывает запросы редиректа и дедупа.

Таблица `domains` (allowlist, управляется через `/admin`):
- `id` BigInteger PK
- `domain` String(255) **UNIQUE** — нормализованный короткий домен
- `is_active` Boolean default False — `False` = добавлен, но инфра (DNS/nginx/TLS) ещё не настроена (на нём нельзя создавать ссылки)
- `created_at` — timezone-aware UTC

Источник истины для allowlist — эта таблица; env `ALLOWED_DOMAINS` засеивается в неё (как
активные) только при пустой таблице на старте.

## Команды

```bash
# Запуск (Docker)
cp .env.example .env        # вписать API_KEY, ALLOWED_DOMAINS, ADMIN_USERNAME/PASSWORD, SECRET_KEY
docker compose up -d --build

# Логи
docker compose logs -f shortener

# Доступ к БД
docker compose exec postgres psql -U shortener -d shortener

# Проверка синтаксиса
python3 -m py_compile app/*.py

# Локальный смоук-тест (домен — через Host; добавь localhost в ALLOWED_DOMAINS либо шли реальный Host)
curl -X POST http://127.0.0.1:8080/shorten -H "Host: krokozaim.ru" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"full_link":"https://example.com/long?a=1"}'
# GET (не HEAD: роут только под GET, HEAD → 405); query влит в Location:
curl -s -D - -o /dev/null "http://127.0.0.1:8080/<slug>?sub1=X" -H "Host: krokozaim.ru"
```

## Переменные окружения (`config.py`)

| Переменная        | По умолчанию                | Назначение |
|-------------------|-----------------------------|------------|
| `DATABASE_URL`    | `postgresql://shortener:shortener@postgres:5432/shortener` | Подключение к БД |
| `API_KEY`         | `""` (обязательно задать)   | Секрет для `POST /shorten`. Без него `/shorten` отдаёт 500 |
| `ALLOWED_DOMAINS` | `go.kybyshka-dev.ru`        | **Первичный сид** доменов в таблицу `domains` (источник истины — БД/панель). Через запятую/пробел, БЕЗ схемы |
| `SHORT_URL_SCHEME`| `https`                     | Схема для сборки `short_url` (в проде `https`; за nginx uvicorn видит `http`, потому схему задаём явно, а не из request) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `""` | Логин/пароль админ-панели `/admin` (constant-time сравнение) |
| `SECRET_KEY`      | `""`                        | Подпись сессионной куки админки (`openssl rand -hex 32`). Пуст → эфемерный ключ на процесс (логины не переживут рестарт) |
| `SERVER_IP`       | `""`                        | IP сервера для чек-листа DNS на странице домена (опц.) |
| `SLUG_LENGTH`     | `5`                         | Длина слага (base62: 62⁵ ≈ 916 млн комбинаций) |
| `SLUG_ALPHABET`   | `0-9 A-Z a-z` (base62)      | Алфавит слага — перечислять **явно** (`0123456789A…Za…z`), НЕ диапазоном `[A-z]` (в ASCII между цифрами/буквами лежит мусор) |
| `REDIRECT_STATUS` | `302`                       | `302` — клики считаются и назначение можно менять; `301` кэшируется браузером (счётчик слепнет) |

## Ключевые решения и грабли

- **Полная ссылка хранится целиком**, не разбирается на маркеры (web_id/offer_id/sub*). Любой новый `sub8` проходит без правки схемы. Дедуп — по `sha256` от полной строки.
- **Мультидомен: каждый домен — независимый шортенер.** Домен из `Host` (`resolve_domain`); уникальность и дедуп — по паре `(domain, …)`. Один slug на разных доменах = разные ссылки. `health` доменно-независим (healthcheck ходит по IP).
- **Allowlist доменов — в БД (таблица `domains`), управляется через `/admin`.** env `ALLOWED_DOMAINS` — лишь первичный сид. `shorten` гейтит по активному домену из БД (`_active_domain`, 400 если нет/неактивен). `redirect` (hot-path) проверку домена НЕ делает отдельным запросом — полагается на поиск по `(domain, slug)` (неизвестный домен → нет строк → 404), лишних обращений к БД нет. Поток нового домена: добавить в панели (pending) → настроить DNS/nginx/TLS → активировать.
- **Проброс query.** Редирект вливает query короткой ссылки в целевой URL (`merge_query`): входящее перекрывает сохранённое по ключу, пустые `subN=` сохраняются (`keep_blank_values=True`). Так per-user данные из рассылки доезжают до leads.tech.
- **`short_url`: схема из `SHORT_URL_SCHEME`, домен — из самой ссылки.** Не выводим из request: за nginx uvicorn видит `http`, а публичные ссылки всегда `https`.
- **Дедуп идемпотентен и потокобезопасен.** Сначала lookup по `(domain, full_link_hash)`; если параллельный запрос успел вставить — `IntegrityError` (составной UNIQUE) ловится, и из БД достаётся уже существующая строка.
- **Слаги** не могут совпасть с системными путями — список `RESERVED` в `slug.py`. При добавлении нового явного роута добавь его имя туда же.
- **`/{slug}` — catch-all в корне.** Явные роуты (`/health`, `/shorten`, `/admin/*`, `/docs`, `/openapi.json`) FastAPI регистрирует раньше и матчит первыми, поэтому коллизии нет. Любой неизвестный путь → 404 из `redirect()`. Админка `/admin` доменно-независима (доступна на любом домене, защищена логином).
- **302 vs 301.** По умолчанию 302, чтобы каждый клик проходил через сервис (счётчик + возможность сменить назначение). 301 браузер кэширует намертво.
- **Время — UTC** (timezone-aware), в отличие от основного проекта vktest2, где всё в МСК. Здесь сознательно UTC как стандарт для standalone-сервиса.
- **Миграций нет.** Меняешь модель → схема НЕ обновится сама на существующей БД (`create_all` создаёт только отсутствующие таблицы). НОВЫЕ таблицы создаются автоматически — напр. `domains` (allowlist) появилась без миграции. Для изменения КОЛОНОК существующей таблицы — `ALTER` вручную или Alembic. Мультидоменная миграция `short_links` (выполнялась вручную; уникальность была на UNIQUE-**индексах** `ix_short_links_*`, не на constraints — поэтому `DROP INDEX`):
  ```sql
  BEGIN;
  DROP INDEX IF EXISTS ix_short_links_slug;
  DROP INDEX IF EXISTS ix_short_links_full_link_hash;
  ALTER TABLE short_links ADD COLUMN domain VARCHAR(255) NOT NULL DEFAULT 'go.kybyshka-dev.ru';
  ALTER TABLE short_links ADD CONSTRAINT uq_short_links_domain_slug UNIQUE (domain, slug);
  ALTER TABLE short_links ADD CONSTRAINT uq_short_links_domain_hash UNIQUE (domain, full_link_hash);
  ALTER TABLE short_links ALTER COLUMN domain DROP DEFAULT;
  COMMIT;
  ```

## Деплой коротких доменов

1. A-запись каждого домена (`go.kybyshka-dev.ru`, `krokozaim.ru`, …) → этот сервер; дождаться `dig +short`.
2. Прописать домены в `ALLOWED_DOMAINS` (`.env`) и в `server_name` (`deploy/nginx.short.conf`).
3. `deploy/nginx.short.conf` → `/etc/nginx/conf.d/`, `nginx -t && systemctl reload nginx` (проксирует на `127.0.0.1:8080`).
4. TLS (один SAN-сертификат): `certbot --nginx -d go.kybyshka-dev.ru -d krokozaim.ru -d nashzaim.ru`. Новый домен потом — `certbot --nginx --expand -d <все, включая новый>`.
5. На существующей БД — сначала ручная миграция (см. «Миграций нет»), затем деплой кода.

## Интеграция с основным бэкендом (vktest2)

Основной бэкенд зовёт `POST /shorten` с заголовком `X-API-Key`, забирает `short_url`. Короткий
домен задаётся через `Host`: публичным адресом `https://krokozaim.ru/shorten` (Host = домен сам),
либо внутренним адресом docker-сети `http://shortener:8000/shorten` с заголовком `Host: krokozaim.ru`.
Пример вызова — в `README.md`.
