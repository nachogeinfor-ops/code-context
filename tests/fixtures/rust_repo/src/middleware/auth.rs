//! `Authorization: Bearer <jwt>` middleware. Validates the access token and
//! attaches the decoded user id to the request as an [`AuthUserId`] extension
//! so downstream handlers can extract it with
//! `Extension<AuthUserId>`.

use axum::extract::{Request, State};
use axum::http::header::AUTHORIZATION;
use axum::middleware::Next;
use axum::response::Response;
use uuid::Uuid;

use crate::dto::auth_dto::TokenType;
use crate::error::ApiError;
use crate::AppState;

/// Newtype wrapper carrying the authenticated user's id through request
/// extensions. Handlers depend on this rather than parsing the JWT
/// themselves.
#[derive(Debug, Clone, Copy)]
pub struct AuthUserId(pub Uuid);

/// axum-style middleware function — registered via
/// `axum::middleware::from_fn_with_state`. Rejects 401 unless the request
/// carries a valid `Authorization: Bearer <access-jwt>` header.
pub async fn require_auth(
    State(state): State<AppState>,
    mut req: Request,
    next: Next,
) -> Result<Response, ApiError> {
    let raw = extract_bearer_token(&req)
        .ok_or_else(|| ApiError::Unauthorized("missing bearer token".into()))?;
    let claims = state.auth.validate_token(&raw, TokenType::Access)?;
    req.extensions_mut().insert(AuthUserId(claims.sub));
    Ok(next.run(req).await)
}

/// Pull the JWT out of an `Authorization: Bearer <token>` header. Returns
/// `None` if the header is missing or doesn't start with `"Bearer "`.
fn extract_bearer_token(req: &Request) -> Option<String> {
    let value = req.headers().get(AUTHORIZATION)?.to_str().ok()?;
    let prefix = "Bearer ";
    if !value.starts_with(prefix) {
        return None;
    }
    Some(value[prefix.len()..].trim().to_string())
}

/// Convenience extractor for handler signatures that want the user id with
/// only one bound. Returns 401 when the middleware hasn't run yet.
pub fn user_id_from_request(req: &Request) -> Result<Uuid, ApiError> {
    req.extensions()
        .get::<AuthUserId>()
        .map(|a| a.0)
        .ok_or_else(|| ApiError::Unauthorized("missing auth context".into()))
}
