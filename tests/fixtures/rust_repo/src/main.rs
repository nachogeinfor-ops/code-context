//! Entry point for the rustapi HTTP server.
//!
//! Wires config -> database -> repository -> service -> handler layers and
//! starts an axum HTTP server listening on the configured port. Mirrors the
//! shape of the Go fixture (`tests/fixtures/go_repo/cmd/server/main.go`).

use std::net::SocketAddr;
use std::sync::Arc;

use axum::routing::{delete, get, patch, post};
use axum::Router;
use tokio::signal;
use tower_http::trace::TraceLayer;

mod config;
mod database;
mod dto;
mod error;
mod handlers;
mod middleware;
mod models;
mod repository;
mod services;

use crate::config::Config;
use crate::database::connect_pool;
use crate::middleware::auth::require_auth;
use crate::middleware::logging::request_log_layer;
use crate::repository::item_repository::ItemRepository;
use crate::repository::user_repository::UserRepository;
use crate::services::auth_service::AuthService;
use crate::services::item_service::ItemService;
use crate::services::user_service::UserService;

/// Shared application state — every handler gets a clone via `State<AppState>`.
#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub auth: Arc<AuthService>,
    pub users: Arc<UserService>,
    pub items: Arc<ItemService>,
}

/// Initialise tracing, load config, open the database, build the Router, and
/// run the server until SIGTERM / Ctrl-C.
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt().with_env_filter("info").init();

    let cfg = Arc::new(Config::from_env()?);
    let pool = connect_pool(&cfg).await?;

    let user_repo = Arc::new(UserRepository::new(pool.clone()));
    let item_repo = Arc::new(ItemRepository::new(pool.clone()));

    let auth_svc = Arc::new(AuthService::new(cfg.clone()));
    let user_svc = Arc::new(UserService::new(user_repo.clone(), auth_svc.clone()));
    let item_svc = Arc::new(ItemService::new(item_repo.clone()));

    let state = AppState {
        config: cfg.clone(),
        auth: auth_svc.clone(),
        users: user_svc.clone(),
        items: item_svc.clone(),
    };

    let public = Router::new()
        .route("/auth/login", post(handlers::auth::login))
        .route("/auth/refresh", post(handlers::auth::refresh));

    let protected = Router::new()
        .route("/users", post(handlers::users::create_user).get(handlers::users::list_users))
        .route(
            "/users/:id",
            get(handlers::users::get_user)
                .patch(handlers::users::update_user)
                .delete(handlers::users::delete_user),
        )
        .route("/items", post(handlers::items::create_item).get(handlers::items::list_items))
        .route(
            "/items/:id",
            get(handlers::items::get_item)
                .patch(handlers::items::update_item)
                .delete(handlers::items::delete_item),
        )
        .layer(axum::middleware::from_fn_with_state(state.clone(), require_auth));

    let app = public
        .merge(protected)
        .with_state(state)
        .layer(request_log_layer())
        .layer(TraceLayer::new_for_http());

    let addr: SocketAddr = format!("0.0.0.0:{}", cfg.port).parse()?;
    tracing::info!("listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

/// Resolves when the process receives Ctrl-C or SIGTERM. Used by axum's
/// `with_graceful_shutdown` to drain in-flight requests before exiting.
async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("failed to install Ctrl-C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("failed to install signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    tracing::info!("shutdown signal received, draining...");
}
