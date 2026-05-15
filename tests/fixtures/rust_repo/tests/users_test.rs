//! HTTP-level smoke tests for the `/users` CRUD endpoints.

use reqwest::StatusCode;
use serde_json::json;

mod common;
use common::TestApp;

#[tokio::test]
async fn create_user_returns_201_with_no_password_in_body() {
    let app = TestApp::spawn().await;
    let token = app.admin_token().await;

    let res = app
        .client()
        .post(app.url("/users"))
        .bearer_auth(&token)
        .json(&json!({
            "email": "dora@example.com",
            "username": "dora",
            "password": "supersecret",
        }))
        .send()
        .await
        .expect("send create");

    assert_eq!(res.status(), StatusCode::CREATED);
    let body: serde_json::Value = res.json().await.unwrap();
    assert_eq!(body["email"], "dora@example.com");
    assert!(body.get("password_hash").is_none());
}

#[tokio::test]
async fn create_user_with_duplicate_email_returns_409() {
    let app = TestApp::spawn().await;
    let token = app.admin_token().await;
    app.seed_user("evan@example.com", "evan", "longpassword").await;

    let res = app
        .client()
        .post(app.url("/users"))
        .bearer_auth(&token)
        .json(&json!({
            "email": "evan@example.com",
            "username": "evan2",
            "password": "longpassword",
        }))
        .send()
        .await
        .expect("send create");

    assert_eq!(res.status(), StatusCode::CONFLICT);
}

#[tokio::test]
async fn list_users_paginates() {
    let app = TestApp::spawn().await;
    let token = app.admin_token().await;
    for i in 0..5 {
        app.seed_user(&format!("u{i}@example.com"), &format!("user{i}"), "passw0rd").await;
    }

    let res = app
        .client()
        .get(app.url("/users?page=1&page_size=3"))
        .bearer_auth(&token)
        .send()
        .await
        .expect("send list");

    assert_eq!(res.status(), StatusCode::OK);
    let body: serde_json::Value = res.json().await.unwrap();
    assert_eq!(body["page"], 1);
    assert_eq!(body["page_size"], 3);
    assert!(body["items"].as_array().unwrap().len() <= 3);
}
