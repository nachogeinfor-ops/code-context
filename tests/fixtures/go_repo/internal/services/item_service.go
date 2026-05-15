// Package services — item business logic.
package services

import (
	"context"
	"errors"

	"github.com/example/goapi/internal/models"
	"github.com/example/goapi/internal/repository"
	"github.com/example/goapi/internal/types"
)

// ErrForbidden is returned when a caller attempts to operate on an item they
// do not own.
var ErrForbidden = errors.New("forbidden")

// ItemService orchestrates item CRUD on behalf of authenticated users.
type ItemService struct {
	repo *repository.ItemRepository
}

// NewItemService constructs an ItemService wired to its repository.
func NewItemService(repo *repository.ItemRepository) *ItemService {
	return &ItemService{repo: repo}
}

// CreateItem persists a new item belonging to ownerID.
func (s *ItemService) CreateItem(ctx context.Context, ownerID string, req *types.CreateItemRequest) (*models.Item, error) {
	item := models.NewItem(newID(), ownerID, req.Title, req.Description)
	if err := s.repo.Insert(ctx, item); err != nil {
		return nil, err
	}
	return item, nil
}

// GetItem fetches an item; returns ErrForbidden if the caller does not own it.
func (s *ItemService) GetItem(ctx context.Context, ownerID, id string) (*models.Item, error) {
	item, err := s.repo.FindByID(ctx, id)
	if err != nil {
		return nil, err
	}
	if !item.IsOwnedBy(ownerID) {
		return nil, ErrForbidden
	}
	return item, nil
}

// ListItemsByOwner returns a paginated slice of items owned by ownerID.
func (s *ItemService) ListItemsByOwner(ctx context.Context, ownerID string, page, pageSize int) ([]models.Item, int, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	offset := (page - 1) * pageSize
	rows, err := s.repo.ListByOwner(ctx, ownerID, offset, pageSize)
	if err != nil {
		return nil, 0, err
	}
	total, err := s.repo.CountByOwner(ctx, ownerID)
	if err != nil {
		return nil, 0, err
	}
	return rows, total, nil
}

// UpdateItem applies title/description changes if the caller owns the item.
func (s *ItemService) UpdateItem(ctx context.Context, ownerID, id string, patch *types.UpdateItemRequest) (*models.Item, error) {
	current, err := s.repo.FindByID(ctx, id)
	if err != nil {
		return nil, err
	}
	if !current.IsOwnedBy(ownerID) {
		return nil, ErrForbidden
	}
	if patch.Title != nil {
		current.Title = *patch.Title
	}
	if patch.Description != nil {
		current.Description = *patch.Description
	}
	if err := s.repo.Update(ctx, id, current); err != nil {
		return nil, err
	}
	return current, nil
}

// DeleteItem removes an item if the caller owns it.
func (s *ItemService) DeleteItem(ctx context.Context, ownerID, id string) error {
	item, err := s.repo.FindByID(ctx, id)
	if err != nil {
		return err
	}
	if !item.IsOwnedBy(ownerID) {
		return ErrForbidden
	}
	return s.repo.Delete(ctx, id)
}
