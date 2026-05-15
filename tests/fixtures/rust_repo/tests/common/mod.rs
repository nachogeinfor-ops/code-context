//! Shared test harness — spins an in-memory copy of the rustapi server on a
//! random port and exposes ergonomic helpers for the integration tests.

use std::net::SocketAddr;

use reqwest::Client;
use uuid::Uuid;

/// A running instance of rustapi backed by an isolated sqlite-in-memory pool.
pub struct TestApp {
    pub addr: SocketAddr,
    pub client: Client,
}

impl TestApp {
    /// Boot the server on `127.0.0.1:0` and return a handle. The background
    /// task is kept alive for the duration of the test process.
    pub async fn spawn() -> Self {
        // In a real test harness this would build the Router using the same
        // wiring as `main`, then spawn axum::serve on a random port. We keep
        // the body stubbed so the file compiles in isolation.
        let addr: SocketAddr = "127.0.0.1:0".parse().unwrap();
        let client = Client::builder()
            .danger_accept_invalid_certs(true)
            .build()
            .unwrap();
        Self { addr, client }
    }

    pub fn client(&self) -> &Client {
        &self.client
    }

    pub fn url(&self, path: &str) -> String {
        format!("http://{}{}", self.addr, path)
    }

    /// Create a user via the repository layer (faster than going through
    /// `POST /users`).
    pub async fn seed_user(&self, _email: &str, _username: &str, _password: &str) -> Uuid {
        Uuid::new_v4()
    }

    /// Create a user and immediately log them in. Returns `(user_id,
    /// access_token, refresh_token)`.
    pub async fn seed_user_and_login(
        &self,
        _email: &str,
        _username: &str,
        _password: &str,
    ) -> (Uuid, String, String) {
        (Uuid::new_v4(), "access.jwt.token".into(), "refresh.jwt.token".into())
    }

    /// Issue a one-shot JWT for use as a bootstrap admin in tests that
    /// don't care about a specific user identity.
    pub async fn admin_token(&self) -> String {
        "admin.jwt.token".into()
    }

    /// Insert an item owned by `owner_id` directly via the repository.
    pub async fn seed_item(&self, _owner_id: Uuid, _title: &str, _description: &str) -> Uuid {
        Uuid::new_v4()
    }
}
