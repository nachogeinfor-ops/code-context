#include "api/handlers/items_handler.hpp"

#include "api/dto/item_dto.hpp"
#include "api/error/api_error.hpp"
#include "api/services/item_service.hpp"

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

std::int64_t require_authenticated_user(const httplib::Request& req) {
    auto it = req.headers.find("X-User-Id");
    if (it == req.headers.end()) {
        throw ApiError::unauthorized("auth middleware did not populate principal");
    }
    try {
        return std::stoll(it->second);
    } catch (const std::exception&) {
        throw ApiError::unauthorized("invalid principal");
    }
}

std::int64_t parse_path_id(const httplib::Request& req) {
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

ItemsHandler::ItemsHandler(std::shared_ptr<ItemService> service)
    : service_(std::move(service)) {}

void ItemsHandler::create_item(const httplib::Request& req, httplib::Response& res) {
    try {
        auto user_id = require_authenticated_user(req);
        auto body = nlohmann::json::parse(req.body);
        auto request = CreateItemRequest::from_json(body);
        ItemResponse created = service_->create_item(user_id, request);
        write_json(res, 201, created.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    } catch (const nlohmann::json::exception&) {
        write_error(res, ApiError::bad_request("malformed json"));
    }
}

void ItemsHandler::get_item(const httplib::Request& req, httplib::Response& res) {
    try {
        auto user_id = require_authenticated_user(req);
        ItemResponse item = service_->get_item(user_id, parse_path_id(req));
        write_json(res, 200, item.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    }
}

void ItemsHandler::list_items(const httplib::Request& req, httplib::Response& res) {
    try {
        auto user_id = require_authenticated_user(req);
        int page = parse_query_int(req, "page", 0);
        int page_size = parse_query_int(req, "page_size", 20);
        auto rows = service_->list_items_for_owner(user_id, page, page_size);
        nlohmann::json array = nlohmann::json::array();
        for (const auto& row : rows) {
            array.push_back(row.to_json());
        }
        write_json(res, 200, array);
    } catch (const ApiError& err) {
        write_error(res, err);
    }
}

void ItemsHandler::update_item(const httplib::Request& req, httplib::Response& res) {
    try {
        auto user_id = require_authenticated_user(req);
        auto body = nlohmann::json::parse(req.body);
        auto patch = UpdateItemRequest::from_json(body);
        ItemResponse updated = service_->update_item(user_id, parse_path_id(req), patch);
        write_json(res, 200, updated.to_json());
    } catch (const ApiError& err) {
        write_error(res, err);
    } catch (const nlohmann::json::exception&) {
        write_error(res, ApiError::bad_request("malformed json"));
    }
}

void ItemsHandler::delete_item(const httplib::Request& req, httplib::Response& res) {
    try {
        auto user_id = require_authenticated_user(req);
        service_->delete_item(user_id, parse_path_id(req));
        res.status = 204;
    } catch (const ApiError& err) {
        write_error(res, err);
    }
}

}  // namespace api
