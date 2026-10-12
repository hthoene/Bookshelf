"""The book library: importing, listing, searching, editing and deleting books."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..formats import detect_format
from ..models import Book, ReadingProgress, User
from ..storage import Storage
from . import covers, progress
from .hashing import filename_md5, partial_md5
from .metadata import extract_metadata

STATUSES = ("all", "reading", "unread", "finished")
SORTS = ("recent", "title", "author", "last_read")
FINISHED_THRESHOLD = 0.98
CONTINUE_READING_LIMIT = 8
_COPY_CHUNK = 1024 * 1024


class LibraryError(Exception):
    """An import/edit error with a user-facing message."""


class DuplicateBookError(LibraryError):
    def __init__(self, book: Book) -> None:
        super().__init__(f"Already in your library as “{book.title}”.")
        self.book = book


@dataclass(frozen=True)
class BookEntry:
    """A book together with its (optional) KOReader reading progress."""

    book: Book
    progress: ReadingProgress | None = None

    @property
    def percent(self) -> int:
        return round(self.progress.percentage * 100) if self.progress else 0

    @property
    def status(self) -> str:
        if self.progress is None or self.progress.percentage <= 0:
            return "unread"
        return "finished" if self.progress.percentage >= FINISHED_THRESHOLD else "reading"

    @property
    def last_read(self) -> datetime | None:
        if self.progress is None:
            return None
        return datetime.fromtimestamp(self.progress.timestamp, UTC).replace(tzinfo=None)


# --- Import -----------------------------------------------------------------------------------


def import_book(
    db: Session,
    storage: Storage,
    user: User,
    filename: str,
    source: BinaryIO,
    *,
    max_bytes: int,
) -> Book:
    filename = PurePath(filename.replace("\\", "/")).name[:500] or "upload"
    fmt = detect_format(filename)
    if fmt is None:
        raise LibraryError(f"Unsupported file type: {filename}")

    temp_path = storage.new_temp_path()
    stored_path: str | None = None
    try:
        size = _copy_limited(source, temp_path, max_bytes)
        if size == 0:
            raise LibraryError("The file is empty.")

        document_hash = partial_md5(temp_path)
        existing = db.scalar(
            select(Book).where(Book.user_id == user.id, Book.partial_md5 == document_hash)
        )
        if existing is not None:
            raise DuplicateBookError(existing)

        metadata = extract_metadata(temp_path, fmt, filename)
        stored_path = storage.store_book(temp_path, user.id, fmt)
        book = Book(
            user_id=user.id,
            title=metadata.title or filename,
            author=metadata.author,
            series=metadata.series,
            series_index=metadata.series_index,
            description=metadata.description,
            language=metadata.language,
            publisher=metadata.publisher,
            format=fmt,
            original_filename=filename,
            file_path=stored_path,
            file_size=size,
            partial_md5=document_hash,
            filename_md5=filename_md5(filename),
        )
        db.add(book)
        db.flush()  # assigns book.id for the cover file name
        if metadata.cover:
            book.has_cover = covers.save_cover(metadata.cover, storage.cover_path(book.id))
        db.commit()
        return book
    except BaseException:
        db.rollback()
        if stored_path is not None:
            (storage.books_dir / stored_path).unlink(missing_ok=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def _copy_limited(source: BinaryIO, target: Path, max_bytes: int) -> int:
    size = 0
    with target.open("wb") as out:
        while chunk := source.read(_COPY_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise LibraryError(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
            out.write(chunk)
    return size


# --- Queries ----------------------------------------------------------------------------------


def list_books(
    db: Session, user: User, *, query: str = "", sort: str = "recent"
) -> list[BookEntry]:
    """All books of ``user`` matching ``query``, with progress attached, sorted by ``sort``."""
    books = db.scalars(select(Book).where(Book.user_id == user.id)).all()
    progress_map = progress.progress_by_document(db, user.id)
    entries = [BookEntry(book, _progress_for(book, progress_map)) for book in books]
    if query.strip():
        terms = query.casefold().split()
        entries = [entry for entry in entries if _matches(entry.book, terms)]
    return sort_entries(entries, sort)


def get_entry(db: Session, user: User, book_id: int) -> BookEntry | None:
    book = db.get(Book, book_id)
    if book is None or book.user_id != user.id:
        return None
    records = db.scalars(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user.id,
            ReadingProgress.document.in_([book.partial_md5, book.filename_md5]),
        )
    )
    return BookEntry(book, _progress_for(book, {r.document: r for r in records}))


def filter_by_status(entries: list[BookEntry], status: str) -> list[BookEntry]:
    if status not in STATUSES or status == "all":
        return entries
    return [entry for entry in entries if entry.status == status]


def count_by_status(entries: list[BookEntry]) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    counts["all"] = len(entries)
    for entry in entries:
        counts[entry.status] += 1
    return counts


def continue_reading(entries: list[BookEntry]) -> list[BookEntry]:
    reading = [entry for entry in entries if entry.status == "reading"]
    reading.sort(key=lambda entry: entry.progress.timestamp, reverse=True)
    return reading[:CONTINUE_READING_LIMIT]


def sort_entries(entries: list[BookEntry], sort: str) -> list[BookEntry]:
    if sort == "title":
        return sorted(entries, key=lambda e: e.book.title.casefold())
    if sort == "author":
        return sorted(entries, key=_author_sort_key)
    if sort == "last_read":
        return sorted(
            entries, key=lambda e: e.progress.timestamp if e.progress else -1, reverse=True
        )
    return sorted(entries, key=lambda e: (e.book.created_at, e.book.id), reverse=True)


def _progress_for(book: Book, progress_map: dict[str, ReadingProgress]) -> ReadingProgress | None:
    """KOReader may identify a book by content or by file name; use the most recent match."""
    candidates = [progress_map.get(book.partial_md5), progress_map.get(book.filename_md5)]
    found = [record for record in candidates if record is not None]
    return max(found, key=lambda record: record.timestamp) if found else None


def _matches(book: Book, terms: list[str]) -> bool:
    haystack = " ".join(filter(None, (book.title, book.author, book.series))).casefold()
    return all(term in haystack for term in terms)


def _author_sort_key(entry: BookEntry) -> tuple:
    book = entry.book
    first_author = (book.author or "").split(" & ")[0].strip()
    # "Last, First" is already in sort order; "First Last" sorts by the last word.
    if "," in first_author:
        surname = first_author.split(",")[0]
    else:
        surname = first_author.split()[-1] if first_author else ""
    return (
        not book.author,
        surname.casefold(),
        (book.series or "").casefold(),
        book.series_index or 0,
        book.title.casefold(),
    )


# --- Mutations --------------------------------------------------------------------------------


def update_metadata(db: Session, book: Book, **changes: object) -> None:
    title = str(changes.pop("title", "") or "").strip()
    if title:
        book.title = title[:500]
    for field in ("author", "series", "language", "publisher", "description"):
        if field in changes:
            value = str(changes[field] or "").strip()
            setattr(book, field, value or None)
    if "series_index" in changes:
        book.series_index = changes["series_index"]  # type: ignore[assignment]
    db.commit()


def replace_cover(db: Session, storage: Storage, book: Book, data: bytes) -> None:
    if not covers.save_cover(data, storage.cover_path(book.id)):
        raise LibraryError("The cover image could not be read.")
    book.has_cover = True
    book.updated_at = utcnow()  # changes the cover URL, so browsers fetch the new image
    db.commit()


def delete_book(db: Session, storage: Storage, book: Book) -> None:
    storage.delete_book_files(book)
    db.delete(book)
    db.commit()
