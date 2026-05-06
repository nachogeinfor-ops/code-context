/**
 * config.ts — Zod-validated environment configuration.
 * Reads process.env and throws at startup if required variables are missing.
 */

import { z } from "zod";

const EnvSchema = z.object({
  PORT: z.coerce.number().default(3000),
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  JWT_SECRET: z.string().min(16, "JWT_SECRET must be at least 16 characters"),
  JWT_ACCESS_EXPIRES_IN: z.string().default("15m"),
  JWT_REFRESH_EXPIRES_IN: z.string().default("7d"),
  BCRYPT_ROUNDS: z.coerce.number().default(10),
  DATABASE_URL: z.string().url().default("sqlite://./dev.db"),
});

export type Env = z.infer<typeof EnvSchema>;

let _config: Env | null = null;

export function loadConfig(): Env {
  if (_config) return _config;
  const result = EnvSchema.safeParse(process.env);
  if (!result.success) {
    throw new Error(`Invalid environment config:\n${result.error.toString()}`);
  }
  _config = result.data;
  return _config;
}

/** Alias used by other modules to obtain the parsed env config. */
export const getConfig = loadConfig;
