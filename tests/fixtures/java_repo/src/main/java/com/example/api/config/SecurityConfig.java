package com.example.api.config;

import com.example.api.middleware.JwtAuthFilter;
import com.example.api.middleware.RequestLoggingFilter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * SecurityConfig — Spring Security filter chain setup.
 *
 * <p>Disables CSRF (this is a stateless REST API), turns sessions off,
 * permits the auth endpoints anonymously, and inserts the
 * {@link JwtAuthFilter} before Spring's username/password filter so that
 * downstream controllers see an authenticated SecurityContext.
 */
@Configuration
public class SecurityConfig {

    private final JwtAuthFilter jwtAuthFilter;
    private final RequestLoggingFilter requestLoggingFilter;

    public SecurityConfig(JwtAuthFilter jwtAuthFilter, RequestLoggingFilter requestLoggingFilter) {
        this.jwtAuthFilter = jwtAuthFilter;
        this.requestLoggingFilter = requestLoggingFilter;
    }

    /**
     * securityFilterChain builds the stateless JWT-based filter chain.
     */
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            .csrf(AbstractHttpConfigurer::disable)
            .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers(HttpMethod.POST, "/api/auth/login").permitAll()
                .requestMatchers(HttpMethod.POST, "/api/auth/refresh").permitAll()
                .requestMatchers("/api/health").permitAll()
                .anyRequest().authenticated()
            )
            .addFilterBefore(requestLoggingFilter, UsernamePasswordAuthenticationFilter.class)
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
