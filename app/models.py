"""Модель короткой ссылки."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, String, Text

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShortLink(Base):
    __tablename__ = "short_links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Короткий код в URL, напр. "QfSaj"
    slug = Column(String(32), unique=True, index=True, nullable=False)
    # Полная исходная ссылка целиком — никаких маркеров, отдаём как есть
    full_link = Column(Text, nullable=False)
    # sha256(full_link) для дедупа: индекс по 64 символам быстрее индекса по TEXT
    full_link_hash = Column(String(64), unique=True, index=True, nullable=False)
    click_count = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_clicked_at = Column(DateTime(timezone=True), nullable=True)
