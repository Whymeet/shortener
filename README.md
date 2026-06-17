# URL Shortener

Отдельный микросервис-сокращатель ссылок. Поддерживает **несколько коротких доменов**
(каждый — независимый шортенер) и **проброс query-параметров**: per-user `sub`-параметры
из рассылки доезжают до целевой ссылки. По короткой ссылке делает **302**-редирект и
считает клики.

## Мультидоменность

Короткий домен определяется по заголовку `Host`. Один и тот же `slug` на разных доменах —
**разные** ссылки; дедуп тоже пер-домен. Список разрешённых доменов хранится в БД и
управляется через [админ-панель](#админ-панель) (env `ALLOWED_DOMAINS` — лишь первичный сид).

- `POST https://krokozaim.ru/shorten` → создаёт ссылку на домене `krokozaim.ru` (домен должен быть **активен**).
- `GET  https://krokozaim.ru/<slug>`  → редирект для этого домена.
- Запрос с `Host`, которого нет среди активных доменов: `shorten` → `400`, redirect → `404`.

## Проброс query-параметров

При редиректе query короткой ссылки **накладывается** на сохранённый целевой URL:
входящие параметры перекрывают сохранённые по ключу, остальные сохранённые (включая
пустые `sub4=&sub5=`) остаются, новые ключи добавляются.

```
Сохранено:   https://t.leads.tech/click/12/9/?sub1=base&sub2=base&sub3=141706&sub4=&sub5=
Короткая:    https://go.kybyshka-dev.ru/j3JjZ?sub1=USER123&sub2=vk_ras
Редирект на: https://t.leads.tech/click/12/9/?sub1=USER123&sub2=vk_ras&sub3=141706&sub4=&sub5=
```

## Админ-панель

Веб-панель на `/admin` (доступна на любом коротком домене, защищена логином). Вход — логин и
пароль из env (`ADMIN_USERNAME` / `ADMIN_PASSWORD`), сессия в подписанной куке (`SECRET_KEY`).

Возможности:
- **Дашборд** — список доменов со статусом (активен / ожидает настройки), кол-вом ссылок и суммой кликов.
- **Добавить домен** — домен попадает в allowlist (БД) со статусом «ожидает настройки».
- **Страница домена** — чек-лист настройки (DNS / nginx / certbot) для неактивных + список ссылок с кликами.
- **Активировать / деактивировать / удалить** домен.

Поток добавления нового (корневого) домена:
1. В панели «Добавить домен» → статус *ожидает настройки* (создавать ссылки на нём пока нельзя).
2. На сервере выполнить чек-лист со страницы домена: DNS A-запись, `server_name` в nginx, `certbot --expand`.
3. Нажать «Отметить активным» → теперь `POST /shorten` на этот домен работает.

> Список доменов — в БД (таблица `domains`). `ALLOWED_DOMAINS` из env засеивается в неё только
> при первом старте с пустой таблицей (как активные). Дальше управление — через панель.

## Контракт API

### Создать / получить короткую ссылку
```http
POST /shorten              (Host определяет короткий домен)
X-API-Key: <API_KEY>
Content-Type: application/json

{ "full_link": "https://t.leads.tech/click/12/108/?sub1=...&sub2=..." }
```
Ответ:
```json
{
  "slug": "QfSaj",
  "short_url": "https://krokozaim.ru/QfSaj",
  "full_link": "https://t.leads.tech/click/12/108/?sub1=...",
  "click_count": 0,
  "created": true
}
```
- `short_url` собирается из домена запроса (`Host`) и `SHORT_URL_SCHEME`.
- Дедуп по `(domain, sha256(full_link))`: та же ссылка на том же домене → тот же `slug`, `created: false`.
- Полная ссылка хранится **целиком** (никаких маркеров) — любой `sub8` и пр. проходят без изменения схемы.

### Редирект
```http
GET https://krokozaim.ru/QfSaj?sub1=...   →  302 Location: <full_link с влитым query>
```
Каждый заход инкрементит `click_count` и обновляет `last_clicked_at`.

### Health
```http
GET /health  →  {"status": "ok"}     (доменно-независим, для healthcheck)
```

## Запуск (Docker)
```bash
cp .env.example .env
# отредактировать API_KEY (openssl rand -hex 32) и ALLOWED_DOMAINS
docker compose up -d --build
```
Сервис слушает `127.0.0.1:8080`. Своя БД Postgres внутри compose, схема создаётся на старте.

Локальный тест без TLS — добавь `localhost` в `ALLOWED_DOMAINS`, `SHORT_URL_SCHEME=http`,
и шли запросы с нужным `Host`:
```bash
curl -X POST http://127.0.0.1:8080/shorten -H "Host: krokozaim.ru" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"full_link":"https://example.com/x"}'
```

## Деплой коротких доменов
1. A-запись каждого домена (`go.kybyshka-dev.ru`, `krokozaim.ru`, …) → этот сервер.
2. Прописать домены в `ALLOWED_DOMAINS` (`.env`) и в `server_name` (`deploy/nginx.short.conf`).
3. Скопировать конфиг в `/etc/nginx/conf.d/`, `nginx -t && systemctl reload nginx`.
4. TLS (один SAN-сертификат на все домены):
   `certbot --nginx -d go.kybyshka-dev.ru -d krokozaim.ru -d nashzaim.ru`.
   Добавить домен позже: `certbot --nginx --expand -d <все домены, включая новый>`.

> Изменение модели на существующей БД миграциями НЕ покрыто (`create_all` колонки не
> добавляет). Колонка `domain` и составные UNIQUE добавляются вручную — см. CLAUDE.md.

## Вызов из основного бэкенда (пример)
```python
import httpx

async def make_short(full_link: str, domain: str) -> str:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"https://{domain}/shorten",            # публичный адрес: домен = короткий хост
            headers={"X-API-Key": SHORTENER_API_KEY},
            json={"full_link": full_link},
        )
        r.raise_for_status()
        return r.json()["short_url"]

# Внутри docker-сети домен задаётся заголовком Host:
#   c.post("http://shortener:8000/shorten",
#          headers={"X-API-Key": ..., "Host": domain}, json={"full_link": ...})
```

## Конфигурация (env)
| Переменная         | По умолчанию                | Назначение                                            |
|--------------------|-----------------------------|-------------------------------------------------------|
| `DATABASE_URL`     | `postgresql://shortener...` | Подключение к БД                                      |
| `API_KEY`          | —                           | Секрет для `POST /shorten`                            |
| `ALLOWED_DOMAINS`  | `go.kybyshka-dev.ru`        | Первичный сид доменов в БД (источник истины — таблица `domains`/панель) |
| `SHORT_URL_SCHEME` | `https`                     | Схема для сборки `short_url`                          |
| `ADMIN_USERNAME`   | —                           | Логин админ-панели `/admin`                           |
| `ADMIN_PASSWORD`   | —                           | Пароль админ-панели                                   |
| `SECRET_KEY`       | —                           | Подпись сессионной куки (`openssl rand -hex 32`); в проде задать |
| `SERVER_IP`        | —                           | IP сервера для чек-листа DNS на странице домена (опц.)|
| `SLUG_LENGTH`      | `5`                         | Длина слага (base62, 62^5 ≈ 916 млн)                  |
| `SLUG_ALPHABET`    | base62 (`0-9 A-Z a-z`)      | Алфавит слага                                         |
| `REDIRECT_STATUS`  | `302`                       | `302` (со счётчиком) или `301` (кэш браузера)         |
