/**
 * routes/items.ts — Express router for /api/items CRUD endpoints.
 * All routes require a valid JWT access token.
 */

import { Router } from "express";
import {
  createItem,
  getItemById,
  updateItem,
  deleteItem,
  listItems,
} from "../controllers/itemsController";
import { requireAuth } from "../middleware/authMiddleware";

export const itemsRouter = Router();

/** GET /api/items — list items belonging to the authenticated user */
itemsRouter.get("/", requireAuth, listItems);

/** POST /api/items — create a new item owned by the authenticated user */
itemsRouter.post("/", requireAuth, createItem);

/** GET /api/items/:id — fetch a single item by ID */
itemsRouter.get("/:id", requireAuth, getItemById);

/** PATCH /api/items/:id — partial update of an item */
itemsRouter.patch("/:id", requireAuth, updateItem);

/** DELETE /api/items/:id — delete an item */
itemsRouter.delete("/:id", requireAuth, deleteItem);
