//! `/auth/login` and `/auth/refresh` axum handlers.

use axum::extract::State;
use axum::Json;
use validator::Validate;

use crate::dto::auth_dto::{LoginRequest, RefreshRequest, TokenPair, TokenType};
use crate::error::ApiError;
use crate::AppState;

/// `POST /auth/login` — authenticate an email/password pair and return a
/// fresh access/refresh token pair. Responds 401 on bad credentials.
pub async fn login(
    State(state): State<AppState>,
    Json(body): Json<LoginRequest>,
) -> Result<Json<TokenPair>, ApiError> {
    body.validate()
        .map_err(|e| ApiError::Validation(e.to_string()))?;
    let user = state
        .users
        .get_user_by_email(&body.email)
        .await
        .map_err(|_| ApiError::Unauthorized("invalid credentials".into()))?;
    if !state.auth.verify_password(&body.password, &user.password_hash) {
        return Err(ApiError::Unauthorized("invalid credentials".into()));
    }
    let pair = state.auth.issue_token_pair(user.id)?;
    Ok(Json(pair))
}

/// `POST /auth/refresh` — exchange a valid refresh token for a new pair.
pub async fn refresh(
    State(state): State<AppState>,
    Json(body): Json<RefreshRequest>,
) -> Result<Json<TokenPair>, ApiError> {
    let claims = state
        .auth
        .validate_token(&body.refresh_token, TokenType::Refresh)?;
    let pair = state.auth.issue_token_pair(claims.sub)?;
    Ok(Json(pair))
}
