/**
 * validators/itemValidators.ts — Zod schemas for Item request payloads.
 */

import { z } from "zod";

export const CreateItemSchema = z.object({
  title: z
    .string()
    .min(1, "Title is required")
    .max(120, "Title must be at most 120 characters"),
  description: z
    .string()
    .max(2000, "Description must be at most 2000 characters")
    .default(""),
});

export const UpdateItemSchema = z.object({
  title: z.string().min(1).max(120).optional(),
  description: z.string().max(2000).optional(),
});

export type CreateItemInput = z.infer<typeof CreateItemSchema>;
export type UpdateItemInput = z.infer<typeof UpdateItemSchema>;
