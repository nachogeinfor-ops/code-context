# rustapi

A small, idiomatic axum HTTP API used as a fixture for the
[code-context](https://github.com/nachogeinfor-ops/code-context) eval suite.

The shape mirrors `tests/fixtures/python_repo`, `ts_repo`, and `go_repo` so we
can compare retrieval quality across languages with the same conceptual
queries (users, items, JWT auth, login/refresh, middleware).

## Layout

```
src/
  main.rs            - axum Router, tokio runtime, graceful shutdown
  config.rs          - envy/dotenvy env-var loader
  database.rs        - sqlx::PgPool connection setup
  error.rs           - ApiError enum + IntoResponse impl
  models/            - sqlx::FromRow domain structs
  dto/               - serde request/response types
  repository/        - sqlx queries (users + items)
  services/          - business logic (auth, users, items)
  handlers/          - axum endpoint functions
  middleware/        - tower layers (JWT auth, request logging)
tests/               - integration tests (HTTP-level smoke)
```

## Notes

This is a **fixture**, not a working binary. `cargo build` is not expected to
succeed — the code is shaped to look like a plausible axum + sqlx project so
that tree-sitter can chunk it and embeddings produce sensible search results.
