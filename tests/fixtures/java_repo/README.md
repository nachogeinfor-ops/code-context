# java_repo — Spring Boot eval fixture

Small Spring Boot 3.x REST API fixture used by the code-context eval suite.

This fixture is intentionally not built or run; it only needs to be a
realistic-looking Spring Boot project that tree-sitter-java can chunk.

## Layout

```
src/main/java/com/example/api/
  Application.java
  config/
    AppConfig.java
    SecurityConfig.java
  controllers/
    AuthController.java
    UsersController.java
    ItemsController.java
  services/
    AuthService.java
    UserService.java
    ItemService.java
    JwtTokenProvider.java
  repositories/
    UserRepository.java
    ItemRepository.java
  models/
    User.java
    Item.java
  dto/
    LoginRequest.java
    TokenResponse.java
    CreateUserRequest.java
    UpdateUserRequest.java
    UserResponse.java
    CreateItemRequest.java
    UpdateItemRequest.java
    ItemResponse.java
  middleware/
    JwtAuthFilter.java
    RequestLoggingFilter.java
  exceptions/
    ApiException.java
    GlobalExceptionHandler.java

src/test/java/com/example/api/
  AuthControllerTest.java
  UsersControllerTest.java
  ItemsControllerTest.java
```

## Endpoints

| Method | Path                 | Controller          |
|--------|----------------------|---------------------|
| POST   | /api/auth/login      | AuthController      |
| POST   | /api/auth/refresh    | AuthController      |
| POST   | /api/users           | UsersController     |
| GET    | /api/users/{id}      | UsersController     |
| GET    | /api/users           | UsersController     |
| PATCH  | /api/users/{id}      | UsersController     |
| DELETE | /api/users/{id}      | UsersController     |
| POST   | /api/items           | ItemsController     |
| GET    | /api/items/{id}      | ItemsController     |
| GET    | /api/items           | ItemsController     |
| PATCH  | /api/items/{id}      | ItemsController     |
| DELETE | /api/items/{id}      | ItemsController     |
