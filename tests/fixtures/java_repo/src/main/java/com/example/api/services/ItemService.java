package com.example.api.services;

import com.example.api.dto.CreateItemRequest;
import com.example.api.dto.ItemResponse;
import com.example.api.dto.UpdateItemRequest;
import com.example.api.exceptions.ApiException;
import com.example.api.models.Item;
import com.example.api.repositories.ItemRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;

/**
 * ItemService — CRUD operations for {@link Item} aggregates.
 *
 * <p>Every read and write enforces ownership: items only come back to
 * the user who owns them, and {@code update}/{@code delete} on someone
 * else's item returns 403 Forbidden.
 */
@Service
public class ItemService {

    private static final int MAX_PAGE_SIZE = 100;

    private final ItemRepository itemRepository;

    public ItemService(ItemRepository itemRepository) {
        this.itemRepository = itemRepository;
    }

    /**
     * createItem persists a new item owned by the supplied user.
     */
    @Transactional
    public ItemResponse createItem(Long ownerId, CreateItemRequest request) {
        Item item = new Item(ownerId, request.getTitle(), request.getDescription());
        Item saved = itemRepository.save(item);
        return ItemResponse.fromEntity(saved);
    }

    /**
     * getItemById fetches a single item and enforces ownership.
     */
    public ItemResponse getItemById(Long ownerId, Long itemId) {
        Item item = loadOwned(ownerId, itemId);
        return ItemResponse.fromEntity(item);
    }

    /**
     * listItems returns a page of items owned by the given user.
     */
    public List<ItemResponse> listItems(Long ownerId, int page, int pageSize) {
        int safePage = Math.max(0, page);
        int safeSize = Math.min(MAX_PAGE_SIZE, Math.max(1, pageSize));
        Pageable pageable = PageRequest.of(safePage, safeSize);
        Page<Item> rows = itemRepository.findByOwnerId(ownerId, pageable);
        return rows.stream().map(ItemResponse::fromEntity).toList();
    }

    /**
     * updateItem applies the non-null fields of {@code patch} to an owned item.
     */
    @Transactional
    public ItemResponse updateItem(Long ownerId, Long itemId, UpdateItemRequest patch) {
        Item item = loadOwned(ownerId, itemId);
        if (patch.getTitle() != null) {
            item.setTitle(patch.getTitle());
        }
        if (patch.getDescription() != null) {
            item.setDescription(patch.getDescription());
        }
        return ItemResponse.fromEntity(item);
    }

    /**
     * deleteItem removes an owned item or 404/403s.
     */
    @Transactional
    public void deleteItem(Long ownerId, Long itemId) {
        int affected = itemRepository.deleteByIdAndOwnerId(itemId, ownerId);
        if (affected == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "item not found");
        }
    }

    /**
     * loadOwned fetches an item and verifies the supplied user owns it.
     * Throws 404 when the item is missing, 403 when ownership mismatches.
     */
    private Item loadOwned(Long ownerId, Long itemId) {
        Item item = itemRepository.findById(itemId)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "item not found"));
        if (!item.isOwnedBy(ownerId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "forbidden");
        }
        return item;
    }
}
