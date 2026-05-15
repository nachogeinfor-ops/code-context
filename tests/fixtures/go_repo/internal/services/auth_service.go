// Package services contains the business logic that sits between handlers
// and repositories — JWT signing/verifying, bcrypt password hashing, and
// composite operations like user signup.
package services

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"

	"github.com/example/goapi/internal/config"
	"github.com/example/goapi/internal/types"
)

// ErrInvalidToken is returned when a JWT cannot be parsed or fails validation.
var ErrInvalidToken = errors.New("invalid token")

// AuthService bundles password hashing and JWT issuance + verification.
type AuthService struct {
	cfg *config.Config
}

// NewAuthService constructs an AuthService from a Config.
func NewAuthService(cfg *config.Config) *AuthService {
	return &AuthService{cfg: cfg}
}

// HashPassword runs bcrypt at the configured cost on the supplied plaintext.
func (s *AuthService) HashPassword(plain string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(plain), s.cfg.BcryptCost)
	if err != nil {
		return "", fmt.Errorf("bcrypt hash: %w", err)
	}
	return string(b), nil
}

// ComparePassword reports whether `plain` matches the bcrypt hash `stored`.
func (s *AuthService) ComparePassword(plain, stored string) bool {
	return bcrypt.CompareHashAndPassword([]byte(stored), []byte(plain)) == nil
}

// IssueAccessToken signs a short-lived JWT identifying the given user.
func (s *AuthService) IssueAccessToken(userID string) (string, error) {
	return s.signToken(userID, types.AccessToken, s.cfg.JWTAccessExpires)
}

// IssueRefreshToken signs a long-lived JWT used to obtain new access tokens.
func (s *AuthService) IssueRefreshToken(userID string) (string, error) {
	return s.signToken(userID, types.RefreshToken, s.cfg.JWTRefreshExpires)
}

// IssueTokenPair signs both an access and a refresh token for the user.
func (s *AuthService) IssueTokenPair(userID string) (*types.TokenPair, error) {
	access, err := s.IssueAccessToken(userID)
	if err != nil {
		return nil, err
	}
	refresh, err := s.IssueRefreshToken(userID)
	if err != nil {
		return nil, err
	}
	return &types.TokenPair{
		AccessToken:  access,
		RefreshToken: refresh,
		ExpiresIn:    int64(s.cfg.JWTAccessExpires.Seconds()),
		TokenType:    "Bearer",
	}, nil
}

// signToken builds + signs a JWT with the given subject, type, and TTL.
func (s *AuthService) signToken(userID string, tt types.TokenType, ttl time.Duration) (string, error) {
	now := time.Now().UTC()
	claims := types.Claims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
			NotBefore: jwt.NewNumericDate(now),
		},
		Type: tt,
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := token.SignedString([]byte(s.cfg.JWTSecret))
	if err != nil {
		return "", fmt.Errorf("sign jwt: %w", err)
	}
	return signed, nil
}

// ValidateToken parses + verifies a JWT and returns the embedded Claims.
// `expected` is the token type the caller requires (access or refresh).
func (s *AuthService) ValidateToken(raw string, expected types.TokenType) (*types.Claims, error) {
	parsed, err := jwt.ParseWithClaims(raw, &types.Claims{}, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return []byte(s.cfg.JWTSecret), nil
	})
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidToken, err)
	}
	claims, ok := parsed.Claims.(*types.Claims)
	if !ok || !parsed.Valid {
		return nil, ErrInvalidToken
	}
	if claims.Type != expected {
		return nil, fmt.Errorf("%w: expected %s token, got %s", ErrInvalidToken, expected, claims.Type)
	}
	return claims, nil
}
