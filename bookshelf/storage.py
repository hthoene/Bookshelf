"""File storage layout below the data directory.

<data_dir>/books/<user_id>/<uuid>.<ext>   uploaded book files
<data_dir>/covers/<book_id>.jpg           cover thumbnails
<data_dir>/tmp/                           in-progress uploads
<data_dir>/files/<user_id>/               WebDAV files (e.g. KOReader statistics)
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from .models import Book


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.books_dir = root / "books"
        self.covers_dir = root / "covers"
        self.tmp_dir = root / "tmp"
        self.files_dir = root / "files"

    def ensure_dirs(self) -> None:
        for directory in (self.books_dir, self.covers_dir, self.tmp_dir, self.files_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def new_temp_path(self) -> Path:
        return self.tmp_dir / uuid.uuid4().hex

    def store_book(self, source: Path, user_id: int, fmt: str) -> str:
        """Move a temp file into the library and return its path relative to ``books_dir``."""
        relative = f"{user_id}/{uuid.uuid4().hex}.{fmt}"
        target = self.books_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, target)
        return relative

    def book_path(self, book: Book) -> Path:
        return self.books_dir / book.file_path

    def cover_path(self, book_id: int) -> Path:
        return self.covers_dir / f"{book_id}.jpg"

    def delete_book_files(self, book: Book) -> None:
        self.book_path(book).unlink(missing_ok=True)
        self.cover_path(book.id).unlink(missing_ok=True)

    def user_files_dir(self, user_id: int) -> Path:
        return self.files_dir / str(user_id)

    def delete_user_dir(self, user_id: int) -> None:
        shutil.rmtree(self.books_dir / str(user_id), ignore_errors=True)
        shutil.rmtree(self.user_files_dir(user_id), ignore_errors=True)
