"""Генерация случайных слагов."""
import secrets

from .config import settings

# Эти пути обслуживаются явными роутами, слаг с таким именем выдавать нельзя
RESERVED = {
    "health",
    "shorten",
    "stats",
    "docs",
    "redoc",
    "openapi.json",
    "favicon.ico",
}


def generate_slug() -> str:
    """Случайный слаг из SLUG_LENGTH символов алфавита (52^5 ≈ 380 млн при дефолте)."""
    return "".join(
        secrets.choice(settings.SLUG_ALPHABET) for _ in range(settings.SLUG_LENGTH)
    )
