package com.example.api.middleware;

import com.example.api.services.JwtTokenProvider;
import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.util.List;

/**
 * JwtAuthFilter — extends {@link OncePerRequestFilter} to authenticate
 * each incoming HTTP request via {@code Authorization: Bearer <jwt>}.
 *
 * <p>Successful verification populates the Spring SecurityContext with
 * a {@code UsernamePasswordAuthenticationToken} whose principal is the
 * numeric user id. Failures leave the context empty so downstream
 * authorisation rules can reject the request.
 */
@Component
public class JwtAuthFilter extends OncePerRequestFilter {

    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtTokenProvider tokenProvider;

    public JwtAuthFilter(JwtTokenProvider tokenProvider) {
        this.tokenProvider = tokenProvider;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain chain
    ) throws ServletException, IOException {
        String token = extractBearerToken(request);
        if (token != null) {
            try {
                Claims claims = tokenProvider.validateToken(token, true);
                Long userId = tokenProvider.extractUserId(claims);
                authenticate(userId);
            } catch (Exception ignored) {
                SecurityContextHolder.clearContext();
            }
        }
        chain.doFilter(request, response);
    }

    /**
     * extractBearerToken pulls the JWT out of the Authorization header.
     */
    private String extractBearerToken(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        return header.substring(BEARER_PREFIX.length()).trim();
    }

    /**
     * authenticate stuffs the resolved user id into Spring's
     * SecurityContext as an anonymous-role authentication token.
     */
    private void authenticate(Long userId) {
        UsernamePasswordAuthenticationToken auth =
            new UsernamePasswordAuthenticationToken(
                userId,
                null,
                List.of(new SimpleGrantedAuthority("ROLE_USER"))
            );
        SecurityContextHolder.getContext().setAuthentication(auth);
    }
}
