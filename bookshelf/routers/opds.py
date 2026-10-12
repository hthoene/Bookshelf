"""OPDS 1.2 catalog, so e-readers (e.g. KOReader) can browse and download books.

Authentication is HTTP Basic with the regular Bookshelf username and password.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..deps import DB, AppStorage
from ..formats import mime_type
from ..models import User
from ..services import library, users
from ..templating import render
from ._files import book_file_response, cover_response

router = APIRouter(prefix="/opds", tags=["opds"])

NAVIGATION = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQUISITION = "application/atom+xml;profile=opds-catalog;kind=acquisition"
PAGE_SIZE = 50

_basic = HTTPBasic(realm="Bookshelf", auto_error=False)


def opds_user(db: DB, credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)]) -> User:
    user = (
        users.authenticate(db, credentials.username, credentials.password) if credentials else None
    )
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": 'Basic realm="Bookshelf"'},
        )
    return user


OpdsUser = Annotated[User, Depends(opds_user)]

# (id, title, description, query string) of the sections on the catalog start page.
_SECTIONS = [
    (
        "reading",
        "Continue reading",
        "Books you are currently reading",
        "status=reading&sort=last_read",
    ),
    ("recent", "Recently added", "Newest books first", "sort=recent"),
    ("title", "All books by title", "Your whole library A–Z", "sort=title"),
    ("author", "All books by author", "Sorted by author and series", "sort=author"),
    ("unread", "Unread", "Books you haven’t started yet", "status=unread&sort=title"),
]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("")
def catalog_root(request: Request, user: OpdsUser) -> Response:
    return render(
        request,
        "opds/navigation.xml",
        media_type=NAVIGATION,
        sections=_SECTIONS,
        now=_now(),
        navigation_type=NAVIGATION,
        acquisition_type=ACQUISITION,
    )


@router.get("/books")
def catalog_books(
    request: Request,
    db: DB,
    user: OpdsUser,
    q: str = "",
    status: str = "all",
    sort: str = "recent",
    page: int = 1,
) -> Response:
    page = max(page, 1)
    result = library.find_books(
        db, user, text=q, status=status, sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
    )
    next_url = None
    if result.has_more:
        url = request.url.include_query_params(page=page + 1)
        next_url = f"{url.path}?{url.query}"
    titles = {key: section_title for key, section_title, *_ in _SECTIONS}
    title = f"Search: {q}" if q else titles.get(status) or titles.get(sort) or "Books"
    return render(
        request,
        "opds/feed.xml",
        media_type=ACQUISITION,
        title=title,
        feed_id=f"books:{request.url.query or 'all'}",
        self_url=f"{request.url.path}?{request.url.query}",
        next_url=next_url,
        entries=result.entries,
        mime_type=mime_type,
        now=_now(),
        navigation_type=NAVIGATION,
        acquisition_type=ACQUISITION,
    )


@router.get("/search.xml")
def opensearch(request: Request, user: OpdsUser) -> Response:
    return render(
        request,
        "opds/opensearch.xml",
        media_type="application/opensearchdescription+xml",
        base_url=str(request.base_url).rstrip("/"),
        acquisition_type=ACQUISITION,
    )


@router.get("/books/{book_id}/file")
def download(db: DB, user: OpdsUser, storage: AppStorage, book_id: int) -> Response:
    entry = library.get_entry(db, user, book_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return book_file_response(storage, entry.book)


@router.get("/books/{book_id}/cover")
def cover(db: DB, user: OpdsUser, storage: AppStorage, book_id: int) -> Response:
    entry = library.get_entry(db, user, book_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return cover_response(storage, entry.book)
