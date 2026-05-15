//! Structured request logging layer built on `tower_http::trace::TraceLayer`.
//!
//! Emits one `tracing` event per request with method, path, status code,
//! and elapsed duration. The `RUSTAPI_LOG_LEVEL` env var controls the
//! threshold via `tracing_subscriber`'s `EnvFilter`.

use std::time::Duration;

use axum::body::Body;
use axum::extract::Request;
use axum::http::Response;
use tower_http::classify::{ServerErrorsAsFailures, SharedClassifier};
use tower_http::trace::{DefaultMakeSpan, DefaultOnRequest, TraceLayer};
use tracing::Level;

/// Build the `TraceLayer` wired with our preferred span / event format.
///
/// Mounted at the top of the Router so it sees every request regardless of
/// auth status.
pub fn request_log_layer() -> TraceLayer<SharedClassifier<ServerErrorsAsFailures>> {
    TraceLayer::new_for_http()
        .make_span_with(
            DefaultMakeSpan::new()
                .level(Level::INFO)
                .include_headers(false),
        )
        .on_request(DefaultOnRequest::new().level(Level::INFO))
        .on_response(on_response)
}

/// Per-response callback. Emits `request.completed` with the method, path,
/// status, and latency in millis.
fn on_response(response: &Response<Body>, latency: Duration, _span: &tracing::Span) {
    tracing::info!(
        status = response.status().as_u16(),
        latency_ms = latency.as_millis() as u64,
        "request completed",
    );
}

/// Optional helper: render a single line per request for stdout-only setups.
/// Mirrors the Go fixture's `RequestLogger`.
pub fn render_access_log_line(req: &Request, status: u16, latency: Duration) -> String {
    format!(
        "{} {} -> {} in {}ms",
        req.method(),
        req.uri().path(),
        status,
        latency.as_millis()
    )
}
