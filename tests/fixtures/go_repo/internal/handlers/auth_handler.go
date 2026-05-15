// Package handlers contains chi HTTP handlers that translate JSON payloads
// to service-layer calls and back.
package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/example/goapi/internal/services"
	"github.com/example/goapi/internal/types"
)

// AuthHandler hosts /auth endpoints (login, refresh).
type AuthHandler struct {
	users *services.UserService
	auth  *services.AuthService
}

// NewAuthHandler constructs an AuthHandler wired to its services.
func NewAuthHandler(users *services.UserService, auth *services.AuthService) *AuthHandler {
	return &AuthHandler{users: users, auth: auth}
}

// Login authenticates an email+password pair and returns an access/refresh
// token pair. Responds 401 on bad credentials, 400 on bad request body.
func (h *AuthHandler) Login(w http.ResponseWriter, r *http.Request) {
	var req types.LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	user, err := h.users.GetUserByEmail(r.Context(), req.Email)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	if !h.auth.ComparePassword(req.Password, user.PasswordHash) {
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	tokens, err := h.auth.IssueTokenPair(user.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue tokens")
		return
	}
	writeJSON(w, http.StatusOK, tokens)
}

// Refresh exchanges a valid refresh token for a new access+refresh pair.
func (h *AuthHandler) Refresh(w http.ResponseWriter, r *http.Request) {
	var req types.RefreshRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	claims, err := h.auth.ValidateToken(req.RefreshToken, types.RefreshToken)
	if err != nil {
		if errors.Is(err, services.ErrInvalidToken) {
			writeError(w, http.StatusUnauthorized, "invalid refresh token")
			return
		}
		writeError(w, http.StatusInternalServerError, "could not validate token")
		return
	}
	tokens, err := h.auth.IssueTokenPair(claims.Subject)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue tokens")
		return
	}
	writeJSON(w, http.StatusOK, tokens)
}
