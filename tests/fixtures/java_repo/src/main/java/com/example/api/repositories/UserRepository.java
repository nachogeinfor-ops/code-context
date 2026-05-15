package com.example.api.repositories;

import com.example.api.models.User;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import java.util.Optional;

/**
 * UserRepository — Spring Data JPA repository for {@link User}.
 *
 * <p>Inherits standard CRUD ({@code findById}, {@code save}, {@code delete},
 * {@code findAll}) from {@link JpaRepository} and adds a handful of
 * domain-specific finders used by the auth + user services.
 */
@Repository
public interface UserRepository extends JpaRepository<User, Long> {

    /**
     * findByEmail looks up a user by their unique email address.
     * Used by AuthService during login.
     */
    Optional<User> findByEmail(String email);

    /**
     * findByUsername looks up a user by their unique username.
     */
    Optional<User> findByUsername(String username);

    /**
     * existsByEmail reports whether a row with the given email already
     * exists, used by UserService.createUser before insert to return a
     * clean 409 Conflict.
     */
    boolean existsByEmail(String email);

    /**
     * findAllPaged returns a page of users ordered by created_at desc.
     * Wraps the default findAll(Pageable) with an explicit JPQL query
     * so the ordering is stable.
     */
    @Query("SELECT u FROM User u ORDER BY u.createdAt DESC")
    Page<User> findAllPaged(Pageable pageable);

    /**
     * countByEmailDomain counts users whose email ends with the given
     * domain (e.g. "@example.com").
     */
    @Query("SELECT COUNT(u) FROM User u WHERE u.email LIKE :domain")
    long countByEmailDomain(@Param("domain") String domain);
}
