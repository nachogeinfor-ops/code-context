// Package repository — sqlx-backed persistence for items.
package repository

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/jmoiron/sqlx"

	"github.com/example/goapi/internal/models"
)

// ErrItemNotFound is returned when no item row matches the supplied id.
var ErrItemNotFound = errors.New("item not found")

// ItemRepository persists Item aggregates via sqlx.
type ItemRepository struct {
	db *sqlx.DB
}

// NewItemRepository constructs an ItemRepository bound to the given DB.
func NewItemRepository(db *sqlx.DB) *ItemRepository {
	return &ItemRepository{db: db}
}

// Insert saves a new item row.
func (r *ItemRepository) Insert(ctx context.Context, item *models.Item) error {
	const query = `
		INSERT INTO items (id, owner_id, title, description, created_at)
		VALUES (:id, :owner_id, :title, :description, :created_at)
	`
	if _, err := r.db.NamedExecContext(ctx, query, item); err != nil {
		return fmt.Errorf("insert item: %w", err)
	}
	return nil
}

// FindByID looks up an item by primary key.
func (r *ItemRepository) FindByID(ctx context.Context, id string) (*models.Item, error) {
	var item models.Item
	const query = `SELECT * FROM items WHERE id = $1`
	if err := r.db.GetContext(ctx, &item, query, id); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrItemNotFound
		}
		return nil, fmt.Errorf("find item by id: %w", err)
	}
	return &item, nil
}

// ListByOwner returns a page of items owned by the given user id.
func (r *ItemRepository) ListByOwner(ctx context.Context, ownerID string, offset, limit int) ([]models.Item, error) {
	var rows []models.Item
	const query = `
		SELECT * FROM items
		WHERE owner_id = $1
		ORDER BY created_at DESC
		LIMIT $2 OFFSET $3
	`
	if err := r.db.SelectContext(ctx, &rows, query, ownerID, limit, offset); err != nil {
		return nil, fmt.Errorf("list items by owner: %w", err)
	}
	return rows, nil
}

// Update applies title/description changes to the item with the given id.
func (r *ItemRepository) Update(ctx context.Context, id string, patch *models.Item) error {
	const query = `
		UPDATE items
		SET title = :title, description = :description
		WHERE id = :id
	`
	patch.ID = id
	res, err := r.db.NamedExecContext(ctx, query, patch)
	if err != nil {
		return fmt.Errorf("update item: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return ErrItemNotFound
	}
	return nil
}

// Delete removes an item by id.
func (r *ItemRepository) Delete(ctx context.Context, id string) error {
	const query = `DELETE FROM items WHERE id = $1`
	res, err := r.db.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("delete item: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return ErrItemNotFound
	}
	return nil
}

// CountByOwner returns the number of items owned by the given user.
func (r *ItemRepository) CountByOwner(ctx context.Context, ownerID string) (int, error) {
	var n int
	const query = `SELECT COUNT(*) FROM items WHERE owner_id = $1`
	if err := r.db.GetContext(ctx, &n, query, ownerID); err != nil {
		return 0, fmt.Errorf("count items by owner: %w", err)
	}
	return n, nil
}
