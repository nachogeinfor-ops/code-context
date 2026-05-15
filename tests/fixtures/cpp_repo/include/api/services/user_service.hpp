#pragma once

#include "api/dto/user_dto.hpp"

#include <cstdint>
#include <memory>
#include <vector>

namespace api {

class UserRepository;
class AuthService;

/**
 * UserService implements the CRUD use cases for User aggregates. It
 * lives between the HTTP handlers and the repository, enforcing
 * uniqueness, hashing passwords through AuthService, and clamping
 * pagination parameters.
 */
class UserService {
public:
    UserService(std::shared_ptr<UserRepository> users,
                std::shared_ptr<AuthService> auth);

    /**
     * create_user hashes the supplied plaintext password, persists a
     * new account, and returns the public DTO. Throws
     * ApiError::conflict when the email is already taken.
     */
    [[nodiscard]] UserResponse create_user(const CreateUserRequest& request);

    /**
     * get_user_by_id returns the user with the given id or throws
     * ApiError::not_found.
     */
    [[nodiscard]] UserResponse get_user_by_id(std::int64_t id);

    /**
     * list_users returns a clamped page of users wrapped in DTOs.
     */
    [[nodiscard]] std::vector<UserResponse> list_users(int page, int page_size);

    /**
     * update_user applies the non-null fields of `patch` to the
     * tracked entity and re-hashes the password if supplied.
     */
    [[nodiscard]] UserResponse update_user(std::int64_t id,
                                           const UpdateUserRequest& patch);

    /**
     * delete_user removes the user with the given id or throws
     * ApiError::not_found.
     */
    void delete_user(std::int64_t id);

private:
    static constexpr int kMaxPageSize = 100;

    std::shared_ptr<UserRepository> users_;
    std::shared_ptr<AuthService> auth_;
};

}  // namespace api
