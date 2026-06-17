# Как создать короткую ссылку (API)

Мини-справочник по запросам к сервису-сокращателю.

## TL;DR

```bash
curl -X POST https://go.kybyshka-dev.ru/shorten \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"full_link":"https://t.leads.tech/click/12/9/?sub1=...&sub2=..."}'
```
В ответе бери поле **`short_url`**.

---

## Эндпоинт

`POST /shorten`

| Что | Как |
|-----|-----|
| **Auth** | заголовок `X-API-Key: <ключ>` (обязателен) |
| **Короткий домен** | определяется заголовком `Host`. На прод-домене — это сам адрес (`https://go.kybyshka-dev.ru/shorten`); локально/из docker-сети — задаётся заголовком `Host`. Домен должен быть **активен** в админке |
| **Тело** | JSON `{"full_link": "<исходная ссылка>"}`. Ссылка должна начинаться с `http://` или `https://`, длина ≤ 4096 |
| **Content-Type** | `application/json` |

### Ответ (`200 OK`)
```json
{
  "slug": "GVZzA",
  "short_url": "https://go.kybyshka-dev.ru/GVZzA",
  "full_link": "https://t.leads.tech/click/12/9/?sub1=...",
  "click_count": 0,
  "created": true
}
```
- `short_url` — готовая короткая ссылка (схема + домен из `Host` + slug).
- `created`: `true` — создана новая; `false` — вернули существующую (сработал дедуп).

---

## Примеры

### 1. Прод — домен прямо в адресе
```bash
curl -X POST https://go.kybyshka-dev.ru/shorten \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"full_link":"http://leadstech.ru/12/pepapapap12w"}'
```
Короткая ссылка вернётся как `https://go.kybyshka-dev.ru/<slug>`.

### 2. Другой домен — тем же запросом, меняешь только адрес/Host
```bash
curl -X POST https://krokozaim.ru/shorten \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"full_link":"http://leadstech.ru/12/pepapapap12w"}'
# → short_url: https://krokozaim.ru/<slug>
```

### 3. Локально / из docker-сети — домен через заголовок Host
```bash
# ключ удобно подставить из .env
curl -X POST http://127.0.0.1:8080/shorten \
  -H "Host: testzaim.ru" \
  -H "X-API-Key: $(grep '^API_KEY=' .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"full_link":"http://leadstech.ru/12/pepapapap12w"}'
# → short_url: http(s)://testzaim.ru/<slug>
```

### 4. Из кода (Python)
```python
import httpx

def make_short(full_link: str, domain: str, api_key: str) -> str:
    r = httpx.post(
        f"https://{domain}/shorten",          # публичный адрес = короткий домен
        headers={"X-API-Key": api_key},
        json={"full_link": full_link},
    )
    r.raise_for_status()
    return r.json()["short_url"]
```

---

## Что важно знать

- **Дедуп пер-домен.** Повторный POST того же `full_link` на тот же домен вернёт **тот же** `slug` с `"created": false`. Один и тот же URL на разных доменах = разные короткие ссылки.
- **Проброс query.** Любые параметры, добавленные к **короткой** ссылке при клике/рассылке, доезжают до целевого URL: входящие перекрывают сохранённые по имени, остальные сохранённые остаются, новые добавляются. Имена параметров любые (`sub1`, `date`, `clickid`, что угодно).
  ```
  Сохранено:   http://leadstech.ru/12/x?sub1=base
  Короткая:    https://go.kybyshka-dev.ru/GVZzA?sub1=USER&date=2026-06-17
  Редирект на: http://leadstech.ru/12/x?sub1=USER&date=2026-06-17
  ```
- **Домен должен быть активен.** Новый домен сперва добавляется в админке (`/admin`), настраивается (DNS/nginx/TLS) и активируется. На неактивном/незарегистрированном домене `shorten` вернёт `400`.
- Сервис **не хранит** значения per-click параметров — только счётчик `click_count` и время последнего клика. Детальная статистика по меткам — на стороне leadstech.

---

## Коды ошибок

| Код | Когда |
|-----|-------|
| `400` | домен (из `Host`) не разрешён или не активирован |
| `401` | нет/неверный `X-API-Key` |
| `422` | кривое тело: нет `full_link`, не `http(s)://`, длиннее 4096 |
| `500` | на сервисе не задан `API_KEY` (конфигурация) |

## Проверить короткую ссылку
```bash
curl -sL https://go.kybyshka-dev.ru/<slug>     # -L = пройти по 302-редиректу
```
