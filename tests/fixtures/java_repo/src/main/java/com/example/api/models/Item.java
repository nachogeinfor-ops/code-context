package com.example.api.models;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.Objects;

/**
 * Item — JPA entity owned by a {@link User} and persisted in the
 * {@code items} table.
 *
 * <p>Items have an {@code ownerId} foreign key to the user table; service-layer
 * code enforces "owner can read/write, others cannot" via
 * {@link #isOwnedBy(Long)}.
 */
@Entity
@Table(name = "items")
public class Item {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "owner_id", nullable = false)
    private Long ownerId;

    @Column(nullable = false)
    private String title;

    @Column(length = 2000)
    private String description;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    public Item() {
    }

    public Item(Long ownerId, String title, String description) {
        this.ownerId = ownerId;
        this.title = title;
        this.description = description;
        this.createdAt = Instant.now();
    }

    /**
     * isOwnedBy reports whether this item belongs to the given user id.
     */
    public boolean isOwnedBy(Long userId) {
        return ownerId != null && ownerId.equals(userId);
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getOwnerId() {
        return ownerId;
    }

    public void setOwnerId(Long ownerId) {
        this.ownerId = ownerId;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Item item)) return false;
        return Objects.equals(id, item.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }
}
