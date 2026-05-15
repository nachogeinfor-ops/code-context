#include "api/handlers/auth_handler.hpp"

#include "api/dto/auth_dto.hpp"
#include "api/error/api_error.hpp"
#include "api/services/auth_service.hpp"

#include <httplib.h>
#include <nlohmann/json.hpp>

#include <utility>

namespace api {

namespace {

void write_json(httplib::Response& res, int status, const nlohmann::json& body) {
    res.status = status;
    res.set_content(body.dump(), "application/json");
}

void write_error(httplib::Response& res, const ApiError& err) {
    nlohmann::json envelope = {
        {"error", {{"code", err.code()}, {"message", err.message()}}}
    };
    write_json(res, err.status(), envelope);
}

}  // namespace

AuthHandler::AuthHandler(std::shared_ptr<AuthService> service)
    : service_(std::move(service)) {}

void AuthHandler::login(const httplib::Request& req, httplib::Response& res) {
    try {
        auto body = nlohmann::json::parse(req.body);
        auto request = LoginRequest::from_json(body);
        TokenResponse tokens = service_->login(request);
        write_json(res, 200, tokens.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    } catch (const nlohmann::json::exception&) {
        write_error(res, ApiError::bad_request("malformed json"));
    }
}

void AuthHandler::refresh(const httplib::Request& req, httplib::Response& res) {
    try {
        auto body = nlohmann::json::parse(req.body);
        auto request = RefreshRequest::from_json(body);
        TokenResponse tokens = service_->refresh(request);
        write_json(res, 200, tokens.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    } catch (const nlohmann::json::exception&) {
        write_error(res, ApiError::bad_request("malformed json"));
    }
}

}  // namespace api
