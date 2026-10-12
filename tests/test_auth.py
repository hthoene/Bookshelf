from fastapi.testclient import TestClient

from .conftest import ADMIN


def test_fresh_install_redirects_to_setup(client: TestClient) -> None:
    response = client.get("/", follow_redirects=True)
    assert response.url.path == "/setup"


def test_setup_only_works_once(admin_client: TestClient) -> None:
    response = admin_client.get("/setup", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_login_logout(admin_client: TestClient) -> None:
    admin_client.post("/logout")
    assert admin_client.get("/", follow_redirects=False).status_code == 303

    bad = admin_client.post("/login", data={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    assert "Wrong username or password" in bad.text

    good = admin_client.post(
        "/login", data={"username": "ADMIN", "password": ADMIN[1]}, follow_redirects=False
    )
    assert good.status_code == 303
    assert admin_client.get("/").status_code == 200


def test_open_redirect_is_blocked(admin_client: TestClient) -> None:
    admin_client.post("/logout")
    response = admin_client.post(
        "/login",
        data={"username": ADMIN[0], "password": ADMIN[1], "next": "//evil.example"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_admin_manages_users(admin_client: TestClient) -> None:
    created = admin_client.post("/admin/users", data={"username": "Bob", "password": "bobpass1"})
    assert created.status_code == 200
    assert "bob" in created.text

    duplicate = admin_client.post("/admin/users", data={"username": "bob", "password": "x" * 8})
    assert duplicate.status_code == 422

    short = admin_client.post("/admin/users", data={"username": "carol", "password": "123"})
    assert short.status_code == 422


def test_non_admin_cannot_manage_users(admin_client: TestClient, client: TestClient) -> None:
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    admin_client.post("/logout")
    client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert client.get("/admin/users").status_code == 403


def test_change_password(admin_client: TestClient) -> None:
    wrong = admin_client.post(
        "/settings/password",
        data={
            "current_password": "x",
            "new_password": "newpass1",
            "new_password_confirm": "newpass1",
        },
    )
    assert wrong.status_code == 422

    ok = admin_client.post(
        "/settings/password",
        data={
            "current_password": ADMIN[1],
            "new_password": "newpass1",
            "new_password_confirm": "newpass1",
        },
    )
    assert ok.status_code == 200
    admin_client.post("/logout")
    response = admin_client.post(
        "/login", data={"username": "admin", "password": "newpass1"}, follow_redirects=False
    )
    assert response.status_code == 303
