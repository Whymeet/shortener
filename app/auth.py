"""Проверка API-ключа для создания ссылок."""
import secrets

from fastapi import Header, HTTPException, status

from .config import settings


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.API_KEY:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "API_KEY не сконфигурирован на сервисе",
        )
    # Сравнение в постоянное время — защита от timing-атак
    if not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный API-ключ")
