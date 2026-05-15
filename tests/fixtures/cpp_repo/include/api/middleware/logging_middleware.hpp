#pragma once

#include <chrono>
#include <unordered_map>

namespace httplib {
struct Request;
struct Response;
}  // namespace httplib

namespace api {

/**
 * LoggingMiddleware writes one JSON log line per request describing
 * the method, path, status, and duration in milliseconds. Disabled by
 * default in test builds via the `enabled` constructor argument.
 */
class LoggingMiddleware {
public:
    explicit LoggingMiddleware(bool enabled);

    /**
     * before_request records the start timestamp keyed by the
     * request's address so after_request can compute the elapsed
     * duration.
     */
    void before_request(const httplib::Request& req, httplib::Response& res);

    /**
     * after_request emits the log line and forgets the start
     * timestamp. Safe to call even if `before_request` was skipped.
     */
    void after_request(const httplib::Request& req, httplib::Response& res);

private:
    using time_point = std::chrono::steady_clock::time_point;

    bool enabled_;
    std::unordered_map<const httplib::Request*, time_point> in_flight_;
};

}  // namespace api
