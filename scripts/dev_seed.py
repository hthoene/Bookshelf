"""Fill a running *development* instance with demo books and reading progress.

    python scripts/dev_seed.py [--url http://localhost:8765]

Creates the admin account "demo" / "demo1234" on a fresh instance (or logs in with it),
uploads generated EPUBs of public-domain classics and reports KOReader progress for some.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tempfile
import zipfile
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


if __name__ == "__main__":
    main()
