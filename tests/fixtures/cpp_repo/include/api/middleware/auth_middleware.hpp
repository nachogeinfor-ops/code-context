#pragma once

#include <functional>
#include <memory>
#include <string_view>

namespace httplib {
struct Request;
struct Response;
}  // namespace httplib

namespace api {

class AuthService;

/**
 * AuthMiddleware enforces the presence of a valid JWT bearer token on
 * protected routes. It extracts the token from the Authorization
 * header, asks AuthService to validate it, and stashes the resolved
 * user id on the request via an X-User-Id pseudo-header so downstream
 * handlers can read it without re-parsing the JWT.
 */
class AuthMiddleware {
public:
    explicit AuthMiddleware(std::shared_ptr<AuthService> service);

    /**
     * require_auth wraps a handler. If the JWT bearer token is valid,
     * it calls `next`; otherwise it writes a 401 JSON error envelope
     * onto `res` and returns without calling `next`.
     */
    void require_auth(const httplib::Request& req, httplib::Response& res,
                      const std::function<void()>& next);

    /**
     * extract_bearer_token strips the "Bearer " prefix from the
     * Authorization header. Returns an empty view when the header is
     * absent or malformed.
     */
    [[nodiscard]] static std::string_view extract_bearer_token(
        std::string_view authorization);

private:
    std::shared_ptr<AuthService> service_;
};

}  // namespace api
