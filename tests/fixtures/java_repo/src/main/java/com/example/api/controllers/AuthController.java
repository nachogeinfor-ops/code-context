package com.example.api.controllers;

import com.example.api.dto.LoginRequest;
import com.example.api.dto.TokenResponse;
import com.example.api.services.AuthService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * AuthController — login + refresh endpoints.
 *
 * <p>Maps {@code /api/auth/login} and {@code /api/auth/refresh}; both
 * endpoints are open in {@link com.example.api.config.SecurityConfig}.
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    /**
     * login authenticates the supplied credentials and returns a
     * {@link TokenResponse} envelope on success.
     */
    @PostMapping("/login")
    public ResponseEntity<TokenResponse> login(@Valid @RequestBody LoginRequest request) {
        TokenResponse response = authService.login(request);
        return ResponseEntity.ok(response);
    }

    /**
     * refresh exchanges a valid refresh token for a new access/refresh pair.
     */
    @PostMapping("/refresh")
    public ResponseEntity<TokenResponse> refresh(
        @RequestHeader("X-Refresh-Token") String refreshToken
    ) {
        TokenResponse response = authService.refresh(refreshToken);
        return ResponseEntity.ok(response);
    }
}
