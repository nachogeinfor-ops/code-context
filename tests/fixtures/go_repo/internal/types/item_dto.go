// Package types — request/response shapes for /items endpoints.
package types

import "time"

// CreateItemRequest is the JSON body for POST /items.
type CreateItemRequest struct {
	Title       string `json:"title" validate:"required,min=1,max=200"`
	Description string `json:"description" validate:"max=2000"`
}

// UpdateItemRequest is the JSON body for PATCH /items/{id}. Optional fields.
type UpdateItemRequest struct {
	Title       *string `json:"title,omitempty" validate:"omitempty,min=1,max=200"`
	Description *string `json:"description,omitempty" validate:"omitempty,max=2000"`
}

// ItemResponse is the public, serialised shape of an Item.
type ItemResponse struct {
	ID          string    `json:"id"`
	OwnerID     string    `json:"owner_id"`
	Title       string    `json:"title"`
	Description string    `json:"description"`
	CreatedAt   time.Time `json:"created_at"`
}

// ItemListResponse wraps a page of items with pagination metadata.
type ItemListResponse struct {
	Items      []ItemResponse `json:"items"`
	TotalCount int            `json:"total_count"`
	Page       int            `json:"page"`
	PageSize   int            `json:"page_size"`
}
