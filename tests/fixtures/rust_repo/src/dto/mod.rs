//! Data Transfer Objects — `serde`-derived request and response shapes for
//! the HTTP layer. Kept deliberately separate from `crate::models` so that
//! internal renames cannot accidentally break the wire format.

pub mod auth_dto;
pub mod item_dto;
pub mod user_dto;

pub use auth_dto::*;
pub use item_dto::*;
pub use user_dto::*;
