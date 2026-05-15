// Package handlers — /items CRUD endpoints scoped to the authenticated user.
package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	"github.com/example/goapi/internal/middleware"
	"github.com/example/goapi/internal/repository"
	"github.com/example/goapi/internal/services"
	"github.com/example/goapi/internal/types"
)

// ItemsHandler hosts /items endpoints.
type ItemsHandler struct {
	items *services.ItemService
}

// NewItemsHandler constructs an ItemsHandler.
func NewItemsHandler(items *services.ItemService) *ItemsHandler {
	return &ItemsHandler{items: items}
}

// CreateItem handles POST /items, owned by the caller's user id.
func (h *ItemsHandler) CreateItem(w http.ResponseWriter, r *http.Request) {
	ownerID := middleware.UserIDFromContext(r.Context())
	var req types.CreateItemRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	item, err := h.items.CreateItem(r.Context(), ownerID, &req)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create item")
		return
	}
	writeJSON(w, http.StatusCreated, toItemResponse(item))
}

// GetItem handles GET /items/{id}.
func (h *ItemsHandler) GetItem(w http.ResponseWriter, r *http.Request) {
	ownerID := middleware.UserIDFromContext(r.Context())
	id := chi.URLParam(r, "id")
	item, err := h.items.GetItem(r.Context(), ownerID, id)
	if err != nil {
		handleItemError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, toItemResponse(item))
}

// ListItems handles GET /items with page/page_size query params, scoped to
// the authenticated user's items.
func (h *ItemsHandler) ListItems(w http.ResponseWriter, r *http.Request) {
	ownerID := middleware.UserIDFromContext(r.Context())
	page, _ := strconv.Atoi(r.URL.Query().Get("page"))
	pageSize, _ := strconv.Atoi(r.URL.Query().Get("page_size"))
	rows, total, err := h.items.ListItemsByOwner(r.Context(), ownerID, page, pageSize)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list items")
		return
	}
	resp := types.ItemListResponse{
		Items:      make([]types.ItemResponse, 0, len(rows)),
		TotalCount: total,
		Page:       page,
		PageSize:   pageSize,
	}
	for i := range rows {
		resp.Items = append(resp.Items, toItemResponse(&rows[i]))
	}
	writeJSON(w, http.StatusOK, resp)
}

// UpdateItem handles PATCH /items/{id}.
func (h *ItemsHandler) UpdateItem(w http.ResponseWriter, r *http.Request) {
	ownerID := middleware.UserIDFromContext(r.Context())
	id := chi.URLParam(r, "id")
	var patch types.UpdateItemRequest
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	item, err := h.items.UpdateItem(r.Context(), ownerID, id, &patch)
	if err != nil {
		handleItemError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, toItemResponse(item))
}

// DeleteItem handles DELETE /items/{id}.
func (h *ItemsHandler) DeleteItem(w http.ResponseWriter, r *http.Request) {
	ownerID := middleware.UserIDFromContext(r.Context())
	id := chi.URLParam(r, "id")
	if err := h.items.DeleteItem(r.Context(), ownerID, id); err != nil {
		handleItemError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// handleItemError maps a service-layer error to an HTTP status.
func handleItemError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, repository.ErrItemNotFound):
		writeError(w, http.StatusNotFound, "item not found")
	case errors.Is(err, services.ErrForbidden):
		writeError(w, http.StatusForbidden, "forbidden")
	default:
		writeError(w, http.StatusInternalServerError, "internal error")
	}
}
