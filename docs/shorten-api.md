# Интеграция с сервисом коротких ссылок

Инструкция для подключения вашего сервиса к нашему сокращателю ссылок.
По одному HTTP-запросу вы получаете короткую ссылку; при переходе по ней пользователь
редиректится на вашу исходную ссылку (302), а добавленные к короткой ссылке параметры
доезжают до неё.

**Что вам выдаём мы:**
- **короткий домен** — например `go.kybyshka-dev.ru` (далее `<КОРОТКИЙ_ДОМЕН>`);
- **API-ключ** — секрет для заголовка `X-API-Key` (далее `<API_KEY>`).

---

## Создать короткую ссылку

```
POST https://<КОРОТКИЙ_ДОМЕН>/shorten
X-API-Key: <API_KEY>
Content-Type: application/json

{ "full_link": "https://пример.ru/длинная/ссылка?a=1&b=2" }
```

| Поле | Требование |
|------|------------|
| `X-API-Key` | обязателен; ваш ключ |
| `full_link` | исходная ссылка; начинается с `http://` или `https://`, длина ≤ 4096 |

**Ответ `200 OK`:**
```json
{
  "slug": "GVZzA",
  "short_url": "https://go.kybyshka-dev.ru/GVZzA",
  "full_link": "https://пример.ru/длинная/ссылка?a=1&b=2",
  "click_count": 0,
  "created": true
}
```
Берите поле **`short_url`** — это готовая короткая ссылка.
`created`: `true` — создана новая, `false` — вернули уже существующую (см. «Дедупликация»).

---

## Примеры

**curl**
```
curl -X POST https://go.kybyshka-dev.ru/shorten \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"full_link":"https://пример.ru/длинная/ссылка?a=1"}'
```

**Python (requests)**
```
import requests

def make_short(full_link: str) -> str:
    r = requests.post(
        "https://go.kybyshka-dev.ru/shorten",
        headers={"X-API-Key": "<API_KEY>"},
        json={"full_link": full_link},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["short_url"]
```

**Node.js (fetch)**
```
async function makeShort(fullLink) {
  const res = await fetch("https://go.kybyshka-dev.ru/shorten", {
    method: "POST",
    headers: { "X-API-Key": "<API_KEY>", "Content-Type": "application/json" },
    body: JSON.stringify({ full_link: fullLink }),
  });
  if (!res.ok) throw new Error("shorten failed: " + res.status);
  return (await res.json()).short_url;
}
```

---

## Проброс query-параметров

Любые параметры, которые вы добавите к **короткой** ссылке, при переходе доедут до исходной.
Удобно для подстановки данных на лету (id пользователя, метки кампании и т.п.). Имена
параметров — любые.

```
Сокращали:    https://пример.ru/click?sub1=base&sub3=X
Короткая:     https://go.kybyshka-dev.ru/GVZzA?sub1=USER123&utm=vk
Переход на:   https://пример.ru/click?sub1=USER123&sub3=X&utm=vk
```
Правило: параметр из короткой ссылки **перекрывает** одноимённый в исходной; параметры,
которых нет в короткой, сохраняются; новые — добавляются.

---

## Дедупликация

Повторный запрос с тем же `full_link` вернёт **ту же** короткую ссылку (`"created": false`),
новая не создаётся. Так что можно безопасно вызывать `/shorten` повторно.

---

## Коды ошибок

| Код | Причина |
|-----|---------|
| `401` | отсутствует или неверный `X-API-Key` |
| `422` | некорректное тело: нет `full_link`, ссылка не на `http(s)://` или длиннее 4096 |
| `400` | короткий домен не разрешён (используйте выданный вам домен) |

---

## Проверка

```
# создать ссылку
curl -s -X POST https://go.kybyshka-dev.ru/shorten \
  -H "X-API-Key: <API_KEY>" -H "Content-Type: application/json" \
  -d '{"full_link":"https://пример.ru/test"}'

# перейти по короткой ссылке (с параметрами) — увидите редирект на исходную
curl -sL "https://go.kybyshka-dev.ru/<slug>?sub1=test"
```

Вопросы по интеграции (домен, ключ, лимиты) — к нам.
