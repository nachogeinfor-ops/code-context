#pragma once

#include "api/config.hpp"
#include "api/dto/auth_dto.hpp"
#include "api/models/user.hpp"

#include <memory>
#include <optional>
#include <string>
#include <string_view>

namespace api {

class UserRepository;

/**
 * AuthService owns the auth machinery: bcrypt password hashing, JWT
 * issuance, JWT verification, and refresh-token exchange. It is
 * deliberately decoupled from the HTTP layer so it can be unit-tested
 * without spinning up a server.
 */
class AuthService {
public:
    AuthService(Config config, std::shared_ptr<UserRepository> users);

    /**
     * encode_password hashes a plaintext password with bcrypt at the
     * configured work factor and returns the encoded digest.
     */
    [[nodiscard]] std::string encode_password(std::string_view plaintext) const;

    /**
     * verify_password returns true iff the bcrypt hash matches the
     * plaintext candidate.
     */
    [[nodiscard]] bool verify_password(std::string_view plaintext,
                                       std::string_view hash) const;

    /**
     * login authenticates an email + password pair against the user
     * repository and returns access/refresh tokens. Throws
     * ApiError::unauthorized on failure.
     */
    [[nodiscard]] TokenResponse login(const LoginRequest& request);

    /**
     * refresh exchanges a still-valid refresh token for a brand-new
     * access token + refresh token pair (rotation).
     */
    [[nodiscard]] TokenResponse refresh(const RefreshRequest& request);

    /**
     * issue_access_token signs a short-lived JWT with the subject set
     * to the user's primary key and a `typ=access` claim.
     */
    [[nodiscard]] std::string issue_access_token(const User& user) const;

    /**
     * issue_refresh_token signs a long-lived JWT with `typ=refresh`.
     */
    [[nodiscard]] std::string issue_refresh_token(const User& user) const;

    /**
     * validate_token parses, verifies the signature, checks expiry and
     * the expected token type ("access" or "refresh"), and returns the
     * subject (user id). Returns std::nullopt on any failure.
     */
    [[nodiscard]] std::optional<std::int64_t> validate_token(
        std::string_view token, std::string_view expected_type) const;

private:
    Config config_;
    std::shared_ptr<UserRepository> users_;
};

}  // namespace api
