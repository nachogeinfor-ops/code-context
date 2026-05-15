// Package tests — integration-flavoured tests for the auth endpoints.
package tests

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/example/goapi/internal/types"
)

// TestLoginEndpointReturnsAccessToken verifies POST /auth/login returns a
// 200 status with a non-empty access/refresh token pair for valid creds.
func TestLoginEndpointReturnsAccessToken(t *testing.T) {
	srv := newTestServer(t)
	defer srv.Close()

	body := types.LoginRequest{
		Email:    "alice@example.com",
		Password: "supersecret",
	}
	resp := postJSON(t, srv.URL+"/auth/login", body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	var pair types.TokenPair
	if err := json.NewDecoder(resp.Body).Decode(&pair); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if pair.AccessToken == "" || pair.RefreshToken == "" {
		t.Fatalf("empty tokens in response: %+v", pair)
	}
}

// TestLoginRejectsBadPassword verifies the endpoint returns 401 when the
// password does not match.
func TestLoginRejectsBadPassword(t *testing.T) {
	srv := newTestServer(t)
	defer srv.Close()

	body := types.LoginRequest{
		Email:    "alice@example.com",
		Password: "wrong-password",
	}
	resp := postJSON(t, srv.URL+"/auth/login", body)
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", resp.StatusCode)
	}
}

// TestRefreshTokenIssuesNewAccessToken exercises the /auth/refresh flow.
func TestRefreshTokenIssuesNewAccessToken(t *testing.T) {
	srv := newTestServer(t)
	defer srv.Close()

	// Pretend we already have a valid refresh token from a prior login.
	pair := loginAndGetTokens(t, srv.URL, "alice@example.com", "supersecret")

	body := types.RefreshRequest{RefreshToken: pair.RefreshToken}
	resp := postJSON(t, srv.URL+"/auth/refresh", body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
}

// postJSON serialises body as JSON and POSTs it to url.
func postJSON(t *testing.T, url string, body interface{}) *http.Response {
	t.Helper()
	buf, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	resp, err := http.Post(url, "application/json", bytes.NewReader(buf))
	if err != nil {
		t.Fatalf("post: %v", err)
	}
	return resp
}

// newTestServer is a placeholder; in a real test we would wire a chi router
// with an in-memory sqlite db and a seeded "alice" user.
func newTestServer(_ *testing.T) *httptest.Server {
	return httptest.NewServer(http.NotFoundHandler())
}

// loginAndGetTokens performs a login round-trip and returns the parsed pair.
func loginAndGetTokens(t *testing.T, baseURL, email, password string) types.TokenPair {
	t.Helper()
	resp := postJSON(t, baseURL+"/auth/login", types.LoginRequest{Email: email, Password: password})
	var pair types.TokenPair
	_ = json.NewDecoder(resp.Body).Decode(&pair)
	return pair
}
