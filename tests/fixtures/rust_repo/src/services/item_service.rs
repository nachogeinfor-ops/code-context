//! Item business logic — every item belongs to exactly one owner; methods
//! that read or write enforce that invariant before touching the repo.

use std::sync::Arc;

use uuid::Uuid;

use crate::dto::item_dto::{CreateItemRequest, UpdateItemRequest};
use crate::error::ApiError;
use crate::models::Item;
use crate::repository::item_repository::ItemRepository;

/// Orchestrates item creation, lookup, and ownership-checked mutations.
pub struct ItemService {
    repo: Arc<ItemRepository>,
}

impl ItemService {
    /// Construct an `ItemService` wired to its repository.
    pub fn new(repo: Arc<ItemRepository>) -> Self {
        Self { repo }
    }

    /// Create a new item owned by `owner_id`.
    pub async fn create_item(
        &self,
        owner_id: Uuid,
        req: &CreateItemRequest,
    ) -> Result<Item, ApiError> {
        let item = Item::new(
            Uuid::new_v4(),
            owner_id,
            req.title.clone(),
            req.description.clone(),
        );
        self.repo.insert(&item).await?;
        Ok(item)
    }

    /// Fetch an item by id, asserting that the caller owns it. Returns
    /// [`ApiError::Forbidden`] when the caller is not the owner — that's
    /// preferred over leaking existence via 404 vs 403 differentiation.
    pub async fn get_item(&self, id: Uuid, caller: Uuid) -> Result<Item, ApiError> {
        let item = self.repo.find_by_id(id).await?;
        if !item.is_owned_by(caller) {
            return Err(ApiError::Forbidden);
        }
        Ok(item)
    }

    /// Return a paginated slice of items belonging to the supplied owner.
    pub async fn list_items_by_owner(
        &self,
        owner_id: Uuid,
        page: u32,
        page_size: u32,
    ) -> Result<(Vec<Item>, i64), ApiError> {
        let page = page.max(1);
        let page_size = page_size.clamp(1, 100);
        let offset = ((page - 1) * page_size) as i64;
        let rows = self
            .repo
            .list_by_owner(owner_id, offset, page_size as i64)
            .await?;
        let total = self.repo.count_by_owner(owner_id).await?;
        Ok((rows, total))
    }

    /// Apply a patch to an item, verifying ownership first.
    pub async fn update_item(
        &self,
        id: Uuid,
        caller: Uuid,
        patch: &UpdateItemRequest,
    ) -> Result<Item, ApiError> {
        let mut item = self.repo.find_by_id(id).await?;
        if !item.is_owned_by(caller) {
            return Err(ApiError::Forbidden);
        }
        if let Some(title) = patch.title.as_ref() {
            item.title = title.clone();
        }
        if let Some(desc) = patch.description.as_ref() {
            item.description = desc.clone();
        }
        self.repo.update(&item).await?;
        Ok(item)
    }

    /// Delete an item after verifying ownership.
    pub async fn delete_item(&self, id: Uuid, caller: Uuid) -> Result<(), ApiError> {
        let item = self.repo.find_by_id(id).await?;
        if !item.is_owned_by(caller) {
            return Err(ApiError::Forbidden);
        }
        self.repo.delete(id).await?;
        Ok(())
    }
}
