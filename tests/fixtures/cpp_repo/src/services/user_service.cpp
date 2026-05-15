#include "api/services/user_service.hpp"

#include "api/error/api_error.hpp"
#include "api/repository/user_repository.hpp"
#include "api/services/auth_service.hpp"

#include <algorithm>
#include <chrono>
#include <utility>

namespace api {

namespace {

std::int64_t now_seconds() {
    using namespace std::chrono;
    return duration_cast<seconds>(system_clock::now().time_since_epoch()).count();
}

}  // namespace

UserService::UserService(std::shared_ptr<UserRepository> users,
                         std::shared_ptr<AuthService> auth)
    : users_(std::move(users)), auth_(std::move(auth)) {}

UserResponse UserService::create_user(const CreateUserRequest& request) {
    if (users_->exists_by_email(request.email)) {
        throw ApiError::conflict("email already taken");
    }
    User user{};
    user.email = request.email;
    user.username = request.username;
    user.password_hash = auth_->encode_password(request.password);
    user.created_at = now_seconds();
    User saved = users_->save(user);
    return UserResponse::from_entity(saved);
}

UserResponse UserService::get_user_by_id(std::int64_t id) {
    auto user = users_->find_by_id(id);
    if (!user.has_value()) {
        throw ApiError::not_found("user not found");
    }
    return UserResponse::from_entity(*user);
}

std::vector<UserResponse> UserService::list_users(int page, int page_size) {
    int safe_page = std::max(0, page);
    int safe_size = std::clamp(page_size, 1, kMaxPageSize);
    auto rows = users_->find_all_paged(safe_page, safe_size);
    std::vector<UserResponse> out;
    out.reserve(rows.size());
    for (const auto& user : rows) {
        out.push_back(UserResponse::from_entity(user));
    }
    return out;
}

UserResponse UserService::update_user(std::int64_t id,
                                      const UpdateUserRequest& patch) {
    auto user = users_->find_by_id(id);
    if (!user.has_value()) {
        throw ApiError::not_found("user not found");
    }
    if (patch.email.has_value()) {
        user->email = *patch.email;
    }
    if (patch.username.has_value()) {
        user->username = *patch.username;
    }
    if (patch.password.has_value()) {
        user->password_hash = auth_->encode_password(*patch.password);
    }
    User saved = users_->update(*user);
    return UserResponse::from_entity(saved);
}

void UserService::delete_user(std::int64_t id) {
    if (!users_->exists_by_id(id)) {
        throw ApiError::not_found("user not found");
    }
    users_->delete_by_id(id);
}

}  // namespace api
