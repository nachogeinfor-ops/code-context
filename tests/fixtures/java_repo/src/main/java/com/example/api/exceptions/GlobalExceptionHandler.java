package com.example.api.exceptions;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * GlobalExceptionHandler — translates exceptions thrown by controllers
 * and services into JSON error envelopes.
 *
 * <p>Implemented via {@code @ControllerAdvice} so it applies across the
 * whole API surface. {@link ApiException} carries its own status;
 * everything else falls back to 500.
 */
@ControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /**
     * handleApiException turns a known ApiException into its declared status.
     */
    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, Object>> handleApiException(ApiException ex) {
        return ResponseEntity.status(ex.getStatus()).body(errorBody(ex.getMessage(), ex.getStatus()));
    }

    /**
     * handleValidation maps {@code @Valid} failures to 400 Bad Request.
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException ex) {
        Map<String, Object> body = errorBody("validation failed", HttpStatus.BAD_REQUEST);
        Map<String, String> fields = new HashMap<>();
        ex.getBindingResult().getFieldErrors().forEach(f ->
            fields.put(f.getField(), f.getDefaultMessage())
        );
        body.put("fields", fields);
        return ResponseEntity.badRequest().body(body);
    }

    /**
     * handleUnexpected catches anything else — logs the stack and emits 500.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleUnexpected(Exception ex) {
        log.error("unexpected error", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
            .body(errorBody("internal server error", HttpStatus.INTERNAL_SERVER_ERROR));
    }

    private Map<String, Object> errorBody(String message, HttpStatus status) {
        Map<String, Object> body = new HashMap<>();
        body.put("error", message);
        body.put("status", status.value());
        body.put("timestamp", Instant.now().toString());
        return body;
    }
}
