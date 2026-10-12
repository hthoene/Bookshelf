"""Browser login sessions backed by the database."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import security
from ..db import utcnow
from ..models import AuthSession, User


def create_session(db: Session, user: User, days: int) -> str:
    """Create a session and return the raw token (to be stored in a cookie)."""
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    token = security.new_token()
    db.add(
        AuthSession(
            token_hash=security.sha256_hex(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=days),
        )
    )
    db.commit()
    return token


def user_for_token(db: Session, token: str) -> User | None:
    session = db.get(AuthSession, security.sha256_hex(token))
    if session is None or session.expires_at < utcnow():
        return None
    return session.user


def end_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == security.sha256_hex(token)))
    db.commit()


def end_other_sessions(db: Session, user: User, keep_token: str | None = None) -> None:
    query = delete(AuthSession).where(AuthSession.user_id == user.id)
    if keep_token:
        query = query.where(AuthSession.token_hash != security.sha256_hex(keep_token))
    db.execute(query)
    db.commit()
