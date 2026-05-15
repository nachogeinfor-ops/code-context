package com.example.api.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

/**
 * AppConfig — non-security beans (encoder, ObjectMapper, JWT secret).
 *
 * <p>SecurityConfig handles the filter chain itself; this file just
 * supplies a few shared singletons that other components inject by type.
 */
@Configuration
public class AppConfig {

    @Value("${app.security.bcrypt-strength:12}")
    private int bcryptStrength;

    @Value("${app.security.jwt-secret:change-me-in-production-please}")
    private String jwtSecret;

    @Value("${app.security.jwt-access-ttl-seconds:900}")
    private long jwtAccessTtlSeconds;

    @Value("${app.security.jwt-refresh-ttl-seconds:2592000}")
    private long jwtRefreshTtlSeconds;

    /**
     * passwordEncoder exposes a {@link BCryptPasswordEncoder} tuned by the
     * configured cost factor. Used by AuthService for hashing + verifying.
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(bcryptStrength);
    }

    /**
     * objectMapper customises Jackson for ISO-8601 dates and pretty-printing.
     */
    @Bean
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.registerModule(new JavaTimeModule());
        mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        return mapper;
    }

    public String getJwtSecret() {
        return jwtSecret;
    }

    public long getJwtAccessTtlSeconds() {
        return jwtAccessTtlSeconds;
    }

    public long getJwtRefreshTtlSeconds() {
        return jwtRefreshTtlSeconds;
    }
}
