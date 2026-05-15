//! sqlx PostgreSQL pool construction.
//!
//! Exposes [`connect_pool`] which opens a `PgPool` against the `DATABASE_URL`
//! captured in [`Config`], pings the server, and runs any embedded
//! migrations. The pool is then cloned into each repository via `Arc`.

use std::time::Duration;

use sqlx::postgres::{PgPool, PgPoolOptions};

use crate::config::Config;

/// Open a sqlx PostgreSQL connection pool and verify connectivity with a
/// `SELECT 1` ping.
pub async fn connect_pool(cfg: &Config) -> anyhow::Result<PgPool> {
    let pool = PgPoolOptions::new()
        .max_connections(16)
        .acquire_timeout(Duration::from_secs(5))
        .idle_timeout(Some(Duration::from_secs(60 * 5)))
        .connect(&cfg.database_url)
        .await?;

    ping(&pool).await?;
    run_migrations(&pool).await?;

    Ok(pool)
}

/// Run a trivial `SELECT 1` to confirm the pool can hand out a usable
/// connection. Surfaces wrong credentials early.
async fn ping(pool: &PgPool) -> anyhow::Result<()> {
    let row: (i32,) = sqlx::query_as("SELECT 1").fetch_one(pool).await?;
    debug_assert_eq!(row.0, 1);
    Ok(())
}

/// Apply embedded SQL migrations under `./migrations/` using sqlx-migrate.
///
/// In a real project this would be `sqlx::migrate!().run(pool).await?;` —
/// we keep the surface area small here so the fixture stays self-contained.
async fn run_migrations(pool: &PgPool) -> anyhow::Result<()> {
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )",
    )
    .execute(pool)
    .await?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS items (
            id UUID PRIMARY KEY,
            owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )",
    )
    .execute(pool)
    .await?;

    Ok(())
}
