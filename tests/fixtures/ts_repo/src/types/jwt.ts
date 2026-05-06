/**
 * types/jwt.ts — TypeScript interfaces for JWT payload shapes.
 */

export interface JwtPayload {
  sub: string;       // subject — the user's ID
  type: "access" | "refresh";
  iat?: number;      // issued at (seconds since epoch)
  exp?: number;      // expiry (seconds since epoch)
}

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}
