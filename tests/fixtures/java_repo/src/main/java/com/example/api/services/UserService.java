package com.example.api.services;

import com.example.api.dto.CreateUserRequest;
import com.example.api.dto.UpdateUserRequest;
import com.example.api.dto.UserResponse;
import com.example.api.exceptions.ApiException;
import com.example.api.models.User;
import com.example.api.repositories.UserRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;

/**
 * UserService — CRUD operations for {@link User} aggregates.
 *
 * <p>Hashes passwords via {@link AuthService#encodePassword}, enforces
 * email uniqueness, and clamps pagination parameters so the controller
 * layer can hand raw query strings to us safely.
 */
@Service
public class UserService {

    private static final int MAX_PAGE_SIZE = 100;

    private final UserRepository userRepository;
    private final AuthService authService;

    public UserService(UserRepository userRepository, AuthService authService) {
        this.userRepository = userRepository;
        this.authService = authService;
    }

    /**
     * createUser hashes the request's plaintext password, persists a new
     * {@link User}, and returns the public DTO.
     */
    @Transactional
    public UserResponse createUser(CreateUserRequest request) {
        if (userRepository.existsByEmail(request.getEmail())) {
            throw new ApiException(HttpStatus.CONFLICT, "email already taken");
        }
        String hashed = authService.encodePassword(request.getPassword());
        User user = new User(request.getEmail(), request.getUsername(), hashed);
        User saved = userRepository.save(user);
        return UserResponse.fromEntity(saved);
    }

    /**
     * getUserById returns the user with the given id or 404s.
     */
    public UserResponse getUserById(Long id) {
        User user = userRepository.findById(id)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "user not found"));
        return UserResponse.fromEntity(user);
    }

    /**
     * listUsers returns a page of users wrapped in DTOs.
     */
    public List<UserResponse> listUsers(int page, int pageSize) {
        int safePage = Math.max(0, page);
        int safeSize = Math.min(MAX_PAGE_SIZE, Math.max(1, pageSize));
        Pageable pageable = PageRequest.of(safePage, safeSize);
        Page<User> rows = userRepository.findAllPaged(pageable);
        return rows.stream().map(UserResponse::fromEntity).toList();
    }

    /**
     * updateUser applies the non-null fields of {@code patch} to the
     * tracked entity and re-hashes the password if supplied.
     */
    @Transactional
    public UserResponse updateUser(Long id, UpdateUserRequest patch) {
        User user = userRepository.findById(id)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "user not found"));
        if (patch.getEmail() != null) {
            user.setEmail(patch.getEmail());
        }
        if (patch.getUsername() != null) {
            user.setUsername(patch.getUsername());
        }
        if (patch.getPassword() != null) {
            user.setPasswordHash(authService.encodePassword(patch.getPassword()));
        }
        return UserResponse.fromEntity(user);
    }

    /**
     * deleteUser removes the user with the given id or 404s.
     */
    @Transactional
    public void deleteUser(Long id) {
        if (!userRepository.existsById(id)) {
            throw new ApiException(HttpStatus.NOT_FOUND, "user not found");
        }
        userRepository.deleteById(id);
    }
}
