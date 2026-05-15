package com.example.api.controllers;

import com.example.api.dto.CreateUserRequest;
import com.example.api.dto.UpdateUserRequest;
import com.example.api.dto.UserResponse;
import com.example.api.services.UserService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import java.util.List;

/**
 * UsersController — CRUD endpoints for {@code /api/users}.
 *
 * <p>Authentication is enforced by {@link
 * com.example.api.middleware.JwtAuthFilter}; this class only worries
 * about request → service → response wiring.
 */
@RestController
@RequestMapping("/api/users")
public class UsersController {

    private final UserService userService;

    public UsersController(UserService userService) {
        this.userService = userService;
    }

    /**
     * createUser handles POST /api/users. Returns 201 with the created
     * user, 409 when the email is already taken.
     */
    @PostMapping
    public ResponseEntity<UserResponse> createUser(
        @Valid @RequestBody CreateUserRequest request
    ) {
        UserResponse created = userService.createUser(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }

    /**
     * getUserById handles GET /api/users/{id}.
     */
    @GetMapping("/{id}")
    public ResponseEntity<UserResponse> getUserById(@PathVariable Long id) {
        return ResponseEntity.ok(userService.getUserById(id));
    }

    /**
     * listUsers handles GET /api/users with optional page / pageSize
     * query params.
     */
    @GetMapping
    public ResponseEntity<List<UserResponse>> listUsers(
        @RequestParam(defaultValue = "0") int page,
        @RequestParam(defaultValue = "20") int pageSize
    ) {
        List<UserResponse> rows = userService.listUsers(page, pageSize);
        return ResponseEntity.ok(rows);
    }

    /**
     * updateUser handles PATCH /api/users/{id}. Applies non-null fields
     * of the patch DTO to the tracked entity.
     */
    @PatchMapping("/{id}")
    public ResponseEntity<UserResponse> updateUser(
        @PathVariable Long id,
        @Valid @RequestBody UpdateUserRequest patch
    ) {
        UserResponse updated = userService.updateUser(id, patch);
        return ResponseEntity.ok(updated);
    }

    /**
     * deleteUser handles DELETE /api/users/{id}. Returns 204.
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteUser(@PathVariable Long id) {
        userService.deleteUser(id);
        return ResponseEntity.noContent().build();
    }
}
