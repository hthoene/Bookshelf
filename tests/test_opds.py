from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from .conftest import ADMIN, make_epub, upload

ATOM = "{http://www.w3.org/2005/Atom}"


def test_requires_basic_auth(admin_client: TestClient) -> None:
    response = admin_client.get("/opds")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    assert admin_client.get("/opds", auth=(ADMIN[0], "wrong")).status_code == 401


def test_navigation_feed(admin_client: TestClient) -> None:
    response = admin_client.get("/opds", auth=ADMIN)
    assert response.status_code == 200
    assert "kind=navigation" in response.headers["content-type"]
    feed = ET.fromstring(response.content)
    titles = [entry.findtext(f"{ATOM}title") for entry in feed.iter(f"{ATOM}entry")]
    assert "Recently added" in titles


def test_acquisition_feed_search_and_download(admin_client: TestClient) -> None:
    dune = make_epub(title="Dune & Sons", author="Frank Herbert")
    upload(admin_client, "a.epub", dune)
    upload(admin_client, "b.epub", make_epub(title="Emma", author="Jane Austen", with_cover=False))

    response = admin_client.get("/opds/books?sort=title", auth=ADMIN)
    assert "kind=acquisition" in response.headers["content-type"]
    feed = ET.fromstring(response.content)  # must be well-formed despite "&" in a title
    entries = list(feed.iter(f"{ATOM}entry"))
    assert [e.findtext(f"{ATOM}title") for e in entries] == ["Dune & Sons", "Emma"]

    links = {link.get("rel"): link.get("href") for link in entries[0].iter(f"{ATOM}link")}
    acquisition = links["http://opds-spec.org/acquisition"]
    assert admin_client.get(acquisition, auth=ADMIN).content == dune
    assert admin_client.get(links["http://opds-spec.org/image"], auth=ADMIN).status_code == 200

    search = ET.fromstring(admin_client.get("/opds/books?q=austen", auth=ADMIN).content)
    assert [e.findtext(f"{ATOM}title") for e in search.iter(f"{ATOM}entry")] == ["Emma"]


def test_opensearch_description(admin_client: TestClient) -> None:
    response = admin_client.get("/opds/search.xml", auth=ADMIN)
    assert "{searchTerms}" in response.text
