#pragma once

#include <memory>

namespace httplib {
struct Request;
struct Response;
}  // namespace httplib

namespace api {

class AuthService;

/**
 * AuthHandler exposes the unauthenticated /api/auth/* endpoints. It
 * translates JSON payloads into AuthService calls and back, and maps
 * ApiError exceptions to the standard error envelope.
 */
class AuthHandler {
public:
    explicit AuthHandler(std::shared_ptr<AuthService> service);

    /**
     * login handles POST /api/auth/login. The body is {email,
     * password}; the response carries access + refresh tokens.
     */
    void login(const httplib::Request& req, httplib::Response& res);

    /**
     * refresh handles POST /api/auth/refresh. The body is a single
     * {refresh_token}; the response is the same TokenResponse shape as
     * login.
     */
    void refresh(const httplib::Request& req, httplib::Response& res);

private:
    std::shared_ptr<AuthService> service_;
};

}  // namespace api
