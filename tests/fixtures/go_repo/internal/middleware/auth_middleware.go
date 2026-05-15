// Package middleware contains chi-compatible HTTP middleware for
// cross-cutting concerns (auth, logging).
package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/example/goapi/internal/services"
	"github.com/example/goapi/internal/types"
)

// ctxKey is an unexported type used as a context key so callers cannot
// accidentally collide with us.
type ctxKey int

const userIDKey ctxKey = iota

// RequireAuth returns chi middleware that verifies the `Authorization:
// Bearer <jwt>` header and stuffs the decoded user id into the request
// context. Responds 401 on any failure.
func RequireAuth(auth *services.AuthService) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw := extractBearerToken(r)
			if raw == "" {
				respondUnauthorized(w, "missing bearer token")
				return
			}
			claims, err := auth.ValidateToken(raw, types.AccessToken)
			if err != nil {
				respondUnauthorized(w, "invalid access token")
				return
			}
			ctx := context.WithValue(r.Context(), userIDKey, claims.Subject)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// extractBearerToken pulls the JWT out of the Authorization header.
func extractBearerToken(r *http.Request) string {
	header := r.Header.Get("Authorization")
	if header == "" {
		return ""
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return ""
	}
	return strings.TrimSpace(header[len(prefix):])
}

// UserIDFromContext retrieves the authenticated user id placed by RequireAuth.
// Returns the empty string if no user is bound to the context.
func UserIDFromContext(ctx context.Context) string {
	if v, ok := ctx.Value(userIDKey).(string); ok {
		return v
	}
	return ""
}

// respondUnauthorized writes a 401 JSON error envelope.
func respondUnauthorized(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
