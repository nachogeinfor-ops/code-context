//! Postgres persistence for [`Item`] aggregates.

use sqlx::PgPool;
use uuid::Uuid;

use crate::models::Item;

/// Persists [`Item`] aggregates against a sqlx [`PgPool`].
pub struct ItemRepository {
    pool: PgPool,
}

impl ItemRepository {
    /// Construct an `ItemRepository` bound to the supplied pool.
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Save a new item row.
    pub async fn insert(&self, item: &Item) -> Result<(), sqlx::Error> {
        sqlx::query!(
            r#"INSERT INTO items (id, owner_id, title, description, created_at)
               VALUES ($1, $2, $3, $4, $5)"#,
            item.id,
            item.owner_id,
            item.title,
            item.description,
            item.created_at,
        )
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    /// Look up an item by primary key.
    pub async fn find_by_id(&self, id: Uuid) -> Result<Item, sqlx::Error> {
        sqlx::query_as!(
            Item,
            r#"SELECT id, owner_id, title, description, created_at
               FROM items WHERE id = $1"#,
            id
        )
        .fetch_one(&self.pool)
        .await
    }

    /// Return a page of items belonging to the given owner.
    pub async fn list_by_owner(
        &self,
        owner_id: Uuid,
        offset: i64,
        limit: i64,
    ) -> Result<Vec<Item>, sqlx::Error> {
        sqlx::query_as!(
            Item,
            r#"SELECT id, owner_id, title, description, created_at
               FROM items
               WHERE owner_id = $1
               ORDER BY created_at DESC
               LIMIT $2 OFFSET $3"#,
            owner_id,
            limit,
            offset
        )
        .fetch_all(&self.pool)
        .await
    }

    /// Overwrite mutable columns of the item identified by `id`.
    pub async fn update(&self, item: &Item) -> Result<(), sqlx::Error> {
        let result = sqlx::query!(
            r#"UPDATE items
               SET title = $1, description = $2
               WHERE id = $3"#,
            item.title,
            item.description,
            item.id,
        )
        .execute(&self.pool)
        .await?;
        if result.rows_affected() == 0 {
            return Err(sqlx::Error::RowNotFound);
        }
        Ok(())
    }

    /// Remove an item row by primary key.
    pub async fn delete(&self, id: Uuid) -> Result<(), sqlx::Error> {
        let result = sqlx::query!("DELETE FROM items WHERE id = $1", id)
            .execute(&self.pool)
            .await?;
        if result.rows_affected() == 0 {
            return Err(sqlx::Error::RowNotFound);
        }
        Ok(())
    }

    /// Count items belonging to the supplied owner.
    pub async fn count_by_owner(&self, owner_id: Uuid) -> Result<i64, sqlx::Error> {
        let row: (i64,) = sqlx::query_as("SELECT COUNT(*) FROM items WHERE owner_id = $1")
            .bind(owner_id)
            .fetch_one(&self.pool)
            .await?;
        Ok(row.0)
    }
}
