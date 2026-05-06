/**
 * app.ts — Express application factory.
 * Creates and configures the Express instance, mounts all routers,
 * and registers global middleware (JSON parsing, error handler).
 */

import express from "express";
import { authRouter } from "./routes/auth";
import { itemsRouter } from "./routes/items";
import { usersRouter } from "./routes/users";
import { errorHandler } from "./middleware/errorHandler";
import { requestLogger } from "./middleware/requestLogger";

export function createApp(): express.Application {
  const app = express();

  // Body parsing
  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  // Request logging
  app.use(requestLogger);

  // API routes
  app.use("/api/auth", authRouter);
  app.use("/api/users", usersRouter);
  app.use("/api/items", itemsRouter);

  // Health-check
  app.get("/health", (_req, res) => {
    res.json({ status: "ok" });
  });

  // Global error handler — must be last
  app.use(errorHandler);

  return app;
}
