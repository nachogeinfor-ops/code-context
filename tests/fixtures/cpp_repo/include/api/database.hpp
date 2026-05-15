#pragma once

#include <memory>
#include <mutex>
#include <string>
#include <string_view>

struct sqlite3;
struct sqlite3_stmt;

namespace api {

/**
 * Database wraps a single SQLite connection and serializes prepared
 * statement execution behind a mutex so the rest of the codebase can
 * pretend the connection is thread-safe. The connection is closed in
 * the destructor.
 */
class Database {
public:
    explicit Database(std::string_view database_path);
    ~Database();

    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    /**
     * migrate runs the schema bootstrap statements idempotently. Creates
     * the users and items tables if they do not exist.
     */
    void migrate();

    /**
     * prepare compiles a SQL statement and returns the raw handle. The
     * caller takes ownership and must call sqlite3_finalize.
     */
    [[nodiscard]] sqlite3_stmt* prepare(std::string_view sql);

    /**
     * exec runs a one-shot SQL statement (typically DDL). Throws on
     * non-OK return codes.
     */
    void exec(std::string_view sql);

    /**
     * last_insert_rowid returns the auto-generated id of the most
     * recently inserted row on this connection.
     */
    [[nodiscard]] long long last_insert_rowid() const;

    /**
     * mutex returns the per-connection mutex callers should lock before
     * executing prepared statements.
     */
    [[nodiscard]] std::mutex& mutex() { return mutex_; }

private:
    sqlite3* handle_;
    mutable std::mutex mutex_;
};

}  // namespace api
