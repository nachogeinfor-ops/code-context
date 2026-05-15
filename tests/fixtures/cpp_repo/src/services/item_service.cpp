#include "api/services/item_service.hpp"

#include "api/error/api_error.hpp"
#include "api/repository/item_repository.hpp"

#include <algorithm>
#include <chrono>
#include <utility>

namespace api {

namespace {

std::int64_t now_seconds() {
    using namespace std::chrono;
    return duration_cast<seconds>(system_clock::now().time_since_epoch()).count();
}

}  // namespace

ItemService::ItemService(std::shared_ptr<ItemRepository> items)
    : items_(std::move(items)) {}

ItemResponse ItemService::create_item(std::int64_t owner_id,
                                      const CreateItemRequest& request) {
    if (request.title.empty()) {
        throw ApiError::bad_request("title must not be empty");
    }
    Item item{};
    item.owner_id = owner_id;
    item.title = request.title;
    item.description = request.description;
    item.created_at = now_seconds();
    Item saved = items_->save(item);
    return ItemResponse::from_entity(saved);
}

ItemResponse ItemService::get_item(std::int64_t requesting_user,
                                   std::int64_t item_id) {
    auto item = items_->find_by_id(item_id);
    if (!item.has_value()) {
        throw ApiError::not_found("item not found");
    }
    if (!item->is_owned_by(requesting_user)) {
        throw ApiError::forbidden("item is owned by another user");
    }
    return ItemResponse::from_entity(*item);
}

std::vector<ItemResponse> ItemService::list_items_for_owner(
    std::int64_t owner_id, int page, int page_size) {
    int safe_page = std::max(0, page);
    int safe_size = std::clamp(page_size, 1, kMaxPageSize);
    auto rows = items_->find_by_owner(owner_id, safe_page, safe_size);
    std::vector<ItemResponse> out;
    out.reserve(rows.size());
    for (const auto& item : rows) {
        out.push_back(ItemResponse::from_entity(item));
    }
    return out;
}

ItemResponse ItemService::update_item(std::int64_t requesting_user,
                                      std::int64_t item_id,
                                      const UpdateItemRequest& patch) {
    auto item = items_->find_by_id(item_id);
    if (!item.has_value()) {
        throw ApiError::not_found("item not found");
    }
    if (!item->is_owned_by(requesting_user)) {
        throw ApiError::forbidden("item is owned by another user");
    }
    if (patch.title.has_value()) {
        item->title = *patch.title;
    }
    if (patch.description.has_value()) {
        item->description = *patch.description;
    }
    Item saved = items_->update(*item);
    return ItemResponse::from_entity(saved);
}

void ItemService::delete_item(std::int64_t requesting_user, std::int64_t item_id) {
    auto item = items_->find_by_id(item_id);
    if (!item.has_value()) {
        throw ApiError::not_found("item not found");
    }
    if (!item->is_owned_by(requesting_user)) {
        throw ApiError::forbidden("item is owned by another user");
    }
    items_->delete_by_id(item_id);
}

}  // namespace api
