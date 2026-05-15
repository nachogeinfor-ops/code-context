//! sqlx-backed persistence for the `users` and `items` aggregates.
//!
//! Repositories are constructor-injected with a `PgPool` and expose async
//! methods that return `Result<T, sqlx::Error>`. The `ApiError` layer
//! upstream rewrites `RowNotFound` into a 404 automatically.

pub mod item_repository;
pub mod user_repository;

pub use item_repository::ItemRepository;
pub use user_repository::UserRepository;
