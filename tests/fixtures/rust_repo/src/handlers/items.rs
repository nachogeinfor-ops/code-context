//! `/items` CRUD axum handlers. Every item endpoint reads the authenticated
//! user id out of request extensions (placed there by the JWT middleware)
//! and passes it through to the service layer for ownership checks.

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Extension;
use axum::Json;
use uuid::Uuid;
use validator::Validate;

use crate::dto::item_dto::{
    CreateItemRequest, ItemListResponse, ItemResponse, UpdateItemRequest,
};
use crate::error::ApiError;
use crate::handlers::users::PageParams;
use crate::middleware::auth::AuthUserId;
use crate::AppState;

/// `POST /items` — create a new item owned by the authenticated user.
pub async fn create_item(
    State(state): State<AppState>,
    Extension(AuthUserId(user_id)): Extension<AuthUserId>,
    Json(body): Json<CreateItemRequest>,
) -> Result<(StatusCode, Json<ItemResponse>), ApiError> {
    body.validate()
        .map_err(|e| ApiError::Validation(e.to_string()))?;
    let item = state.items.create_item(user_id, &body).await?;
    Ok((StatusCode::CREATED, Json(item.into())))
}

/// `GET /items/{id}` — fetch a single item, asserting the caller owns it.
pub async fn get_item(
    State(state): State<AppState>,
    Extension(AuthUserId(user_id)): Extension<AuthUserId>,
    Path(id): Path<Uuid>,
) -> Result<Json<ItemResponse>, ApiError> {
    let item = state.items.get_item(id, user_id).await?;
    Ok(Json(item.into()))
}

/// `GET /items` — list items owned by the authenticated user, with
/// page/page_size query params for pagination.
pub async fn list_items(
    State(state): State<AppState>,
    Extension(AuthUserId(user_id)): Extension<AuthUserId>,
    Query(params): Query<PageParams>,
) -> Result<Json<ItemListResponse>, ApiError> {
    let (rows, total) = state
        .items
        .list_items_by_owner(user_id, params.page, params.page_size)
        .await?;
    let items = rows.into_iter().map(ItemResponse::from).collect();
    Ok(Json(ItemListResponse {
        items,
        total_count: total,
        page: params.page,
        page_size: params.page_size,
    }))
}

/// `PATCH /items/{id}` — partially update an item the caller owns.
pub async fn update_item(
    State(state): State<AppState>,
    Extension(AuthUserId(user_id)): Extension<AuthUserId>,
    Path(id): Path<Uuid>,
    Json(body): Json<UpdateItemRequest>,
) -> Result<Json<ItemResponse>, ApiError> {
    body.validate()
        .map_err(|e| ApiError::Validation(e.to_string()))?;
    let item = state.items.update_item(id, user_id, &body).await?;
    Ok(Json(item.into()))
}

/// `DELETE /items/{id}` — delete an item the caller owns.
pub async fn delete_item(
    State(state): State<AppState>,
    Extension(AuthUserId(user_id)): Extension<AuthUserId>,
    Path(id): Path<Uuid>,
) -> Result<impl IntoResponse, ApiError> {
    state.items.delete_item(id, user_id).await?;
    Ok(StatusCode::NO_CONTENT)
}
