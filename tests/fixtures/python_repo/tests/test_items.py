"""Tests for the /items endpoints."""

from fastapi.testclient import TestClient


def _seed_user(client: TestClient) -> int:
    resp = client.post(
        "/users/",
        json={"email": "bob@example.com", "username": "bob", "password": "supersecret1"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_create_item_returns_201(client: TestClient) -> None:
    owner_id = _seed_user(client)
    resp = client.post(
        "/items/",
        params={"owner_id": owner_id},
        json={"title": "First item", "description": "A test item"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "First item"
    assert data["owner_id"] == owner_id


def test_list_items_route(client: TestClient) -> None:
    owner_id = _seed_user(client)
    client.post("/items/", params={"owner_id": owner_id}, json={"title": "Item A"})
    resp = client.get("/items/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_item_not_found(client: TestClient) -> None:
    resp = client.get("/items/99999")
    assert resp.status_code == 404


def test_update_item(client: TestClient) -> None:
    owner_id = _seed_user(client)
    created = client.post("/items/", params={"owner_id": owner_id}, json={"title": "Old"}).json()
    resp = client.patch(f"/items/{created['id']}", json={"title": "New"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New"


def test_delete_item(client: TestClient) -> None:
    owner_id = _seed_user(client)
    created = client.post(
        "/items/", params={"owner_id": owner_id}, json={"title": "To delete"}
    ).json()
    assert client.delete(f"/items/{created['id']}").status_code == 204
    assert client.get(f"/items/{created['id']}").status_code == 404
