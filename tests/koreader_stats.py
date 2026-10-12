"""Build KOReader-style statistics.sqlite3 files for tests (schema version 20221111)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE book (
    id integer PRIMARY KEY autoincrement, title text, authors text, notes integer,
    last_open integer, highlights integer, pages integer, series text, language text,
    md5 text, total_read_time integer, total_read_pages integer
);
CREATE TABLE page_stat_data (
    id_book integer, page integer NOT NULL DEFAULT 0, start_time integer NOT NULL DEFAULT 0,
    duration integer NOT NULL DEFAULT 0, total_pages integer NOT NULL DEFAULT 0,
    UNIQUE (id_book, page, start_time), FOREIGN KEY(id_book) REFERENCES book(id)
);
CREATE INDEX page_stat_data_start_time ON page_stat_data (start_time);
"""


def make_statistics_db(path: Path, books: list[dict]) -> bytes:
    """``books``: dicts with title, authors, md5, pages and ``reads`` [(start_time, page, seconds)]."""
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        for book in books:
            cursor = conn.execute(
                "INSERT INTO book (title, authors, md5, pages, last_open) VALUES (?, ?, ?, ?, ?)",
                (book["title"], book.get("authors"), book.get("md5"), book.get("pages"), 0),
            )
            conn.executemany(
                "INSERT INTO page_stat_data (id_book, page, start_time, duration, total_pages)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (cursor.lastrowid, page, start, secs, book.get("pages") or 0)
                    for start, page, secs in book["reads"]
                ],
            )
        conn.commit()
    return path.read_bytes()
