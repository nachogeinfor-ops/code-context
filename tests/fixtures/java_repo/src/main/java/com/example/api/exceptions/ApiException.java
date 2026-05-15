package com.example.api.exceptions;

import org.springframework.http.HttpStatus;

/**
 * ApiException — runtime exception carrying an HTTP status code and a
 * client-safe message.
 *
 * <p>Thrown from the service layer; caught + serialised into a JSON
 * error envelope by {@link GlobalExceptionHandler}.
 */
public class ApiException extends RuntimeException {

    private final HttpStatus status;

    public ApiException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public ApiException(HttpStatus status, String message, Throwable cause) {
        super(message, cause);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}
