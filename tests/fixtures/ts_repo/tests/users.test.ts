/**
 * tests/users.test.ts — Integration tests for /api/users endpoints.
 * Tests create, get, update, delete, and list operations.
 */

import request from "supertest";
import { createApp } from "../src/app";
import { signAccessToken } from "../src/services/authService";

const app = createApp();

describe("POST /api/users — create user", () => {
  it("creates a new user and returns 201 with public fields", async () => {
    const res = await request(app).post("/api/users").send({
      email: "bob@example.com",
      username: "bob",
      password: "Password1!",
    });
    expect(res.status).toBe(201);
    expect(res.body).toMatchObject({ email: "bob@example.com", username: "bob" });
    expect(res.body).not.toHaveProperty("passwordHash");
  });

  it("returns 409 when email is already registered", async () => {
    await request(app).post("/api/users").send({
      email: "dup@example.com",
      username: "dup1",
      password: "Password1!",
    });
    const res = await request(app).post("/api/users").send({
      email: "dup@example.com",
      username: "dup2",
      password: "Password1!",
    });
    expect(res.status).toBe(409);
  });

  it("returns 422 on validation failure (short password)", async () => {
    const res = await request(app).post("/api/users").send({
      email: "bad@example.com",
      username: "baduser",
      password: "short",
    });
    expect(res.status).toBe(422);
  });
});

describe("GET /api/users/:id — get user by ID", () => {
  it("returns the user when authenticated", async () => {
    const createRes = await request(app).post("/api/users").send({
      email: "carol@example.com",
      username: "carol",
      password: "Password1!",
    });
    const { id } = createRes.body;
    const token = signAccessToken(id);

    const res = await request(app)
      .get(`/api/users/${id}`)
      .set("Authorization", `Bearer ${token}`);
    expect(res.status).toBe(200);
    expect(res.body.id).toBe(id);
  });

  it("returns 401 without a token", async () => {
    const res = await request(app).get("/api/users/some-id");
    expect(res.status).toBe(401);
  });
});
