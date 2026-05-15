#include "api/database.hpp"

#include "api/error/api_error.hpp"

#include <sqlite3.h>

#include <stdexcept>
#include <string>

namespace api {

namespace {

constexpr const char* kCreateUsersTable = R"sql(
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
)sql";

constexpr const char* kCreateItemsTable = R"sql(
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    created_at INTEGER NOT NULL
);
)sql";

constexpr const char* kCreateItemsIndex =
    "CREATE INDEX IF NOT EXISTS idx_items_owner ON items(owner_id);";

}  // namespace

Database::Database(std::string_view database_path) : handle_(nullptr) {
    std::string path{database_path};
    int rc = sqlite3_open(path.c_str(), &handle_);
    if (rc != SQLITE_OK) {
        std::string message = "sqlite open failed: ";
        message += sqlite3_errmsg(handle_);
        sqlite3_close(handle_);
        handle_ = nullptr;
        throw ApiError::internal(message);
    }
    sqlite3_busy_timeout(handle_, 5000);
}

Database::~Database() {
    if (handle_ != nullptr) {
        sqlite3_close(handle_);
        handle_ = nullptr;
    }
}

void Database::migrate() {
    exec(kCreateUsersTable);
    exec(kCreateItemsTable);
    exec(kCreateItemsIndex);
}

sqlite3_stmt* Database::prepare(std::string_view sql) {
    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(handle_, sql.data(), static_cast<int>(sql.size()),
                                &stmt, nullptr);
    if (rc != SQLITE_OK) {
        throw ApiError::internal(std::string{"sqlite prepare failed: "} +
                                 sqlite3_errmsg(handle_));
    }
    return stmt;
}

void Database::exec(std::string_view sql) {
    char* err_msg = nullptr;
    std::string statement{sql};
    int rc = sqlite3_exec(handle_, statement.c_str(), nullptr, nullptr, &err_msg);
    if (rc != SQLITE_OK) {
        std::string message = "sqlite exec failed: ";
        if (err_msg != nullptr) {
            message += err_msg;
            sqlite3_free(err_msg);
        }
        throw ApiError::internal(message);
    }
}

long long Database::last_insert_rowid() const {
    return sqlite3_last_insert_rowid(handle_);
}

}  // namespace api
