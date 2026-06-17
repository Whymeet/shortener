"""URL-сокращатель: POST /shorten создаёт/возвращает короткую ссылку, GET /{slug} редиректит."""
import hashlib
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_api_key
from .config import normalize_domain, settings
from .database import Base, engine, get_db
from .models import ShortLink, utcnow
from .schemas import ShortenRequest, ShortenResponse
from .slug import RESERVED, generate_slug


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Одна таблица — Alembic избыточен, создаём схему на старте
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="URL Shortener", version="1.0.0", lifespan=lifespan)


def resolve_domain(request: Request) -> str | None:
    """Короткий домен из заголовка Host, если он в ALLOWED_DOMAINS (иначе None).

    Решение по HTTP-статусу принимает вызывающий эндпоинт (shorten → 400, redirect → 404).
    """
    host = normalize_domain(request.headers.get("host", ""))
    return host if host in settings.ALLOWED_DOMAINS else None


def merge_query(stored_url: str, incoming_query: str) -> str:
    """Накладывает query короткой ссылки на сохранённый целевой URL.

    Входящие параметры перекрывают сохранённые по ключу; сохранённые, которых нет во
    входящих (включая пустые sub4=&sub5=), остаются; новые ключи добавляются. Так per-user
    sub-параметры из рассылки доезжают до целевой ссылки (leads.tech).
    """
    parts = urlsplit(stored_url)
    merged = dict(parse_qsl(parts.query, keep_blank_values=True))      # сохранённые
    merged.update(parse_qsl(incoming_query, keep_blank_values=True))   # входящие перекрывают
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment)
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/shorten",
    response_model=ShortenResponse,
    dependencies=[Depends(require_api_key)],
)
def shorten(payload: ShortenRequest, request: Request, db: Session = Depends(get_db)):
    domain = resolve_domain(request)
    if domain is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный короткий домен")

    full_link = payload.full_link
    link_hash = hashlib.sha256(full_link.encode("utf-8")).hexdigest()

    # Дедуп ПЕР-ДОМЕН: та же ссылка на том же домене → существующий слаг
    existing = (
        db.query(ShortLink)
        .filter(ShortLink.domain == domain, ShortLink.full_link_hash == link_hash)
        .first()
    )
    if existing:
        return _response(existing, created=False)

    # Полагаемся на составной UNIQUE (domain, slug)/(domain, hash): при коллизии — retry
    for _ in range(10):
        slug = generate_slug()
        if slug in RESERVED:
            continue
        link = ShortLink(
            domain=domain, slug=slug, full_link=full_link, full_link_hash=link_hash
        )
        db.add(link)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Параллельный запрос мог вставить ту же ссылку на этом домене — вернём её
            existing = (
                db.query(ShortLink)
                .filter(
                    ShortLink.domain == domain, ShortLink.full_link_hash == link_hash
                )
                .first()
            )
            if existing:
                return _response(existing, created=False)
            # Иначе коллизия слага в пределах домена — пробуем другой
            continue
        db.refresh(link)
        return _response(link, created=True)

    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось сгенерировать уникальный слаг"
    )


@app.get("/{slug}")
def redirect(slug: str, request: Request, db: Session = Depends(get_db)):
    domain = resolve_domain(request)
    if domain is None:
        # Чужой/неизвестный Host — нейтральный 404, не раскрываем природу сервиса
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка не найдена")

    link = (
        db.query(ShortLink)
        .filter(ShortLink.domain == domain, ShortLink.slug == slug)
        .first()
    )
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка не найдена")

    # Атомарный инкремент счётчика, чтобы не терять клики при гонках
    db.execute(
        update(ShortLink)
        .where(ShortLink.id == link.id)
        .values(click_count=ShortLink.click_count + 1, last_clicked_at=utcnow())
    )
    db.commit()

    # Прокидываем query короткой ссылки на целевой URL (per-user sub-параметры из рассылки)
    target = merge_query(link.full_link, request.url.query)
    return RedirectResponse(url=target, status_code=settings.REDIRECT_STATUS)


def _response(link: ShortLink, created: bool) -> ShortenResponse:
    return ShortenResponse(
        slug=link.slug,
        short_url=f"{settings.SHORT_URL_SCHEME}://{link.domain}/{link.slug}",
        full_link=link.full_link,
        click_count=link.click_count,
        created=created,
    )
