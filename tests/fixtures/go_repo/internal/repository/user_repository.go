// Package repository contains sqlx-backed persistence for users and items.
//
// Repositories are constructor-injected with a *sqlx.DB. All exported methods
// take context.Context as the first argument and return wrapped sql errors so
// callers can disambiguate "not found" via errors.Is(err, sql.ErrNoRows).
package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/jmoiron/sqlx"

	"github.com/example/goapi/internal/models"
)

// ErrUserNotFound is returned when no row matches the supplied identifier.
var ErrUserNotFound = errors.New("user not found")

// UserRepository persists User aggregates via sqlx.
type UserRepository struct {
	db *sqlx.DB
}

// NewUserRepository constructs a UserRepository bound to the given DB.
func NewUserRepository(db *sqlx.DB) *UserRepository {
	return &UserRepository{db: db}
}

// Insert saves a new user row. Returns the saved user (with timestamps).
func (r *UserRepository) Insert(ctx context.Context, u *models.User) error {
	const query = `
		INSERT INTO users (id, email, username, password_hash, created_at)
		VALUES (:id, :email, :username, :password_hash, :created_at)
	`
	if _, err := r.db.NamedExecContext(ctx, query, u); err != nil {
		return fmt.Errorf("insert user: %w", err)
	}
	return nil
}

// FindByID looks up a user by primary key.
func (r *UserRepository) FindByID(ctx context.Context, id string) (*models.User, error) {
	var u models.User
	const query = `SELECT * FROM users WHERE id = $1`
	if err := r.db.GetContext(ctx, &u, query, id); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrUserNotFound
		}
		return nil, fmt.Errorf("find user by id: %w", err)
	}
	return &u, nil
}

// FindByEmail looks up a user by their unique email address.
func (r *UserRepository) FindByEmail(ctx context.Context, email string) (*models.User, error) {
	var u models.User
	const query = `SELECT * FROM users WHERE email = $1`
	if err := r.db.GetContext(ctx, &u, query, email); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrUserNotFound
		}
		return nil, fmt.Errorf("find user by email: %w", err)
	}
	return &u, nil
}

// List returns a page of users with offset/limit pagination.
func (r *UserRepository) List(ctx context.Context, offset, limit int) ([]models.User, error) {
	var rows []models.User
	const query = `SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2`
	if err := r.db.SelectContext(ctx, &rows, query, limit, offset); err != nil {
		return nil, fmt.Errorf("list users: %w", err)
	}
	return rows, nil
}

// Update applies the non-zero fields of `patch` to the user with the given id.
func (r *UserRepository) Update(ctx context.Context, id string, patch *models.User) error {
	const query = `
		UPDATE users
		SET email = :email, username = :username, password_hash = :password_hash
		WHERE id = :id
	`
	patch.ID = id
	res, err := r.db.NamedExecContext(ctx, query, patch)
	if err != nil {
		return fmt.Errorf("update user: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return ErrUserNotFound
	}
	return nil
}

// Delete removes a user by id.
func (r *UserRepository) Delete(ctx context.Context, id string) error {
	const query = `DELETE FROM users WHERE id = $1`
	res, err := r.db.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("delete user: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return ErrUserNotFound
	}
	return nil
}

// Count returns the total number of users in the table.
func (r *UserRepository) Count(ctx context.Context) (int, error) {
	var n int
	if err := r.db.GetContext(ctx, &n, `SELECT COUNT(*) FROM users`); err != nil {
		return 0, fmt.Errorf("count users: %w", err)
	}
	return n, nil
}
