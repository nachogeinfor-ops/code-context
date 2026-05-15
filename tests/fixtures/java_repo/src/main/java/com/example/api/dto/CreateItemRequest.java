package com.example.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * CreateItemRequest — DTO for POST /api/items.
 *
 * <p>{@code title} is required and validated; {@code description} is
 * optional with a generous upper bound. The authenticated user id is
 * pulled from the SecurityContext by the controller, so it is NOT
 * part of this body.
 */
public class CreateItemRequest {

    @NotBlank
    @Size(min = 1, max = 200)
    private String title;

    @Size(max = 2000)
    private String description;

    public CreateItemRequest() {
    }

    public CreateItemRequest(String title, String description) {
        this.title = title;
        this.description = description;
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
