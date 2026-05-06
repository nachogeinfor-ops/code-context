/**
 * types/item.ts — TypeScript interfaces for the Item domain.
 */

export interface Item {
  id: string;
  title: string;
  description: string;
  ownerId: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface NewItem {
  title: string;
  description: string;
  ownerId: string;
}

export interface ItemUpdate {
  title?: string;
  description?: string;
}
