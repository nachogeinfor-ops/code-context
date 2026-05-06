/**
 * services/userService.ts — Business logic for user account management.
 */

import { randomUUID } from "crypto";
import type { User, NewUser, UserUpdate, PublicUser } from "../types/user";
import { hashPassword } from "./authService";

// In-memory store; replace with a real DB layer in production
const users: Map<string, User> = new Map();
const byEmail: Map<string, string> = new Map(); // email -> id

export async function createUser(data: NewUser): Promise<PublicUser> {
  if (byEmail.has(data.email)) {
    throw Object.assign(new Error("Email already registered"), { status: 409 });
  }
  const id = randomUUID();
  const passwordHash = await hashPassword(data.password);
  const now = new Date();
  const user: User = {
    id,
    email: data.email,
    username: data.username,
    passwordHash,
    createdAt: now,
    updatedAt: now,
  };
  users.set(id, user);
  byEmail.set(data.email, id);
  return toPublic(user);
}

export function getUserById(id: string): PublicUser {
  const user = users.get(id);
  if (!user) throw Object.assign(new Error("User not found"), { status: 404 });
  return toPublic(user);
}

export function getUserByEmail(email: string): User | undefined {
  const id = byEmail.get(email);
  return id ? users.get(id) : undefined;
}

export async function updateUser(id: string, data: UserUpdate): Promise<PublicUser> {
  const user = users.get(id);
  if (!user) throw Object.assign(new Error("User not found"), { status: 404 });
  if (data.email) {
    byEmail.delete(user.email);
    user.email = data.email;
    byEmail.set(data.email, id);
  }
  if (data.username) user.username = data.username;
  if (data.password) user.passwordHash = await hashPassword(data.password);
  user.updatedAt = new Date();
  users.set(id, user);
  return toPublic(user);
}

export function deleteUser(id: string): void {
  const user = users.get(id);
  if (!user) throw Object.assign(new Error("User not found"), { status: 404 });
  byEmail.delete(user.email);
  users.delete(id);
}

export function listUsers(): PublicUser[] {
  return Array.from(users.values()).map(toPublic);
}

function toPublic(user: User): PublicUser {
  const { id, email, username, createdAt } = user;
  return { id, email, username, createdAt };
}
