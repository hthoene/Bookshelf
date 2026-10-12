"""Fill a running *development* instance with demo books and reading progress.

    python scripts/dev_seed.py [--url http://localhost:8765]

Creates the admin account "demo" / "demo1234" on a fresh instance (or logs in with it),
uploads generated EPUBs of public-domain classics, reports KOReader progress for some and
uploads a generated KOReader statistics database via WebDAV, like a real device would.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import random
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bookshelf.services.hashing import partial_md5  # noqa: E402

USERNAME, PASSWORD = "demo", "demo1234"

# title, author, (series, index), cover colours (None = generated placeholder), progress, device
BOOKS = [
    ("Middlemarch", "George Eliot", None, ((44, 62, 80), (22, 30, 40)), None, None),
    ("Anne of Green Gables", "L. M. Montgomery", None, None, None, None),
    ("The Time Machine", "H. G. Wells", None, ((26, 82, 118), (10, 36, 56)), 1.0, "PocketBook Era"),
    ("Jane Eyre", "Charlotte Brontë", None, ((120, 40, 48), (60, 18, 24)), None, None),
    ("The Odyssey", "Homer", None, None, 0.08, "Kobo Libra Colour"),
    ("Dracula", "Bram Stoker", None, ((30, 30, 34), (90, 14, 20)), 0.34, "Kobo Libra Colour"),
    (
        "The Hound of the Baskervilles",
        "Arthur Conan Doyle",
        ("Sherlock Holmes", 5),
        ((70, 84, 52), (30, 38, 22)),
        None,
        None,
    ),
    ("Frankenstein", "Mary Shelley", None, ((54, 70, 66), (18, 26, 26)), 1.0, "PocketBook Era"),
    ("Moby-Dick", "Herman Melville", None, ((20, 70, 96), (196, 172, 120)), 0.71, "PocketBook Era"),
    (
        "The Adventures of Sherlock Holmes",
        "Arthur Conan Doyle",
        ("Sherlock Holmes", 3),
        None,
        None,
        None,
    ),
    (
        "Pride and Prejudice",
        "Jane Austen",
        None,
        ((214, 196, 170), (150, 110, 90)),
        0.46,
        "Kobo Libra Colour",
    ),
]

DESCRIPTION = (
    "A demo book generated for development. It contains no real text, but its metadata, "
    "cover and reading progress behave exactly like a real e-book in your library."
)


def make_epub(title, author, series, colours) -> bytes:
    meta = ""
    if series:
        meta += f'<meta name="calibre:series" content="{escape(series[0])}"/>'
        meta += f'<meta name="calibre:series_index" content="{series[1]}"/>'
    if colours:
        meta += '<meta name="cover" content="cover"/>'
    cover_item = '<item id="cover" href="cover.jpg" media-type="image/jpeg"/>' if colours else ""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>
    <dc:language>en</dc:language><dc:publisher>Public Domain Press</dc:publisher>
    <dc:description>{escape(DESCRIPTION)}</dc:description>{meta}
  </metadata>
  <manifest><item id="t" href="t.xhtml" media-type="application/xhtml+xml"/>{cover_item}</manifest>
  <spine><itemref idref="t"/></spine>
</package>"""
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("content.opf", opf)
        archive.writestr("t.xhtml", f"<html><body><h1>{escape(title)}</h1></body></html>")
        if colours:
            archive.writestr("cover.jpg", make_cover(title, author, *colours))
    return buffer.getvalue()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["georgiab.ttf", "DejaVuSerif-Bold.ttf"] if bold else ["georgia.ttf", "DejaVuSerif.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(candidate, font=font) <= width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


def make_cover(title: str, author: str, top, bottom) -> bytes:
    width, height = 600, 900
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):  # vertical gradient
        t = y / height
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)),
        )
    light = sum(top) / 3 > 150
    ink = (40, 32, 28) if light else (250, 246, 238)
    draw.rectangle((36, 36, width - 36, height - 36), outline=ink, width=2)
    draw.line((90, 300, width - 90, 300), fill=ink, width=2)

    text = title.upper() if len(title) < 14 else title
    size = 58
    while True:  # shrink until every line fits inside the frame
        title_font = _font(size, bold=True)
        lines = _wrap(draw, text, title_font, width - 160)
        if (
            size <= 30
            or max(draw.textlength(line, font=title_font) for line in lines) <= width - 160
        ):
            break
        size -= 4
    y = 340
    for line in lines:
        draw.text((width / 2, y), line, font=title_font, fill=ink, anchor="ma")
        y += int(size * 1.2)
    draw.line((width / 2 - 40, y + 20, width / 2 + 40, y + 20), fill=ink, width=2)
    draw.text((width / 2, height - 130), author, font=_font(32), fill=ink, anchor="ma")

    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


STATS_SCHEMA = """
CREATE TABLE book (id integer PRIMARY KEY autoincrement, title text, authors text, notes integer,
    last_open integer, highlights integer, pages integer, series text, language text, md5 text,
    total_read_time integer, total_read_pages integer);
CREATE TABLE page_stat_data (id_book integer, page integer NOT NULL DEFAULT 0,
    start_time integer NOT NULL DEFAULT 0, duration integer NOT NULL DEFAULT 0,
    total_pages integer NOT NULL DEFAULT 0, UNIQUE (id_book, page, start_time));
"""
PAGES = 320


def make_statistics(read_books: list[tuple[str, str, str, float]]) -> bytes:
    """A KOReader statistics.sqlite3 for (title, author, md5, progress) tuples.

    The history is generated backwards from today: the books in progress were read most
    recently (in turns), the finished ones before that. The last days are always active, so the
    demo shows a reading streak.
    """
    rng = random.Random(7)
    current = [b for b in read_books if b[3] < 1]
    finished = [b for b in read_books if b[3] >= 1]
    last_page = {b[2]: PAGES if b[3] >= 1 else int(PAGES * b[3]) for b in read_books}
    rows: dict[str, list[tuple[int, int, int]]] = {b[2]: [] for b in read_books}

    today = datetime.now(UTC).replace(hour=18, minute=0, second=0, microsecond=0)
    day = today
    while any(last_page.values()):
        if rng.random() < 0.7 or today - day < timedelta(days=6):
            pending = [b for b in current if last_page[b[2]]]
            book = rng.choice(pending) if pending else next(b for b in finished if last_page[b[2]])
            count = min(rng.randint(12, 55), last_page[book[2]])
            start = int(day.timestamp()) + rng.randint(-4, 2) * 1800
            for page in range(last_page[book[2]] - count + 1, last_page[book[2]] + 1):
                seconds = rng.randint(55, 110)
                rows[book[2]].append((start, page, seconds))
                start += seconds
            last_page[book[2]] -= count
        day -= timedelta(days=1)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "statistics.sqlite3")
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(STATS_SCHEMA)
            for title, author, md5, _ in read_books:
                book_id = conn.execute(
                    "INSERT INTO book (title, authors, md5, pages, last_open) VALUES (?,?,?,?,?)",
                    (title, author, md5, PAGES, 0),
                ).lastrowid
                conn.executemany(
                    "INSERT INTO page_stat_data VALUES (?, ?, ?, ?, ?)",
                    [(book_id, page, start, secs, PAGES) for start, page, secs in rows[md5]],
                )
            conn.commit()
        return path.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8765")
    base = parser.parse_args().url.rstrip("/")

    with httpx.Client(base_url=base, follow_redirects=False) as client:
        form = {"username": USERNAME, "password": PASSWORD, "password_confirm": PASSWORD}
        if client.post("/setup", data=form).headers.get("location") != "/":
            client.post("/login", data={"username": USERNAME, "password": PASSWORD})
        sync_headers = {
            "x-auth-user": USERNAME,
            "x-auth-key": hashlib.md5(PASSWORD.encode()).hexdigest(),
        }
        read_books = []
        for title, author, series, colours, progress, device in BOOKS:
            data = make_epub(title, author, series, colours)
            filename = f"{author} - {title}.epub"
            response = client.post("/api/books", files={"file": (filename, data)})
            print(f"{response.status_code} {title}")
            if progress is None:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, "book.epub")
                path.write_bytes(data)
                document = partial_md5(path)
            read_books.append((title, author, document, progress))
            client.put(
                "/syncs/progress",
                headers=sync_headers,
                json={
                    "document": document,
                    "progress": "/body/DocFragment[5]/body/p[3]/text().0",
                    "percentage": progress,
                    "device": device,
                    "device_id": device.lower().replace(" ", "-"),
                },
            )

        response = client.put(
            "/webdav/statistics.sqlite3",
            content=make_statistics(read_books),
            auth=(USERNAME, PASSWORD),
        )
        print(f"{response.status_code} statistics.sqlite3")


if __name__ == "__main__":
    main()
