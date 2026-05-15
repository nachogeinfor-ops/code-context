#pragma once

#include <cstdint>
#include <string>

namespace api {

/**
 * User is the canonical domain model for an account row. It carries
 * the password_hash so services can do bcrypt comparisons; DTOs never
 * leak the hash to the wire.
 */
struct User {
    std::int64_t id;
    std::string email;
    std::string username;
    std::string password_hash;
    std::int64_t created_at;  // unix seconds

    /**
     * is_persisted returns true once the repository assigns an
     * auto-incremented primary key.
     */
    [[nodiscard]] bool is_persisted() const noexcept { return id > 0; }
};

}  // namespace api
