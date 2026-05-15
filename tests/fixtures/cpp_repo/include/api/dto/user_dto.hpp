#pragma once

#include "api/models/user.hpp"

#include <nlohmann/json.hpp>

#include <optional>
#include <string>

namespace api {

/**
 * CreateUserRequest is the JSON body for POST /api/users. Validation
 * lives in from_json: email must contain '@', username/password must
 * be non-empty.
 */
struct CreateUserRequest {
    std::string email;
    std::string username;
    std::string password;

    [[nodiscard]] static CreateUserRequest from_json(const nlohmann::json& body);
};

/**
 * UpdateUserRequest is the JSON body for PATCH /api/users/{id}. Every
 * field is optional; the service only touches fields that are present.
 */
struct UpdateUserRequest {
    std::optional<std::string> email;
    std::optional<std::string> username;
    std::optional<std::string> password;

    [[nodiscard]] static UpdateUserRequest from_json(const nlohmann::json& body);
};

/**
 * UserResponse is the publicly-visible shape of a user. Notably, it
 * never contains password_hash.
 */
struct UserResponse {
    std::int64_t id;
    std::string email;
    std::string username;
    std::int64_t created_at;

    /**
     * from_entity copies the public fields from a User domain model
     * onto a wire DTO.
     */
    [[nodiscard]] static UserResponse from_entity(const User& user);

    [[nodiscard]] nlohmann::json to_json() const;
};

}  // namespace api
