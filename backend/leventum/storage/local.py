"""Dateispeicher. Die Datenbank kennt nur den relativen Schlüssel (`key`), nie einen absoluten Pfad.
Für einen Serverbetrieb kann eine weitere FileStore-Implementierung (z. B. S3) ergänzt werden."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

# Erlaubte Typen: Endung -> (MIME, Magic-Bytes-Präfixe; None = textbasiert/keine Prüfung)
ALLOWED: dict[str, tuple[str, tuple[bytes, ...] | None]] = {
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (b"PK\x03\x04",)),
    ".txt": ("text/plain", None),
    ".csv": ("text/csv", None),
}


class FileValidationError(Exception):
    pass


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int
    sha256: str
    mime: str
    original_name: str


class FileStore(Protocol):
    def save(self, stream: BinaryIO, original_name: str) -> StoredFile: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalFileStore:
    def __init__(self, root: Path, max_bytes: int):
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # Pfad-Traversal-Schutz
            raise FileValidationError("Ungültiger Dateischlüssel.")
        return p

    def save(self, stream: BinaryIO, original_name: str) -> StoredFile:
        safe_name = Path(original_name.replace("\\", "/")).name
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED:
            raise FileValidationError(f"Dateityp '{ext or '(ohne Endung)'}' ist nicht erlaubt.")
        mime, magics = ALLOWED[ext]
        key = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}{ext}"
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        head = b""
        try:
            with open(target, "wb") as out:
                while chunk := stream.read(1024 * 256):
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FileValidationError("Die Datei überschreitet die maximale Größe.")
                    h.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise FileValidationError("Die Datei ist leer.")
            if magics and not any(head.startswith(m) for m in magics):
                raise FileValidationError("Der Dateiinhalt passt nicht zur Dateiendung.")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return StoredFile(key=key, size=size, sha256=h.hexdigest(), mime=mime, original_name=safe_name)

    def open(self, key: str) -> BinaryIO:
        return open(self._path(key), "rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
