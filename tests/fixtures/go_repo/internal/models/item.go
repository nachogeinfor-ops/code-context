// Package models contains domain structs persisted by the repository layer.
package models

import "time"

// Item is the canonical item record stored in the `items` table.
// Each item has exactly one owner (a User).
type Item struct {
	ID          string    `db:"id" json:"id"`
	OwnerID     string    `db:"owner_id" json:"owner_id"`
	Title       string    `db:"title" json:"title"`
	Description string    `db:"description" json:"description"`
	CreatedAt   time.Time `db:"created_at" json:"created_at"`
}

// NewItem allocates an Item with the given owner and current timestamp.
func NewItem(id, ownerID, title, description string) *Item {
	return &Item{
		ID:          id,
		OwnerID:     ownerID,
		Title:       title,
		Description: description,
		CreatedAt:   time.Now().UTC(),
	}
}

// IsOwnedBy reports whether the item belongs to the given user id.
func (i *Item) IsOwnedBy(userID string) bool {
	return i != nil && i.OwnerID == userID
}
