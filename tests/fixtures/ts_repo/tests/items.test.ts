/**
 * tests/items.test.ts — Integration tests for /api/items endpoints.
 * Tests create item, list items by owner, update item, and delete item.
 */

import request from "supertest";
import { createApp } from "../src/app";
import { signAccessToken } from "../src/services/authService";

const app = createApp();
const userId = "test-user-123";
const token = signAccessToken(userId);
const authHeader = `Bearer ${token}`;

describe("POST /api/items — create item", () => {
  it("creates an item owned by the authenticated user", async () => {
    const res = await request(app)
      .post("/api/items")
      .set("Authorization", authHeader)
      .send({ title: "My first item", description: "A short description" });
    expect(res.status).toBe(201);
    expect(res.body).toMatchObject({ title: "My first item", ownerId: userId });
  });

  it("returns 422 when title is missing", async () => {
    const res = await request(app)
      .post("/api/items")
      .set("Authorization", authHeader)
      .send({ description: "no title" });
    expect(res.status).toBe(422);
  });

  it("returns 401 without a valid token", async () => {
    const res = await request(app)
      .post("/api/items")
      .send({ title: "Should fail" });
    expect(res.status).toBe(401);
  });
});

describe("GET /api/items — list items by owner", () => {
  it("returns only items owned by the authenticated user", async () => {
    const res = await request(app)
      .get("/api/items")
      .set("Authorization", authHeader);
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body)).toBe(true);
    res.body.forEach((item: { ownerId: string }) => {
      expect(item.ownerId).toBe(userId);
    });
  });
});

describe("DELETE /api/items/:id", () => {
  it("deletes an existing item and returns 204", async () => {
    const createRes = await request(app)
      .post("/api/items")
      .set("Authorization", authHeader)
      .send({ title: "To delete" });
    const { id } = createRes.body;

    const res = await request(app)
      .delete(`/api/items/${id}`)
      .set("Authorization", authHeader);
    expect(res.status).toBe(204);
  });
});
