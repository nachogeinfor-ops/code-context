/**
 * middleware/authMiddleware.ts — Express middleware that verifies JWT access tokens.
 * Attaches the decoded payload to `req.user` for downstream handlers.
 */

import type { Request, Response, NextFunction } from "express";
import { verifyToken } from "../services/authService";
import type { JwtPayload } from "../types/jwt";

// Augment the Express Request type to carry `user`
declare global {
  namespace Express {
    interface Request {
      user?: JwtPayload;
    }
  }
}

export function requireAuth(req: Request, res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    res.status(401).json({ message: "Missing or malformed Authorization header" });
    return;
  }
  const token = authHeader.slice(7);
  try {
    req.user = verifyToken(token, "access");
    next();
  } catch {
    res.status(401).json({ message: "Invalid or expired access token" });
  }
}
