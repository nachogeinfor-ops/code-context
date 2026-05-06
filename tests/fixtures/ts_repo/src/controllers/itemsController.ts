/**
 * controllers/itemsController.ts — Request handlers for /api/items endpoints.
 */

import type { Request, Response, NextFunction } from "express";
import { CreateItemSchema, UpdateItemSchema } from "../validators/itemValidators";
import * as itemService from "../services/itemService";

export function createItem(req: Request, res: Response, next: NextFunction): void {
  try {
    const data = CreateItemSchema.parse(req.body);
    // Attach authenticated user as owner
    const item = itemService.createItem({ ...data, ownerId: req.user!.sub });
    res.status(201).json(item);
  } catch (err) {
    next(err);
  }
}

export function getItemById(req: Request, res: Response, next: NextFunction): void {
  try {
    const item = itemService.getItemById(req.params.id);
    res.json(item);
  } catch (err) {
    next(err);
  }
}

export function updateItem(req: Request, res: Response, next: NextFunction): void {
  try {
    const data = UpdateItemSchema.parse(req.body);
    const item = itemService.updateItem(req.params.id, data);
    res.json(item);
  } catch (err) {
    next(err);
  }
}

export function deleteItem(req: Request, res: Response, next: NextFunction): void {
  try {
    itemService.deleteItem(req.params.id);
    res.status(204).send();
  } catch (err) {
    next(err);
  }
}

export function listItems(req: Request, res: Response, next: NextFunction): void {
  try {
    const items = itemService.listItemsByOwner(req.user!.sub);
    res.json(items);
  } catch (err) {
    next(err);
  }
}
