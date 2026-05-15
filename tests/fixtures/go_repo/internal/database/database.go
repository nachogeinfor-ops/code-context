// Package database wires the sqlx connection used by every repository and
// applies the minimal schema migrations the API depends on.
package database

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
	_ "github.com/mattn/go-sqlite3" // sqlite driver

	"github.com/example/goapi/internal/config"
)

// Open dials the configured database and runs the schema migrations.
func Open(cfg *config.Config) (*sqlx.DB, error) {
	driver, dsn, err := parseDatabaseURL(cfg.DatabaseURL)
	if err != nil {
		return nil, err
	}

	db, err := sqlx.Connect(driver, dsn)
	if err != nil {
		return nil, fmt.Errorf("connect %s: %w", driver, err)
	}
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("ping: %w", err)
	}

	if err := migrate(ctx, db); err != nil {
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return db, nil
}

// parseDatabaseURL splits a DSN like "sqlite://./goapi.db" into a sql driver
// name and a connection string the driver understands.
func parseDatabaseURL(url string) (driver, dsn string, err error) {
	idx := strings.Index(url, "://")
	if idx < 0 {
		return "", "", fmt.Errorf("invalid DATABASE_URL: %q", url)
	}
	scheme := url[:idx]
	rest := url[idx+3:]
	switch scheme {
	case "sqlite", "sqlite3":
		return "sqlite3", rest, nil
	case "postgres", "postgresql":
		return "postgres", url, nil
	default:
		return "", "", fmt.Errorf("unsupported DATABASE_URL scheme: %q", scheme)
	}
}

// migrate applies the minimum schema required for users + items + tokens.
func migrate(ctx context.Context, db *sqlx.DB) error {
	stmts := []string{
		`CREATE TABLE IF NOT EXISTS users (
			id TEXT PRIMARY KEY,
			email TEXT UNIQUE NOT NULL,
			username TEXT UNIQUE NOT NULL,
			password_hash TEXT NOT NULL,
			created_at DATETIME DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE TABLE IF NOT EXISTS items (
			id TEXT PRIMARY KEY,
			owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			title TEXT NOT NULL,
			description TEXT,
			created_at DATETIME DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE INDEX IF NOT EXISTS idx_items_owner ON items(owner_id)`,
	}
	for _, stmt := range stmts {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			return err
		}
	}
	return nil
}
