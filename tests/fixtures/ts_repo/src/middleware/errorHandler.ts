/**
 * middleware/errorHandler.ts — Global Express error-handling middleware.
 * Must be registered last with app.use() so that thrown/next(err) errors land here.
 */

import type { Request, Response, NextFunction, ErrorRequestHandler } from "express";
import { ZodError } from "zod";

export const errorHandler: ErrorRequestHandler = (
  err: unknown,
  _req: Request,
  res: Response,
  _next: NextFunction
): void => {
  // Zod validation errors
  if (err instanceof ZodError) {
    res.status(422).json({
      message: "Validation error",
      errors: err.flatten().fieldErrors,
    });
    return;
  }

  // Custom status errors (e.g. thrown with Object.assign(new Error(...), { status }))
  if (err instanceof Error) {
    const status = (err as Error & { status?: number }).status ?? 500;
    res.status(status).json({ message: err.message });
    return;
  }

  // Unknown shape
  res.status(500).json({ message: "Internal server error" });
};
