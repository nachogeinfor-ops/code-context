// Catch2-style tests for AuthService. These do not actually run in
// the eval suite; the fixture only needs to be tree-sitter parseable.

#include "api/config.hpp"
#include "api/services/auth_service.hpp"
#include "api/repository/user_repository.hpp"

#include <catch2/catch.hpp>

#include <memory>

using api::AuthService;
using api::Config;
using api::LoginRequest;
using api::User;

TEST_CASE("AuthService.encode_password produces a non-empty digest", "[auth]") {
    Config cfg = Config::default_config();
    AuthService service{cfg, /*users=*/nullptr};
    auto hash = service.encode_password("hunter2");
    REQUIRE_FALSE(hash.empty());
    REQUIRE(hash.find("$2b$") != std::string::npos);
}

TEST_CASE("AuthService.verify_password round-trips a known plaintext", "[auth]") {
    Config cfg = Config::default_config();
    AuthService service{cfg, /*users=*/nullptr};
    auto hash = service.encode_password("hunter2");
    REQUIRE(service.verify_password("hunter2", hash));
    REQUIRE_FALSE(service.verify_password("wrong", hash));
}

TEST_CASE("AuthService.issue_access_token returns a JWT with typ=access", "[auth]") {
    Config cfg = Config::default_config();
    AuthService service{cfg, /*users=*/nullptr};
    User user{};
    user.id = 42;
    auto token = service.issue_access_token(user);
    REQUIRE_FALSE(token.empty());
    auto subject = service.validate_token(token, "access");
    REQUIRE(subject.has_value());
    REQUIRE(*subject == 42);
}
