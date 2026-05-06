/**
 * services/authService.ts — JWT sign/verify and bcrypt hash/compare utilities.
 */

import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import { getConfig } from "../config";
import type { JwtPayload, TokenPair } from "../types/jwt";

export async function hashPassword(plain: string): Promise<string> {
  const { BCRYPT_ROUNDS } = getConfig();
  return bcrypt.hash(plain, BCRYPT_ROUNDS);
}

export async function comparePassword(
  plain: string,
  hashed: string
): Promise<boolean> {
  return bcrypt.compare(plain, hashed);
}

export function signAccessToken(userId: string): string {
  const { JWT_SECRET, JWT_ACCESS_EXPIRES_IN } = getConfig();
  const payload: Omit<JwtPayload, "iat" | "exp"> = { sub: userId, type: "access" };
  return jwt.sign(payload, JWT_SECRET, { expiresIn: JWT_ACCESS_EXPIRES_IN });
}

export function signRefreshToken(userId: string): string {
  const { JWT_SECRET, JWT_REFRESH_EXPIRES_IN } = getConfig();
  const payload: Omit<JwtPayload, "iat" | "exp"> = { sub: userId, type: "refresh" };
  return jwt.sign(payload, JWT_SECRET, { expiresIn: JWT_REFRESH_EXPIRES_IN });
}

export function createTokenPair(userId: string): TokenPair {
  return {
    accessToken: signAccessToken(userId),
    refreshToken: signRefreshToken(userId),
  };
}

export function verifyToken(token: string, expectedType: "access" | "refresh" = "access"): JwtPayload {
  const { JWT_SECRET } = getConfig();
  const decoded = jwt.verify(token, JWT_SECRET) as JwtPayload;
  if (decoded.type !== expectedType) {
    throw new Error(`Expected token type "${expectedType}", got "${decoded.type}"`);
  }
  return decoded;
}
