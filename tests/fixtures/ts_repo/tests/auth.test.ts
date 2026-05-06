/**
 * tests/auth.test.ts — Integration tests for authentication endpoints.
 * Uses supertest to exercise POST /api/auth/login and POST /api/auth/refresh.
 */

import request from "supertest";
import { createApp } from "../src/app";
import * as userService from "../src/services/userService";

const app = createApp();

beforeAll(async () => {
  // Seed a test user
  await userService.createUser({
    email: "alice@example.com",
    username: "alice",
    password: "Secret123!",
  });
});

describe("POST /api/auth/login", () => {
  it("returns 200 with token pair on valid credentials", async () => {
    const res = await request(app)
      .post("/api/auth/login")
      .send({ email: "alice@example.com", password: "Secret123!" });
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty("accessToken");
    expect(res.body).toHaveProperty("refreshToken");
  });

  it("returns 401 on wrong password", async () => {
    const res = await request(app)
      .post("/api/auth/login")
      .send({ email: "alice@example.com", password: "wrong" });
    expect(res.status).toBe(401);
  });

  it("returns 401 on unknown email", async () => {
    const res = await request(app)
      .post("/api/auth/login")
      .send({ email: "nobody@example.com", password: "Secret123!" });
    expect(res.status).toBe(401);
  });
});

describe("POST /api/auth/refresh", () => {
  it("returns a new token pair given a valid refresh token", async () => {
    const loginRes = await request(app)
      .post("/api/auth/login")
      .send({ email: "alice@example.com", password: "Secret123!" });
    const { refreshToken } = loginRes.body;

    const res = await request(app)
      .post("/api/auth/refresh")
      .send({ refreshToken });
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty("accessToken");
  });

  it("returns 422 when refreshToken field is missing", async () => {
    const res = await request(app).post("/api/auth/refresh").send({});
    expect(res.status).toBe(422);
  });
});
