//! Domain model structs. These map 1:1 to database rows via
//! [`sqlx::FromRow`] and are the persistence-layer's currency. DTOs in
//! `crate::dto` are intentionally separate so that internal renames don't
//! ripple to the wire format.

pub mod item;
pub mod user;

pub use item::Item;
pub use user::User;
