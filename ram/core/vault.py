"""Encrypted secret vault — passwords, account numbers, kid SSNs, garage codes.

Encryption uses Fernet derived from OLLIE_VAULT_PASSPHRASE. Each entry is
stored ciphertext-only; the passphrase is never persisted.
"""
from __future__ import annotations

import base64
import hashlib
import time
from typing import Any

from sqlalchemy import Column, Integer, String, Text, Float

from ram.core.config import settings
from ram.core.memory import Base, db, _engine


class VaultItem(Base):
    __tablename__ = "vault"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, index=True)
    kind = Column(String, default="secret")
    ciphertext = Column(Text)
    note = Column(Text, default="")
    ts = Column(Float, default=time.time)


Base.metadata.create_all(_engine)


def _key() -> bytes | None:
    pw = settings.ollie_vault_passphrase
    if not pw:
        return None
    digest = hashlib.sha256(pw.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    k = _key()
    return Fernet(k) if k else None


def store(name: str, value: str, kind: str = "secret", note: str = "") -> str:
    f = _fernet()
    if not f:
        return "ERROR: cryptography missing or OLLIE_VAULT_PASSPHRASE not set"
    ct = f.encrypt(value.encode()).decode()
    with db() as s:
        existing = s.query(VaultItem).filter(VaultItem.name == name).one_or_none()
        if existing:
            existing.ciphertext = ct
            existing.kind = kind
            existing.note = note
            existing.ts = time.time()
        else:
            s.add(VaultItem(name=name, kind=kind, ciphertext=ct, note=note))
    return f"vault[{name}] saved"


def reveal(name: str) -> str:
    f = _fernet()
    if not f:
        return "ERROR: vault unavailable"
    with db() as s:
        item = s.query(VaultItem).filter(VaultItem.name == name).one_or_none()
        if not item:
            return f"no vault item '{name}'"
        try:
            return f.decrypt(item.ciphertext.encode()).decode()
        except Exception:
            return "ERROR: decryption failed (wrong passphrase?)"


def list_items() -> list[dict]:
    with db() as s:
        return [
            {"name": i.name, "kind": i.kind, "note": i.note, "ts": i.ts}
            for i in s.query(VaultItem).order_by(VaultItem.name).all()
        ]
