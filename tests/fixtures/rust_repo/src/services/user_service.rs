//! User account business logic — signup, lookup, update, delete.

use std::sync::Arc;

use uuid::Uuid;

use crate::dto::user_dto::{CreateUserRequest, UpdateUserRequest};
use crate::error::ApiError;
use crate::models::User;
use crate::repository::user_repository::UserRepository;
use crate::services::auth_service::AuthService;

/// Orchestrates the user lifecycle. Owns hashing-then-persisting in
/// [`UserService::create_user`] so handlers can't accidentally skip the hash
/// step.
pub struct UserService {
    repo: Arc<UserRepository>,
    auth: Arc<AuthService>,
}

impl UserService {
    /// Construct a `UserService` wired to its dependencies.
    pub fn new(repo: Arc<UserRepository>, auth: Arc<AuthService>) -> Self {
        Self { repo, auth }
    }

    /// Register a new user account. The password is argon2-hashed before
    /// hitting the database. Returns [`ApiError::Conflict`] on email
    /// collision.
    pub async fn create_user(&self, req: &CreateUserRequest) -> Result<User, ApiError> {
        if self.repo.find_by_email(&req.email).await.is_ok() {
            return Err(ApiError::Conflict("email already taken".into()));
        }
        let hash = self.auth.hash_password(&req.password)?;
        let user = User::new(Uuid::new_v4(), req.email.clone(), req.username.clone(), hash);
        self.repo.insert(&user).await?;
        Ok(user)
    }

    /// Fetch a user by primary key.
    pub async fn get_user_by_id(&self, id: Uuid) -> Result<User, ApiError> {
        Ok(self.repo.find_by_id(id).await?)
    }

    /// Fetch a user by email address.
    pub async fn get_user_by_email(&self, email: &str) -> Result<User, ApiError> {
        Ok(self.repo.find_by_email(email).await?)
    }

    /// Return a paginated slice of users along with the total count for
    /// page-meta. Clamps `page` to `>= 1` and `page_size` to `[1, 100]`.
    pub async fn list_users(
        &self,
        page: u32,
        page_size: u32,
    ) -> Result<(Vec<User>, i64), ApiError> {
        let page = page.max(1);
        let page_size = page_size.clamp(1, 100);
        let offset = ((page - 1) * page_size) as i64;
        let rows = self.repo.list(offset, page_size as i64).await?;
        let total = self.repo.count().await?;
        Ok((rows, total))
    }

    /// Apply a patch to an existing user record. Any `None` field on the
    /// request is left untouched.
    pub async fn update_user(
        &self,
        id: Uuid,
        patch: &UpdateUserRequest,
    ) -> Result<User, ApiError> {
        let mut current = self.repo.find_by_id(id).await?;
        if let Some(email) = patch.email.as_ref() {
            current.email = email.clone();
        }
        if let Some(username) = patch.username.as_ref() {
            current.username = username.clone();
        }
        if let Some(password) = patch.password.as_ref() {
            current.password_hash = self.auth.hash_password(password)?;
        }
        self.repo.update(&current).await?;
        Ok(current)
    }

    /// Remove a user by id.
    pub async fn delete_user(&self, id: Uuid) -> Result<(), ApiError> {
        Ok(self.repo.delete(id).await?)
    }
}
