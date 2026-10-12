from fastapi.testclient import TestClient

from bookshelf.config import Settings
from bookshelf.main import create_app
from bookshelf.security import md5_hex

from .conftest import ADMIN, make_epub, upload

HEADERS = {
    "x-auth-user": ADMIN[0],
    "x-auth-key": md5_hex(ADMIN[1]),
    "accept": "application/vnd.koreader.v1+json",
}


def test_healthcheck(client: TestClient) -> None:
    assert client.get("/healthcheck").json() == {"state": "OK"}


def test_auth(admin_client: TestClient) -> None:
    assert admin_client.get("/users/auth", headers=HEADERS).json() == {"authorized": "OK"}
    bad = admin_client.get("/users/auth", headers={**HEADERS, "x-auth-key": md5_hex("wrong")})
    assert bad.status_code == 401
    assert bad.json() == {"code": 2001, "message": "Unauthorized"}
    assert admin_client.get("/users/auth").status_code == 401


def test_progress_roundtrip_and_library_integration(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    page = admin_client.get(f"/books/{book_id}")
    document = page.text.split('KOReader document ID</dt><dd class="mono">')[1][:32]

    assert admin_client.get(f"/syncs/progress/{document}", headers=HEADERS).json() == {}

    saved = admin_client.put(
        "/syncs/progress",
        headers=HEADERS,
        json={
            "document": document,
            "progress": "/body/DocFragment[3]/body/p[2]/text().0",
            "percentage": 0.4237,
            "device": "Kobo Libra 2",
            "device_id": "ABC123",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["document"] == document

    fetched = admin_client.get(f"/syncs/progress/{document}", headers=HEADERS).json()
    assert fetched["percentage"] == 0.4237
    assert fetched["device"] == "Kobo Libra 2"
    assert fetched["progress"].startswith("/body/DocFragment")

    library = admin_client.get("/")
    assert "Continue reading" in library.text
    assert "42%" in library.text


def test_pdf_page_number_progress(admin_client: TestClient) -> None:
    response = admin_client.put(
        "/syncs/progress",
        headers=HEADERS,
        json={
            "document": "abc",
            "progress": 17,
            "percentage": 0.1,
            "device": "x",
            "device_id": "y",
        },
    )
    assert response.status_code == 200
    assert admin_client.get("/syncs/progress/abc", headers=HEADERS).json()["progress"] == "17"


def test_missing_document(admin_client: TestClient) -> None:
    response = admin_client.put("/syncs/progress", headers=HEADERS, json={"percentage": 0.5})
    assert response.status_code == 403
    assert response.json()["code"] == 2004


def test_registration_disabled_by_default(client: TestClient) -> None:
    response = client.post("/users/create", json={"username": "kobo", "password": md5_hex("pw")})
    assert response.status_code == 402
    assert response.json()["code"] == 2005


def test_registration_when_enabled(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, allow_registration=True))
    with TestClient(app) as client:
        key = md5_hex("readerpass")
        created = client.post("/users/create", json={"username": "kobo", "password": key})
        assert created.status_code == 201
        assert created.json() == {"username": "kobo"}

        again = client.post("/users/create", json={"username": "kobo", "password": key})
        assert again.json()["code"] == 2002

        headers = {"x-auth-user": "kobo", "x-auth-key": key}
        assert client.get("/users/auth", headers=headers).status_code == 200
        # The same account can log in to the web UI with the plain password.
        login = client.post(
            "/login", data={"username": "kobo", "password": "readerpass"}, follow_redirects=False
        )
        assert login.status_code == 303
