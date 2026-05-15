#include "api/repository/item_repository.hpp"

#include "api/database.hpp"
#include "api/error/api_error.hpp"

#include <sqlite3.h>

#include <mutex>
#include <string>
#include <utility>

namespace api {

namespace {

Item row_to_item(sqlite3_stmt* stmt) {
    Item out{};
    out.id = sqlite3_column_int64(stmt, 0);
    out.owner_id = sqlite3_column_int64(stmt, 1);
    out.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
    if (auto* desc = sqlite3_column_text(stmt, 3); desc != nullptr) {
        out.description = reinterpret_cast<const char*>(desc);
    }
    out.created_at = sqlite3_column_int64(stmt, 4);
    return out;
}

void bind_text(sqlite3_stmt* stmt, int idx, std::string_view value) {
    sqlite3_bind_text(stmt, idx, value.data(), static_cast<int>(value.size()),
                      SQLITE_TRANSIENT);
}

}  // namespace

ItemRepository::ItemRepository(std::shared_ptr<Database> db) : db_(std::move(db)) {}

Item ItemRepository::save(const Item& item) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "INSERT INTO items(owner_id, title, description, created_at) "
        "VALUES(?, ?, ?, ?);");
    sqlite3_bind_int64(stmt, 1, item.owner_id);
    bind_text(stmt, 2, item.title);
    bind_text(stmt, 3, item.description);
    sqlite3_bind_int64(stmt, 4, item.created_at);
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if (rc != SQLITE_DONE) {
        throw ApiError::internal("could not insert item");
    }
    Item saved = item;
    saved.id = db_->last_insert_rowid();
    return saved;
}

Item ItemRepository::update(const Item& item) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "UPDATE items SET title = ?, description = ? WHERE id = ?;");
    bind_text(stmt, 1, item.title);
    bind_text(stmt, 2, item.description);
    sqlite3_bind_int64(stmt, 3, item.id);
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if (rc != SQLITE_DONE) {
        throw ApiError::internal("could not update item");
    }
    return item;
}

std::optional<Item> ItemRepository::find_by_id(std::int64_t id) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "SELECT id, owner_id, title, description, created_at "
        "FROM items WHERE id = ?;");
    sqlite3_bind_int64(stmt, 1, id);
    std::optional<Item> out;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        out = row_to_item(stmt);
    }
    sqlite3_finalize(stmt);
    return out;
}

std::vector<Item> ItemRepository::find_by_owner(std::int64_t owner_id,
                                                int page, int page_size) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "SELECT id, owner_id, title, description, created_at "
        "FROM items WHERE owner_id = ? "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?;");
    sqlite3_bind_int64(stmt, 1, owner_id);
    sqlite3_bind_int(stmt, 2, page_size);
    sqlite3_bind_int(stmt, 3, page * page_size);
    std::vector<Item> out;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        out.push_back(row_to_item(stmt));
    }
    sqlite3_finalize(stmt);
    return out;
}

void ItemRepository::delete_by_id(std::int64_t id) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare("DELETE FROM items WHERE id = ?;");
    sqlite3_bind_int64(stmt, 1, id);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
}

std::int64_t ItemRepository::count_by_owner(std::int64_t owner_id) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "SELECT COUNT(*) FROM items WHERE owner_id = ?;");
    sqlite3_bind_int64(stmt, 1, owner_id);
    std::int64_t count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = sqlite3_column_int64(stmt, 0);
    }
    sqlite3_finalize(stmt);
    return count;
}

}  // namespace api
