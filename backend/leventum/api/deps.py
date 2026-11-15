from __future__ import annotations

from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from leventum.config import Settings
from leventum.models import AppUser
from leventum.security.permissions import has_permission
from leventum.services import auth

COOKIE = "leventum_session"
CLIENT_HEADER = "x-leventum-client"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> AppUser:
    user = auth.resolve_session(db, settings, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, detail={"code": "unauthenticated", "detail": "Nicht angemeldet."})
    return user


def require(permission: str):
    def dep(user: AppUser = Depends(current_user)) -> AppUser:
        if not has_permission(user.role.code, permission):
            raise HTTPException(403, detail={"code": "forbidden", "detail": "Keine Berechtigung."})
        return user
    return dep
