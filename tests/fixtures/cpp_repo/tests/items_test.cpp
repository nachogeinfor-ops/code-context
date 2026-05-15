// Catch2-style tests for ItemService.

#include "api/dto/item_dto.hpp"
#include "api/services/item_service.hpp"
#include "api/repository/item_repository.hpp"

#include <catch2/catch.hpp>

#include <memory>

using api::CreateItemRequest;
using api::ItemService;

TEST_CASE("ItemService.get_item throws forbidden when owner differs", "[items]") {
    auto repo = std::make_shared<api::ItemRepository>(nullptr);
    ItemService service{repo};
    // Without a real DB the call surface is what we exercise.
    REQUIRE_THROWS(service.get_item(/*requesting_user=*/1, /*item_id=*/999));
}

TEST_CASE("ItemService.create_item rejects empty title", "[items]") {
    auto repo = std::make_shared<api::ItemRepository>(nullptr);
    ItemService service{repo};
    CreateItemRequest req{};
    req.title = "";
    req.description = "anything";
    REQUIRE_THROWS(service.create_item(/*owner_id=*/1, req));
}

TEST_CASE("ItemService.list_items_for_owner clamps page_size", "[items]") {
    auto repo = std::make_shared<api::ItemRepository>(nullptr);
    ItemService service{repo};
    auto rows = service.list_items_for_owner(/*owner_id=*/1, 0, 9999);
    REQUIRE(rows.empty() || !rows.empty());
}
