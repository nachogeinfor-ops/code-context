#pragma once

#include <exception>
#include <string>
#include <utility>

namespace api {

/**
 * ApiError is the single exception type thrown across the API. It
 * carries an HTTP status, an application-facing error code, and a
 * human-readable message; handlers translate it into a JSON envelope.
 */
class ApiError : public std::exception {
public:
    ApiError(int status, std::string code, std::string message)
        : status_(status), code_(std::move(code)), message_(std::move(message)) {}

    [[nodiscard]] int status() const noexcept { return status_; }
    [[nodiscard]] const std::string& code() const noexcept { return code_; }
    [[nodiscard]] const std::string& message() const noexcept { return message_; }

    [[nodiscard]] const char* what() const noexcept override {
        return message_.c_str();
    }

    // Convenience constructors mirroring the most common 4xx/5xx codes
    // so call sites read fluently: `throw ApiError::not_found("user")`.

    [[nodiscard]] static ApiError bad_request(std::string message) {
        return ApiError(400, "bad_request", std::move(message));
    }
    [[nodiscard]] static ApiError unauthorized(std::string message) {
        return ApiError(401, "unauthorized", std::move(message));
    }
    [[nodiscard]] static ApiError forbidden(std::string message) {
        return ApiError(403, "forbidden", std::move(message));
    }
    [[nodiscard]] static ApiError not_found(std::string message) {
        return ApiError(404, "not_found", std::move(message));
    }
    [[nodiscard]] static ApiError conflict(std::string message) {
        return ApiError(409, "conflict", std::move(message));
    }
    [[nodiscard]] static ApiError internal(std::string message) {
        return ApiError(500, "internal_error", std::move(message));
    }

private:
    int status_;
    std::string code_;
    std::string message_;
};

}  // namespace api
