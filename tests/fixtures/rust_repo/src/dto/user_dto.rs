//! Request / response types for `/users` endpoints.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use validator::Validate;

/// JSON body for `POST /users`. All fields are required.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct CreateUserRequest {
    #[validate(email)]
    pub email: String,
    #[validate(length(min = 3, max = 32))]
    pub username: String,
    #[validate(length(min = 8))]
    pub password: String,
}

/// JSON body for `PATCH /users/{id}`. Every field is optional; `None`
/// means "leave unchanged".
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct UpdateUserRequest {
    #[validate(email)]
    pub email: Option<String>,
    #[validate(length(min = 3, max = 32))]
    pub username: Option<String>,
    #[validate(length(min = 8))]
    pub password: Option<String>,
}

/// Public-facing user shape. Deliberately excludes `password_hash` so it can
/// never leak through this type.
#[derive(Debug, Clone, Serialize)]
pub struct UserResponse {
    pub id: Uuid,
    pub email: String,
    pub username: String,
    pub created_at: DateTime<Utc>,
}

/// Paginated wrapper used by `GET /users`.
#[derive(Debug, Clone, Serialize)]
pub struct UserListResponse {
    pub items: Vec<UserResponse>,
    pub total_count: i64,
    pub page: u32,
    pub page_size: u32,
}

impl From<crate::models::User> for UserResponse {
    fn from(u: crate::models::User) -> Self {
        UserResponse {
            id: u.id,
            email: u.email,
            username: u.username,
            created_at: u.created_at,
        }
    }
}
