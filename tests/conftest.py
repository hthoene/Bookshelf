from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from bookshelf import security
from bookshelf.config import Settings
from bookshelf.main import create_app

ADMIN = ("admin", "secret123")


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    username, password = ADMIN
    response = client.post(
        "/setup",
        data={"username": username, "password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


def make_epub(
    title: str = "The Test Book",
    author: str = "Ada Lovelace",
    series: str | None = "Engines",
    series_index: str = "2",
    with_cover: bool = True,
) -> bytes:
    """Build a minimal but valid EPUB 2 file in memory."""
    series_meta = (
        f'<meta name="calibre:series" content="{series}"/>'
        f'<meta name="calibre:series_index" content="{series_index}"/>'
        if series
        else ""
    )
    cover_meta = '<meta name="cover" content="cover-img"/>' if with_cover else ""
    cover_item = (
        '<item id="cover-img" href="images/cover.png" media-type="image/png"/>'
        if with_cover
        else ""
    )
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{escape(title)}</dc:title>
    <dc:creator opf:role="aut">{escape(author)}</dc:creator>
    <dc:creator opf:role="ill">Some Illustrator</dc:creator>
    <dc:language>en</dc:language>
    <dc:description>&lt;p&gt;A &lt;b&gt;fine&lt;/b&gt; book.&lt;/p&gt;&lt;p&gt;Second paragraph.&lt;/p&gt;</dc:description>
    {series_meta}{cover_meta}
  </metadata>
  <manifest>
    <item id="text" href="text.xhtml" media-type="application/xhtml+xml"/>
    {cover_item}
  </manifest>
  <spine><itemref idref="text"/></spine>
</package>"""
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/text.xhtml", f"<html><body><p>{escape(title)}</p></body></html>")
        if with_cover:
            image = io.BytesIO()
            Image.new("RGB", (300, 450), (180, 40, 40)).save(image, "PNG")
            archive.writestr("OEBPS/images/cover.png", image.getvalue())
    return buffer.getvalue()


def upload(client: TestClient, filename: str, data: bytes):
    return client.post("/api/books", files={"file": (filename, data, "application/octet-stream")})
