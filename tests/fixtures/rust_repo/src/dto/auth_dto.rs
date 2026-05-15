//! Request / response types for `/auth/login` and `/auth/refresh`.

use serde::{Deserialize, Serialize};
use uuid::Uuid;
use validator::Validate;

/// JSON body for `POST /auth/login`.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct LoginRequest {
    #[validate(email)]
    pub email: String,
    #[validate(length(min = 8))]
    pub password: String,
}

/// JSON body for `POST /auth/refresh`.
#[derive(Debug, Clone, Deserialize)]
pub struct RefreshRequest {
    pub refresh_token: String,
}

/// JSON response envelope returned by both `/auth/login` and `/auth/refresh`.
///
/// `expires_in` is reported in seconds and tracks `access_token` (not the
/// refresh token, which lives much longer).
#[derive(Debug, Clone, Serialize)]
pub struct TokenPair {
    pub access_token: String,
    pub refresh_token: String,
    pub expires_in: u64,
    pub token_type: &'static str,
}

/// Discriminator for what kind of JWT we're minting. Embedded as the `typ`
/// claim so a refresh token can't accidentally be presented as an access
/// token (or vice versa).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TokenType {
    Access,
    Refresh,
}

/// Claims payload signed inside every JWT we issue.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claims {
    pub sub: Uuid,
    pub iat: i64,
    pub exp: i64,
    pub typ: TokenType,
}
