package com.example.api.dto;

/**
 * TokenResponse — POJO response shape returned by /api/auth/login and
 * /api/auth/refresh.
 *
 * <p>Mirrors the OAuth2 bearer-token envelope: {@code accessToken},
 * {@code refreshToken}, {@code expiresIn} (seconds), and a fixed
 * {@code tokenType = "Bearer"}.
 */
public class TokenResponse {

    private String accessToken;
    private String refreshToken;
    private long expiresIn;
    private String tokenType = "Bearer";

    public TokenResponse() {
    }

    public TokenResponse(String accessToken, String refreshToken, long expiresIn) {
        this.accessToken = accessToken;
        this.refreshToken = refreshToken;
        this.expiresIn = expiresIn;
    }

    public String getAccessToken() {
        return accessToken;
    }

    public void setAccessToken(String accessToken) {
        this.accessToken = accessToken;
    }

    public String getRefreshToken() {
        return refreshToken;
    }

    public void setRefreshToken(String refreshToken) {
        this.refreshToken = refreshToken;
    }

    public long getExpiresIn() {
        return expiresIn;
    }

    public void setExpiresIn(long expiresIn) {
        this.expiresIn = expiresIn;
    }

    public String getTokenType() {
        return tokenType;
    }

    public void setTokenType(String tokenType) {
        this.tokenType = tokenType;
    }
}
