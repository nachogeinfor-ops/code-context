package com.example.api.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Size;

/**
 * UpdateUserRequest — partial-update DTO for PATCH /api/users/{id}.
 *
 * <p>All fields are optional; nulls mean "leave the existing value
 * alone." Service-layer code applies the non-null fields to the
 * tracked JPA entity before flushing.
 */
public class UpdateUserRequest {

    @Email
    private String email;

    @Size(min = 3, max = 32)
    private String username;

    @Size(min = 8, max = 128)
    private String password;

    public UpdateUserRequest() {
    }

    public String getEmail() {
        return email;
    }

    public void setEmail(String email) {
        this.email = email;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }
}
