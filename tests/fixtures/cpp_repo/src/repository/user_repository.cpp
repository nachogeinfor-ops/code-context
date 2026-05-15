#include "api/repository/user_repository.hpp"

#include "api/database.hpp"
#include "api/error/api_error.hpp"

#include <sqlite3.h>

#include <mutex>
#include <string>
#include <utility>

namespace api {

namespace {

User row_to_user(sqlite3_stmt* stmt) {
    User out{};
    out.id = sqlite3_column_int64(stmt, 0);
    out.email = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    out.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
    out.password_hash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
    out.created_at = sqlite3_column_int64(stmt, 4);
    return out;
}

void bind_text(sqlite3_stmt* stmt, int idx, std::string_view value) {
    sqlite3_bind_text(stmt, idx, value.data(), static_cast<int>(value.size()),
                      SQLITE_TRANSIENT);
}

}  // namespace

UserRepository::UserRepository(std::shared_ptr<Database> db) : db_(std::move(db)) {}

User UserRepository::save(const User& user) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "INSERT INTO users(email, username, password_hash, created_at) "
        "VALUES(?, ?, ?, ?);");
    bind_text(stmt, 1, user.email);
    bind_text(stmt, 2, user.username);
    bind_text(stmt, 3, user.password_hash);
    sqlite3_bind_int64(stmt, 4, user.created_at);
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if (rc != SQLITE_DONE) {
        throw ApiError::conflict("could not insert user (email may be taken)");
    }
    User saved = user;
    saved.id = db_->last_insert_rowid();
    return saved;
}

User UserRepository::update(const User& user) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "UPDATE users SET email = ?, username = ?, password_hash = ? "
        "WHERE id = ?;");
    bind_text(stmt, 1, user.email);
    bind_text(stmt, 2, user.username);
    bind_text(stmt, 3, user.password_hash);
    sqlite3_bind_int64(stmt, 4, user.id);
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if (rc != SQLITE_DONE) {
        throw ApiError::internal("could not update user");
    }
    return user;
}

std::optional<User> UserRepository::find_by_id(std::int64_t id) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "SELECT id, email, username, password_hash, created_at "
        "FROM users WHERE id = ?;");
    sqlite3_bind_int64(stmt, 1, id);
    std::optional<User> out;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        out = row_to_user(stmt);
    }
    sqlite3_finalize(stmt);
    return out;
}

std::optional<User> UserRepository::find_by_email(std::string_view email) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "SELECT id, email, username, password_hash, created_at "
        "FROM users WHERE email = ?;");
    bind_text(stmt, 1, email);
    std::optional<User> out;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        out = row_to_user(stmt);
    }
    sqlite3_finalize(stmt);
    return out;
}

bool UserRepository::exists_by_email(std::string_view email) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare("SELECT 1 FROM users WHERE email = ? LIMIT 1;");
    bind_text(stmt, 1, email);
    bool exists = sqlite3_step(stmt) == SQLITE_ROW;
    sqlite3_finalize(stmt);
    return exists;
}

bool UserRepository::exists_by_id(std::int64_t id) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare("SELECT 1 FROM users WHERE id = ? LIMIT 1;");
    sqlite3_bind_int64(stmt, 1, id);
    bool exists = sqlite3_step(stmt) == SQLITE_ROW;
    sqlite3_finalize(stmt);
    return exists;
}

std::vector<User> UserRepository::find_all_paged(int page, int page_size) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare(
        "SELECT id, email, username, password_hash, created_at "
        "FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?;");
    sqlite3_bind_int(stmt, 1, page_size);
    sqlite3_bind_int(stmt, 2, page * page_size);
    std::vector<User> out;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        out.push_back(row_to_user(stmt));
    }
    sqlite3_finalize(stmt);
    return out;
}

void UserRepository::delete_by_id(std::int64_t id) {
    std::lock_guard<std::mutex> lock{db_->mutex()};
    sqlite3_stmt* stmt = db_->prepare("DELETE FROM users WHERE id = ?;");
    sqlite3_bind_int64(stmt, 1, id);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
}

}  // namespace api
