# URL Shortener

Отдельный микросервис-сокращатель ссылок. Принимает полную ссылку, отдаёт короткую;
по короткой делает **302**-редирект и считает клики.

## Контракт API

### Создать / получить короткую ссылку
```http
POST /shorten
X-API-Key: <API_KEY>
Content-Type: application/json

{ "full_link": "https://t.leads.tech/click/12/108/?sub1=...&sub2=..." }
```
Ответ:
```json
{
  "slug": "QfSaj",
  "short_url": "https://s.kybyshka-dev.ru/QfSaj",
  "full_link": "https://t.leads.tech/click/12/108/?sub1=...",
  "click_count": 0,
  "created": true
}
```
- Дедуп по `sha256(full_link)`: одинаковая ссылка → тот же `slug`, `created: false`.
- Полная ссылка хранится **целиком** (никаких маркеров) — любой `sub8` и пр. проходят без изменения схемы.

### Редирект
```http
GET https://s.kybyshka-dev.ru/QfSaj   →  302 Location: <full_link>
```
Каждый заход инкрементит `click_count` и обновляет `last_clicked_at`.

### Health
```http
GET /health  →  {"status": "ok"}
```

## Запуск (Docker)
```bash
cp .env.example .env
# отредактировать API_KEY (openssl rand -hex 32) и SHORT_BASE_URL
docker compose up -d --build
```
Сервис слушает `127.0.0.1:8080`. Своя БД Postgres внутри compose, схема создаётся на старте.

## Деплой короткого домена
1. A/CNAME запись `s.kybyshka-dev.ru` → этот сервер.
2. Скопировать `deploy/nginx.short.conf` в `/etc/nginx/conf.d/`, `nginx -t && systemctl reload nginx`.
3. TLS: `certbot --nginx -d s.kybyshka-dev.ru`.

## Вызов из основного бэкенда (пример)
```python
import httpx

async def make_short(full_link: str) -> str:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            "http://shortener:8000/shorten",      # внутри docker-сети, либо https://s.kybyshka-dev.ru
            headers={"X-API-Key": SHORTENER_API_KEY},
            json={"full_link": full_link},
        )
        r.raise_for_status()
        return r.json()["short_url"]
```

## Конфигурация (env)
| Переменная        | По умолчанию                | Назначение                                  |
|-------------------|-----------------------------|---------------------------------------------|
| `DATABASE_URL`    | `postgresql://shortener...` | Подключение к БД                            |
| `API_KEY`         | —                           | Секрет для `POST /shorten`                   |
| `SHORT_BASE_URL`  | `http://localhost:8080`     | Базовый URL для сборки `short_url`           |
| `SLUG_LENGTH`     | `5`                         | Длина слага (`[A-Za-z]`, 52^5 ≈ 380 млн)     |
| `REDIRECT_STATUS` | `302`                       | `302` (со счётчиком) или `301` (кэш браузера)|
