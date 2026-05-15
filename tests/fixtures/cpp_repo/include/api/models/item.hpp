#pragma once

#include <cstdint>
#include <string>

namespace api {

/**
 * Item is the canonical domain entity for a user-owned record. The
 * owner_id refers to User::id and is used by the repository and
 * services to enforce ownership-scoped queries.
 */
struct Item {
    std::int64_t id;
    std::int64_t owner_id;
    std::string title;
    std::string description;
    std::int64_t created_at;  // unix seconds

    /**
     * is_owned_by returns true when the supplied user owns the item.
     */
    [[nodiscard]] bool is_owned_by(std::int64_t user_id) const noexcept {
        return owner_id == user_id;
    }
};

}  // namespace api
