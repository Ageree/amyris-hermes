import { internalMutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";

// Personalized AI apps (Feature 5). One row per generated app maps a public slug to
// its Turso data plane. SECURITY (mirrors agentInstances.workerSecretRef): the row
// stores `dbTokenRef` = the env-var NAME of the data-plane token, NEVER the token —
// the httpAction reads process.env[dbTokenRef] at request time. These are internal
// functions: the Python/agent provisioner calls register after generate_app, and the
// /app/<slug> httpAction calls getBySlug. Neither is a public client surface.

// slug is reflected into the served URL + the page's API_BASE, so constrain it to a
// safe charset at the trust boundary (name is HTML-escaped at render time).
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

export const register = internalMutation({
  args: {
    userId: v.id("users"),
    slug: v.string(),
    name: v.string(),
    dbHostname: v.string(),
    dbName: v.string(),
    group: v.string(),
    tables: v.string(), // JSON manifest of the app's tables (provisioner output)
    dbTokenRef: v.string(), // env-var NAME of the Turso data-plane token (never the token)
  },
  returns: v.id("apps"),
  handler: async (ctx, args) => {
    if (!SLUG_RE.test(args.slug)) {
      throw new Error("slug must match ^[a-z0-9][a-z0-9-]{0,63}$");
    }
    if (!args.name.trim()) throw new Error("name is required");
    if (!args.dbHostname.trim()) throw new Error("dbHostname is required");
    if (!args.dbTokenRef.trim()) throw new Error("dbTokenRef is required");

    // The by_slug index is the serving key — reject a duplicate (check-then-insert in
    // one mutation is atomic under Convex OCC).
    const existing = await ctx.db
      .query("apps")
      .withIndex("by_slug", (q) => q.eq("slug", args.slug))
      .first();
    if (existing) throw new Error(`app slug already registered: ${args.slug}`);

    return await ctx.db.insert("apps", { ...args, createdAt: Date.now() });
  },
});

export const getBySlug = internalQuery({
  args: { slug: v.string() },
  // Narrowed to the serve-time fields (least exposure). dbTokenRef is only the env-var
  // NAME (safe to pass within the server); the httpAction resolves the actual token
  // from process.env and never returns it to the client.
  returns: v.union(
    v.object({
      name: v.string(),
      dbHostname: v.string(),
      dbTokenRef: v.string(),
    }),
    v.null(),
  ),
  handler: async (ctx, { slug }) => {
    const app = await ctx.db
      .query("apps")
      .withIndex("by_slug", (q) => q.eq("slug", slug))
      .first();
    if (!app) return null;
    return { name: app.name, dbHostname: app.dbHostname, dbTokenRef: app.dbTokenRef };
  },
});
