"""Админ-панель /admin: управление доменами (allowlist в БД) и просмотр статистики.

Доступна ТОЛЬКО на домене settings.ADMIN_HOST (если задан) — на прочих доменах /admin
отдаёт 404, чтобы панель не светилась на публичных коротких доменах. Защищена логином
(сессия в подписанной куке через SessionMiddleware).
"""
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import domain_to_unicode, normalize_domain, settings
from .database import get_db
from .models import Domain, ShortLink

templates = Jinja2Templates(directory="app/templates")


def admin_host_only(request: Request) -> None:
    """Гейт на уровне роутера: пускаем только на ADMIN_HOST (если задан), иначе 404.

    404 (а не 403) — чтобы на публичных доменах `/admin` выглядел как несуществующий путь
    и даже не показывал форму логина.
    """
    if settings.ADMIN_HOST:
        host = normalize_domain(request.headers.get("host", ""))
        if host != settings.ADMIN_HOST:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


# Гейт по домену применяется ко ВСЕМ роутам админки (включая login/logout)
router = APIRouter(prefix="/admin", dependencies=[Depends(admin_host_only)])


# --- авторизация -----------------------------------------------------------
def check_credentials(username: str, password: str) -> bool:
    """Constant-time проверка логина/пароля. Оба поля сверяются всегда."""
    if not settings.ADMIN_USERNAME or not settings.ADMIN_PASSWORD:
        return False
    u_ok = secrets.compare_digest(username, settings.ADMIN_USERNAME)
    p_ok = secrets.compare_digest(password, settings.ADMIN_PASSWORD)
    return u_ok and p_ok


def require_admin(request: Request) -> None:
    """Dependency: нет сессии админа → 303-редирект на форму логина."""
    if not request.session.get("admin"):
        raise HTTPException(
            status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"}
        )


def _redirect(path: str, msg: str | None = None) -> RedirectResponse:
    if msg:
        path = f"{path}?{urlencode({'msg': msg})}"
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


# --- логин/логаут ----------------------------------------------------------
@router.get("/login")
def login_form(request: Request):
    if request.session.get("admin"):
        return _redirect("/admin")
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login_submit(
    request: Request, username: str = Form(""), password: str = Form("")
):
    if check_credentials(username, password):
        request.session["admin"] = True
        return _redirect("/admin")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Неверный логин или пароль"},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return _redirect("/admin/login")


# --- дашборд ---------------------------------------------------------------
def _dashboard_rows(db: Session) -> list[dict]:
    """Домены + кол-во ссылок + сумма кликов (LEFT JOIN → домены без ссылок с нулями)."""
    agg = (
        select(
            ShortLink.domain.label("domain"),
            func.count(ShortLink.id).label("links"),
            func.coalesce(func.sum(ShortLink.click_count), 0).label("clicks"),
        )
        .group_by(ShortLink.domain)
        .subquery()
    )
    stmt = (
        select(
            Domain.id,
            Domain.domain,
            Domain.is_active,
            func.coalesce(agg.c.links, 0),
            func.coalesce(agg.c.clicks, 0),
        )
        .outerjoin(agg, agg.c.domain == Domain.domain)
        .order_by(Domain.created_at)
    )
    return [
        {
            "id": r[0],
            "domain": domain_to_unicode(r[1]),   # красивое отображение IDN (xn-- → кириллица)
            "is_active": r[2],
            "links": r[3],
            "clicks": r[4],
        }
        for r in db.execute(stmt).all()
    ]


@router.get("", dependencies=[Depends(require_admin)])
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "domains": _dashboard_rows(db),
            "msg": request.query_params.get("msg"),
            "server_ip": settings.SERVER_IP,
        },
    )


# --- управление доменами ---------------------------------------------------
@router.post("/domains", dependencies=[Depends(require_admin)])
def add_domain(domain: str = Form(""), db: Session = Depends(get_db)):
    name = normalize_domain(domain)
    if not name:
        return _redirect("/admin", "Пустой домен")
    if db.query(Domain.id).filter(Domain.domain == name).first():
        return _redirect("/admin", f"Домен {name} уже есть")
    db.add(Domain(domain=name, is_active=False))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect("/admin", f"Домен {name} уже есть")
    return _redirect("/admin", f"Добавлен {name} (ожидает настройки)")


@router.post("/domains/{domain_id}/activate", dependencies=[Depends(require_admin)])
def activate_domain(domain_id: int, db: Session = Depends(get_db)):
    db.query(Domain).filter(Domain.id == domain_id).update({Domain.is_active: True})
    db.commit()
    return _redirect(f"/admin/domains/{domain_id}")


@router.post("/domains/{domain_id}/deactivate", dependencies=[Depends(require_admin)])
def deactivate_domain(domain_id: int, db: Session = Depends(get_db)):
    db.query(Domain).filter(Domain.id == domain_id).update({Domain.is_active: False})
    db.commit()
    return _redirect(f"/admin/domains/{domain_id}")


@router.post("/domains/{domain_id}/delete", dependencies=[Depends(require_admin)])
def delete_domain(domain_id: int, db: Session = Depends(get_db)):
    db.query(Domain).filter(Domain.id == domain_id).delete()
    db.commit()
    return _redirect("/admin", "Домен удалён из allowlist")


@router.get("/domains/{domain_id}", dependencies=[Depends(require_admin)])
def domain_detail(request: Request, domain_id: int, db: Session = Depends(get_db)):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Домен не найден")
    links = (
        db.query(ShortLink)
        .filter(ShortLink.domain == d.domain)
        .order_by(ShortLink.click_count.desc())
        .limit(500)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "domain_detail.html",
        {
            "d": d,
            "domain_display": domain_to_unicode(d.domain),
            "links": links,
            "server_ip": settings.SERVER_IP,
        },
    )
