import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Id } from "../convex/_generated/dataModel";

const authMock = vi.hoisted(() => ({
  config: undefined as any,
}));

vi.mock("@convex-dev/auth/server", () => ({
  convexAuth: vi.fn((config) => {
    authMock.config = config;
    return {
      auth: {},
      signIn: {},
      signOut: {},
      store: {},
      isAuthenticated: {},
    };
  }),
}));

let createOrUpdateUser: any;

beforeAll(async () => {
  await import("../convex/auth");
  createOrUpdateUser = authMock.config.callbacks.createOrUpdateUser;
});

type TableName = "users" | "entitlements";
type StoredDoc = Record<string, any> & { _id: string };

function makeCtx(seedUsers: Array<Record<string, any>> = []) {
  const tables: Record<TableName, StoredDoc[]> = {
    users: seedUsers.map((user, i) => ({
      _id: user._id ?? (`users:seed${i + 1}` as Id<"users">),
      ...user,
    })),
    entitlements: [],
  };
  const patches: Array<{ id: string; patch: Record<string, any> }> = [];

  const findById = (id: string) =>
    [...tables.users, ...tables.entitlements].find((doc) => doc._id === id);

  const db = {
    query(table: TableName) {
      let filter: { field: string; value: any } | undefined;
      return {
        withIndex(_index: string, build: (q: any) => any) {
          const q = {
            eq(field: string, value: any) {
              filter = { field, value };
              return q;
            },
          };
          build(q);
          return this;
        },
        async first() {
          return (
            tables[table].find((doc) =>
              filter ? doc[filter.field] === filter.value : true,
            ) ?? null
          );
        },
      };
    },
    async insert(table: TableName, value: Record<string, any>) {
      const id = `${table}:${tables[table].length + 1}`;
      tables[table].push({ _id: id, ...value });
      return id;
    },
    async patch(id: string, patch: Record<string, any>) {
      patches.push({ id, patch });
      const doc = findById(id);
      if (doc) Object.assign(doc, patch);
    },
    async get(id: string) {
      return findById(id) ?? null;
    },
  };

  return { ctx: { db }, tables, patches };
}

function callbackArgs(type: "phone" | "verification", phone: string) {
  return {
    existingUserId: null,
    type,
    provider: {},
    profile: { phone },
  };
}

describe("auth phone dedupe ownership gates", () => {
  it("rejects an unproven phone match instead of linking to the existing user", async () => {
    const existingUserId = "users:existing" as Id<"users">;
    const { ctx, tables } = makeCtx([
      { _id: existingUserId, phone: "+15551234567" },
    ]);

    await expect(
      createOrUpdateUser(ctx, callbackArgs("phone", "+1 (555) 123-4567")),
    ).rejects.toThrow(
      "an account with this phone already exists — sign in instead",
    );

    expect(tables.users).toHaveLength(1);
    expect(tables.entitlements).toHaveLength(0);
  });

  it("links a verification-type phone match to the existing user", async () => {
    const existingUserId = "users:existing" as Id<"users">;
    const { ctx, tables } = makeCtx([
      { _id: existingUserId, phone: "+15551234567" },
    ]);

    await expect(
      createOrUpdateUser(ctx, callbackArgs("verification", "+1 (555) 123-4567")),
    ).resolves.toBe(existingUserId);

    expect(tables.users).toHaveLength(1);
    expect(tables.entitlements).toHaveLength(0);
  });

  it("does not persist an unproven phone on fresh insert", async () => {
    const { ctx, tables } = makeCtx();

    const userId = await createOrUpdateUser(
      ctx,
      callbackArgs("phone", "+1 (555) 123-4567"),
    );

    const insertedUser = tables.users.find((user) => user._id === userId);
    expect(insertedUser).toBeDefined();
    expect(insertedUser?.phone).toBeUndefined();
    expect(insertedUser?.phoneVerificationTime).toBeUndefined();
    expect(tables.entitlements).toHaveLength(1);
  });
});
