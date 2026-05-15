// Package models contains domain structs persisted by the repository layer.
//
// Field tags target sqlx (db:"...") for column mapping; json tags are kept
// minimal here because public-facing shapes live in internal/types.
package models

import "time"

// User is the canonical user record stored in the `users` table.
type User struct {
	ID           string    `db:"id" json:"id"`
	Email        string    `db:"email" json:"email"`
	Username     string    `db:"username" json:"username"`
	PasswordHash string    `db:"password_hash" json:"-"`
	CreatedAt    time.Time `db:"created_at" json:"created_at"`
}

// NewUser allocates a User with a fresh ID and CreatedAt set to now.
func NewUser(id, email, username, passwordHash string) *User {
	return &User{
		ID:           id,
		Email:        email,
		Username:     username,
		PasswordHash: passwordHash,
		CreatedAt:    time.Now().UTC(),
	}
}

// Equal compares two users by identity, used in tests.
func (u *User) Equal(other *User) bool {
	if u == nil || other == nil {
		return u == other
	}
	return u.ID == other.ID && u.Email == other.Email
}
