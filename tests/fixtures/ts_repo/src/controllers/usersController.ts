/**
 * controllers/usersController.ts — Request handlers for /api/users endpoints.
 */

import type { Request, Response, NextFunction } from "express";
import { CreateUserSchema, UpdateUserSchema } from "../validators/userValidators";
import * as userService from "../services/userService";

export async function createUser(req: Request, res: Response, next: NextFunction): Promise<void> {
  try {
    const data = CreateUserSchema.parse(req.body);
    const user = await userService.createUser(data);
    res.status(201).json(user);
  } catch (err) {
    next(err);
  }
}

export function getUserById(req: Request, res: Response, next: NextFunction): void {
  try {
    const user = userService.getUserById(req.params.id);
    res.json(user);
  } catch (err) {
    next(err);
  }
}

export async function updateUser(req: Request, res: Response, next: NextFunction): Promise<void> {
  try {
    const data = UpdateUserSchema.parse(req.body);
    const user = await userService.updateUser(req.params.id, data);
    res.json(user);
  } catch (err) {
    next(err);
  }
}

export function deleteUser(req: Request, res: Response, next: NextFunction): void {
  try {
    userService.deleteUser(req.params.id);
    res.status(204).send();
  } catch (err) {
    next(err);
  }
}

export function listUsers(_req: Request, res: Response, next: NextFunction): void {
  try {
    const users = userService.listUsers();
    res.json(users);
  } catch (err) {
    next(err);
  }
}
