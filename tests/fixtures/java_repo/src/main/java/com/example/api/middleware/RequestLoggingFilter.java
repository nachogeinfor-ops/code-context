package com.example.api.middleware;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.time.Duration;
import java.time.Instant;

/**
 * RequestLoggingFilter — logs each incoming HTTP request with method,
 * path, status, and elapsed duration.
 *
 * <p>Implemented as a {@link OncePerRequestFilter} so we run before the
 * authentication filter and capture timing for the entire chain,
 * including any 401s rejected by JwtAuthFilter.
 */
@Component
public class RequestLoggingFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RequestLoggingFilter.class);

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain chain
    ) throws ServletException, IOException {
        Instant start = Instant.now();
        try {
            chain.doFilter(request, response);
        } finally {
            long elapsed = Duration.between(start, Instant.now()).toMillis();
            log.info(
                "method={} path={} status={} duration_ms={}",
                request.getMethod(),
                request.getRequestURI(),
                response.getStatus(),
                elapsed
            );
        }
    }
}
