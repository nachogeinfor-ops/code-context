/**
 * services/itemService.ts — Business logic for item CRUD operations.
 */

import { randomUUID } from "crypto";
import type { Item, NewItem, ItemUpdate } from "../types/item";

// In-memory store; replace with a real DB layer in production
const items: Map<string, Item> = new Map();

export function createItem(data: NewItem): Item {
  const id = randomUUID();
  const now = new Date();
  const item: Item = { id, ...data, createdAt: now, updatedAt: now };
  items.set(id, item);
  return item;
}

export function getItemById(id: string): Item {
  const item = items.get(id);
  if (!item) throw Object.assign(new Error("Item not found"), { status: 404 });
  return item;
}

export function listItemsByOwner(ownerId: string): Item[] {
  return Array.from(items.values()).filter((i) => i.ownerId === ownerId);
}

export function updateItem(id: string, data: ItemUpdate): Item {
  const item = items.get(id);
  if (!item) throw Object.assign(new Error("Item not found"), { status: 404 });
  if (data.title !== undefined) item.title = data.title;
  if (data.description !== undefined) item.description = data.description;
  item.updatedAt = new Date();
  items.set(id, item);
  return item;
}

export function deleteItem(id: string): void {
  if (!items.has(id)) throw Object.assign(new Error("Item not found"), { status: 404 });
  items.delete(id);
}

export function listAllItems(): Item[] {
  return Array.from(items.values());
}
