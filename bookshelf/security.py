"""Password hashing and token helpers.

KOReader's sync protocol never sends the plain password, only ``md5(password)`` (the "key").
Passwords are therefore stored as ``bcrypt(md5(password))`` so one hash verifies both the web
login and the KOReader key.
"""

from __future__ import annotations

import hashlib
import secrets
import time

import bcrypt

BCRYPT_ROUNDS = 12
_VERIFY_CACHE_TTL = 600  # seconds
_VERIFY_CACHE_MAX = 1000

# Successful verifications, so frequent sync/OPDS requests don't pay the bcrypt cost each time.
# Keyed by the stored hash, so a password change invalidates entries automatically.
_verified: dict[tuple[str, str], float] = {}


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hash_sync_key(key: str) -> str:
    return bcrypt.hashpw(key.lower().encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def hash_password(password: str) -> str:
    return hash_sync_key(md5_hex(password))


def verify_sync_key(key: str, password_hash: str) -> bool:
    key = key.lower()
    cache_key = (password_hash, sha256_hex(key))
    now = time.monotonic()
    if _verified.get(cache_key, 0.0) > now:
        return True
    try:
        valid = bcrypt.checkpw(key.encode(), password_hash.encode())
    except ValueError:
        return False
    if valid:
        if len(_verified) >= _VERIFY_CACHE_MAX:
            _verified.clear()
        _verified[cache_key] = now + _VERIFY_CACHE_TTL
    return valid


def verify_password(password: str, password_hash: str) -> bool:
    return verify_sync_key(md5_hex(password), password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)
