#include "api/middleware/auth_middleware.hpp"

#include "api/error/api_error.hpp"
#include "api/services/auth_service.hpp"

#include <httplib.h>
#include <nlohmann/json.hpp>

#include <string>
#include <utility>

namespace api {

namespace {

constexpr std::string_view kBearerPrefix = "Bearer ";

void write_unauthorized(httplib::Response& res, std::string_view message) {
    nlohmann::json envelope = {
        {"error", {{"code", "unauthorized"}, {"message", std::string{message}}}}
    };
    res.status = 401;
    res.set_content(envelope.dump(), "application/json");
}

}  // namespace

AuthMiddleware::AuthMiddleware(std::shared_ptr<AuthService> service)
    : service_(std::move(service)) {}

std::string_view AuthMiddleware::extract_bearer_token(std::string_view authorization) {
    if (authorization.size() <= kBearerPrefix.size()) {
        return {};
    }
    if (authorization.substr(0, kBearerPrefix.size()) != kBearerPrefix) {
        return {};
    }
    return authorization.substr(kBearerPrefix.size());
}

void AuthMiddleware::require_auth(const httplib::Request& req,
                                  httplib::Response& res,
                                  const std::function<void()>& next) {
    auto header_it = req.headers.find("Authorization");
    if (header_it == req.headers.end()) {
        write_unauthorized(res, "missing Authorization header");
        return;
    }
    std::string_view token = extract_bearer_token(header_it->second);
    if (token.empty()) {
        write_unauthorized(res, "malformed bearer token");
        return;
    }
    auto subject = service_->validate_token(token, "access");
    if (!subject.has_value()) {
        write_unauthorized(res, "token rejected");
        return;
    }
    // Stash the resolved principal so handlers can read it via the
    // X-User-Id pseudo-header. cpp-httplib's headers are mutable.
    const_cast<httplib::Request&>(req).set_header("X-User-Id",
                                                  std::to_string(*subject));
    next();
}

}  // namespace api
