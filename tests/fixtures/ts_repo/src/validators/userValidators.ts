/**
 * validators/userValidators.ts — Zod schemas for User request payloads.
 */

import { z } from "zod";

export const CreateUserSchema = z.object({
  email: z.string().email("Invalid email address"),
  username: z
    .string()
    .min(3, "Username must be at least 3 characters")
    .max(30, "Username must be at most 30 characters")
    .regex(/^[a-z0-9_]+$/, "Username may only contain lowercase letters, digits, and underscores"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(72, "Password must be at most 72 characters"),
});

export const UpdateUserSchema = z.object({
  email: z.string().email().optional(),
  username: z.string().min(3).max(30).optional(),
  password: z.string().min(8).max(72).optional(),
});

export type CreateUserInput = z.infer<typeof CreateUserSchema>;
export type UpdateUserInput = z.infer<typeof UpdateUserSchema>;
