//! Server configuration loaded from environment variables.
//!
//! Uses `envy` to map `RUSTAPI_*` env vars onto the [`Config`] struct, with
//! `dotenvy` providing a `.env` shim during development. Validation is
//! performed in [`Config::validate`] and surfaced as a [`ConfigError`].

use std::time::Duration;

use serde::Deserialize;
use thiserror::Error;

/// Top-level configuration carried in [`AppState::config`].
///
/// Field names map to env vars prefixed with `RUSTAPI_`, e.g. `JWTSecret`
/// becomes `RUSTAPI_JWT_SECRET`.
#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    #[serde(default = "default_port")]
    pub port: u16,
    pub database_url: String,
    pub jwt_secret: String,
    #[serde(default = "default_access_expires", with = "humantime_serde")]
    pub jwt_access_expires: Duration,
    #[serde(default = "default_refresh_expires", with = "humantime_serde")]
    pub jwt_refresh_expires: Duration,
    #[serde(default = "default_argon2_memory")]
    pub argon2_memory_kb: u32,
    #[serde(default = "default_log_level")]
    pub log_level: String,
}

/// Errors that may be returned by [`Config::from_env`].
#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("envy: {0}")]
    Envy(#[from] envy::Error),
    #[error("dotenv: {0}")]
    Dotenv(#[from] dotenvy::Error),
    #[error("config validation: {0}")]
    Invalid(String),
}

impl Config {
    /// Read `RUSTAPI_*` variables from the process environment (and `.env`)
    /// and return a fully validated [`Config`].
    pub fn from_env() -> Result<Self, ConfigError> {
        let _ = dotenvy::dotenv();
        let cfg: Config = envy::prefixed("RUSTAPI_").from_env()?;
        cfg.validate()?;
        Ok(cfg)
    }

    /// Enforce invariants that the deserialiser cannot express on its own.
    fn validate(&self) -> Result<(), ConfigError> {
        if self.jwt_secret.len() < 16 {
            return Err(ConfigError::Invalid(
                "RUSTAPI_JWT_SECRET must be at least 16 characters".into(),
            ));
        }
        if self.argon2_memory_kb < 8 * 1024 {
            return Err(ConfigError::Invalid(
                "RUSTAPI_ARGON2_MEMORY_KB must be >= 8192 (8 MiB)".into(),
            ));
        }
        Ok(())
    }
}

fn default_port() -> u16 {
    8080
}

fn default_access_expires() -> Duration {
    Duration::from_secs(15 * 60)
}

fn default_refresh_expires() -> Duration {
    Duration::from_secs(7 * 24 * 60 * 60)
}

fn default_argon2_memory() -> u32 {
    19 * 1024
}

fn default_log_level() -> String {
    "info".into()
}

/// Tiny stand-in for the `humantime_serde` crate so the file compiles in
/// isolation. Parses strings like `"15m"` or `"168h"` into a `Duration`.
mod humantime_serde {
    use std::time::Duration;

    use serde::de::Error as _;
    use serde::{Deserialize, Deserializer};

    pub fn deserialize<'de, D>(d: D) -> Result<Duration, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(d)?;
        parse(&raw).ok_or_else(|| D::Error::custom(format!("invalid duration: {raw}")))
    }

    fn parse(raw: &str) -> Option<Duration> {
        let (n, unit) = raw.split_at(raw.len().saturating_sub(1));
        let n: u64 = n.parse().ok()?;
        match unit {
            "s" => Some(Duration::from_secs(n)),
            "m" => Some(Duration::from_secs(n * 60)),
            "h" => Some(Duration::from_secs(n * 60 * 60)),
            "d" => Some(Duration::from_secs(n * 60 * 60 * 24)),
            _ => None,
        }
    }
}
