// chat-sites: registry + provisioning for assistant-generated personalized sites.
//   - publish  (action)         : worker-secret-gated entry the Hermes skill calls.
//   - _upsert  (internalMutation): write/overwrite the registry row.
//   - getByHandle (internalQuery): server-side read for the action + http routes.
// Serving (GET /s/:handle) and the data proxy (POST /site-data/:handle) live in
// http.ts and read these via runQuery.

import { action, internalMutation, internalQuery } from "./_generated/server";
import { internal } from "./_generated/api";
import { v } from "convex/values";
import { assertSitesPublisher } from "./lib/auth";
import { validateHandle, buildSiteUrl } from "./lib/sitelib";
import { provisionApp, applySchema, tursoConfigFromEnv } from "./lib/turso";

const kindValidator = v.union(v.literal("static"), v.literal("app"));
const MAX_HTML_BYTES = 1_000_000; // ~1MB single-file document cap

// Narrowed projection returned to server-side callers (action + http routes).
// Deliberately a fixed shape (not the raw Doc) so the validator is small and the
// per-DB token is only ever read by trusted server code.
const siteProjection = v.object({
  handle: v.string(),
  userId: v.optional(v.id("users")),
  kind: kindValidator,
  title: v.optional(v.string()),
  html: v.string(),
  tursoDbName: v.optional(v.string()),
  tursoHostname: v.optional(v.string()),
  tursoToken: v.optional(v.string()),
  schemaSql: v.optional(v.string()),
  version: v.number(),
});

export const getByHandle = internalQuery({
  args: { handle: v.string() },
  returns: v.union(v.null(), siteProjection),
  handler: async (ctx, { handle }) => {
    const row = await ctx.db
      .query("sites")
      .withIndex("by_handle", (q) => q.eq("handle", handle))
      .unique();
    if (!row) return null;
    return {
      handle: row.handle,
      userId: row.userId,
      kind: row.kind,
      title: row.title,
      html: row.html,
      tursoDbName: row.tursoDbName,
      tursoHostname: row.tursoHostname,
      tursoToken: row.tursoToken,
      schemaSql: row.schemaSql,
      version: row.version,
    };
  },
});

export const _upsert = internalMutation({
  args: {
    handle: v.string(),
    userId: v.optional(v.id("users")),
    kind: kindValidator,
    title: v.optional(v.string()),
    html: v.string(),
    tursoDbName: v.optional(v.string()),
    tursoHostname: v.optional(v.string()),
    tursoToken: v.optional(v.string()),
    schemaSql: v.optional(v.string()),
  },
  returns: v.id("sites"),
  handler: async (ctx, args) => {
    const now = Date.now();
    const existing = await ctx.db
      .query("sites")
      .withIndex("by_handle", (q) => q.eq("handle", args.handle))
      .unique();
    if (existing) {
      await ctx.db.patch(existing._id, {
        userId: args.userId ?? existing.userId,
        kind: args.kind,
        title: args.title,
        html: args.html,
        tursoDbName: args.tursoDbName ?? existing.tursoDbName,
        tursoHostname: args.tursoHostname ?? existing.tursoHostname,
        tursoToken: args.tursoToken ?? existing.tursoToken,
        schemaSql: args.schemaSql ?? existing.schemaSql,
        version: (existing.version ?? 1) + 1,
        updatedAt: now,
      });
      return existing._id;
    }
    return await ctx.db.insert("sites", {
      handle: args.handle,
      userId: args.userId,
      kind: args.kind,
      title: args.title,
      html: args.html,
      tursoDbName: args.tursoDbName,
      tursoHostname: args.tursoHostname,
      tursoToken: args.tursoToken,
      schemaSql: args.schemaSql,
      version: 1,
      createdAt: now,
      updatedAt: now,
    });
  },
});

/**
 * Publish (create or update) a site. The Hermes `create-site` skill calls this
 * over the public HTTP API with the worker secret. For `kind="app"` it
 * provisions an isolated Turso database on first publish and applies the schema;
 * republishes reuse the same database (idempotent CREATE TABLE IF NOT EXISTS).
 * Returns the live public URL.
 */
export const publish = action({
  args: {
    secret: v.string(),
    handle: v.string(),
    kind: kindValidator,
    html: v.string(),
    title: v.optional(v.string()),
    schema: v.optional(v.string()),   // CREATE TABLE ...; for kind="app"
    userId: v.optional(v.id("users")),
  },
  returns: v.object({ url: v.string(), handle: v.string(), kind: kindValidator }),
  handler: async (ctx, args): Promise<{ url: string; handle: string; kind: "static" | "app" }> => {
    assertSitesPublisher(args.secret);
    const handle = validateHandle(args.handle);

    const html = args.html ?? "";
    if (!html.trim()) throw new Error("html is empty");
    if (html.length > MAX_HTML_BYTES) throw new Error("html too large");

    const base = process.env.SITES_PUBLIC_BASE;
    if (!base) throw new Error("SITES_PUBLIC_BASE not configured");

    // Look up an existing site to enforce ownership + reuse its DB on republish.
    const existing = await ctx.runQuery(internal.sites.getByHandle, { handle });
    if (existing) {
      if (existing.userId && args.userId && existing.userId !== args.userId) {
        throw new Error(`handle "${handle}" is taken`);
      }
      if (existing.kind !== args.kind) {
        throw new Error(`handle "${handle}" already exists as kind "${existing.kind}"`);
      }
    }

    let tursoDbName: string | undefined;
    let tursoHostname: string | undefined;
    let tursoToken: string | undefined;
    const schemaSql = args.kind === "app" ? (args.schema ?? "") : undefined;

    if (args.kind === "app") {
      const cfg = tursoConfigFromEnv();
      if (existing?.tursoHostname && existing?.tursoToken && existing?.tursoDbName) {
        // Republish: reuse the existing isolated DB; re-apply schema idempotently.
        tursoDbName = existing.tursoDbName;
        tursoHostname = existing.tursoHostname;
        tursoToken = existing.tursoToken;
        if (schemaSql && schemaSql.trim()) {
          await applySchema(existing.tursoHostname, existing.tursoToken, schemaSql);
        }
      } else {
        const rand = crypto.randomUUID().slice(0, 8);
        const dbName = `s-${handle.slice(0, 40)}-${rand}`;
        const prov = await provisionApp(cfg, dbName, schemaSql ?? "");
        tursoDbName = prov.dbName;
        tursoHostname = prov.hostname;
        tursoToken = prov.token;
      }
    }

    await ctx.runMutation(internal.sites._upsert, {
      handle,
      userId: args.userId,
      kind: args.kind,
      title: args.title,
      html,
      tursoDbName,
      tursoHostname,
      tursoToken,
      schemaSql,
    });

    return { url: buildSiteUrl(base, handle), handle, kind: args.kind };
  },
});
