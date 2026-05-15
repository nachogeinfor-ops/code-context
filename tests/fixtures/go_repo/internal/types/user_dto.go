// Package types — request/response shapes for /users endpoints.
package types

import "time"

// CreateUserRequest is the JSON body for POST /users.
type CreateUserRequest struct {
	Email    string `json:"email" validate:"required,email"`
	Username string `json:"username" validate:"required,min=3,max=32"`
	Password string `json:"password" validate:"required,min=8"`
}

// UpdateUserRequest is the JSON body for PATCH /users/{id}. All fields are
// optional; nil pointers mean "leave unchanged".
type UpdateUserRequest struct {
	Email    *string `json:"email,omitempty" validate:"omitempty,email"`
	Username *string `json:"username,omitempty" validate:"omitempty,min=3,max=32"`
	Password *string `json:"password,omitempty" validate:"omitempty,min=8"`
}

// UserResponse is the public, serialised shape of a User. Never contains
// the password hash.
type UserResponse struct {
	ID        string    `json:"id"`
	Email     string    `json:"email"`
	Username  string    `json:"username"`
	CreatedAt time.Time `json:"created_at"`
}

// UserListResponse wraps a page of users with pagination metadata.
type UserListResponse struct {
	Items      []UserResponse `json:"items"`
	TotalCount int            `json:"total_count"`
	Page       int            `json:"page"`
	PageSize   int            `json:"page_size"`
}
