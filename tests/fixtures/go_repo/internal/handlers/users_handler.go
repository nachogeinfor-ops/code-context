// Package handlers — /users CRUD endpoints.
package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	"github.com/example/goapi/internal/repository"
	"github.com/example/goapi/internal/services"
	"github.com/example/goapi/internal/types"
)

// UsersHandler hosts /users endpoints.
type UsersHandler struct {
	users *services.UserService
}

// NewUsersHandler constructs a UsersHandler.
func NewUsersHandler(users *services.UserService) *UsersHandler {
	return &UsersHandler{users: users}
}

// CreateUser handles POST /users. Returns 201 with the created user on
// success, 409 when the email is already taken.
func (h *UsersHandler) CreateUser(w http.ResponseWriter, r *http.Request) {
	var req types.CreateUserRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	user, err := h.users.CreateUser(r.Context(), &req)
	if err != nil {
		if errors.Is(err, services.ErrEmailAlreadyTaken) {
			writeError(w, http.StatusConflict, "email already taken")
			return
		}
		writeError(w, http.StatusInternalServerError, "could not create user")
		return
	}
	writeJSON(w, http.StatusCreated, toUserResponse(user))
}

// GetUser handles GET /users/{id}.
func (h *UsersHandler) GetUser(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	user, err := h.users.GetUserByID(r.Context(), id)
	if err != nil {
		if errors.Is(err, repository.ErrUserNotFound) {
			writeError(w, http.StatusNotFound, "user not found")
			return
		}
		writeError(w, http.StatusInternalServerError, "could not fetch user")
		return
	}
	writeJSON(w, http.StatusOK, toUserResponse(user))
}

// ListUsers handles GET /users with page/page_size query params.
func (h *UsersHandler) ListUsers(w http.ResponseWriter, r *http.Request) {
	page, _ := strconv.Atoi(r.URL.Query().Get("page"))
	pageSize, _ := strconv.Atoi(r.URL.Query().Get("page_size"))
	rows, total, err := h.users.ListUsers(r.Context(), page, pageSize)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list users")
		return
	}
	resp := types.UserListResponse{
		Items:      make([]types.UserResponse, 0, len(rows)),
		TotalCount: total,
		Page:       page,
		PageSize:   pageSize,
	}
	for i := range rows {
		resp.Items = append(resp.Items, toUserResponse(&rows[i]))
	}
	writeJSON(w, http.StatusOK, resp)
}

// UpdateUser handles PATCH /users/{id}.
func (h *UsersHandler) UpdateUser(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	var patch types.UpdateUserRequest
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	user, err := h.users.UpdateUser(r.Context(), id, &patch)
	if err != nil {
		if errors.Is(err, repository.ErrUserNotFound) {
			writeError(w, http.StatusNotFound, "user not found")
			return
		}
		writeError(w, http.StatusInternalServerError, "could not update user")
		return
	}
	writeJSON(w, http.StatusOK, toUserResponse(user))
}

// DeleteUser handles DELETE /users/{id}.
func (h *UsersHandler) DeleteUser(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if err := h.users.DeleteUser(r.Context(), id); err != nil {
		if errors.Is(err, repository.ErrUserNotFound) {
			writeError(w, http.StatusNotFound, "user not found")
			return
		}
		writeError(w, http.StatusInternalServerError, "could not delete user")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
