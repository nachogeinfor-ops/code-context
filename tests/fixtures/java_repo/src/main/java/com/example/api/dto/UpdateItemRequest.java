package com.example.api.dto;

import jakarta.validation.constraints.Size;

/**
 * UpdateItemRequest — partial-update DTO for PATCH /api/items/{id}.
 *
 * <p>Optional title and description; nulls mean "do not change."
 * Ownership is re-checked in the service layer before any field is
 * applied.
 */
public class UpdateItemRequest {

    @Size(min = 1, max = 200)
    private String title;

    @Size(max = 2000)
    private String description;

    public UpdateItemRequest() {
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
}
