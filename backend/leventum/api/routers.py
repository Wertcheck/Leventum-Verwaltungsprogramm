from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum.api.deps import COOKIE, current_user, get_db, get_settings, require
from leventum.config import Settings
from leventum.models import AppUser
from leventum.security.finance_access import can_read_finance, require_finance_read
from leventum.services import audit, auth, backup as backup_svc
from leventum.services.errors import ServiceError
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
def health(request: Request):
    return {"status": "ok", "demo": bool(request.app.state.settings.demo_mode)}


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
def dashboard(as_of: str | None = Query(default=None, description="Stichtag (YYYY-MM-DD, nicht in der Zukunft); ohne Angabe heute. Erfordert finance:read"),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings), user: AppUser = Depends(current_user)):
    can_fin = can_read_finance(user)
    if as_of is not None and not can_fin:
        require_finance_read(user)  # Rechteprüfung VOR jeder Stichtagsvalidierung (auch bei ungültigem/zukünftigem Wert -> 403)
    return build_dashboard(db, as_of, settings.contract_end_preview_days, include_finance=can_fin)  # Auflösung/Validierung zentral in services/stichtag.resolve


# --- Backup (nur Administrator) -------------------------------------------------------------
backup_router = APIRouter(prefix="/system/backups", dependencies=[Depends(require("system:backup"))])


@backup_router.get("")
def backups_list(settings: Settings = Depends(get_settings)):
    return {"items": backup_svc.list_backups(settings), **backup_svc.latest_backup_info(settings)}


class BackupCreate(BaseModel):
    passphrase: str | None = Field(default=None, max_length=256)  # optional: verschlüsselte Sicherung (AES-256-GCM); die Passphrase wird NICHT gespeichert


class PassphraseBody(BaseModel):
    passphrase: str | None = Field(default=None, max_length=256)


@backup_router.post("")
def backups_create(request: Request, body: BackupCreate | None = None, db: Session = Depends(get_db), user: AppUser = Depends(current_user),
                   settings: Settings = Depends(get_settings)):
    pw = body.passphrase if body and body.passphrase else None
    try:
        path = backup_svc.create_backup(request.app.state.engine, settings, passphrase=pw)
    except backup_svc.BackupError as e:
        raise HTTPException(400, detail={"code": "backup_failed", "detail": str(e)})
    res = backup_svc.verify_backup(path, pw)
    audit.record(db, "backup.created", actor_user_id=user.id, entity_type="backup", entity_id=path.name,
                 summary="Backup erstellt", details={"verified": res.ok, "encrypted": bool(pw)})
    db.commit()
    return {"id": path.name, "encrypted": bool(pw), "verified": res.ok, "problems": res.problems}


@backup_router.post("/{backup_id}/verify")
def backups_verify(backup_id: str, body: PassphraseBody | None = None, settings: Settings = Depends(get_settings)):
    try:
        res = backup_svc.verify_backup(backup_svc.resolve_backup(settings, backup_id), body.passphrase if body else None)
    except backup_svc.BackupError as e:
        raise HTTPException(404, detail={"code": "not_found", "detail": str(e)})
    return {"ok": res.ok, "problems": res.problems}


class RestoreRequest(BaseModel):
    confirm: bool = False
    passphrase: str | None = Field(default=None, max_length=256)


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
        safety = backup_svc.restore_backup(request.app.state.engine, settings, path, body.passphrase)
    except backup_svc.BackupError as e:
        raise HTTPException(400, detail={"code": "restore_failed", "detail": str(e)})
    return {"ok": True, "safety_backup": safety.name, "note": "Bitte erneut anmelden."}


protected.include_router(backup_router)
