"""FastAPI dependencies shared by all routers. Use the ``Annotated`` aliases in endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .config import Settings
from .models import User
from .services import sessions
from .storage import Storage

SESSION_COOKIE = "bookshelf_session"


class LoginRequired(Exception):
    """Raised when a page needs a logged-in user; handled in ``main.py``."""


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
AppStorage = Annotated[Storage, Depends(get_storage)]


def optional_user(request: Request, db: DB) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    return sessions.user_for_token(db, token) if token else None


OptionalUser = Annotated[User | None, Depends(optional_user)]


def current_user(user: OptionalUser) -> User:
    if user is None:
        raise LoginRequired
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrators only.")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )
