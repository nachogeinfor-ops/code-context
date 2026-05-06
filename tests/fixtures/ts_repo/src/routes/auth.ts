/**
 * routes/auth.ts — Express router for /api/auth endpoints.
 * Handles login (POST /login) and token refresh (POST /refresh).
 */

import { Router } from "express";
import { login, refreshToken } from "../controllers/authController";

export const authRouter = Router();

/**
 * POST /api/auth/login
 * Accepts { email, password }; returns { accessToken, refreshToken }.
 */
authRouter.post("/login", login);

/**
 * POST /api/auth/refresh
 * Accepts { refreshToken }; returns a new { accessToken, refreshToken } pair.
 */
authRouter.post("/refresh", refreshToken);
