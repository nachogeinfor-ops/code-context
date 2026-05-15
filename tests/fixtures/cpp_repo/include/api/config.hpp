#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace api {

/**
 * Config holds runtime settings loaded from environment variables or
 * an optional JSON config file. Immutable after load().
 */
struct Config {
    std::string database_path;
    std::string jwt_secret;
    std::string bind_host;
    std::uint16_t bind_port;
    std::uint32_t access_token_ttl_seconds;
    std::uint32_t refresh_token_ttl_seconds;
    int bcrypt_work_factor;
    bool enable_request_logging;

    /**
     * load reads settings from the environment and from the optional
     * JSON file at `config_path`. Environment variables override file
     * values. Throws ApiError on malformed input.
     */
    [[nodiscard]] static Config load(std::string_view config_path = "");

    /**
     * default_config builds a Config populated with safe defaults so
     * callers can use it in tests without touching disk.
     */
    [[nodiscard]] static Config default_config();
};

}  // namespace api
