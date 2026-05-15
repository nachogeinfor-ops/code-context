//! `User` aggregate — represents a row in the `users` table.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Persistent representation of a user account.
///
/// `password_hash` carries the argon2 PHC string and must NEVER be serialised
/// to clients — see `crate::dto::user_dto::UserResponse` for the public shape.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    pub username: String,
    pub password_hash: String,
    pub created_at: DateTime<Utc>,
}

impl User {
    /// Construct a fresh `User` with `created_at = now()`.
    pub fn new(id: Uuid, email: String, username: String, password_hash: String) -> Self {
        Self {
            id,
            email,
            username,
            password_hash,
            created_at: Utc::now(),
        }
    }

    /// True when the supplied email matches this user (case-insensitive).
    pub fn has_email(&self, email: &str) -> bool {
        self.email.eq_ignore_ascii_case(email)
    }
}
