// Entry point for the cpp_api_fixture HTTP server. Wires up the SQLite
// database, repositories, services, handlers, and middleware, then
// starts the cpp-httplib server on the configured address.

#include "api/config.hpp"
#include "api/database.hpp"
#include "api/error/api_error.hpp"
#include "api/handlers/auth_handler.hpp"
#include "api/handlers/items_handler.hpp"
#include "api/handlers/users_handler.hpp"
#include "api/middleware/auth_middleware.hpp"
#include "api/middleware/logging_middleware.hpp"
#include "api/repository/item_repository.hpp"
#include "api/repository/user_repository.hpp"
#include "api/services/auth_service.hpp"
#include "api/services/item_service.hpp"
#include "api/services/user_service.hpp"

#include <httplib.h>

#include <iostream>
#include <memory>

namespace {

/**
 * register_routes attaches every HTTP route to the cpp-httplib server.
 * Lifetimes of the handler instances are owned by main() so we can keep
 * the binding lambdas thin.
 */
void register_routes(httplib::Server& server,
                     api::AuthHandler& auth,
                     api::UsersHandler& users,
                     api::ItemsHandler& items,
                     api::AuthMiddleware& guard) {
    // Auth.
    server.Post("/api/auth/login", [&](const httplib::Request& req, httplib::Response& res) {
        auth.login(req, res);
    });
    server.Post("/api/auth/refresh", [&](const httplib::Request& req, httplib::Response& res) {
        auth.refresh(req, res);
    });

    // Users (mixed public + authenticated).
    server.Post("/api/users", [&](const httplib::Request& req, httplib::Response& res) {
        users.create_user(req, res);
    });
    server.Get(R"(/api/users/(\d+))", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { users.get_user(req, res); });
    });
    server.Get("/api/users", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { users.list_users(req, res); });
    });
    server.Patch(R"(/api/users/(\d+))", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { users.update_user(req, res); });
    });
    server.Delete(R"(/api/users/(\d+))", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { users.delete_user(req, res); });
    });

    // Items (all authenticated).
    server.Post("/api/items", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { items.create_item(req, res); });
    });
    server.Get("/api/items", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { items.list_items(req, res); });
    });
    server.Get(R"(/api/items/(\d+))", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { items.get_item(req, res); });
    });
    server.Patch(R"(/api/items/(\d+))", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { items.update_item(req, res); });
    });
    server.Delete(R"(/api/items/(\d+))", [&](const httplib::Request& req, httplib::Response& res) {
        guard.require_auth(req, res, [&] { items.delete_item(req, res); });
    });
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string_view cfg_path = (argc > 1) ? argv[1] : "";
        api::Config cfg = api::Config::load(cfg_path);

        auto db = std::make_shared<api::Database>(cfg.database_path);
        db->migrate();

        auto user_repo = std::make_shared<api::UserRepository>(db);
        auto item_repo = std::make_shared<api::ItemRepository>(db);

        auto auth_service = std::make_shared<api::AuthService>(cfg, user_repo);
        auto user_service = std::make_shared<api::UserService>(user_repo, auth_service);
        auto item_service = std::make_shared<api::ItemService>(item_repo);

        api::AuthHandler auth_handler{auth_service};
        api::UsersHandler users_handler{user_service};
        api::ItemsHandler items_handler{item_service};
        api::AuthMiddleware guard{auth_service};
        api::LoggingMiddleware logger{cfg.enable_request_logging};

        httplib::Server server;
        server.set_pre_routing_handler([&](const httplib::Request& req, httplib::Response& res) {
            logger.before_request(req, res);
            return httplib::Server::HandlerResponse::Unhandled;
        });
        server.set_post_routing_handler([&](const httplib::Request& req, httplib::Response& res) {
            logger.after_request(req, res);
        });
        register_routes(server, auth_handler, users_handler, items_handler, guard);

        std::cout << "listening on " << cfg.bind_host << ':' << cfg.bind_port << '\n';
        server.listen(cfg.bind_host.c_str(), cfg.bind_port);
        return 0;
    } catch (const api::ApiError& err) {
        std::cerr << "fatal: " << err.what() << '\n';
        return 1;
    } catch (const std::exception& err) {
        std::cerr << "fatal: " << err.what() << '\n';
        return 1;
    }
}
