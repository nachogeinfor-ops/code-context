"""Tests for the /users endpoints."""

from fastapi.testclient import TestClient


def _create_user(
    client: TestClient,
    email: str = "alice@example.com",
    username: str = "alice",
) -> dict:
    resp = client.post(
        "/users/",
        json={"email": email, "username": username, "password": "supersecret1"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_user_returns_201(client: TestClient) -> None:
    data = _create_user(client)
    assert data["email"] == "alice@example.com"
    assert data["username"] == "alice"
    assert "hashed_password" not in data


def test_create_user_duplicate_email_returns_400(client: TestClient) -> None:
    _create_user(client)
    resp = client.post(
        "/users/",
        json={"email": "alice@example.com", "username": "alice2", "password": "supersecret1"},
    )
    assert resp.status_code == 400


def test_list_users(client: TestClient) -> None:
    _create_user(client)
    resp = client.get("/users/")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_get_user_by_id(client: TestClient) -> None:
    created = _create_user(client)
    resp = client.get(f"/users/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_user_not_found(client: TestClient) -> None:
    resp = client.get("/users/99999")
    assert resp.status_code == 404


def test_delete_user(client: TestClient) -> None:
    created = _create_user(client)
    resp = client.delete(f"/users/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/users/{created['id']}").status_code == 404
