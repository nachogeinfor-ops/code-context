#include "api/config.hpp"

#include "api/error/api_error.hpp"

#include <nlohmann/json.hpp>

#include <cstdlib>
#include <fstream>

namespace api {

namespace {

/**
 * read_env returns the value of `name` from the process environment, or
 * `fallback` if the variable is unset or empty.
 */
std::string read_env(const char* name, std::string_view fallback) {
    const char* raw = std::getenv(name);
    if (raw == nullptr || raw[0] == '\0') {
        return std::string{fallback};
    }
    return std::string{raw};
}

}  // namespace

Config Config::default_config() {
    Config cfg{};
    cfg.database_path = "api.db";
    cfg.jwt_secret = "change-me-in-prod";
    cfg.bind_host = "0.0.0.0";
    cfg.bind_port = 8080;
    cfg.access_token_ttl_seconds = 900;
    cfg.refresh_token_ttl_seconds = 604800;
    cfg.bcrypt_work_factor = 12;
    cfg.enable_request_logging = true;
    return cfg;
}

Config Config::load(std::string_view config_path) {
    Config cfg = default_config();

    // Layer 1: optional JSON file.
    if (!config_path.empty()) {
        std::ifstream in{std::string{config_path}};
        if (!in) {
            throw ApiError::internal("config file not readable");
        }
        nlohmann::json doc;
        try {
            in >> doc;
        } catch (const nlohmann::json::parse_error& e) {
            throw ApiError::bad_request(std::string{"config json parse: "} + e.what());
        }
        if (auto it = doc.find("database_path"); it != doc.end()) {
            cfg.database_path = it->get<std::string>();
        }
        if (auto it = doc.find("jwt_secret"); it != doc.end()) {
            cfg.jwt_secret = it->get<std::string>();
        }
        if (auto it = doc.find("bind_port"); it != doc.end()) {
            cfg.bind_port = it->get<std::uint16_t>();
        }
    }

    // Layer 2: environment overrides.
    cfg.database_path = read_env("API_DB_PATH", cfg.database_path);
    cfg.jwt_secret = read_env("API_JWT_SECRET", cfg.jwt_secret);
    cfg.bind_host = read_env("API_BIND_HOST", cfg.bind_host);
    if (const char* port_raw = std::getenv("API_BIND_PORT"); port_raw != nullptr) {
        cfg.bind_port = static_cast<std::uint16_t>(std::atoi(port_raw));
    }
    return cfg;
}

}  // namespace api
