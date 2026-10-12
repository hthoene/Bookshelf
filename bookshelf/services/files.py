"""A small per-user file store that backs the WebDAV endpoint.

KOReader's cloud sync (e.g. for reading statistics) downloads a file, merges it on the device
and uploads it again with ``If-Match: <etag>``. The store therefore provides stable ETags and
atomic, precondition-checked replacement. It is deliberately flat: no sub-folders.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")


class PreconditionFailed(Exception):
    """An If-Match / If-None-Match condition did not hold."""


@dataclass(frozen=True)
class StoredFile:
    name: str
    path: Path
    size: int
    modified: datetime  # timezone-aware UTC
    etag: str


def is_valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name)) and not name.endswith((" ", "."))


class FileStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def list(self) -> list[StoredFile]:
        if not self.directory.is_dir():
            return []
        files = (self.get(path.name) for path in self.directory.iterdir())
        return sorted((f for f in files if f is not None), key=lambda f: f.name.casefold())

    def get(self, name: str) -> StoredFile | None:
        if not is_valid_name(name):
            return None
        path = self.directory / name
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        if not path.is_file():
            return None
        return StoredFile(
            name=name,
            path=path,
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, UTC),
            etag=f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
        )

    def new_temp_path(self) -> Path:
        """A hidden temp file inside the store, so the final rename is atomic."""
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory / f".upload-{uuid.uuid4().hex}"

    def commit(
        self,
        temp_path: Path,
        name: str,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> bool:
        """Atomically move ``temp_path`` to ``name``. Returns True if the file was created."""
        current = self.get(name)
        if if_match is not None and not _etag_matches(if_match, current):
            raise PreconditionFailed
        if if_none_match is not None and _etag_matches(if_none_match, current):
            raise PreconditionFailed
        os.replace(temp_path, self.directory / name)
        return current is None

    def delete(self, name: str) -> bool:
        current = self.get(name)
        if current is None:
            return False
        current.path.unlink(missing_ok=True)
        return True


def _etag_matches(header: str, current: StoredFile | None) -> bool:
    if current is None:
        return False
    for tag in header.split(","):
        tag = tag.strip()
        if tag == "*" or tag.removeprefix("W/") == current.etag:
            return True
    return False
