//! Postgres persistence for [`User`] aggregates.

use sqlx::PgPool;
use uuid::Uuid;

use crate::models::User;

/// Persists [`User`] aggregates against a sqlx [`PgPool`].
pub struct UserRepository {
    pool: PgPool,
}

impl UserRepository {
    /// Construct a `UserRepository` bound to the supplied pool.
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Save a new user row. Returns `Err(sqlx::Error::Database)` with a
    /// unique-violation code when the email is already taken.
    pub async fn insert(&self, user: &User) -> Result<(), sqlx::Error> {
        sqlx::query!(
            r#"INSERT INTO users (id, email, username, password_hash, created_at)
               VALUES ($1, $2, $3, $4, $5)"#,
            user.id,
            user.email,
            user.username,
            user.password_hash,
            user.created_at,
        )
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    /// Look up a user by primary key. Returns `RowNotFound` if absent.
    pub async fn find_by_id(&self, id: Uuid) -> Result<User, sqlx::Error> {
        sqlx::query_as!(
            User,
            r#"SELECT id, email, username, password_hash, created_at
               FROM users WHERE id = $1"#,
            id
        )
        .fetch_one(&self.pool)
        .await
    }

    /// Look up a user by their unique email address.
    pub async fn find_by_email(&self, email: &str) -> Result<User, sqlx::Error> {
        sqlx::query_as!(
            User,
            r#"SELECT id, email, username, password_hash, created_at
               FROM users WHERE email = $1"#,
            email
        )
        .fetch_one(&self.pool)
        .await
    }

    /// Return a page of users ordered by `created_at DESC`.
    pub async fn list(&self, offset: i64, limit: i64) -> Result<Vec<User>, sqlx::Error> {
        sqlx::query_as!(
            User,
            r#"SELECT id, email, username, password_hash, created_at
               FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2"#,
            limit,
            offset
        )
        .fetch_all(&self.pool)
        .await
    }

    /// Overwrite every mutable column of the user identified by `id`.
    pub async fn update(&self, user: &User) -> Result<(), sqlx::Error> {
        let result = sqlx::query!(
            r#"UPDATE users
               SET email = $1, username = $2, password_hash = $3
               WHERE id = $4"#,
            user.email,
            user.username,
            user.password_hash,
            user.id,
        )
        .execute(&self.pool)
        .await?;
        if result.rows_affected() == 0 {
            return Err(sqlx::Error::RowNotFound);
        }
        Ok(())
    }

    /// Remove a user row by primary key.
    pub async fn delete(&self, id: Uuid) -> Result<(), sqlx::Error> {
        let result = sqlx::query!("DELETE FROM users WHERE id = $1", id)
            .execute(&self.pool)
            .await?;
        if result.rows_affected() == 0 {
            return Err(sqlx::Error::RowNotFound);
        }
        Ok(())
    }

    /// Return the total number of users in the table.
    pub async fn count(&self) -> Result<i64, sqlx::Error> {
        let row: (i64,) = sqlx::query_as("SELECT COUNT(*) FROM users")
            .fetch_one(&self.pool)
            .await?;
        Ok(row.0)
    }
}
