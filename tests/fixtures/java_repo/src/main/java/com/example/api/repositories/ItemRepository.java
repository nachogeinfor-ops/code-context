package com.example.api.repositories;

import com.example.api.models.Item;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/**
 * ItemRepository — Spring Data JPA repository for {@link Item}.
 *
 * <p>Owner-scoped queries dominate this repo: items always come back
 * filtered by {@code ownerId}, which is how the service layer enforces
 * "you can only see your own items."
 */
@Repository
public interface ItemRepository extends JpaRepository<Item, Long> {

    /**
     * findByOwnerId returns a page of items belonging to the given user.
     */
    Page<Item> findByOwnerId(Long ownerId, Pageable pageable);

    /**
     * countByOwnerId returns the number of items owned by the user.
     */
    long countByOwnerId(Long ownerId);

    /**
     * deleteByIdAndOwnerId removes an item only if the owner matches.
     * Returns 0 if no row was touched (ownership mismatch or not found).
     */
    @Modifying
    @Transactional
    @Query("DELETE FROM Item i WHERE i.id = :id AND i.ownerId = :ownerId")
    int deleteByIdAndOwnerId(@Param("id") Long id, @Param("ownerId") Long ownerId);
}
