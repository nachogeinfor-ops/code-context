//! HTTP-level smoke tests for the `/items` CRUD endpoints.

use reqwest::StatusCode;
use serde_json::json;

mod common;
use common::TestApp;

#[tokio::test]
async fn create_item_associates_owner_from_jwt() {
    let app = TestApp::spawn().await;
    let (user_id, access, _refresh) = app
        .seed_user_and_login("frank@example.com", "frank", "passw0rdpass")
        .await;

    let res = app
        .client()
        .post(app.url("/items"))
        .bearer_auth(&access)
        .json(&json!({
            "title": "First item",
            "description": "shiny",
        }))
        .send()
        .await
        .expect("send create");

    assert_eq!(res.status(), StatusCode::CREATED);
    let body: serde_json::Value = res.json().await.unwrap();
    assert_eq!(body["title"], "First item");
    assert_eq!(body["owner_id"], serde_json::Value::String(user_id.to_string()));
}

#[tokio::test]
async fn get_item_of_another_user_returns_403() {
    let app = TestApp::spawn().await;
    let (_grace_id, _grace_access, _) = app
        .seed_user_and_login("grace@example.com", "grace", "longenough")
        .await;
    let (henry_id, henry_access, _) = app
        .seed_user_and_login("henry@example.com", "henry", "longenough")
        .await;

    let id = app.seed_item(henry_id, "hidden", "private").await;
    let res = app
        .client()
        .get(app.url(&format!("/items/{id}")))
        .bearer_auth(&henry_access)
        .send()
        .await
        .expect("owner can read");
    assert_eq!(res.status(), StatusCode::OK);

    let foreign_access = app
        .seed_user_and_login("ivy@example.com", "ivy", "longenough")
        .await
        .1;
    let res = app
        .client()
        .get(app.url(&format!("/items/{id}")))
        .bearer_auth(&foreign_access)
        .send()
        .await
        .expect("foreigner forbidden");
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn delete_item_returns_204() {
    let app = TestApp::spawn().await;
    let (user_id, access, _) = app
        .seed_user_and_login("jane@example.com", "jane", "anotherpassword")
        .await;
    let id = app.seed_item(user_id, "ephemeral", "").await;

    let res = app
        .client()
        .delete(app.url(&format!("/items/{id}")))
        .bearer_auth(&access)
        .send()
        .await
        .expect("send delete");
    assert_eq!(res.status(), StatusCode::NO_CONTENT);
}
