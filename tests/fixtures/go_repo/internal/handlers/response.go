// Package handlers — shared JSON helpers + response mappers.
package handlers

import (
	"encoding/json"
	"log"
	"net/http"

	"github.com/example/goapi/internal/models"
	"github.com/example/goapi/internal/types"
)

// errorBody is the canonical envelope returned for non-2xx responses.
type errorBody struct {
	Error string `json:"error"`
}

// writeJSON serialises `body` as JSON and writes it with the given status.
func writeJSON(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if body == nil {
		return
	}
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Printf("writeJSON: %v", err)
	}
}

// writeError is a convenience wrapper around writeJSON for error responses.
func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, errorBody{Error: message})
}

// toUserResponse projects a User model into its public response shape.
func toUserResponse(u *models.User) types.UserResponse {
	return types.UserResponse{
		ID:        u.ID,
		Email:     u.Email,
		Username:  u.Username,
		CreatedAt: u.CreatedAt,
	}
}

// toItemResponse projects an Item model into its public response shape.
func toItemResponse(i *models.Item) types.ItemResponse {
	return types.ItemResponse{
		ID:          i.ID,
		OwnerID:     i.OwnerID,
		Title:       i.Title,
		Description: i.Description,
		CreatedAt:   i.CreatedAt,
	}
}
