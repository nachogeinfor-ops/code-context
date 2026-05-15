package com.example.api.services;

import com.example.api.config.AppConfig;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Component;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;

/**
 * JwtTokenProvider — issues and validates JWT access + refresh tokens.
 *
 * <p>Uses HS256 with a secret pulled from {@link AppConfig}. Access
 * tokens are short-lived; refresh tokens are long-lived and carry a
 * {@code typ=refresh} claim so they cannot accidentally be used as
 * access tokens.
 */
@Component
public class JwtTokenProvider {

    private static final String TYPE_CLAIM = "typ";
    private static final String ACCESS_TYPE = "access";
    private static final String REFRESH_TYPE = "refresh";

    private final AppConfig config;
    private final SecretKey signingKey;

    public JwtTokenProvider(AppConfig config) {
        this.config = config;
        byte[] secretBytes = config.getJwtSecret().getBytes(StandardCharsets.UTF_8);
        this.signingKey = Keys.hmacShaKeyFor(secretBytes);
    }

    /**
     * issueAccessToken signs a short-lived JWT for the given user id.
     */
    public String issueAccessToken(Long userId) {
        return signToken(userId, ACCESS_TYPE, config.getJwtAccessTtlSeconds());
    }

    /**
     * issueRefreshToken signs a long-lived JWT used to exchange for new
     * access tokens.
     */
    public String issueRefreshToken(Long userId) {
        return signToken(userId, REFRESH_TYPE, config.getJwtRefreshTtlSeconds());
    }

    /**
     * validateToken parses the supplied JWT, checks the signature, and
     * confirms the {@code typ} claim matches what the caller expected.
     * Throws an unchecked exception on any failure.
     */
    public Claims validateToken(String raw, boolean requireAccess) {
        Claims claims = Jwts.parserBuilder()
            .setSigningKey(signingKey)
            .build()
            .parseClaimsJws(raw)
            .getBody();
        String expected = requireAccess ? ACCESS_TYPE : REFRESH_TYPE;
        Object actual = claims.get(TYPE_CLAIM);
        if (!expected.equals(actual)) {
            throw new IllegalArgumentException(
                "expected " + expected + " token but got " + actual);
        }
        return claims;
    }

    /**
     * extractUserId returns the subject claim as a {@link Long}.
     */
    public Long extractUserId(Claims claims) {
        return Long.parseLong(claims.getSubject());
    }

    /**
     * signToken assembles + signs a JWT with the given subject, type, and TTL.
     */
    private String signToken(Long userId, String type, long ttlSeconds) {
        Instant now = Instant.now();
        Instant exp = now.plusSeconds(ttlSeconds);
        return Jwts.builder()
            .setSubject(String.valueOf(userId))
            .claim(TYPE_CLAIM, type)
            .setIssuedAt(Date.from(now))
            .setExpiration(Date.from(exp))
            .signWith(signingKey, SignatureAlgorithm.HS256)
            .compact();
    }
}
