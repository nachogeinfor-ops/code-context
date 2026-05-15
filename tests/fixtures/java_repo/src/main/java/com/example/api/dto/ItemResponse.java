package com.example.api.dto;

import com.example.api.models.Item;
import java.time.Instant;

/**
 * ItemResponse — public-facing item shape returned by /api/items endpoints.
 *
 * <p>Record-based POJO with {@code id}, {@code ownerId}, {@code title},
 * {@code description}, and {@code createdAt}. The {@link #fromEntity}
 * factory adapts a JPA {@link Item} for transport.
 */
public record ItemResponse(
    Long id,
    Long ownerId,
    String title,
    String description,
    Instant createdAt
) {
    public static ItemResponse fromEntity(Item item) {
        return new ItemResponse(
            item.getId(),
            item.getOwnerId(),
            item.getTitle(),
            item.getDescription(),
            item.getCreatedAt()
        );
    }
}
