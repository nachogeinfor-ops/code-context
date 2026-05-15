//! HTTP-level smoke tests for `/auth/login` and `/auth/refresh`.

use reqwest::StatusCode;
use serde_json::json;

mod common;
use common::TestApp;

#[tokio::test]
async fn login_with_valid_credentials_returns_token_pair() {
    let app = TestApp::spawn().await;
    app.seed_user("alice@example.com", "alice", "correctpassword").await;

    let res = app
        .client()
        .post(app.url("/auth/login"))
        .json(&json!({
            "email": "alice@example.com",
            "password": "correctpassword",
        }))
        .send()
        .await
        .expect("send login");

    assert_eq!(res.status(), StatusCode::OK);
    let body: serde_json::Value = res.json().await.unwrap();
    assert!(body["access_token"].is_string());
    assert!(body["refresh_token"].is_string());
    assert_eq!(body["token_type"], "Bearer");
}

#[tokio::test]
async fn login_with_wrong_password_returns_401() {
    let app = TestApp::spawn().await;
    app.seed_user("bob@example.com", "bob", "rightpassword").await;

    let res = app
        .client()
        .post(app.url("/auth/login"))
        .json(&json!({
            "email": "bob@example.com",
            "password": "wrongpassword",
        }))
        .send()
        .await
        .expect("send login");

    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn refresh_with_valid_token_returns_new_pair() {
    let app = TestApp::spawn().await;
    let (_user_id, _access, refresh) = app
        .seed_user_and_login("carol@example.com", "carol", "anotherpassword")
        .await;

    let res = app
        .client()
        .post(app.url("/auth/refresh"))
        .json(&json!({ "refresh_token": refresh }))
        .send()
        .await
        .expect("send refresh");

    assert_eq!(res.status(), StatusCode::OK);
}
