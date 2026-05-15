//! Shared error type. Every handler returns `Result<T, ApiError>` so we get
//! consistent HTTP responses for every failure mode.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;
use thiserror::Error;

/// One enum to rule every fallible code path — handlers, services, and
/// repositories convert their own errors into [`ApiError`] via `From` impls.
#[derive(Debug, Error)]
pub enum ApiError {
    #[error("not found")]
    NotFound,
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("bad request: {0}")]
    BadRequest(String),
    #[error("unauthorized: {0}")]
    Unauthorized(String),
    #[error("forbidden")]
    Forbidden,
    #[error("validation failed: {0}")]
    Validation(String),
    #[error("internal: {0}")]
    Internal(#[from] anyhow::Error),
}

impl ApiError {
    fn status_code(&self) -> StatusCode {
        match self {
            ApiError::NotFound => StatusCode::NOT_FOUND,
            ApiError::Conflict(_) => StatusCode::CONFLICT,
            ApiError::BadRequest(_) | ApiError::Validation(_) => StatusCode::BAD_REQUEST,
            ApiError::Unauthorized(_) => StatusCode::UNAUTHORIZED,
            ApiError::Forbidden => StatusCode::FORBIDDEN,
            ApiError::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}

/// Render every variant as `{ "error": "<message>" }` JSON.
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = Json(json!({ "error": self.to_string() }));
        (self.status_code(), body).into_response()
    }
}

/// sqlx -> ApiError plumbing. Row-not-found becomes 404, every other sqlx
/// error becomes 500.
impl From<sqlx::Error> for ApiError {
    fn from(err: sqlx::Error) -> Self {
        match err {
            sqlx::Error::RowNotFound => ApiError::NotFound,
            other => ApiError::Internal(other.into()),
        }
    }
}
