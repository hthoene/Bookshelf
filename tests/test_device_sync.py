"""Marking books for e-readers and the OPDS sync feed used by KOReader's catalog sync."""

from __future__ import annotations

import time
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from .conftest import ADMIN, make_epub, upload

ATOM = "{http://www.w3.org/2005/Atom}"


def feed_titles(client: TestClient, url: str) -> list[str]:
    response = client.get(url, auth=ADMIN)
    assert response.status_code == 200
    assert "kind=acquisition" in response.headers["content-type"]
    return [
        e.findtext(f"{ATOM}title") for e in ET.fromstring(response.content).iter(f"{ATOM}entry")
    ]


def mark(client: TestClient, book_id: int, enabled: bool = True) -> None:
    response = client.post(
        f"/books/{book_id}/device", data={"enabled": str(enabled).lower()}, follow_redirects=False
    )
    assert response.status_code == 303


def test_sync_feed_lists_marked_books_newest_marked_first(admin_client: TestClient) -> None:
    ids = {
        title: upload(admin_client, f"{title}.epub", make_epub(title=title)).json()["id"]
        for title in ("Emma", "Dracula", "Walden")
    }
    assert feed_titles(admin_client, "/opds/sync") == []

    mark(admin_client, ids["Walden"])
    time.sleep(0.01)
    mark(admin_client, ids["Emma"])
    # KOReader stops at the last downloaded entry, so newly marked books must come first.
    assert feed_titles(admin_client, "/opds/sync") == ["Emma", "Walden"]

    mark(admin_client, ids["Walden"])  # marking again keeps the original position
    assert feed_titles(admin_client, "/opds/sync") == ["Emma", "Walden"]

    mark(admin_client, ids["Emma"], enabled=False)
    assert feed_titles(admin_client, "/opds/sync") == ["Walden"]


def test_sync_feed_requires_auth_and_is_private(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    mark(admin_client, book_id)
    assert admin_client.get("/opds/sync").status_code == 401
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    response = admin_client.get("/opds/sync", auth=("bob", "bobpass1"))
    assert "<entry>" not in response.text


def test_whole_library_sync_feed_is_newest_first(admin_client: TestClient) -> None:
    for title in ("First", "Second", "Third"):
        upload(admin_client, f"{title}.epub", make_epub(title=title))
    assert feed_titles(admin_client, "/opds/books?sort=recent") == ["Third", "Second", "First"]


def test_navigation_and_library_filter(admin_client: TestClient) -> None:
    marked = upload(admin_client, "a.epub", make_epub(title="Marked")).json()["id"]
    upload(admin_client, "b.epub", make_epub(title="Other"))

    library = admin_client.get("/")
    assert "On e-reader" not in library.text  # the filter only appears once something is marked

    mark(admin_client, marked)
    library = admin_client.get("/")
    assert "On e-reader <small>1</small>" in library.text
    assert library.text.count('class="badge-device"') == 1

    filtered = admin_client.get("/?device=true", headers={"HX-Request": "true"})
    assert "Marked" in filtered.text and "Other" not in filtered.text

    book_page = admin_client.get(f"/books/{marked}")
    assert 'aria-pressed="true"' in book_page.text

    nav = admin_client.get("/opds", auth=ADMIN).text
    assert "Marked for e-reader" in nav
    assert feed_titles(admin_client, "/opds/books?device=1&sort=device") == ["Marked"]

    settings = admin_client.get("/settings").text
    assert "/opds/sync" in settings and "1 marked" in settings
