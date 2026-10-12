"""Library pages (grid, book details) and the upload API used by the web UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..deps import DB, AppSettings, AppStorage, CurrentUser
from ..models import User
from ..services import library
from ..services.library import BookEntry
from ..services.metadata.base import parse_float
from ..templating import render
from ._files import book_file_response, cover_response

router = APIRouter()


def _entry_or_404(db: DB, user: User, book_id: int) -> BookEntry:
    entry = library.get_entry(db, user, book_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return entry


@router.get("/")
def library_page(
    request: Request,
    db: DB,
    user: CurrentUser,
    q: str = "",
    status: str = "all",
    sort: str = "recent",
) -> Response:
    status = status if status in library.STATUSES else "all"
    sort = sort if sort in library.SORTS else "recent"
    matching = library.list_books(db, user, query=q, sort=sort)
    context = {
        "user": user,
        "nav": "library",
        "q": q,
        "status": status,
        "sort": sort,
        "entries": library.filter_by_status(matching, status),
        "counts": library.count_by_status(matching),
        "continue_reading": library.continue_reading(matching) if not q and status == "all" else [],
        "has_books": bool(matching) or bool(q),
    }
    # htmx requests (search, filters, refresh after upload) only need the library fragment.
    is_fragment = (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )
    template = "partials/library.html" if is_fragment else "library.html"
    return render(request, template, headers={"Vary": "HX-Request"}, **context)


@router.post("/api/books")
def upload_book(
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    try:
        book = library.import_book(
            db,
            storage,
            user,
            file.filename or "upload",
            file.file,
            max_bytes=settings.max_upload_bytes,
        )
    except library.DuplicateBookError as exc:
        return JSONResponse(
            {"error": str(exc), "book_id": exc.book.id, "duplicate": True}, status_code=409
        )
    except library.LibraryError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(
        {"id": book.id, "title": book.title, "url": f"/books/{book.id}"}, status_code=201
    )


@router.get("/books/{book_id}")
def book_page(request: Request, db: DB, user: CurrentUser, book_id: int) -> Response:
    entry = _entry_or_404(db, user, book_id)
    return render(request, "book.html", user=user, nav="library", entry=entry, book=entry.book)


@router.post("/books/{book_id}")
def update_book(
    request: Request,
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    book_id: int,
    title: Annotated[str, Form()] = "",
    author: Annotated[str, Form()] = "",
    series: Annotated[str, Form()] = "",
    series_index: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
    publisher: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    cover: Annotated[UploadFile | None, File()] = None,
) -> Response:
    entry = _entry_or_404(db, user, book_id)
    library.update_metadata(
        db,
        entry.book,
        title=title,
        author=author,
        series=series,
        series_index=parse_float(series_index.strip()),
        language=language,
        publisher=publisher,
        description=description,
    )
    if cover is not None and cover.filename:
        data = cover.file.read()
        if data:
            try:
                library.replace_cover(db, storage, entry.book, data)
            except library.LibraryError as exc:
                entry = _entry_or_404(db, user, book_id)
                return render(
                    request,
                    "book.html",
                    status_code=422,
                    user=user,
                    nav="library",
                    entry=entry,
                    book=entry.book,
                    error=str(exc),
                )
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@router.post("/books/{book_id}/delete")
def delete_book(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    entry = _entry_or_404(db, user, book_id)
    library.delete_book(db, storage, entry.book)
    return RedirectResponse("/", status_code=303)


@router.get("/books/{book_id}/file")
def download_book(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    return book_file_response(storage, _entry_or_404(db, user, book_id).book)


@router.get("/books/{book_id}/cover")
def book_cover(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    return cover_response(storage, _entry_or_404(db, user, book_id).book)
