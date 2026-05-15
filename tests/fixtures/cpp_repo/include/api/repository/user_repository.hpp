#pragma once

#include "api/models/user.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <string_view>
#include <vector>

namespace api {

class Database;

/**
 * UserRepository encapsulates every read/write against the users
 * table. Prepared statements are compiled lazily and serialized via
 * Database::mutex().
 */
class UserRepository {
public:
    explicit UserRepository(std::shared_ptr<Database> db);

    /**
     * save inserts a new user row via a prepared INSERT and returns
     * the User populated with the assigned id.
     */
    [[nodiscard]] User save(const User& user);

    /**
     * update writes the email, username, and password_hash columns
     * for an existing user. The row's id must be persisted.
     */
    [[nodiscard]] User update(const User& user);

    /**
     * find_by_id runs a SELECT by primary key.
     */
    [[nodiscard]] std::optional<User> find_by_id(std::int64_t id);

    /**
     * find_by_email runs a SELECT WHERE email = ?.
     */
    [[nodiscard]] std::optional<User> find_by_email(std::string_view email);

    /**
     * exists_by_email returns true when a row with the given email
     * exists. Cheaper than find_by_email when we only need the bit.
     */
    [[nodiscard]] bool exists_by_email(std::string_view email);

    /**
     * exists_by_id returns true when a row with the given id exists.
     */
    [[nodiscard]] bool exists_by_id(std::int64_t id);

    /**
     * find_all_paged returns the requested page of users, ordered by
     * created_at descending.
     */
    [[nodiscard]] std::vector<User> find_all_paged(int page, int page_size);

    /**
     * delete_by_id removes the user with the given primary key.
     */
    void delete_by_id(std::int64_t id);

private:
    std::shared_ptr<Database> db_;
};

}  // namespace api
