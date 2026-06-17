"""Конфигурация сервиса через переменные окружения."""
import os


def normalize_domain(value: str) -> str:
    """Канон домена для сравнения: lower-case, без схемы/пути/порта.

    Применяется и к списку ALLOWED_DOMAINS, и к заголовку Host входящего запроса,
    чтобы сравнение было устойчивым (`krokozaim.ru:8080`, `https://krokozaim.ru/` → `krokozaim.ru`).
    """
    v = value.strip().lower()
    if "//" in v:                 # отрезаем схему https:// если затесалась
        v = v.split("//", 1)[1]
    v = v.split("/", 1)[0]        # отрезаем путь
    v = v.split(":", 1)[0]        # отрезаем порт
    return v


class Settings:
    # Строка подключения к Postgres (своя БД микросервиса)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://shortener:shortener@postgres:5432/shortener",
    )
    # Общий секрет для POST /shorten (заголовок X-API-Key)
    API_KEY: str = os.getenv("API_KEY", "")
    # ПЕРВИЧНЫЙ СИД списка коротких доменов. Источник истины в рантайме — таблица `domains`
    # (управляется через /admin); ALLOWED_DOMAINS засеивается в неё ТОЛЬКО при пустой таблице.
    # Перечислять через запятую/пробел, БЕЗ схемы: ALLOWED_DOMAINS=go.kybyshka-dev.ru,krokozaim.ru
    ALLOWED_DOMAINS: set[str] = {
        normalize_domain(d)
        for d in os.getenv("ALLOWED_DOMAINS", "go.kybyshka-dev.ru").replace(",", " ").split()
        if normalize_domain(d)
    }
    # Схема для сборки short_url в ответе. За nginx uvicorn видит http, но публичные
    # ссылки всегда https → задаём явно, НЕ выводим из request.
    SHORT_URL_SCHEME: str = os.getenv("SHORT_URL_SCHEME", "https").strip().lower()
    # Админ-панель /admin: логин-пароль (constant-time сравнение) и секрет для подписи
    # сессионной куки (openssl rand -hex 32). SERVER_IP — для чек-листа DNS на странице домена.
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    SERVER_IP: str = os.getenv("SERVER_IP", "")
    # Домен, на котором доступна админка /admin. На прочих доменах /admin отдаёт 404
    # (не светится на публичных коротких доменах). Пусто = доступна везде (только для дева).
    ADMIN_HOST: str = normalize_domain(os.getenv("ADMIN_HOST", ""))
    # Длина слага и алфавит (base62: 0-9A-Za-z — перечислять ЯВНО, НЕ диапазоном [A-z]: в ASCII между
    # цифрами/заглавными/строчными лежит мусор. Цифры → больше ёмкости, как у bit.ly/tinyurl.)
    SLUG_LENGTH: int = int(os.getenv("SLUG_LENGTH", "5"))
    SLUG_ALPHABET: str = os.getenv(
        "SLUG_ALPHABET",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    )
    # 302 — каждый клик проходит через сервис (счётчик + смена назначения).
    # 301 кэшируется браузером намертво и ломает подсчёт кликов.
    REDIRECT_STATUS: int = int(os.getenv("REDIRECT_STATUS", "302"))


settings = Settings()
