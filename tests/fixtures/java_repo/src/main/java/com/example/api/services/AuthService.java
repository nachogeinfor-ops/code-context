package com.example.api.services;

import com.example.api.config.AppConfig;
import com.example.api.dto.LoginRequest;
import com.example.api.dto.TokenResponse;
import com.example.api.exceptions.ApiException;
import com.example.api.models.User;
import com.example.api.repositories.UserRepository;
import io.jsonwebtoken.Claims;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import java.util.Optional;

/**
 * AuthService — login + refresh business logic.
 *
 * <p>Delegates JWT signing/verification to {@link JwtTokenProvider} and
 * password hashing to the configured {@link PasswordEncoder} (bcrypt).
 * Returns {@link TokenResponse} envelopes so the controller can serialise
 * them straight back to the client.
 */
@Service
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider tokenProvider;
    private final AppConfig appConfig;

    public AuthService(
        UserRepository userRepository,
        PasswordEncoder passwordEncoder,
        JwtTokenProvider tokenProvider,
        AppConfig appConfig
    ) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.tokenProvider = tokenProvider;
        this.appConfig = appConfig;
    }

    /**
     * login authenticates a user by email + password and returns a fresh
     * access/refresh token pair. Throws 401 on any credential mismatch.
     */
    public TokenResponse login(LoginRequest request) {
        Optional<User> maybeUser = userRepository.findByEmail(request.getEmail());
        if (maybeUser.isEmpty()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "invalid credentials");
        }
        User user = maybeUser.get();
        if (!passwordEncoder.matches(request.getPassword(), user.getPasswordHash())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "invalid credentials");
        }
        return issueTokenPair(user);
    }

    /**
     * refresh validates an existing refresh token and issues a new
     * access/refresh token pair for the same user.
     */
    public TokenResponse refresh(String refreshToken) {
        Claims claims;
        try {
            claims = tokenProvider.validateToken(refreshToken, false);
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "invalid refresh token");
        }
        Long userId = tokenProvider.extractUserId(claims);
        User user = userRepository.findById(userId)
            .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "user not found"));
        return issueTokenPair(user);
    }

    /**
     * encodePassword runs the configured bcrypt encoder over a plaintext
     * credential. Exposed for {@link UserService} to share the same encoder.
     */
    public String encodePassword(String plaintext) {
        return passwordEncoder.encode(plaintext);
    }

    /**
     * issueTokenPair signs both an access + refresh token for a user.
     */
    private TokenResponse issueTokenPair(User user) {
        String access = tokenProvider.issueAccessToken(user.getId());
        String refresh = tokenProvider.issueRefreshToken(user.getId());
        return new TokenResponse(access, refresh, appConfig.getJwtAccessTtlSeconds());
    }
}
