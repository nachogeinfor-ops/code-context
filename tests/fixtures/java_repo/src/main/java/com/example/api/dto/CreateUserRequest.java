package com.example.api.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * CreateUserRequest — DTO for POST /api/users.
 *
 * <p>Validated by {@code @Valid} in {@link
 * com.example.api.controllers.UsersController#createUser}. The
 * controller never persists this directly — it hands the validated
 * POJO to {@link com.example.api.services.UserService}, which hashes
 * the password and constructs the JPA entity.
 */
public class CreateUserRequest {

    @NotBlank
    @Email
    private String email;

    @NotBlank
    @Size(min = 3, max = 32)
    private String username;

    @NotBlank
    @Size(min = 8, max = 128)
    private String password;

    public CreateUserRequest() {
    }

    public CreateUserRequest(String email, String username, String password) {
        this.email = email;
        this.username = username;
        this.password = password;
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
