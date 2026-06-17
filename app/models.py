"""Модель короткой ссылки."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, String, Text, UniqueConstraint

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShortLink(Base):
    __tablename__ = "short_links"

    # Каждый домен — независимый шортенер: slug и дедуп уникальны В ПРЕДЕЛАХ домена.
    # Составной UNIQUE (domain, ...) в PostgreSQL создаёт индекс с ведущей колонкой domain,
    # который покрывает запросы редиректа и дедупа — отдельные индексы не нужны.
    __table_args__ = (
        UniqueConstraint("domain", "slug", name="uq_short_links_domain_slug"),
        UniqueConstraint("domain", "full_link_hash", name="uq_short_links_domain_hash"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Короткий домен, к которому привязана ссылка (из заголовка Host)
    domain = Column(String(255), nullable=False)
    # Короткий код в URL, напр. "QfSaj" — уникален в пределах домена
    slug = Column(String(32), nullable=False)
    # Полная исходная ссылка целиком — никаких маркеров, отдаём как есть
    full_link = Column(Text, nullable=False)
    # sha256(full_link) для дедупа — уникален в пределах домена
    full_link_hash = Column(String(64), nullable=False)
    click_count = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_clicked_at = Column(DateTime(timezone=True), nullable=True)
