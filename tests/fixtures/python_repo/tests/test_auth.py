"""Tests for the /auth endpoints — login and token refresh."""

from fastapi.testclient import TestClient


def _register(
    client: TestClient,
    email: str = "carol@example.com",
    password: str = "hunter22!",
) -> dict:
    resp = client.post(
        "/users/",
        json={"email": email, "username": email.split("@")[0], "password": password},
    )
    assert resp.status_code == 201
    return resp.json()


def test_login_returns_tokens(client: TestClient) -> None:
    _register(client)
    resp = client.post(
        "/auth/login",
        json={"username": "carol@example.com", "password": "hunter22!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    _register(client)
    resp = client.post("/auth/login", json={"username": "carol@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_returns_401(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401


def test_refresh_token_flow(client: TestClient) -> None:
    """Exchange a valid refresh token for a new token pair."""
    _register(client)
    tokens = client.post(
        "/auth/login", json={"username": "carol@example.com", "password": "hunter22!"}
    ).json()
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert "access_token" in new_tokens
    assert new_tokens["access_token"] != tokens["access_token"]


def test_refresh_with_invalid_token_returns_401(client: TestClient) -> None:
    resp = client.post("/auth/refresh", json={"refresh_token": "not.a.real.token"})
    assert resp.status_code == 401
