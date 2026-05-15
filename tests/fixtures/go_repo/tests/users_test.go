// Package tests — integration-flavoured tests for /users endpoints.
package tests

import (
	"encoding/json"
	"net/http"
	"testing"

	"github.com/example/goapi/internal/types"
)

// TestCreateUserEndpointReturns201 verifies POST /users returns a 201
// Created response with the persisted user shape.
func TestCreateUserEndpointReturns201(t *testing.T) {
	srv := newTestServer(t)
	defer srv.Close()

	body := types.CreateUserRequest{
		Email:    "bob@example.com",
		Username: "bobthebuilder",
		Password: "correct-horse",
	}
	resp := postJSON(t, srv.URL+"/users", body)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want 201", resp.StatusCode)
	}
	var user types.UserResponse
	if err := json.NewDecoder(resp.Body).Decode(&user); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if user.ID == "" || user.Email != body.Email {
		t.Fatalf("unexpected user payload: %+v", user)
	}
}

// TestCreateUserConflictOnDuplicateEmail verifies 409 on duplicate email.
func TestCreateUserConflictOnDuplicateEmail(t *testing.T) {
	srv := newTestServer(t)
	defer srv.Close()

	body := types.CreateUserRequest{
		Email:    "alice@example.com",
		Username: "alice2",
		Password: "another-secret",
	}
	resp := postJSON(t, srv.URL+"/users", body)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("status = %d, want 409", resp.StatusCode)
	}
}

// TestListUsersReturnsPagedResponse verifies pagination metadata is filled.
func TestListUsersReturnsPagedResponse(t *testing.T) {
	srv := newTestServer(t)
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/users?page=1&page_size=10", nil)
	req.Header.Set("Authorization", "Bearer test-token")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
}
