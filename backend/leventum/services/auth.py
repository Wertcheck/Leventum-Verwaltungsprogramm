from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leventum.config import Settings
from leventum.db.base import utcnow
from leventum.db.engine import aware
from leventum.models import AppUser, Role, UserSession
from leventum.security.passwords import hash_password, verify_password
from leventum.services import audit


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def needs_setup(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(AppUser)) == 0


def create_admin(db: Session, settings: Settings, username: str, display_name: str, password: str) -> AppUser:
    if not needs_setup(db):
        raise AuthError("setup_done", "Die Ersteinrichtung ist bereits abgeschlossen.")
    username = username.strip()
    if not username:
        raise AuthError("invalid", "Benutzername fehlt.")
    if len(password) < settings.min_password_length:
        raise AuthError("weak_password", f"Das Passwort muss mindestens {settings.min_password_length} Zeichen lang sein.")
    role = db.scalar(select(Role).where(Role.code == "admin"))
    user = AppUser(username=username, display_name=display_name.strip() or username,
                   password_hash=hash_password(password), role_id=role.id)
    db.add(user)
    db.flush()
    audit.record(db, "user.created", actor_user_id=user.id, entity_type="user", entity_id=user.id,
                 summary="Administrator bei der Ersteinrichtung angelegt")
    return user


def login(db: Session, settings: Settings, username: str, password: str) -> tuple[str, AppUser]:
    """Gibt (Klartext-Token, Benutzer) zurück. Fehlermeldungen verraten nicht, ob der Benutzer existiert."""
    now = utcnow()
    user = db.scalar(select(AppUser).where(AppUser.username == username.strip()))
    generic = AuthError("invalid_credentials", "Benutzername oder Passwort ist falsch.")
    if user is None or not user.is_active:
        audit.record(db, "auth.login_failed", summary="Anmeldung fehlgeschlagen (unbekannter/inaktiver Benutzer)")
        db.commit()
        raise generic
    if user.locked_until and aware(user.locked_until) > now:
        audit.record(db, "auth.login_blocked", actor_user_id=user.id, entity_type="user", entity_id=user.id,
                     summary="Anmeldung während Sperre abgelehnt")
        db.commit()
        raise AuthError("locked", "Zu viele Fehlversuche. Bitte später erneut versuchen.")
    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        details = None
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
            details = {"locked_until": user.locked_until.isoformat()}
        audit.record(db, "auth.login_failed", actor_user_id=user.id, entity_type="user", entity_id=user.id,
                     summary="Anmeldung fehlgeschlagen", details=details)
        db.commit()
        raise generic
    user.failed_login_count = 0
    user.locked_until = None
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=_hash_token(token), user_id=user.id,
                       expires_at=now + timedelta(hours=settings.session_absolute_hours)))
    audit.record(db, "auth.login", actor_user_id=user.id, entity_type="user", entity_id=user.id, summary="Angemeldet")
    db.commit()
    return token, user


def resolve_session(db: Session, settings: Settings, token: str | None) -> AppUser | None:
    if not token:
        return None
    s = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    now = utcnow()
    if s is None or s.revoked_at is not None or aware(s.expires_at) <= now:
        return None
    if aware(s.last_seen_at) + timedelta(minutes=settings.session_idle_minutes) <= now:
        return None
    if not s.user.is_active:
        return None
    s.last_seen_at = now
    db.commit()
    return s.user


def logout(db: Session, token: str | None) -> None:
    if not token:
        return
    s = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if s and s.revoked_at is None:
        s.revoked_at = utcnow()
        audit.record(db, "auth.logout", actor_user_id=s.user_id, entity_type="user", entity_id=s.user_id, summary="Abgemeldet")
        db.commit()
