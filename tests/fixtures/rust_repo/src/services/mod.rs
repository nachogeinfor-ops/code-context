//! Business logic that sits between handlers and repositories.
//!
//! Services own JWT signing/verification, argon2 password hashing, and
//! composite operations like user signup. Handlers should never touch
//! repositories directly — go through a service.

pub mod auth_service;
pub mod item_service;
pub mod user_service;

pub use auth_service::AuthService;
pub use item_service::ItemService;
pub use user_service::UserService;
