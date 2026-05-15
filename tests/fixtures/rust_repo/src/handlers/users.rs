//! `/users` CRUD axum handlers.

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde::Deserialize;
use uuid::Uuid;
use validator::Validate;

use crate::dto::user_dto::{
    CreateUserRequest, UpdateUserRequest, UserListResponse, UserResponse,
};
use crate::error::ApiError;
use crate::AppState;

/// Query parameters accepted by `GET /users`.
#[derive(Debug, Deserialize)]
pub struct PageParams {
    #[serde(default = "default_page")]
    pub page: u32,
    #[serde(default = "default_page_size")]
    pub page_size: u32,
}

fn default_page() -> u32 {
    1
}

fn default_page_size() -> u32 {
    20
}

/// `POST /users` — register a new user account. Returns 201 + the created
/// user on success, 409 when the email is already taken.
pub async fn create_user(
    State(state): State<AppState>,
    Json(body): Json<CreateUserRequest>,
) -> Result<(StatusCode, Json<UserResponse>), ApiError> {
    body.validate()
        .map_err(|e| ApiError::Validation(e.to_string()))?;
    let user = state.users.create_user(&body).await?;
    Ok((StatusCode::CREATED, Json(user.into())))
}

/// `GET /users/{id}` — fetch a user by primary key.
pub async fn get_user(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<UserResponse>, ApiError> {
    let user = state.users.get_user_by_id(id).await?;
    Ok(Json(user.into()))
}

/// `GET /users` — list users with page / page_size query params.
pub async fn list_users(
    State(state): State<AppState>,
    Query(params): Query<PageParams>,
) -> Result<Json<UserListResponse>, ApiError> {
    let (rows, total) = state.users.list_users(params.page, params.page_size).await?;
    let items = rows.into_iter().map(UserResponse::from).collect();
    Ok(Json(UserListResponse {
        items,
        total_count: total,
        page: params.page,
        page_size: params.page_size,
    }))
}

/// `PATCH /users/{id}` — partially update a user.
pub async fn update_user(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    Json(body): Json<UpdateUserRequest>,
) -> Result<Json<UserResponse>, ApiError> {
    body.validate()
        .map_err(|e| ApiError::Validation(e.to_string()))?;
    let user = state.users.update_user(id, &body).await?;
    Ok(Json(user.into()))
}

/// `DELETE /users/{id}` — remove a user. Returns 204 on success.
pub async fn delete_user(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<impl IntoResponse, ApiError> {
    state.users.delete_user(id).await?;
    Ok(StatusCode::NO_CONTENT)
}
