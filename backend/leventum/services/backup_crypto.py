"""Optionale Verschlüsselung von Backup-Dateien: AES-256-GCM, Schlüssel per scrypt aus einer Passphrase, Streaming in 1-MB-Blöcken.
Format: MAGIC | salt(16) | nonce-Präfix(8) | { len(4) | AESGCM(Block) }…  Jeder Block hat die Nonce (Präfix + Zähler) und als AAD ein Endekennzeichen
(Manipulation, Umordnung oder Abschneiden der Datei werden erkannt). NICHT verschlüsselt werden die laufende Datenbank und der Dokumentenordner –
das ist Aufgabe von BitLocker/Windows-Konto."""
from __future__ import annotations

import os
import struct
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"LEVBKP01"
CHUNK = 1024 * 1024
MIN_PASSPHRASE = 12


class CryptoError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def is_encrypted(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(len(MAGIC)) == MAGIC


def encrypt_file(src: Path, dst: Path, passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE:
        raise CryptoError("weak_passphrase", f"Die Passphrase muss mindestens {MIN_PASSPHRASE} Zeichen lang sein.")
    salt, prefix = os.urandom(16), os.urandom(8)
    aes = AESGCM(_key(passphrase, salt))
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(MAGIC + salt + prefix)
        counter, chunk = 0, fi.read(CHUNK)
        while True:
            nxt = fi.read(CHUNK)
            last = not nxt
            ct = aes.encrypt(prefix + struct.pack(">I", counter), chunk, b"\x01" if last else b"\x00")
            fo.write(struct.pack(">I", len(ct)) + ct)
            if last:
                break
            counter, chunk = counter + 1, nxt


def decrypt_file(src: Path, dst: Path, passphrase: str) -> None:
    try:
        with open(src, "rb") as fi:
            if fi.read(len(MAGIC)) != MAGIC:
                raise CryptoError("not_encrypted", "Keine verschlüsselte Leventum-Sicherung.")
            salt, prefix = fi.read(16), fi.read(8)
            if len(salt) != 16 or len(prefix) != 8:
                raise CryptoError("corrupt", "Die Sicherung ist unvollständig.")
            aes = AESGCM(_key(passphrase, salt))
            with open(dst, "wb") as fo:
                counter, saw_last = 0, False
                while hdr := fi.read(4):
                    if saw_last:
                        raise CryptoError("corrupt", "Unerwartete Daten nach dem Ende der Sicherung.")
                    (n,) = struct.unpack(">I", hdr)
                    ct = fi.read(n)
                    if len(ct) != n:
                        raise CryptoError("corrupt", "Die Sicherung ist abgeschnitten.")
                    nonce = prefix + struct.pack(">I", counter)
                    peek = fi.read(1)
                    is_last = not peek
                    if peek:
                        fi.seek(-1, 1)
                    try:
                        fo.write(aes.decrypt(nonce, ct, b"\x01" if is_last else b"\x00"))
                    except InvalidTag:
                        raise CryptoError("wrong_passphrase_or_tampered", "Falsche Passphrase oder die Sicherung wurde verändert/abgeschnitten.")
                    saw_last, counter = is_last, counter + 1
                if not saw_last:
                    raise CryptoError("corrupt", "Die Sicherung ist leer oder abgeschnitten.")
    except CryptoError:
        dst.unlink(missing_ok=True)
        raise
