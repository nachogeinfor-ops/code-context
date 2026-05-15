// Package types contains request and response DTOs serialised by the
// handler layer, plus JWT claim types shared between handlers, middleware,
// and the auth service.
package types

import "github.com/golang-jwt/jwt/v5"

// LoginRequest is the body of POST /auth/login.
type LoginRequest struct {
	Email    string `json:"email" validate:"required,email"`
	Password string `json:"password" validate:"required,min=8"`
}

// RefreshRequest is the body of POST /auth/refresh.
type RefreshRequest struct {
	RefreshToken string `json:"refresh_token" validate:"required"`
}

// TokenPair is the JSON shape returned by /auth/login and /auth/refresh.
type TokenPair struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int64  `json:"expires_in"`
	TokenType    string `json:"token_type"`
}

// TokenType discriminates between access and refresh JWTs.
type TokenType string

const (
	AccessToken  TokenType = "access"
	RefreshToken TokenType = "refresh"
)

// Claims is the custom JWT payload embedded in every issued token.
// `Subject` (in RegisteredClaims) holds the user ID.
type Claims struct {
	jwt.RegisteredClaims
	Type TokenType `json:"typ"`
}

// IsAccess reports whether these claims belong to an access token.
func (c *Claims) IsAccess() bool {
	return c != nil && c.Type == AccessToken
}

// IsRefresh reports whether these claims belong to a refresh token.
func (c *Claims) IsRefresh() bool {
	return c != nil && c.Type == RefreshToken
}
