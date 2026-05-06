/**
 * routes/users.ts — Express router for /api/users CRUD endpoints.
 * All mutating routes require a valid JWT access token.
 */

import { Router } from "express";
import {
  createUser,
  getUserById,
  updateUser,
  deleteUser,
  listUsers,
} from "../controllers/usersController";
import { requireAuth } from "../middleware/authMiddleware";

export const usersRouter = Router();

/** GET /api/users — list all users (protected) */
usersRouter.get("/", requireAuth, listUsers);

/** POST /api/users — create a new user account */
usersRouter.post("/", createUser);

/** GET /api/users/:id — get a single user by ID (protected) */
usersRouter.get("/:id", requireAuth, getUserById);

/** PATCH /api/users/:id — partial update of a user (protected) */
usersRouter.patch("/:id", requireAuth, updateUser);

/** DELETE /api/users/:id — delete a user account (protected) */
usersRouter.delete("/:id", requireAuth, deleteUser);
