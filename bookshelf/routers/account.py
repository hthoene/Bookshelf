"""Account settings: password change and device setup instructions (KOReader, OPDS)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from ..deps import DB, SESSION_COOKIE, CurrentUser
from ..models import User
from ..services import sessions, users
from ..templating import render

router = APIRouter()


def _render_settings(request: Request, user: User, status_code: int = 200, **extra: object):
    server_url = str(request.base_url).rstrip("/")
    return render(
        request,
        "settings.html",
        status_code=status_code,
        user=user,
        nav="settings",
        server_url=server_url,
        opds_url=f"{server_url}/opds",
        **extra,
    )


@router.get("/settings")
def settings_page(request: Request, user: CurrentUser) -> Response:
    return _render_settings(request, user)


@router.post("/settings/password")
def change_password(
    request: Request,
    db: DB,
    user: CurrentUser,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()],
) -> Response:
    error = None
    if users.authenticate(db, user.username, current_password) is None:
        error = "Your current password is incorrect."
    elif new_password != new_password_confirm:
        error = "The new passwords don’t match."
    else:
        try:
            users.set_password(db, user, new_password)
        except users.UserError as exc:
            error = str(exc)
    if error:
        return _render_settings(request, user, status_code=422, password_error=error)

    sessions.end_other_sessions(db, user, keep_token=request.cookies.get(SESSION_COOKIE))
    return _render_settings(
        request,
        user,
        password_notice="Password changed. Remember to log in again on your KOReader devices.",
    )
