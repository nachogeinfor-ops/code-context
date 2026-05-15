package com.example.api.dto;

import com.example.api.models.User;
import java.time.Instant;

/**
 * UserResponse — public-facing user shape returned by /api/users endpoints.
 *
 * <p>Implemented as a Java record so the JSON shape is fixed at compile
 * time. The password hash is intentionally absent — only the safe,
 * read-only fields are exposed.
 */
public record UserResponse(
    Long id,
    String email,
    String username,
    Instant createdAt
) {
    /**
     * fromEntity adapts a {@link User} JPA entity to the public DTO,
     * stripping the password hash.
     */
    public static UserResponse fromEntity(User user) {
        return new UserResponse(
            user.getId(),
            user.getEmail(),
            user.getUsername(),
            user.getCreatedAt()
        );
    }
}
