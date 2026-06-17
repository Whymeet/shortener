"""Конфигурация сервиса через переменные окружения."""
import os


class Settings:
    # Строка подключения к Postgres (своя БД микросервиса)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://shortener:shortener@postgres:5432/shortener",
    )
    # Общий секрет для POST /shorten (заголовок X-API-Key)
    API_KEY: str = os.getenv("API_KEY", "")
    # Базовый URL короткого домена, из него собирается short_url в ответе
    SHORT_BASE_URL: str = os.getenv("SHORT_BASE_URL", "http://localhost:8080").rstrip("/")
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
