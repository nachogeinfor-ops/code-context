// Package services — user account business logic.
package services

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"

	"github.com/example/goapi/internal/models"
	"github.com/example/goapi/internal/repository"
	"github.com/example/goapi/internal/types"
)

// ErrEmailAlreadyTaken is returned by CreateUser when the supplied email is
// already registered.
var ErrEmailAlreadyTaken = errors.New("email already taken")

// UserService orchestrates user account creation, lookup, and updates.
type UserService struct {
	repo *repository.UserRepository
	auth *AuthService
}

// NewUserService constructs a UserService wired to its dependencies.
func NewUserService(repo *repository.UserRepository, auth *AuthService) *UserService {
	return &UserService{repo: repo, auth: auth}
}

// CreateUser registers a new account. The password is bcrypt-hashed before
// being persisted. Returns ErrEmailAlreadyTaken on email collision.
func (s *UserService) CreateUser(ctx context.Context, req *types.CreateUserRequest) (*models.User, error) {
	if existing, _ := s.repo.FindByEmail(ctx, req.Email); existing != nil {
		return nil, ErrEmailAlreadyTaken
	}
	hash, err := s.auth.HashPassword(req.Password)
	if err != nil {
		return nil, fmt.Errorf("hash password: %w", err)
	}
	user := models.NewUser(newID(), req.Email, req.Username, hash)
	if err := s.repo.Insert(ctx, user); err != nil {
		return nil, fmt.Errorf("insert user: %w", err)
	}
	return user, nil
}

// GetUserByID fetches a user by their primary key.
func (s *UserService) GetUserByID(ctx context.Context, id string) (*models.User, error) {
	return s.repo.FindByID(ctx, id)
}

// GetUserByEmail fetches a user by their email address.
func (s *UserService) GetUserByEmail(ctx context.Context, email string) (*models.User, error) {
	return s.repo.FindByEmail(ctx, email)
}

// ListUsers returns a paginated slice of users.
func (s *UserService) ListUsers(ctx context.Context, page, pageSize int) ([]models.User, int, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	offset := (page - 1) * pageSize
	rows, err := s.repo.List(ctx, offset, pageSize)
	if err != nil {
		return nil, 0, err
	}
	total, err := s.repo.Count(ctx)
	if err != nil {
		return nil, 0, err
	}
	return rows, total, nil
}

// UpdateUser applies a patch to an existing user record.
func (s *UserService) UpdateUser(ctx context.Context, id string, patch *types.UpdateUserRequest) (*models.User, error) {
	current, err := s.repo.FindByID(ctx, id)
	if err != nil {
		return nil, err
	}
	if patch.Email != nil {
		current.Email = *patch.Email
	}
	if patch.Username != nil {
		current.Username = *patch.Username
	}
	if patch.Password != nil {
		hash, err := s.auth.HashPassword(*patch.Password)
		if err != nil {
			return nil, fmt.Errorf("hash password: %w", err)
		}
		current.PasswordHash = hash
	}
	if err := s.repo.Update(ctx, id, current); err != nil {
		return nil, err
	}
	return current, nil
}

// DeleteUser removes a user by id.
func (s *UserService) DeleteUser(ctx context.Context, id string) error {
	return s.repo.Delete(ctx, id)
}

// newID returns a random 128-bit hex identifier suitable for user/item IDs.
func newID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}
