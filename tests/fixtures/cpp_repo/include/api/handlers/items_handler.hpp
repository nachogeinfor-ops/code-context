#pragma once

#include <memory>

namespace httplib {
struct Request;
struct Response;
}  // namespace httplib

namespace api {

class ItemService;

/**
 * ItemsHandler exposes the /api/items CRUD endpoints. Every endpoint
 * runs behind AuthMiddleware, which stuffs the resolved user id into
 * the request context so we can scope reads/writes by ownership.
 */
class ItemsHandler {
public:
    explicit ItemsHandler(std::shared_ptr<ItemService> service);

    /**
     * create_item handles POST /api/items. The owner_id comes from
     * the authenticated principal, not the request body.
     */
    void create_item(const httplib::Request& req, httplib::Response& res);

    /**
     * get_item handles GET /api/items/{id} returning 403 when the
     * requested item belongs to another user.
     */
    void get_item(const httplib::Request& req, httplib::Response& res);

    /**
     * list_items handles GET /api/items returning only items owned by
     * the authenticated user.
     */
    void list_items(const httplib::Request& req, httplib::Response& res);

    /**
     * update_item handles PATCH /api/items/{id} with an
     * UpdateItemRequest body.
     */
    void update_item(const httplib::Request& req, httplib::Response& res);

    /**
     * delete_item handles DELETE /api/items/{id} returning 204 no
     * content on success.
     */
    void delete_item(const httplib::Request& req, httplib::Response& res);

private:
    std::shared_ptr<ItemService> service_;
};

}  // namespace api
