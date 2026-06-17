"""URL-сокращатель: POST /shorten создаёт/возвращает короткую ссылку, GET /{slug} редиректит."""
import hashlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_api_key
from .config import settings
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/shorten",
    response_model=ShortenResponse,
    dependencies=[Depends(require_api_key)],
)
def shorten(payload: ShortenRequest, db: Session = Depends(get_db)):
    full_link = payload.full_link
    link_hash = hashlib.sha256(full_link.encode("utf-8")).hexdigest()

    # Дедуп: уже есть точно такая же ссылка → отдаём существующий слаг
    existing = db.query(ShortLink).filter(ShortLink.full_link_hash == link_hash).first()
    if existing:
        return _response(existing, created=False)

    # Полагаемся на UNIQUE-констрейнты: при коллизии слага или гонке по hash — retry
    for _ in range(10):
        slug = generate_slug()
        if slug in RESERVED:
            continue
        link = ShortLink(slug=slug, full_link=full_link, full_link_hash=link_hash)
        db.add(link)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Параллельный запрос мог вставить ту же ссылку — вернём её
            existing = (
                db.query(ShortLink).filter(ShortLink.full_link_hash == link_hash).first()
            )
            if existing:
                return _response(existing, created=False)
            # Иначе это коллизия слага — пробуем другой
            continue
        db.refresh(link)
        return _response(link, created=True)

    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось сгенерировать уникальный слаг"
    )


@app.get("/{slug}")
def redirect(slug: str, db: Session = Depends(get_db)):
    link = db.query(ShortLink).filter(ShortLink.slug == slug).first()
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка не найдена")

    # Атомарный инкремент счётчика, чтобы не терять клики при гонках
    db.execute(
        update(ShortLink)
        .where(ShortLink.id == link.id)
        .values(click_count=ShortLink.click_count + 1, last_clicked_at=utcnow())
    )
    db.commit()
    return RedirectResponse(url=link.full_link, status_code=settings.REDIRECT_STATUS)


def _response(link: ShortLink, created: bool) -> ShortenResponse:
    return ShortenResponse(
        slug=link.slug,
        short_url=f"{settings.SHORT_BASE_URL}/{link.slug}",
        full_link=link.full_link,
        click_count=link.click_count,
        created=created,
    )
