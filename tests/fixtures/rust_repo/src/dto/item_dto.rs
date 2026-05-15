//! Request / response types for `/items` endpoints.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use validator::Validate;

/// JSON body for `POST /items`. `description` is optional and defaults to
/// the empty string when omitted.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct CreateItemRequest {
    #[validate(length(min = 1, max = 200))]
    pub title: String,
    #[serde(default)]
    pub description: String,
}

/// JSON body for `PATCH /items/{id}` — both fields optional.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct UpdateItemRequest {
    #[validate(length(min = 1, max = 200))]
    pub title: Option<String>,
    pub description: Option<String>,
}

/// Public-facing item shape returned by every read endpoint.
#[derive(Debug, Clone, Serialize)]
pub struct ItemResponse {
    pub id: Uuid,
    pub owner_id: Uuid,
    pub title: String,
    pub description: String,
    pub created_at: DateTime<Utc>,
}

/// Paginated wrapper used by `GET /items`.
#[derive(Debug, Clone, Serialize)]
pub struct ItemListResponse {
    pub items: Vec<ItemResponse>,
    pub total_count: i64,
    pub page: u32,
    pub page_size: u32,
}

impl From<crate::models::Item> for ItemResponse {
    fn from(i: crate::models::Item) -> Self {
        ItemResponse {
            id: i.id,
            owner_id: i.owner_id,
            title: i.title,
            description: i.description,
            created_at: i.created_at,
        }
    }
}
