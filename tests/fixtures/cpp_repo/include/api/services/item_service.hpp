#pragma once

#include "api/dto/item_dto.hpp"

#include <cstdint>
#include <memory>
#include <vector>

namespace api {

class ItemRepository;

/**
 * ItemService implements the CRUD use cases for Item aggregates and
 * enforces owner_id-scoped visibility. The HTTP layer always passes
 * the authenticated user id; this service translates "not yours" into
 * a 403 instead of a 404.
 */
class ItemService {
public:
    explicit ItemService(std::shared_ptr<ItemRepository> items);

    /**
     * create_item persists a new item owned by the supplied user.
     */
    [[nodiscard]] ItemResponse create_item(std::int64_t owner_id,
                                           const CreateItemRequest& request);

    /**
     * get_item returns the item with the given id, but only if it is
     * owned by `requesting_user`. Throws 403 otherwise.
     */
    [[nodiscard]] ItemResponse get_item(std::int64_t requesting_user,
                                        std::int64_t item_id);

    /**
     * list_items_for_owner returns a clamped page of items owned by
     * the requesting user.
     */
    [[nodiscard]] std::vector<ItemResponse> list_items_for_owner(
        std::int64_t owner_id, int page, int page_size);

    /**
     * update_item applies the supplied patch only if the requesting
     * user owns the item; otherwise throws 403.
     */
    [[nodiscard]] ItemResponse update_item(std::int64_t requesting_user,
                                           std::int64_t item_id,
                                           const UpdateItemRequest& patch);

    /**
     * delete_item removes the item, enforcing ownership.
     */
    void delete_item(std::int64_t requesting_user, std::int64_t item_id);

private:
    static constexpr int kMaxPageSize = 100;

    std::shared_ptr<ItemRepository> items_;
};

}  // namespace api
