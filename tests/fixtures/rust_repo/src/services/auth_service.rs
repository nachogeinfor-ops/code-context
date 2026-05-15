//! Argon2 password hashing + JWT issuance / verification.
//!
//! Mirrors the Go fixture's `auth_service.go`. Every fallible method returns
//! [`ApiError`] so callers can `?` directly inside handlers.

use std::sync::Arc;

use argon2::password_hash::{rand_core::OsRng, PasswordHasher, PasswordVerifier, SaltString};
use argon2::{Argon2, PasswordHash};
use chrono::{Duration, Utc};
use jsonwebtoken::{decode, encode, DecodingKey, EncodingKey, Header, Validation};
use uuid::Uuid;

use crate::config::Config;
use crate::dto::auth_dto::{Claims, TokenPair, TokenType};
use crate::error::ApiError;

/// Bundles password hashing and JWT issuance / verification.
pub struct AuthService {
    cfg: Arc<Config>,
}

impl AuthService {
    /// Construct an `AuthService` bound to the supplied config.
    pub fn new(cfg: Arc<Config>) -> Self {
        Self { cfg }
    }

    /// Hash a plaintext password with argon2id using a random salt.
    /// Returns the PHC-encoded string ready to persist.
    pub fn hash_password(&self, plain: &str) -> Result<String, ApiError> {
        let salt = SaltString::generate(&mut OsRng);
        let argon = Argon2::default();
        let phc = argon
            .hash_password(plain.as_bytes(), &salt)
            .map_err(|e| ApiError::Internal(anyhow::anyhow!("argon2 hash: {e}")))?
            .to_string();
        Ok(phc)
    }

    /// Verify a candidate plaintext password against a stored argon2 PHC
    /// string. Returns `true` only on an exact match.
    pub fn verify_password(&self, plain: &str, stored: &str) -> bool {
        let parsed = match PasswordHash::new(stored) {
            Ok(p) => p,
            Err(_) => return false,
        };
        Argon2::default()
            .verify_password(plain.as_bytes(), &parsed)
            .is_ok()
    }

    /// Mint a short-lived JWT identifying the given user.
    pub fn issue_access_token(&self, user_id: Uuid) -> Result<String, ApiError> {
        self.sign_token(user_id, TokenType::Access, self.cfg.jwt_access_expires.as_secs() as i64)
    }

    /// Mint a long-lived JWT used to obtain new access tokens.
    pub fn issue_refresh_token(&self, user_id: Uuid) -> Result<String, ApiError> {
        self.sign_token(
            user_id,
            TokenType::Refresh,
            self.cfg.jwt_refresh_expires.as_secs() as i64,
        )
    }

    /// Mint both an access and a refresh token for the user and return them
    /// wrapped in a [`TokenPair`] suitable for the wire.
    pub fn issue_token_pair(&self, user_id: Uuid) -> Result<TokenPair, ApiError> {
        let access = self.issue_access_token(user_id)?;
        let refresh = self.issue_refresh_token(user_id)?;
        Ok(TokenPair {
            access_token: access,
            refresh_token: refresh,
            expires_in: self.cfg.jwt_access_expires.as_secs(),
            token_type: "Bearer",
        })
    }

    /// Parse and verify a raw JWT, returning its [`Claims`] payload. Fails
    /// with [`ApiError::Unauthorized`] when the token is malformed, expired,
    /// or signed with the wrong key.
    pub fn validate_token(&self, raw: &str, expected: TokenType) -> Result<Claims, ApiError> {
        let key = DecodingKey::from_secret(self.cfg.jwt_secret.as_bytes());
        let mut validation = Validation::default();
        validation.leeway = 5;
        let data = decode::<Claims>(raw, &key, &validation)
            .map_err(|e| ApiError::Unauthorized(format!("invalid token: {e}")))?;
        if data.claims.typ != expected {
            return Err(ApiError::Unauthorized(format!(
                "expected {:?} token, got {:?}",
                expected, data.claims.typ
            )));
        }
        Ok(data.claims)
    }

    /// Low-level helper used by `issue_access_token` / `issue_refresh_token`.
    fn sign_token(
        &self,
        user_id: Uuid,
        typ: TokenType,
        ttl_seconds: i64,
    ) -> Result<String, ApiError> {
        let now = Utc::now();
        let claims = Claims {
            sub: user_id,
            iat: now.timestamp(),
            exp: (now + Duration::seconds(ttl_seconds)).timestamp(),
            typ,
        };
        let key = EncodingKey::from_secret(self.cfg.jwt_secret.as_bytes());
        encode(&Header::default(), &claims, &key)
            .map_err(|e| ApiError::Internal(anyhow::anyhow!("sign jwt: {e}")))
    }
}
