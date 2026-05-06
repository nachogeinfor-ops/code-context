/**
 * controllers/authController.ts — Request handlers for authentication endpoints.
 */

import type { Request, Response, NextFunction } from "express";
import { z } from "zod";
import { getUserByEmail } from "../services/userService";
import { comparePassword, createTokenPair, verifyToken } from "../services/authService";

const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

const RefreshSchema = z.object({
  refreshToken: z.string().min(1),
});

export async function login(req: Request, res: Response, next: NextFunction): Promise<void> {
  try {
    const { email, password } = LoginSchema.parse(req.body);
    const user = getUserByEmail(email);
    if (!user) {
      res.status(401).json({ message: "Invalid credentials" });
      return;
    }
    const valid = await comparePassword(password, user.passwordHash);
    if (!valid) {
      res.status(401).json({ message: "Invalid credentials" });
      return;
    }
    const tokens = createTokenPair(user.id);
    res.status(200).json(tokens);
  } catch (err) {
    next(err);
  }
}

export function refreshToken(req: Request, res: Response, next: NextFunction): void {
  try {
    const { refreshToken } = RefreshSchema.parse(req.body);
    const payload = verifyToken(refreshToken, "refresh");
    const tokens = createTokenPair(payload.sub);
    res.status(200).json(tokens);
  } catch (err) {
    next(err);
  }
}
