package com.example.api.middleware;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * AuthenticatedUser — controller-parameter annotation that resolves to
 * the authenticated user id placed in the SecurityContext by {@link
 * JwtAuthFilter}.
 *
 * <p>Meta-annotated with {@link AuthenticationPrincipal} so Spring's
 * argument resolver handles binding without any extra config.
 */
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
@AuthenticationPrincipal
public @interface AuthenticatedUser {
}
