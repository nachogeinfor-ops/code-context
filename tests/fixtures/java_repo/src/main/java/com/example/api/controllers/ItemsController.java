package com.example.api.controllers;

import com.example.api.dto.CreateItemRequest;
import com.example.api.dto.ItemResponse;
import com.example.api.dto.UpdateItemRequest;
import com.example.api.middleware.AuthenticatedUser;
import com.example.api.services.ItemService;
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
 * ItemsController — CRUD endpoints for {@code /api/items}.
 *
 * <p>Every endpoint here is scoped to the authenticated user; the
 * {@link AuthenticatedUser} resolver pulls the user id out of the
 * security context, so handler signatures stay clean.
 */
@RestController
@RequestMapping("/api/items")
public class ItemsController {

    private final ItemService itemService;

    public ItemsController(ItemService itemService) {
        this.itemService = itemService;
    }

    /**
     * createItem handles POST /api/items. The owner_id is taken from
     * the authenticated user, never the request body.
     */
    @PostMapping
    public ResponseEntity<ItemResponse> createItem(
        @AuthenticatedUser Long ownerId,
        @Valid @RequestBody CreateItemRequest request
    ) {
        ItemResponse created = itemService.createItem(ownerId, request);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }

    /**
     * getItemById handles GET /api/items/{id}. Returns 403 if the item
     * is not owned by the authenticated user.
     */
    @GetMapping("/{id}")
    public ResponseEntity<ItemResponse> getItemById(
        @AuthenticatedUser Long ownerId,
        @PathVariable Long id
    ) {
        return ResponseEntity.ok(itemService.getItemById(ownerId, id));
    }

    /**
     * listItems handles GET /api/items. Returns items owned by the
     * authenticated user, paginated.
     */
    @GetMapping
    public ResponseEntity<List<ItemResponse>> listItems(
        @AuthenticatedUser Long ownerId,
        @RequestParam(defaultValue = "0") int page,
        @RequestParam(defaultValue = "20") int pageSize
    ) {
        List<ItemResponse> rows = itemService.listItems(ownerId, page, pageSize);
        return ResponseEntity.ok(rows);
    }

    /**
     * updateItem handles PATCH /api/items/{id}.
     */
    @PatchMapping("/{id}")
    public ResponseEntity<ItemResponse> updateItem(
        @AuthenticatedUser Long ownerId,
        @PathVariable Long id,
        @Valid @RequestBody UpdateItemRequest patch
    ) {
        ItemResponse updated = itemService.updateItem(ownerId, id, patch);
        return ResponseEntity.ok(updated);
    }

    /**
     * deleteItem handles DELETE /api/items/{id}. Returns 204 on success.
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteItem(
        @AuthenticatedUser Long ownerId,
        @PathVariable Long id
    ) {
        itemService.deleteItem(ownerId, id);
        return ResponseEntity.noContent().build();
    }
}
