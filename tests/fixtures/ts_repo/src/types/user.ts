/**
 * types/user.ts — TypeScript interfaces for the User domain.
 */

export interface User {
  id: string;
  email: string;
  username: string;
  passwordHash: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface NewUser {
  email: string;
  username: string;
  password: string;
}

export interface UserUpdate {
  email?: string;
  username?: string;
  password?: string;
}

export interface PublicUser {
  id: string;
  email: string;
  username: string;
  createdAt: Date;
}
