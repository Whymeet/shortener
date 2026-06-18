"""URL-сокращатель: POST /shorten создаёт/возвращает короткую ссылку, GET /{slug} редиректит."""
import hashlib
import secrets
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import admin
from .auth import require_api_key
from .config import normalize_domain, settings
from .database import Base, SessionLocal, engine, get_db
from .models import Domain, ShortLink, utcnow
from .schemas import ShortenRequest, ShortenResponse
from .slug import RESERVED, generate_slug


def _seed_domains() -> None:
    """Первичный сид allowlist: если таблица domains пуста — засеять из env как активные
    (эти домены в проде уже работают). Дальше управление доменами — через /admin."""
    with SessionLocal() as db:
        if db.query(Domain).count() == 0:
            for name in settings.ALLOWED_DOMAINS:
                db.add(Domain(domain=name, is_active=True))
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic избыточен, создаём схему на старте (таблица domains создастся автоматически)
    Base.metadata.create_all(bind=engine)
    _seed_domains()
    yield


app = FastAPI(title="URL Shortener", version="1.0.0", lifespan=lifespan)

# Сессия админки (подписанная кука). SECRET_KEY обязателен в проде; если пуст — эфемерный
# ключ на процесс (логины не переживут рестарт), но ядро-сервис не падает.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY or secrets.token_hex(32),
    same_site="lax",
    https_only=(settings.SHORT_URL_SCHEME == "https"),
    max_age=14 * 24 * 3600,
)
app.include_router(admin.router)


def resolve_domain(request: Request) -> str:
    """Нормализованный короткий домен из заголовка Host (lower-case, без схемы/порта/пути)."""
    return normalize_domain(request.headers.get("host", ""))


def _active_domain(db: Session, domain: str) -> bool:
    """Домен зарегистрирован в allowlist (БД) и активен — на нём можно создавать ссылки."""
    if not domain:
        return False
    return (
        db.query(Domain.id)
        .filter(Domain.domain == domain, Domain.is_active.is_(True))
        .first()
        is not None
    )


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


@app.get("/internal/tls-allow")
def tls_allow(domain: str = "", db: Session = Depends(get_db)):
    """ask-эндпоинт для Caddy on-demand TLS: 2xx → выпускать сертификат, иначе нет.

    Caddy шлёт GET /internal/tls-allow?domain=<host> перед выпуском сертификата на новый SNI.
    Разрешаем ТОЛЬКО активные домены из БД — тот же гейт, что и для shorten (_active_domain).
    """
    if _active_domain(db, normalize_domain(domain)):
        return {"ok": True}
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Домен не активен")


@app.post(
    "/shorten",
    response_model=ShortenResponse,
    dependencies=[Depends(require_api_key)],
)
def shorten(payload: ShortenRequest, request: Request, db: Session = Depends(get_db)):
    domain = resolve_domain(request)
    if not _active_domain(db, domain):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Домен не разрешён или ещё не активирован"
        )

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
    # Домен из Host; неизвестный/неактивный домен просто не даст совпадений → 404 (без доп. запроса)
    domain = resolve_domain(request)
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
