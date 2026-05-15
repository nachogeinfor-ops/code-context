#pragma once

#include <nlohmann/json.hpp>

#include <cstdint>
#include <string>

namespace api {

/**
 * LoginRequest is the JSON body posted to /api/auth/login. Both fields
 * are required; the handler validates non-emptiness before delegating
 * to AuthService.
 */
struct LoginRequest {
    std::string email;
    std::string password;

    /**
     * from_json parses a JSON object into a LoginRequest, throwing
     * ApiError::bad_request when required fields are missing.
     */
    [[nodiscard]] static LoginRequest from_json(const nlohmann::json& body);
};

/**
 * RefreshRequest is the body for /api/auth/refresh. The refresh_token
 * is the long-lived JWT issued at login time.
 */
struct RefreshRequest {
    std::string refresh_token;

    [[nodiscard]] static RefreshRequest from_json(const nlohmann::json& body);
};

/**
 * TokenResponse is the response envelope returned by login and
 * refresh. Carries both the short-lived access token and the
 * long-lived refresh token plus an expires_in hint for clients.
 */
struct TokenResponse {
    std::string access_token;
    std::string refresh_token;
    std::uint32_t expires_in_seconds;
    std::string token_type;  // always "Bearer"

    /**
     * to_json serializes the response into a JSON object suitable for
     * httplib::Response::set_content.
     */
    [[nodiscard]] nlohmann::json to_json() const;
};

}  // namespace api
