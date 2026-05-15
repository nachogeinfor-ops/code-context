//! `Item` aggregate — represents a row in the `items` table.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Persistent representation of a user-owned item.
///
/// An item belongs to exactly one owner via [`Item::owner_id`]; deletes
/// cascade from the owning user.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Item {
    pub id: Uuid,
    pub owner_id: Uuid,
    pub title: String,
    pub description: String,
    pub created_at: DateTime<Utc>,
}

impl Item {
    /// Construct a fresh `Item` owned by the given user.
    pub fn new(id: Uuid, owner_id: Uuid, title: String, description: String) -> Self {
        Self {
            id,
            owner_id,
            title,
            description,
            created_at: Utc::now(),
        }
    }

    /// True when the supplied user id owns this item.
    pub fn is_owned_by(&self, user_id: Uuid) -> bool {
        self.owner_id == user_id
    }
}
