#include "api/middleware/logging_middleware.hpp"

#include <httplib.h>
#include <nlohmann/json.hpp>

#include <iostream>

namespace api {

LoggingMiddleware::LoggingMiddleware(bool enabled) : enabled_(enabled) {}

void LoggingMiddleware::before_request(const httplib::Request& req,
                                       httplib::Response& /*res*/) {
    if (!enabled_) {
        return;
    }
    in_flight_[&req] = std::chrono::steady_clock::now();
}

void LoggingMiddleware::after_request(const httplib::Request& req,
                                      httplib::Response& res) {
    if (!enabled_) {
        return;
    }
    auto it = in_flight_.find(&req);
    long long duration_ms = 0;
    if (it != in_flight_.end()) {
        auto now = std::chrono::steady_clock::now();
        duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                          now - it->second)
                          .count();
        in_flight_.erase(it);
    }
    nlohmann::json line = {
        {"method", req.method},
        {"path", req.path},
        {"status", res.status},
        {"duration_ms", duration_ms},
    };
    std::cout << line.dump() << '\n';
}

}  // namespace api
