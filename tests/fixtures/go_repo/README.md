# go-repo fixture

This directory is an eval fixture for **code-context**. It is a small, tutorial-grade Go HTTP API
(chi router, JWT auth, bcrypt hashing, sqlx persistence) mirroring the same `users` / `items` /
`auth` resources used by `python_repo` and `ts_repo`.

It is not a working application: dependencies are not vendored and the code is not expected to
compile or pass `go build`. It exists solely as a realistic Go codebase target for semantic search
evaluation.

Layout follows the standard Go project layout:

- `cmd/server/` — entry point (`main.go`)
- `internal/config/` — environment-driven configuration loader
- `internal/database/` — sqlx connection wiring and migrations
- `internal/models/` — domain structs (User, Item)
- `internal/types/` — request/response DTOs and JWT claim types
- `internal/handlers/` — chi HTTP handlers (CRUD for users/items, login/refresh for auth)
- `internal/services/` — business logic (token signing, password hashing, user creation)
- `internal/repository/` — sqlx persistence layer (named queries, parameterised)
- `internal/middleware/` — auth middleware (Bearer JWT verification), request logging
- `tests/` — table-driven `_test.go` files for auth, users, items
