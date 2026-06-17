"""Pydantic-схемы запросов и ответов."""
from pydantic import BaseModel, field_validator


class ShortenRequest(BaseModel):
    full_link: str

    @field_validator("full_link")
    @classmethod
    def _validate(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("full_link должен начинаться с http:// или https://")
        if len(v) > 4096:
            raise ValueError("full_link слишком длинный (>4096)")
        return v


class ShortenResponse(BaseModel):
    slug: str
    short_url: str
    full_link: str
    click_count: int
    created: bool  # True — создана новая, False — вернули существующую (дедуп)
