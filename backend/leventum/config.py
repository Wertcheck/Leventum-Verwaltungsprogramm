"""Zentrale Konfiguration. Alle Speicherorte sind hier konfigurierbar (Env-Präfix LEVENTUM_)."""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Leventum"
    return Path.home() / ".local" / "share" / "leventum"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEVENTUM_", env_file=".env", extra="ignore")

    data_dir: Path = default_data_dir()
    database_url: str | None = None  # None -> SQLite in data_dir
    documents_dir: Path | None = None
    backup_dir: Path | None = None
    frontend_dist: Path | None = None

    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    session_idle_minutes: int = 480
    session_absolute_hours: int = 24
    max_failed_logins: int = 5
    lockout_minutes: int = 5
    min_password_length: int = 12
    max_upload_bytes: int = 25 * 1024 * 1024
    backup_max_age_hours: int = 72
    document_retention_days: int = 3650  # Annahme (nicht rechtlich geprüft): endgültige Löschung frühestens 10 Jahre nach dem Upload
    cookie_secure: bool = False  # True bei HTTPS-Serverbetrieb

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'db' / 'leventum.sqlite3').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    @property
    def documents_path(self) -> Path:
        return self.documents_dir or (self.data_dir / "documents")

    @property
    def backups_path(self) -> Path:
        return self.backup_dir or (self.data_dir / "backups")

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.data_dir / "db", self.documents_path, self.backups_path):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
