from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum.api.deps import COOKIE, current_user, get_db, get_settings, require
from leventum.config import Settings
from leventum.models import AppUser
from leventum.services import audit, auth, backup as backup_svc
from leventum.services.dashboard import build_dashboard

public = APIRouter()      # bewusst ohne Auth: Health + Auth-Bootstrap
protected = APIRouter()   # alles andere: Auth erzwungen über Dependency am Router


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class SetupRequest(Credentials):
    display_name: str = Field(default="", max_length=120)


def user_out(u: AppUser) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role.code}


def _set_cookie(resp: Response, token: str, settings: Settings) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=settings.cookie_secure,
                    max_age=settings.session_absolute_hours * 3600, path="/")


@public.get("/health")
def health():
    return {"status": "ok"}


@public.get("/auth/status")
def auth_status(db: Session = Depends(get_db)):
    return {"setup_required": auth.needs_setup(db)}


@public.post("/auth/setup")
def auth_setup(body: SetupRequest, response: Response, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)):
    try:
        auth.create_admin(db, settings, body.username, body.display_name, body.password)
        db.commit()
        token, user = auth.login(db, settings, body.username, body.password)
    except auth.AuthError as e:
        db.rollback()
        raise HTTPException(400 if e.code != "setup_done" else 409, detail={"code": e.code, "detail": e.message})
    _set_cookie(response, token, settings)
    return user_out(user)


@public.post("/auth/login")
def auth_login(body: Credentials, response: Response, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)):
    try:
        token, user = auth.login(db, settings, body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(429 if e.code == "locked" else 401, detail={"code": e.code, "detail": e.message})
    _set_cookie(response, token, settings)
    return user_out(user)


@public.post("/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.logout(db, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@protected.get("/auth/me")
def auth_me(user: AppUser = Depends(current_user)):
    return user_out(user)


@protected.get("/dashboard", dependencies=[Depends(require("dashboard:read"))])
def dashboard(db: Session = Depends(get_db)):
    return build_dashboard(db)


# --- Backup (nur Administrator) -------------------------------------------------------------
backup_router = APIRouter(prefix="/system/backups", dependencies=[Depends(require("system:backup"))])


@backup_router.get("")
def backups_list(settings: Settings = Depends(get_settings)):
    return {"items": backup_svc.list_backups(settings), **backup_svc.latest_backup_info(settings)}


@backup_router.post("")
def backups_create(request: Request, db: Session = Depends(get_db), user: AppUser = Depends(current_user),
                   settings: Settings = Depends(get_settings)):
    try:
        path = backup_svc.create_backup(request.app.state.engine, settings)
    except backup_svc.BackupError as e:
        raise HTTPException(400, detail={"code": "backup_failed", "detail": str(e)})
    res = backup_svc.verify_backup(path)
    audit.record(db, "backup.created", actor_user_id=user.id, entity_type="backup", entity_id=path.name,
                 summary="Backup erstellt", details={"verified": res.ok})
    db.commit()
    return {"id": path.name, "verified": res.ok, "problems": res.problems}


@backup_router.post("/{backup_id}/verify")
def backups_verify(backup_id: str, settings: Settings = Depends(get_settings)):
    try:
        res = backup_svc.verify_backup(backup_svc.resolve_backup(settings, backup_id))
    except backup_svc.BackupError as e:
        raise HTTPException(404, detail={"code": "not_found", "detail": str(e)})
    return {"ok": res.ok, "problems": res.problems}


class RestoreRequest(BaseModel):
    confirm: bool = False


@backup_router.post("/{backup_id}/restore")
def backups_restore(backup_id: str, body: RestoreRequest, request: Request, db: Session = Depends(get_db),
                    user: AppUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    if not body.confirm:
        raise HTTPException(400, detail={"code": "confirmation_required", "detail": "Bestätigung erforderlich."})
    try:
        path = backup_svc.resolve_backup(settings, backup_id)
        audit.record(db, "backup.restore_started", actor_user_id=user.id, entity_type="backup", entity_id=backup_id,
                     summary="Wiederherstellung gestartet")
        db.commit()
        db.close()
        safety = backup_svc.restore_backup(request.app.state.engine, settings, path)
    except backup_svc.BackupError as e:
        raise HTTPException(400, detail={"code": "restore_failed", "detail": str(e)})
    return {"ok": True, "safety_backup": safety.name, "note": "Bitte erneut anmelden."}


protected.include_router(backup_router)
