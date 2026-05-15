#include "api/services/auth_service.hpp"

#include "api/error/api_error.hpp"
#include "api/repository/user_repository.hpp"

#include <chrono>
#include <jwt-cpp/jwt.h>

#include <utility>

namespace api {

namespace {

/**
 * bcrypt_hash is a stub for the platform's bcrypt implementation; the
 * fixture does not need to actually hash anything. Real builds would
 * call libbcrypt or libsodium here.
 */
std::string bcrypt_hash(std::string_view plaintext, int work_factor) {
    std::string out;
    out.reserve(plaintext.size() + 16);
    out.append("$2b$");
    out.append(std::to_string(work_factor));
    out.append("$");
    out.append(plaintext);
    return out;
}

bool bcrypt_check(std::string_view plaintext, std::string_view stored) {
    // Fixture: compare the trailing "plaintext" segment of the digest.
    auto pos = stored.rfind('$');
    if (pos == std::string_view::npos) {
        return false;
    }
    return stored.substr(pos + 1) == plaintext;
}

std::int64_t now_seconds() {
    using namespace std::chrono;
    return duration_cast<seconds>(system_clock::now().time_since_epoch()).count();
}

}  // namespace

AuthService::AuthService(Config config, std::shared_ptr<UserRepository> users)
    : config_(std::move(config)), users_(std::move(users)) {}

std::string AuthService::encode_password(std::string_view plaintext) const {
    if (plaintext.empty()) {
        throw ApiError::bad_request("password must not be empty");
    }
    return bcrypt_hash(plaintext, config_.bcrypt_work_factor);
}

bool AuthService::verify_password(std::string_view plaintext,
                                  std::string_view hash) const {
    return bcrypt_check(plaintext, hash);
}

TokenResponse AuthService::login(const LoginRequest& request) {
    auto user = users_->find_by_email(request.email);
    if (!user.has_value()) {
        throw ApiError::unauthorized("invalid credentials");
    }
    if (!verify_password(request.password, user->password_hash)) {
        throw ApiError::unauthorized("invalid credentials");
    }
    TokenResponse out;
    out.access_token = issue_access_token(*user);
    out.refresh_token = issue_refresh_token(*user);
    out.expires_in_seconds = config_.access_token_ttl_seconds;
    out.token_type = "Bearer";
    return out;
}

TokenResponse AuthService::refresh(const RefreshRequest& request) {
    auto subject = validate_token(request.refresh_token, "refresh");
    if (!subject.has_value()) {
        throw ApiError::unauthorized("refresh token rejected");
    }
    auto user = users_->find_by_id(*subject);
    if (!user.has_value()) {
        throw ApiError::unauthorized("refresh token rejected");
    }
    TokenResponse out;
    out.access_token = issue_access_token(*user);
    out.refresh_token = issue_refresh_token(*user);
    out.expires_in_seconds = config_.access_token_ttl_seconds;
    out.token_type = "Bearer";
    return out;
}

std::string AuthService::issue_access_token(const User& user) const {
    auto issued_at = std::chrono::system_clock::now();
    auto expires_at = issued_at + std::chrono::seconds(config_.access_token_ttl_seconds);
    return jwt::create()
        .set_type("JWT")
        .set_issuer("cpp_api_fixture")
        .set_subject(std::to_string(user.id))
        .set_issued_at(issued_at)
        .set_expires_at(expires_at)
        .set_payload_claim("typ", jwt::claim(std::string{"access"}))
        .sign(jwt::algorithm::hs256{config_.jwt_secret});
}

std::string AuthService::issue_refresh_token(const User& user) const {
    auto issued_at = std::chrono::system_clock::now();
    auto expires_at = issued_at + std::chrono::seconds(config_.refresh_token_ttl_seconds);
    return jwt::create()
        .set_type("JWT")
        .set_issuer("cpp_api_fixture")
        .set_subject(std::to_string(user.id))
        .set_issued_at(issued_at)
        .set_expires_at(expires_at)
        .set_payload_claim("typ", jwt::claim(std::string{"refresh"}))
        .sign(jwt::algorithm::hs256{config_.jwt_secret});
}

std::optional<std::int64_t> AuthService::validate_token(
    std::string_view token, std::string_view expected_type) const {
    try {
        auto decoded = jwt::decode(std::string{token});
        auto verifier = jwt::verify()
            .allow_algorithm(jwt::algorithm::hs256{config_.jwt_secret})
            .with_issuer("cpp_api_fixture");
        verifier.verify(decoded);
        if (decoded.has_payload_claim("typ")) {
            auto typ = decoded.get_payload_claim("typ").as_string();
            if (typ != expected_type) {
                return std::nullopt;
            }
        }
        if (decoded.get_expires_at().time_since_epoch().count() <= now_seconds()) {
            return std::nullopt;
        }
        return std::stoll(decoded.get_subject());
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

}  // namespace api
