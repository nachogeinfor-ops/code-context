#include "api/handlers/users_handler.hpp"

#include "api/dto/user_dto.hpp"
#include "api/error/api_error.hpp"
#include "api/services/user_service.hpp"

#include <httplib.h>
#include <nlohmann/json.hpp>

#include <cstdlib>
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

std::int64_t parse_id(const httplib::Request& req) {
    try {
        return std::stoll(req.matches[1]);
    } catch (const std::exception&) {
        throw ApiError::bad_request("invalid id segment");
    }
}

int parse_query_int(const httplib::Request& req, const char* key, int fallback) {
    auto it = req.params.find(key);
    if (it == req.params.end()) {
        return fallback;
    }
    try {
        return std::stoi(it->second);
    } catch (const std::exception&) {
        return fallback;
    }
}

}  // namespace

UsersHandler::UsersHandler(std::shared_ptr<UserService> service)
    : service_(std::move(service)) {}

void UsersHandler::create_user(const httplib::Request& req, httplib::Response& res) {
    try {
        auto body = nlohmann::json::parse(req.body);
        auto request = CreateUserRequest::from_json(body);
        UserResponse created = service_->create_user(request);
        write_json(res, 201, created.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    } catch (const nlohmann::json::exception&) {
        write_error(res, ApiError::bad_request("malformed json"));
    }
}

void UsersHandler::get_user(const httplib::Request& req, httplib::Response& res) {
    try {
        UserResponse user = service_->get_user_by_id(parse_id(req));
        write_json(res, 200, user.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    }
}

void UsersHandler::list_users(const httplib::Request& req, httplib::Response& res) {
    try {
        int page = parse_query_int(req, "page", 0);
        int page_size = parse_query_int(req, "page_size", 20);
        auto rows = service_->list_users(page, page_size);
        nlohmann::json array = nlohmann::json::array();
        for (const auto& row : rows) {
            array.push_back(row.to_json());
        }
        write_json(res, 200, array);
    } catch (const ApiError& err) {
        write_error(res, err);
    }
}

void UsersHandler::update_user(const httplib::Request& req, httplib::Response& res) {
    try {
        auto body = nlohmann::json::parse(req.body);
        auto patch = UpdateUserRequest::from_json(body);
        UserResponse updated = service_->update_user(parse_id(req), patch);
        write_json(res, 200, updated.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    } catch (const nlohmann::json::exception&) {
        write_error(res, ApiError::bad_request("malformed json"));
    }
}

void UsersHandler::delete_user(const httplib::Request& req, httplib::Response& res) {
    try {
        service_->delete_user(parse_id(req));
        res.status = 204;
    } catch (const ApiError& err) {
        write_error(res, err);
    }
}

}  // namespace api
