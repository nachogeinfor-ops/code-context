#pragma once

#include <memory>

namespace httplib {
struct Request;
struct Response;
}  // namespace httplib

namespace api {

class UserService;

/**
 * UsersHandler exposes the /api/users CRUD endpoints. POST is public;
 * everything else relies on AuthMiddleware to enforce a valid bearer
 * token before the handler runs.
 */
class UsersHandler {
public:
    explicit UsersHandler(std::shared_ptr<UserService> service);

    /**
     * create_user handles POST /api/users. Validates the
     * CreateUserRequest body and returns 201 with the public user
     * DTO.
     */
    void create_user(const httplib::Request& req, httplib::Response& res);

    /**
     * get_user handles GET /api/users/{id}. The id is captured by the
     * router regex.
     */
    void get_user(const httplib::Request& req, httplib::Response& res);

    /**
     * list_users handles GET /api/users with optional page and
     * page_size query parameters.
     */
    void list_users(const httplib::Request& req, httplib::Response& res);

    /**
     * update_user handles PATCH /api/users/{id} applying a partial
     * patch defined by UpdateUserRequest.
     */
    void update_user(const httplib::Request& req, httplib::Response& res);

    /**
     * delete_user handles DELETE /api/users/{id} returning 204 no
     * content on success.
     */
    void delete_user(const httplib::Request& req, httplib::Response& res);

private:
    std::shared_ptr<UserService> service_;
};

}  // namespace api
