import { describe, expect, it } from "vitest";
import type { Id } from "../convex/_generated/dataModel";
import {
  LOGIN_HANDOFF_TTL_MS,
  loginHandoffGetResponse,
  mintLoginHandoffImpl,
} from "../convex/loginHandoff";

describe("fleet login handoff", () => {
  it("mints a 15-minute token row and returns only the URL/expiry", async () => {
    const now = 1_772_500_000_000;
    const userId = "users:handoff" as Id<"users">;
    const inserts: Array<{ table: string; doc: Record<string, unknown> }> = [];
    const ctx = {
      db: {
        insert: async (table: string, doc: Record<string, unknown>) => {
          inserts.push({ table, doc });
          return "loginHandoffTokens:1";
        },
      },
    } as any;

    const minted = await mintLoginHandoffImpl(ctx, userId, {
      now,
      env: { LOGIN_HANDOFF_BASE: "https://handoff.example" },
    });

    expect(inserts).toHaveLength(1);
    expect(inserts[0].table).toBe("loginHandoffTokens");
    expect(inserts[0].doc.userId).toBe(userId);
    expect(inserts[0].doc.createdAt).toBe(now);
    expect(inserts[0].doc.expiresAt).toBe(now + LOGIN_HANDOFF_TTL_MS);
    expect(inserts[0].doc.consumedAt).toBeUndefined();
    expect(inserts[0].doc.token).toMatch(/^[A-Za-z0-9_-]{32}$/);
    expect(minted).toEqual({
      url: `https://handoff.example/login/${inserts[0].doc.token}`,
      expiresAt: now + LOGIN_HANDOFF_TTL_MS,
    });
    expect("token" in minted).toBe(false);
  });

  it("renders 404 for invalid tokens before consuming anything", async () => {
    let consumed = false;
    const res = await loginHandoffGetResponse(
      new Request("https://handoff.example/login/not-a-valid-token!"),
      async () => {
        consumed = true;
        return { ok: true, userId: "users:handoff" as Id<"users">, expiresAt: Date.now() };
      },
    );

    expect(res.status).toBe(404);
    expect(consumed).toBe(false);
    expect(await res.text()).toContain("invalid or expired");
  });

  it("renders 200 for a valid consumed token without leaking bearer material", async () => {
    const priorSecret = process.env.WORKER_SECRET;
    process.env.WORKER_SECRET = "worker-secret-that-must-not-render";
    const token = "abcdefghijklmnopQRSTUVWX12345678";
    try {
      const res = await loginHandoffGetResponse(
        new Request(`https://handoff.example/login/${token}`),
        async (seenToken) => {
          expect(seenToken).toBe(token);
          return {
            ok: true,
            userId: "users:handoff" as Id<"users">,
            expiresAt: Date.now() + LOGIN_HANDOFF_TTL_MS,
          };
        },
      );

      const html = await res.text();
      expect(res.status).toBe(200);
      expect(html).toContain("Login handoff link verified");
      expect(html).not.toContain(token);
      expect(html).not.toContain("users:handoff");
      expect(html).not.toContain("worker-secret-that-must-not-render");
    } finally {
      if (priorSecret === undefined) delete process.env.WORKER_SECRET;
      else process.env.WORKER_SECRET = priorSecret;
    }
  });
});
