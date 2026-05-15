cmake_minimum_required(VERSION 3.16)
project(cpp_api_fixture LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Third-party (provided by the host system or vcpkg, not vendored here).
find_package(nlohmann_json CONFIG REQUIRED)
find_package(SQLite3 REQUIRED)

add_library(api_lib STATIC
    src/config.cpp
    src/database.cpp
    src/handlers/auth_handler.cpp
    src/handlers/users_handler.cpp
    src/handlers/items_handler.cpp
    src/services/auth_service.cpp
    src/services/user_service.cpp
    src/services/item_service.cpp
    src/repository/user_repository.cpp
    src/repository/item_repository.cpp
    src/middleware/auth_middleware.cpp
    src/middleware/logging_middleware.cpp
)
target_include_directories(api_lib PUBLIC include)
target_link_libraries(api_lib PUBLIC nlohmann_json::nlohmann_json SQLite::SQLite3)

add_executable(api_server src/main.cpp)
target_link_libraries(api_server PRIVATE api_lib)

enable_testing()
add_executable(api_tests
    tests/auth_test.cpp
    tests/users_test.cpp
    tests/items_test.cpp
)
target_link_libraries(api_tests PRIVATE api_lib)
add_test(NAME api_tests COMMAND api_tests)
