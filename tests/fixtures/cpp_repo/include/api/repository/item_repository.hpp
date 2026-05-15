#pragma once

#include "api/models/item.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace api {

class Database;

/**
 * ItemRepository encapsulates the items table. All queries that
 * return more than one row scope by owner_id so that a forgotten
 * ownership check at the service layer can't leak data across users.
 */
class ItemRepository {
public:
    explicit ItemRepository(std::shared_ptr<Database> db);

    /**
     * save inserts a new item row and returns the row populated with
     * the auto-generated id.
     */
    [[nodiscard]] Item save(const Item& item);

    /**
     * update writes the title and description columns for an existing
     * item; ownership is enforced at the service layer.
     */
    [[nodiscard]] Item update(const Item& item);

    /**
     * find_by_id is the only single-row read; it does not filter by
     * owner because the service layer needs the row to decide between
     * 403 and 404.
     */
    [[nodiscard]] std::optional<Item> find_by_id(std::int64_t id);

    /**
     * find_by_owner returns a page of items belonging to one user,
     * ordered by created_at descending.
     */
    [[nodiscard]] std::vector<Item> find_by_owner(std::int64_t owner_id,
                                                  int page, int page_size);

    /**
     * delete_by_id removes the item with the given primary key. The
     * service layer must have already enforced ownership.
     */
    void delete_by_id(std::int64_t id);

    /**
     * count_by_owner returns the number of items owned by a given
     * user. Useful for paginator hints.
     */
    [[nodiscard]] std::int64_t count_by_owner(std::int64_t owner_id);

private:
    std::shared_ptr<Database> db_;
};

}  // namespace api
