//! axum endpoint functions. Every handler takes `State<AppState>` for shared
//! services and a JSON or `Path` extractor for inputs, and returns
//! `Result<Json<T>, ApiError>` so failures render as a JSON error envelope
//! with the right HTTP status.

pub mod auth;
pub mod items;
pub mod users;
