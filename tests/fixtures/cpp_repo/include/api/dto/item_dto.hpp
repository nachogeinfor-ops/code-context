#pragma once

#include "api/models/item.hpp"

#include <nlohmann/json.hpp>

#include <optional>
#include <string>

namespace api {

/**
 * CreateItemRequest is the JSON body for POST /api/items. The owner_id
 * comes from the authenticated principal, not from the request body.
 */
struct CreateItemRequest {
    std::string title;
    std::string description;

    [[nodiscard]] static CreateItemRequest from_json(const nlohmann::json& body);
};

/**
 * UpdateItemRequest is the JSON body for PATCH /api/items/{id}. Both
 * fields are optional so the service can apply a partial patch.
 */
struct UpdateItemRequest {
    std::optional<std::string> title;
    std::optional<std::string> description;

    [[nodiscard]] static UpdateItemRequest from_json(const nlohmann::json& body);
};

/**
 * ItemResponse is the wire shape returned for any item read endpoint.
 * Includes the owner_id so clients can render ownership chips.
 */
struct ItemResponse {
    std::int64_t id;
    std::int64_t owner_id;
    std::string title;
    std::string description;
    std::int64_t created_at;

    [[nodiscard]] static ItemResponse from_entity(const Item& item);
    [[nodiscard]] nlohmann::json to_json() const;
};

}  // namespace api
